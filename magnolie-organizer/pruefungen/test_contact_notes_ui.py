"""#638 owned work leases, actual writer completion and lock-order boundaries."""
import json
from pathlib import Path
import threading

import pytest

from test_contact_notes_consent import Harness, native
from test_contact_notes_controller import Runtime
from magnolie_contact_notes_ui import NativeNotesUiSaveSession


@pytest.mark.parametrize('mode', ['complete', 'wrong-token', 'wrong-text', 'expire', 'cancel', 'foreign-cancel', 'session-stop',
    'controller-stop', 'revoke', 'native-save', 'double-claim', 'fake-witness', 'journal-failure', 'work-lock-held',
    'mixed-contact', 'mixed-tree', 'foreign-controller'])
def test_owned_numeric_ui_lane_keeps_native_writer_journal_and_physical_holds(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    blocker = None
    release = threading.Event()
    try:
        h.configure(); runtime = Runtime(h); c = runtime.controller
        request = runtime.start().intent.request()
        h.send(runtime.result(request))
        work = c.process_one()
        assert work.kind == 'save'
        h.probe._notes_original_controller = c
        h.probe._organizer_vertraut = lambda: True
        h.probe._darf_schreiben = lambda: True
        now = [0]
        session = NativeNotesUiSaveSession(c, lambda: json.dumps(h.probe._aktuelle_daten,
            ensure_ascii=False, sort_keys=True, separators=(',', ':')), clock=lambda: now[0])
        h.probe._notes_original_ui = session
        offer = session.publish(work)
        before = Path(native.daten_datei()).read_bytes()
        physical = dict(c._physical)
        if mode == 'wrong-token':
            with pytest.raises(PermissionError): session.claim('0' * 64, offer['text'])
        if mode == 'foreign-cancel': session.cancel('0' * 64)
        if mode == 'expire': now[0] = 8
        if mode == 'cancel': session.cancel(offer['token'])
        if mode == 'session-stop': session.stop()
        if mode == 'controller-stop': c.stop()
        if mode == 'revoke': h.store.revoke()
        if mode == 'native-save':
            data = json.loads(json.dumps(h.probe._aktuelle_daten)); data['later-edit'] = 'preserve'
            assert h.save(monkeypatch, data)['ok']
            before = Path(native.daten_datei()).read_bytes()
        command = {'cmd': 'speichern', 'id': 246, 'text': offer['text'], 'notesOriginalLauf': offer['token']}
        if mode == 'wrong-text': command['text'] += ' '
        if mode == 'mixed-contact': command['kontaktOriginalLauf'] = 'foreign'
        if mode == 'mixed-tree': command['baumSyncLauf'] = {}
        if mode == 'foreign-controller': h.probe._notes_original_controller = object()
        if mode == 'fake-witness':
            proof = session.claim(offer['token'], offer['text'])
            with pytest.raises(PermissionError):
                with h.probe._daten_sperre:
                    proof.complete({'ok': True, 'committed': True, 'repairPending': False, 'standSha256': 'f' * 64})
            proof.failed()
        else:
            native.Fenster.bei_nachricht(h.probe, json.dumps(command))
            if mode in ('wrong-text', 'expire', 'cancel', 'session-stop', 'controller-stop', 'native-save',
                    'mixed-contact', 'mixed-tree', 'foreign-controller'):
                assert h.probe._speicher_auftraege.qsize() == 0
                assert h.replies[-1][1]['ok'] is False
            else:
                assert h.probe._speicher_auftraege.qsize() == 1
                if mode == 'double-claim':
                    with pytest.raises(PermissionError): session.claim(offer['token'], offer['text'])
                if mode == 'journal-failure':
                    monkeypatch.setattr(c._outcomes, 'seal_after_save', lambda _: (_ for _ in ()).throw(OSError('owned synthetic journal fault')))
                if mode == 'work-lock-held':
                    acquired = threading.Event()
                    def block_work():
                        with c._work:
                            acquired.set(); release.wait(15)
                    blocker = threading.Thread(target=block_work)
                    blocker.start(); assert acquired.wait(2)
                monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
                h.probe._speicher_auftraege.put(None)
                writer = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,), daemon=True)
                writer.start(); writer.join(5)
                assert not writer.is_alive(), 'Writer took controller._work while holding the book gate'
                acknowledgment = h.replies[-1][1]
                assert acknowledgment['id'] == 246
                if mode == 'revoke':
                    assert acknowledgment['ok'] is False
                else:
                    assert acknowledgment['ok'] is True
                    assert 'notesOriginalBasis' in h.probe._aktuelle_daten['kontakte'][0]
                    if mode == 'journal-failure':
                        assert h.probe._notes_original_work_error == 'notes_ui_save_ack_held'
                        assert not c.ready_acks()
                    else:
                        assert c.ready_acks() and len(list((tmp_path / 'outcomes').glob('*.bin'))) == 1
                        return
        assert dict(c._physical) == physical, 'Rejected UI lease released a physical request reservation'
        assert not list((tmp_path / 'outcomes').glob('*.bin'))
        if mode != 'journal-failure': assert Path(native.daten_datei()).read_bytes() == before
    finally:
        release.set()
        if blocker is not None: blocker.join(3)
        h.service.anhalten()


