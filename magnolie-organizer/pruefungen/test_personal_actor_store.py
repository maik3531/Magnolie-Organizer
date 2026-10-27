"""Persist the explicit wire marker, independently of volatile actor ownership."""
import json
import sqlite3
import copy
import pytest
from test_mcp_phone import owned_service
import magnolie_telefon as phone
import magnolie_personal_actor as actor


RUN = "11111111-1111-4111-8111-111111111111"
REQUEST = {"format": 3, "run_id": RUN, "trigger": "manual", "modules": ["notes", "tasks"]}


def test_encrypted_outbox_reopen_keeps_wire_actor_and_semantic_queue_kind(tmp_path):
    service, peer, events = owned_service(tmp_path)
    store = service.store
    wire = store.queue(peer["device_id"], "personal_sync.request", REQUEST, 60000, actor_run_id=RUN)
    assert wire["kind"] == actor.DATA_KIND and actor.unwrap(wire["body"]) == ("personal_sync.request", REQUEST)
    with sqlite3.connect(store.database_path) as db:
        row = db.execute("SELECT message_id,kind,created_ms,expires_ms,payload FROM outbox").fetchone()
    assert row[:4] == (wire["message_id"], "personal_sync.request", wire["created_ms"], wire["expires_ms"])
    assert json.loads(store._decrypt(row[4], "outbox", wire["message_id"])) == wire
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Owned desktop")
    assert reopened.pending(peer["device_id"]) == [wire]
    decision_id = "44444444-4444-4444-8444-444444444444"
    decision = {"format": 1, "run_id": RUN, "decision_id": decision_id, "decisions": [{
        "proposal_id": "55555555-5555-4555-8555-555555555555", "decision": "restore",
        "expected_clock": [{"actor_id": "66666666-6666-4666-8666-666666666666", "counter": 1}]}]}
    decision_wire = reopened.queue(peer["device_id"], "personal_sync.deletion_decision", decision, 60000, actor_run_id=RUN)
    assert reopened.acknowledge(peer["device_id"], decision_wire["message_id"]) == decision_id
    assert reopened.pending(peer["device_id"]) == [wire]
    reopened.acknowledge(peer["device_id"], wire["message_id"])
    assert reopened.pending(peer["device_id"]) == []
    assert not events and service.server is None


def test_legacy_queue_and_invalid_actor_selection_do_not_mix(tmp_path):
    service, peer, events = owned_service(tmp_path)
    store = service.store
    ordinary = store.queue(peer["device_id"], "personal_sync.request", REQUEST, 60000)
    assert ordinary["kind"] == "personal_sync.request" and ordinary["body"] == REQUEST
    for kind, body, run in [
        ("personal_sync.request", REQUEST, "22222222-2222-4222-8222-222222222222"),
        ("personal_sync.settings", {"format": 1, "own_device": True}, RUN),
        (actor.START_KIND, actor.start(RUN), RUN),
    ]:
        with pytest.raises(ValueError):
            store.queue(peer["device_id"], kind, body, 60000, actor_run_id=run)
    assert store.pending(peer["device_id"]) == [ordinary] and not events


def test_reserved_actor_waits_for_an_explicit_transport_route(tmp_path):
    service, peer, events = owned_service(tmp_path)
    peer["personal_sync"].update(own_device=True, remote_own_device=True)
    for name in ("personal_notes_sync", "personal_tasks_sync"):
        peer["local_grants"]["grants"][name] = True
        peer["grants"]["grants"][name] = True
    service.store.save_peers()
    service.personal_sync_available = lambda: True
    service.store.remember_personal_run(peer["device_id"], REQUEST)
    wire = service.store.queue(peer["device_id"], "personal_sync.request", REQUEST, 60000, actor_run_id=RUN)
    assert service.store.outbox_policy(peer["device_id"], wire["message_id"]) == "any"
    sent = []
    class Channel:
        def send(self, message): sent.append(message)
    assert service._send_message(Channel(), peer["device_id"], wire) is False
    assert not sent and service.store.pending(peer["device_id"]) == [wire] and not events


