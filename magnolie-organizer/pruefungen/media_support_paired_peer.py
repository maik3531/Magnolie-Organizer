"""Disposable FS1 peer for the actual Notes session reader; never discovers a phone."""

from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from test_telefon import FakeBluetooth, _complete_peer
from magnolie_file_control import KIND as FILE_CONTROL_KIND, VIDEO_DISCOVERY_VERSION, FileControlPacket, FileGrantState
from magnolie_file_desktop_connection import NativeDesktopFileConnection
import magnolie_telefon as phone
from magnolie_telefon import (PAIR_FRAME_MAX, PhoneService, native_file_pairing_epoch,
                              now_ms, receive_frame, unb64)


class Desktop(PhoneService):
    ping = None
    heartbeat = False
    test_settings = False
    settings_owner = None
    resumed = False
    video_sender = False
    video_control_sent = False
    closed_video_owner = False

    def _payload(self, peer, channel, payload, scoped_reference=None):
        if self.video_control_sent and payload.get('kind') == FILE_CONTROL_KIND:
            grants = FileControlPacket.parse(payload['body']).grants
            assert not grants.send_files and not grants.receive_files
            if not self.closed_video_owner:
                self.closed_video_owner = True
                self.ping = str(uuid4())
                channel.send(dict(type='ping', ping_id=self.ping, sent_ms=now_ms()))
            return
        super()._payload(peer, channel, payload, scoped_reference)
        attempt = self._native_media_support.get(channel)
        if self.ping is None and attempt is not None and attempt.supports(channel):
            assert self.connections[peer['device_id']] is channel
            # This fixture grants no contacts/identifier permissions. The
            # separate reader matrix checks the fully populated legacy list.
            versions = peer['capabilities']['items']['device_status']['versions']
            assert versions == [1, 2, 3, 11, 12, 13, 21, 22], versions
            if self.test_settings:
                if self.settings_owner is None:
                    assert not self._native_file_connections
                    self.settings_owner = self.open_native_file_connection(
                        peer['device_id'], peer['static_public'], channel, self._generation)
                    before = self.settings_owner.desktop_snapshot()['shared_media']
                    assert before['configured'] is self.resumed and not before['agreed']
                    if self.resumed:
                        assert before['values']['enabled'] is True
                    else:
                        self.settings_owner._media_transport.change('enabled', True)
                        if self.video_sender:
                            for field, value in (
                                ('collection_mode', 'entire_collection'), ('direction', 'pc_to_phone'),
                                ('photos_enabled', False), ('videos_enabled', True),
                            ):
                                self.settings_owner._media_transport.change(field, value)
                    self.settings_owner._media_transport.send_settings()
                owner = self.settings_owner
                state = owner.desktop_snapshot()['shared_media']
                if not state['agreed']:
                    return
                assert state['values']['enabled'] is True
                assert owner._media_source is None and owner._desktop_session is None
                assert owner._preferences.read().policy is None
                if self.video_sender:
                    assert state['values']['videos_enabled'] and not state['values']['photos_enabled']
                    if not self.video_control_sent:
                        self.video_control_sent = True
                        at = now_ms()
                        control = FileControlPacket(FileGrantState(1, 'a'*64, send_files=True), 'b'*64, 1, None)
                        channel.send(dict(type='message', v=1, kind=FILE_CONTROL_KIND, message_id=str(uuid4()),
                                          created_ms=at, expires_ms=at+10_000, body=control.wire()))
                    return
            else:
                assert not self._native_file_connections
            self.ping = str(uuid4())
            channel.send(dict(type='ping', ping_id=self.ping, sent_ms=now_ms()))
        if self.ping is not None and payload.get('type') == 'pong' and payload.get('ping_id') == self.ping:
            assert attempt.supports(channel)
            self.heartbeat = True
            channel.send(dict(type='close', reason='normal'))


def main(test_settings=False, reconnect=False, video_sender=False):
    with TemporaryDirectory(prefix='magnolie-media-paired-') as root, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        service = Desktop(str(Path(root) / 'telefon'), 'Isolated desktop', bluetooth_backend=FakeBluetooth())
        service.test_settings = test_settings
        service.video_sender = video_sender
        service.enabled = service._native_media_support_checked = service._native_photo_built = True
        service.native_screen_included = False
        NativeDesktopFileConnection._data_handlers_ready = True
        identity = service.store.identity
        print(listener.getsockname()[1], identity['device_id'], identity['static_public'], flush=True)
        peer_id, public = sys.stdin.readline().split()
        peer = _complete_peer(peer_id, public=unb64(public, 32))
        peer['grants'] = {}
        peer['file_pairing_epoch'] = native_file_pairing_epoch(bytes([1])*32)
        peer['personal_sync'].update(own_device=True, remote_own_device=True)
        service.store.peers = [peer]
        service.store.save_peers()
        desktop_capabilities = phone.desktop_capabilities

        def fixture_capabilities(*args, **kwargs):
            capabilities = desktop_capabilities(*args, **kwargs)
            if video_sender:
                capabilities['items']['device_status']['versions'].append(VIDEO_DISCOVERY_VERSION)
            return capabilities

        for resumed in range(2 if reconnect else 1):
            service.resumed = bool(resumed)
            service.ping = service.settings_owner = None
            service.heartbeat = False
            with listener.accept()[0] as client:
                client.settimeout(12)
                start = receive_frame(client, PAIR_FRAME_MAX)
                try:
                    # Model a photo-capable desktop composition in this disposable
                    # process, without editing or reading a user's build configuration.
                    with (patch.object(phone.optional_phone, 'available', lambda name: name == 'photo_sync'),
                          patch.object(phone, 'desktop_capabilities', fixture_capabilities)):
                        service._session(client, start)
                except EOFError:
                    if not service.heartbeat:
                        raise
            assert service.heartbeat and not service._native_media_support and not service._native_file_connections
            assert not video_sender or service.closed_video_owner
            print('same-parent-pong', flush=True)


if __name__ == '__main__':
    assert sys.argv[1:] in ([], ['--settings'], ['--reconnect'], ['--video-sender'])
    main(test_settings=bool(sys.argv[1:]), reconnect=sys.argv[1:] == ['--reconnect'],
         video_sender=sys.argv[1:] == ['--video-sender'])
