"""Advanced-functions admission with actual signed parent; no host devices."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_camera_ui import NativeWebcamUi
from test_file_authenticated_desktop import native
from test_phone_camera_native_dispatch import connected, probe
from test_phone_camera_receiver import Output
from magnolie_phone_camera_transport import WebcamMediaSocket
from magnolie_phone_webcam import NativeWebcamSession, VIDEO_BYTES, AUDIO_BYTES
import socket
import os
import magnolie_hintergrund as background
from magnolie_phone_camera_ui import open_video


class Video:
    def __init__(self):
        self.closed = False
        self.closes = 0

    def close(self):
        self.closed = True
        self.closes += 1


@pytest.fixture
def ui(connected):
    service, peer, client = connected
    videos = []
    def video(choice):
        value = Video(); videos.append(value); return value
    manager = NativeWebcamUi(service, inventory=lambda: [dict(path='/dev/video42', label='Controlled virtual output')],
        video_factory=video)
    return manager, videos, service, peer, client


def choose(manager):
    prepared = manager.prepare('auto')
    return prepared['action'], prepared['choices'][0]['token']


def test_off_status_and_explicit_kde_refusal_never_inventory_or_open(connected):
    service, _, _ = connected
    manager = NativeWebcamUi(service, inventory=lambda: pytest.fail('inventory while off'),
        video_factory=lambda _: pytest.fail('native open while off'))
    assert manager.status()['phase'] == 'off'
    assert manager.prepare('kdeconnect')['reason'] == 'compatible_extension_required'
    assert service._native_webcam_owner is None


def test_actual_descriptor_identity_is_checked_and_changed_output_is_closed(tmp_path, monkeypatch):
    # Real fstat on a controlled file descriptor; native driver validation itself
    # belongs to LinuxVideoOutput and is not pretended by this test adapter.
    path = tmp_path / 'controlled-output'; path.write_bytes(b'')
    info = path.stat(); outputs = []
    class Held:
        def __init__(self, device):
            self.fd = os.open(device, os.O_WRONLY); self.closed = False; outputs.append(self)
        def close(self):
            if not self.closed: os.close(self.fd); self.closed = True
    monkeypatch.setattr('magnolie_phone_webcam.LinuxVideoOutput', Held)
    choice = dict(path=str(path), identity=(info.st_dev, info.st_ino, info.st_rdev))
    output = open_video(choice)
    try: assert output is outputs[0] and not output.closed
    finally: output.close()
    choice['identity'] = (info.st_dev, info.st_ino + 1, info.st_rdev)
    with pytest.raises(PermissionError): open_video(choice)
    assert outputs[-1].closed


def test_expired_and_cancelled_actions_never_probe_or_open(ui):
    manager, videos, service, _, _ = ui
    now = [10.0]; manager.clock = lambda: now[0]
    action, token = choose(manager)
    now[0] = 70
    with pytest.raises(PermissionError): manager.start(action, token, False, False)
    action, token = choose(manager)
    manager.cancel(action)
    with pytest.raises(PermissionError): manager.start(action, token, False, False)
    assert not videos and service._native_webcam_owner is None


@pytest.mark.parametrize('change', ['generation', 'capabilities', 'channel'])
def test_changed_original_source_cannot_use_old_choice(ui, change):
    manager, videos, service, peer, client = ui
    action, token = choose(manager)
    if change == 'generation': service._generation += 1
    elif change == 'capabilities': client.channel.last_capabilities = dict(client.channel.last_capabilities)
    else: service.connections[peer['device_id']] = None
    with pytest.raises(PermissionError): manager.start(action, token, False, False)
    assert not videos and service._native_webcam_owner is None


def test_failed_prepare_invalidates_older_successful_action(ui):
    manager, videos, service, _, _ = ui
    action, token = choose(manager)
    manager.prepare('kdeconnect')
    with pytest.raises(PermissionError): manager.start(action, token, False, False)
    assert not videos and service._native_webcam_owner is None


def test_source_changed_during_video_open_is_rejected_and_original_fd_closed(ui):
    manager, videos, service, _, _ = ui
    action, token = choose(manager)
    original = manager.video_factory
    def opened(choice):
        video = original(choice); service._generation += 1; return video
    manager.video_factory = opened
    with pytest.raises(PermissionError): manager.start(action, token, False, False)
    assert videos[0].closed and service._native_webcam_owner is None


def test_original_source_is_checked_inside_service_admission_not_only_before_call(ui, monkeypatch):
    manager, videos, service, _, client = ui
    action, token = choose(manager)
    original = service.begin_native_webcam
    def replaced(*args, **settings):
        client.channel.last_capabilities = dict(client.channel.last_capabilities)
        return original(*args, **settings)
    monkeypatch.setattr(service, 'begin_native_webcam', replaced)
    with pytest.raises(PermissionError): manager.start(action, token, False, False)
    assert videos[0].closed and service._native_webcam_owner is None


def test_choice_is_one_use_stop_is_lease_bound_and_unprepared_video_is_closed(ui):
    manager, videos, service, _, client = ui
    action, token = choose(manager)
    result = manager.start(action, token, False, True)
    assert result['enabled'] and not result['active'] and result['front']
    owner = manager.owner
    assert len(videos) == 1 and not videos[0].closed
    client.ack(client.receive())
    with pytest.raises(PermissionError): manager.start(action, token, False, True)
    with pytest.raises(PermissionError): manager.stop('f' * 64)
    assert not owner.stopping.is_set()
    manager.stop(result['lease'])
    assert owner.done.wait(4); owner.worker.join(1)
    assert owner.is_completely_stopped() and videos[0].closed
    assert manager.status()['phase'] == 'off'
    assert service._native_media_activity()['camera'] is False


def test_held_video_factory_never_reopens_path_or_reuses_descriptor(ui):
    manager, videos, _, _, client = ui
    action, token = choose(manager)
    result = manager.start(action, token, True, False)
    client.ack(client.receive())
    # Actual output-session construction, injected audio is unnecessary in mute mode.
    output = manager.owner.output_factory('/dev/video42', lambda: None, muted=True)
    try:
        assert output.video is videos[0]
        with pytest.raises(PermissionError): manager.owner.output_factory('/dev/video42', lambda: None, muted=True)
    finally:
        output.close(); manager.stop(result['lease'])
        assert manager.owner.done.wait(4); manager.owner.worker.join(1)
    assert len(videos) == 1 and videos[0].closed


@pytest.mark.parametrize('payload', [
    {'action': 'start', 'device': '/dev/video42'},
    {'action': 'prepare', 'provider': 'auto', 'enabled': True},
    {'action': 'prepare', 'provider': []},
    {'action': 'start', 'action_token': 'a' * 64, 'choice_token': 'b' * 64, 'muted': 1, 'front': False},
    {'action': 'stop', 'lease': '/dev/video42'},
    {'action': 'cancel', 'action_token': 'a' * 65},
    {'action': 'start', 'url': 'http://phone/video'}, {}, None,
])
def test_ipc_refuses_paths_flags_urls_and_invalid_tokens(payload):
    with pytest.raises(background.IPCError): background._request_shape('phone_webcam_action', {'request': payload})


def test_service_daemon_and_proxy_route_only_ephemeral_tokens_without_status_inventory(ui, monkeypatch):
    manager, videos, service, _, _ = ui
    service._native_webcam_ui = manager
    server = SimpleNamespace(phone_backend=service)
    assert background.IPCServer._phone_operation(server, 'phone_webcam_status', {})['phase'] == 'off'
    calls = []
    def ipc(operation, arguments, path, timeout):
        background._request_shape(operation, arguments)
        calls.append(operation)
        return background.IPCServer._phone_operation(server, operation, arguments)
    monkeypatch.setattr(background, 'ipc_request', ipc)
    proxy = background.PhoneServiceProxy(path='/controlled/no-socket')
    assert not proxy.webcam_status()['enabled']
    result = proxy.webcam_action(dict(action='prepare', provider='notes'))
    assert result['choices'] and not videos
    proxy.webcam_action(dict(action='cancel', action_token=result['action']))
    with pytest.raises(PermissionError):
        proxy.webcam_action(dict(action='start', action_token=result['action'], choice_token=result['choices'][0]['token'], muted=False, front=False))
    assert service._native_webcam_owner is None
    assert calls == ['phone_webcam_status', 'phone_webcam_action', 'phone_webcam_action', 'phone_webcam_action']


def test_base_status_does_not_import_optional_ui_or_probe(connected, monkeypatch):
    service, _, _ = connected
    monkeypatch.setattr('importlib.import_module', lambda *args: pytest.fail('optional import from status'))
    assert service.webcam_status()['phase'] == 'off'
    service._native_camera_built = False
    assert service.webcam_status()['reason'] == 'not_in_build'
    with pytest.raises(PermissionError): service.webcam_action(dict(action='prepare', provider='auto'))


def test_uncertain_cleanup_holds_slot_and_closes_prepared_video_even_if_exchange_close_fails(ui, monkeypatch):
    manager, videos, service, _, client = ui
    action, token = choose(manager)
    result = manager.start(action, token, False, False)
    owner = manager.owner
    client.ack(client.receive()); client.request(probe()); client.report('offer')
    error = RuntimeError('controlled uncertain native unload')
    receipt = object(); error.native_cleanup_owner = receipt
    def failed_close(): raise error
    monkeypatch.setattr(owner.exchange, 'close', failed_close)
    manager.stop(result['lease'])
    assert owner.done.wait(4); owner.worker.join(1)
    assert videos[0].closed and owner.pending_cleanup_owner is receipt
    assert not owner.is_completely_stopped()
    assert manager.status()['phase'] == 'shutdown_pending'
    assert manager.prepare('auto')['reason'] == 'owner_busy'
    assert len(videos) == 1 and service._native_webcam_owner is owner


def test_actual_unix_daemon_proxy_activates_and_stops_original_signed_phone_owner(ui, tmp_path):
    manager, videos, service, _, client = ui
    service._native_webcam_ui = manager
    server = background.IPCServer(None, path=str(tmp_path / 'webcam.sock'), phone_backend=service).start()
    try:
        proxy = background.PhoneServiceProxy(path=server.path)
        assert proxy.webcam_status()['phase'] == 'off' and not videos
        prepared = proxy.webcam_action(dict(action='prepare', provider='auto'))
        result = proxy.webcam_action(dict(action='start', action_token=prepared['action'],
            choice_token=prepared['choices'][0]['token'], muted=False, front=False))
        client.ack(client.receive())
        assert result['enabled'] and len(videos) == 1
        assert not proxy.webcam_status()['active']
        with pytest.raises(background.IPCError):
            proxy.webcam_action(dict(action='start', device='/dev/video42', enabled=True))
        proxy.webcam_action(dict(action='stop', lease=result['lease']))
        assert manager.owner.done.wait(4); manager.owner.worker.join(1)
        assert videos[0].closed and manager.owner.is_completely_stopped()
    finally:
        server.close()


def test_ui_to_real_daemon_signed_parent_and_encrypted_av_reuses_original_held_video(connected, tmp_path, monkeypatch):
    service, _, client = connected
    video = Output('/controlled/original-video')
    manager = NativeWebcamUi(service,
        inventory=lambda: [dict(path='/dev/video42', label='Controlled virtual output')],
        video_factory=lambda choice: video)
    service._native_webcam_ui = manager
    monkeypatch.setattr('magnolie_phone_webcam.NativeWebcamSession',
        lambda *args, **settings: NativeWebcamSession(*args, audio_factory=Output, **settings))
    server = background.IPCServer(None, path=str(tmp_path / 'av.sock'), phone_backend=service).start()
    try:
        proxy = background.PhoneServiceProxy(path=server.path)
        prepared = proxy.webcam_action(dict(action='prepare', provider='notes'))
        result = proxy.webcam_action(dict(action='start', action_token=prepared['action'],
            choice_token=prepared['choices'][0]['token'], muted=False, front=False))
        owner = manager.owner
        client.ack(client.receive())
        original = probe(); client.request(original); offer = client.report('offer')
        with socket.create_connection(('127.0.0.1', offer['port']), timeout=2) as media:
            sender = WebcamMediaSocket(media, offer['session'], bytes.fromhex(offer['secret']), owner.current, sending=True)
            client.request(dict(original, op='prepared', session=offer['session']))
            client.report('send')
            outputs = owner.exchange.run.outputs
            assert outputs.video is video and not proxy.webcam_status()['active']
            sender.send('video', 0, 0, b'v' * VIDEO_BYTES)
            assert video.arrived.wait(2)
            assert not proxy.webcam_status()['active']
            sender.send('audio', 0, 0, b'a' * AUDIO_BYTES)
            assert outputs.audio.arrived.wait(2)
            assert proxy.webcam_status()['active']
            proxy.webcam_action(dict(action='stop', lease=result['lease']))
            assert owner.done.wait(4); owner.worker.join(1)
            assert owner.is_completely_stopped() and video.closed and outputs.audio.closed
            assert not proxy.webcam_status()['active']
    finally:
        server.close()