def test_unadmitted_actor_receive_never_uses_legacy_staging_or_gui(tmp_path):
    service, peer, events = owned_service(tmp_path)
    service.store.remember_personal_run(peer["device_id"], REQUEST)
    queued = service.store.queue(peer["device_id"], "personal_sync.request", REQUEST, 60000, actor_run_id=RUN)
    now = phone.now_ms()
    original = {"type": "message", "v": 1, "message_id": "77777777-7777-4777-8777-777777777777",
        "kind": "personal_sync.batch", "created_ms": now, "expires_ms": now + 60000,
        "body": {"format": 3, "run_id": RUN, "batch_id": "88888888-8888-4888-8888-888888888888",
            "sequence": 0, "last": True, "reply": False, "records_hash": phone.records_hash([]), "records": []}}
    wire = actor.wire_message(original, RUN)
    start = {**original, "message_id": RUN, "kind": actor.START_KIND, "body": actor.start(RUN)}
    malformed = {**wire, "body": {"owned_unclaimed": "Must not reach GUI/storage"}}
    sent = []
    class Channel:
        def send(self, message): sent.append(message)
    channel = Channel()
    plain_ack = {"type": "ack", "message_id": queued["message_id"], "status": "accepted", "error": "none"}
    marked_ack = {**original, "kind": actor.ACK_KIND, "body": actor.ack(RUN, queued["message_id"])}
    cancel = {**original, "kind": actor.CANCEL_KIND, "body": actor.cancel(RUN)}
    for frame in (start, wire, malformed, plain_ack, marked_ack, cancel):
        service._payload(peer, channel, frame)
    assert not sent and not events
    assert service.store.pending(peer["device_id"]) == [queued]
    with sqlite3.connect(service.store.database_path) as db:
        for table in ("inbox", "dedupe", "personal_batch", "personal_domain", "personal_attachment_transfer", "personal_attachment_chunk"):
            assert db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
    ping_id = "99999999-9999-4999-8999-999999999999"
    service._payload(peer, channel, {"type": "ping", "ping_id": ping_id, "sent_ms": now})
    assert sent == [{"type": "pong", "ping_id": ping_id, "sent_ms": now}] and not events


