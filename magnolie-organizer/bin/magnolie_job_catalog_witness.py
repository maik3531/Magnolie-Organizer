"""Original immutable catalog bootstrap identity; no reservation authority."""
from dataclasses import dataclass
import re

from magnolie_file_transfer import TransferError


@dataclass(frozen=True)
class JobCatalogWitness:
    receiver_id: str
    receiver_identity_sha256: str
    root_key: tuple
    lock_key: tuple
    owner_key: tuple
    owner_sha256: str

    def wire(self):
        return dict(format=1,receiver_id=self.receiver_id,receiver_identity_sha256=self.receiver_identity_sha256,
            root_key=list(self.root_key),lock_key=list(self.lock_key),owner_key=list(self.owner_key),owner_sha256=self.owner_sha256)

    @classmethod
    def parse(cls,value):
        def fail():raise TransferError('file_job_catalog_invalid_witness')
        if (type(value) is not dict or set(value)!={'format','receiver_id','receiver_identity_sha256','root_key','lock_key','owner_key','owner_sha256'}
                or type(value['format']) is not int or value['format']!=1 or type(value['receiver_id']) is not str
                or re.fullmatch(r'[A-Za-z0-9_-]{16,160}',value['receiver_id']) is None):fail()
        for name in ('receiver_identity_sha256','owner_sha256'):
            if type(value[name]) is not str or re.fullmatch('[0-9a-f]{64}',value[name]) is None:fail()
        for name in ('root_key','lock_key','owner_key'):
            key=value[name]
            if type(key) is not list or len(key)!=2 or any(type(number) is not int or not 0<=number<2**64 for number in key) or not key[1]:fail()
        return cls(value['receiver_id'],value['receiver_identity_sha256'],tuple(value['root_key']),tuple(value['lock_key']),
            tuple(value['owner_key']),value['owner_sha256'])

    @property
    def grants_write_authority(self):return False


@dataclass(frozen=True)
class NativeJobCatalogChoice:
    witness: JobCatalogWitness
    owner: object
