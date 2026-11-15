"""#636 native before-dialog context against actual synthetic encrypted saves.

No GTK dialog, socket, installed profile/keyring or original provider is opened.
"""
import copy
from pathlib import Path

import pytest

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_consent import NativeNotesSetupDecision
from magnolie_contact_notes_return import NativeNotesExportChoice


def choose(h, snapshot, local_id='second-id', guard=None):
    body, origin, transport = h.observed(dict(h.export, share_id='setup-native-share',
        setup_id='55555555-5555-4555-8555-555555555555'))
    result = NativeNotesExportChoice(body, origin, transport, snapshot,
        h.probe._kontakt_quellen_buchaufnahme, lambda _: local_id)
    if guard is not None:
        result._persistent_guard = guard
    return result


@pytest.mark.parametrize('mode', ['initial', 'addition', 'cancel', 'revoke-initial', 'revoke-addition', 'other-store-revoke',
    'replace', 'other-store-replace', 'native-save', 'one-use', 'forged-decision', 'forged-choice', 'revoked-before',
    'unknown-primary', 'pending', 'lost-key', 'revoke-before-publish', 'callbacks-outside-lock'])
def test_native_setup_decision_keeps_before_dialog_book_and_private_cas(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        book = copy.deepcopy(h.probe._aktuelle_daten)
        other = copy.deepcopy(book['kontakte'][0]); other.update(id='second-id', uid='second-uid')
        book['kontakte'].append(other)
        assert h.save(monkeypatch, book)['ok']
        adding = mode in ('addition', 'revoke-addition', 'other-store-revoke', 'replace', 'other-store-replace',
            'unknown-primary', 'pending', 'lost-key', 'callbacks-outside-lock')
        if adding or mode == 'revoked-before': h.configure()
        if mode == 'revoked-before': h.store.revoke()
        if mode == 'unknown-primary':
            changed = copy.deepcopy(h.probe._aktuelle_daten); changed['untracked'] = True
            native.speichere_text(h.probe._vielleicht_verschluesseln(__import__('json').dumps(changed)))
        if mode == 'pending': Path(h.root, '.transaction').write_bytes(b'pending\n')
        if mode == 'lost-key': Path(h.root, '.key').unlink()
        if mode in ('unknown-primary', 'pending', 'lost-key'):
            with pytest.raises((PermissionError, FileNotFoundError)):
                with h.probe._daten_sperre: h.store.begin_setup_decision()
            return
        if mode == 'forged-decision':
            with pytest.raises(PermissionError): NativeNotesSetupDecision({}).commit(object())
            assert not Path(h.root).exists()
            return
        if mode == 'callbacks-outside-lock':
            capture = h.store._capture
            def outside():
                assert h.store.has_desired_consent()
                return capture()
            h.store._capture = outside
        with h.probe._daten_sperre: decision = h.store.begin_setup_decision()
        assert decision.is_addition == adding
        key = Path(h.root, '.key').read_bytes() if Path(h.root, '.key').exists() else None
        assert adding or mode == 'revoked-before' or not Path(h.root).exists(), 'Pre-dialog read initialized a consent root'
        if mode == 'cancel':
            assert not Path(h.root).exists()  # No commit on native chooser cancellation.
            return
        # Dialog phase is outside the native book/private gates. These are native
        # operations, not renderer IDs/status grants or copied consent records.
        if mode in ('revoke-initial', 'revoke-addition'): h.store.revoke()
        if mode == 'other-store-revoke': h.new_store().revoke()
        if mode == 'replace': h.store.configure([h.choice])
        if mode == 'other-store-replace': h.new_store().configure([h.choice])
        if mode == 'native-save':
            edit = copy.deepcopy(h.probe._aktuelle_daten); edit['during-dialog'] = 'preserve'
            assert h.save(monkeypatch, edit)['ok']
        before = Path(native.daten_datei()).read_bytes()
        if mode == 'forged-choice': selected = object()
        elif mode == 'native-save': selected = choose(h, h.probe._kontakt_quellen_buchaufnahme())
        else: selected = choose(h, decision.snapshot, guard=h.store.revoke if mode == 'revoke-before-publish' else None)
        if mode in ('initial', 'addition', 'one-use', 'revoked-before', 'callbacks-outside-lock'):
            with h.probe._daten_sperre: decision.commit(selected)
            active = h.store._active_record()
            assert len(active[1]['choices']) == (2 if adding else 1)
            assert any(source['local_id'] == 'second-id' and source['local_uid'] == 'second-uid' and
                source['share_id'] == 'setup-native-share' for source in active[1]['choices'])
            if adding: assert Path(h.root, '.key').read_bytes() == key
            if mode == 'one-use':
                written = Path(h.root, 'choices.aes').read_bytes()
                with pytest.raises(PermissionError, match='already_used'): decision.commit(selected)
                assert Path(h.root, 'choices.aes').read_bytes() == written
        else:
            with pytest.raises(PermissionError):
                with h.probe._daten_sperre: decision.commit(selected)
        assert Path(native.daten_datei()).read_bytes() == before
        if mode in ('revoke-initial', 'revoke-addition', 'other-store-revoke', 'revoke-before-publish'):
            assert not h.store.has_desired_consent()
        if mode in ('native-save', 'forged-choice', 'revoke-initial', 'revoke-before-publish'):
            assert not Path(h.root, '.key').exists()
    finally:
        h.service.anhalten()
