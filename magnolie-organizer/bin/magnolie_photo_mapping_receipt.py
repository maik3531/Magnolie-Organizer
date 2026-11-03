"""Exact historical save→mapping evidence, never current presence or authority."""
from dataclasses import dataclass
from hashlib import sha256
import re

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_receipt import NativeSavedFileReceipt
from magnolie_file_transfer import TransferError
from magnolie_photo_mapping_witness import PhotoMappingStoreCheckpoint
from magnolie_telefon import canonical


@dataclass(frozen=True)
class SavedMappingEntry:
    file_id: str
    photo_id: str
    saved_receipt_sha256: str
    mapping_record_sha256: str


@dataclass(frozen=True)
class SavedPhotoMappingReceipt:
    owner: str
    accepted_sha256: str
    history_sha256: str
    store: PhotoMappingStoreCheckpoint
    entries: tuple

    def wire(self):
        return dict(format=1,owner=self.owner,accepted_sha256=self.accepted_sha256,history_sha256=self.history_sha256,
            store=self.store.wire(),entries=[dict(file_id=e.file_id,photo_id=e.photo_id,
                saved_receipt_sha256=e.saved_receipt_sha256,mapping_record_sha256=e.mapping_record_sha256) for e in self.entries])

    @property
    def grants_write_authority(self):return False

    @property
    def is_saved_receipt(self):return False

    @property
    def is_book_save_ack(self):return False

    @classmethod
    def capture(cls,accepted,history,owner,receipts,records,store):
        # Import only at the native capture boundary, avoiding index/receiver
        # import cycles. A parsed value itself grants no mutation permission.
        from magnolie_photo_mappings import NativeSavedPhotoMapping
        if (type(accepted) is not NativeAcceptedTransfer or type(history) is not NativeMediaHistory
                or type(store) is not PhotoMappingStoreCheckpoint or type(receipts) is not tuple or type(records) is not tuple
                or len(receipts)!=len(history.entries) or len(records)!=len(history.entries)
                or any(type(r) is not NativeSavedFileReceipt for r in receipts)
                or any(type(r) is not NativeSavedPhotoMapping for r in records)):
            raise TransferError('photo_mapping_receipt_native_evidence_required')
        by_file={r.file_id:r for r in receipts};mapped={r.source_file_id:r for r in records};entries=[]
        if len(by_file)!=len(receipts) or len(mapped)!=len(records):raise TransferError('photo_mapping_receipt_duplicate_evidence')
        for media in history.entries:
            saved=by_file.get(media.file_id);record=mapped.get(media.file_id)
            if (saved is None or record is None or saved.owner!=owner or record.job_owner!=owner
                    or saved.accepted_sha256!=accepted.fingerprint or saved.manifest_sha256!=accepted.manifest.fingerprint
                    or record.accepted_sha256!=accepted.fingerprint or record.manifest_sha256!=accepted.manifest.fingerprint
                    or record.association.source_epoch!=history.source_epoch or record.association.media_type!=history.media_type
                    or record.association.photo_id!=media.photo_id or record.receipt_sha256!=saved.protected_record_sha256
                    or record.destination!=accepted.destination or record.relative_path!=saved.relative_path
                    or record.file_key!=saved.file_key or record.parent_keys!=saved.parent_keys
                    or record.saved_size!=saved.size or record.saved_sha256!=saved.sha256):
                raise TransferError('photo_mapping_receipt_original_evidence_changed')
            entries.append(SavedMappingEntry(media.file_id,media.photo_id,saved.protected_record_sha256,record.protected_record_sha256))
        result=cls(owner,accepted.fingerprint,sha256(canonical(history.wire())).hexdigest(),store,tuple(entries))
        return cls.parse(result.wire(),accepted,history,owner,receipts)

    @classmethod
    def parse(cls,value,accepted,history,owner,receipts):
        def fail():raise TransferError('photo_mapping_receipt_invalid')
        if (type(accepted) is not NativeAcceptedTransfer or type(history) is not NativeMediaHistory
                or type(owner) is not str or re.fullmatch('[0-9a-f]{32}',owner) is None
                or type(receipts) is not tuple or any(type(r) is not NativeSavedFileReceipt for r in receipts)
                or type(value) is not dict or set(value)!={'format','owner','accepted_sha256','history_sha256','store','entries'}
                or type(value['format']) is not int or value['format']!=1 or value['owner']!=owner
                or value['accepted_sha256']!=accepted.fingerprint or value['history_sha256']!=sha256(canonical(history.wire())).hexdigest()
                or type(value['entries']) is not list or len(value['entries'])!=len(accepted.manifest.files)):
            fail()
        NativeMediaHistory.parse(history.wire(),accepted)
        store=PhotoMappingStoreCheckpoint.parse(value['store']);by_file={r.file_id:r for r in receipts}
        if len(by_file)!=len(receipts) or set(by_file)!={f.id for f in accepted.manifest.files}:fail()
        if store.count<len(history.entries):fail()
        if history.mapping_store is not None and (store.witness!=history.mapping_store.witness
                or store.revision<history.mapping_store.revision or store.count<history.mapping_store.count
                or store.revision==history.mapping_store.revision and store!=history.mapping_store):fail()
        entries=[]
        for entry,media,file in zip(value['entries'],history.entries,accepted.manifest.files):
            saved=by_file[media.file_id]
            if (type(entry) is not dict or set(entry)!={'file_id','photo_id','saved_receipt_sha256','mapping_record_sha256'}
                    or entry['file_id']!=media.file_id or entry['photo_id']!=media.photo_id
                    or saved.owner!=owner or saved.accepted_sha256!=accepted.fingerprint
                    or saved.manifest_sha256!=accepted.manifest.fingerprint or saved.size!=file.size or saved.sha256!=file.sha256
                    or saved.relative_path!=dict(accepted.targets)[file.id]
                    or entry['saved_receipt_sha256']!=saved.protected_record_sha256
                    or any(type(entry[name]) is not str or re.fullmatch('[0-9a-f]{64}',entry[name]) is None
                        for name in ('saved_receipt_sha256','mapping_record_sha256'))):fail()
            entries.append(SavedMappingEntry(entry['file_id'],entry['photo_id'],entry['saved_receipt_sha256'],entry['mapping_record_sha256']))
        return cls(owner,accepted.fingerprint,value['history_sha256'],store,tuple(entries))
