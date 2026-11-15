"""Contact-only native witness + actual Linux encrypted/atomic save worker.

No provider IO, GTK, installation or document-issued source permissions.
"""
import copy
import hashlib
import json
from pathlib import Path
import queue
import threading
import sys
from types import MethodType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_native_book_json import book_hash
from magnolie_personal_actor_store import NativeBookOwnerScope
from test_startup_read_failure import native


def data():
    return {'syncEpoch': 'native-contact-book-epoch', 'kontakte': [
        {'id': 'local', 'uid': 'canonical-person', 'notiz': 'Grüße synthetic', 'sync': True}],
        'notizen': [{'id': 'keep', 'text': 'Other domains untouched'}],
        'customOrganizer': {'drawing': {'x': 1.25, 'y': -0.5}},
        'saved': True, 'sourceAdmissions': ['document-claims-do-not-grant']}


@pytest.mark.parametrize('mode', ['initial', 'success', 'changed', 'before-write', 'locked',
    'unavailable', 'other-binding', 'later-save', 'ready-again', 'bad-payload', 'nonfinite', 'deep-memory', 'deep-payload'])
def test_independent_contact_book_requires_native_commit_not_document_claims(mode):
    current = data()
    text = json.dumps(current, ensure_ascii=False, indent=2)
    book = NativeContactSourceBook()
    book.set_ready(True)
    assert book.capture('native-binding', True, current) is None
    if mode == 'initial':
        return
    saved = book.record_saved('native-binding', True, text)
    snapshot = book.capture('native-binding', True, current)
    assert snapshot.saved_book == saved and snapshot.book() == current
    assert snapshot.saved_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert snapshot.content_sha256 == book_hash(current)
    assert snapshot.saved_sha256 != snapshot.content_sha256, 'Raw SaveACK was confused with normalized content'
    if mode == 'success':
        return
    binding, available = 'native-binding', True
    if mode == 'changed':
        current['kontakte'][0]['notiz'] = 'Unsaved native memory change'
    elif mode == 'before-write':
        book.invalidate_saved()
    elif mode in ('locked', 'ready-again'):
        book.set_ready(False)
        if mode == 'ready-again':
            book.set_ready(True)
    elif mode == 'unavailable':
        available = False
    elif mode == 'other-binding':
        binding = 'different-native-book'
    elif mode == 'later-save':
        book.invalidate_saved()
        assert book.capture(binding, available, current) is None
        later = book.record_saved(binding, available, text)
        assert later['book_source'] == saved['book_source'] and later['sequence'] == saved['sequence'] + 1
        assert book.capture(binding, available, current).saved_book == later
        return
    elif mode == 'deep-memory':
        nested = current
        for _ in range(1100):
            nested['child'] = {}
            nested = nested['child']
    elif mode in ('bad-payload', 'nonfinite', 'deep-payload'):
        invalid = '{' if mode == 'bad-payload' else '{"x":NaN}' if mode == 'nonfinite' else '[' * 1100 + '0' + ']' * 1100
        assert book.record_saved(binding, available, invalid) is None
    assert book.capture(binding, available, current) is None
    if mode in ('ready-again', 'other-binding', 'unavailable'):
        later = book.record_saved(binding, True, text)
        assert later['book_source'] != saved['book_source'] and later['sequence'] == 1


@pytest.mark.parametrize('mode', ['plain', 'encrypted', 'fractional', 'failure-before-write',
    'failure-after-unknown', 'repair-after-rename', 'reminder-repair', 'stale-epoch', 'historical-impostor'])
