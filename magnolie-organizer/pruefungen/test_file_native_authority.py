from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import os
import sys
import uuid
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_telefon as phone
from magnolie_file_native_authority import read_native_file_peer,from_authenticated_identity
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from test_telefon import _complete_peer

@pytest.fixture
def native(tmp_path):
    root=tmp_path/'native';root.mkdir(mode=0o700)
    (root/'storage.key').write_bytes(bytes(range(32)));(root/'storage.key').chmod(0o600)
    peer=_complete_peer(public=bytes([7])*32)
    peer['personal_sync'].update(own_device=True,remote_own_device=True)
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([1])*32)
    peer['capabilities']=phone.desktop_capabilities()
    peer['capabilities']['items']['device_status']['versions'].append(21) # Fixture only, never actual advertisement.
    def write(peers):
        blob=phone.canonical(dict(storage_version=1,items=peers));nonce=bytes([8])*12
        (root/'peers.json').write_bytes(nonce+AESGCM(bytes(range(32))).encrypt(nonce,blob,b'magnolie-phone-storage-v1\0peersall'))
        (root/'peers.json').chmod(0o600)
    write([peer])
    return root,peer,write

def test_actual_native_encrypted_peer_projection_never_constructs_store_migrates_or_loads_private_identity(native,monkeypatch):
    root,peer,_=native
    for method in ('__init__','_load_peers','peer','sole_peer'):
        monkeypatch.setattr(phone.PhoneStore,method,lambda *args,**kwargs:pytest.fail('File authority called a creating/migrating peer loader'))
    before={path.name:(path.stat().st_ino,path.read_bytes()) for path in root.iterdir()}
    with ExistingFileTransferProtection(root) as protection:
        snapshot=read_native_file_peer(protection,peer['device_id'],peer['static_public'])
        assert snapshot.identity_sha256==sha256(bytes([7])*32).hexdigest()
        assert snapshot.pairing_epoch==peer['file_pairing_epoch']
        assert snapshot.metadata_supported
        owner=object();control=snapshot.control_peer(owner,ready=True,handlers_ready=True)
        assert control.allowed and control.owner is owner and control.pairing_epoch==snapshot.pairing_epoch
        assert not snapshot.control_peer(owner,ready=True,handlers_ready=False).allowed
    assert before=={path.name:(path.stat().st_ino,path.read_bytes()) for path in root.iterdir()}
    assert not (root/'identity.json').exists() and not (root/'identity.key').exists() and not (root/'phone.db').exists()
    assert 21 not in phone.desktop_capabilities()['items']['device_status']['versions']

@pytest.mark.parametrize('change',['legacy','own','remote-own','pending','ambiguous','unsupported','legacy-capabilities'])
def test_closed_or_incomplete_native_metadata_is_not_normalized_into_consent(native,change):
    root,peer,write=native
    if change=='legacy':del peer['file_pairing_epoch']
    elif change=='own':peer['personal_sync']['own_device']=False
    elif change=='remote-own':peer['personal_sync']['remote_own_device']=False
    elif change=='pending':
        peer.update(state='pair_commit_pending',pending_transcript=phone.b64(bytes(32)),pending_phone_finish_proof=phone.b64(bytes(32)),
                    pending_desktop_finish_proof=phone.b64(bytes(32)),pending_expires_ms=1_900_000_000_000)
    elif change=='unsupported':peer['capabilities']['items']['device_status']['versions'].remove(21)
    elif change=='legacy-capabilities':peer['capabilities']={}
    peers=[peer,deepcopy(peer)] if change=='ambiguous' else [peer]
    write(peers);before=(root/'peers.json').read_bytes()
    with ExistingFileTransferProtection(root) as protection:
        snapshot=read_native_file_peer(protection,peer['device_id'],peer['static_public'])
        if change in ('unsupported','legacy-capabilities'):
            assert snapshot is not None and not snapshot.metadata_supported
            assert not snapshot.control_peer(object(),ready=True,handlers_ready=True).allowed
        else:assert snapshot is None
    assert (root/'peers.json').read_bytes()==before

@pytest.mark.parametrize('change',['missing','corrupt','permissions','symlink','hardlink','directory'])
def test_unsafe_or_missing_native_peer_metadata_fails_without_replacement(native,change):
    root,peer,_=native;path=root/'peers.json'
    if change=='corrupt':
        data=path.read_bytes();path.write_bytes(data[:-1]+bytes([data[-1]^1]))
    elif change=='permissions':path.chmod(0o644)
    else:
        path.rename(root/'held-peers')
        if change=='symlink':path.symlink_to(root/'held-peers')
        elif change=='hardlink':os.link(root/'held-peers',path)
        elif change=='directory':path.mkdir(mode=0o700)
    before=set(root.iterdir())
    with ExistingFileTransferProtection(root) as protection:
        with pytest.raises((OSError,TransferError,InvalidTag)):read_native_file_peer(protection,peer['device_id'],peer['static_public'])
    assert set(root.iterdir())==before
    if change=='missing':assert not path.exists()

def test_exact_pinned_peer_key_and_persistent_pairing_must_match_native_readback(native):
    root,peer,write=native
    with ExistingFileTransferProtection(root) as protection:
        first=read_native_file_peer(protection,peer['device_id'],peer['static_public'])
        assert read_native_file_peer(protection,str(uuid.uuid4()),peer['static_public']) is None
        assert read_native_file_peer(protection,peer['device_id'],phone.b64(bytes(32))) is None
        peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([2])*32);write([peer])
        second=read_native_file_peer(protection,peer['device_id'],peer['static_public'])
        assert first.identity_sha256==second.identity_sha256 and first.pairing_epoch!=second.pairing_epoch

def test_public_identity_projection_is_pure_and_requires_the_native_desktop_role():
    identity=dict(storage_version=1,device_id=str(uuid.uuid4()),role='desktop',display_name='PC',static_public=phone.b64(bytes([7])*32))
    result=from_authenticated_identity(identity)
    assert result.receiver_identity_sha256==sha256(bytes([7])*32).hexdigest()
    identity['role']='phone'
    with pytest.raises(TransferError):from_authenticated_identity(identity)

def test_peer_change_during_actual_native_decryption_cannot_return_stale_pairing(native,monkeypatch):
    root,peer,write=native;original=AESGCM.decrypt
    def changed(cipher,*args):
        plain=original(cipher,*args)
        peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([2])*32);write([peer])
        return plain
    monkeypatch.setattr(AESGCM,'decrypt',changed)
    with ExistingFileTransferProtection(root) as protection:
        with pytest.raises(TransferError,match='native_peers_changed'):read_native_file_peer(protection,peer['device_id'],peer['static_public'])
