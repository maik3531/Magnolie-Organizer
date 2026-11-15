"""#638 actual DOM/numeric IPC/encrypted writer/journal, no installed GUI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import pytest

from test_contact_notes_consent import Harness, native
from test_contact_notes_controller import Runtime


@pytest.mark.parametrize('mode', ['normal', 'bootstrap', 'reopen', 'reopen-unsent', 'unsent', 'tampered-offer', 'unknown-ack'])
def test_actual_native_notes_save_is_adopted_by_dom_and_survives_next_real_user_save(native, monkeypatch, tmp_path, mode):
    node = os.environ.get('NODE') or shutil.which('node')
    assert node, 'Existing Node runtime required'
    h = Harness(native, tmp_path)
    h.probe._organizer_vertraut = lambda: True
    h.probe._darf_schreiben = lambda: True
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
    script = Path(__file__).with_name('notes-original-native-save-repro.cjs')
    errors = (tmp_path / 'node-stderr.log').open('w')
    process = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
        text=True, env=os.environ.copy())
    def send(value):
        process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n'); process.stdin.flush()
    def write_queue():
        h.probe._speicher_auftraege.put(None)
        thread = threading.Thread(target=native.Fenster._speicher_lauf, args=(h.probe,), daemon=True)
        thread.start(); thread.join(15)
        assert not thread.is_alive(), 'Actual native writer exceeded bounded fixture run'
        return [value for callback, value in h.replies if callback == 'App.gespeichert'][-1]
    try:
        send({'type': 'init', 'data': h.probe._aktuelle_daten, 'mode': mode})
        initialized, native_basis, renderer_basis, journal_key, history_before, runtime = False, None, None, None, None, None
        while True:
            line = process.stdout.readline()
            assert line, (tmp_path / 'node-stderr.log').read_text()
            packet = json.loads(line)
            if packet['type'] == 'command' and packet['value']['cmd'] == 'speichern':
                command = packet['value']
                native.Fenster.bei_nachricht(h.probe, json.dumps(command))
                assert h.probe._speicher_auftraege.qsize() == 1
                result = write_queue()
                assert result['ok'] is True and result['id'] == command['id']
                if 'notesOriginalLauf' in command and 'notesOriginalBasis' in h.probe._aktuelle_daten['kontakte'][0]:
                    native_basis = h.probe._aktuelle_daten['kontakte'][0]['notesOriginalBasis']
                    journal_path, = (tmp_path / 'outcomes').glob('*.bin'); journal_key = journal_path.stem
                    history_before = journal_path.read_bytes()
                    assert runtime.outcomes.readonly_query(journal_key, h.store).request()
                send({'type': 'ack', 'value': result})
            elif packet['type'] == 'initialized':
                assert not initialized; initialized = True
                h.configure(); runtime = Runtime(h); request_work = runtime.start(); request = request_work.intent.request()
                if mode in ('bootstrap', 'reopen', 'reopen-unsent'):
                    old = runtime
                    proof = request_work.intent._request_intention
                    old.controller.stop(); h.restart()
                    runtime = Runtime(h); runtime.negotiate()
                    runtime.controller.register_unconfirmed(proof.key, runtime.protocol, physical=proof.physical)
                h.probe._notes_original_controller = runtime.controller
                if mode in ('reopen', 'reopen-unsent'):
                    send({'type': 'reopen', 'data': h.probe._aktuelle_daten, 'mode': mode})
                    continue
                h.send(runtime.result(request))
                work = native.Fenster._notes_original_native_arbeit(h.probe)
                assert work.kind == ('needs-real-save' if mode == 'bootstrap' else 'save') and h.probe._speicher_auftraege.qsize() == 0
                offer = [value for callback, value in h.replies if callback == 'App.notesOriginalSpeichern'][-1]
                if mode == 'tampered-offer':
                    altered = json.loads(offer['text']); altered['kontakte'][0]['notiz'] = 'Not metadata only'
                    offer = dict(offer, text=json.dumps(altered))
                send({'type': 'offer', 'value': offer})
            elif packet['type'] == 'reopened':
                assert mode in ('reopen', 'reopen-unsent') and h.probe._kontakt_quellen_buchaufnahme() is None
                h.send(runtime.result(request))
                work = native.Fenster._notes_original_native_arbeit(h.probe)
                assert work.kind == 'needs-real-save' and h.probe._speicher_auftraege.empty()
                offer = [value for callback, value in h.replies if callback == 'App.notesOriginalSpeichern'][-1]
                send({'type': 'offer', 'value': offer})
            elif packet['type'] == 'bootstrap-observation':
                assert mode in ('bootstrap', 'reopen') and not list((tmp_path / 'outcomes').glob('*.bin'))
                work = native.Fenster._notes_original_native_arbeit(h.probe)
                assert work.kind == 'save' and h.probe._speicher_auftraege.empty()
                offer = [value for callback, value in h.replies if callback == 'App.notesOriginalSpeichern'][-1]
                send({'type': 'offer', 'value': offer})
            elif packet['type'] == 'command' and packet['value']['cmd'] == 'notes_original_save_cancel':
                assert mode in ('unsent', 'reopen-unsent', 'tampered-offer')
                native.Fenster.bei_nachricht(h.probe, json.dumps(packet['value']))
                assert h.probe._speicher_auftraege.empty()
                assert 'notesOriginalBasis' not in h.probe._aktuelle_daten['kontakte'][0]
                assert not list((tmp_path / 'outcomes').glob('*.bin'))
                assert runtime.controller._physical
                send({'type': 'finish'})
                assert json.loads(process.stdout.readline())['type'] == 'finished'
                process.wait(timeout=5)
                assert process.returncode == 0
                break
            elif packet['type'] == 'native-observation':
                assert packet['idType'] == 'number'; renderer_basis = packet['basis']
                send({'type': 'edit'})
            elif packet['type'] == 'complete':
                assert packet['data']['kontakte'][0]['notiz'] == 'Later synthetic user edit must survive'
                decoded = json.loads(native.daten_entschluesseln(Path(native.daten_datei()).read_text(), h.probe._kennwort))
                assert decoded == h.probe._aktuelle_daten and decoded['kontakte'][0]['notiz'] == 'Later synthetic user edit must survive'
                journal_path, = (tmp_path / 'outcomes').glob('*.bin')
                assert journal_path.read_bytes() == history_before
                retained_basis = decoded['kontakte'][0].get('notesOriginalBasis')
                history_error = None
                try: runtime.outcomes.readonly_query(journal_key, h.store).request()
                except PermissionError as error: history_error = str(error)
                send({'type': 'finish'})
                assert json.loads(process.stdout.readline())['type'] == 'finished'
                process.wait(timeout=5)
                assert process.returncode == 0
                assert renderer_basis == native_basis and retained_basis == native_basis and history_error is None, (
                    'Actual native metadata save was not adopted by DOM; next real user save lost Notes basis (query availability observed separately)',
                    {'rendererHadBasis': renderer_basis is not None, 'nativeBasisRetained': retained_basis is not None, 'historyError': history_error})
                break
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=5)
        errors.close(); h.service.anhalten()