def test_actual_worker_records_contact_witness_only_after_unrepaired_native_commit(native, monkeypatch, mode):
    before = data()
    proposed = copy.deepcopy(before)
    proposed['kontakte'][0]['notiz'] = 'Confirmed native contact change'
    if mode == 'fractional':
        proposed['customOrganizer']['drawing']['x'] = 3.125
    if mode == 'stale-epoch':
        proposed['syncEpoch'] = 'stale-request-epoch'
    before_text = json.dumps(before, ensure_ascii=False)
    text = json.dumps(proposed, ensure_ascii=False, indent=2)
    password = '' if mode == 'plain' else 'synthetic-only-contact-worker'
    if password:
        initial, dek, dek_id, wrapper = native.daten_huelle_anlegen(before_text, password)
    else:
        initial, dek, dek_id, wrapper = before_text, None, None, None
    native.speichere_text(initial)
    path = Path(native.daten_datei())
    original_bytes = path.read_bytes()
    book = NativeContactSourceBook()
    book.set_ready(True)
    replies, snapshots = [], []
    phone_owner = NativeBookOwnerScope()
    phone_owner.set_ready(True)
    probe = SimpleNamespace(_kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id,
        _daten_umschlag=wrapper, _aktuelle_daten=before, _daten_sperre=threading.RLock(),
        _speicher_auftraege=queue.Queue(), _gesperrt=False, _ladefehler='',
        _operation_laeuft=False, _sync_laeuft=False, _wirklich_beenden=False,
        _kontakt_quellen_buch=book, _notes_actor_book_owner=phone_owner,
        _journal_snapshot=lambda reason: snapshots.append(reason),
        antwort=lambda callback, value: replies.append((callback, value)))
    for name in ('_vielleicht_verschluesseln', '_kontakt_quellen_buchbindung',
                 '_kontakt_quellen_buchnachweis', '_kontakt_quellen_buchaufnahme',
                 '_telefon_actor_buchbindung', '_telefon_actor_buchnachweis'):
        setattr(probe, name, MethodType(getattr(native.Fenster, name), probe))
    original_state = book.record_saved(*probe._kontakt_quellen_buchbindung(), before_text)
    phone_state = phone_owner.record_saved(*probe._telefon_actor_buchbindung(), hashlib.sha256(before_text.encode()).hexdigest())
    probe._notes_actor_saved_data = (phone_state['book_source'], phone_state['sequence'], book_hash(before))
    assert phone_state['book_source'] != original_state['book_source'], 'Contact source reused phone actor ownership'
    assert probe._kontakt_quellen_buchaufnahme().saved_book == original_state
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: mode != 'reminder-repair')
    actual_write = native.speichere_text
    writes = []

    def checked_write(payload):
        # Executed INSIDE actual production worker/native write, not a test
        # wrapper pretending that a submitted JSON or file replacement is ACK.
        assert probe._kontakt_quellen_buchaufnahme() is None, 'Old witness survived a pending native write'
        writes.append(payload)
        if mode == 'failure-before-write':
            raise OSError('Controlled contact write failure')
        actual_write(payload)
        if mode in ('failure-after-unknown', 'repair-after-rename'):
            raise OSError('Controlled post-rename failure')

    monkeypatch.setattr(native, 'speichere_text', checked_write)
    if mode == 'failure-after-unknown':
        monkeypatch.setattr(native, '_erinnerungsprofil_lesen', lambda: (_ for _ in ()).throw(OSError('Controlled unknown readback')))
    probe._speicher_auftraege.put((1, text, None, {}) if mode == 'historical-impostor' else (1, text, None))
    probe._speicher_auftraege.put(None)
    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(probe,), daemon=True)
    worker.start()
    worker.join(timeout=15)
    assert not worker.is_alive(), 'Bounded actual writer did not finish'
    response, = [value for callback, value in replies if callback == 'App.gespeichert']
    current = probe._kontakt_quellen_buchaufnahme()
    if mode in ('plain', 'encrypted', 'fractional'):
        assert response['ok'] is True and response['committed'] is True and response['repairPending'] is False
        assert response['standSha256'] == hashlib.sha256(text.encode()).hexdigest()
        assert current.saved_sha256 == response['standSha256'] and current.sequence == original_state['sequence'] + 1
        assert current.book() == proposed and snapshots == ['pre-change'] and len(writes) == 1
    elif mode in ('repair-after-rename', 'reminder-repair'):
        # Preserve the EXISTING general writer ACK/repair semantics, but do not
        # release contact provider writes from that repair-pending state.
        assert response['ok'] is True and response['committed'] is True and response['repairPending'] is True
        assert current is None and len(writes) == 1
    elif mode in ('stale-epoch', 'historical-impostor'):
        assert response['ok'] is False and not writes and not snapshots and path.read_bytes() == original_bytes
        assert current.saved_book == original_state
    else:
        assert response['ok'] is False and current is None and len(writes) == 1
    if writes and mode != 'failure-before-write':
        stored = native.daten_entschluesseln(path.read_text(), password) if password else path.read_text()
        assert stored == text
    if mode in ('plain', 'encrypted', 'fractional', 'repair-after-rename', 'reminder-repair'):
        phone_after = probe._telefon_actor_buchnachweis()
        assert phone_after['book_source'] == phone_state['book_source'] and phone_after['sequence'] == phone_state['sequence'] + 1
        assert phone_after['sha256'] == response['standSha256'], 'Existing phone writer witness/repair policy was altered'
    assert not any(callback.startswith('App.sync') for callback, _ in replies), 'Saved-book observation started source synchronization'


def test_contact_readiness_and_phone_actor_policy_are_independent(native):
    book = NativeContactSourceBook()
    probe = SimpleNamespace(_kontakt_quellen_buch=book, _aktuelle_daten=data(),
        _gesperrt=False, _operation_laeuft=False, _sync_laeuft=False, _wirklich_beenden=False,
        _ladefehler='', _daten_dek_kennung=None, _daten_sperre=threading.RLock())
    native._organizer_gui_bereitschaft(probe, True)
    binding = native.Fenster._kontakt_quellen_buchbindung(probe)
    book.record_saved(*binding, json.dumps(probe._aktuelle_daten))
    assert book.capture(*binding, probe._aktuelle_daten) is not None
    probe._sync_laeuft = True
    assert native.Fenster._telefon_actor_buchbindung(probe)[1] is False, 'Phone actor sync fence was weakened'
    assert native.Fenster._kontakt_quellen_buchbindung(probe)[1] is False
    native._organizer_gui_bereitschaft(probe, False)
    native._organizer_gui_bereitschaft(probe, True)
    probe._sync_laeuft = False
    assert book.capture(*native.Fenster._kontakt_quellen_buchbindung(probe), probe._aktuelle_daten) is None


def test_contact_saved_book_module_is_in_existing_linux_source_manifests():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
                 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_source_book.py' in (root / name).read_text()
    json.loads((root / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())
