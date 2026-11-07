"""Native owned-file source inspection; no cache, upload or UI acceptance."""
from pathlib import Path
from hashlib import sha256
import os
import socket
import sys
import threading
import types

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_telefon as phone
from magnolie_file_transfer import TransferError
from magnolie_file_native_authority import capture_authenticated_binding
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_transport import NativeMediaSettingsTransport
from magnolie_media_retention import NativeMediaRetention
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_mappings import ProtectedPhotoMappings
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings,save
from test_media_transport import PeerWire,agreement,AT


@pytest.fixture
def source(mappings):
    fixture,owner=mappings;receiver,pages,association=save(fixture)
    _,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages);record=records[0]
    service,peer=fixture[:2]
    peer['capabilities']['items']['device_status']['versions'].append(23);service.store.save_peers()
    left,right=socket.socketpair();left.settimeout(2);right.settimeout(2)
    channel=phone.SecureChannel(left,bytes([3])*16,bytes([1])*32,bytes([1])*4,bytes([2])*32,bytes([2])*4)
    binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
    service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    prefs=ProtectedPhotoPreferences(authority);store=ProtectedPhotoMappings(authority)
    controller=NativeMediaSettingsTransport(authority,lambda:True,clock=lambda:AT)
    policy=prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=True,videos=False)
    h=types.SimpleNamespace(controller=controller,wire=PeerWire(right),channel=channel,authority=authority,peer=peer,
        preferences=prefs,mappings=store,policy=policy,record=record,association=association,target=fixture[4]/record.relative_path)
    agreement(h);h.source=NativeMappedMediaSource(prefs,store,controller)
    try:yield h
    finally:h.source.close();controller.close();store.close();prefs.close();authority.close();left.close();right.close()


def inspect(h,owner=None):
    return (owner or h.source).inspect(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256)


def test_native_source_inspects_actual_same_inode_pc_edit_without_promoting_history_or_send_readiness(source):
    h=source;edited=b'actual PC-edited original bytes, never transcoded';h.target.write_bytes(edited)
    observation=inspect(h)
    assert observation.size==len(edited) and observation.sha256==sha256(edited).hexdigest()
    assert observation.file_key==h.record.file_key and observation.original_reference==h.record.phone_original_reference()
    assert observation.sha256!=observation.original_reference['original_sha256']
    assert not observation.grants_read_authority and not observation.proves_deletion and not observation.is_saved_receipt
    assert h.target.read_bytes()==edited and not h.preferences.local_grant(True).grants.send_files
    returned=observation.original_reference;returned['original_sha256']='9'*64
    assert observation.original_reference==h.record.phone_original_reference()


def test_historical_mapping_and_shared_agreement_cannot_read_without_positive_local_source_consent(source,monkeypatch):
    h=source;h.policy=h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    monkeypatch.setattr(h.source,'_file',lambda *args:pytest.fail('Source was opened before native positive consent'))
    with pytest.raises(TransferError,match='local_consent_required'):inspect(h)
    assert h.target.read_bytes()==b'hello'


@pytest.mark.parametrize('change',['replacement','symlink','hardlink'])
def test_original_inode_and_single_link_are_required_instead_of_adopting_same_name_bytes(source,change):
    h=source;held=h.target.with_name(h.target.name+'.fixture-held')
    if change=='hardlink':os.link(h.target,held)
    else:
        h.target.rename(held)
        if change=='symlink':h.target.symlink_to(held)
        else:h.target.write_bytes(b'hello')
    with pytest.raises((TransferError,OSError)):inspect(h)
    assert held.read_bytes()==b'hello' and h.target.read_bytes()==b'hello'


def test_shared_master_withdrawal_after_actual_source_read_holds_before_any_observation_is_returned(source):
    h=source
    with_owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,
        boundary=lambda phase:h.controller.change('enabled',False) if phase=='source_chunk_read' else None)
    try:
        with pytest.raises(TransferError,match='current_intent_required'):inspect(h,with_owner)
    finally:with_owner.close()
    assert h.target.read_bytes()==b'hello' and h.controller.intent_for('images',to_phone=True) is None


def test_source_cancel_retains_exact_os_media_lane_until_the_blocked_read_actually_returns(source,monkeypatch):
    h=source;entered=threading.Event();release=threading.Event();ended=threading.Event();results=[];pread=os.pread
    def blocked(fd,size,offset):
        value=os.fstat(fd)
        if (value.st_dev,value.st_ino)==h.record.file_key and offset==0:
            entered.set();assert release.wait(8)
        return pread(fd,size,offset)
    monkeypatch.setattr(os,'pread',blocked)
    action=h.preferences.issue_action()
    def work():
        try:results.append(h.source.inspect(action,h.policy,h.association,h.record.protected_record_sha256))
        except BaseException as error:results.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);h.source.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5)
    assert ended.is_set() and not worker.is_alive() and len(results)==1 and isinstance(results[0],TransferError)
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None
    assert h.target.read_bytes()==b'hello'
