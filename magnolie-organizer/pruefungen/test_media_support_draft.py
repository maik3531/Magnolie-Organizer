"""#330 discovery component over a private wire; no production dispatcher."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import socket
import sys
from threading import Event
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
import magnolie_media_sync as media
from magnolie_media_transport import NativeMediaSettingsTransport
from magnolie_media_support import NativeMediaSupportAttempt, TTL, ack, offer, valid
from magnolie_file_native_authority import capture_authenticated_binding
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_file_transfer import TransferError
from magnolie_photo_preferences import ProtectedPhotoPreferences
from test_media_transport import AT, PeerWire, incoming
from test_file_authenticated_desktop import native
from test_telefon import FakeBluetooth, _complete_peer
from test_file_video_authority import ack_all


FULL = [1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 17, 18, 19, 20, 21, 22]


@contextmanager
def wire_pair():
    left, right = socket.socketpair()
    with left, right:
        left.settimeout(.25)
        right.settimeout(1)
        yield phone.SecureChannel(left, bytes([3])*16, bytes([1])*32, bytes([1])*4,
                                  bytes([2])*32, bytes([2])*4), PeerWire(right)


def legacy_state():
    capabilities = phone.desktop_capabilities()
    capabilities['items']['device_status']['versions'] = list(FULL)
    return phone.validate_capabilities(capabilities)


def test_exact_duplicate_control_preserves_existing_media_support_but_changed_control_retires(native,monkeypatch):
    service,peer,_=native
    peer['capabilities']=legacy_state();service.store.save_peers()
    monkeypatch.setattr(service,'_native_media_support_checked',True)
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *_:None)
    with wire_pair() as (channel,wire):
        binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
        service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
        def deliver(message):
            wire.send(message);service._payload(peer,channel,channel.receive())

        try:
            ack_all(service,peer,channel)
            remote=offer(phone.now_ms());deliver(remote)
            own=wire.receive();assert wire.receive()==ack(remote)
            deliver(ack(own))
            support=service._native_media_support[channel]
            assert support.supports(channel) and not service._native_file_connections
            original=service.photo_sync_state(peer['device_id'])['shared_media']
            for kind,previous in list(service._native_file_control_receipts[channel].items()):
                sent=channel.send_seq
                service._observe_native_file_control(peer,channel,kind,deepcopy(previous),duplicate=True,acknowledged=False)
                assert support.supports(channel)
                service._observe_native_file_control(peer,channel,kind,deepcopy(previous),duplicate=True)
                assert support.supports(channel) and channel.send_seq==sent
                assert service.photo_sync_state(peer['device_id'])['shared_media']==original
            kind='capabilities.update'
            different=deepcopy(service._native_file_control_receipts[channel][kind])
            different['body']['revision']+=1
            service._observe_native_file_control(peer,channel,kind,different,duplicate=True,acknowledged=False)
            assert not support.supports(channel)
            ack_all(service,peer,channel)
            assert not support.supports(channel) and not service._native_file_connections
            assert 'shared_media' not in service.photo_sync_state(peer['device_id'])
        finally:service._end_native_file_connection(channel)


@pytest.mark.parametrize('hello_first,video',[(True,True),(False,True),(False,False)])
def test_negotiated_shared_settings_visible_off_without_creating_file_owner(native,monkeypatch,hello_first,video):
    from magnolie_media_retention import NativeMediaRetention
    service,peer,_=native
    peer['capabilities']=legacy_state()
    if not video:peer['capabilities']['items']['device_status']['versions'].remove(22)
    service.store.save_peers()
    monkeypatch.setattr(service,'_native_media_support_checked',True)
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *_:None)
    book=Path(service.store.root).parent/'daten.json'
    book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":30}}}');book.chmod(0o600)
    with NativeMediaRetention(service.store.root) as retention:assert retention.adopt_existing_saved()
    with wire_pair() as (channel,wire):
        binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
        service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
        def deliver(message):
            wire.send(message);service._payload(peer,channel,channel.receive())

        try:
            ack_all(service,peer,channel)
            assert 'shared_media' not in service.photo_sync_state(peer['device_id'])
            def native_paths():
                return {p.name for p in Path(service.store.root).iterdir() if p.name not in {'phone.db-wal','phone.db-shm'}}
            before=native_paths()
            remote=offer(phone.now_ms())
            if hello_first:
                deliver(remote)
                own=wire.receive();assert wire.receive()==ack(remote)
                assert 'shared_media' not in service.photo_sync_state(peer['device_id'])
                deliver(ack(own))
            else:
                service._begin_native_media_support(peer,channel)
                deliver(ack(wire.receive()))
                assert 'shared_media' not in service.photo_sync_state(peer['device_id'])
                deliver(remote);assert wire.receive()==ack(remote)
            assert service._native_media_support[channel].supports(channel)
            state=service.photo_sync_state(peer['device_id'])
            assert state['shared_media']['values']==media.DEFAULTS
            assert not state['shared_media']['configured'] and not state['shared_media']['agreed']
            assert not state['enabled'] and not state['shared_media']['values']['enabled']
            assert state.get('video_supported',False) is video
            assert 'sending_setup' not in state
            deliver(remote) # Duplicate cannot refresh the preview or emit another ACK.
            assert service.photo_sync_state(peer['device_id'])['shared_media']==state['shared_media']
            assert not service._native_file_connections and native_paths()==before
            authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
            try:assert not media.NativeMediaSettingsStore.has_stored_settings(authority)
            finally:authority.close()
            fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
            request=dict(action='shared_setting',field='auto_mode',value='wifi',version='f'*64)
            with pytest.raises(ValueError,match='media_settings_native_choice_changed'):
                service.photo_sync_action(peer['device_id'],fingerprint,request)
            assert not service._native_file_connections
            request['version']=state['shared_media']['version']
            result=service.photo_sync_action(peer['device_id'],fingerprint,request)
            outbound=wire.receive()
            assert outbound['kind']==media.KIND and media.configured(outbound['body'])['auto_mode']=='wifi'
            assert result['shared_media']['configured'] and not result['shared_media']['agreed']
            assert not result['enabled'] and not result['shared_media']['values']['enabled']
            connection=service._native_file_connections[channel]
            assert connection._catalog is connection._run is None and connection._media_transport.intent_for('images') is None
            support=service._native_media_support[channel];support.close()
            assert 'shared_media' not in service.photo_sync_state(peer['device_id'])
        finally:service._end_native_file_connection(channel)


def test_encrypted_support_requires_both_completions_and_retains_every_legacy_version():
    live, tick = [True], [100]
    at = phone.now_ms()
    legacy = legacy_state()
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: live[0], lambda: at, lambda: tick[0])
        assert not attempt.supports(channel) and attempt.send() and not attempt.send()
        own = wire.receive()
        assert valid(own, at)
        wire.send(ack(own))
        assert attempt.receive(channel, channel.receive()) and not attempt.supports(channel)
        remote = offer(at)
        assert not attempt.receive(object(), remote)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        assert attempt.supports(channel)
        assert legacy == legacy_state() and len(legacy['items']['device_status']['versions']) == 16
        live[0] = False
        assert not attempt.supports(channel)
        live[0] = True
        assert not attempt.supports(channel) and not attempt.send()


def test_full_legacy_schema_reaches_actual_settings_store_and_requires_separate_agreement(native):
    service, peer, _ = native
    peer['capabilities'] = legacy_state()
    service.store.save_peers()
    with wire_pair() as (channel, wire), wire_pair() as (foreign, foreign_wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, 'wifi', file_binding=binding)
        authority = service.open_native_file_authority(peer['device_id'], peer['static_public'], channel, binding.generation)
        preferences = ProtectedPhotoPreferences(authority)
        live = [True]
        attempt = NativeMediaSupportAttempt(channel, lambda: live[0], lambda: AT)
        other = NativeMediaSupportAttempt(foreign, lambda: True, lambda: AT)
        transport = None

        def deliver(target, wire, message, receiver):
            wire.send(message)
            return receiver(target, target.receive())

        def exchange(target, wire, owner):
            assert owner.send()
            sent = wire.receive()
            assert deliver(target, wire, ack(sent), owner.receive)
            remote = offer(AT)
            assert deliver(target, wire, remote, owner.receive) and wire.receive() == ack(remote)
            assert owner.supports(target)

        try:
            with pytest.raises(PermissionError, match='peer_unsupported'):
                NativeMediaSettingsTransport(authority, lambda: True, support=attempt)
            exchange(foreign, foreign_wire, other)
            with pytest.raises(PermissionError, match='peer_unsupported'):
                NativeMediaSettingsTransport(authority, lambda: True, support=other)
            exchange(channel, wire, attempt)
            transport = NativeMediaSettingsTransport(authority, lambda: True, clock=lambda: AT, support=attempt)
            assert transport.display_snapshot()['configured'] is False
            assert transport.intent_for('images') is None and preferences.read().policy is None
            transport.change('enabled', True)
            transport.change('direction', 'two_way')
            transport.change('auto_mode', 'wifi')
            transport.change('videos_enabled', True)
            transport.change('skip_deletions', True)
            sent = transport.send_settings()
            assert sent == wire.receive()
            assert deliver(channel, wire, ack(sent), transport.observe)
            assert transport.intent_for('images') is None
            echoed = incoming(sent['body'])
            assert deliver(channel, wire, echoed, transport.observe) and wire.receive() == ack(echoed)
            assert transport.intent_for('images', to_phone=True) is not None
            assert transport.intent_for('video', to_phone=False) is not None  # settings only, not video-batch support
            projection = transport.display_snapshot()
            assert projection['agreed'] and {key:projection['values'][key] for key in
                ('collection_mode','direction','auto_mode','skip_deletions')} == dict(
                collection_mode='phone_inventory',direction='two_way',auto_mode='wifi',skip_deletions=True)
            assert not preferences.local_grant(True).grants.send_files
            assert not preferences.local_grant(True).grants.receive_files and preferences.read().policy is None
            assert peer['capabilities']['items']['device_status']['versions'] == FULL

            live[0] = False
            assert transport.intent_for('images') is None and transport.display_snapshot() is None
            with pytest.raises(PermissionError):transport.change('direction', 'phone_to_pc')
            live[0] = True
            assert transport.intent_for('images') is None
            assert media.NativeMediaSettingsStore.has_stored_settings(authority)
            assert preferences.read().policy is None
        finally:
            if transport is not None:transport.close()
            attempt.close();other.close();preferences.close();authority.close()


@pytest.mark.parametrize('field,value', [('format', True), ('feature', 'pc_image_batch'), ('grant', True)])
def test_draft_offers_neither_batching_nor_permissions(field, value):
    message = offer(1)
    message['body'][field] = value
    assert not valid(message, 1)


def test_stale_receipt_cannot_extend_the_local_deadline():
    tick = [100]
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: True, lambda: 100_000, lambda: tick[0])
        assert attempt.send()
        own = wire.receive()
        tick[0] += TTL
        assert not attempt.receive(channel, ack(own))
        assert not attempt.receive(channel, offer(100_000))
        assert not attempt.supports(channel)


@pytest.mark.parametrize('completion', ['written', 'failed', 'withdrawn', 'expired'])
def test_early_encrypted_receipt_waits_for_the_original_writer(monkeypatch, completion):
    at, tick, live = phone.now_ms(), [100], [True]
    with wire_pair() as (channel, wire), ThreadPoolExecutor(max_workers=1) as worker:
        original_write = channel.send_ephemeral
        finish = Event()

        def held_result(payload, current):
            original_write(payload, current)
            if payload['type'] == 'message':
                assert finish.wait(2)
                if completion == 'failed':
                    raise OSError('synthetic incomplete write result')

        monkeypatch.setattr(channel, 'send_ephemeral', held_result)
        attempt = NativeMediaSupportAttempt(channel, lambda: live[0], lambda: at, lambda: tick[0])
        remote = offer(at)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        result = worker.submit(attempt.send)
        try:
            own = wire.receive()
            wire.send(ack(own))
            assert attempt.receive(channel, channel.receive())
            assert not attempt.supports(channel)
            if completion == 'withdrawn':
                live[0] = False
            elif completion == 'expired':
                tick[0] += TTL
        finally:
            finish.set()
        assert result.result(timeout=2) == (completion == 'written')
        live[0] = True
        assert attempt.supports(channel) == (completion == 'written') and not attempt.send()


def test_failed_opposite_receipt_write_does_not_establish_support(monkeypatch):
    at = phone.now_ms()
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: True, lambda: at, lambda: 100)
        assert attempt.send()
        own = wire.receive()
        wire.send(ack(own))
        assert attempt.receive(channel, channel.receive())

        def failed_write(payload, current):
            assert payload['type'] == 'ack'
            current()
            raise OSError('synthetic failed opposite receipt write')

        monkeypatch.setattr(channel, 'send_ephemeral', failed_write)
        remote = offer(at)
        wire.send(remote)
        assert not attempt.receive(channel, channel.receive())
        assert not attempt.supports(channel)
        assert not attempt.receive(channel, remote) and not attempt.send()


@pytest.mark.parametrize('error', ['unsupported', 'invalid_schema'])
def test_matching_legacy_rejection_ends_only_that_attempt(error):
    at = phone.now_ms()
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: True, lambda: at, lambda: 100)
        assert attempt.send()
        own = wire.receive()
        unrelated = dict(ack(offer(at)), status='rejected', error=error)
        wire.send(unrelated)
        assert not attempt.receive(channel, channel.receive())
        remote = offer(at)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        wire.send(dict(ack(own), status='rejected', error=error))
        assert not attempt.receive(channel, channel.receive())
        wire.send(ack(own))
        assert not attempt.receive(channel, channel.receive())
        assert not attempt.supports(channel) and not attempt.send()


def test_legacy_rejection_does_not_stop_the_authenticated_parent(tmp_path, monkeypatch):
    service = phone.PhoneService(str(tmp_path/'synthetic'), 'Fixture', bluetooth_backend=FakeBluetooth())
    # Source-only tests do not contain the installed package composition.
    monkeypatch.setattr(service, '_native_photo_built', True)
    peer = _complete_peer()
    peer['capabilities'] = legacy_state()
    peer['personal_sync'].update(own_device=True, remote_own_device=True)
    service.store.peers = [peer]
    service.store.save_peers()
    service.enabled = True
    before = deepcopy(service.store.peers)
    with wire_pair() as (channel, wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, 'wifi', file_binding=binding)
        message = offer(phone.now_ms())
        wire.send(message)
        service._payload(peer, channel, channel.receive())
        assert wire.receive() == dict(ack(message), status='rejected', error='unsupported')
        reserved = dict(offer(phone.now_ms()), kind='file_transfer.shared_support')
        with pytest.raises(ValueError, match='file_desktop_native_route_unavailable'):
            service._payload(peer, channel, reserved)
        heartbeat = dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms())
        wire.send(heartbeat)
        service._payload(peer, channel, channel.receive())
        assert wire.receive() == dict(heartbeat, type='pong')
        assert service.store.peers == before
        assert not service._native_file_connections


@pytest.mark.parametrize('transport,direction,kind,automatic', [
    ('wifi','two_way','images',False),('wifi','phone_to_pc','images',False),('wifi','phone_to_pc','video',False),
    ('wifi','phone_to_pc','images',True),('bluetooth','two_way','images',False)])
def test_actual_reader_joins_only_original_wlan_after_acks_and_never_uses_outbox(native, monkeypatch, tmp_path, transport, direction, kind, automatic, photo_receive_timing):
    service, peer, _ = native
    peer['capabilities'] = legacy_state()
    service.store.save_peers()
    monkeypatch.setattr(service, '_native_media_support_checked', True)
    monkeypatch.setattr(service, '_resume_automatic_photos', lambda *args: None)
    monkeypatch.setattr(NativeDesktopFileConnection, '_data_handlers_ready', True)
    with wire_pair() as (channel, wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, transport, file_binding=binding)
        def deliver(frame):
            wire.send(frame)
            service._payload(peer, channel, channel.receive())
        try:
            deliver(offer(phone.now_ms()))
            assert not service._native_media_support and channel.send_seq==0  # Already authenticated, but no fresh controls.
            ack_all(service, peer, channel)
            remote_probe = offer(phone.now_ms())
            deliver(remote_probe)
            assert not service._native_file_connections
            if transport=='bluetooth':
                assert not service._native_media_support and channel.send_seq==0
                return
            owner=service._native_media_support[channel]
            local=wire.receive();assert valid(local,phone.now_ms())
            assert wire.receive()==ack(remote_probe) and not owner.supports(channel)
            with monkeypatch.context() as patch:
                patch.setattr(service.store,'outbox_policy',lambda *args,**kwargs:pytest.fail('Discovery ACK used the personal outbox'))
                deliver(ack(local))
                assert owner.supports(channel)
                assert not service._native_file_connections  # Support does not create a file owner.
                connection=service.open_native_file_connection(peer['device_id'],peer['static_public'],channel,binding.generation)
                assert connection._media_source is None and not connection.desktop_snapshot()['shared_media']['configured']
                selected=media.change(media.create(peer['device_id']),peer['device_id'],service.store.identity['device_id'],'enabled',True)
                field='videos_enabled' if kind=='video' else 'photos_enabled'
                selected=media.change(selected,peer['device_id'],service.store.identity['device_id'],field,True)
                if kind=='video':selected=media.change(selected,peer['device_id'],service.store.identity['device_id'],'photos_enabled',False)
                selected=media.change(selected,peer['device_id'],service.store.identity['device_id'],'direction',direction)
                if automatic:selected=media.change(selected,peer['device_id'],service.store.identity['device_id'],'auto_mode','wifi')
                def settings(body):
                    message=incoming(body)
                    at=phone.now_ms()
                    return dict(message,created_ms=at,expires_ms=at+60_000)
                proposal=settings(selected);deliver(proposal)
                assert wire.receive()==ack(proposal)
                reply=wire.receive();assert reply['kind']==media.KIND
                deliver(ack(reply))
                assert not connection.desktop_snapshot()['shared_media']['agreed']
                echo=settings(reply['body']);deliver(echo)
                assert wire.receive()==ack(echo)
                assert connection.desktop_snapshot()['shared_media']['agreed']
                assert connection._desktop_session is None and connection._preferences.read().policy is None
                assert not connection._local().grants.receive_files and not connection._local().grants.send_files
                from magnolie_media_retention import NativeMediaRetention
                book=tmp_path/'daten.json'
                book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":0}}}',encoding='utf-8')
                book.chmod(0o600)
                with NativeMediaRetention(service.store.root) as policy:assert policy.adopt_existing_saved()
                session=connection.desktop_session()
                with pytest.raises(TransferError,match='photo_schedule_not_ready'):
                    session.start('sync_shared')  # Matching settings are not enough for the normal entry point.
                if not automatic:
                    session._run('sync_shared',None)  # Check the same worker's independent final guard as well.
                    expected=('media_source_native_composition_required' if direction=='two_way'
                        else 'media_source_shared_incoming_review_required')
                    assert session.snapshot()['state']=='held' and session.snapshot()['error']==expected
                assert connection._preferences.read().policy is None
                if direction=='phone_to_pc':
                    exercise_private_receiver(service,peer,channel,wire,connection,session,tmp_path,deliver,kind,monkeypatch,automatic=automatic,timing=photo_receive_timing)
                send_seq=channel.send_seq
                withdrawn=dict(offer(phone.now_ms()),kind='personal_sync.settings',body=dict(format=1,own_device=False))
                service._observe_native_file_control(peer,channel,withdrawn['kind'],withdrawn,acknowledged=False)
                assert not owner.supports(channel)
                ack_all(service,peer,channel)
                deliver(ack(local)) # Even after withdrawal this is not a personal ACK or a fresh attempt.
                deliver(offer(phone.now_ms()))
                assert not owner.supports(channel) and channel.send_seq==send_seq
                assert 'shared_media' not in connection.desktop_snapshot()
                session._run('sync_shared',None)
                assert session.snapshot()['error']=='media_source_current_intent_required'
                assert channel.send_seq==send_seq
            assert peer['capabilities']['items']['device_status']['versions']==FULL
            assert service._native_file_connections[channel] is connection
            heartbeat=dict(type='ping',ping_id=str(uuid.uuid4()),sent_ms=phone.now_ms())
            deliver(heartbeat)
            assert wire.receive()==dict(heartbeat,type='pong')
        finally:service._end_native_file_connection(channel)
        assert not service._native_media_support
        if automatic:
            assert session.join(5)
            exercise_private_reconnect(service,peer)


def exercise_private_reconnect(service,peer):
    with wire_pair() as (channel,wire):
        binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
        service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
        def deliver(frame):
            wire.send(frame)
            service._payload(peer,channel,channel.receive())
        try:
            ack_all(service,peer,channel)
            assert not service._native_file_connections
            probe=offer(phone.now_ms());deliver(probe)
            local=wire.receive();assert valid(local,phone.now_ms()) and wire.receive()==ack(probe)
            assert not service._native_file_connections  # Previously agreed choices are not fresh support.
            deliver(ack(local))
            connection=service._native_file_connections[channel]
            settings=wire.receive();assert settings['kind']==media.KIND and media.effective(settings['body'])['auto_mode']=='wifi'
            assert wire.receive()['kind']=='file_transfer.control'
            assert not connection.desktop_snapshot()['shared_media']['agreed'] and connection._desktop_session is None
            deliver(ack(settings))
            assert not connection.desktop_snapshot()['shared_media']['agreed'] and connection._desktop_session is None
            at=phone.now_ms();echo=dict(incoming(settings['body']),created_ms=at,expires_ms=at+60_000)
            deliver(echo);assert wire.receive()==ack(echo)
            assert connection.desktop_snapshot()['shared_media']['agreed']
            assert connection._desktop_session is None  # No current phone SEND or file-control echo.
            assert connection._preferences.read().policy.enabled
        finally:service._end_native_file_connection(channel)


def exercise_private_receiver(service,peer,channel,wire,connection,session,tmp_path,deliver,kind,monkeypatch,*,automatic,timing=None):
    from dataclasses import replace
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image
    from magnolie_file_control import FileControlPacket,FileGrantState,NativeFilePeer,NativeLocalFileGrant,NativeFileControlSession
    from magnolie_media_storage_bootstrap import NativeMediaStorageBootstrap
    from magnolie_photo_destination import NativePhotoDestinationController
    import magnolie_file_sources as sources
    from magnolie_transfer_job_catalog import NativeJobCatalogIdentity
    from test_file_desktop_album_worker import phone_batches
    from test_file_desktop_media import manifest
    from test_file_desktop_sources import response,ALBUM,CATALOG

    destination=tmp_path/'explicit-photo-target';destination.mkdir(mode=0o700)
    chooser=NativePhotoDestinationController(connection._authority)
    try:
        choice=chooser.choose_custom(chooser.issue_action(),destination)
        prefs=connection._preferences
        prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',destination_choice=choice)
    finally:chooser.close()
    photo_directory=destination
    if kind=='video':
        from magnolie_photo_destination import NativeVideoDestinationController
        destination=tmp_path/'explicit-video-target';destination.mkdir(mode=0o700)
        chooser=NativeVideoDestinationController(connection._authority)
        try:
            choice=chooser.choose_custom(chooser.issue_action(),destination)
            prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=True,destination_choice=choice)
        finally:chooser.close()
    bootstrap=NativeMediaStorageBootstrap(connection._authority)
    try:bootstrap.prepare(bootstrap.issue_action(),prefs.read())
    finally:bootstrap.close()

    identity=connection._authority.identity
    pc=NativeFilePeer(identity.receiver_id,identity.receiver_identity_sha256,object(),True,True,True,True,True)
    phone_identity=NativeJobCatalogIdentity(peer['device_id'],sha256(phone.unb64(peer['static_public'],32)).hexdigest())
    local=NativeLocalFileGrant(FileGrantState(1,'a'*64,True,False),object(),True)
    remote=NativeFileControlSession(phone_identity,lambda:pc,lambda:local)
    try:
        ended=Event();activity=[]
        if automatic:
            def observe(owner,active):
                assert owner is session
                activity.append(active)
                if timing is not None:timing.event('activity_started' if active else 'activity_ended')
                if not active:ended.set()
            connection._activity_changed=observe
            assert session._timer is None and session._schedule.mode=='manual'
        if timing is not None:timing.start()
        assert connection.send_controls()
        remote.observe_remote(FileControlPacket.parse(wire.receive()['body']),pc)
        packet=remote.packet();at=phone.now_ms()
        deliver(dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='file_transfer.control',
            created_ms=at,expires_ms=at+60_000,body=packet.wire()))
        remote.mark_sent(packet)
        remote.observe_remote(FileControlPacket.parse(wire.receive()['body']),pc)
        policy=prefs.read().policy
        token=policy.videos.destination_token if kind=='video' else policy.destination_token
        assert connection._receive_binding(media_type=kind)==remote.binding(token,sender_is_local=True)
        commands=[]
        def metadata(message):
            operation=message['body']['operation'];commands.append(operation)
            if timing is not None and operation in ('status','discover'):timing.event(operation)
            if operation=='status':
                video_fields={'videos':dict(enabled=True,revision=1)} if kind=='video' else {}
                deliver(response(message,sources.RESULT,version='b'*64,revision=2,enabled=True,associated=True,
                    repair_pending=False,kinds=sorted(sources.KINDS),**video_fields))
            elif operation=='discover':
                video_fields={'media_type':'video'} if kind=='video' else {}
                deliver(response(message,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
                    after=0,next_cursor=None,coverage='full_videos' if kind=='video' else 'full_images',proves_deletion=False,
                    albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)]),**video_fields))
            else:pytest.fail('A shared choice triggered an unrelated permission or configuration command')
        fixture=(service,peer,channel,connection,destination)
        seed=manifest(fixture)
        if kind=='video':
            from base64 import b64decode
            from test_file_desktop_video_album_worker import video_phone
            original=b64decode((Path(__file__).parent/'fixture-original-media.mp4.base64').read_text('ascii'))
            path='Camera/video.mp4'
            def phone_with_batches(batches,**options):return video_phone(fixture,destination,batches,monkeypatch,**options)
        else:
            raw=BytesIO();Image.new('RGB',(5,7),(12,34,56)).save(raw,format='JPEG');original=raw.getvalue()
            path=seed.files[0].path
            def phone_with_batches(batches,**options):return phone_batches(fixture,batches,**options)
        first=replace(seed.files[0],path=path,size=len(original),sha256=sha256(original).hexdigest())
        batch=replace(seed,files=(first,),total_bytes=len(original))
        measurement={'observe':timing.event} if timing is not None else {}
        with phone_with_batches([batch],metadata_handler=metadata,content=original,wire=wire,**measurement) as (chunks,saved,_,_,errors):
            if automatic:
                if timing is not None:timing.mark('deadline_wait_started')
                automatic_mode=session._schedule.mode=='automatic'
                completed=ended.wait(12) if automatic_mode else False
                if timing is not None:
                    timing.checkpoint(deadline_met=completed,automatic_mode=automatic_mode)
                assert automatic_mode and completed, (session.snapshot()['error'],activity,commands,session._automatic_paused)
                assert activity==[True,False]
            else:session.start('sync_shared')
            assert session.join(35) and session.snapshot()['state']=='complete',session.snapshot()
            assert not errors and len(chunks)==len(saved)==1
        local_path=destination/first.path
        assert local_path.read_bytes()==original and commands==['status','discover']
        # Real local edits to a mapped original survive a subsequent no-change
        # phone inventory. Neither the file bytes nor the transfer grant changes.
        edited=b'private local edit of test original'
        local_path.write_bytes(edited);inode=local_path.stat().st_ino
        again=replace(batch,source_id='8'*32,transfer_id='9'*32,files=(replace(first,id='7'*32),))
        with phone_with_batches([again],metadata_handler=metadata,content=original,wire=wire) as (chunks,saved,_,_,errors):
            session.start('sync_shared')
            assert session.join(35) and session.snapshot()['state']=='complete',session.snapshot()
            assert not errors and not chunks and not saved
        assert local_path.read_bytes()==edited and local_path.stat().st_ino==inode
        if kind=='video':assert not list(photo_directory.iterdir())
    finally:remote.close()
