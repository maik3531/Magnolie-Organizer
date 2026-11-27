"""Admission through the actual original reader and native photo action."""
from hashlib import sha256
from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
import magnolie_file_sources as sources
from magnolie_file_control import FileControlPacket, FileGrantState, NativeFileControlSession, NativeFilePeer, NativeLocalFileGrant
from magnolie_media_retention import NativeMediaRetention
from magnolie_photo_destination import NativePhotoDestinationController, photo_folder_component
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_sources import response
from test_file_video_authority import ack_all
from test_media_support_draft import capture_authenticated_binding, legacy_state, offer, ack, wire_pair
from test_media_transport import incoming


@pytest.mark.parametrize('outcome', ['stop_before_echo', 'stop_during_status', 'remote_off', 'local_off',
                                      'read_missing', 'read_allowed', 'worker', 'book_changed'])
def test_manual_first_receive_waits_for_explicit_start_and_original_file_controls(native, tmp_path, monkeypatch, outcome):
    service, peer, _ = native
    peer['capabilities'] = legacy_state()
    service.store.save_peers()
    monkeypatch.setattr(service, '_native_media_support_checked', True)
    monkeypatch.setattr(service, '_resume_automatic_photos', lambda *_: None)
    pictures = tmp_path / 'Pictures'
    pictures.mkdir(mode=0o700)
    choose = NativePhotoDestinationController.choose_default
    monkeypatch.setattr(NativePhotoDestinationController, 'choose_default',
                        lambda self, action: choose(self, action, pictures_provider=lambda: pictures))
    book = tmp_path / 'daten.json'
    book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":30}}}', encoding='utf-8')
    book.chmod(0o600)
    with NativeMediaRetention(service.store.root) as retention:
        assert retention.adopt_existing_saved()

    with wire_pair() as (channel, wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, 'wifi', file_binding=binding)

        def dispatch(message):
            wire.send(message)
            service._payload(peer, channel, channel.receive())

        def quiet():
            wire.sock.settimeout(.10)
            with pytest.raises(TimeoutError):
                wire.receive()
            wire.sock.settimeout(2)

        try:
            ack_all(service, peer, channel)
            probe = offer(phone.now_ms())
            dispatch(probe)
            submitted = wire.receive()
            assert wire.receive() == ack(probe)
            dispatch(ack(submitted))
            connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
            connection._media_transport.change('enabled', True)
            settings = connection._media_transport.send_settings()
            assert wire.receive() == settings
            dispatch(ack(settings))
            at = phone.now_ms()
            echo = dict(incoming(settings['body']), created_ms=at, expires_ms=at + 60_000)
            dispatch(echo)
            assert wire.receive() == ack(echo)
            finger = phone.fingerprint(phone.unb64(peer['static_public'], 32))

            def start(action):
                service.photo_sync_action(peer['device_id'], finger, {'action': action})

            state = service.photo_sync_state(peer['device_id'])
            assert state['shared_media']['agreed'] and state['manual_image_receive']
            assert connection._preferences.read().policy is None
            assert not list(pictures.iterdir())
            assert connection._album_worker is None and connection._mapped_worker is None
            quiet()
            if outcome == 'local_off':
                with connection._operation():
                    prefs=connection._preferences
                    opted_out=prefs.configure(prefs.issue_action(), prefs.read(), enabled=False, mode='manual')
                    connection._local()
                assert not service.photo_sync_state(peer['device_id'])['manual_image_receive']
                with pytest.raises(TransferError, match='photo_schedule_not_ready'):
                    start('sync_shared')
                assert connection._preferences.read() == opted_out
                assert not list(pictures.iterdir())
                quiet()
                return

            start('sync_shared')
            control = wire.receive()
            assert control['kind'] == 'file_transfer.control'
            packet = FileControlPacket.parse(control['body'])
            grant = packet.grants
            session = connection.desktop_session()
            assert grant.receive_files and not grant.send_files
            with connection._operation(incoming=True):
                saved = connection._preferences.read().policy
            assert saved.enabled and saved.sending is None and saved.videos is None
            assert Path(saved.destination.path) == pictures / photo_folder_component(peer['display_name'])
            assert session._schedule.active is None and not session._sync_active
            assert connection._album_worker is None and connection._mapped_worker is None
            quiet()
            if outcome == 'stop_before_echo':
                start('stop')
                assert session.join(3)
                quiet()
                return

            identity = connection._authority.identity
            desktop = NativeFilePeer(identity.receiver_id, identity.receiver_identity_sha256,
                                     object(), True, True, True, True, True)
            origin = NativeJobCatalogIdentity(peer['device_id'], sha256(phone.unb64(peer['static_public'],32)).hexdigest())
            owner = object()
            grant_state = NativeLocalFileGrant(FileGrantState(1, 'a'*64, False, False), owner, True)
            remote = NativeFileControlSession(origin, lambda: desktop, lambda: grant_state)
            remote.observe_remote(packet, desktop)

            def send_control():
                outgoing = remote.packet()
                at = phone.now_ms()
                dispatch(dict(type='message', v=1, message_id=str(uuid4()), kind='file_transfer.control',
                              created_ms=at, expires_ms=at + 60_000, body=outgoing.wire()))
                remote.mark_sent(outgoing)

            send_control()
            remote.observe_remote(FileControlPacket.parse(wire.receive()['body']), desktop)
            send_control()
            status = wire.receive()
            assert status['body']['operation'] == 'status'
            remote_off = outcome == 'remote_off'
            before = response(status, sources.RESULT, version='b'*64, revision=2 if remote_off else 0,
                              enabled=False, associated=remote_off, repair_pending=False,
                              kinds=sorted(sources.KINDS) if remote_off else [])
            if outcome == 'stop_during_status':
                start('stop')
                assert session.join(3)
                dispatch(before)
                assert connection._source_pending is None and connection._source_status is None
                quiet()
                return
            dispatch(before)
            if remote_off:
                assert session.join(3)
                assert session.snapshot()['error'] == 'media_source_shared_incoming_review_required'
                quiet()
                return
            configure = wire.receive()
            assert configure['body']['operation'] == 'configure' and configure['body']['enabled'] is True
            assert configure['body']['expected_version'] == before['body']['version']
            assert configure['expires_ms'] <= status['expires_ms'] + 2
            dispatch(response(configure, sources.RESULT, version='c'*64, revision=2, enabled=True,
                              associated=True, repair_pending=False, kinds=sorted(sources.KINDS)))
            quiet()  # Positive source metadata is not the fresh SEND echo.
            assert session._schedule.active is None and not session._sync_active
            grant_state = NativeLocalFileGrant(FileGrantState(2, 'd'*64, True, False), owner, True)
            send_control()
            remote.observe_remote(FileControlPacket.parse(wire.receive()['body']), desktop)
            send_control()
            discover = wire.receive()
            assert discover['body']['operation'] == 'discover' and discover['expires_ms'] <= status['expires_ms'] + 2
            assert session._schedule.active is None and not session._sync_active
            coverage = 'none' if outcome == 'read_missing' else 'full_images'
            album_id = str(uuid4())
            albums = [dict(album_id=album_id, kind='camera', display_name='Camera',
                           visible_images=1, needs_choice=False)] if outcome == 'worker' else []
            catalog = response(discover, sources.CATALOG, version='c'*64,
                               page=dict(format=1, catalog_id=str(uuid4()), after=0, next_cursor=None,
                                         coverage=coverage, proves_deletion=False, albums=albums))
            if outcome == 'book_changed':
                changed = {'einstellungen': {'papierkorb': {'an': True, 'tage': 7}}}
                with NativeMediaRetention(service.store.root) as retention:
                    paused = retention.pause()
                    book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":7}}}', encoding='utf-8')
                    retention.publish_saved(paused, changed)
            dispatch(catalog)
            if outcome == 'read_missing':
                request = wire.receive()
                assert request['body']['operation'] == 'request_read' and request['body'].get('media_type', 'images') == 'images'
                dispatch(response(request, sources.PERMISSION_RESULT, version='c'*64, state='notification_posted'))
            if outcome == 'worker':
                request = wire.receive()
                assert request['body']['operation'] == 'batch_run' and request['body']['album_id'] == album_id
                assert session._schedule.active is not None and session._sync_active and connection._album_worker is not None
                run=dict(version='c'*64, run_id=str(uuid4()), source_io_ended=True)
                dispatch(response(request, sources.RUN_RESULT, **run, state='empty_ready', batch_end=True))
                cancel=wire.receive()
                assert cancel['body']['operation']=='cancel_run'
                dispatch(response(cancel, sources.RUN_RESULT, **run, state='canceled_held', batch_end=True))
                end=wire.receive()
                assert end['body']['operation']=='end_run'
                dispatch(response(end, sources.RUN_RESULT, **run, state='canceled_held', run_ended=True))
            assert session.join(3), session.snapshot()
            expected = {'read_allowed': 'complete', 'worker': 'complete',
                        'read_missing': 'permission_required', 'book_changed': 'held'}
            assert session.snapshot()['state'] == expected[outcome], session.snapshot()
            if outcome == 'book_changed':
                assert session.snapshot()['error'] == 'media_retention_lease_changed'
            quiet()
            assert session._schedule.active is None and not session._sync_active
            assert connection._album_worker is None and connection._source_pending is None
            assert not list(Path(saved.destination.path).iterdir())
        finally:
            service._end_native_file_connection(channel)
