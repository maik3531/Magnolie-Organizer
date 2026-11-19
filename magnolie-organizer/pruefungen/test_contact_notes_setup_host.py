"""#640 actual native host/preparation/FS1/worker/UI ownership, synthetic only."""
import copy
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from types import MethodType, SimpleNamespace

import pytest

from test_contact_notes_consent import Harness, native
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_contact_notes_setup_run import NativeNotesSetupHost


@pytest.fixture
def host_case(native, monkeypatch, tmp_path):
    h = Harness(native, tmp_path)
    state = SimpleNamespace(h=h, native=native, posts=queue.Queue(), timers={}, notices=[], choices=[], contacts=[], peers=[],
        calls=[], sessions=[], host=None, mode='complete', arrived=threading.Event(), release=threading.Event(), destroyed=[])
    sequence = [0]
    def schedule(kind, callback):
        sequence[0] += 1; state.timers[sequence[0]] = kind, callback; return sequence[0]
    monkeypatch.setattr(native.GLib, 'timeout_add', lambda ms, cb: schedule(ms, cb), raising=False)
    monkeypatch.setattr(native.GLib, 'timeout_add_seconds', lambda seconds, cb: schedule('prepare', cb), raising=False)
    def remove(identifier): state.timers.pop(identifier, None)
    monkeypatch.setattr(native.GLib, 'source_remove', remove, raising=False)
    monkeypatch.setattr(native.GLib, 'idle_add', lambda cb: state.posts.put(cb) or 1, raising=False)
    monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', lambda: state.mode != 'offline')
    monkeypatch.setattr(native.Fenster, '_hintergrund_gui_sichtbarkeit', lambda self, visible: None)
    h.probe.destroy = lambda: state.destroyed.append(True)
    h.probe._organizer_vertraut = lambda: True; h.probe._darf_schreiben = lambda: True
    h.probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, h.probe)
    h.probe._baum_sperre, h.probe._baumdienst, h.probe._baum = h.service._sperre, h.service, h.receiver
    peer = native.baum_partner(h.receiver, h.sender['kennung']); peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
    h.receiver.setdefault('syncEpoch', 'synthetic-host-epoch')
    def peer_choice(values):
        assert not h.probe._daten_sperre._is_owned() and not h.probe._baum_sperre._is_owned()
        state.peers.append(values)
        if state.mode == 'peer-error': raise RuntimeError('synthetic peer chooser failure')
        if state.mode in ('cancel-peer', 'close-peer'):
            if state.mode == 'close-peer': assert native.Fenster._beenden_endgueltig(h.probe) is True
            else: state.host.stop()
            assert state.host.poll() is True and not state.host.quiesced.is_set(), 'Pending slot was mistaken for returned native peer dialog'
        return h.sender['kennung']
    def source_choice(values):
        assert threading.current_thread() is threading.main_thread()
        assert not h.probe._daten_sperre._is_owned() and not h.probe._baum_sperre._is_owned()
        state.choices.append(values)
        if state.mode == 'source-error': raise RuntimeError('synthetic source chooser failure')
        return None if state.mode == 'source-cancel' else 0
    def contact_choice(view):
        assert threading.current_thread() is threading.main_thread()
        assert not h.probe._daten_sperre._is_owned() and not h.probe._baum_sperre._is_owned()
        state.contacts.append(view)
        if state.mode == 'cancel-contact':
            state.host.stop()
            assert state.host.poll() is True and not state.host.quiesced.is_set()
        return None if state.mode == 'contact-cancel' else view.contacts[0]['id']
    def status(phase):
        assert threading.current_thread() is threading.main_thread()
        assert not h.probe._daten_sperre._is_owned() and not h.probe._baum_sperre._is_owned()
        state.notices.append(phase)
        if state.mode == 'notice-error': raise RuntimeError('synthetic closed status widget')
    def sender(url, body):
        assert threading.current_thread() is not threading.main_thread()
        assert not h.probe._daten_sperre._is_owned() and not h.probe._baum_sperre._is_owned()
        state.calls.append(url)
        if state.mode in ('cancel-active-probe', 'close-active-probe'):
            state.arrived.set()
            assert state.release.wait(5), 'Held fixture probe was not released'
            raise PermissionError('synthetic cancelled held probe')
        if url.endswith('/sitzung'):
            answer, session = native.fs_antwort_bauen(h.sender, {'kennung': h.receiver['kennung'], 'oeffentlich': h.receiver['oeffentlich']}, body)
            state.sessions.append(session); return answer
        session = state.sessions[-1]
        clear, _ = native.umschlag_oeffnen_fs(session, h.sender['kennung'], h.receiver['kennung'], body)
        assert clear['art'] == 'kontakt_original_aushandlung'
        h.send(dict(clear, antwort=True))
        if state.mode != 'cancel-wait': h.send(h.export)
        state.arrived.set()
        return native.fs_ack_bauen(session, body)
    def start():
        state.host = native.Fenster._notes_original_native_setup_run(h.probe, status, source_choice, peer_choice, contact_choice, sender)
        return state.host
    def ready(value=True):
        offer = [value for callback, value in h.replies if callback == 'App.notesSetupVorbereiten'][-1]
        snapshot = h.probe._kontakt_quellen_buchaufnahme()
        message = dict(cmd='notes_setup_prepared', token=offer['token'], bereit=value,
            standSha256=snapshot.saved_sha256 if snapshot is not None else '')
        native.Fenster.bei_nachricht(h.probe, json.dumps(message))
        return message
    def pump():
        while not state.posts.empty():
            callback = state.posts.get_nowait(); callback()
            if state.mode == 'replay': callback()
        for identifier, (kind, callback) in list(state.timers.items()):
            if identifier in state.timers and kind == 25 and callback() is False: state.timers.pop(identifier, None)
    def finish():
        deadline = time.monotonic() + 8
        while not state.host.quiesced.is_set() or not state.posts.empty():
            assert time.monotonic() < deadline, 'Native host did not join its bounded owned work'
            pump(); time.sleep(.001)
        assert state.host.poll() is False
    state.start, state.ready, state.pump, state.finish = start, ready, pump, finish
    try:
        yield state
    finally:
        state.release.set()
        if state.host is not None:
            state.host.stop(); finish()
        for session in state.sessions: native.fs_sitzung_loeschen(session)
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['complete', 'source-cancel', 'contact-cancel', 'source-error', 'peer-error', 'offline',
    'prepare-cancel', 'cancel-prepare', 'expiry', 'cancel-peer', 'close-peer', 'cancel-contact', 'cancel-wait',
    'cancel-active-probe', 'close-active-probe', 'profile-replace', 'locked', 'replay', 'notice-error', 'busy', 'foreign-entry'])
