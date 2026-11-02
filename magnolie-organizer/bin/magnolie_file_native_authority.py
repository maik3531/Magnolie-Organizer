"""Read-only native desktop file authority. No store/key construction/migration."""
from dataclasses import dataclass
from hashlib import sha256

from magnolie_file_control import NativeFilePeer, DISCOVERY_VERSION
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity
from magnolie_telefon import PhoneStore, strict_json, unb64, valid_uuid, current_native_file_pairing_epoch

def from_authenticated_identity(identity):
    """Project the public desktop identity already authenticated by transport.
    This pure helper does not make an arbitrary dictionary an authenticated owner.
    Only the actual channel/generation cache may supply it to a controller.
    """
    if (type(identity) is not dict or type(identity.get('storage_version')) is not int or identity['storage_version']!=1
            or identity.get('role')!='desktop' or not valid_uuid(identity.get('device_id'))):
        raise TransferError('file_authority_authenticated_identity_required')
    return NativeJobCatalogIdentity(identity['device_id'],sha256(unb64(identity.get('static_public'),32)).hexdigest())

@dataclass(frozen=True)
class NativeFilePeerSnapshot:
    peer_id: str
    static_public: str
    identity_sha256: str
    pairing_epoch: str
    metadata_supported: bool

    def control_peer(self,owner,*,ready,handlers_ready):
        if type(ready) is not bool or type(handlers_ready) is not bool:
            raise TransferError('file_authority_native_transport_required')
        return NativeFilePeer(self.peer_id,self.identity_sha256,owner,ready,True,True,True,
                              self.metadata_supported and handlers_ready,self.pairing_epoch)

def read_native_file_peer(protection,peer_id,static_public):
    if type(protection) is not ExistingFileTransferProtection:
        raise TransferError('file_authority_existing_native_protection_required')
    value=strict_json(protection.read_native_peers_blob())
    if (type(value) is not dict or set(value)!={'storage_version','items'} or type(value['storage_version']) is not int
            or value['storage_version']!=1 or type(value['items']) is not list or len(value['items'])>8):
        raise TransferError('file_authority_invalid_native_peers')
    # Ambiguous/absent native peers never select the first record or create one.
    if len(value['items'])!=1:return None
    peer=value['items'][0]
    PhoneStore._validate_peer(peer) # Static validation only; no migrating loader.
    if peer['device_id']!=peer_id or peer['static_public']!=static_public:return None
    epoch=current_native_file_pairing_epoch(peer)
    if epoch is None:return None
    status=peer['capabilities'].get('items',{}).get('device_status',{})
    return NativeFilePeerSnapshot(peer_id,static_public,sha256(unb64(static_public,32)).hexdigest(),epoch,
                                  status.get('available') is True and DISCOVERY_VERSION in status.get('versions',[]))
