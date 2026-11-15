"""Unconfirmed request state is neither a saved ACK nor restart replay authority."""
import copy
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from test_contact_notes_consent import Harness, native
from test_contact_notes_controller import Runtime
from magnolie_contact_notes_requests import NativeNotesRequestIntents, _FreshRequestIntention
from magnolie_contact_notes_return import NativeNotesAckIntents, NativeNotesPendingResult, NativeNotesSavedAckIntent


def clone_request(pending):
    return NativeNotesPendingResult(pending._snapshot, json.loads(pending._request_text), pending._local_id,
        pending._local_uid, pending._peer, pending._own, pending._capture, pending._mapping,
        before_revision=pending._before_revision, source_choice=pending._source_choice)


@pytest.mark.parametrize('mode', ['success', 'reload', 'same-uuid', 'new-uuid', 'new-setup', 'missing-key',
    'changed-key', 'forgotten-memory-proof', 'changed-primary', 'changed-primary-before-seal', 'missing-root-identity', 'forget-during-proof'])
def test_pre_save_intention_is_encrypted_private_durable_and_never_becomes_loaded_replay_permission(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); pending = h.choice.pending()
        key = [None if mode == 'missing-key' else b'J' * 32]
        root = tmp_path / 'requests'
        store = NativeNotesRequestIntents(root, lambda: key[0])
        def change_primary():
            changed = copy.deepcopy(h.probe._aktuelle_daten)
            changed['kontakte'][0]['notiz'] = 'Unknown authenticated primary content'
            native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(changed)))
        if mode == 'changed-primary-before-seal': change_primary()
        if mode in ('missing-key', 'changed-primary-before-seal'):
            with pytest.raises(PermissionError): store.seal(pending)
            assert not root.exists()
            return
        proof = store.seal(pending)
        assert proof.link(pending) == proof.key and store.seal(pending) is proof
        record = store.load_held(proof.key)
        assert record['state'] == 'request_pending' and record['request'] == pending.request()
        assert record['book_before'] == [pending._snapshot.saved_sha256, pending._snapshot.content_sha256]
        assert b'canonical-native-share' not in (root / ('r-' + proof.key + '.bin')).read_bytes()
        with pytest.raises(PermissionError): NativeNotesSavedAckIntent(record).body()
        ack_store = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: b'J' * 32)
        with pytest.raises(InvalidTag): ack_store._decode(proof.key, (root / ('r-' + proof.key + '.bin')).read_bytes())
        with pytest.raises(PermissionError):
            _FreshRequestIntention(store, proof.key, proof.physical, proof.ciphertext_hash, pending, object()).link(pending)
        before = {path.name: path.read_bytes() for path in root.iterdir() if path.name != '.lock'}
        if mode == 'reload':
            reloaded = NativeNotesRequestIntents(root, lambda: key[0])
            assert reloaded.load_held(proof.key) == record
            with pytest.raises(PermissionError): reloaded.seal(pending)
        if mode == 'same-uuid':
            with pytest.raises(PermissionError): store.seal(clone_request(pending))
        if mode == 'new-uuid':
            with pytest.raises(PermissionError): store.seal(h.choice.pending())
        if mode == 'new-setup':
            h.store.configure([h.choice])  # Separate genuine decision, not a portable setup flag.
            with pytest.raises(PermissionError): store.seal(h.choice.pending())
            with pytest.raises(PermissionError): proof.link(pending)
        if mode == 'changed-key':
            key[0] = b'K' * 32
            with pytest.raises(PermissionError): store.seal(h.choice.pending())
            with pytest.raises(PermissionError): store.load_held(proof.key)
        if mode == 'missing-root-identity':
            (root / '.journal-key').unlink()  # Own synthetic ledger marker only.
            before.pop('.journal-key')
            with pytest.raises(PermissionError): store.seal(h.choice.pending())
            with pytest.raises(PermissionError): proof.link(pending)
            assert not (root / '.journal-key').exists(), 'Unknown populated root adopted a replacement identity'
        if mode == 'forgotten-memory-proof':
            store.forget_process_proofs()
            with pytest.raises(PermissionError): proof.link(pending)
            with pytest.raises(PermissionError): store.seal(h.choice.pending())
        if mode == 'forget-during-proof':
            primary = h.store._primary
            def observe():
                observed = primary()
                store.forget_process_proofs()
                return observed
            h.store._primary = observe
            with pytest.raises(PermissionError): proof.link(pending)
        if mode == 'changed-primary':
            change_primary()
            with pytest.raises(PermissionError): proof.link(pending)
        assert {path.name: path.read_bytes() for path in root.iterdir() if path.name != '.lock'} == before
        assert not (tmp_path / 'outcomes').exists()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('step', ['physical_written', 'archive_written', 'after_readback'])
