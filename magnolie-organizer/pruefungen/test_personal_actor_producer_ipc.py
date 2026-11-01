"""Actual private IPC for fresh operation-local native GUI producer projection."""
import base64
import copy
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest

import magnolie_hintergrund as background
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
import magnolie_shared_sync as shared
from magnolie_personal_actor_store import NativeProducerBookSnapshot
from test_personal_actor_producer import native, ACTOR, RUN
from test_personal_actor_source import actor_source_fixture
from test_personal_actor_transport import gtk_actor_bridge
from test_shared_sync_transport import message
from test_hintergrunddienst import FakeBackend


@contextmanager
def proxy_producer(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    peer_id = peer['device_id']; clock = [{'actor_id': ACTOR, 'counter': 1}]
    peer['grants']['grants']['personal_deletions_sync'] = True
    service.note_controls[channel]['grants.update'] = copy.deepcopy(peer['grants'])
    setting = service.store.change_shared_setting(peer_id, peer['static_public'], 'skip_deletions', False)
    service._payload(peer, channel, message(shared.merge(shared.create(peer_id), setting, peer_id, service.store.identity['device_id'])))
    proposal_id = personal.deletion_proposal_id(peer_id, 'attachment', 'removed-file', 'note-one', clock, 'a' * 64)
    book = {'notizen': [{'id': 'note-one', 'text': 'PRIVATE SYNTHETIC Grüße 🌸' * 2000, 'anhaenge': []}], 'aufgaben': [],
        'personalSync': {'actor_id': ACTOR, 'counter': 1, 'peer_device_id': peer_id,
            'entities': {'attachment\0note-one\0removed-file': {'state': 'deleted', 'status': 'local_pending', 'peer_device_id': peer_id,
                'parent_id': 'note-one', 'clock': clock, 'hash': '', 'prior_hash': 'a' * 64, 'proposal_id': proposal_id, 'deleted_ms': 2, 'label': 'Synthetic removed attachment'}}}}
    owner, read, snapshot = native(book)
    with tempfile.TemporaryDirectory(prefix='actor-producer-ipc-') as root:
        path = str(Path(root) / 'bridge.sock')
        server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
        service.personal_sync_available = server.gui_personal_ready
        proxy = background.PhoneServiceProxy(path)
        proxy.native_actor_book_source = lambda: owner.current('native-producer-fixture', True)
        proxy.native_actor_saved_book = read
        book_guard = threading.RLock()
        proxy.native_actor_producer_guard = lambda: book_guard
        proxy.native_actor_producer_book = lambda: NativeProducerBookSnapshot.capture(read, lambda: book,
            lambda: (snapshot.book_source, snapshot.sequence, snapshot.content_sha256))
        try:
            proxy.start(); proxy.set_visible(True); proxy.set_ready(True)
            handle = proxy.create_personal_actor(peer_id, fingerprint)
            yield server, proxy, handle, service, peer, channel, owner, read, snapshot, proposal_id, clock
        finally:
            proxy.stop()
            if proxy._event_thread is not None: proxy._event_thread.join(timeout=3)
            server.close()


@pytest.mark.parametrize('scenario', ['success', 'sql-retry', 'writer-after-chunk', 'source-after-chunk', 'foreign-token', 'worker-thread', 'writer-lock', 'missing-guard'])
def test_native_proxy_uploads_fresh_bounded_book_only_for_the_live_protected_run(tmp_path, monkeypatch, scenario):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, snapshot, proposal_id, clock = values
        queued_before = service.store.pending(peer['device_id']); wire_before = copy.deepcopy(channel.sent)
        original = proxy._call; receivers = []; chunks = [0]
        def observed(operation, **fields):
            if operation == 'actor_producer':
                assert proxy.native_actor_producer_guard()._is_owned(), 'Native writer lock was not held through the producer IPC operation'
                if scenario == 'writer-lock' and fields['request']['action'] == 'commit':
                    lock = proxy.native_actor_producer_guard(); acquired = []
                    def writer():
                        result = lock.acquire(timeout=0.05); acquired.append(result)
                        if result: lock.release()
                    thread = threading.Thread(target=writer); thread.start(); thread.join(1)
                    assert not thread.is_alive() and acquired == [False], 'A save worker replaced native book authority during final IPC commit'
            result = original(operation, **fields)
            if operation == 'actor_producer':
                request = fields['request']
                if request['action'] == 'begin': receivers.append(server._phone_actor_projections[handle.actor_id]['receiver'])
                if request['action'] == 'chunk':
                    chunks[0] += 1
                    assert len(request['data_base64']) <= 43692
                    if scenario == 'writer-after-chunk': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
                    if scenario == 'source-after-chunk': service.connections.clear()
                    if scenario == 'foreign-token':
                        with pytest.raises(background.IPCError):
                            original('actor_producer', subscriber=proxy._subscriber, book_source=handle.book_source,
                                request={'action': 'abort', 'actor_id': handle.actor_id, 'owner_token': handle.owner_token, 'projection_token': 'f' * 64})
                        assert not receivers[-1].closed, 'Foreign token aborted the legitimate native projection'
            return result
        monkeypatch.setattr(proxy, '_call', observed)
        if scenario == 'missing-guard':
            proxy.native_actor_producer_guard = None
            with pytest.raises(background.IPCError): proxy.produce_personal_actor_proposals(handle)
            assert not server._phone_actor_projections
            return
        if scenario == 'worker-thread':
            errors = []
            def worker():
                try: proxy.produce_personal_actor_proposals(handle)
                except background.IPCError as error: errors.append(error)
            thread = threading.Thread(target=worker); thread.start(); thread.join(3)
            assert not thread.is_alive() and errors and not receivers
            return
        if scenario == 'sql-retry':
            with sqlite3.connect(service.store.database_path) as db:
                db.execute("CREATE TRIGGER native_projection_fault BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'synthetic native IPC SQL fault'); END")
            with pytest.raises(background.IPCError): proxy.produce_personal_actor_proposals(handle)
            assert not server._phone_actor_projections and service.store.pending(peer['device_id']) == queued_before
            with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER native_projection_fault')
        if scenario in ('writer-after-chunk', 'source-after-chunk'):
            with pytest.raises(background.IPCError): proxy.produce_personal_actor_proposals(handle)
            assert service.store.pending(peer['device_id']) == queued_before
        else:
            result = gtk_actor_bridge()(SimpleNamespace(_telefon_actor_buchnachweis=read, _daten_sperre=proxy.native_actor_producer_guard()), proxy,
                {'action': 'notes_actor_produce', 'actorId': handle.actor_id, 'ownerToken': handle.owner_token, 'bookSource': handle.book_source})['actor']
            assert result == {'producer_staged': True, 'message_count': 1, 'proposal_count': 1,
                'proposal_ids': [proposal_id],
                'book_sha256': snapshot.saved_sha256, 'save_sequence': snapshot.sequence}
            frames = service.store.pending(peer['device_id'])
            assert len(frames) == len(queued_before) + 1 and chunks[0] >= 2
            assert proxy.produce_personal_actor_proposals(handle) == result
            assert service.store.pending(peer['device_id']) == frames
            proxy.start_personal_actor(handle)
            producer_frame = next(frame for frame in frames if frame['kind'] == actor.DATA_KIND)
            assert not service._send_personal_actor_queued(channel, peer['device_id'], producer_frame), 'Daemon reused an expired operation projection as a background writer proof'
            decision = {'format': 1, 'run_id': handle.actor_id, 'decision_id': RUN, 'decisions': [
                {'proposal_id': proposal_id, 'decision': 'restore', 'expected_clock': clock}]}
            assert len(service.store.personal_decision_targets(actor.storage_peer(handle.actor_id), decision, False)) == 1
            assert service.store.personal_decision_targets(peer['device_id'], decision, False) is None
            proxy.cancel_personal_actor(handle)
            assert service.store.pending(peer['device_id']) == queued_before
        assert not server._phone_actor_projections
        assert all(receiver.closed and receiver.received_bytes == 0 for receiver in receivers)
        assert service.native_actor_producer_book is None and service.native_actor_saved_book is None
        assert service.server is None
        # Only explicit cancellation sends a control; staging/upload/replay do not.
        if scenario in ('writer-after-chunk', 'source-after-chunk'): assert channel.sent == wire_before


@pytest.mark.parametrize('action,field,value', [('begin', 'total_bytes', True), ('begin', 'total_bytes', 256 * 1024 * 1024 + 1),
    ('begin', 'content_sha256', 'caller-name'), ('chunk', 'offset', True), ('chunk', 'offset', -1),
    ('chunk', 'data_base64', 'a' * 43693), ('commit', 'projection_token', 'not-token')])
def test_projection_ipc_shapes_reject_unbounded_or_caller_asserted_authority(action, field, value):
    request = {'action': action, 'actor_id': RUN, 'owner_token': 'a' * 64}
    if action == 'begin': request.update(source_revision='b' * 64, native_saved_book={'book_source': 'c' * 64, 'sequence': 1, 'sha256': 'd' * 64}, content_sha256='e' * 64, total_bytes=100)
    else: request['projection_token'] = 'f' * 64
    if action == 'chunk': request.update(offset=0, data_base64=base64.b64encode(b'{}').decode())
    request[field] = value
    with pytest.raises(background.IPCError): background._request_shape('phone_actor_producer', {'subscriber': 'a' * 32, 'book_source': 'c' * 64, 'request': request})


@pytest.mark.parametrize('cleanup', ['abort', 'unsubscribe', 'server-close', 'deadline', 'capacity'])
def test_partial_native_projection_is_bounded_and_erased_by_actual_lifecycle(tmp_path, monkeypatch, cleanup):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, snapshot, proposal_id, clock = values
        status = proxy.personal_actor_status(handle)
        source = proxy.current_actor_source(status['peer_id'], status['fingerprint'])
        def call(action, **fields):
            return proxy._call('actor_producer', subscriber=proxy._subscriber, book_source=handle.book_source,
                request={'action': action, 'actor_id': handle.actor_id, 'owner_token': handle.owner_token, **fields})
        begin = dict(source_revision=source, native_saved_book=snapshot.saved_book, content_sha256=snapshot.content_sha256, total_bytes=len(snapshot.text.encode()))
        token = call('begin', **begin)['projection_token']
        receiver = server._phone_actor_projections[handle.actor_id]['receiver']
        call('chunk', projection_token=token, offset=0, data_base64=base64.b64encode(snapshot.text.encode()[:32768]).decode())
        assert receiver.received_bytes == 32768
        if cleanup == 'capacity':
            with pytest.raises(background.IPCError): call('begin', **begin)
            assert receiver.received_bytes == 32768 and not receiver.closed
        if cleanup in ('abort', 'capacity'): call('abort', projection_token=token)
        elif cleanup == 'unsubscribe': proxy.stop()
        elif cleanup == 'server-close': server.close()
        else:
            closed = threading.Event(); original = receiver.close
            def observed_close(): original(); closed.set()
            receiver.close = observed_close
            with service.lock: server._phone_actor_projections[handle.actor_id]['expires'] = 0
            assert closed.wait(3), 'Idle IPC accept watchdog did not erase an abandoned projection'
        assert not server._phone_actor_projections and receiver.closed and receiver.received_bytes == 0
        assert service.native_actor_producer_book is None and service.server is None


@pytest.mark.parametrize('scenario', ['success', 'before-start', 'writer-change', 'send-failure', 'after-ack', 'foreign-gui', 'worker-thread', 'expired-start-after-admission'])
def test_operation_live_native_dispatch_preserves_start_order_backoff_and_actual_send_outcome(tmp_path, monkeypatch, scenario):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, snapshot, proposal_id, clock = values
        proxy.produce_personal_actor_proposals(handle)
        frame = next(frame for frame in service.store.pending(peer['device_id']) if frame['kind'] == actor.DATA_KIND)
        if scenario != 'before-start':
            import magnolie_telefon as phone
            proxy.start_personal_actor(handle)
            assert proxy.dispatch_personal_actor_proposals(handle)['message_count'] == 0
            request = {'format': 3, 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
            service._payload(peer, channel, actor.wire_message(phone.PhoneService._actor_control_message('personal_sync.request', request), handle.actor_id))
        wire_before = copy.deepcopy(channel.sent)
        if scenario == 'expired-start-after-admission':
            service.personal_actor_admissions[handle.actor_id]['start']['expires_ms'] = 0
            with pytest.raises(background.IPCError): proxy.start_personal_actor(handle)
        original_send = channel.send
        def send(wire):
            assert not service.lock._is_owned(), 'Producer network I/O held phone/SQLite guards'
            guard = proxy.native_actor_producer_guard(); acquired = guard.acquire(timeout=0.02)
            if acquired: guard.release()
            assert not acquired, 'GUI writer guard was not held across the native encrypted send claim'
            if scenario == 'send-failure': raise OSError('Synthetic producer channel failure')
            original_send(wire)
        channel.send = send
        if scenario == 'writer-change': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
        if scenario == 'worker-thread':
            errors = []
            def worker():
                try: proxy.dispatch_personal_actor_proposals(handle)
                except background.IPCError as error: errors.append(error)
            thread = threading.Thread(target=worker); thread.start(); thread.join(3)
            assert not thread.is_alive() and errors
        elif scenario == 'foreign-gui':
            other = background.PhoneServiceProxy(proxy.path)
            other.native_actor_book_source = proxy.native_actor_book_source; other.native_actor_saved_book = read
            other.native_actor_producer_guard = proxy.native_actor_producer_guard
            try:
                other.start(); other.set_visible(True); other.set_ready(True)
                with pytest.raises(background.IPCError): other.dispatch_personal_actor_proposals(handle)
            finally:
                other.stop()
                if other._event_thread is not None: other._event_thread.join(timeout=3)
        elif scenario in ('before-start', 'writer-change', 'send-failure'):
            with pytest.raises(background.IPCError): proxy.dispatch_personal_actor_proposals(handle)
        else:
            result = gtk_actor_bridge()(SimpleNamespace(_telefon_actor_buchnachweis=read, _daten_sperre=proxy.native_actor_producer_guard()), proxy,
                {'action': 'notes_actor_dispatch_proposals', 'actorId': handle.actor_id, 'ownerToken': handle.owner_token, 'bookSource': handle.book_source})['actor']
            assert result == {'dispatch_started': True, 'message_count': 1, 'delivery_confirmed': False}
            assert channel.sent[-1] == frame
            assert proxy.dispatch_personal_actor_proposals(handle) == {'dispatch_started': False, 'message_count': 0, 'delivery_confirmed': False}
            if scenario == 'after-ack':
                import magnolie_telefon as phone
                ack = phone.PhoneService._actor_control_message(actor.ACK_KIND, actor.ack(handle.actor_id, frame['message_id']))
                service._payload(peer, channel, ack)
                assert service.store.outbox_message(peer['device_id'], frame['message_id']) is None
                assert proxy.dispatch_personal_actor_proposals(handle)['message_count'] == 0
        assert not server._phone_actor_book_probes and not server._phone_actor_projections
        if scenario not in ('success', 'after-ack', 'expired-start-after-admission'): assert channel.sent == wire_before
        channel.send = original_send
