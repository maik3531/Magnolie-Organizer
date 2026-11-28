"""Mixed challenge on the original encrypted reader, before file work."""
from contextlib import closing

import pytest

import magnolie_telefon as phone
from magnolie_file_control import FileControlPacket, FileGrantState, KIND as CONTROL
from magnolie_file_transfer import TransferError
from magnolie_media_mixed_preflight import REQUEST, create_ready_result
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_source_roots import ProtectedMediaCollectionRoots
from magnolie_media_support import PC_IMAGE_BATCH, SHARED_SETTINGS, ack, offer
from test_file_authenticated_desktop import native
from test_file_video_authority import ack_all
from test_media_source_sender import message
from test_media_support_draft import capture_authenticated_binding, legacy_state, wire_pair


def test_mixed_preflight_waits_for_both_roots_exact_reply_and_current_local_run(native, tmp_path, monkeypatch):
    service, peer, _ = native
    peer['capabilities'] = legacy_state()
    service.store.save_peers()
    for key in ('_native_media_support_checked', '_native_pc_video_checked', '_native_pc_image_batch_checked'):
        monkeypatch.setattr(service, key, True)
    monkeypatch.setattr(service, '_resume_automatic_photos', lambda *_: None)
    book = tmp_path / 'daten.json'
    book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":30}}}', encoding='utf-8')
    book.chmod(0o600)
    with NativeMediaRetention(service.store.root) as retention:
        assert retention.adopt_existing_saved()
    with wire_pair() as (channel, wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, 'wifi', file_binding=binding)

        def dispatch(packet):
            wire.send(packet)
            service._payload(peer, channel, channel.receive())

        try:
            ack_all(service, peer, channel)
            for feature in (SHARED_SETTINGS, PC_IMAGE_BATCH):
                remote = offer(phone.now_ms(), feature)
                dispatch(remote)
                sent = wire.receive()
                assert sent['body']['feature'] == feature
                assert wire.receive() == ack(remote)
                dispatch(ack(sent))
            connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
            connection._private_pc_mixed_runtime = True
            transport = connection._media_transport
            for field, value in (('direction', 'pc_to_phone'), ('collection_mode', 'entire_collection'),
                                 ('enabled', True), ('videos_enabled', True)):
                transport.change(field, value)
            sent = transport.send_settings()
            assert wire.receive() == sent
            dispatch(ack(sent))
            echo = message('file_transfer.shared_settings', sent['body'])
            dispatch(echo)
            assert wire.receive() == ack(echo)
            intent = connection._private_mixed_collection_intent()
            assert intent is transport.intent_for('video', to_phone=True)
            assert intent is not None

            preferences = connection._preferences
            saved = preferences.configure_sending(preferences.issue_action(), preferences.read(), photos=True, videos=True)
            assert connection.send_controls()
            first = FileControlPacket.parse(wire.receive()['body'])
            assert first.grants.send_files and not first.grants.receive_files
            remote = FileControlPacket(FileGrantState(1, '6' * 64, False, True), '7' * 64, 1, first.challenge)
            dispatch(message(CONTROL, remote.wire()))
            assert FileControlPacket.parse(wire.receive()['body']).echo == remote.challenge
            controls = connection._controls.binding('0' * 64, sender_is_local=True)
            assert controls is not None
            live = True
            with pytest.raises(TransferError, match='both_roots_required'):
                connection.begin_mixed_pc_preflight(lambda: live)
            with closing(ProtectedMediaCollectionRoots(connection._authority)) as catalog:
                for kind in ('images', 'videos'):
                    path = tmp_path / kind
                    path.mkdir(mode=0o700)
                    with NativeCollectionRoot(path, lambda: True) as root:
                        catalog.add(catalog.issue_action(), catalog.read(), root, kind)
                preferences.bind_collection_roots(preferences.issue_action(), saved, catalog)
            connection._local()

            first_pending = connection.begin_mixed_pc_preflight(lambda: live)
            first_request = wire.receive()
            assert first_request['kind'] == REQUEST
            with pytest.raises(TransferError):
                connection.finish_mixed_pc_preflight(first_pending, accept=True)
            stale = create_ready_result(first_request, intent.body, controls, phone.now_ms())
            with pytest.raises(TransferError):
                dispatch(stale)

            second_pending = connection.begin_mixed_pc_preflight(lambda: live)
            second_request = wire.receive()
            assert first_request['message_id'] != second_request['message_id']
            dispatch(create_ready_result(second_request, intent.body, controls, phone.now_ms()))
            assert second_pending.wait_for_reply(lambda: False)
            admitted = connection.finish_mixed_pc_preflight(second_pending, accept=True)
            worker = object()
            admitted.claim(worker)
            admitted.require_boundary(worker)
            live = False
            with pytest.raises(TransferError, match='original_owner_required'):
                admitted.require_worker(worker)
            connection.finish_mixed_pc_pass(admitted)
            assert connection._mapped_worker is None and connection._media_sender is None
            assert not list((tmp_path / 'images').iterdir()) and not list((tmp_path / 'videos').iterdir())
        finally:
            service._end_native_file_connection(channel)
