"""Expected original metadata-store identities, not file/READ/write grants."""
from dataclasses import dataclass

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError


@dataclass(frozen=True)
class PhotoMappingStoreWitness:
    scope: str
    root_key: tuple
    database_key: tuple
    lock_key: tuple

    def wire(self):
        return dict(format=1,scope=self.scope,root_key=list(self.root_key),database_key=list(self.database_key),lock_key=list(self.lock_key))

    @classmethod
    def parse(cls,value):
        if (type(value) is not dict or set(value)!={'format','scope','root_key','database_key','lock_key'}
                or type(value['format']) is not int or value['format']!=1 or not _hex(value['scope'])):
            raise TransferError('photo_mapping_store_invalid_witness')
        for name in ('root_key','database_key','lock_key'):
            key=value[name]
            if (type(key) is not list or len(key)!=2 or any(type(number) is not int or not 0<=number<2**64 for number in key)
                    or key[1]==0):raise TransferError('photo_mapping_store_invalid_witness')
        return cls(value['scope'],tuple(value['root_key']),tuple(value['database_key']),tuple(value['lock_key']))

    @property
    def grants_write_authority(self):return False


@dataclass(frozen=True)
class NativePhotoMappingStoreChoice:
    witness: PhotoMappingStoreWitness
    owner: object
