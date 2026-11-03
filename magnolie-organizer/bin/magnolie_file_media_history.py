"""Immutable native job media history, never renewed source or target authority."""
from dataclasses import dataclass
import re

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_control import _hex
from magnolie_file_media import SourceMediaEntry, correlate_media_pages
from magnolie_file_transfer import TransferError
from magnolie_photo_mapping_witness import PhotoMappingStoreCheckpoint
from magnolie_telefon import valid_uuid


@dataclass(frozen=True)
class NativeMediaHistory:
    accepted_sha256: str
    manifest_sha256: str
    version: str
    run_id: str
    source_epoch: str
    media_type: str
    insertion_witness: bool
    attempts: tuple
    entries: tuple
    mapping_store: PhotoMappingStoreCheckpoint | None = None
    version_parents: tuple = ()

    @property
    def grants_write_authority(self):return False

    @property
    def is_saved_receipt(self):return False

    def wire(self):
        value=dict(format=1,accepted_sha256=self.accepted_sha256,manifest_sha256=self.manifest_sha256,
            version=self.version,run_id=self.run_id,source_epoch=self.source_epoch,media_type=self.media_type,
            insertion_witness=self.insertion_witness,
            attempts=[dict(request_id=request_id,count=count) for request_id,count in self.attempts],
            entries=[dict(file_id=entry.file_id,photo_id=entry.photo_id,media_kind=entry.media_kind) for entry in self.entries])
        if self.mapping_store is not None:value=dict(value,format=2,mapping_store=self.mapping_store.wire())
        if self.version_parents:
            value=dict(value,format=3,version_parents=[dict(photo_id=photo,record_sha256=record) for photo,record in self.version_parents])
        return value

    @classmethod
    def capture(cls,accepted,pages,*,mapping_store=None,version_parents=()):
        if type(accepted) is not NativeAcceptedTransfer:raise TransferError('file_media_history_native_acceptance_required')
        if mapping_store is not None and type(mapping_store) is not PhotoMappingStoreCheckpoint:
            raise TransferError('file_media_history_native_mapping_checkpoint_required')
        entries=correlate_media_pages(pages,accepted.manifest)
        first=pages[0]
        history=cls(accepted.fingerprint,accepted.manifest.fingerprint,first.version,first.run_id,first.source_epoch,
            first.media_type,first.insertion_witness,tuple((page.request_id,len(page.entries)) for page in pages),entries,mapping_store,version_parents)
        return cls.parse(history.wire(),accepted)

    @classmethod
    def parse(cls,value,accepted):
        """Only protected job metadata callers may supply historical bytes.
        Parsing does not verify live READ, a current target or a saved file.
        """
        def fail():raise TransferError('file_media_history_invalid')
        if (type(accepted) is not NativeAcceptedTransfer or type(value) is not dict
                or type(value.get('format')) is not int or value['format'] not in (1,2,3)
                or set(value)!=({'format','accepted_sha256','manifest_sha256','version','run_id','source_epoch',
                    'media_type','insertion_witness','attempts','entries'} | ({'mapping_store'} if value['format']>=2 else set())
                    | ({'version_parents'} if value['format']==3 else set()))
                or value['accepted_sha256']!=accepted.fingerprint or value['manifest_sha256']!=accepted.manifest.fingerprint
                or not _hex(value['version']) or not _hex(value['source_epoch']) or not valid_uuid(value['run_id'],version=4)
                or value['media_type'] not in ('images','video') or type(value['insertion_witness']) is not bool
                or type(value['attempts']) is not list or not 1<=len(value['attempts'])<=128
                or type(value['entries']) is not list or len(value['entries'])!=len(accepted.manifest.files)):
            fail()
        attempts=[]
        for attempt in value['attempts']:
            if (type(attempt) is not dict or set(attempt)!={'request_id','count'}
                    or not valid_uuid(attempt['request_id'],version=4) or type(attempt['count']) is not int
                    or not 1<=attempt['count']<=8):fail()
            attempts.append((attempt['request_id'],attempt['count']))
        if sum(count for _,count in attempts)!=len(value['entries']) or len({request for request,_ in attempts})!=len(attempts):fail()
        entries=[]
        for entry in value['entries']:
            if (type(entry) is not dict or set(entry)!={'file_id','photo_id','media_kind'}
                    or type(entry['file_id']) is not str or re.fullmatch('[0-9a-f]{32}',entry['file_id']) is None
                    or not _hex(entry['photo_id']) or entry['media_kind'] not in (
                        ('image','animation','unknown_image') if value['media_type']=='images' else ('video',))):fail()
            entries.append(SourceMediaEntry(entry['file_id'],entry['photo_id'],entry['media_kind']))
        if (tuple(entry.file_id for entry in entries)!=tuple(file.id for file in accepted.manifest.files)
                or len({entry.photo_id for entry in entries})!=len(entries)):fail()
        parents=[]
        if value['format']==3:
            if (not value['insertion_witness'] or type(value['version_parents']) is not list
                    or not 1<=len(value['version_parents'])<=len(entries)):fail()
            for parent in value['version_parents']:
                if (type(parent) is not dict or set(parent)!={'photo_id','record_sha256'}
                        or not _hex(parent['photo_id']) or not _hex(parent['record_sha256'])
                        or parent['photo_id'] not in {entry.photo_id for entry in entries}):fail()
                parents.append((parent['photo_id'],parent['record_sha256']))
            if len(set(photo for photo,_ in parents))!=len(parents) or parents!=sorted(parents):fail()
        return cls(value['accepted_sha256'],value['manifest_sha256'],value['version'],value['run_id'],value['source_epoch'],
            value['media_type'],value['insertion_witness'],tuple(attempts),tuple(entries),
            PhotoMappingStoreCheckpoint.parse(value['mapping_store']) if value['format']>=2 else None,tuple(parents))
