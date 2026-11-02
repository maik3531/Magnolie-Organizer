"""Native accepted file-receive operation (#330), no transport registration.

Blocking native I/O-lane methods only: no worker/thread/timer or PhoneStore is
constructed. Actual own-peer permission and serialized publication authority
must be supplied by the native controller. Physical publication alone remains
unreceipted; explicit original readback plus protected receipt commit confirms
a local save. Restart publication is repair-pending, never silently repeated.
"""
from dataclasses import dataclass
import threading

from magnolie_file_transfer import EncryptedTransferStage, ResumeLedger, TransferError
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from magnolie_publication_journal import ProtectedPublicationJournal
from magnolie_file_publish import NativeFilePublisher, inspect_publication_destination


class NativeReceiveStartError(TransferError):
    def __init__(self, job, cause):
        self.job = job
        self.cause_code = str(cause) if isinstance(cause, TransferError) else type(cause).__name__
        super().__init__("file_receive_start_pending:" + self.cause_code)


@dataclass(frozen=True)
class NativeReceiveProgress:
    owner: str
    verified_bytes: int
    checkpoint_verified_bytes: int
    total_bytes: int
    phase: str
    checkpoint_cleanup_pending: bool

    @property
    def is_saved_receipt(self):
        return False

    @property
    def grants_write_authority(self):
        return False


