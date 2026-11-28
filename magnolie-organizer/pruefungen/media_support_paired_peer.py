"""Disposable FS1 peer for the actual Notes session reader; never discovers a phone."""

import base64
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

from test_telefon import FakeBluetooth, _complete_peer
from magnolie_file_control import KIND as FILE_CONTROL_KIND, VIDEO_DISCOVERY_VERSION, FileControlPacket, FileGrantState
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_file_accept_message import KIND as ACCEPT
from magnolie_file_saved_message import KIND as SAVED
from magnolie_file_published_readback import KIND as READBACK
from magnolie_media_mixed_preflight import RESULT as MIXED_READY
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_source_choice import NativeCollectionRoot, native_folder_witness
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_retirement import _NativeSourceRetirementJournal
import magnolie_telefon as phone
from magnolie_telefon import (PAIR_FRAME_MAX, PhoneService, native_file_pairing_epoch,
                              fingerprint, now_ms, receive_frame, unb64)


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


class MixedDesktop(PhoneService):
    """Real control, shared agreement, picker, manual action and original source END."""
    phase = 'settings'

    def _payload(self, peer, channel, payload, scoped_reference=None):
        super()._payload(peer, channel, payload, scoped_reference)
        support = self._native_media_support.get(channel)
        if support is None or not support.supports(channel):
            return
        owner = self._native_file_connections.get(channel)
        peer_id = peer['device_id']
        fpr = fingerprint(unb64(peer['static_public'], 32))
        kind = payload.get('kind')
        ping_id = payload.get('ping_id')

        def sync():
            self.photo_sync_action(peer_id, fpr, dict(action='sync_shared'))

        if self.phase == 'settings' and owner is None:
            state = self.photo_sync_state(peer_id)['shared_media']
            self.photo_sync_action(peer_id, fpr, dict(action='shared_setting', field='direction',
                                   value='pc_to_phone', version=state['version']))
            owner = self._native_file_connections[channel]
            for field, value in [('collection_mode', 'entire_collection'), ('videos_enabled', True), ('enabled', True)]:
                owner._media_transport.change(field, value)
            owner._media_transport.send_settings()
            self.phase = 'agree'
        elif self.phase == 'agree' and owner._private_mixed_collection_intent() is not None:
            state = owner.desktop_snapshot()
            assert state['sending_choice_kinds'] == ['photos', 'videos']
            assert not state['collection_manual_outgoing_ready']
            choice = self.photo_sync_sending_consent(peer_id, fpr, 'prepare', True, True, None,
                                                     state['sending_consent']['version'])
            granted = self.photo_sync_sending_consent(peer_id, fpr, 'commit', None, None, choice['selection'], None)
            assert granted['photos'] and granted['videos']
            self.phase = 'closed'
        elif self.phase == 'closed' and kind == FILE_CONTROL_KIND:
            assert not FileControlPacket.parse(payload['body']).grants.receive_files
            self.phase = 'receive'
            print('mixed-closed-owner', flush=True)
        elif self.phase == 'receive' and ping_id == '2222d686-6130-4125-b60a-e43c2832a9bc':
            assert owner._controls._remote.grants.receive_files
            self.ping = str(uuid4())
            channel.send(dict(type='ping', ping_id=self.ping, sent_ms=now_ms()))
        elif self.phase == 'receive' and payload.get('type') == 'pong' and ping_id == self.ping:
            assert owner._controls._remote.grants.receive_files and not owner._controls._remote.grants.send_files
            self._pick_roots(owner, peer_id, fpr)
            self.phase = 'photo-only'
            started = monotonic()
            sync()

            def check_missing_video():
                session = owner.desktop_session()
                assert session.join(16), session.snapshot()
                state = session.snapshot()
                assert monotonic() - started >= 9.5
                assert state['state'] == 'held' and state['error'] == 'media_mixed_preflight_current_owner_required', state
                assert state['saved_files'] == 0 and state['known_files'] == 0
                assert owner._mixed_preflight is None and owner._mapped_worker is None and owner._media_sender is None
                assert self.phase == 'photo-only'
                self.phase = 'both'
                print('mixed-photo-only-held', flush=True)

            Thread(target=check_missing_video, name='mixed-negative-proof').start()
        elif self.phase == 'both' and ping_id == 'b15ff3d5-b4b5-4948-adb7-99795dcadb42':
            self.ended = []
            self.phase = 'preflight'
            sync()
        elif self.phase == 'preflight' and kind == MIXED_READY:
            self.phase = 'offer'
        elif self.phase == 'offer' and kind == ACCEPT:
            sender = owner._media_sender
            self.job = sender._job
            self.offer = sender._record.body['offer']
            expected_kind = 'video' if self.ended else 'images'
            body = self.offer['body']
            assert body['format'] == (3 if expected_kind == 'images' else 2)
            assert body['media_type'] == expected_kind and not body['originals']
            assert len(sender._cache.manifest.files) == 1
            assert payload['body']['offer_id'] == self.offer['message_id']
            self._require_archived(owner)
            self.phase = 'copy'
        elif self.phase == 'copy' and kind == SAVED:
            self.saved = payload
            self.phase = 'readback'
        elif self.phase == 'readback' and kind == READBACK:
            assert payload['body']['format'] == (2 if self.offer['body']['format'] == 3 else 1)
            assert payload['body']['offer_id'] == self.offer['message_id']
            assert payload['expires_ms'] <= self.saved['expires_ms'] <= self.offer['expires_ms']
            self.ended.append(self.job)
            self.phase = 'offer'
            if len(self.ended) == 2:
                session = owner.desktop_session()
                assert session.join(35) and session.snapshot()['state'] == 'complete', session.snapshot()
                assert session.snapshot()['saved_files'] == 2
                self._require_archived(owner)
                self.phase = 'repeat'
                sync()
        elif self.phase == 'repeat' and kind == MIXED_READY:
            # The fresh metadata challenge is permitted. No offer, chunk or
            # saved progress may be emitted while the unchanged roots are scanned.
            sequence = channel.send_seq
            session = owner.desktop_session()
            assert session.join(38), session.snapshot()
            status = session.snapshot()
            assert status['state'] == 'complete' and status['known_files'] == 2 and status['saved_files'] == 0, status
            assert channel.send_seq == sequence and owner._media_sender is None and owner._mixed_pass is None
            assert all(path.read_bytes() == raw for path, raw in self.originals.items())
            self.phase = 'done'
            self.heartbeat = True
            print('mixed-archived-both-end-unchanged', flush=True)
            channel.send(dict(type='close', reason='normal'))
        elif kind in (ACCEPT, SAVED, READBACK, MIXED_READY):
            raise AssertionError(f'Unexpected {kind} during {self.phase}')

    def _pick_roots(self, owner, peer_id, fpr):
        label, photo, video = sys.stdin.readline(64_000).split()
        assert label == 'mixed-originals'
        self.originals = {}
        for media_type, name, encoded in [('images', 'original.png', photo), ('video', 'original.mp4', video)]:
            selected_root = Path(self.store.root).parent / media_type
            selected_root.mkdir(mode=0o700)
            raw = base64.b64decode(encoded, validate=True)
            source = selected_root / name
            source.write_bytes(raw)
            self.originals[source] = raw
            version = owner.desktop_snapshot()['shared_media']['version']
            picker = self.photo_sync_collection_choice(peer_id, fpr, 'prepare', media_type, version=version)
            with NativeCollectionRoot(selected_root, lambda: True) as folder:
                selected = self.photo_sync_collection_choice(peer_id, fpr, 'commit', media_type,
                    selection=picker['selection'], path=str(selected_root), witness=native_folder_witness(folder))
        assert len(selected['roots']) == 2 and owner.desktop_snapshot()['collection_manual_outgoing_ready']
        outside = Path(self.store.root).parent / 'not-selected'
        outside.mkdir()
        for source, raw in self.originals.items():
            (outside / source.name).write_bytes(raw)

    def _require_archived(self, owner):
        journal = _NativeSourceRetirementJournal(_NativeSourceJobs(owner._authority))
        assert all(journal.lookup(job).body['state'] == 'archived' for job in self.ended)


