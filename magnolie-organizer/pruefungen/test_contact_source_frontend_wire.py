"""Actual Linux frontend/native bridge/DAV/journal/encrypted writer wire.

Synthetic provider transport, native decision and WLAN observations only; no
installed GUI/device acceptance. Actual GTK and kernel probes are separate.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from test_startup_read_failure import native, Host
from test_contact_source_dav_factory import account, Source
from magnolie_contact_source_book import NativeContactSourceBook
import magnolie_nextcloud as nc


@pytest.mark.parametrize('return_wlan', [False, True, 'after-write'])
def test_actual_linux_frontend_saveack_consent_plan_readback_and_result_writer(native, tmp_path, monkeypatch, return_wlan):
    node = os.environ.get('NODE') or shutil.which('node')
    if not node: pytest.skip('Explicit existing Node runtime required for actual frontend wire')
    root = Path(__file__).resolve().parents[2]
    host, source, store = Host(native), Source(native), account(tmp_path)
    host._gesperrt = False; host._wirklich_beenden = False
    remote = native.vcf_lesen(source.wire)['kontakte'][0]
    contact = dict(copy.deepcopy(remote), id='local-person', uid='canonical-person', sync=True)
    key = nc.source_id('addressbook', source.href, 'generic-dav')
    native._dav_syncquelle_setzen(contact, key, source.resource, source.etag, baseline=remote)
    initial = {'version': 7, 'syncEpoch': 'synthetic-linux-frontend-wire', 'kontakte': [contact],
               'notizen': [{'id': 'keep', 'titel': 'Keep', 'text': 'Synthetic other domain'}],
               'customOrganizer': {'drawing': {'x': 1.25}}, 'einstellungen': {}}
    host._aktuelle_daten = initial
    host._kennwort = 'Synthetic-only-618-frontend'
    text = json.dumps(initial, ensure_ascii=False)
    encrypted, host._daten_dek, host._daten_dek_kennung, host._daten_umschlag = native.daten_huelle_anlegen(text, host._kennwort)
    native.speichere_text(encrypted)
    host._kontakt_quellen_buch = NativeContactSourceBook(); host._kontakt_quellen_buch.set_ready(True)
    host._kontakt_quellen_buch.record_saved(*host._kontakt_quellen_buchbindung(), text)
    actual_client = store.checked_client
    wlan = [not return_wlan or return_wlan == 'after-write']
    def provider_transport(*args):
        response = source.transport(*args)
        if return_wlan == 'after-write' and args[0] == 'PUT': wlan[0] = False
        return response
    monkeypatch.setattr(store, 'checked_client', lambda revision, purpose='dav', transport=None:
                        actual_client(revision, purpose=purpose, transport=provider_transport))
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: store)
    monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', lambda: wlan[0])
    monkeypatch.setattr(native, 'kontakt_quellen_freigabe_dialog', lambda parent, choices, selected:
                        tuple(item['uid'] for item in choices))
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
    idles, threads, protected = [], [], []
    removed = []
    glib = SimpleNamespace(idle_add=lambda fn, *args: idles.append((fn, args)),
                           source_remove=lambda timer: removed.append(timer))
    if return_wlan: glib.timeout_add_seconds = lambda seconds, fn: 17
    monkeypatch.setattr(native, 'GLib', glib)
    actual_thread = threading.Thread
    def make_thread(*args, **kwargs):
        thread = actual_thread(*args, **kwargs); threads.append(thread); return thread
    monkeypatch.setattr(native, 'threading', SimpleNamespace(Thread=make_thread))
    actual_protect = host._kontakt_quellen_schutz
    protection_errors = []
    def protect(snapshot):
        try: identity = actual_protect(snapshot)
        except Exception as error:
            protection_errors.append({'error': type(error).__name__ + ': ' + str(error),
                                      'bookVersion': snapshot.book().get('version')})
            raise
        assert native.journal_snapshot_lesen(identity, host._kennwort, exakt=True)[1]['daten'] == snapshot.book()
        protected.append(identity)
        return identity
    host._kontakt_quellen_schutz = protect
    environment = dict(os.environ, MAGNOLIE_TEST_WEB=str(root / 'magnolie-organizer/web'),
                       MAGNOLIE_TEST_EXPECT_ORIGINAL_RUNS='2' if return_wlan else '1')
    saves, forwarded, complete = 0, 0, None
    planner_observations = []
    actual_plan = native.kontakt_quellen_update_plan
    def checked_plan(*args):
        try:
            result = actual_plan(*args)
            planner_observations.append('status=' + result['status'])
            return result
        except Exception as error:
            planner_observations.append(type(error).__name__ + ': ' + str(error)); raise
    monkeypatch.setattr(native, 'kontakt_quellen_update_plan', checked_plan)
    wire_commands = []
    wlan_returns = 0
    requests_before_update = None
    def settle():
        for _ in range(5):
            for thread in list(threads):
                thread.join(timeout=20)
                assert not thread.is_alive(), 'Native controller exceeded bounded wire run'
                threads.remove(thread)
            pending = list(idles); idles.clear()
            for fn, args in pending: fn(*args)
            if not threads and not idles: return
        raise AssertionError('Native wire callbacks did not settle')
    stderr_path = tmp_path / 'frontend-wire-stderr.log'
    with stderr_path.open('w') as errors:
        process = subprocess.Popen([node, str(root / 'magnolie-organizer-windows/tests/contact-original-source-updates.js'), '--wire'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, env=environment)
        def send(value):
            process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n'); process.stdin.flush()
        try:
            send({'type': 'init', 'daten': initial})
            for line in process.stdout:
                message = json.loads(line)
                if message['type'] == 'complete':
                    complete = message; break
                assert message['type'] == 'command'
                command = message['value']
                wire_commands.append(command['cmd'])
                if command['cmd'] not in ('speichern', 'kontakt_originalquellen_freigabe', 'kontakt_originalquellen_update'):
                    continue  # No real account/phone/discovery/background command.
                if command['cmd'] == 'kontakt_originalquellen_freigabe': assert saves == 2 and source.writes == 0
                if command['cmd'] == 'kontakt_originalquellen_update':
                    assert saves == 2
                    if return_wlan and not wlan_returns: requests_before_update = len(source.records)
                host.bei_nachricht(json.dumps(command, ensure_ascii=False))
                settle()
                if command['cmd'] == 'speichern':
                    saves += 1
                    host._speicher_auftraege.put(None)
                    native.Fenster._speicher_lauf(host)
                while forwarded < len(host.responses):
                    callback, response = host.responses[forwarded]; forwarded += 1
                    if callback not in ('App.gespeichert', 'App.originalKontaktFreigabe', 'App.originalKontaktErgebnis', 'App.originalKontaktNetz'):
                        continue
                    if callback == 'App.originalKontaktNetz':
                        send({'callback': 'originalKontaktNetz', 'value': response}); continue
                    if return_wlan and callback == 'App.originalKontaktErgebnis' and response.get('code') == 'wlan_required':
                        assert wlan_returns == 0
                        if return_wlan == 'after-write':
                            assert source.writes == 1 and len(protected) == 1
                            assert host._aktuelle_daten['kontakte'][0]['syncQuellen'][key]['etag'] == '"v1"'
                        else:
                            assert source.writes == 0 and len(source.records) == requests_before_update
                        send({'callback': 'originalKontaktErgebnis', 'value': response})
                        wlan_returns += 1; wlan[0] = True
                        host._kontakt_quellen_netz_pruefen(); settle()
                        continue
                    assert response['ok'] is True, (callback, response)
                    if callback == 'App.originalKontaktErgebnis':
                        assert response.get('token'), {'writes': source.writes,
                            'plannerObservations': planner_observations, 'protectionErrors': protection_errors}
                    send({'callback': callback.split('.', 1)[1], 'value': response})
            if complete is None:
                print('wire-diagnostic=' + json.dumps({'saves': saves, 'writes': source.writes,
                    'plannerObservations': planner_observations, 'commands': wire_commands,
                    'replies': [(name, value.get('ok'), value.get('code'), value.get('freigaben'),
                                bool(value.get('token')), value.get('fehlerQuellen'))
                               for name, value in host.responses if isinstance(value, dict)]}))
            assert complete is not None, {'stderr': stderr_path.read_text()[-1500:], 'saves': saves,
                'writes': source.writes, 'commands': wire_commands,
                'replies': [(name, value.get('ok'), value.get('code'), value.get('freigaben'),
                            bool(value.get('token')), bool(value.get('kontaktOriginalGespeichert')))
                           for name, value in host.responses if isinstance(value, dict)]}
            process.wait(timeout=5)
            assert process.returncode == 0, stderr_path.read_text()[-1500:]
        finally:
            host._kontakt_quellen_netz_stoppen()
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            process.stdin.close(); process.stdout.close()
    assert saves == 3 and source.writes == 1 and len(protected) == 1
    methods = [method for method, *_ in source.records]
    assert methods.count('PUT') == 1
    if return_wlan == 'after-write':
        assert 'REPORT' in methods[methods.index('PUT') + 1:], 'Uncertain write was acknowledged without a fresh source read'
    assert wlan_returns == int(bool(return_wlan))
    if return_wlan: assert removed == [17]
    actual = native.daten_entschluesseln(Path(native.daten_datei()).read_text(), host._kennwort)
    assert actual == complete['text']
    saved = host._kontakt_quellen_buchaufnahme()
    assert saved.book() == json.loads(actual)
    assert saved.book()['kontakte'][0]['uid'] == 'canonical-person'
    assert saved.book()['kontakte'][0]['syncQuellen'][key]['etag'] == '"v2"'
    assert saved.book()['customOrganizer']['drawing']['x'] == 1.25
    assert 'UID:provider-original\r\n' in source.wire and 'Canonical note' in source.wire