def test_interrupted_pre_save_write_never_mints_a_proof_or_allows_a_different_uuid_to_bypass_the_hold(native, tmp_path, step):
    h = Harness(native, tmp_path)
    try:
        h.configure(); pending = h.choice.pending()
        def interrupt(actual):
            if actual == step: raise OSError('Controlled pre-save intention interruption')
        root = tmp_path / 'requests'
        store = NativeNotesRequestIntents(root, lambda: b'J' * 32, stage=interrupt)
        with pytest.raises(OSError): store.seal(pending)
        assert not hasattr(pending, '_request_intention')
        before = {path.name: path.read_bytes() for path in root.iterdir() if path.name != '.lock'}
        reloaded = NativeNotesRequestIntents(root, lambda: b'J' * 32)
        for candidate in (clone_request(pending), h.choice.pending()):
            with pytest.raises(PermissionError): reloaded.seal(candidate)
        assert {path.name: path.read_bytes() for path in root.iterdir() if path.name != '.lock'} == before
        assert not (tmp_path / 'outcomes').exists()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('step', ['normal', 'terminal_archive_written', 'terminal_physical_written'])
def test_only_real_durable_settled_ack_retires_the_request_lease_and_old_ack_cannot_release_its_successor(native, monkeypatch, tmp_path, step):
    h = Harness(native, tmp_path)
    try:
        h.configure(); pending = h.choice.pending(); h.pending = pending
        requests = NativeNotesRequestIntents(tmp_path / 'requests', lambda: b'J' * 32)
        proof = requests.seal(pending); result = Runtime.result(pending.request())
        h.send(result)
        with h.probe._daten_sperre: commit = pending.prepare_commit()
        assert h.save(monkeypatch, invocation=commit)['ok']
        outcomes = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: b'J' * 32)
        ack = outcomes.seal_after_save(pending).body(); h.pending = None
        path, = (tmp_path / 'outcomes').glob('*.bin')
        assert outcomes.load_held(path.stem)['request_intention'] == proof.key
        with pytest.raises(PermissionError): requests.retire_from_terminal(ack)
        status = dict(result, art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=ack['desktop_sha256'])
        h.send(status); body, origin, transport = h.results.pop()
        intent = outcomes.reauthorize(path.stem, h.store, body, origin, transport)
        with pytest.raises(PermissionError): requests.retire_from_terminal(intent)  # Status alone is not durable local completion.
        outcomes.confirm_terminal(intent)
        intent = outcomes.reauthorize(path.stem, h.store, body, origin, transport)
        if step != 'normal':
            def interrupt(actual):
                if actual == step: raise OSError('Controlled local retirement interruption')
            requests._stage = interrupt
            with pytest.raises(OSError): requests.retire_from_terminal(intent)
            requests._stage = lambda _: None
        retired = requests.retire_from_terminal(intent)
        assert retired['state'] == 'request_settled'
        with pytest.raises(PermissionError): proof.link(pending)
        # New native quote + a later actual local edit, not a guessed UUID over a hold.
        export = dict(h.export, before_basis=result['next_basis'], native_revision=2,
            kontakt=dict(h.before, **result_target(pending)))
        from magnolie_contact_notes_return import notes_content_hash
        export['content_sha256'] = notes_content_hash(export['kontakt'])
        changed = copy.deepcopy(h.probe._aktuelle_daten); changed['kontakte'][0]['notiz'] = 'Next actual saved edit'
        assert h.save(monkeypatch, changed)['ok']
        observed = h.observed(export)
        with h.probe._daten_sperre: choice = h.store.restore(*observed)
        successor = choice.pending(); next_proof = requests.seal(successor)
        physical = tmp_path / 'requests' / ('p-' + next_proof.physical + '.bin')
        held = physical.read_bytes()
        again = outcomes.reauthorize(path.stem, h.store, body, origin, transport)
        assert requests.retire_from_terminal(again) == retired
        assert physical.read_bytes() == held and next_proof.link(successor) == next_proof.key
    finally:
        h.service.anhalten()


def result_target(pending):
    return json.loads(pending._request_text)['ziel']


def test_controller_stop_during_sealing_retains_the_disk_hold_but_mints_no_fresh_provider_send_proof(native, tmp_path):
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h); runtime.negotiate(); c = runtime.controller
        def stop(step):
            if step == 'archive_written': c.stop()
        c._requests._stage = stop
        h.send(h.export)
        assert c.process_one().kind == 'held'
        assert c._requests._fresh == {} and not (tmp_path / 'outcomes').exists()
        assert list(Path(c._requests.root).glob('p-*.bin'))
        fresh_store = NativeNotesRequestIntents(c._requests.root, lambda: b'J' * 32)
        with pytest.raises(PermissionError): fresh_store.seal(h.choice.pending())
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['success', 'physical-only', 'revoked', 'changed-key', 'unknown-primary',
    'memory-impostor', 'missing-data', 'wrong-pins', 'copied-query', 'late-revoke', 'changed-request-record'])