def main(test_settings=False, reconnect=False, video_sender=False, mixed=False):
    with TemporaryDirectory(prefix='magnolie-media-paired-') as root, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        desktop = MixedDesktop if mixed else Desktop
        service = desktop(str(Path(root) / 'telefon'), 'Isolated desktop', bluetooth_backend=FakeBluetooth())
        service.test_settings = test_settings
        service.video_sender = video_sender
        service.enabled = service._native_media_support_checked = service._native_photo_built = True
        service.native_screen_included = False
        NativeDesktopFileConnection._data_handlers_ready = True
        if mixed:
            service._native_pc_image_batch_checked = service._native_pc_video_checked = service._native_pc_mixed_checked = True
            book = Path(root) / 'daten.json'
            book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":30}}}', encoding='utf-8')
            book.chmod(0o600)
            with NativeMediaRetention(service.store.root) as retention:
                assert retention.adopt_existing_saved()
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
            if (video_sender or mixed) and VIDEO_DISCOVERY_VERSION not in capabilities['items']['device_status']['versions']:
                capabilities['items']['device_status']['versions'].append(VIDEO_DISCOVERY_VERSION)
            return capabilities

        for resumed in range(2 if reconnect else 1):
            service.resumed = bool(resumed)
            service.ping = service.settings_owner = None
            service.heartbeat = False
            with listener.accept()[0] as client:
                client.settimeout(25 if mixed else 12)
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
    assert sys.argv[1:] in ([], ['--settings'], ['--reconnect'], ['--video-sender'], ['--pc-send-mixed'])
    main(test_settings=bool(sys.argv[1:]), reconnect=sys.argv[1:] == ['--reconnect'],
         video_sender=sys.argv[1:] == ['--video-sender'], mixed=sys.argv[1:] == ['--pc-send-mixed'])
