"""Synthetic tree consent/status delivery; no user profiles, sockets or firewall."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from modul_laden import quellmodul_laden
from test_baum_off_state import Host


@pytest.fixture
def native_opt_in(tmp_path, monkeypatch):
    for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'):
        path = tmp_path / key; path.mkdir()
        monkeypatch.setenv(key, str(path))
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'unix:path=' + str(tmp_path / 'absent-session'))
    monkeypatch.setenv('DBUS_SYSTEM_BUS_ADDRESS', 'unix:path=' + str(tmp_path / 'absent-system'))
    monkeypatch.setitem(sys.modules, 'gi', None)
    module = quellmodul_laden('baum_ui_opt_in', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')
    profile = tmp_path / 'owned-book'; profile.mkdir()
    monkeypatch.setattr(module, 'daten_verzeichnis', lambda: str(profile))
    monkeypatch.setattr(module, 'GLib', SimpleNamespace(idle_add=lambda *_: 0))
    starts = []
    class Service:
        def __init__(self, *_args, **_kwargs): pass
        def starten(self): starts.append(True); return True
        def anhalten(self): pass
    monkeypatch.setattr(module, 'BaumDienst', Service)
    monkeypatch.setattr(module, 'baum_firewall_einrichten', lambda: (True, ''))
    assert module.baum_moeglich()
    return module, starts


@pytest.mark.parametrize('missing_field', [False, True])
def test_fresh_or_legacy_missing_activation_stays_off(native_opt_in, missing_field):
    module, starts = native_opt_in
    if missing_field:
        state = module.baum_schluessel_erzeugen('Owned fixture'); state.pop('an')
        Path(module.baum_datei()).write_text(json.dumps(state))
    host = Host(module)
    assert host._baum_bericht()['an'] is False
    assert host._baum_dienst_pflegen() is False
    assert module.baum_lesen()['an'] is False
    assert not starts


def test_previous_explicit_on_and_off_keep_identity_on_reload(native_opt_in):
    module, starts = native_opt_in
    host = Host(module)
    original = host._baum_zustand()
    identity = {key: original[key] for key in ('kennung', 'geheim', 'oeffentlich', 'partner')}
    host._baum_schalten(True, 'Owned fixture')
    assert Host(module)._baum_bericht()['an'] is True
    assert len(starts) == 1
    host._baum_schalten(False, 'Owned fixture')
    assert Host(module)._baum_bericht()['an'] is False
    stored = module.baum_lesen()
    assert {key: stored[key] for key in identity} == identity
    assert len(starts) == 1


def test_delayed_on_status_cannot_override_newer_persisted_opt_out(native_opt_in, monkeypatch):
    module, starts = native_opt_in
    state = module.baum_schluessel_erzeugen('Owned fixture'); state['an'] = True
    module.baum_schreiben(state)
    queued, delivered, errors = [], [], []
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    calls = [0]
    def schedule(callback, *_args):
        with lock:
            first = calls[0] == 0; calls[0] += 1
        if first:
            entered.set()
            assert release.wait(3)
        with lock: queued.append(callback)
        return len(queued)
    monkeypatch.setattr(module.GLib, 'idle_add', schedule)
    class View:
        def evaluate_javascript(self, script, *_args):
            prefix, suffix = 'App.baumStand(JSON.parse(', '));'
            assert script.startswith(prefix) and script.endswith(suffix)
            delivered.append(json.loads(json.loads(script[len(prefix):-len(suffix)])))
    class GuiHost(Host):
        def _baum_stand_melden(self): return module.Fenster._baum_stand_melden(self)
    host = GuiHost(module); host.ansicht = View()
    def older_report():
        try: host._baum_stand_melden()
        except BaseException as error: errors.append(error)
    worker = threading.Thread(target=older_report)
    worker.start()
    try:
        assert entered.wait(3)
        host._baum_schalten(False, 'Owned fixture')
        assert module.baum_lesen()['an'] is False
    finally:
        release.set(); worker.join(3)
    assert not worker.is_alive() and not errors
    for callback in queued: callback()
    assert len(delivered) == 2
    assert module.baum_lesen()['an'] is False and not starts
    assert delivered[-1]['an'] is False, 'Older queued status re-enabled the checkbox after a durable explicit opt-out'
