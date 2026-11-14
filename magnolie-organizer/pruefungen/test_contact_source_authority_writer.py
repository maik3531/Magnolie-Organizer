"""Actual encrypted serial writer with injected native private consent store.

No production setup/startup hydration or frontend persistence is claimed here.
"""
import copy
import json
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace

import pytest

from test_contact_source_saved_book import data, native
from test_contact_source_dav_factory import account, Source
from magnolie_contact_source_authority import NativeContactSourceApprovalStore
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_contact_source_dav import NativeDavApprovalScope
from magnolie_nextcloud import source_id


@pytest.mark.parametrize('mode', ['success', 'same-content', 'write-before', 'write-after-unknown',
    'write-after-repair', 'reminder-repair', 'intent-failed', 'confirmation-failed',
    'restart-first-save', 'restart-pending-new', 'restart-pending-old', 'restart-unknown-primary'])
def test_actual_encrypted_writer_tracks_only_confirmed_unrepaired_approved_book(native, tmp_path, monkeypatch, mode):
    before = data(); before_text = json.dumps(before, ensure_ascii=False)
    proposed = copy.deepcopy(before)
    if mode != 'same-content': proposed['kontakte'][0]['notiz'] = 'Durable synthetic writer change'
    text = json.dumps(proposed, ensure_ascii=False, indent=2)
    password = 'synthetic-only-durable-writer'
    envelope, dek, dek_id, wrapper = native.daten_huelle_anlegen(before_text, password)
    native.speichere_text(envelope)
    book = NativeContactSourceBook(); book.set_ready(True)
    replies = []
    host = SimpleNamespace(_kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id,
        _daten_umschlag=wrapper, _aktuelle_daten=before, _daten_sperre=threading.RLock(),
        _speicher_auftraege=queue.Queue(), _gesperrt=False, _ladefehler='',
        _operation_laeuft=False, _sync_laeuft=False, _wirklich_beenden=False,
        _kontakt_quellen_buch=book, _journal_snapshot=lambda reason: None,
        antwort=lambda callback, value: replies.append((callback, value)))
    for name in ('_vielleicht_verschluesseln', '_kontakt_quellen_buchbindung',
                 '_kontakt_quellen_buchnachweis', '_kontakt_quellen_buchaufnahme', '_kontakt_quellen_hauptdatei_aufnahme'):
        setattr(host, name, MethodType(getattr(native.Fenster, name), host))
    book.record_saved(*host._kontakt_quellen_buchbindung(), before_text)
    accounts = account(tmp_path)
    scope = NativeDavApprovalScope(host._kontakt_quellen_buchnachweis, accounts)
    uid = source_id('addressbook', Source.href, 'generic-dav')
    scope.configure([{'uid': uid, 'href': Source.href, 'art': 'addressbook', 'canUpdate': True}],
                    lambda choices, selected: [choices[0]['uid']])
    store = NativeContactSourceApprovalStore(str(tmp_path / 'private-consent'), accounts,
        host._kontakt_quellen_buchaufnahme, lambda: str(Path(native.daten_datei()).resolve()),
        capture_primary=host._kontakt_quellen_hauptdatei_aufnahme)
    witness = store.approve(host._kontakt_quellen_buchaufnahme(), scope.capture())
    host._kontakt_quellen_dauerfreigabe = store
    if mode in ('restart-pending-new', 'restart-pending-old'):
        store.prepare_save(host._kontakt_quellen_buchaufnahme(), text)
        if mode == 'restart-pending-new':
            native.speichere_text(host._vielleicht_verschluesseln(text))
            host._aktuelle_daten = proposed
    if mode == 'restart-unknown-primary':
        native.speichere_text(host._vielleicht_verschluesseln(json.dumps(dict(before, unknownEdit=True))))
    if mode.startswith('restart-'):
        book.invalidate_saved()
        assert host._kontakt_quellen_buchaufnahme() is None
    def forbidden(*args, **kwargs): pytest.fail('Actual writer requested keyring access')
    actual_write = native.speichere_text
    def write(payload):
        assert host._kontakt_quellen_buchaufnahme() is None
        with pytest.raises(PermissionError): store.load_current()
        if mode == 'write-before': raise OSError('Controlled pre-write failure')
        actual_write(payload)
        if mode in ('write-after-unknown', 'write-after-repair'): raise OSError('Controlled post-write failure')
    monkeypatch.setattr(native, 'speichere_text', write)
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **kwargs: mode != 'reminder-repair')
    if mode == 'write-after-unknown':
        monkeypatch.setattr(native, '_erinnerungsprofil_lesen', lambda: (_ for _ in ()).throw(OSError('Controlled unreadable outcome')))
    if mode in ('intent-failed', 'restart-unknown-primary'):
        # Failure before durable intent exists: book save must still succeed.
        if mode == 'intent-failed':
            monkeypatch.setattr(store, 'prepare_save', lambda *args: (_ for _ in ()).throw(OSError('Controlled intent failure')))
        def ordinary_write(payload):
            assert host._kontakt_quellen_buchaufnahme() is None
            actual_write(payload)
        monkeypatch.setattr(native, 'speichere_text', ordinary_write)
    if mode == 'confirmation-failed':
        monkeypatch.setattr(store, 'confirm_save', lambda *args: (_ for _ in ()).throw(OSError('Controlled confirmation failure')))
    with monkeypatch.context() as quiet:
        quiet.setattr(accounts, 'read_snapshot', forbidden)
        host._speicher_auftraege.put((1, text, None)); host._speicher_auftraege.put(None)
        worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(host,), daemon=True)
        worker.start(); worker.join(timeout=15); assert not worker.is_alive()
    reply = [value for callback, value in replies if callback == 'App.gespeichert'][-1]
    pending = tmp_path / 'private-consent/.book-intent.json'
    if mode in ('success', 'same-content', 'restart-first-save', 'restart-pending-new', 'restart-pending-old'):
        assert reply['ok'] and reply['committed'] and not reply['repairPending']
        assert not pending.exists() and host._kontakt_quellen_dauerfehler is None
        restored = store.load_current()
        assert restored.generation == witness.generation and restored.sources == witness.sources
        assert restored.snapshot.book() == proposed
    else:
        assert host._kontakt_quellen_dauerfehler
        if mode in ('write-before', 'write-after-unknown'): assert reply['ok'] is False
        else:
            assert reply['ok'] and reply['committed']
            assert reply['repairPending'] is (mode in ('write-after-repair', 'reminder-repair'))
        if mode in ('intent-failed', 'restart-unknown-primary'): assert not pending.exists() and store.load_current() is None
        else:
            assert pending.exists()
            with pytest.raises((PermissionError, ValueError)): store.load_current()
    if mode not in ('write-before',):
        assert json.loads(native.entschluesseln(Path(native.daten_datei()).read_text(), password)) == proposed
    assert not any('freigabe' in key.lower() for key in reply), 'Sidecar success became a renderer permission'
