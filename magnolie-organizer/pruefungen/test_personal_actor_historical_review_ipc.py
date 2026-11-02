"""Fresh native projection over real private IPC; metadata-only auth-origin review."""
import copy
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest
import magnolie_hintergrund as background
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
from magnolie_personal_actor_store import NativeProducerBookSnapshot
from test_personal_actor_producer_ipc import proxy_producer
from test_personal_actor_restore_candidate import gui_candidates
from test_personal_actor_historical_prepare import durable_queue
from test_personal_actor_transport import frame, gtk_actor_bridge


def test_native_review_group_capacity_does_not_relax_wire_packets_or_accept_caller_origin():
    run = str(uuid.uuid4()); clock = [{'actor_id': str(uuid.uuid4()), 'counter': 1}]
    choices = [{'proposal_id': str(uuid.uuid4()), 'decision': 'restore', 'expected_clock': clock, 'confirm_conflict': True} for _ in range(256)]
    arguments = {'subscriber': 'a' * 32, 'book_source': 'b' * 64, 'request': {'action': 'begin', 'actor_id': run, 'owner_token': 'c' * 64,
        'source_revision': 'd' * 64, 'native_saved_book': {'book_source': 'b' * 64, 'sequence': 1, 'sha256': 'e' * 64},
        'content_sha256': 'f' * 64, 'total_bytes': 2, 'review_revision': '1' * 64, 'choices': choices}}
    background._request_shape('phone_actor_historical_review', arguments)  # Shape only, never admission or source authority.
    with pytest.raises(ValueError):
        personal.validate_body('personal_sync.deletion_decision', {'format': 1, 'run_id': run, 'decision_id': run,
            'decisions': [{key: choice[key] for key in ('proposal_id', 'decision', 'expected_clock')} for choice in choices]})
    for fault in ('over-capacity', 'caller-origin', 'boolean-type', 'missing-revision'):
        changed = copy.deepcopy(arguments)
        if fault == 'over-capacity': changed['request']['choices'].append(copy.deepcopy(choices[0]))
        elif fault == 'caller-origin': changed['request']['frames'] = []
        elif fault == 'boolean-type': changed['request']['choices'][0]['confirm_conflict'] = 1
        else: changed['request']['review_revision'] = None
        with pytest.raises(background.IPCError): background._request_shape('phone_actor_historical_review', changed)


@pytest.mark.parametrize('fault', ['none', 'missing', 'changed', 'choice-clock', 'no-origin', 'wrong-purpose', 'writer-drift', 'foreign-token'])
def test_historical_review_ipc_keeps_auth_origin_native_writer_and_projection_purpose_separate(tmp_path, monkeypatch, gui_candidates, fault):
    for index, raw in enumerate(gui_candidates if fault == 'none' else gui_candidates[:1]):
        fixture = copy.deepcopy(raw)
        with proxy_producer(tmp_path / str(index), monkeypatch) as values:
            server, proxy, handle, service, peer, channel, owner, read, _, _, _ = values
            book, target = fixture['book'], fixture['target']
            state = book['personalSync']; state['peer_device_id'] = peer['device_id']
            meta = state['entities'][target['kind'] + '\0' + target['id']]
            meta['peer_device_id'] = peer['device_id']
            meta['proposal_id'] = personal.deletion_proposal_id(peer['device_id'], target['kind'], target['id'], '', meta['clock'], meta['prior_hash'])
            if fault == 'missing': book['papierkorb'] = []
            if fault == 'changed': book['papierkorb'][0]['eintrag']['titel'] = 'Changed source'
            text = json.dumps(book, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            saved = owner.record_saved('native-producer-fixture', True, hashlib.sha256(text.encode()).hexdigest())
            snapshot = NativeProducerBookSnapshot.capture(read, lambda: book, lambda: (saved['book_source'], saved['sequence'], saved['sha256']))
            proxy.native_actor_producer_book = lambda: snapshot
            proxy.start_personal_actor(handle)
            request = {'format': fixture['format'], 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
            service._payload(peer, channel, actor.wire_message(frame('personal_sync.request', request), handle.actor_id))
            if fault != 'no-origin':
                body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
                    'proposals': [dict(target, deleted_ms=2, label='Synthetic historical target')]}
                service._payload(peer, channel, actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id))
            channel.sent.clear(); queue = durable_queue(service); before = read()
            original = proxy._call; receivers = []
            def call(operation, **fields):
                if operation == 'actor_historical_review': assert proxy.native_actor_producer_guard()._is_owned()
                result = original(operation, **fields)
                if operation == 'actor_historical_review':
                    selection = fields['request']
                    if selection['action'] == 'begin':
                        receivers.append(server._phone_actor_projections[handle.actor_id]['receiver'])
                        if fault in ('wrong-purpose', 'foreign-token'):
                            with pytest.raises(background.IPCError):
                                original('actor_observer' if fault == 'wrong-purpose' else operation, subscriber=proxy._subscriber, book_source=handle.book_source,
                                    request={'action': 'abort', 'actor_id': handle.actor_id, 'owner_token': handle.owner_token,
                                        'projection_token': result['projection_token'] if fault == 'wrong-purpose' else 'f' * 64})
                            assert not receivers[-1].closed
                    if selection['action'] == 'chunk' and fault == 'writer-drift':
                        owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
                return result
            monkeypatch.setattr(proxy, '_call', call)
            native_bridge = gtk_actor_bridge()
            native_owner = SimpleNamespace(_daten_sperre=proxy.native_actor_producer_guard(), _telefon_actor_buchnachweis=read)
            def bridge(action, **fields):
                return native_bridge(native_owner, proxy, {'action': action, 'actorId': handle.actor_id, 'ownerToken': handle.owner_token, 'bookSource': handle.book_source, **fields})['actor']
            if fault in ('no-origin', 'writer-drift'):
                with pytest.raises(background.IPCError): bridge('notes_actor_historical_review')
            else:
                view = bridge('notes_actor_historical_review')
                assert view['action_authorized'] is False and view['targets'] == [target]
                choices = [{'proposal_id': target['proposal_id'], 'decision': 'restore', 'expected_clock': copy.deepcopy(target['clock']), 'confirm_conflict': True}]
                if fault == 'choice-clock': choices[0]['expected_clock'][0]['counter'] += 1
                if fault in ('missing', 'changed', 'choice-clock'):
                    with pytest.raises(background.IPCError): bridge('notes_actor_historical_source_review', reviewRevision=view['revision'], choices=choices)
                else:
                    reviewed = bridge('notes_actor_historical_source_review', reviewRevision=view['revision'], choices=choices)
                    assert reviewed['action_authorized'] is False and len(reviewed['restore_source_revision']) == 64
                    assert reviewed['local_restore_sources'][0]['target'] == target
                    assert 'Protected synthetic source' not in json.dumps(reviewed) and 'data:' not in json.dumps(reviewed)
                    assert reviewed['content_scope'] == view['content_scope']
            assert not server._phone_actor_projections and all(receiver.closed for receiver in receivers)
            assert service.native_actor_producer_book is None, 'Private projection escaped into a retained daemon book provider'
            assert durable_queue(service) == queue and not channel.sent and snapshot.book() == book
            if fault != 'writer-drift': assert read() == before
