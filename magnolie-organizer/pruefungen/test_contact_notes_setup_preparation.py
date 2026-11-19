"""#640 actual Linux DOM/numeric IPC/encrypted writer -> pre-peer native CAS."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from types import MethodType

import pytest

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_setup import NativeNotesSetupPreparation
from magnolie_contact_source_book import NativeContactSourceBook


@pytest.mark.parametrize('mode', ['expiry', 'stop', 'foreign-reply', 'malformed-reply', 'busy'])
def test_native_ui_preparation_owns_timeout_reply_and_cleanup(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    outcomes, timers, removed = [], [], []
    monkeypatch.setattr(native.GLib, 'timeout_add_seconds', lambda seconds, callback: timers.append(callback) or len(timers), raising=False)
    monkeypatch.setattr(native.GLib, 'source_remove', lambda timer: removed.append(timer), raising=False)
    try:
        preparation = native.Fenster._notes_original_native_setup_prepare(h.probe, outcomes.append)
        if mode == 'busy':
            with pytest.raises(PermissionError): native.Fenster._notes_original_native_setup_prepare(h.probe, outcomes.append)
            assert len(timers) == 1
        message = dict(cmd='notes_setup_prepared', token=preparation.token, bereit=False, standSha256='')
        if mode == 'expiry':
            assert timers[0]() is False and outcomes == [None] and not removed
            assert timers[0]() is False and outcomes == [None]
        elif mode == 'stop':
            native.Fenster._notes_original_native_stop_session(h.probe)
            assert outcomes == [] and removed == [1]
            assert timers[0]() is False and outcomes == []
        else:
            if mode in ('foreign-reply', 'malformed-reply'):
                invalid = dict(message, token='f' * 64) if mode == 'foreign-reply' else dict(message, permission=True)
                native.Fenster._notes_original_native_setup_prepared(h.probe, invalid)
                assert not outcomes and not removed and h.probe._notes_original_setup_preparation[0] is preparation
            native.Fenster._notes_original_native_setup_prepared(h.probe, message)
            assert outcomes == [None] and removed == [1]
        assert h.probe._notes_original_setup_preparation is None
        assert preparation.accept(message) is None and not h.store.has_desired_consent()
    finally:
        native.Fenster._notes_original_native_setup_preparation_stop(h.probe)
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['saved', 'loaded', 'wrong-token', 'wrong-hash', 'not-idle', 'expired', 'new-owner', 'stopped', 'extra-field'])
def test_native_preparation_never_invents_saved_witness_from_renderer(native, tmp_path, mode):
    h = Harness(native, tmp_path)
    try:
        if mode == 'loaded':
            h.probe._kontakt_quellen_buch = NativeContactSourceBook(); h.probe._kontakt_quellen_buch.set_ready(True)
        now = [0]
        source = lambda: h.probe._kontakt_quellen_buch.source(*h.probe._kontakt_quellen_buchbindung())
        owner = [source()]
        preparation = NativeNotesSetupPreparation(lambda: owner[0], h.probe._kontakt_quellen_buchaufnahme, clock=lambda: now[0])
        snapshot = h.probe._kontakt_quellen_buchaufnahme()
        message = dict(cmd='notes_setup_prepared', token=preparation.token, bereit=mode != 'not-idle',
            standSha256=snapshot.saved_sha256 if snapshot is not None else 'a' * 64)
        if mode == 'wrong-token':
            assert preparation.accept(dict(message, token='f' * 64)) is None
        if mode == 'wrong-hash': message['standSha256'] = 'c' * 64
        if mode == 'expired': now[0] = 40
        if mode == 'new-owner': owner[0] = 'd' * 64
        if mode == 'stopped': preparation.stop()
        if mode == 'extra-field':
            assert preparation.accept(dict(message, permission=True)) is None
        accepted = preparation.accept(message)
        assert (accepted is not None) == (mode in ('saved', 'wrong-token', 'extra-field'))
        assert preparation.accept(message) is None
        assert not h.store.has_desired_consent()
    finally:
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['fresh', 'pending', 'note-snapshot', 'string-ack', 'replay', 'repair-pending', 'locked', 'editor', 'modal'])
def test_actual_linux_editor_flush_before_native_peer_choice(native, monkeypatch, tmp_path, mode):
    node = os.environ.get('NODE') or shutil.which('node')
    assert node, 'Existing Node runtime required'
    h = Harness(native, tmp_path)
    acquired, peers, timers, removed = [], [], {}, []
    process = None
    try:
        h.probe._organizer_vertraut = lambda: True; h.probe._darf_schreiben = lambda: True
        h.probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, h.probe)
        h.probe._baum_sperre, h.probe._baumdienst, h.probe._baum = h.service._sperre, h.service, h.receiver
        peer = native.baum_partner(h.receiver, h.sender['kennung']); peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
        h.receiver.setdefault('syncEpoch', 'synthetic-preparation-epoch')
        h.probe._aktuelle_daten['notizen'] = [{'id': 'synthetic-setup-note', 'titel': 'Note', 'text': 'Keep', 'html': 'Keep'}]
        assert h.save(monkeypatch)['ok']
        h.probe._kontakt_quellen_buch = NativeContactSourceBook(); h.probe._kontakt_quellen_buch.set_ready(True)
        assert h.probe._kontakt_quellen_buchaufnahme() is None
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: mode != 'repair-pending')
        def schedule(seconds, callback):
            assert seconds == 40
            timers[len(timers) + 1] = callback; return len(timers)
        monkeypatch.setattr(native.GLib, 'timeout_add_seconds', schedule, raising=False)
        monkeypatch.setattr(native.GLib, 'source_remove', lambda timer: removed.append(timer), raising=False)
        def choose(values):
            assert threading.current_thread() is threading.main_thread()
            assert not h.probe._daten_sperre._is_owned() and not h.probe._baum_sperre._is_owned()
            peers.append(values)
            return h.sender['kennung']
        preparation = native.Fenster._notes_original_native_setup_prepare(h.probe, acquired.append, choose)
        assert not acquired and not peers and not h.store.has_desired_consent()
        offer = [value for callback, value in h.replies if callback == 'App.notesSetupVorbereiten'][-1]
        script = Path(__file__).resolve().parents[2] / 'magnolie-organizer-windows/tests/notes-setup-preparation.js'
        environment = dict(os.environ, MAGNOLIE_TEST_WEB=str(Path(__file__).resolve().parents[1] / 'web'))
        errors = tmp_path / 'preparation-node-stderr.log'
        with errors.open('w') as stderr:
            process = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True, env=environment)
            def send(value):
                process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n'); process.stdin.flush()
            send(dict(type='init', mode=mode, daten=h.probe._aktuelle_daten))
            delayed, saves, replies = None, 0, 0
            while True:
                line = process.stdout.readline()
                assert line, errors.read_text()
                packet = json.loads(line)
                if packet['type'] == 'initialized':
                    send(dict(callback='notesSetupVorbereiten', value=offer)); continue
                if packet['type'] == 'string-ack-ignored':
                    assert not acquired and not peers
                    send(dict(callback='gespeichert', value=delayed)); continue
                if packet['type'] != 'command': continue
                command = packet['value']
                if command['cmd'] == 'speichern':
                    assert not acquired and not peers
                    saves += 1
                    native.Fenster.bei_nachricht(h.probe, json.dumps(command))
                    assert h.probe._speicher_auftraege.qsize() == 1
                    h.probe._speicher_auftraege.put(None)
                    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,))
                    worker.start(); worker.join(15)
                    assert not worker.is_alive()
                    ack = [value for callback, value in h.replies if callback == 'App.gespeichert'][-1]
                    assert ack['ok'] is True and ack['id'] == command['id']
                    if mode == 'string-ack':
                        delayed = ack; send(dict(callback='gespeichert', value=dict(ack, id=str(ack['id']))))
                    else: send(dict(callback='gespeichert', value=ack))
                elif command['cmd'] == 'notes_setup_prepared':
                    replies += 1
                    native.Fenster.bei_nachricht(h.probe, json.dumps(command))
                    expected = mode not in ('repair-pending', 'locked', 'editor', 'modal')
                    assert len(acquired) == 1 and (acquired[0] is not None) == expected
                    assert len(peers) == int(expected)
                    native.Fenster.bei_nachricht(h.probe, json.dumps(command))
                    assert len(acquired) == 1 and not h.store.has_desired_consent()
                    assert h.probe._notes_original_setup_preparation is None and removed == [1]
                    assert replies == 1 and saves == (0 if mode in ('locked', 'editor', 'modal') else 2 if mode == 'pending' else 1)
                    if mode == 'pending': assert h.probe._aktuelle_daten['kontakte'][0]['notiz'] == 'Latest synthetic edit during pending save'
                    if mode == 'note-snapshot': assert h.probe._aktuelle_daten['notizen'][0]['text'] == 'Latest pending synthetic note'
                    if mode == 'repair-pending': assert h.probe._kontakt_quellen_buchaufnahme() is None
                    assert preparation.accept(command) is None
                    send(dict(type='finish')); process.wait(timeout=5); assert process.returncode == 0, errors.read_text()
                    break
    finally:
        if process is not None and process.poll() is None: process.kill(); process.wait(timeout=5)
        native.Fenster._notes_original_native_setup_preparation_stop(h.probe)
        for acquisition in acquired:
            if acquisition is not None: acquisition.stop()
        h.service.anhalten()
