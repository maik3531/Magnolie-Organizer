"""Explicit known-choice/read-only existing-key composition, owned fixtures only."""
import copy
import json
from pathlib import Path
from types import MethodType
import threading

import pytest
from cryptography.exceptions import InvalidTag

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_session import NativeNotesNativeSession
from test_contact_notes_controller import Runtime, admit_window_offer


def phone(root):
    root.mkdir(mode=0o700, parents=True)
    key = root / 'storage.key'; key.write_bytes(b'S' * 32); key.chmod(0o600)
    return key


@pytest.mark.parametrize('mode', ['attached', 'no-choice', 'revoked', 'key-missing', 'unsafe-key', 'wrong-binding',
    'unknown-primary', 'unsaved-native-edit', 'pending', 'occupied', 'concurrent-revoke', 'stopped-before', 'key-loss',
    'key-replacement', 'stop-idempotent', 'foreign-slot-stop', 'stopped-controller'])
def test_session_admission_needs_real_private_selection_and_existing_independent_key(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    root = tmp_path / 'owned-native-profile'
    slots = {}
    session = None
    try:
        if mode != 'no-choice': h.configure()
        key = phone(root / 'telefon') if mode not in ('no-choice', 'key-missing') else None
        if mode == 'revoked': h.store.revoke()
        if mode == 'unsafe-key': key.chmod(0o640)
        if mode == 'unknown-primary':
            edit = copy.deepcopy(h.probe._aktuelle_daten); edit['unknown'] = 'do not adopt'
            native.speichere_text(h.probe._vielleicht_verschluesseln(json.dumps(edit)))
        if mode == 'unsaved-native-edit': h.probe._aktuelle_daten['later-edit'] = 'preserve'
        if mode == 'pending': Path(h.root, '.transaction').write_bytes(b'pending\n')
        foreign = object()
        if mode == 'occupied': slots['owner'] = foreign
        def attach(owner, controller, ui):
            assert h.probe._daten_sperre._is_owned()
            if slots: return False
            slots.update(owner=owner, controller=controller, ui=ui)
            return True
        def detach(owner, controller, ui):
            assert h.probe._daten_sperre._is_owned()
            if slots.get('owner') is owner: slots.clear()
        session = NativeNotesNativeSession(str(root), str(Path(native.daten_datei()).resolve()) + ('.foreign' if mode == 'wrong-binding' else ''),
            h.store, lambda: json.dumps(h.probe._aktuelle_daten, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
            lambda: h.probe._daten_sperre, attach, detach)
        key_reads = []
        read = session._key.read_existing
        def existing():
            key_reads.append(True)
            value = read()
            if mode == 'concurrent-revoke': h.store.revoke()
            return value
        monkeypatch.setattr(session._key, 'read_existing', existing)
        if mode == 'stopped-before': session.stop()
        admitted = session.try_attach_known()
        if mode in ('no-choice', 'revoked'):
            assert admitted == 'no-choice' and key_reads == []
        elif mode == 'key-missing': assert admitted == 'key-missing'
        elif mode == 'stopped-before': assert admitted == 'stopped' and key_reads == []
        elif mode in ('unsafe-key', 'wrong-binding', 'unknown-primary', 'unsaved-native-edit', 'pending', 'occupied', 'concurrent-revoke'):
            assert admitted == 'held' and not session.is_active
            if mode in ('wrong-binding', 'unknown-primary', 'unsaved-native-edit', 'pending'): assert key_reads == []
        else:
            assert admitted == 'attached' and session.is_active
            assert session.try_attach_known() == 'attached' and slots['owner'] is session
            if mode in ('key-loss', 'key-replacement'):
                before = session._existing_key()
                if mode == 'key-loss': key.unlink()
                else: key.write_bytes(b'K' * 32)
                after = session.controller._outcomes._existing_key()
                assert after is None if mode == 'key-loss' else after != before
            if mode == 'foreign-slot-stop': slots['owner'] = foreign
            if mode == 'stopped-controller':
                session.controller.stop()
                assert not session.is_active and session.try_attach_known() == 'stopped'
            session.stop(); session.stop()
            assert not session.is_active and session._existing_key() is None and session.try_attach_known() == 'stopped'
        if mode in ('occupied', 'foreign-slot-stop'): assert slots['owner'] is foreign
        else: assert slots == {}
        assert not (root / 'notes-original-outcomes').exists()
        assert not (root / 'notes-original-outcomes-pending').exists()
        if mode in ('no-choice', 'key-missing'): assert not root.exists()
        elif key is not None:
            assert {p.name for p in (root / 'telefon').iterdir()} <= {'storage.key'}
    finally:
        if session is not None: session.stop()
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['attached', 'locked', 'closing', 'foreign-controller'])
def test_actual_window_explicit_session_entry_never_starts_phone_or_replaces_foreign_work(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure()
        root = Path(native.daten_verzeichnis()).resolve()
        phone(root / 'telefon')
        probe = h.probe
        probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, probe)
        foreign = object()
        if mode == 'locked': probe._gesperrt = True
        if mode == 'closing': probe._wirklich_beenden = True
        if mode == 'foreign-controller': probe._notes_original_controller = foreign
        monkeypatch.setattr(native, 'PhoneService', lambda *_args, **_kwargs: pytest.fail('Session constructed a phone store/service'))
        admitted = native.Fenster._notes_original_native_resume_known(probe)
        if mode == 'attached':
            assert admitted == 'attached' and probe._notes_original_session.is_active
            controller, ui = probe._notes_original_controller, probe._notes_original_ui
            assert ui.controller is controller
            assert native.Fenster._notes_original_native_resume_known(probe) == 'attached'
            native.Fenster._notes_original_native_stop_session(probe)
            assert probe._notes_original_controller is None and probe._notes_original_ui is None and probe._notes_original_session is None
        else:
            assert admitted == 'held'
            assert getattr(probe, '_notes_original_session', None) is None
        if mode == 'foreign-controller': assert probe._notes_original_controller is foreign
        assert not (root / 'telefon' / 'phone.db').exists()
        assert not (root / 'notes-original-outcomes').exists()
        assert not (root / 'notes-original-outcomes-pending').exists()
    finally:
        h.service.anhalten()


def test_session_module_is_shipped_without_registering_startup_or_renderer_entry():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
            'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_notes_session.py' in (root / name).read_text()
    source = (root / 'bin/magnolie-organizer').read_text()
    assert source.count('_notes_original_native_resume_known(') == 1


@pytest.mark.parametrize('change', ['stop', 'loss', 'replacement', 'lock'])
def test_composed_session_real_fs1_numeric_writer_and_journal_do_not_keep_stale_key_authority(native, monkeypatch, tmp_path, change):
    h = Harness(native, tmp_path)
    try:
        h.configure(); root = Path(native.daten_verzeichnis()).resolve(); key = phone(root / 'telefon')
        probe = h.probe
        probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, probe)
        assert native.Fenster._notes_original_native_resume_known(probe) == 'attached'
        session = probe._notes_original_session; c = session.controller
        runtime = Runtime(h); runtime.controller = c; runtime.outcomes = c._outcomes
        runtime.protocol = c.begin_peer((h.sender['kennung'], h.sender['oeffentlich']), (h.receiver['kennung'], h.receiver['oeffentlich']))
        request = runtime.start().intent.request(); h.send(runtime.result(request))
        work = native.Fenster._notes_original_native_arbeit(probe)
        assert work.kind == 'save' and not probe._speicher_auftraege.qsize()
        admit_window_offer(h)
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
        probe._speicher_auftraege.put(None)
        writer = threading.Thread(target=native.Fenster._speicher_lauf, args=(probe,), daemon=True)
        writer.start(); writer.join(10)
        assert not writer.is_alive() and c.ready_acks()
        journal, = Path(c._outcomes.root).glob('*.bin'); history = journal.read_bytes()
        assert c._outcomes.readonly_query(journal.stem, h.store).request()
        saved_book = Path(native.daten_datei()).read_bytes()
        if change == 'loss': key.unlink()
        if change == 'replacement': key.write_bytes(b'K' * 32)
        if change == 'lock':
            probe._gesperrt = True
            assert native.Fenster._notes_original_native_resume_known(probe) == 'held'
        else:
            if change == 'stop': native.Fenster._notes_original_native_stop_session(probe)
        with pytest.raises((PermissionError, InvalidTag)): c._outcomes.readonly_query(journal.stem, h.store).request()
        assert journal.read_bytes() == history and Path(native.daten_datei()).read_bytes() == saved_book
        native.Fenster._notes_original_native_stop_session(probe)
        assert not session.is_active and not (root / 'telefon' / 'phone.db').exists()
        if change == 'loss': assert not key.exists()
    finally:
        h.service.anhalten()
