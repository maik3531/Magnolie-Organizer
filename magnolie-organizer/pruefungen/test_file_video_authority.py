"""Video availability needs protected support AND current secure ACK metadata."""
from copy import deepcopy
import uuid

import pytest

from test_file_authenticated_desktop import native,bind
import magnolie_telefon as phone
from magnolie_file_native_authority import NativeDesktopFileAuthority


def observe(service,peer,channel,kind,body,**kwargs):
    now=phone.now_ms()
    message=dict(type='message',v=1,message_id=str(uuid.uuid4()),kind=kind,
        created_ms=now,expires_ms=now+60_000,body=deepcopy(body))
    service._observe_native_file_control(peer,channel,kind,message,**kwargs)
    return message


def setup_video(native,monkeypatch):
    service,peer,_=native
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    peer['capabilities']['items']['device_status']['versions'].append(22)
    service.store.save_peers();channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    return service,peer,channel,binding,authority


def ack_all(service,peer,channel):
    observe(service,peer,channel,'capabilities.update',peer['capabilities'])
    observe(service,peer,channel,'grants.update',peer['grants'])
    observe(service,peer,channel,'personal_sync.settings',dict(format=1,own_device=True))


def test_persisted_video_marker_needs_all_current_acknowledgements_and_default_authority_stays_closed(native,monkeypatch):
    service,peer,channel,binding,authority=setup_video(native,monkeypatch)
    try:
        assert authority.current_peer().video_supported and not authority.video_available()
        observe(service,peer,channel,'capabilities.update',peer['capabilities'],acknowledged=False)
        observe(service,peer,channel,'grants.update',peer['grants'])
        observe(service,peer,channel,'personal_sync.settings',dict(format=1,own_device=True))
        assert not authority.video_available()
        observe(service,peer,channel,'capabilities.update',peer['capabilities'])
        assert authority.video_available()
        closed=NativeDesktopFileAuthority(binding,lambda:binding,channel=channel)
        try:assert not closed.video_available()
        finally:closed.close()
    finally:authority.close()


def test_withdrawal_failed_ack_and_superseded_positive_cannot_revive_video_or_revoke_photo_authority(native,monkeypatch):
    service,peer,channel,_,authority=setup_video(native,monkeypatch)
    try:
        ack_all(service,peer,channel);assert authority.video_available()
        positive=deepcopy(service._native_file_control_receipts[channel]['capabilities.update'])
        base=authority.current_peer().control_peer(authority,ready=True,handlers_ready=True)
        peer['capabilities']['items']['device_status']['versions'].remove(22);service.store.save_peers()
        service._observe_native_file_control(peer,channel,'capabilities.update',positive,duplicate=True)
        assert not authority.video_available()
        assert vars(authority.current_peer().control_peer(authority,ready=True,handlers_ready=True))==vars(base)
        observe(service,peer,channel,'capabilities.update',peer['capabilities'])
        peer['capabilities']['items']['device_status']['versions'].append(22);service.store.save_peers()
        observe(service,peer,channel,'capabilities.update',peer['capabilities'],acknowledged=False)
        assert not authority.video_available()
        observe(service,peer,channel,'capabilities.update',peer['capabilities'])
        assert authority.video_available()
    finally:authority.close()


@pytest.mark.parametrize('change',['grants','own','generation','channel','base_marker'])
def test_current_video_witness_rechecks_live_metadata_and_transport(native,monkeypatch,change):
    service,peer,channel,_,authority=setup_video(native,monkeypatch)
    try:
        ack_all(service,peer,channel);assert authority.video_available()
        if change=='grants':peer['grants']=dict(peer['grants'],revision=999)
        elif change=='own':
            observe(service,peer,channel,'personal_sync.settings',dict(format=1,own_device=False),acknowledged=False)
        elif change=='generation':service._generation+=1
        elif change=='channel':bind(service,peer)
        else:
            peer['capabilities']['items']['device_status']['versions'].remove(21);service.store.save_peers()
            observe(service,peer,channel,'capabilities.update',peer['capabilities'])
        assert not authority.video_available()
        if change=='channel':
            fresh_channel=service.connections[peer['device_id']]
            fresh=service.open_native_file_authority(peer['device_id'],peer['static_public'],fresh_channel,service._generation)
            try:
                assert not fresh.video_available()
                ack_all(service,peer,fresh_channel);assert fresh.video_available()
            finally:fresh.close()
    finally:authority.close()


def test_video_witness_is_rechecked_after_protected_io_without_service_lock(native,monkeypatch):
    service,peer,channel,_,authority=setup_video(native,monkeypatch)
    try:
        ack_all(service,peer,channel)
        original=authority.protection.read_native_peers_blob
        def withdrawn_during_read():
            assert not service.lock._is_owned()
            blob=original()
            service._native_file_controls[channel].pop('capabilities.update',None)
            return blob
        monkeypatch.setattr(authority.protection,'read_native_peers_blob',withdrawn_during_read)
        assert not authority.video_available()
        assert authority.current_peer() is not None
    finally:authority.close()


def test_real_payload_failed_secure_ack_and_superseded_capability_replay_cannot_restore_video(native,monkeypatch):
    service,peer,channel,_,authority=setup_video(native,monkeypatch)
    try:
        ack_all(service,peer,channel);assert authority.video_available()
        def update(video):
            body=deepcopy(peer['capabilities']);body['revision']+=1
            versions=body['items']['device_status']['versions']
            if video and 22 not in versions:versions.append(22)
            if not video and 22 in versions:versions.remove(22)
            now=phone.now_ms()
            return dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='capabilities.update',
                created_ms=now,expires_ms=now+60_000,body=body)
        positive=update(True);service._payload(peer,channel,positive)
        channel.send.side_effect=OSError('fixture encrypted capability ACK lost')
        withdrawal=update(False)
        with pytest.raises(OSError):service._payload(peer,channel,withdrawal)
        assert not authority.video_available() and authority.current_peer().metadata_supported
        channel.send.side_effect=None
        service._payload(peer,channel,positive)
        assert not authority.video_available()
        service._payload(peer,channel,withdrawal)
        assert not authority.video_available()
        renewed=update(True);channel.send.side_effect=OSError('fixture positive ACK lost')
        with pytest.raises(OSError):service._payload(peer,channel,renewed)
        assert not authority.video_available()
        channel.send.side_effect=None
        service._payload(peer,channel,positive)
        assert not authority.video_available()
        service._payload(peer,channel,renewed)
        assert authority.video_available()
    finally:authority.close()


def test_positive_channel_witness_cannot_replace_protected_video_support(native,monkeypatch):
    service,peer,channel,binding,authority=setup_video(native,monkeypatch)
    local=NativeDesktopFileAuthority(binding,lambda:binding,channel=channel,video_witness=lambda:True)
    try:
        assert local.video_available()
        peer['capabilities']['items']['device_status']['versions'].remove(22);service.store.save_peers()
        assert not local.video_available() and local.current_peer().metadata_supported
        peer['capabilities']['items']['device_status']['versions'].append(22)
        peer['capabilities']['items']['device_status']['versions'].remove(21);service.store.save_peers()
        assert not local.video_available() and not local.current_peer().video_supported
    finally:local.close();authority.close()
