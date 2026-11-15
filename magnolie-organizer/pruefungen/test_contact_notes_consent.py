"""Genuine FS1 choice -> private consent -> actual encrypted writer/restart.

All data paths, keys and peers are isolated synthetic fixtures. No installed
notebook/provider/keyring is read; no sockets or native setup UI are started.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
from types import MethodType, SimpleNamespace

import pytest

from test_contact_notes_fs_origin import fixture, frame
from test_contact_notes_pending_result import prepare_native_book
from test_startup_read_failure import native
from magnolie_contact_notes_consent import NativeNotesChoiceStore
from magnolie_contact_notes_return import (NativeNotesExportChoice, NativeNotesAckIntents,
    notes_content_hash, _frame_bytes)
from magnolie_contact_source_book import NativeContactSourceBook


class Harness:
    def __init__(self, native, tmp_path):
        self.native = native
        self.probe, self.book, self.replies, self.snapshots, _, _ = prepare_native_book(native)
        self.probe._kontakt_quellen_hauptdatei_aufnahme = MethodType(native.Fenster._kontakt_quellen_hauptdatei_aufnahme, self.probe)
        self.root = str(tmp_path / 'notes-consent')
        self.sequence, self.exports, self.results, self.pending, self.choices = 0, [], [], None, 0
        def accept(peer, body, origin, transport):
            if body['art'] == 'kontakt_original_export': self.exports.append((body, origin, transport))
            else:
                self.results.append((body, origin, transport))
                if self.pending is not None: self.pending.stage_result(body, origin, transport)
            return True
        self.sender, self.receiver, _, _, self.service = fixture(native, accept)
        self.before = {'notiz': 'Native before', 'telefone': [{'art': 'mobil', 'wert': '+123'}]}
        self.export = {'art': 'kontakt_original_export', 'fassung': 1, 'share_id': 'canonical-native-share',
            'setup_id': '44444444-4444-4444-8444-444444444444', 'before_basis': 'b' * 64,
            'native_revision': 1, 'kontakt': self.before, 'content_sha256': notes_content_hash(self.before)}
        self.store = self.new_store()
        self.probe._notes_original_choice_store = self.store  # Native injection only; production remains unregistered.

    def new_store(self):
        return NativeNotesChoiceStore(self.root, self.probe._kontakt_quellen_buchaufnahme,
            lambda: os.path.realpath(self.native.daten_datei()), self.probe._kontakt_quellen_hauptdatei_aufnahme,
            current_native_data=lambda: self.probe._aktuelle_daten)

    def send(self, body):
        self.sequence += 1
        channel, envelope, _ = frame(self.native, self.service, self.sender, self.receiver, body, bytes([self.sequence]) * 16)
        try:
            status, ack = self.service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')
            assert status == 200 and self.native.fs_ack_pruefen(channel, envelope, ack)
        finally:
            self.native.fs_sitzung_loeschen(channel)

    def observed(self, body=None):
        self.send(self.export if body is None else body)
        return self.exports.pop()

    def configure(self):
        body, origin, transport = self.observed()
        def choose(contacts):
            self.choices += 1
            return contacts[0]['id']
        self.choice = NativeNotesExportChoice(body, origin, transport, self.probe._kontakt_quellen_buchaufnahme(),
            self.probe._kontakt_quellen_buchaufnahme, choose)
        with self.probe._daten_sperre:
            self.store.configure([self.choice])
        assert self.choices == 1 and self.store.recognizes_saved()
        primary = self.probe._kontakt_quellen_hauptdatei_aufnahme()
        assert primary.saved_sha256 != self.probe._kontakt_quellen_buchaufnahme().saved_sha256, 'Envelope and clear SaveACK domains were confused'

    def restore(self, body=None):
        observed = self.observed(body)
        with self.probe._daten_sperre:
            choice = self.store.restore(*observed)
        assert self.choices == 1, 'Restart restoration asked for another native choice'
        return choice

    def save(self, monkeypatch, proposed=None, repair=False, invocation=None):
        monkeypatch.setattr(self.native, 'erinnerungsdaten_schreiben', lambda **_: not repair)
        text = invocation.text if invocation is not None else json.dumps(proposed or self.probe._aktuelle_daten, ensure_ascii=False)
        self.probe._speicher_auftraege.put((len(self.replies) + 1, text, None, None, invocation))
        self.probe._speicher_auftraege.put(None)
        thread = threading.Thread(target=self.native.Fenster._speicher_lauf, args=(self.probe,), daemon=True)
        thread.start(); thread.join(timeout=15)
        assert not thread.is_alive()
        return [value for callback, value in self.replies if callback == 'App.gespeichert'][-1]

    def restart(self):
        self.service.anhalten()  # Pinned identities survive; old session proofs do not.
        self.probe._kontakt_quellen_buch = NativeContactSourceBook()
        self.probe._kontakt_quellen_buch.set_ready(True)
        self.store = self.new_store()
        self.probe._notes_original_choice_store = self.store
        assert self.probe._kontakt_quellen_buchaufnahme() is None


@pytest.mark.parametrize('mode', ['ordinary', 'same-content', 'restart', 'missing-key', 'unknown-primary',
    'repair-then-save', 'prepare-failure', 'confirm-failure-recover', 'revoked', 'changed-native-setup',
    'wrong-primary-binding', 'ack-history-after-revoke', 'changed-peer-pin', 'changed-own-pin', 'damaged-consent'])
def test_private_notes_choice_follows_actual_native_encrypted_saves_without_reprompt(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure()
        key = Path(h.root, '.key').read_bytes()
        assert len(key) == 32 and b'canonical-person' not in Path(h.root, 'choices.aes').read_bytes()
        if mode == 'changed-native-setup':
            changed = dict(h.export, setup_id='55555555-5555-4555-8555-555555555555')
            with pytest.raises(PermissionError): h.restore(changed)
            assert h.choices == 1
            return
        if mode == 'wrong-primary-binding':
            h.store._binding = lambda: '/synthetic-different-primary'
            with pytest.raises(PermissionError): h.restore()
            return
        if mode in ('changed-peer-pin', 'changed-own-pin'):
            h.service.anhalten()
            if mode == 'changed-peer-pin':
                h.sender = native.baum_schluessel_erzeugen('Other synthetic peer')
            else:
                h.receiver.clear()
                h.receiver.update(native.baum_schluessel_erzeugen('Other synthetic own identity'))
                h.receiver.update(an=True, syncEpoch='synthetic-origin-epoch')
            peer = native.baum_partner_aufnehmen(h.receiver, h.sender['name'], h.sender['kennung'],
                h.sender['oeffentlich'], '127.0.0.1')
            peer['bestaetigt'] = True
            with pytest.raises(PermissionError): h.restore()
            assert h.choices == 1
            return
        if mode == 'revoked':
            h.store.revoke()
            assert not h.store.has_desired_consent()
            with pytest.raises(PermissionError): h.choice.require_current()
            with pytest.raises(PermissionError): h.restore()
            return
        if mode == 'ack-history-after-revoke':
            h.pending = h.choice.pending(); request = h.pending.request()
            result = {'art': 'kontakt_original_ergebnis', 'fassung': 1,
                **{name: request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')},
                'request_sha256': hashlib.sha256(_frame_bytes(request)).hexdigest(),
                'receipt_id': '22222222-2222-4222-8222-222222222222', 'native_revision': 2, 'next_basis': 'd' * 64}
            h.send(result)
            with h.probe._daten_sperre: invocation = h.pending.prepare_commit()
            assert h.save(monkeypatch, invocation=invocation)['ok']
            intents = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: b'J' * 32)
            intent = intents.seal_after_save(h.pending)
            path, = (tmp_path / 'outcomes').glob('*.bin')
            assert key != b'J' * 32 and intent.body()['receipt_id'] == result['receipt_id']
            h.store.revoke()
            with pytest.raises(PermissionError): intent.body()
            assert intents.load_held(path.stem)['result'] == result
            return
        if mode == 'restart': h.restart()
        if mode == 'missing-key': Path(h.root, '.key').unlink()
        if mode == 'damaged-consent':
            path = Path(h.root, 'choices.aes'); original = path.read_bytes()
            path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        proposed = copy.deepcopy(h.probe._aktuelle_daten)
        if mode not in ('same-content', 'restart'): proposed['kontakte'][0]['notiz'] = 'Next saved native edit'
        if mode == 'unknown-primary':
            text = json.dumps(proposed)
            native.speichere_text(h.probe._vielleicht_verschluesseln(text))
            h.probe._aktuelle_daten = proposed
            h.restart()
        actual_write = h.store._write
        def write(directory, name, value):
            if mode == 'prepare-failure' and name == '.book-intent.json': raise OSError('Controlled prepare failure')
            actual_write(directory, name, value)
            if mode == 'confirm-failure-recover' and name == 'choices.aes': raise OSError('Controlled post-content advance failure')
        h.store._write = write
        response = h.save(monkeypatch, proposed, repair=mode == 'repair-then-save')
        assert response['ok'] and response['committed'], ('Consent-sidecar errors blocked an ordinary book save', response)
        assert json.loads(native.daten_entschluesseln(Path(native.daten_datei()).read_text(), h.probe._kennwort)) == proposed
        if mode == 'missing-key':
            assert not Path(h.root, '.key').exists()
            with pytest.raises(FileNotFoundError): h.restore()
        elif mode == 'damaged-consent':
            from cryptography.exceptions import InvalidTag
            with pytest.raises(InvalidTag): h.restore()
            assert Path(h.root, '.key').read_bytes() == key
        elif mode in ('unknown-primary', 'prepare-failure'):
            assert not h.store.recognizes_saved()
            with pytest.raises(PermissionError): h.restore()
            assert h.probe._notes_original_choice_error == 'notes_choice_save_preparation_failed'
        elif mode == 'repair-then-save':
            assert response['repairPending'] and h.probe._kontakt_quellen_buchaufnahme() is None
            with pytest.raises(PermissionError): h.restore()
            assert h.save(monkeypatch)['ok']
            h.restore().pending()
        elif mode == 'confirm-failure-recover':
            assert h.probe._notes_original_choice_error == 'notes_choice_save_confirmation_failed'
            assert not h.store.recognizes_saved()
            h.store._write = actual_write
            h.store.recover_saved(h.probe._kontakt_quellen_buchaufnahme())
            h.restore().pending()
        else:
            assert not response['repairPending'] and h.store.recognizes_saved()
            h.restore().pending()
            assert Path(h.root, '.key').read_bytes() == key
            if mode == 'restart': assert h.probe._kontakt_quellen_buchaufnahme().sequence == 1
    finally:
        h.service.anhalten()


def test_absent_or_copied_notes_consent_creates_no_default_key_or_choice(native, tmp_path):
    h = Harness(native, tmp_path)
    try:
        assert not h.store.has_desired_consent() and not Path(h.root).exists()
        h.store.revoke(); assert not Path(h.root).exists()
        with pytest.raises(PermissionError): h.store.configure([{'setup_id': h.export['setup_id'], 'native': True}])
        assert not Path(h.root).exists()
        with pytest.raises(PermissionError): h.store.restore(h.export, h.export, 'copied')
        assert not Path(h.root).exists()
        from magnolie_contact_source_authority import NativeStoredContactApproval, NativeContactSourcePrimaryBook as old_primary
        from magnolie_contact_book_save_chain import NativeContactSourcePrimaryBook as shared_primary
        assert old_primary is shared_primary, 'Existing native primary witness API identity changed'
        copied_dav = NativeStoredContactApproval(h.store, '', '', '', None, ())
        with pytest.raises(TypeError): copied_dav.require_current()
        assert not Path(h.root).exists(), 'Shared save chain accidentally supplied DAV authority to Notes'
    finally:
        h.service.anhalten()


def test_native_choice_cannot_register_memory_when_the_authenticated_primary_file_is_different(native, tmp_path):
    h = Harness(native, tmp_path)
    try:
        changed = copy.deepcopy(h.probe._aktuelle_daten)
        changed['kontakte'][0]['notiz'] = 'External synthetic primary change'
        native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(changed)))
        with pytest.raises(PermissionError): h.configure()
        assert not Path(h.root).exists(), 'A stale in-memory choice created consent for a different primary'
    finally:
        h.service.anhalten()


def test_shared_native_book_chain_is_in_all_existing_linux_source_manifests():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
                 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        for module in ('magnolie_contact_book_save_chain.py', 'magnolie_contact_notes_return.py', 'magnolie_contact_notes_consent.py'):
            assert module in (root / name).read_text()
    json.loads((root / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())


def test_actual_startup_notes_reader_creates_no_files_and_calls_no_book_or_key_callbacks(native):
    def forbidden(): pytest.fail('Default startup reader touched a book or key callback')
    probe = SimpleNamespace(_kontakt_quellen_buchaufnahme=forbidden, _kontakt_quellen_hauptdatei_aufnahme=forbidden)
    store = native.Fenster._notes_original_choice_store_hole(probe)
    assert native.Fenster._notes_original_choice_store_hole(probe) is store
    assert not Path(store.root).exists() and not store.has_desired_consent()
    assert store.prepare_current_save('{}') is None and not Path(store.root).exists()


@pytest.mark.parametrize('outcome', ['old', 'new'])
def test_known_primary_save_intent_recovers_across_fresh_owner_but_is_not_a_saved_witness(native, monkeypatch, tmp_path, outcome):
    h = Harness(native, tmp_path)
    try:
        h.configure(); key = Path(h.root, '.key').read_bytes()
        proposed = copy.deepcopy(h.probe._aktuelle_daten)
        proposed['kontakte'][0]['notiz'] = 'Known proposed native outcome'
        text = json.dumps(proposed, ensure_ascii=False)
        h.store.prepare_current_save(text)
        if outcome == 'new':
            native.speichere_text(h.probe._vielleicht_verschluesseln(text))
            h.probe._aktuelle_daten = proposed
        h.restart()
        observed = h.probe._kontakt_quellen_hauptdatei_aufnahme()
        assert h.store.recover_primary(observed) == observed.content_sha256
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        with pytest.raises(PermissionError): h.restore()
        assert h.save(monkeypatch)['ok']
        h.restore().pending()
        assert Path(h.root, '.key').read_bytes() == key and h.choices == 1
    finally:
        h.service.anhalten()


def test_uncertain_consent_publication_quarantines_selected_ephemeral_choice(native, tmp_path):
    h = Harness(native, tmp_path)
    try:
        actual_write = h.store._write
        def write(directory, name, value):
            actual_write(directory, name, value)
            if name == '.transaction' and value == b'clean\n':
                raise OSError('Controlled post-clean-marker uncertainty')
        h.store._write = write
        with pytest.raises(OSError): h.configure()
        assert Path(h.root, '.transaction').read_bytes() == b'pending\n'
        with pytest.raises(PermissionError): h.choice.require_current()
        with pytest.raises(PermissionError): h.new_store().has_desired_consent()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['success', 'known-later-save', 'missing-native-data', 'unknown-primary', 'memory-impostor',
    'revoked', 'reconfigured', 'missing-journal-key', 'changed-result', 'changed-receipt', 'legacy-no-seal',
    'wrong-book-seal', 'removed-contact', 'changed-uid', 'expired-origin', 'copied-origin',
    'boolean-result-version', 'float-result-revision', 'revoke-after-reauthorize', 'unknown-primary-after-reauthorize', 'other-authenticated-peer',
    'status-prepared', 'status-settled', 'status-wrong-desktop', 'status-unknown-phase', 'status-extra-field',
    'status-bool-version', 'status-float-revision', 'status-write-failure', 'status-post-write-failure',
    'status-revoked', 'status-wrong-request-sha', 'status-wrong-basis', 'status-wrong-target', 'status-expired-origin'])
def test_existing_saved_ack_recovers_only_with_private_primary_context_and_fresh_exact_result(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); h.pending = h.choice.pending(); request = h.pending.request()
        result = {'art': 'kontakt_original_ergebnis', 'fassung': 1,
            **{name: request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')},
            'request_sha256': hashlib.sha256(_frame_bytes(request)).hexdigest(),
            'receipt_id': '22222222-2222-4222-8222-222222222222', 'native_revision': 2, 'next_basis': 'd' * 64}
        h.send(result)
        with h.probe._daten_sperre: invocation = h.pending.prepare_commit()
        assert h.save(monkeypatch, invocation=invocation)['ok']
        journal_key = [b'J' * 32]
        intents = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: journal_key[0])
        fresh = intents.seal_after_save(h.pending); expected = fresh.body()
        path, = (tmp_path / 'outcomes').glob('*.bin')
        original = path.read_bytes()
        old_origin = h.results[-1][1:]
        if mode == 'known-later-save':
            edited = copy.deepcopy(h.probe._aktuelle_daten); edited['kontakte'][0]['notiz'] = 'Later known local edit'
            assert h.save(monkeypatch, edited)['ok']
        h.restart(); h.pending = None
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        with pytest.raises(PermissionError): fresh.body()
        if mode == 'missing-native-data': h.store._native_data = None
        if mode == 'unknown-primary':
            edited = copy.deepcopy(h.probe._aktuelle_daten); edited['kontakte'][0]['notiz'] = 'Unknown primary replacement'
            native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(edited)))
            h.probe._aktuelle_daten = edited
        if mode == 'memory-impostor': h.probe._aktuelle_daten['kontakte'][0]['notiz'] = 'Memory is not the authenticated primary'
        if mode == 'revoked': h.store.revoke()
        if mode == 'reconfigured':
            assert h.save(monkeypatch)['ok']
            chosen = h.restore(); h.store.configure([chosen])
        if mode in ('removed-contact', 'changed-uid'):
            edited = copy.deepcopy(h.probe._aktuelle_daten)
            if mode == 'removed-contact': edited['kontakte'] = []
            else: edited['kontakte'][0]['uid'] = 'Different canonical identity'
            assert h.save(monkeypatch, edited)['ok']
        if mode in ('legacy-no-seal', 'wrong-book-seal'):
            record = intents.load_held(path.stem)
            if mode == 'legacy-no-seal': record.pop('choice_seal')
            else: record['choice_seal']['book'] = '0' * 64
            nonce = b'R' * 12
            path.write_bytes(b'\x01' + nonce + intents._cipher().encrypt(nonce, _frame_bytes(record),
                intents._DOMAIN + path.stem.encode('ascii')))
            original = path.read_bytes()
        body = dict(result)
        if mode.startswith('status-'):
            body.update(art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=expected['desktop_sha256'])
            if mode == 'status-prepared': body['phase'] = 'prepared'
            if mode == 'status-wrong-desktop': body['desktop_sha256'] = '0' * 64
            if mode == 'status-unknown-phase': body['phase'] = 'complete'
            if mode == 'status-extra-field': body['saved'] = True
            if mode == 'status-bool-version': body['fassung'] = True
            if mode == 'status-float-revision': body['native_revision'] = 2.0
            if mode == 'status-wrong-request-sha': body['request_sha256'] = '0' * 64
            if mode == 'status-wrong-basis': body['before_basis'] = '0' * 64
            if mode == 'status-wrong-target': body['target_sha256'] = '0' * 64
            if mode == 'status-revoked': h.store.revoke()
        if mode == 'changed-result': body['target_sha256'] = '0' * 64
        if mode == 'changed-receipt': body['receipt_id'] = '33333333-3333-4333-8333-333333333333'
        if mode == 'boolean-result-version': body['fassung'] = True
        if mode == 'float-result-revision': body['native_revision'] = 2.0
        if mode == 'other-authenticated-peer':
            h.sender = native.baum_schluessel_erzeugen('Other synthetic authenticated sender')
            peer = native.baum_partner_aufnehmen(h.receiver, h.sender['name'], h.sender['kennung'], h.sender['oeffentlich'], '127.0.0.1')
            peer['bestaetigt'] = True
            h.store._capture_primary = lambda: pytest.fail('Wrong peer reached native primary inspection')
        h.send(body); body, origin, transport = h.results.pop()
        if mode == 'status-expired-origin': h.service.anhalten()
        if mode == 'missing-journal-key': journal_key[0] = None
        if mode == 'expired-origin': origin, transport = old_origin
        if mode == 'copied-origin': origin = body
        before_book = Path(native.daten_datei()).read_bytes()
        if mode in ('missing-native-data', 'unknown-primary', 'memory-impostor', 'revoked', 'reconfigured',
                    'missing-journal-key', 'legacy-no-seal', 'wrong-book-seal', 'removed-contact', 'changed-uid'):
            with pytest.raises(PermissionError): intents.readonly_query(path.stem, h.store)
        if mode in ('status-prepared', 'status-settled', 'status-write-failure', 'status-post-write-failure'):
            restored = intents.reauthorize(path.stem, h.store, body, origin, transport)
            assert restored.body() == expected
            assert restored.terminal_confirmed() == (mode != 'status-prepared')
            if mode == 'status-prepared':
                with pytest.raises(PermissionError): intents.confirm_terminal(restored)
            else:
                actual_write = intents._write
                def write(directory, name, value):
                    if mode == 'status-write-failure': raise OSError('Controlled before terminal marker write')
                    actual_write(directory, name, value)
                    if mode == 'status-post-write-failure': raise OSError('Controlled after terminal marker write')
                if mode != 'status-settled':
                    intents._write = write
                    with pytest.raises(OSError): intents.confirm_terminal(restored)
                    intents._write = actual_write
                    if mode == 'status-write-failure':
                        assert path.read_bytes() == original
                        assert restored.body() == expected
                    else:
                        with pytest.raises(PermissionError): restored.body()
                    restored = intents.reauthorize(path.stem, h.store, body, origin, transport)
                complete = intents.confirm_terminal(restored)
                assert complete['native_terminal_sha256'] == hashlib.sha256(_frame_bytes(body)).hexdigest()
                with pytest.raises(PermissionError): restored.body()
                if mode == 'status-post-write-failure':
                    assert intents.confirm_terminal(restored) == complete
                else:
                    with pytest.raises(PermissionError): intents.confirm_terminal(restored)
                original = path.read_bytes()
                assert b'native_terminal_sha256' not in original
                again = intents.reauthorize(path.stem, h.store, body, origin, transport)
                assert again.terminal_confirmed()
                assert intents.confirm_terminal(again) == complete
                with pytest.raises(PermissionError): again.body()
                from magnolie_contact_notes_return import NativeNotesSavedAckIntent
                for fake in (body, NativeNotesSavedAckIntent(body)):
                    with pytest.raises(PermissionError): intents.confirm_terminal(fake)
                with pytest.raises(PermissionError): NativeNotesSavedAckIntent(body).terminal_confirmed()
            assert h.probe._kontakt_quellen_buchaufnahme() is None
        elif mode in ('success', 'known-later-save', 'revoke-after-reauthorize', 'unknown-primary-after-reauthorize'):
            restored = intents.reauthorize(path.stem, h.store, body, origin, transport)
            assert restored.body() == expected
            assert h.probe._kontakt_quellen_buchaufnahme() is None, 'Primary read was laundered into a saved-writer witness'
            assert h.choices == 1
            if mode == 'revoke-after-reauthorize': h.store.revoke()
            if mode == 'unknown-primary-after-reauthorize':
                edited = copy.deepcopy(h.probe._aktuelle_daten); edited['kontakte'][0]['notiz'] = 'Late unknown primary'
                native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(edited)))
                h.probe._aktuelle_daten = edited
                before_book = Path(native.daten_datei()).read_bytes()
            if mode in ('revoke-after-reauthorize', 'unknown-primary-after-reauthorize'):
                with pytest.raises(PermissionError): restored.body()
            h.service.anhalten()
            with pytest.raises(PermissionError): restored.body()
        else:
            with pytest.raises(PermissionError): intents.reauthorize(path.stem, h.store, body, origin, transport)
        assert path.read_bytes() == original and Path(native.daten_datei()).read_bytes() == before_book
    finally:
        h.service.anhalten()
