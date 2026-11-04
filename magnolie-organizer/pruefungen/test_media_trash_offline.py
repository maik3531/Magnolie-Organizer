"""Own local recovery survives disconnect/unpair without becoming a data grant."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_trash import ProtectedMediaTrash,NativeLocalMediaTrashAuthority
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_mappings import ProtectedPhotoMappings
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings
from test_media_trash import trash,prepare,paths


@pytest.mark.parametrize('unpair',[False,True])
def test_actual_trashed_bytes_restore_after_disconnect_or_unpair_without_any_phone_command(trash,unpair):
    fixture,mappings,association,mapping,online=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=online.trash(online.issue_action(),snapshot,entry.operation,lambda:True)
    scope=online._scope;online.close();fixture[0]._end_native_file_connection(fixture[2])
    if unpair:
        fixture[0].store.peers=[];fixture[0].store.save_peers()
    root=Path(fixture[0].store.root);before=set(root.iterdir());sent=fixture[2].send.call_count
    authority=NativeLocalMediaTrashAuthority(str(root),scope)
    owner=ProtectedMediaTrash(authority)
    try:
        current,entries=owner.read()
        assert current.associated and entries[0].operation==entry.operation
        assert not hasattr(authority,'native_channel') and not hasattr(authority.current_peer(),'control_peer')
        with pytest.raises(TransferError,match='local_recovery_only'):
            owner.trash(owner.issue_action(),current,entry.operation,lambda:True)
        with pytest.raises(TransferError,match='local_recovery_only'):
            owner.prepare_local(owner.issue_action(),current,mappings,association,mapping.protected_record_sha256)
        with pytest.raises(TransferError,match='native_authority_required'):ProtectedPhotoPreferences(authority)
        with pytest.raises(TransferError,match='native_authority_required'):ProtectedPhotoMappings(authority)
        restored,entry=owner.restore(owner.issue_action(),current,entry.operation,lambda:authority.current_peer() is not None)
        assert entry.state=='restored' and original.read_bytes()==b'hello' and not payload.exists()
        assert fixture[2].send.call_count==sent and set(root.iterdir())==before
        with pytest.raises(TransferError):owner.trash(owner.issue_action(),restored,entry.operation,lambda:True)
    finally:owner.close();authority.close()


def test_offline_authority_never_creates_missing_native_root_key_or_anchor(tmp_path,trash):
    missing=tmp_path/'must-not-be-created'
    with pytest.raises((OSError,TransferError)):NativeLocalMediaTrashAuthority(str(missing),'a'*64)
    assert not missing.exists()
    root=Path(trash[0][0].store.root);before=set(root.iterdir())
    with pytest.raises((OSError,TransferError)):NativeLocalMediaTrashAuthority(str(root),'a'*64)
    assert set(root.iterdir())==before


def test_offline_key_withdrawal_blocks_restore_and_old_authority_cannot_revive(trash):
    fixture,_,_,_,online=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=online.trash(online.issue_action(),snapshot,entry.operation,lambda:True)
    scope=online._scope;online.close()
    root=Path(fixture[0].store.root);authority=NativeLocalMediaTrashAuthority(str(root),scope)
    owner=ProtectedMediaTrash(authority)
    key=root/'storage.key';original_key=key.read_bytes()
    try:
        current,_=owner.read();key.write_bytes(b'x'*32);key.chmod(0o600)
        with pytest.raises(TransferError):owner.restore(owner.issue_action(),current,entry.operation,lambda:True)
        assert payload.read_bytes()==b'hello' and not original.exists()
        key.write_bytes(original_key)
        with pytest.raises(TransferError):owner.read()
        assert payload.read_bytes()==b'hello'
    finally:key.write_bytes(original_key);owner.close();authority.close()


def test_offline_anchor_removed_after_capture_holds_instead_of_absent_defaults(trash):
    fixture,_,_,_,online=trash
    snapshot,entry=prepare(trash);scope=online._scope;online.close()
    root=Path(fixture[0].store.root);authority=NativeLocalMediaTrashAuthority(str(root),scope)
    owner=ProtectedMediaTrash(authority)
    (root/online._anchor).rename(root/(online._anchor+'.explicit-fixture-parked'))
    try:
        with pytest.raises(TransferError,match='original_anchor_required'):owner.read()
    finally:owner.close();authority.close()


def test_observed_online_history_cannot_reset_when_both_originals_disappear(trash):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);root=Path(fixture[0].store.root)
    for name in (owner._name,owner._anchor):
        (root/name).rename(root/(name+'.explicit-fixture-parked'))
    with pytest.raises(TransferError,match='original_anchor_required'):owner.read()
