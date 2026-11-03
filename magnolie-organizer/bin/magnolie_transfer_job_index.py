"""Protected native checkpoint heads and separate local file-save receipts.

Explicitly reserved per-operation private SQLite index. No personal database,
key generation, wire dispatcher, destination publication or automatic restore.
SQLite FULL commits and native CAS serialize checkpoint heads; source bytes
must still be re-read by EncryptedTransferStage.open_checkpoint on restart.
Only explicit original-destination readback can create a saved file receipt;
neither checkpoint heads nor file receipts are Notes/Organizer book SaveACKs.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import weakref

from magnolie_file_transfer import FileManifest, NativeTransferBinding, TransferError, TransferStageHandle
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_receipt import NativeSavedFileReceipt
from magnolie_photo_mapping_receipt import SavedPhotoMappingReceipt
from magnolie_file_publish import inspect_publication_destination
from magnolie_publication_journal import ProtectedPublicationJournal


_ROOT_GATES = weakref.WeakValueDictionary()
_ACTIVE_OPERATIONS = weakref.WeakValueDictionary()
_ROOT_GATES_LOCK = threading.Lock()
_LOCAL = threading.local()


@dataclass(frozen=True)
class NativeCheckpointHead:
    revision: int
    handle: TransferStageHandle
    protected_sha256: str

    def __post_init__(self):
        if (type(self.revision) is not int or not 1 <= self.revision < 2**31
                or type(self.handle) is not TransferStageHandle or type(self.protected_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.protected_sha256) is None):
            raise TransferError("transfer_job_index_invalid_head")

    @property
    def is_saved_receipt(self):
        return False

    @property
    def grants_write_authority(self):
        return False


class ProtectedTransferJobIndex:
    PREFIX = "file-job-index-"
    MAX_REVISIONS = 128
    MAX_DATABASE_BYTES = 4 * 1024 * 1024
    MAX_RECORD_BYTES = 4096
    MAX_OWNER_BYTES = 2 * 1024 * 1024
    MAX_RECEIPT_BYTES = 16 * 1024
    _SCHEMA = {"meta": "CREATE TABLE meta(id INTEGER PRIMARY KEY CHECK(id=1),payload BLOB NOT NULL)",
        "heads": "CREATE TABLE heads(revision INTEGER PRIMARY KEY,payload BLOB NOT NULL)"}
    _RECEIPT_SCHEMA = "CREATE TABLE receipts(file_id TEXT PRIMARY KEY,payload BLOB NOT NULL)"
    _MAPPING_SCHEMA = "CREATE TABLE mapping_receipt(id INTEGER PRIMARY KEY CHECK(id=1),payload BLOB NOT NULL)"

    def __init__(self, parent, manifest, binding, current_binding, seal, unseal, *, owner, create=False, accepted=None, media_history=None):
        if (type(manifest) is not FileManifest or type(binding) is not NativeTransferBinding
                or (manifest.sender_id, manifest.receiver_id) != (binding.sender_id, binding.receiver_id)
                or type(owner) is not str or re.fullmatch(r"[0-9a-f]{32}", owner) is None
                or type(create) is not bool or not all(callable(value) for value in (current_binding, seal, unseal))):
            raise TransferError("transfer_job_index_native_context_required")
        self._context = {"format": 1, "owner": owner, "manifest_sha256": manifest.fingerprint, "binding": vars(binding)}
        if accepted is not None:
            if type(accepted) is not NativeAcceptedTransfer or accepted.manifest != manifest or accepted.binding != binding:
                raise TransferError("transfer_job_index_acceptance_mismatch")
            self._context = dict(self._context, format=2, accepted=accepted.wire())
        if media_history is not None:
            if type(media_history) is not NativeMediaHistory:
                raise TransferError('transfer_job_index_native_media_history_required')
            media_history=NativeMediaHistory.parse(media_history.wire(),accepted)
            self._context=dict(self._context,format=3,media_history=media_history.wire())
        self._accepted = accepted
        self._media_history = media_history
        self._expected_manifest = manifest
        self._binding, self._current = binding, current_binding
        self._seal, self._unseal = seal, unseal
        self._domain = "magnolie-transfer-job-index-v1/" + owner + "/" + manifest.fingerprint + "/"
        self._gate = threading.RLock()
        self._parent = Path(parent)
        if not self._parent.is_absolute() or self._parent.resolve(strict=True) != self._parent:
            raise TransferError("transfer_job_index_canonical_parent_required")
        self._ancestors = [(path, self._key(os.lstat(path))) for path in (self._parent, *self._parent.parents)]
        self._parent_fd = os.open(self._parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._root_fd = self._database_fd = self._lock_fd = None
        self._db = None
        self._closed = False
        self._uncertain = False
        self._operation_lease = None
        self._last = None
        self._name = self.PREFIX + owner
        try:
            self._private(os.fstat(self._parent_fd), directory=True)
            if create:
                self._fresh()
                os.mkdir(self._name, mode=0o700, dir_fd=self._parent_fd)
            self._root_fd = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent_fd)
            self._root_key = self._key(os.fstat(self._root_fd))
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            self._lock_fd = os.open("index.lock", flags, 0o600, dir_fd=self._root_fd)
            self._lock_key = self._key(os.fstat(self._lock_fd))
            self._database_fd = os.open("index.sqlite", flags, 0o600, dir_fd=self._root_fd)
            self._database_key = self._key(os.fstat(self._database_fd))
            with _ROOT_GATES_LOCK:
                self._root_gate = _ROOT_GATES.setdefault(self._root_key, threading.RLock())
            with self._locked():
                path = self._parent / self._name / "index.sqlite"
                self._db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5, check_same_thread=False)
                self._db.execute("PRAGMA busy_timeout=5000")
                if create:
                    self._db.execute("PRAGMA journal_mode=DELETE")
                    self._db.execute("PRAGMA synchronous=FULL")
                    with self._db:
                        self._fresh()
                        for sql in self._SCHEMA.values():
                            self._db.execute(sql)
                        self._db.execute("PRAGMA user_version=1")
                        payload = {"context": self._context, "root_key": self._root_key,
                            "database_key": self._database_key, "lock_key": self._lock_key}
                        self._db.execute("INSERT INTO meta VALUES(1,?)", (self._protect(payload, "owner"),))
                        self._fresh()
                    os.fsync(self._root_fd)
                    os.fsync(self._parent_fd)
                else:
                    # No CREATE TABLE/IF NOT EXISTS, replacement database or
                    # unattended crash-journal adoption on reopen.
                    self._db.execute("PRAGMA synchronous=FULL")
                self._schema()
                self._owner_cipher = None
                self._owner()
                self._snapshot()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _key(value):
        return value.st_dev, value.st_ino

    @staticmethod
    def _private(value, *, directory=False):
        if (not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
                or value.st_uid != os.geteuid() or value.st_mode & 0o077 or not directory and value.st_nlink != 1):
            raise TransferError("transfer_job_index_unsafe_entry")

    def _fresh(self):
        if self._current() != self._binding:
            raise TransferError("transfer_job_index_binding_revoked")
        if self._accepted is not None:
            self._accepted.verify(self._current)

    def _directories(self):
        if self._closed:
            raise TransferError("transfer_job_index_closed")
        for path, key in self._ancestors:
            value = os.lstat(path)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != key:
                raise TransferError("transfer_job_index_parent_changed")
        parent = os.fstat(self._parent_fd)
        self._private(parent, directory=True)
        if self._key(parent) != self._ancestors[0][1]:
            raise TransferError("transfer_job_index_parent_changed")
        root = os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
        self._private(root, directory=True)
        if self._key(root) != self._root_key or self._key(os.fstat(self._root_fd)) != self._root_key:
            raise TransferError("transfer_job_index_root_changed")
        for name, fd, key in (("index.lock", self._lock_fd, self._lock_key), ("index.sqlite", self._database_fd, self._database_key)):
            named = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            self._private(named)
            self._private(os.fstat(fd))
            if self._key(named) != key or self._key(os.fstat(fd)) != key:
                raise TransferError("transfer_job_index_original_changed")
        if os.fstat(self._database_fd).st_size > self.MAX_DATABASE_BYTES:
            raise TransferError("transfer_job_index_size_limit")
        with os.scandir(self._root_fd) as entries:
            for entry in entries:
                if entry.name not in {"index.lock", "index.sqlite", "index.sqlite-journal"}:
                    raise TransferError("transfer_job_index_unknown_entry_preserved")
                if entry.name == "index.sqlite-journal" and (self._db is None or not self._db.in_transaction):
                    # A leftover sidecar is not authenticated original evidence.
                    # Preserve it for explicit native repair, rather than let a
                    # fresh SQLite connection recover/delete an unknown file.
                    raise TransferError("transfer_job_index_journal_repair_required")
                value = entry.stat(follow_symlinks=False)
                self._private(value)
                if value.st_size > self.MAX_DATABASE_BYTES:
                    raise TransferError("transfer_job_index_size_limit")

    @contextmanager
    def _locked(self):
        with self._gate, self._root_gate:
            active = _ACTIVE_OPERATIONS.get(self._root_key)
            if active is not None and active is not self:
                raise TransferError("transfer_job_index_operation_busy")
            self._directories()
            held = getattr(_LOCAL, "held", None)
            if held is None:
                held = _LOCAL.held = set()
            first = self._root_key not in held
            if first:
                if self._operation_lease is None:
                    try:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise TransferError("transfer_job_index_operation_busy") from error
                held.add(self._root_key)
            try:
                self._directories()
                yield
                self._directories()
            finally:
                if first:
                    held.remove(self._root_key)
                    if self._operation_lease is None:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

    def _protect(self, value, suffix):
        plain = self._json(value)
        maximum = self._record_limit(suffix)
        if len(plain) > maximum:
            raise TransferError("transfer_job_index_record_size")
        blob = self._seal(plain, self._domain + suffix)
        if type(blob) is not bytes or not len(plain) <= len(blob) <= len(plain) + 128 or len(blob) > maximum + 128:
            raise TransferError("transfer_job_index_invalid_protection")
        return blob

    def _open(self, blob, suffix):
        maximum = self._record_limit(suffix)
        if type(blob) is not bytes or not 1 <= len(blob) <= maximum + 128:
            raise TransferError("transfer_job_index_invalid_record")
        plain = self._unseal(blob, self._domain + suffix)
        if type(plain) is not bytes or len(plain) > maximum:
            raise TransferError("transfer_job_index_invalid_protection")
        value = json.loads(plain)
        if self._json(value) != plain:
            raise TransferError("transfer_job_index_noncanonical_record")
        return value

    def _record_limit(self, suffix):
        return self.MAX_OWNER_BYTES if suffix in ("owner","mapping-receipt") else self.MAX_RECEIPT_BYTES if suffix.startswith("receipt/") else self.MAX_RECORD_BYTES

    def _schema(self):
        actual = dict(self._db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        wanted = (self._SCHEMA if version == 1 else dict(self._SCHEMA, receipts=self._RECEIPT_SCHEMA)
            if version == 2 else dict(self._SCHEMA, receipts=self._RECEIPT_SCHEMA,mapping_receipt=self._MAPPING_SCHEMA) if version == 3 else None)
        if wanted is None or actual != wanted:
            raise TransferError("transfer_job_index_unknown_schema")
        if (self._db.execute("PRAGMA journal_mode").fetchone() != ("delete",)
                or self._db.execute("PRAGMA synchronous").fetchone() != (2,)):
            raise TransferError("transfer_job_index_unsupported_journal")
        self._schema_version = version

    def _owner(self):
        self._schema()
        rows = self._db.execute("SELECT id,payload FROM meta LIMIT 2").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise TransferError("transfer_job_index_owner_missing")
        blob = rows[0][1]
        value = self._open(blob, "owner")
        if (type(value) is dict and type(value.get("context")) is dict
                and type(value["context"].get("format")) is int
                and value["context"].get("format") in (2,3,4) and value['context']['format'] > self._context['format']):
            stored = value["context"]
            base = {key: item for key, item in stored.items() if key not in ("media_history","mapping_receipt_sha256")}
            if 'accepted' not in stored:
                raise TransferError("transfer_job_index_acceptance_mismatch")
            accepted = NativeAcceptedTransfer.parse(stored["accepted"])
            if accepted.manifest != self._expected_manifest or accepted.binding != self._binding:
                raise TransferError("transfer_job_index_acceptance_mismatch")
            if self._accepted is not None and self._accepted != accepted:
                raise TransferError('transfer_job_index_acceptance_mismatch')
            wanted_base=dict({key:item for key,item in self._context.items() if key not in ('media_history','mapping_receipt_sha256')},format=2,accepted=accepted.wire())
            if dict(base,format=2)!=wanted_base:
                raise TransferError('transfer_job_index_acceptance_mismatch')
            # Parsing authenticated metadata does not check a live destination
            # or grant. Mutation still goes through _fresh/accepted.verify.
            wanted_context = wanted_base
            if stored['format']>=3:
                history=NativeMediaHistory.parse(stored.get('media_history'),accepted)
                if self._media_history is not None and self._media_history!=history:
                    raise TransferError('transfer_job_index_media_history_changed')
                wanted_context=dict(wanted_context,format=3,media_history=history.wire())
                if stored['format']==4:
                    digest=stored.get('mapping_receipt_sha256')
                    if type(digest) is not str or re.fullmatch('[0-9a-f]{64}',digest) is None:
                        raise TransferError('transfer_job_index_mapping_receipt_required')
                    wanted_context=dict(wanted_context,format=4,mapping_receipt_sha256=digest)
            else:
                history=None
        else:
            accepted = self._accepted
            wanted_context = self._context
            history = self._media_history
        wanted = {"context": wanted_context, "root_key": list(self._root_key),
            "database_key": list(self._database_key), "lock_key": list(self._lock_key)}
        if value != wanted or self._owner_cipher is not None and self._owner_cipher != blob:
            raise TransferError("transfer_job_index_owner_changed")
        self._context, self._accepted, self._media_history = wanted_context, accepted, history
        self._owner_cipher = blob
        if (self._context['format']==4)!=(self._schema_version==3):
            raise TransferError('transfer_job_index_mapping_receipt_schema_changed')
        if self._context['format']==4:
            rows=self._db.execute('SELECT id,payload FROM mapping_receipt LIMIT 2').fetchall()
            if (len(rows)!=1 or rows[0][0]!=1 or type(rows[0][1]) is not bytes
                    or sha256(rows[0][1]).hexdigest()!=self._context['mapping_receipt_sha256']):
                raise TransferError('transfer_job_index_mapping_receipt_changed')

    @property
    def accepted_transfer(self):
        with self._locked():
            self._owner()
            return self._accepted  # None for legacy heads; never guessed defaults.

    @property
    def media_history(self):
        with self._locked():
            self._owner()
            return self._media_history  # Historical only; absence is not inferred.

    def _snapshot(self):
        self._schema()
        self._owner()
        rows = self._db.execute("SELECT revision,payload FROM heads ORDER BY revision LIMIT ?", (self.MAX_REVISIONS + 1,)).fetchall()
        if len(rows) > self.MAX_REVISIONS:
            raise TransferError("transfer_job_index_revision_limit")
        latest = None
        previous = ""
        hashes = set()
        for expected, (revision, blob) in enumerate(rows, 1):
            value = self._open(blob, "head/" + str(revision))
            if (type(value) is not dict or set(value) != {"format", "revision", "previous", "owner", "checkpoint"}
                    or type(value["format"]) is not int or value["format"] != 1 or revision != expected
                    or type(value["revision"]) is not int or value["revision"] != revision or value["previous"] != previous):
                raise TransferError("transfer_job_index_invalid_head_chain")
            handle = TransferStageHandle(value["owner"], value["checkpoint"])
            if handle.owner != self._context["owner"]:
                raise TransferError("transfer_job_index_wrong_stage_owner")
            previous = sha256(blob).hexdigest()
            hashes.add(previous)
            latest = NativeCheckpointHead(revision, handle, previous)
        if self._last is not None and (latest is None or latest.revision < self._last.revision
                or latest.revision == self._last.revision and latest != self._last):
            raise TransferError("transfer_job_index_head_rollback")
        self._last = latest
        self._head_hashes = frozenset(hashes)
        return latest

    def snapshot(self):
        """Protected local inspection, also after revocation; no source access."""
        with self._locked():
            return self._snapshot()

    def read_head(self):
        value = self.snapshot()
        return value.handle if value is not None else None

    def publish_head(self, handle, expected):
        with self._locked():
            if self._uncertain:
                raise TransferError("transfer_job_index_repair_pending")
            if self._root_key in getattr(_LOCAL, "actions", set()):
                raise TransferError("transfer_job_index_head_action_active")
            self._fresh()
            if (type(handle) is not TransferStageHandle or handle.owner != self._context["owner"]
                    or expected is not None and type(expected) is not NativeCheckpointHead):
                raise TransferError("transfer_job_index_invalid_head")
            observed = self._snapshot()
            if observed != expected:
                raise TransferError("transfer_job_index_head_cas_failed")
            revision = observed.revision + 1 if observed else 1
            if revision > self.MAX_REVISIONS:
                raise TransferError("transfer_job_index_revision_limit")
            blob = self._protect({"format": 1, "revision": revision,
                "previous": observed.protected_sha256 if observed else "", "owner": handle.owner, "checkpoint": handle.checkpoint}, "head/" + str(revision))
            self._fresh()
            self._uncertain = True
            with self._db:
                self._db.execute("INSERT INTO heads VALUES(?,?)", (revision, blob))
                self._fresh()
            os.fsync(self._root_fd)
            self._fresh()
            result = self._snapshot()
            if result != NativeCheckpointHead(revision, handle, sha256(blob).hexdigest()):
                raise TransferError("transfer_job_index_head_readback_failed")
            self._uncertain = False
            return result

    def guard_head(self, expected, action):
        with self._locked():
            self._fresh()
            if self._uncertain or type(expected) is not TransferStageHandle or self.read_head() != expected:
                raise TransferError("transfer_job_index_head_changed")
            actions = getattr(_LOCAL, "actions", None)
            if actions is None:
                actions = _LOCAL.actions = set()
            if self._root_key in actions:
                raise TransferError("transfer_job_index_nested_head_action")
            actions.add(self._root_key)
            try:
                action()
                self._fresh()
                if self.read_head() != expected:
                    raise TransferError("transfer_job_index_head_changed")
            finally:
                actions.remove(self._root_key)

    def claim_operation(self):
        """Exact native worker ownership, held across calls/threads until its
        actual end. This is not file/grant/publication or wire authority.
        Competing processes fail busy instead of starting another receiver.
        """
        if self._root_key in getattr(_LOCAL, "held", set()):
            raise TransferError("transfer_job_index_operation_busy")
        with self._locked():
            self._fresh()
            self._snapshot()
            if self._uncertain or self._operation_lease is not None or self._root_key in getattr(_LOCAL, "actions", set()):
                raise TransferError("transfer_job_index_operation_busy")
            self._operation_lease = object()
            _ACTIVE_OPERATIONS[self._root_key] = self
            return self._operation_lease

    def _require_receipt_worker(self, lease):
        if (lease is None or lease is not self._operation_lease or _ACTIVE_OPERATIONS.get(self._root_key) is not self
                or self._accepted is None):
            raise TransferError("transfer_job_index_receipt_worker_required")
        if self._uncertain:
            raise TransferError("transfer_job_index_repair_pending")
        self._fresh()

    def _require_end_worker(self,lease):
        """Exact still-owned metadata lease after I/O END, even after revocation.

        This does not renew a source, target, checkpoint-write or receipt grant.
        A native closed-owner proof must be recordable during orderly teardown.
        """
        if (lease is None or lease is not self._operation_lease or _ACTIVE_OPERATIONS.get(self._root_key) is not self
                or self._accepted is None or self._uncertain):
            raise TransferError('transfer_job_index_end_worker_required')
        self._directories();self._owner()

    def _enable_receipts(self):
        self._snapshot()
        if self._schema_version >= 2:
            return
        self._uncertain = True
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(self._RECEIPT_SCHEMA)
            self._db.execute("PRAGMA user_version=2")
            self._fresh()
        os.fsync(self._root_fd)
        self._fresh()
        self._snapshot()
        self._uncertain = False

    def saved_receipts(self):
        """Authenticated historical saves only, not current presence/grants."""
        with self._locked():
            if self._uncertain or self._db.in_transaction:
                raise TransferError("transfer_job_index_repair_pending")
            self._snapshot()
            if self._schema_version == 1:
                return ()
            if self._accepted is None:
                raise TransferError("transfer_job_index_receipt_context_required")
            rows = self._db.execute("SELECT file_id,payload FROM receipts ORDER BY file_id LIMIT 129").fetchall()
            if len(rows) > len(self._accepted.manifest.files):
                raise TransferError("transfer_job_index_receipt_count_mismatch")
            result = []
            for file_id, blob in rows:
                if type(file_id) is not str or re.fullmatch(r"[0-9a-f]{32}", file_id) is None:
                    raise TransferError("transfer_job_index_invalid_receipt_member")
                value = self._open(blob, "receipt/" + file_id)
                result.append(NativeSavedFileReceipt.parse(value, self._accepted, self._context["owner"], file_id,
                    sha256(blob).hexdigest(), self._head_hashes))
            if result:
                # A reopened receipt may follow a lost post-commit directory
                # sync/ACK. Re-establish physical DB+directory durability before
                # exposing saved evidence; never certify an open transaction.
                os.fsync(self._database_fd)
                os.fsync(self._root_fd)
            return tuple(result)

    def saved_mapping_receipt(self):
        """Historical mapping evidence; no destination presence or wire authority."""
        with self._locked():
            receipts=self.saved_receipts()
            if self._context['format']!=4:return None
            blob=self._db.execute('SELECT payload FROM mapping_receipt WHERE id=1').fetchone()[0]
            value=SavedPhotoMappingReceipt.parse(self._open(blob,'mapping-receipt'),self._accepted,
                self._media_history,self._context['owner'],receipts)
            os.fsync(self._database_fd);os.fsync(self._root_fd)
            self._directories();self._owner()
            return value

    def commit_saved_mapping(self, records, store, lease):
        """Owned explicit schema upgrade and one immutable post-mapping receipt."""
        with self._locked():
            self._require_receipt_worker(lease)
            existing=self.saved_mapping_receipt()
            if existing is not None:return existing
            if self._schema_version!=2 or self._media_history is None:
                raise TransferError('transfer_job_index_mapping_receipt_context_required')
            evidence=SavedPhotoMappingReceipt.capture(self._accepted,self._media_history,self._context['owner'],
                self.saved_receipts(),records,store)
            blob=self._protect(evidence.wire(),'mapping-receipt')
            context=dict(self._context,format=4,mapping_receipt_sha256=sha256(blob).hexdigest())
            owner=self._protect(dict(context=context,root_key=self._root_key,database_key=self._database_key,
                lock_key=self._lock_key),'owner')
            self._require_receipt_worker(lease);self._snapshot()
            self._uncertain=True
            with self._db:
                self._db.execute('BEGIN IMMEDIATE')
                self._db.execute(self._MAPPING_SCHEMA)
                self._db.execute('INSERT INTO mapping_receipt VALUES(1,?)',(blob,))
                self._db.execute('UPDATE meta SET payload=? WHERE id=1',(owner,))
                self._db.execute('PRAGMA user_version=3')
                self._fresh()
            os.fsync(self._database_fd);os.fsync(self._root_fd);self._fresh()
            self._context=context;self._owner_cipher=owner
            self._snapshot()
            # Leave the object fenced on any post-commit readback failure.
            self._uncertain=False
            try:
                result=self.saved_mapping_receipt()
                if result!=evidence:raise TransferError('transfer_job_index_mapping_receipt_readback_failed')
                self._fresh();return result
            except BaseException:
                self._uncertain=True;raise

    def commit_saved_file(self, journal, file_id, lease):
        """Explicit native save/recovery: authenticate original journal and
        freshly read actual original destination bytes before durable receipt.
        No file or journal write is performed and no unknown target is adopted.
        """
        with self._locked():
            self._require_receipt_worker(lease)
            if type(journal) is not ProtectedPublicationJournal:
                raise TransferError("transfer_job_index_native_journal_required")
            file = next((file for file in self._accepted.manifest.files if file.id == file_id), None)
            if file is None:
                raise TransferError("transfer_job_index_unknown_receipt_member")
            for existing in self.saved_receipts():
                if existing.file_id == file_id:
                    return existing  # Keep later PC edits/deletions; never re-save.
            journal.require_context(self._accepted.manifest, self._binding, dict(self._accepted.targets))
            evidence = journal.inspect(file_id)
            if evidence is None:
                raise TransferError("transfer_job_index_missing_publication_evidence")
            observed = inspect_publication_destination(self._accepted.destination.path, self._accepted.manifest, self._binding,
                dict(self._accepted.targets), journal, file_id, self._current)
            if observed.state != "original_present" or journal.inspect(file_id) != evidence:
                raise TransferError("transfer_job_index_original_destination_unconfirmed")
            head = self._snapshot()
            if head is None:
                raise TransferError("transfer_job_index_missing_source_checkpoint")
            self._require_receipt_worker(lease)
            self._enable_receipts()  # Explicit owned transactional schema 1→2.
            receipt = NativeSavedFileReceipt(self._context["owner"], self._accepted.manifest.fingerprint,
                self._accepted.fingerprint, file_id, dict(self._accepted.targets)[file_id], file.size, file.sha256,
                (evidence.witness.source_device, evidence.witness.source_inode), evidence.witness.parent_keys,
                evidence.phase, evidence.protected_record_sha256, head.protected_sha256, "")
            blob = self._protect(receipt.wire(), "receipt/" + file_id)
            self._fresh()
            self._uncertain = True
            with self._db:
                self._db.execute("INSERT INTO receipts VALUES(?,?)", (file_id, blob))
                self._fresh()
            os.fsync(self._root_fd)
            self._fresh()
            self._snapshot()
            row = self._db.execute("SELECT payload FROM receipts WHERE file_id=?", (file_id,)).fetchone()
            if row is None or row[0] != blob:
                raise TransferError("transfer_job_index_receipt_readback_failed")
            value = self._open(row[0], "receipt/" + file_id)
            result = NativeSavedFileReceipt.parse(value, self._accepted, self._context["owner"], file_id,
                sha256(row[0]).hexdigest(), self._head_hashes)
            self._fresh()
            self._uncertain = False
            return result

    def release_operation(self, lease):
        """Actual native worker END only; cancellation/transport ACK is not END."""
        with self._gate, self._root_gate:
            if (lease is None or lease is not self._operation_lease or self._root_key in getattr(_LOCAL, "held", set())):
                raise TransferError("transfer_job_index_invalid_operation_end")
            self._release_operation()

    def _release_operation(self):
        if self._operation_lease is not None:
            if _ACTIVE_OPERATIONS.get(self._root_key) is self:
                del _ACTIVE_OPERATIONS[self._root_key]
            self._operation_lease = None
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    def close(self):
        with self._gate:
            if self._closed:
                return
            self._closed = True
            if self._db is not None:
                self._db.close()
            if self._operation_lease is not None:
                with self._root_gate:
                    self._release_operation()
            for fd in (self._database_fd, self._lock_fd, self._root_fd, self._parent_fd):
                if fd is not None:
                    os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
