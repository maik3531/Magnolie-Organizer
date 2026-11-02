"""Real IPC native preparation: exact pair -> metadata-only closed owner, no write."""
import copy
import gc
import hashlib
import json
import uuid
import weakref
import threading
from contextlib import contextmanager

import pytest
import magnolie_hintergrund as background
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
from magnolie_personal_actor_store import NativeProducerBookSnapshot, NativeSavedBookContentWitness
from test_personal_actor_producer_ipc import proxy_producer
from test_personal_actor_restore_candidate import gui_candidates
from test_personal_actor_historical_prepare import durable_queue
from test_personal_actor_transport import frame


def test_prepare_ipc_shape_accepts_only_projection_inputs_not_claimed_save_or_origin_authority():
    run = str(uuid.uuid4())
    request = {'action': 'begin', 'actor_id': run, 'owner_token': 'c' * 64, 'source_revision': 'd' * 64,
        'native_saved_book': {'book_source': 'b' * 64, 'sequence': 1, 'sha256': 'e' * 64}, 'content_sha256': 'f' * 64, 'total_bytes': 2,
        'candidate_sha256': '1' * 64, 'candidate_bytes': 2, 'review_revision': '2' * 64,
        'choices': [{'proposal_id': str(uuid.uuid4()), 'decision': 'restore', 'expected_clock': [{'actor_id': str(uuid.uuid4()), 'counter': 1}], 'confirm_conflict': True}]}
    arguments = {'subscriber': 'a' * 32, 'book_source': 'b' * 64, 'request': request}
    background._request_shape('phone_actor_historical_prepare', arguments)  # Schema only, never authority.
    for fault in ('saved', 'frames', 'purpose', 'capacity', 'implicit'):
        changed = copy.deepcopy(arguments)
        if fault in ('saved', 'frames', 'purpose'): changed['request'][fault] = True
        elif fault == 'capacity': changed['request']['candidate_bytes'] = 256 * 1024 * 1024 + 1
        else: changed['request']['choices'] = None; changed['request']['review_revision'] = None
        with pytest.raises(background.IPCError): background._request_shape('phone_actor_historical_prepare', changed)
    chunk = dict(arguments, request={'action': 'chunk', 'actor_id': run, 'owner_token': 'c' * 64, 'projection_token': 'f' * 64,
        'offset': 0, 'data_base64': 'e30=', 'channel': 'ordinary-data'})
    with pytest.raises(background.IPCError): background._request_shape('phone_actor_historical_prepare', chunk)


@contextmanager
def historical_proxy(tmp_path, monkeypatch, raw):
    fixture = copy.deepcopy(raw)
    with proxy_producer(tmp_path, monkeypatch, scope_members=fixture['members']) as values:
        server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
        book, target = fixture['book'], fixture['target']; key = target['kind'] + '\0' + target['id']
        state = book['personalSync']; state['peer_device_id'] = peer['device_id']
        meta = state['entities'][key]; meta['peer_device_id'] = peer['device_id']
        meta['proposal_id'] = personal.deletion_proposal_id(peer['device_id'], target['kind'], target['id'], '', meta['clock'], meta['prior_hash'])
        text = json.dumps(book, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        saved = owner.record_saved('native-producer-fixture', True, hashlib.sha256(text.encode()).hexdigest())
        snapshot = NativeProducerBookSnapshot.capture(read, lambda: book, lambda: (saved['book_source'], saved['sequence'], saved['sha256']))
        proxy.native_actor_producer_book = lambda: snapshot
        candidate = json.loads(fixture['candidate_text']); candidate['personalSync']['peer_device_id'] = peer['device_id']
        candidate['personalSync']['entities'][key]['peer_device_id'] = peer['device_id']
        candidate_text = json.dumps(candidate, ensure_ascii=False, separators=(',', ':'))
        proxy.start_personal_actor(handle)
        request = {'format': fixture['format'], 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
        service._payload(peer, channel, actor.wire_message(frame('personal_sync.request', request), handle.actor_id))
        body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
            'proposals': [dict(target, deleted_ms=2, label='Synthetic historical target')]}
        service._payload(peer, channel, actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id))
        channel.sent.clear()
        view = proxy.review_personal_actor_incoming_targets(handle)
        yield values, fixture, book, snapshot, candidate_text, view