def test_actual_native_linux_host_joins_preparation_worker_and_dialogs(host_case, mode):
    s = host_case; h, native = s.h, s.native; s.mode = mode
    before = Path(native.daten_datei()).read_bytes()
    host = s.start()
    assert host.phase == 'preparing' and not s.calls and not s.peers and not h.store.has_desired_consent()
    if mode in ('busy', 'foreign-entry'):
        version = h.probe._notes_original_setup_version
        with pytest.raises(PermissionError): s.start()
        assert h.probe._notes_original_setup_version == version
        if mode == 'foreign-entry':
            with pytest.raises(PermissionError): native.Fenster._notes_original_native_setup_acquire(h.probe)
            with pytest.raises(PermissionError): native.Fenster._notes_original_native_setup_prepare(h.probe, lambda _: None)
            with pytest.raises(PermissionError): native.Fenster._notes_original_native_setup_candidate(h.probe, {})
    if mode == 'cancel-prepare':
        host.stop(); s.finish(); s.ready()
    elif mode == 'expiry':
        identifier, (_, callback) = next((key, value) for key, value in s.timers.items() if value[0] == 'prepare')
        assert callback() is False; s.timers.pop(identifier, None)
    else: s.ready(mode != 'prepare-cancel')
    if mode in ('cancel-wait', 'cancel-active-probe', 'close-active-probe'):
        assert s.arrived.wait(5)
        if mode == 'close-active-probe':
            assert native.Fenster._beenden_endgueltig(h.probe) is True
            assert not s.destroyed and not h.probe._wirklich_beenden
        else: host.stop()
        if mode != 'cancel-wait': assert host.poll() is True and not host.quiesced.is_set()
        s.release.set()
    if mode in ('profile-replace', 'locked'):
        deadline = time.monotonic() + 5
        while host._run.phase != 'offering':
            assert time.monotonic() < deadline; time.sleep(.001)
        if mode == 'locked': h.probe._gesperrt = True
        else: h.probe._aktuelle_daten = copy.deepcopy(h.probe._aktuelle_daten)
        # Poll the native profile restriction before delivering the queued UI choice.
        next(callback for kind, callback in s.timers.values() if kind == 25)()
    s.finish()
    granted = mode in ('complete', 'replay', 'notice-error', 'busy', 'foreign-entry')
    expected = 'configured' if granted else 'held' if mode in ('peer-error', 'source-error') else 'waiting-network' if mode == 'offline' else 'cancelled'
    assert host.phase == expected and h.store.has_desired_consent() == granted
    assert host._run is None and host._worker is None and host._owned is None
    assert h.probe._notes_original_setup_host is None and h.service._notes_setup_collector is None
    assert len(s.choices) <= 1 and len(s.contacts) <= 1
    assert s.notices == ([] if mode == 'locked' else [expected])
    assert Path(native.daten_datei()).read_bytes() == before
    if mode in ('close-peer', 'close-active-probe'):
        assert native.Fenster._beenden_endgueltig(h.probe) is False and s.destroyed == [True]
        with pytest.raises(PermissionError): s.start()
    host.stop(); assert host.poll() is False