def test_unconfirmed_reload_can_query_readonly_without_a_saved_witness_but_never_replay_or_ack(native, tmp_path, mode):
    from magnolie_contact_notes_return import NativeNotesProtocolNegotiation
    h = Harness(native, tmp_path)
    sessions = []
    try:
        h.configure(); pending = h.choice.pending(); request = pending.request()
        key = [b'J' * 32]
        root = tmp_path / 'requests'
        store = NativeNotesRequestIntents(root, lambda: key[0])
        proof = store.seal(pending)
        if mode == 'physical-only': (root / ('r-' + proof.key + '.bin')).unlink()  # Own synthetic crash state.
        h.restart()
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        reloaded = NativeNotesRequestIntents(root, lambda: key[0])
        if mode == 'revoked': h.store.revoke()
        if mode == 'changed-key': key[0] = b'K' * 32
        if mode == 'missing-data': h.store._native_data = None
        if mode in ('unknown-primary', 'memory-impostor'):
            changed = copy.deepcopy(h.probe._aktuelle_daten); changed['kontakte'][0]['notiz'] = 'Unrecognized current contents'
            if mode == 'unknown-primary': native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(changed)))
            h.probe._aktuelle_daten = changed
        before = {p.name: p.read_bytes() for p in root.iterdir() if p.name != '.lock'}
        before_book = Path(native.daten_datei()).read_bytes()
        if mode in ('revoked', 'changed-key', 'missing-data', 'unknown-primary', 'memory-impostor'):
            with pytest.raises(PermissionError): reloaded.readonly_query(proof.key, h.store, physical=proof.physical)
        else:
            query = reloaded.readonly_query(proof.key, h.store, physical=proof.physical)
            payload = query.request()
            assert set(payload) == {'art', 'fassung', 'request_id', 'request_sha256', 'share_id', 'before_basis', 'target_sha256'}
            assert payload['request_id'] == request['request_id'] and 'ziel' not in payload
            with pytest.raises(PermissionError): NativeNotesSavedAckIntent(query).body()
            with pytest.raises(PermissionError): native.baum_notes_anfrage_senden(lambda: h.receiver, query, None, lambda: True)
            peer = native.baum_partner(h.receiver, h.sender['kennung'])
            peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
            protocol = NativeNotesProtocolNegotiation((h.sender['kennung'], h.sender['oeffentlich']),
                (h.receiver['kennung'], h.receiver['oeffentlich']))
            h.send(dict(protocol.request(), antwort=True)); protocol.accept(*h.results.pop())
            if mode == 'wrong-pins':
                protocol._peer = ('another-native-peer', h.sender['oeffentlich'])
            if mode == 'copied-query': query = payload
            if mode == 'late-revoke': h.store.revoke()
            if mode == 'changed-request-record':
                physical = root / ('p-' + proof.physical + '.bin')
                blob = physical.read_bytes(); physical.write_bytes(blob[:-1] + bytes([blob[-1] ^ 1]))
                before[physical.name] = physical.read_bytes()
            calls = []
            def send(url, body):
                calls.append(url)
                if url.endswith('/sitzung'):
                    answer, session = native.fs_antwort_bauen(h.sender,
                        {'kennung': h.receiver['kennung'], 'oeffentlich': h.receiver['oeffentlich']}, body)
                    sessions.append(session); return answer
                session = sessions[-1]
                clear, _ = native.umschlag_oeffnen_fs(session, h.sender['kennung'], h.receiver['kennung'], body)
                assert clear == payload and clear['art'] == 'kontakt_original_statusanfrage'
                return native.fs_ack_bauen(session, body)
            if mode in ('success', 'physical-only'):
                assert native.baum_notes_statusanfrage_senden(lambda: h.receiver, query, protocol, lambda: True, sender=send)
                assert len(calls) == 2
            else:
                with pytest.raises((PermissionError, InvalidTag)):
                    native.baum_notes_statusanfrage_senden(lambda: h.receiver, query, protocol, lambda: True, sender=send)
                assert calls == []
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        assert Path(native.daten_datei()).read_bytes() == before_book
        assert {p.name: p.read_bytes() for p in root.iterdir() if p.name != '.lock'} == before
        assert reloaded._fresh == {} and not (tmp_path / 'outcomes').exists()
    finally:
        for session in sessions: native.fs_sitzung_loeschen(session)
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['success', 'physical-only', 'no-bootstrap', 'wrong-result', 'bool-version',
    'status-without-saved-history', 'changed-local-target', 'known-unrelated-save', 'late-revoke', 'expired-origin', 'metadata-written-before-crash'])
