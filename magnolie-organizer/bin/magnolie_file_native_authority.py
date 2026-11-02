"""Read-only native desktop file authority. No store/key construction/migration."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import threading

from magnolie_file_control import NativeFilePeer, DISCOVERY_VERSION
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity
from magnolie_telefon import PhoneStore, strict_json, unb64, valid_uuid, current_native_file_pairing_epoch

@dataclass(frozen=True)
class AuthenticatedNativeFileBinding:
    local_identity: NativeJobCatalogIdentity
    peer_id: str
    static_public: str
    pairing_epoch: str | None
    generation: int
    store_owner: object
    native_directory: str

def capture_authenticated_binding(identity,peer,generation,store_owner):
    """Called only at actual authenticated transport binding, not from a request."""
    epoch=peer.get('file_pairing_epoch')
    from magnolie_file_control import _hex
    if (type(generation) is not int or generation<0 or not valid_uuid(peer.get('device_id'))
            or epoch is not None and not _hex(epoch)):
        raise TransferError('file_authority_authenticated_binding_required')
    unb64(peer.get('static_public'),32)
    return AuthenticatedNativeFileBinding(from_authenticated_identity(identity),peer['device_id'],peer['static_public'],
        epoch,generation,store_owner,str(Path(store_owner.root).absolute()))

class NativeDesktopFileAuthority:
    """Explicit existing-root owner; construction starts no worker or file scan.
    UI revocation uses revoke() only. Actual close belongs to the native I/O lane
    after its outstanding work ends, never an impatient UI ownership release.
    """
    def __init__(self,binding,current_binding,*,channel):
        if type(binding) is not AuthenticatedNativeFileBinding or not callable(current_binding) or current_binding() is not binding:
            raise TransferError('file_authority_native_channel_changed')
        self.binding=binding;self.identity=binding.local_identity;self._current=current_binding
        self.native_channel=channel # Exact authenticated owner supplied by native factory.
        self._revoked=threading.Event()
        self.protection=ExistingFileTransferProtection(binding.native_directory)
        try:
            if self.current_peer() is None:raise TransferError('file_authority_native_pairing_unavailable')
        except Exception:
            self.close();raise

    def current_peer(self):
        if self._revoked.is_set():return None
        try:
            if self._current() is not self.binding:
                self.revoke();return None
            peer=read_native_file_peer(self.protection,self.binding.peer_id,self.binding.static_public)
            if (peer is None or peer.pairing_epoch!=self.binding.pairing_epoch or self._current() is not self.binding or self._revoked.is_set()):
                self.revoke();return None
            return peer
        except Exception:
            self.revoke();raise

    def revoke(self):
        self._revoked.set() # No metadata/key read or wait on its I/O gate.

    def close(self):
        self.revoke();self.protection.close()

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
    display_name: str = ''

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
                                  status.get('available') is True and DISCOVERY_VERSION in status.get('versions',[]),peer['display_name'])