@pytest.mark.parametrize('mode', ['worker-error', 'not-started', 'fake-acquisition', 'stop-before-start'])
def test_host_constructor_and_rejected_worker_cannot_start_or_strand_native_work(host_case, mode):
    s = host_case; h, native = s.h, s.native
    begun, cancelled, launched, notices = [], [], [], []
    quiet = [False]
    def begin(ready):
        begun.append(True)
        if mode == 'fake-acquisition': ready({'permission': True}); return
        acquisition = native.Fenster._notes_original_native_setup_acquire(h.probe, lambda _: h.sender['kennung'])
        ready(acquisition)
        ready(acquisition)  # Duplicate callback must not consume another owner or launch twice.
    def launch(work):
        launched.append(True)
        if mode == 'worker-error': raise RuntimeError('synthetic unavailable worker scheduler')
        return threading.Thread(target=work)  # Intentionally NOT started; this cannot be accepted as joined work.
    host = NativeNotesSetupHost(begin, lambda: cancelled.append(True), launch,
        lambda callback: s.posts.put(callback) or True, lambda _: 0, lambda view: view.contacts[0]['id'],
        notices.append, lambda: quiet[0])
    s.host = host
    assert not begun and not launched and not s.calls
    if mode == 'stop-before-start':
        host.stop()
        with pytest.raises(PermissionError): host.start()
    else: host.start()
    assert host.poll() is True and not host.quiesced.is_set(), 'Missing native dialog quietness was treated as a successful join'
    quiet[0] = True
    assert host.poll() is False and host.quiesced.is_set()
    assert notices == ['cancelled' if mode == 'stop-before-start' else 'held']
    assert len(begun) == int(mode != 'stop-before-start') and len(launched) == int(mode in ('worker-error', 'not-started'))
    assert not s.calls and not h.store.has_desired_consent() and h.service._notes_setup_collector is None


@pytest.mark.parametrize('mode', ['pending', 'note-snapshot'])
def test_actual_dom_numeric_writer_to_native_host_and_fs1_source_publication(host_case, monkeypatch, tmp_path, mode):
    s = host_case; h, native = s.h, s.native
    node = os.environ.get('NODE') or shutil.which('node'); assert node
    h.probe._aktuelle_daten['notizen'] = [{'id': 'synthetic-setup-note', 'titel': 'Note', 'text': 'Keep', 'html': 'Keep'}]
    assert h.save(monkeypatch)['ok']
    h.probe._kontakt_quellen_buch = NativeContactSourceBook(); h.probe._kontakt_quellen_buch.set_ready(True)
    assert h.probe._kontakt_quellen_buchaufnahme() is None
    s.start()
    offer = [value for callback, value in h.replies if callback == 'App.notesSetupVorbereiten'][-1]
    script = Path(__file__).resolve().parents[2] / 'magnolie-organizer-windows/tests/notes-setup-preparation.js'
    environment = dict(os.environ, MAGNOLIE_TEST_WEB=str(Path(__file__).resolve().parents[1] / 'web'))
    with (tmp_path / 'host-node-errors.log').open('w') as errors:
        process = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, env=environment)
        def send(packet): process.stdin.write(json.dumps(packet, ensure_ascii=False) + '\n'); process.stdin.flush()
        try:
            send(dict(type='init', mode=mode, daten=h.probe._aktuelle_daten))
            while True:
                line = process.stdout.readline(); assert line, (tmp_path / 'host-node-errors.log').read_text()
                packet = json.loads(line)
                if packet['type'] == 'initialized': send(dict(callback='notesSetupVorbereiten', value=offer)); continue
                if packet['type'] != 'command': continue
                command = packet['value']
                if command['cmd'] == 'speichern':
                    assert not s.peers and not s.calls
                    native.Fenster.bei_nachricht(h.probe, json.dumps(command))
                    h.probe._speicher_auftraege.put(None)
                    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,)); worker.start(); worker.join(15)
                    assert not worker.is_alive()
                    ack = [value for callback, value in h.replies if callback == 'App.gespeichert'][-1]
                    assert ack['ok'] is True and ack['id'] == command['id']
                    send(dict(callback='gespeichert', value=ack))
                elif command['cmd'] == 'notes_setup_prepared':
                    native.Fenster.bei_nachricht(h.probe, json.dumps(command)); break
            s.finish()
            assert s.host.phase == 'configured' and h.store.has_desired_consent()
            assert len(s.peers) == len(s.choices) == len(s.contacts) == 1 and len(s.calls) == 2
            if mode == 'pending': assert h.probe._aktuelle_daten['kontakte'][0]['notiz'] == 'Latest synthetic edit during pending save'
            else: assert h.probe._aktuelle_daten['notizen'][0]['text'] == 'Latest pending synthetic note'
            send(dict(type='finish')); process.wait(timeout=5); assert process.returncode == 0
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
