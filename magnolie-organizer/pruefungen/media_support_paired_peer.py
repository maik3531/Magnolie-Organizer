"""Disposable FS1 peer for the actual Notes session reader; never discovers a phone."""

from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from test_telefon import FakeBluetooth, _complete_peer
from magnolie_file_desktop_connection import NativeDesktopFileConnection
import magnolie_telefon as phone
from magnolie_telefon import (PAIR_FRAME_MAX, PhoneService, native_file_pairing_epoch,
                              now_ms, receive_frame, unb64)


class Desktop(PhoneService):
    ping = None
    heartbeat = False

    def _payload(self, peer, channel, payload, scoped_reference=None):
        super()._payload(peer, channel, payload, scoped_reference)
        attempt = self._native_media_support.get(channel)
        if self.ping is None and attempt is not None and attempt.supports(channel):
            assert self.connections[peer['device_id']] is channel
            assert not self._native_file_connections
            # This fixture grants no contacts/identifier permissions. The
            # separate reader matrix checks the fully populated legacy list.
            versions = peer['capabilities']['items']['device_status']['versions']
            assert versions == [1, 2, 3, 11, 12, 13, 21, 22], versions
            self.ping = str(uuid4())
            channel.send(dict(type='ping', ping_id=self.ping, sent_ms=now_ms()))
        if self.ping is not None and payload.get('type') == 'pong' and payload.get('ping_id') == self.ping:
            assert attempt.supports(channel) and not self._native_file_connections
            self.heartbeat = True
            channel.send(dict(type='close', reason='normal'))


def main():
    with TemporaryDirectory(prefix='magnolie-media-paired-') as root, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        service = Desktop(str(Path(root) / 'telefon'), 'Isolated desktop', bluetooth_backend=FakeBluetooth())
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
        with listener.accept()[0] as client:
            client.settimeout(12)
            start = receive_frame(client, PAIR_FRAME_MAX)
            try:
                # Model a photo-capable desktop composition in this disposable
                # process, without editing or reading a user's build configuration.
                with patch.object(phone.optional_phone, 'available', lambda name: name == 'photo_sync'):
                    service._session(client, start)
            except EOFError:
                if not service.heartbeat:
                    raise
        assert service.heartbeat and not service._native_media_support and not service._native_file_connections
        print('same-parent-pong', flush=True)


if __name__ == '__main__':
    main()