def test_resumed_unconfirmed_request_requires_fresh_verified_result_and_real_native_saves_before_ack(native, monkeypatch, tmp_path, mode):
    from magnolie_contact_notes_requests import NativeNotesRecoveryNeedsSave
    from magnolie_contact_notes_return import NativeNotesProtocolNegotiation
    h = Harness(native, tmp_path)
    try:
        h.configure(); original = h.choice.pending()
        store = NativeNotesRequestIntents(tmp_path / 'requests', lambda: b'J' * 32)
        proof = store.seal(original); request = original.request()
        if mode == 'metadata-written-before-crash':
            h.pending = original
            h.send(Runtime.result(request))
            with h.probe._daten_sperre: old_commit = original.prepare_commit()
            assert h.save(monkeypatch, invocation=old_commit)['ok']
            h.pending = None
            assert not (tmp_path / 'outcomes').exists(), 'Fixture accidentally sealed the old ACK'
        if mode == 'physical-only': (tmp_path / 'requests' / ('r-' + proof.key + '.bin')).unlink()
        h.restart()
        store = NativeNotesRequestIntents(tmp_path / 'requests', lambda: b'J' * 32)
        query = store.readonly_query(proof.key, h.store, physical=proof.physical)
        body = Runtime.result(request)
        if mode == 'wrong-result': body['target_sha256'] = '0' * 64
        if mode == 'bool-version': body['fassung'] = True
        if mode == 'status-without-saved-history':
            body.update(art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256='e' * 64)
        h.send(body); body, origin, transport = h.results.pop()
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        if mode in ('wrong-result', 'bool-version', 'status-without-saved-history'):
            with pytest.raises(PermissionError): store.resume_verified(query, body, origin, transport)
            assert h.probe._kontakt_quellen_buchaufnahme() is None and not (tmp_path / 'outcomes').exists()
            return
        with pytest.raises(NativeNotesRecoveryNeedsSave): store.resume_verified(query, body, origin, transport)
        if mode == 'no-bootstrap':
            assert h.probe._kontakt_quellen_buchaufnahme() is None and store._fresh == {}
            return
        if mode == 'expired-origin': h.service.anhalten()
        proposed = copy.deepcopy(h.probe._aktuelle_daten)
        if mode == 'changed-local-target': proposed['kontakte'][0]['notiz'] = 'Different actual later edit'
        if mode == 'known-unrelated-save': proposed['known-native-later-value'] = 'must survive'
        assert h.save(monkeypatch, proposed)['ok'], 'Bootstrap must use the real ordinary encrypted writer'
        if mode in ('changed-local-target', 'expired-origin'):
            before = Path(native.daten_datei()).read_bytes()
            with pytest.raises(PermissionError): store.resume_verified(query, body, origin, transport)
            assert Path(native.daten_datei()).read_bytes() == before and not (tmp_path / 'outcomes').exists()
            return
        with h.probe._daten_sperre: pending = store.resume_verified(query, body, origin, transport)
        assert pending.request() == request and pending._source_choice is None
        assert store._fresh == {}, 'Reload minted a fresh provider mutation stamp'
        protocol = NativeNotesProtocolNegotiation(tuple(pending._peer), tuple(pending._own))
        with pytest.raises(PermissionError): pending._for_negotiated_protocol(protocol)
        if mode == 'late-revoke':
            h.store.revoke()
            with pytest.raises(PermissionError): pending.prepare_commit()
            return
        outcomes = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: b'J' * 32)
        with pytest.raises(PermissionError): outcomes.seal_after_save(pending)
        with h.probe._daten_sperre: commit = pending.prepare_commit()
        assert h.save(monkeypatch, invocation=commit)['ok']
        ack = outcomes.seal_after_save(pending).body()
        assert ack['request_id'] == request['request_id'] and ack['request_sha256'] == body['request_sha256']
        path, = (tmp_path / 'outcomes').glob('*.bin')
        assert outcomes.load_held(path.stem)['request_intention'] == proof.key
        assert h.probe._kontakt_quellen_buchaufnahme().sequence == 2, 'No writer witness may be fabricated from the initial primary read'
        if mode == 'known-unrelated-save': assert h.probe._aktuelle_daten['known-native-later-value'] == 'must survive'
    finally:
        h.service.anhalten()