class NativeFileReceiveOperation:
    @classmethod
    def accept(cls, catalog, accepted, current_binding, seal, unseal, publication_gate):
        if (type(catalog) is not ProtectedTransferJobCatalog
                or not all(callable(value) for value in (current_binding, seal, unseal, publication_gate))):
            raise TransferError("file_receive_native_controller_required")
        job = catalog.reserve(accepted, current_binding)
        return cls(catalog, job, current_binding, seal, unseal, publication_gate, create=True)

    @classmethod
    def resume(cls, catalog, job, current_binding, seal, unseal, publication_gate):
        return cls(catalog, job, current_binding, seal, unseal, publication_gate, create=False)

    @classmethod
    def read_saved_receipts(cls, catalog, job, current_binding, seal, unseal):
        """Fresh native authority around historical protected file receipts.
        No source/cache/journal reopen or repeated publication is necessary.
        """
        if type(catalog) is not ProtectedTransferJobCatalog:
            raise TransferError("file_receive_native_controller_required")
        parent = catalog.require_reserved(job)
        job.accepted.verify(current_binding)
        with ProtectedTransferJobIndex(parent, job.accepted.manifest, job.accepted.binding, current_binding,
                seal, unseal, owner=job.owner, accepted=job.accepted) as index:
            result = index.saved_receipts()
        job.accepted.verify(current_binding)
        return result

    def __init__(self, catalog, job, current_binding, seal, unseal, publication_gate, *, create):
        if (type(catalog) is not ProtectedTransferJobCatalog or type(create) is not bool
                or not all(callable(value) for value in (current_binding, seal, unseal, publication_gate))):
            raise TransferError("file_receive_native_controller_required")
        parent = catalog.require_reserved(job)
        job.accepted.verify(current_binding)
        self._job = job
        self._accepted = job.accepted
        self._current = current_binding
        self._gate = threading.RLock()
        self._closed = False
        self._failed = False
        self._index = self._stage = self._journal = self._publisher = None
        self._lease = None
        self._phase = "receiving" if create else "receiving_publication_repair_pending"
        self._cleanup_pending = False
        self._chunks_since_checkpoint = 0
        self._published = None
        self._receipts = None
        try:
            self._index = ProtectedTransferJobIndex(parent, self._accepted.manifest, self._accepted.binding,
                current_binding, seal, unseal, owner=job.owner, create=create, accepted=self._accepted)
            self._lease = self._index.claim_operation()
            self._stage = EncryptedTransferStage(parent, self._accepted.manifest, self._accepted.binding,
                current_binding, seal, unseal, owner=job.owner)
            if create:
                self._stage.create()
                self._ledger = ResumeLedger(self._accepted.manifest, self._accepted.binding, current_binding)
                self._verified_bytes = 0
                self._checkpoint_bytes = -1
                self._checkpoint()
            else:
                head = self._index.read_head()
                if head is None:
                    raise TransferError("file_receive_initial_checkpoint_repair_required")
                self._ledger = self._stage.open_checkpoint(head)
                self._verified_bytes = self._ledger.verified_bytes
                self._checkpoint_bytes = self._verified_bytes
            self._journal = ProtectedPublicationJournal(parent, self._accepted.manifest, self._accepted.binding,
                dict(self._accepted.targets), seal, unseal, owner=job.owner, create=create)
            if create:
                self._publisher = NativeFilePublisher(self._accepted.destination.path, self._accepted.manifest,
                    self._accepted.binding, current_binding, publication_gate, owner=job.owner,
                    targets=dict(self._accepted.targets), journal=self._journal, accepted=self._accepted)
            self._set_checkpoint_batch()
        except Exception as error:
            self.close()  # Descriptors/worker lease only. All data/quota stay held.
            raise NativeReceiveStartError(job, error) from error

    def _set_checkpoint_batch(self):
        remaining = sum(len(self._ledger.missing(file.id)) for file in self._accepted.manifest.files)
        self._remaining_chunks = remaining
        head = self._index.snapshot()
        slots = self._index.MAX_REVISIONS - head.revision
        if remaining and slots < 1:
            raise TransferError("file_receive_checkpoint_history_repair_required")
        # Leave a final checkpoint slot. Large jobs must not consume the bounded
        # head history with a checkpoint for every individual 64-KiB chunk.
        divisor = max(1, slots - 1)
        self._checkpoint_batch = max(1, (remaining + divisor - 1) // divisor)

    def _require(self):
        if self._closed:
            raise TransferError("file_receive_closed")
        if self._failed:
            raise TransferError("file_receive_repair_pending")
        self._accepted.verify(self._current)

    def _checkpoint(self):
        verified = self._verified_bytes
        if verified == self._checkpoint_bytes:
            return
        expected = self._index.snapshot()
        result = self._stage.commit_checkpoint(self._ledger, lambda handle: self._index.publish_head(handle, expected),
            self._index.read_head, self._index.guard_head)
        if self._index.read_head() != result.handle:
            raise TransferError("file_receive_checkpoint_readback_failed")
        self._checkpoint_bytes = verified
        self._cleanup_pending = result.cleanup_pending
        self._chunks_since_checkpoint = 0

    def progress(self):
        with self._gate:
            self._require()
            return NativeReceiveProgress(self.job.owner, self._verified_bytes, self._checkpoint_bytes,
                self._accepted.manifest.total_bytes, self._phase, self._cleanup_pending)

    def acceptance_message(self, offer, *, now=None, message_id=None):
        """After actual reservation/lease/stage admission, not from wire paths.
        Building metadata is not secure-send completion or a saved receipt.
        """
        from magnolie_file_accept_message import create_acceptance
        with self._gate:
            self._require()
            if self._phase != 'receiving':
                raise TransferError('file_accept_receive_phase_changed')
            reply=create_acceptance(self._accepted,offer,self._current,now=now,message_id=message_id)
            self._require()
            return reply

    def receive_chunk(self, file_id, index, data):
        with self._gate:
            self._require()
            if self._published is not None or self._receipts is not None:
                raise TransferError("file_receive_already_physically_published")
            try:
                missing = index in self._ledger.missing(file_id)
                self._ledger.record(file_id, index, data, self._stage.write_chunk, self._stage.read_chunk)
                if missing:
                    self._verified_bytes += len(data)
                    self._remaining_chunks -= 1
                    self._chunks_since_checkpoint += 1
                complete = self._remaining_chunks == 0
                if self._chunks_since_checkpoint >= self._checkpoint_batch or complete:
                    self._checkpoint()
                return self.progress()
            except Exception:
                self._failed = True
                raise

    def checkpoint(self):
        with self._gate:
            self._require()
            try:
                self._checkpoint()
                self._set_checkpoint_batch()
                return self.progress()
            except Exception:
                self._failed = True
                raise

    def publish_completed(self):
        with self._gate:
            self._require()
            if self._receipts is not None:
                raise TransferError("file_receive_already_saved")
            if self._publisher is None:
                raise TransferError("file_receive_publication_repair_required")
            if self._published is not None:
                # Recheck original native target evidence; do not save again.
                return tuple(self._publisher.publish(file.id, self._ledger, self._stage.read_chunk)
                    for file in self._accepted.manifest.files)
            if any(self._ledger.missing(file.id) for file in self._accepted.manifest.files):
                raise TransferError("file_receive_incomplete_manifest")
            try:
                self._checkpoint()
                result = tuple(self._publisher.publish(file.id, self._ledger, self._stage.read_chunk)
                    for file in self._accepted.manifest.files)
                self._published = result
                self._phase = "physically_published_unreceipted"
                return result
            except Exception:
                self._failed = True
                raise

    def inspect_publication(self, file_id):
        with self._gate:
            self._require()
            return inspect_publication_destination(self._accepted.destination.path, self._accepted.manifest,
                self._accepted.binding, dict(self._accepted.targets), self._journal, file_id, self._current)

    def commit_saved_receipts(self):
        """Explicit local save/recovery step, not a transport or book ACK.
        May recover actual original files without adopting/repeating publication.
        """
        with self._gate:
            self._require()
            try:
                result = tuple(self._index.commit_saved_file(self._journal, file.id, self._lease)
                    for file in self._accepted.manifest.files)
                self._receipts = result
                self._phase = "saved_locally"
                return result
            except Exception:
                self._failed = True
                raise

    def close(self):
        with self._gate:
            if self._closed:
                return
            self._closed = True
            # Index/lease closes last, after all actual native I/O objects ended.
            failure = None
            for value in (self._publisher, self._journal, self._stage, self._index):
                if value is not None:
                    try:
                        value.close()
                    except Exception as error:
                        if failure is None:
                            failure = error
            if failure is not None:
                raise failure

    @property
    def job(self):
        return self._job

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
