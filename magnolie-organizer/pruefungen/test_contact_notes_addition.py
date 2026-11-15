"""#637: synthetic native choices, actual encrypted saves, no installed sources."""
import copy
from pathlib import Path

import pytest

from test_contact_notes_consent import Harness, native
from test_contact_notes_controller import Runtime
from magnolie_contact_notes_return import NativeNotesExportChoice, NativeNotesAckIntents
from magnolie_contact_notes_requests import NativeNotesRequestIntents


def second_choice(h, *, local_id='second-id', share='second-share', guard=None):
    body, origin, transport = h.observed(dict(h.export, share_id=share,
        setup_id='55555555-5555-4555-8555-555555555555'))
    choice = NativeNotesExportChoice(body, origin, transport, h.probe._kontakt_quellen_buchaufnahme(),
        h.probe._kontakt_quellen_buchaufnahme, lambda _: local_id)
    if guard is not None:
        choice._persistent_guard = guard
    return choice


def two_contacts(h, monkeypatch):
    book = copy.deepcopy(h.probe._aktuelle_daten)
    other = copy.deepcopy(book['kontakte'][0]); other.update(id='second-id', uid='second-uid')
    book['kontakte'].append(other)
    assert h.save(monkeypatch, book)['ok']
    h.configure()


@pytest.mark.parametrize('operation', ['replace', 'add'])
def test_saved_history_survives_only_monotone_source_addition(native, monkeypatch, tmp_path, operation):
    h = Harness(native, tmp_path)
    try:
        two_contacts(h, monkeypatch)
        pending = h.choice.pending(); h.pending = pending
        requests = NativeNotesRequestIntents(tmp_path / 'requests', lambda: b'J' * 32)
        proof = requests.seal(pending); result = Runtime.result(pending.request())
        h.send(result)
        with h.probe._daten_sperre: commit = pending.prepare_commit()
        assert h.save(monkeypatch, invocation=commit)['ok']
        outcomes = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: b'J' * 32)
        ack = outcomes.seal_after_save(pending).body(); h.pending = None
        history_path, = (tmp_path / 'outcomes').glob('*.bin')
        history_key = history_path.stem
        assert outcomes.readonly_query(history_key, h.store).request()
        added = second_choice(h)
        body, origin, transport = h.observed()
        fresh = NativeNotesExportChoice(body, origin, transport, h.probe._kontakt_quellen_buchaufnahme(),
            h.probe._kontakt_quellen_buchaufnahme, lambda contacts: contacts[0]['id'])
        key = Path(h.root, '.key').read_bytes()
        primary = Path(native.daten_datei()).read_bytes()
        history = {p.name: p.read_bytes() for p in (tmp_path / 'outcomes').iterdir() if p.name != '.lock'}
        with h.probe._daten_sperre:
            if operation == 'replace': h.store.configure([fresh, added])
            else: h.store.add_sources([added])
        assert Path(native.daten_datei()).read_bytes() == primary
        assert {p.name: p.read_bytes() for p in (tmp_path / 'outcomes').iterdir() if p.name != '.lock'} == history
        if operation == 'replace':
            assert Path(h.root, '.key').read_bytes() != key
            with pytest.raises(PermissionError, match='notes_choice_ack_binding_changed'):
                outcomes.readonly_query(history_key, h.store)
            return
        assert Path(h.root, '.key').read_bytes() == key
        assert outcomes.readonly_query(history_key, h.store).request()
        approval = Path(h.root, 'choices.aes').read_bytes()
        h.store.add_sources([added])
        assert Path(h.root, 'choices.aes').read_bytes() == approval
        assert added.pending() is not None
        status = dict(result, art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=ack['desktop_sha256'])
        h.send(status); body, origin, transport = h.results.pop()
        restored = outcomes.reauthorize(history_key, h.store, body, origin, transport)
        outcomes.confirm_terminal(restored)
        restored = outcomes.reauthorize(history_key, h.store, body, origin, transport)
        assert requests.retire_from_terminal(restored)['state'] == 'request_settled'
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['fresh', 'loaded-query', 'missing', 'revoked', 'collision-id', 'collision-share',
    'changed-setup', 'fake-choice', 'unknown-book', 'concurrent-revoke', 'concurrent-replace', 'pending', 'lost-key', 'stale-choice'])
def test_source_addition_is_narrow_native_and_cas_bound(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        two_contacts(h, monkeypatch)
        pending = h.choice.pending()
        requests = NativeNotesRequestIntents(tmp_path / 'requests', lambda: b'J' * 32)
        proof = requests.seal(pending) if mode in ('fresh', 'loaded-query') else None
        def guard():
            if mode == 'concurrent-revoke': h.store.revoke()
            elif mode == 'concurrent-replace': h.store.configure([h.choice])
            elif mode == 'stale-choice': raise PermissionError('synthetic_expired_selection')
        added = second_choice(h,
            local_id=pending._local_id if mode in ('collision-id', 'changed-setup') else 'second-id',
            share=h.export['share_id'] if mode == 'collision-share' else 'second-share',
            guard=guard if mode in ('concurrent-revoke', 'concurrent-replace', 'stale-choice') else None)
        if mode == 'missing':
            # Use an empty owned private root, not deleted production state.
            h.store.root = str(tmp_path / 'empty-consent')
        if mode == 'revoked': h.store.revoke()
        if mode == 'pending': Path(h.root, '.transaction').write_bytes(b'pending\n')
        if mode == 'lost-key': Path(h.root, '.key').unlink()
        if mode == 'unknown-book':
            changed = copy.deepcopy(h.probe._aktuelle_daten); changed['untracked'] = True
            native.speichere_text(h.probe._vielleicht_verschluesseln(__import__('json').dumps(changed)))
        before = Path(native.daten_datei()).read_bytes()
        if mode in ('fresh', 'loaded-query'):
            h.store.add_sources([added])
            assert proof.link(pending) == proof.key
            reloaded = NativeNotesRequestIntents(tmp_path / 'requests', lambda: b'J' * 32)
            assert reloaded.load_held(proof.key)['request'] == pending.request()
            with pytest.raises(PermissionError): reloaded.seal(pending)
        else:
            with pytest.raises((PermissionError, FileNotFoundError)):
                h.store.add_sources([object() if mode == 'fake-choice' else added])
        assert Path(native.daten_datei()).read_bytes() == before
        if mode == 'concurrent-revoke': assert not h.store.has_desired_consent()
    finally:
        h.service.anhalten()