def test_private_storage_namespace_reuses_existing_stagers_without_gui_replay(tmp_path):
    service, peer, events = owned_service(tmp_path)
    private = actor.storage_peer(RUN)
    assert actor.is_storage_peer(private) and not phone.valid_uuid(private)
    assert not actor.is_storage_peer(peer["device_id"])
    service.store.remember_personal_run(private, REQUEST)
    now = phone.now_ms()
    batch = {"type": "message", "v": 1, "message_id": "77777777-7777-4777-8777-777777777777", "kind": "personal_sync.batch",
        "created_ms": now, "expires_ms": now + 60000, "body": {"format": 3, "run_id": RUN,
            "batch_id": "88888888-8888-4888-8888-888888888888", "sequence": 0, "last": True, "reply": False,
            "records_hash": phone.records_hash([]), "records": []}}
    staged = service.store.stage_personal_batch(private, batch)
    assert staged is not None and staged["records"] == []
    proposal = {**batch, "message_id": "99999999-9999-4999-8999-999999999999", "kind": "personal_sync.deletion_proposals",
        "body": {"format": 1, "run_id": RUN, "proposal_batch_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "sequence": 0, "last": True, "proposals": []}}
    service.store.stage_personal_domain(private, proposal)
    service.replay_personal_sync()
    assert not events and len(service.store.peers) == 1 and service.store.peers[0]["device_id"] == peer["device_id"]
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Owned desktop")
    assert any(owner == private for owner, _ in reopened.ready_personal_batches())
    assert any(owner == private for owner, _ in reopened.ready_personal_domains())


def _stage_actor_commit(store):
    private = actor.storage_peer(RUN)
    store.remember_personal_run(private, REQUEST)
    now = phone.now_ms()
    batch = {"type":"message", "v":1, "message_id":"77777777-7777-4777-8777-777777777777", "kind":"personal_sync.batch",
        "created_ms":now, "expires_ms":now+60000, "body":{"format":3, "run_id":RUN,
        "batch_id":"88888888-8888-4888-8888-888888888888", "sequence":0, "last":True,
        "reply":False, "records_hash":phone.records_hash([]), "records":[]}}
    staged = store.stage_personal_batch(private, batch)
    references = []
    for message_id in ("99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"):
        message = {**batch, "message_id":message_id, "kind":"personal_sync.deletion_proposals",
            "body":{"format":1, "run_id":RUN, "proposal_batch_id":message_id,
                "sequence":len(references), "last":len(references) == 1, "proposals":[]}}
        intent = store.stage_personal_domain(private, message)
        references.append((message_id, intent["commit_token"]))
    return private, staged, references


@pytest.mark.parametrize('mode', ('missing', 'partial', 'foreign_token', 'extra', 'duplicate', 'expired', 'foreign_run'))
def test_actor_core_commit_does_not_partially_accept_unreviewed_intents(tmp_path, mode):
    service, peer, events = owned_service(tmp_path)
    store = service.store
    private, batch, references = _stage_actor_commit(store)
    chosen = copy.deepcopy(references)
    if mode == 'missing': chosen = None
    elif mode == 'partial': chosen = chosen[:1]
    elif mode == 'foreign_token': chosen[1] = (chosen[1][0], 'foreign')
    elif mode == 'extra': chosen.append((RUN, 'foreign'))
    elif mode == 'duplicate': chosen.append(chosen[0])
    elif mode == 'expired':
        with sqlite3.connect(store.database_path) as db:
            db.execute('UPDATE personal_domain SET expires_ms=0 WHERE message_id=?', (chosen[1][0],))
    elif mode == 'foreign_run':
        with sqlite3.connect(store.database_path) as db:
            row = db.execute('SELECT payload FROM personal_domain WHERE message_id=?', (chosen[1][0],)).fetchone()
            message = json.loads(store._decrypt(row[0], 'personal_domain', chosen[1][0]))
            message['body']['run_id'] = '22222222-2222-4222-8222-222222222222'
            db.execute('UPDATE personal_domain SET payload=? WHERE message_id=?',
                (store._encrypt(phone.canonical(message), 'personal_domain', chosen[1][0]), chosen[1][0]))
    if mode == 'duplicate':
        with pytest.raises(ValueError): store.commit_personal_batch(private, batch['message_id'], batch['commit_token'], actor_intents=chosen)
    else:
        assert store.commit_personal_batch(private, batch['message_id'], batch['commit_token'], actor_intents=chosen) == (private, [])
    assert store.has_personal_batch(private, batch['message_id'], batch['commit_token'])
    assert len(store.ready_personal_domains()) == 2
    assert all(store.dedupe_result(private, identity) is None for identity, token in references)
    assert not events and service.server is None


def test_actor_core_commit_accepts_exact_intents_atomically_and_survives_reopen(tmp_path):
    service, peer, events = owned_service(tmp_path)
    store = service.store
    private, batch, references = _stage_actor_commit(store)
    # A real SQLite failure after the first domain mutation must roll back the
    # intent receipt, deduplication and batch ledger as one unit.
    with sqlite3.connect(store.database_path) as db:
        db.execute("CREATE TRIGGER actor_commit_failure BEFORE DELETE ON personal_domain WHEN OLD.message_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.commit_personal_batch(private, batch['message_id'], batch['commit_token'], actor_intents=references)
    assert store.has_personal_batch(private, batch['message_id'], batch['commit_token'])
    assert len(store.ready_personal_domains()) == 2
    assert all(store.dedupe_result(private, identity) is None for identity, token in references)
    with sqlite3.connect(store.database_path) as db: db.execute('DROP TRIGGER actor_commit_failure')
    assert store.commit_personal_batch(private, batch['message_id'], batch['commit_token'], actor_intents=list(reversed(references))) == (private, [batch['message_id']])
    reopened = phone.PhoneStore(str(tmp_path / 'phone'), 'Owned desktop')
    assert not reopened.ready_personal_domains() and not reopened.ready_personal_batches()
    assert all(reopened.dedupe_result(private, identity) == ('accepted', 'none') for identity, token in references)
    assert reopened.commit_personal_batch(private, batch['message_id'], batch['commit_token'], actor_intents=references) == (private, [])
    assert not events and service.server is None


@pytest.mark.parametrize('kind,parent', (('note',''), ('task',''), ('attachment','scope-parent')))
def test_terminal_target_proof_binds_entity_parent_hash_and_clock_without_legacy_guessing(tmp_path, kind, parent):
    service, peer, events = owned_service(tmp_path)
    store = service.store; private = actor.storage_peer(RUN)
    clock = [{'actor_id':RUN, 'counter':2}]
    proposal = {'proposal_id':'33333333-3333-4333-8333-333333333333', 'kind':kind, 'id':'scope-target',
        'parent_id':parent, 'prior_hash':'a'*64, 'clock':clock, 'deleted_ms':0, 'label':'Not retained in target proof'}
    body = {'format':1, 'run_id':RUN, 'proposal_batch_id':RUN, 'sequence':0, 'last':True, 'proposals':[proposal]}
    decision = {'format':1, 'run_id':RUN, 'decision_id':'44444444-4444-4444-8444-444444444444',
        'decisions':[{'proposal_id':proposal['proposal_id'], 'decision':'restore', 'expected_clock':clock}]}
    assert store.personal_decision_targets(private, decision, False) is None
    store.remember_personal_proposal_kinds(private, body, True)
    target = {name:proposal[name] for name in ('proposal_id','kind','id','parent_id','prior_hash','clock')}
    assert store.personal_decision_targets(private, decision, False) == [target]
    value = store.personal_decision_targets(private, decision, False); value[0]['id'] = 'caller-edit'
    assert store.personal_decision_targets(private, decision, False) == [target]
    for field, value in [('id','foreign-target'), ('prior_hash','b'*64)] + ([('parent_id','foreign-parent')] if parent else []):
        changed = copy.deepcopy(body); changed['proposals'][0][field] = value
        with pytest.raises(ValueError): store.remember_personal_proposal_kinds(private, changed, True)
        assert store.personal_decision_targets(private, decision, False) == [target]
    key = 'personal_proposal_kind:%s:out:%s' % (private, proposal['proposal_id'])
    with sqlite3.connect(store.database_path) as db:
        raw = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0]
        saved = json.loads(store._decrypt(raw, 'personal_proposal_kind', key))
        legacy = {name:value for name,value in saved.items() if name != 'target'}
        db.execute('UPDATE meta SET value=? WHERE key=?', (store._encrypt(phone.canonical(legacy), 'personal_proposal_kind', key), key))
    assert store.personal_decision_kinds(private, decision, False) == [kind]
    assert store.personal_decision_targets(private, decision, False) is None
    store.remember_personal_proposal_kinds(private, body, True)
    reopened = phone.PhoneStore(str(tmp_path / 'phone'), 'Owned desktop')
    assert reopened.personal_decision_targets(private, decision, False) == [target]
    other = actor.storage_peer('22222222-2222-4222-8222-222222222222')
    assert reopened.personal_decision_targets(other, decision, False) is None
    stale = copy.deepcopy(decision); stale['decisions'][0]['expected_clock'][0]['counter'] += 1
    assert reopened.personal_decision_targets(private, stale, False) is None
    with sqlite3.connect(store.database_path) as db:
        saved['expires_ms'] = 0
        db.execute('UPDATE meta SET value=? WHERE key=?', (store._encrypt(phone.canonical(saved), 'personal_proposal_kind', key), key))
    assert reopened.personal_decision_targets(private, decision, False) is None
    assert not events and service.server is None
