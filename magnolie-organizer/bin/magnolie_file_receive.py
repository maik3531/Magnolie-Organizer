"""Native accepted file-receive operation (#330), no transport registration.

Blocking native I/O-lane methods only: no worker/thread/timer or PhoneStore is
constructed. Actual own-peer permission and serialized publication authority
must be supplied by the native controller. Physical publication alone remains
unreceipted; explicit original readback plus protected receipt commit confirms
a local save. Restart publication requires a positive native unpublished-END
proof consumed by the catalog; otherwise it remains repair-pending.
"""
from dataclasses import dataclass
import os
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
    def accept(cls, catalog, accepted, current_binding, seal, unseal, publication_gate, *, media_history=None,expected_jobs=None):
        if (type(catalog) is not ProtectedTransferJobCatalog
                or not all(callable(value) for value in (current_binding, seal, unseal, publication_gate))):
            raise TransferError("file_receive_native_controller_required")
        if media_history is not None:
            from magnolie_file_media_history import NativeMediaHistory
            if type(media_history) is not NativeMediaHistory:raise TransferError('file_receive_native_media_history_required')
            NativeMediaHistory.parse(media_history.wire(),accepted)
        job = catalog.reserve(accepted, current_binding,expected_jobs=expected_jobs)
        return cls(catalog, job, current_binding, seal, unseal, publication_gate, create=True,media_history=media_history)

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
        parent = catalog.require_recorded(job)
        job.accepted.verify(current_binding)
        with ProtectedTransferJobIndex(parent, job.accepted.manifest, job.accepted.binding, current_binding,
                seal, unseal, owner=job.owner, accepted=job.accepted) as index:
            result = index.saved_receipts()
        job.accepted.verify(current_binding)
        return result

    @classmethod
    def read_media_history(cls, catalog, job, current_binding, seal, unseal):
        """Original protected association only, no stage/publication reopen."""
        if type(catalog) is not ProtectedTransferJobCatalog:
            raise TransferError('file_receive_native_controller_required')
        parent=catalog.require_recorded(job)
        job.accepted.verify(current_binding)
        with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,current_binding,
                seal,unseal,owner=job.owner,accepted=job.accepted) as index:
            result=index.media_history
        job.accepted.verify(current_binding)
        return result

    def __init__(self, catalog, job, current_binding, seal, unseal, publication_gate, *, create,media_history=None):
        if (type(catalog) is not ProtectedTransferJobCatalog or type(create) is not bool
                or not all(callable(value) for value in (current_binding, seal, unseal, publication_gate))):
            raise TransferError("file_receive_native_controller_required")
        parent = catalog.require_reserved(job)
        job.accepted.verify(current_binding)
        self._job = job
        self._catalog = catalog
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
        self._unpublished_end = None
        try:
            self._index = ProtectedTransferJobIndex(parent, self._accepted.manifest, self._accepted.binding,
                current_binding, seal, unseal, owner=job.owner, create=create, accepted=self._accepted,media_history=media_history)
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
            else:
                self._publisher=catalog.renew_unpublished_publication(self,publication_gate)
                if self._publisher is not None:self._phase='receiving'
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
            if self._phase not in ('receiving', 'receiving_publication_repair_pending'):
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

    def chunk_request_message(self,file_id,index,*,now=None,message_id=None):
        from magnolie_file_chunk_message import create_request
        with self._gate:
            self._require()
            if self._published is not None or self._receipts is not None:
                raise TransferError('file_receive_already_physically_published')
            result=create_request(self._accepted,self._current,file_id,index,now=now,message_id=message_id)
            self._require()
            return result

    def receive_chunk_message(self,message,request,*,now=None):
        from magnolie_file_chunk_message import parse_chunk
        with self._gate:
            self._require()
            data=parse_chunk(message,request,self._accepted,self._current,now=now)
            body=request['body']
            return self.receive_chunk(body['file_id'],body['chunk_index'],data)

    def next_chunk_request_message(self,*,now=None,message_id=None):
        """One explicit native coordinator step, not a timer or worker loop.
        Resume construction already authenticated the checkpoint and read back
        every claimed staged chunk. Only that native ledger chooses the member.
        None means no missing source bytes, never saved/published/sync success.
        """
        with self._gate:
            self._require()
            if self._published is not None or self._receipts is not None:
                raise TransferError('file_receive_already_physically_published')
            for file in self._accepted.manifest.files:
                missing=self._ledger.missing(file.id)
                if missing:
                    return self.chunk_request_message(file.id,missing[0],now=now,message_id=message_id)
            self._require()
            return None

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

    def saved_receipt_message(self,*,now=None,message_id=None):
        """Fresh protected readback of complete historical local receipts only.
        No publication, re-publication, receipt construction or quota retirement.
        """
        from magnolie_file_saved_message import create_saved
        with self._gate:
            self._require()
            receipts=self._index.saved_receipts()
            result=create_saved(self._accepted,receipts,self._current,self.job.owner,now=now,message_id=message_id)
            self._require()
            return result

    def observe_saved_photo(self, file_id):
        """Actual current target bytes, not historical receipt presence.
        No baseline, tombstone, replacement right or quota release is created.
        """
        from magnolie_photo_target import observe_saved_target
        with self._gate:
            self._require()
            receipt = next((item for item in self._index.saved_receipts() if item.file_id == file_id), None)
            if receipt is None:
                raise TransferError('file_receive_saved_photo_receipt_required')
            result = observe_saved_target(self._accepted, receipt, self._current)
            self._require()
            if receipt not in self._index.saved_receipts():
                raise TransferError('file_receive_saved_photo_receipt_changed')
            return result

    def close(self):
        with self._gate:
            if self._closed:
                return
            evidence=None
            if not self._failed and self._publisher is not None and not self._publisher._attempted:
                try:
                    self._index._require_end_worker(self._lease)
                    self._publisher._directories()
                    self._journal.require_new_operation(self._accepted.manifest,self._accepted.binding,
                        dict(self._accepted.targets),self.job.owner)
                    head=self._index.snapshot()
                    if head is not None and not self._publisher._cache_entries() and self._journal._entries()=={'owner.enc'}:
                        evidence=dict(accepted_sha256=self._accepted.fingerprint,checkpoint_sha256=head.protected_sha256,
                            index_key=list(self._index._root_key),database_key=list(self._index._database_key),
                            stage_key=list(ProtectedTransferJobCatalog._key(os.fstat(self._stage._root_fd))),
                            journal_key=list(self._journal._root_key),publication_key=list(self._publisher._cache_key))
                except Exception:
                    pass # Revocation/uncertainty closes resources, never mints END evidence.
            self._closed = True
            # Index/lease closes last, after all actual native I/O objects ended.
            failure = None
            for value in (self._publisher, self._journal, self._stage):
                if value is not None:
                    try:
                        value.close()
                    except Exception as error:
                        if failure is None:
                            failure = error
            try:
                if evidence is not None and failure is None:
                    self._unpublished_end=evidence
                    self._catalog.record_unpublished_end(self,evidence)
            except Exception as error:
                failure=error
            finally:
                if self._index is not None:
                    try:self._index.close()
                    except Exception as error:
                        if failure is None:failure=error
            if failure is not None:
                raise failure

    @property
    def job(self):
        return self._job

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
