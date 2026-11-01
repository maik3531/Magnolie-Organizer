"""Operation-live native GUI projection over real private IPC, not wire admission."""
import copy
import hashlib
import json
import threading
import uuid

import pytest
import magnolie_hintergrund as background
from magnolie_personal_actor_store import NativeProducerBookSnapshot
from test_personal_actor_producer_ipc import proxy_producer
from test_personal_actor_incoming_target_evidence import live_fixture


def live_projection(values, kind, prepare=None):
    server, proxy, handle, service, peer, channel, owner, read, old, _, _ = values
    _, _, live, target, key, _ = live_fixture(kind)
    book = old.book()
    book['notizen'] += live['notizen']; book['aufgaben'] += live['aufgaben']
    meta = live['personalSync']['entities'][key]
    meta['peer_device_id'] = peer['device_id']
    book['personalSync']['entities'][key] = meta
    if prepare is not None: prepare(book, target, key)
    text = json.dumps(book, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    saved = owner.record_saved('native-producer-fixture', True, hashlib.sha256(text.encode()).hexdigest())
    snapshot = NativeProducerBookSnapshot.capture(read, lambda: book,
        lambda: (saved['book_source'], saved['sequence'], saved['sha256']))
    proxy.native_actor_producer_book = lambda: snapshot
    return book, target, snapshot


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_live_gui_observer_ipc_returns_only_exact_metadata_without_queue_or_data_rights(tmp_path, monkeypatch, kind):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
        book, target, snapshot = live_projection(values, kind)
        before_wire, before_queue, before_saved = copy.deepcopy(channel.sent), service.store.pending(peer['device_id']), read()
        result = proxy.observe_personal_actor_incoming_targets(handle, [target])
        assert len(result) == 1 and result[0]['target'] == target and result[0]['requires_conflict_choice'] is True
        assert 'PRIVATE' not in json.dumps(result)
        assert service.store.pending(peer['device_id']) == before_queue and channel.sent == before_wire
        assert book == snapshot.book() and read() == before_saved
        assert not server._phone_actor_projections
        assert service.native_actor_producer_book is None, 'Operation-local projection escaped into a long-lived daemon callback'


@pytest.mark.parametrize('scenario', ['writer-lock', 'wrong-purpose', 'foreign-token', 'writer-after-chunk',
    'source-after-chunk', 'missing-guard', 'worker-thread', 'content-target', 'malformed-target'])
def test_observer_projection_fences_purpose_native_writer_and_private_lifetime(tmp_path, monkeypatch, scenario):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
        book, target, snapshot = live_projection(values, 'note')
        before_wire, before_queue = copy.deepcopy(channel.sent), service.store.pending(peer['device_id'])
        original = proxy._call; receivers = []
        def call(operation, **fields):
            if operation == 'actor_observer':
                assert proxy.native_actor_producer_guard()._is_owned()
                if scenario == 'writer-lock' and fields['request']['action'] == 'commit':
                    guard = proxy.native_actor_producer_guard(); acquired = []
                    def writer():
                        got = guard.acquire(timeout=0.05); acquired.append(got)
                        if got: guard.release()
                    thread = threading.Thread(target=writer); thread.start(); thread.join(1)
                    assert not thread.is_alive() and acquired == [False]
            result = original(operation, **fields)
            if operation == 'actor_observer':
                request = fields['request']
                if request['action'] == 'begin':
                    receivers.append(server._phone_actor_projections[handle.actor_id]['receiver'])
                    if scenario in ('wrong-purpose', 'foreign-token'):
                        for action in ('commit', 'abort'):
                            with pytest.raises(background.IPCError):
                                original('actor_producer' if scenario == 'wrong-purpose' else 'actor_observer',
                                    subscriber=proxy._subscriber, book_source=handle.book_source,
                                    request={'action': action, 'actor_id': handle.actor_id, 'owner_token': handle.owner_token,
                                        'projection_token': result['projection_token'] if scenario == 'wrong-purpose' else 'f' * 64})
                        assert not receivers[-1].closed
                if request['action'] == 'chunk':
                    if scenario == 'writer-after-chunk': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
                    if scenario == 'source-after-chunk': service.connections.clear()
            return result
        monkeypatch.setattr(proxy, '_call', call)
        if scenario == 'missing-guard':
            proxy.native_actor_producer_guard = None
            with pytest.raises(background.IPCError): proxy.observe_personal_actor_incoming_targets(handle, [target])
        elif scenario == 'worker-thread':
            errors = []
            def worker():
                try: proxy.observe_personal_actor_incoming_targets(handle, [target])
                except background.IPCError as error: errors.append(error)
            thread = threading.Thread(target=worker); thread.start(); thread.join(3)
            assert not thread.is_alive() and errors and not receivers
        else:
            if scenario == 'content-target': target['id'] = 'note-one'
            if scenario == 'malformed-target': target['content'] = 'PRIVATE'
            if scenario in ('writer-after-chunk', 'source-after-chunk', 'content-target', 'malformed-target'):
                with pytest.raises(background.IPCError): proxy.observe_personal_actor_incoming_targets(handle, [target])
            else:
                assert proxy.observe_personal_actor_incoming_targets(handle, [target])[0]['target'] == target
        assert not server._phone_actor_projections and all(receiver.closed for receiver in receivers)
        assert service.native_actor_producer_book is None
        assert service.store.pending(peer['device_id']) == before_queue and channel.sent == before_wire


def test_maximum_observation_group_uses_one_native_capture_and_one_daemon_book_parse(tmp_path, monkeypatch):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
        targets = []
        def prepare(book, target, key):
            template = book['personalSync']['entities'].pop(key)
            book['aufgaben'] = []
            for index in range(256):
                identifier = 'offscope-task-%03d' % index
                book['aufgaben'].append({'id': identifier, 'titel': 'PRIVATE TASK'})
                book['personalSync']['entities']['task\0' + identifier] = copy.deepcopy(template)
                targets.append(dict(copy.deepcopy(target), id=identifier, proposal_id=str(uuid.uuid4())))
        book, _, snapshot = live_projection(values, 'task', prepare)
        captures, parses = [], []
        proxy.native_actor_producer_book = lambda: (captures.append(True), snapshot)[1]
        original = NativeProducerBookSnapshot.book
        def parsed(value):
            parses.append(True)
            return original(value)
        monkeypatch.setattr(NativeProducerBookSnapshot, 'book', parsed)
        before_queue, before_wire = service.store.pending(peer['device_id']), copy.deepcopy(channel.sent)
        result = proxy.observe_personal_actor_incoming_targets(handle, targets)
        assert len(result) == 256 and all(value['requires_conflict_choice'] for value in result)
        assert len(captures) == 1 and len(parses) == 1
        assert not server._phone_actor_projections and 'PRIVATE' not in json.dumps(result)
        assert service.store.pending(peer['device_id']) == before_queue and channel.sent == before_wire