def test_real_native_prepare_ipc_closes_data_without_retaining_either_book_or_issuing_a_save(tmp_path, monkeypatch, gui_candidates):
    for index, raw in enumerate(gui_candidates):
        with historical_proxy(tmp_path / str(index), monkeypatch, raw) as setup:
            values, fixture, book, snapshot, text, view = setup
            server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
            queue, before = durable_queue(service), read(); captured = []; receiver_refs = []
            original_factory = NativeSavedBookContentWitness.from_snapshot.__func__
            def witness(cls, value):
                captured.append(weakref.ref(value))
                return original_factory(cls, value)
            original = proxy._call
            def call(operation, **fields):
                if operation == 'actor_historical_prepare': assert proxy.native_actor_producer_guard()._is_owned()
                result = original(operation, **fields)
                if operation == 'actor_historical_prepare' and fields['request']['action'] == 'begin':
                    receiver_refs.append(server._phone_actor_projections[handle.actor_id]['receiver'])
                return result
            with monkeypatch.context() as local:
                local.setattr(NativeSavedBookContentWitness, 'from_snapshot', classmethod(witness)); local.setattr(proxy, '_call', call)
                claim = proxy.prepare_personal_actor_historical_restore_save(handle, view['revision'], [fixture['choice']], text)
            gc.collect()
            assert captured and all(reference() is None for reference in captured), 'Daemon retained the consumed before-book snapshot'
            assert receiver_refs and all(value.closed and not value._candidate and not value._before._buffer for value in receiver_refs)
            assert not server._phone_actor_projections and not server._phone_actor_historical_probes
            assert service.native_actor_producer_book is None and service.native_actor_saved_book is None
            assert claim['data_closed'] is True and claim['book_persisted'] is False and claim['phone_persisted'] is False
            assert claim['after_sha256'] == hashlib.sha256(text.encode()).hexdigest()
            status = proxy.personal_actor_status(handle)
            assert status['phase'] == 'completion' and status['historical_book_persisted'] is False
            registry = server._phone_actor_registry(proxy._subscriber, handle.book_source)
            native_handle = service.personal_actor_admissions[handle.actor_id]['handle']
            with pytest.raises(PermissionError): registry.require_current(native_handle)
            with pytest.raises(PermissionError): service.check_personal_actor_historical_restore_save(registry, native_handle, claim['claim_token'], text)
            assert read() == before and durable_queue(service) == queue and not channel.sent and snapshot.book() == book


@pytest.mark.parametrize('fault', ['candidate', 'choice', 'purpose', 'foreign-token', 'writer-drift', 'missing-guard', 'worker-thread', 'caller-choice'])
def test_prepare_ipc_rejects_changed_candidates_sources_and_foreign_projection_purposes(tmp_path, monkeypatch, gui_candidates, fault):
    with historical_proxy(tmp_path, monkeypatch, gui_candidates[0]) as setup:
        values, fixture, book, snapshot, text, view = setup
        server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
        queue, before = durable_queue(service), read(); original = proxy._call; receivers = []
        def call(operation, **fields):
            result = original(operation, **fields)
            if operation == 'actor_historical_prepare':
                selection = fields['request']
                if selection['action'] == 'begin':
                    receivers.append(server._phone_actor_projections[handle.actor_id]['receiver'])
                    if fault == 'caller-choice': choices[0]['decision'] = 'delete'
                    if fault in ('purpose', 'foreign-token'):
                        for action in ('commit', 'abort'):
                            with pytest.raises(background.IPCError):
                                original('actor_historical_review' if fault == 'purpose' else operation,
                                    subscriber=proxy._subscriber, book_source=handle.book_source,
                                    request={'action': action, 'actor_id': handle.actor_id, 'owner_token': handle.owner_token,
                                        'projection_token': result['projection_token'] if fault == 'purpose' else 'f' * 64})
                            assert not receivers[-1].closed
                if selection['action'] == 'chunk' and fault == 'writer-drift': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
            return result
        monkeypatch.setattr(proxy, '_call', call)
        choices = [copy.deepcopy(fixture['choice'])]
        if fault == 'candidate':
            changed = json.loads(text); changed['einstellungen']['unrelated_synthetic_change'] = True; text = json.dumps(changed)
        if fault == 'choice': choices[0]['confirm_conflict'] = False
        if fault == 'missing-guard': proxy.native_actor_producer_guard = None
        if fault in ('purpose', 'foreign-token', 'caller-choice'):
            assert proxy.prepare_personal_actor_historical_restore_save(handle, view['revision'], choices, text)['data_closed'] is True
            assert service.personal_actor_admissions[handle.actor_id]['historical_save_claim']['choices'][0]['decision'] == 'restore'
        elif fault == 'worker-thread':
            errors = []
            def worker():
                try: proxy.prepare_personal_actor_historical_restore_save(handle, view['revision'], choices, text)
                except background.IPCError as error: errors.append(error)
            thread = threading.Thread(target=worker); thread.start(); thread.join(timeout=3)
            assert not thread.is_alive() and errors and not receivers
        else:
            with pytest.raises(background.IPCError): proxy.prepare_personal_actor_historical_restore_save(handle, view['revision'], choices, text)
            assert proxy.personal_actor_status(handle)['phase'] in ('registered', 'receiving')
        assert not server._phone_actor_projections and not server._phone_actor_historical_probes
        assert all(value.closed and not value._candidate and not value._before._buffer for value in receivers)
        assert durable_queue(service) == queue and not channel.sent and snapshot.book() == book
        if fault != 'writer-drift': assert read() == before
