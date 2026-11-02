"""Actual service reserved dispatch/control ownership; data handlers stay OFF."""
from pathlib import Path
import sys
import threading
import uuid
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
from magnolie_file_control import KIND, FileControlPacket, FileGrantState
from magnolie_file_desktop_connection import is_reserved_file_message, NativeDesktopFileConnection
from magnolie_photo_destination import NativePhotoDestinationController
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native, bind


@pytest.fixture
def attached(native):
    service, peer, _ = native
    channel, binding = bind(service, peer)
    connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
    try: yield service, peer, channel, binding, connection
    finally: service._end_native_file_connection(channel)


def control(*, receive=True):
    at = phone.now_ms()
    packet = FileControlPacket(FileGrantState(1, 'a'*64, False, receive), 'b'*64, 1, None)
    return dict(type='message', v=1, kind=KIND, message_id=str(uuid.uuid4()),
                created_ms=at, expires_ms=at+60_000, body=packet.wire())


def forbid_legacy(service, monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('Reserved file route touched personal/legacy persistence')
    for name in ('peer', 'sole_peer', 'remember_message', 'dedupe_result', 'queue'):
        monkeypatch.setattr(service.store, name, forbidden)


def test_native_attachment_is_inert_no_preferences_or_send_and_no_second_owner(attached):
    service, peer, channel, binding, connection = attached
    channel.send.assert_not_called()
    assert connection.read_preferences().policy is None
    assert not list(Path(service.store.root).glob('photo-preferences-v1-*'))
    with pytest.raises(ValueError, match='busy'):
        service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
    assert not connection._authority.protection._closed


def test_actual_reserved_dispatch_joins_control_echo_without_personal_defaults_or_data_grants(attached, monkeypatch):
    service, peer, channel, _, connection = attached
    forbid_legacy(service, monkeypatch)
    message = control()
    service._payload(peer, channel, message)
    reply = channel.send.call_args.args[0]
    local = FileControlPacket.parse(reply['body'])
    assert reply['kind'] == KIND and local.echo == FileControlPacket.parse(message['body']).challenge
    assert not local.grants.send_files and not local.grants.receive_files
    assert connection._controls._sent_grants == local.grants
    assert connection._controls.binding('f'*64) is None
    service._payload(peer, channel, message)
    assert channel.send.call_count == 1
    assert 21 not in phone.desktop_capabilities()['items']['device_status']['versions']


@pytest.mark.parametrize('kind', ['file_transfer.control', 'file_transfer.offer', 'file_transfer.accept',
    'file_transfer.chunk.request', 'file_transfer.chunk', 'file_transfer.saved',
    'file_transfer.sources.request', 'file_transfer.sources.run_result', 'file_transfer.future'])
def test_unattached_reserved_namespace_never_enters_personal_or_legacy_replay(native, monkeypatch, kind):
    service, peer, _ = native
    channel, _ = bind(service, peer)
    forbid_legacy(service, monkeypatch)
    message = control(); message['kind'] = kind
    assert is_reserved_file_message(message)
    with pytest.raises(ValueError, match='route_unavailable'): service._payload(peer, channel, message)
    channel.send.assert_not_called()
    assert not list(Path(service.store.root).glob('photo-preferences-v1-*'))


@pytest.mark.parametrize('kind', ['file_transfer.offer', 'file_transfer.chunk', 'file_transfer.sources.result'])
def test_unsupported_data_is_rejected_even_with_native_control_owner(attached, monkeypatch, kind):
    service, peer, channel, _, connection = attached
    forbid_legacy(service, monkeypatch)
    message = control(); message['kind'] = kind
    with pytest.raises(TransferError): service._payload(peer, channel, message)
    channel.send.assert_not_called()
    assert connection.read_preferences().policy is None


def test_failed_actual_secure_output_is_not_recorded_as_native_send_completion(attached):
    service, peer, channel, _, connection = attached
    channel.send.side_effect = OSError('synthetic actual secure-output failure')
    with pytest.raises(OSError): service._payload(peer, channel, control())
    assert connection._controls._sent_grants is None
    channel.send.side_effect = None
    assert connection.send_controls()
    assert connection._controls._sent_grants is not None


def test_socket_write_expiry_does_not_mark_native_control_send_complete(attached):
    _, _, channel, _, connection = attached
    clock = [phone.now_ms()]
    channel.send.side_effect = lambda message: clock.__setitem__(0, clock[0]+60_000)
    with pytest.raises(TransferError): connection.send_controls(clock=lambda: clock[0])
    assert connection._controls._sent_grants is None


def test_transport_replacement_revokes_and_cannot_reuse_old_native_controller(attached):
    service, peer, channel, binding, connection = attached
    replacement, _ = bind(service, peer)
    assert channel not in service._native_file_connections and connection._closed.is_set()
    assert connection._authority.protection._closed
    with pytest.raises(TransferError): connection.send_controls()
    assert service.current_native_file_identity(peer['device_id'], peer['static_public'], channel, binding.generation) is None
    service._end_native_file_connection(replacement)


def test_close_during_actual_control_write_retains_resources_until_real_end(attached, monkeypatch):
    service, peer, channel, binding, connection = attached
    entered = threading.Event(); release = threading.Event(); ended = threading.Event(); errors = []
    def blocked(message):
        assert not service.lock._is_owned()
        entered.set(); assert release.wait(5)
    channel.send.side_effect = blocked
    def receive():
        try: service._payload(peer, channel, control())
        except Exception as error: errors.append(error)
        finally: ended.set()
    worker = threading.Thread(target=receive); worker.start()
    try:
        assert entered.wait(5)
        with pytest.raises(TransferError, match='busy'): connection.read_preferences()
        service._end_native_file_connection(channel)
        assert connection._closed.is_set() and not connection._authority.protection._closed
        assert connection._controls._sent_grants is None
        with pytest.raises(ValueError): service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
        release.set(); assert ended.wait(5); worker.join(5)
        assert len(errors) == 1 and isinstance(errors[0], TransferError)
        assert connection._authority.protection._closed and connection._controls._sent_grants is None
    finally:
        release.set(); worker.join(5)
        assert not worker.is_alive()


def test_stale_channel_or_pinned_key_cannot_reach_attached_native_route(attached, monkeypatch):
    service, peer, channel, _, _ = attached
    forbid_legacy(service, monkeypatch)
    wrong = dict(peer, static_public=phone.b64(bytes([99])*32))
    for selected, owner in ((wrong, channel), (peer, mock.Mock())):
        with pytest.raises(ValueError): service._payload(selected, owner, control())
    channel.send.assert_not_called()


def test_foreign_output_channel_cannot_adopt_a_valid_native_authority(native):
    service, peer, _ = native
    channel, binding = bind(service, peer)
    authority = service.open_native_file_authority(peer['device_id'], peer['static_public'], channel, binding.generation)
    try:
        with pytest.raises(TransferError, match='native_owner_required'):
            NativeDesktopFileConnection(authority, mock.Mock())
        assert authority.current_peer() is not None
    finally: authority.close()


def test_saved_enabled_policy_does_not_announce_receive_before_real_data_handlers(attached, tmp_path):
    _, _, channel, _, connection = attached
    destination = tmp_path / 'explicit-choice'; destination.mkdir(mode=0o700)
    chooser = NativePhotoDestinationController(connection._authority)
    try:
        choice = chooser.choose_custom(chooser.issue_action(), destination)
        prefs = connection._preferences
        saved = prefs.configure(prefs.issue_action(), prefs.read(), enabled=True, mode='automatic', destination_choice=choice)
        assert saved.associated and saved.destination_available
        assert connection.send_controls()
        packet = FileControlPacket.parse(channel.send.call_args.args[0]['body'])
        assert not packet.grants.send_files and not packet.grants.receive_files
        assert connection._controls.binding(choice.destination_token) is None
        assert not list(destination.iterdir())
    finally: chooser.close()


@pytest.mark.parametrize('kind', ['file_transfer.control', 'file_transfer.accept', 'file_transfer.sources.request', 'file_transfer.future'])
def test_reserved_output_cannot_use_legacy_global_grants_or_outbox(attached, monkeypatch, kind):
    service, peer, channel, _, _ = attached
    forbid_legacy(service, monkeypatch)
    message = control(); message['kind'] = kind
    assert service._send_message(channel, peer['device_id'], message) is False
    assert service._send_message_locked(channel, peer['device_id'], message) is False
    channel.send.assert_not_called()
