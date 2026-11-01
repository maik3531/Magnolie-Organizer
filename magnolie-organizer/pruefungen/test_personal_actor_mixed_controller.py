"""Full native Mixed controller/IPC with test-only readiness; no GUI/phone E2E."""
import base64
import copy
import json
import sqlite3
import uuid
from types import SimpleNamespace
import pytest
import magnolie_content_scope as scope
import magnolie_hintergrund as background
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
from test_personal_actor_producer_ipc import proxy_producer
from test_personal_actor_transport import frame, gtk_actor_bridge


@pytest.mark.parametrize('early_peer_ack', [True, False])
@pytest.mark.parametrize('handoff_fault', [True, False])
def test_native_mixed_prepare_save_report_order_late_union_and_metadata_retry(tmp_path, monkeypatch, early_peer_ack, handoff_fault):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, snapshot, proposal_id, clock = values
        assert not service._actor_mixed_ready  # Not an IPC argument/capability.
        monkeypatch.setattr(service, '_actor_mixed_ready', True)
        proxy.produce_personal_actor_proposals(handle); proxy.start_personal_actor(handle)
        remote_id = str(uuid.uuid4()); remote_clock = [{'actor_id': peer['device_id'], 'counter': 2}]
        request = {'format': 3, 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
        batch = {'format': 3, 'run_id': handle.actor_id, 'batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
            'reply': False, 'records': [], 'records_hash': personal.records_hash([])}
        proposals = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
            'proposals': [{'proposal_id': remote_id, 'kind': 'task', 'id': 'task-one', 'parent_id': '', 'clock': remote_clock,
                'prior_hash': 'f' * 64, 'deleted_ms': 2, 'label': 'Synthetic incoming task'}]}
        for kind, body in [('personal_sync.request', request), ('personal_sync.batch', batch), ('personal_sync.deletion_proposals', proposals)]:
            service._payload(peer, channel, actor.wire_message(frame(kind, body), handle.actor_id))
        view = proxy.read_personal_actor_staging(handle)
        original_view = json.loads(base64.b64decode(view['data_base64']))
        intent = original_view['intents'][0]
        plan = {'choices': [{'proposal_id': remote_id, 'decision': 'delete', 'expected_clock': remote_clock, 'allow_conflict': True}],
            'intents': [{'kind': intent['kind'], 'message_id': intent['pending_message_id'], 'commit_token': intent['commit_token']}]}
        claim = proxy.prepare_personal_actor_commit(handle, view['revision'], 'b' * 64, read(), plan)
        assert proxy.prepare_personal_actor_commit(handle, view['revision'], 'b' * 64, read(), plan) == claim
        admission = service.personal_actor_admissions[handle.actor_id]
        assert admission['commit_plan']['fixed_review']['before_scope'] == original_view['content_scope']
        owner.record_saved('native-producer-fixture', True, 'b' * 64)
        proxy.commit_personal_actor(handle, claim['claim_token'], read())
        ordinary = copy.deepcopy(admission['save_receipt'])
        proxy.queue_personal_actor_reply(handle, claim['claim_token'], [dict(batch, batch_id=str(uuid.uuid4()), reply=True)], [], read())
        reply = service.store.outbox_message(peer['device_id'], admission['reply_ids'][0])
        assert service._send_personal_actor_queued(channel, peer['device_id'], reply)
        if handoff_fault:
            registry = admission['registry']; begin = registry.begin_decision_review; attempts = [0]
            def fail_once(*args, **kwargs):
                attempts[0] += 1
                if attempts[0] != 1: return begin(*args, **kwargs)
                with sqlite3.connect(service.store.database_path) as db:
                    db.execute("CREATE TRIGGER mixed_report_fault BEFORE INSERT ON personal_actor_context BEGIN SELECT RAISE(ABORT,'synthetic mixed report handoff fault'); END")
                try: return begin(*args, **kwargs)
                finally:
                    with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER mixed_report_fault')
            monkeypatch.setattr(registry, 'begin_decision_review', fail_once)
            service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, reply['message_id'])))
            assert not admission.get('report_owner') and not admission.get('completion_report_id')
            prepared = copy.deepcopy(admission['fixed_frames'])
            assert prepared and all(value['message_id'] not in admission['outbound'] for value in prepared)
            assert not service._send_personal_actor_queued(channel, peer['device_id'], prepared[0])
            assert read() == ordinary
        service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, reply['message_id'])))
        fixed = admission['fixed_frames'][0]
        if handoff_fault: assert admission['fixed_frames'] == prepared
        report = service.store.outbox_message(peer['device_id'], admission['completion_report_id'])
        assert proxy.personal_actor_status(handle)['phase'] == 'decision_review'
        with pytest.raises(PermissionError): admission['registry'].require_current(admission['handle'])
        assert not service._send_personal_actor_queued(channel, peer['device_id'], report)
        assert service._send_personal_actor_queued(channel, peer['device_id'], fixed)
        assert service._send_personal_actor_queued(channel, peer['device_id'], report)
        assert channel.sent.index(fixed) < channel.sent.index(report)
        fixed_ack = frame(actor.ACK_KIND, actor.ack(handle.actor_id, fixed['message_id']))
        if early_peer_ack: service._payload(peer, channel, fixed_ack)
        service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, report['message_id'])))
        binding = (peer['device_id'], peer['static_public'], id(channel))
        result_scope = scope.advance(original_view['content_scope'], ['note-one'], [])
        for part in scope.chunks(result_scope): service.content_scope_sessions[channel].receive(binding, part)
        late_frame = actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1, 'run_id': handle.actor_id,
            'decision_id': str(uuid.uuid4()), 'decisions': [{'proposal_id': proposal_id, 'decision': 'restore', 'expected_clock': clock}]}), handle.actor_id)
        service._payload(peer, channel, late_frame)
        bridge = gtk_actor_bridge(); host = SimpleNamespace(_daten_sperre=proxy.native_actor_producer_guard(), _telefon_actor_buchnachweis=read)
        def native(action, **fields):
            return bridge(host, proxy, {'action': action, 'actorId': handle.actor_id, 'ownerToken': handle.owner_token, 'bookSource': handle.book_source, **fields})['actor']
        late_page = native('notes_actor_late_review')
        late = json.loads(base64.b64decode(late_page['data_base64']))
        assert late['fixed_decision_message_ids'] == [fixed['message_id']]
        assert late['fixed_decisions'][0]['proposal_id'] == remote_id and late['decisions'][0]['proposal_id'] == proposal_id
        assert late['content_scope'] == result_scope and read() == ordinary
        late_claim = native('notes_actor_prepare_late_save', reviewRevision=late_page['review_revision'], bookSha256='c' * 64)
        owner.record_saved('native-producer-fixture', True, 'c' * 64); final_sequence = read()['sequence']
        receipt = native('notes_actor_confirm_late_save', claimToken=late_claim['claim_token'])
        assert not receipt['phone_persisted'] and receipt == native('notes_actor_confirm_late_save', claimToken=late_claim['claim_token'])
        state = native('notes_actor_advance_completion')
        if not early_peer_ack:
            assert not state['phone_persisted'] and state['deletion_completion']['saved'] == 1
            service._payload(peer, channel, fixed_ack)
            state = native('notes_actor_advance_completion')
        assert state['phase'] == 'completed' and state['deletion_completion'] == dict(expected=2, received=2, saved=2, rejected=0)
        assert read()['sequence'] == final_sequence and admission['save_receipt'] == ordinary
        assert sum(value == fixed for value in channel.sent) == 1
        assert not server._phone_actor_book_probes