def test_native_ui_helper_is_shipped_without_automatic_session_activation():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
            'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_notes_ui.py' in (root / name).read_text()
    json.loads((root / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())


@pytest.mark.parametrize('mode', ['lost-handoff', 'locked', 'replaced-controller', 'invalid-native-model'])
def test_existing_worker_tick_expires_or_stops_its_owned_ui_lane_without_new_timer(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h); c = runtime.controller
        request = runtime.start().intent.request()
        h.send(runtime.result(request))
        work = c.process_one()
        h.probe._notes_original_controller = c
        now = [0]
        session = NativeNotesUiSaveSession(c, lambda: None if mode == 'invalid-native-model' else
            json.dumps(h.probe._aktuelle_daten), clock=lambda: now[0])
        h.probe._notes_original_ui = session
        if mode == 'invalid-native-model':
            with pytest.raises(PermissionError): session.publish(work)
        else:
            session.publish(work)
            if mode == 'lost-handoff': now[0] = 8
            if mode == 'locked': h.probe._gesperrt = True
            if mode == 'replaced-controller': h.probe._notes_original_controller = None
            native.Fenster._notes_original_native_arbeit(h.probe)
            assert session._pending is None
        assert not c._book_save_busy()
        assert c._physical and not h.probe._speicher_auftraege.qsize()
        assert not list((tmp_path / 'outcomes').glob('*.bin'))
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('kind', ['none-intent', 'copied-work', 'foreign-request'])
def test_ui_publish_cannot_invent_a_native_writer_or_owner(native, tmp_path, kind):
    from magnolie_contact_notes_controller import NativeNotesWork
    h = Harness(native, tmp_path)
    try:
        h.configure(); runtime = Runtime(h)
        request = runtime.start().intent.request()
        h.send(runtime.result(request)); work = runtime.controller.process_one()
        session = NativeNotesUiSaveSession(runtime.controller, lambda: json.dumps(h.probe._aktuelle_daten))
        fake = NativeNotesWork('save', None if kind == 'none-intent' else work.intent,
            'foreign-request' if kind == 'foreign-request' else work.request_id)
        if kind == 'copied-work': fake = {'kind': work.kind, 'intent': work.intent, 'request_id': work.request_id}
        with pytest.raises(PermissionError): session.publish(fake)
        assert session._pending is None and runtime.controller._physical
        assert not list((tmp_path / 'outcomes').glob('*.bin'))
        session.publish(work)  # Invalid input did not steal the genuine lane.
        session.stop()
    finally:
        h.service.anhalten()