@pytest.mark.parametrize('fault', ['duplicate-proposal', 'duplicate-entity', 'combined-capacity', 'initial-incoming-decision'])
def test_native_mixed_preflight_rejects_ambiguous_or_unsupported_unions_before_ordinary_save(tmp_path, monkeypatch, fault):
    with proxy_producer(tmp_path, monkeypatch) as values:
        server, proxy, handle, service, peer, channel, owner, read, snapshot, proposal_id, clock = values
        monkeypatch.setattr(service, '_actor_mixed_ready', True)
        proxy.produce_personal_actor_proposals(handle); proxy.start_personal_actor(handle)
        request = {'format': 3, 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
        batch = {'format': 3, 'run_id': handle.actor_id, 'batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
            'reply': False, 'records': [], 'records_hash': personal.records_hash([])}
        for kind, body in [('personal_sync.request', request), ('personal_sync.batch', batch)]:
            service._payload(peer, channel, actor.wire_message(frame(kind, body), handle.actor_id))
        choices = []
        if fault == 'initial-incoming-decision':
            decision = {'format': 1, 'run_id': handle.actor_id, 'decision_id': str(uuid.uuid4()),
                'decisions': [{'proposal_id': proposal_id, 'decision': 'restore', 'expected_clock': clock}]}
            service._payload(peer, channel, actor.wire_message(frame('personal_sync.deletion_decision', decision), handle.actor_id))
        else:
            proposals = []
            for index in range(256 if fault == 'combined-capacity' else 1):
                remote_id = proposal_id if fault == 'duplicate-proposal' else str(uuid.uuid4())
                target = {'proposal_id': remote_id, 'kind': 'attachment', 'id': 'removed-file' if fault == 'duplicate-entity' else 'incoming-file-%d' % index,
                    'parent_id': 'note-one', 'clock': clock, 'prior_hash': 'f' * 64, 'deleted_ms': 2, 'label': 'Synthetic preflight target'}
                proposals.append(target)
                choices.append({'proposal_id': remote_id, 'decision': 'delete', 'expected_clock': clock, 'allow_conflict': True})
            proposals.sort(key=lambda value: value['proposal_id'])
            for start in range(0, len(proposals), 32):
                body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': handle.actor_id, 'sequence': start // 32,
                    'last': start + 32 >= len(proposals), 'proposals': proposals[start:start + 32]}
                service._payload(peer, channel, actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id))
        first = proxy.read_personal_actor_staging(handle); raw = base64.b64decode(first['data_base64']); next_offset = first['next_offset']
        while next_offset is not None:
            part = proxy.read_personal_actor_staging(handle, offset=next_offset, expected_revision=first['revision'])
            raw += base64.b64decode(part['data_base64']); next_offset = part['next_offset']
        intents = json.loads(raw)['intents']
        assert intents
        plan = {'choices': choices, 'intents': [{'kind': value['kind'], 'message_id': value['pending_message_id'], 'commit_token': value['commit_token']} for value in intents]}
        before = read()
        with pytest.raises(background.IPCError):
            proxy.prepare_personal_actor_commit(handle, first['revision'], 'b' * 64, before, plan)
        admission = service.personal_actor_admissions[handle.actor_id]
        assert not admission.get('commit_plan') and read() == before
        with sqlite3.connect(service.store.database_path) as db:
            assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_fixed:%'").fetchone()[0] == 0
