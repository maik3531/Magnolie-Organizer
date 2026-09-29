"""Tree activation order and persisted opt-out, isolated state and no network."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from modul_laden import quellmodul_laden


class Host:
    def __init__(self, module):
        self.module = module
        self._baum_sperre = threading.RLock()
        self._baum_dienst_sperre = threading.RLock()
        self._kennwort = ''
        self._gesperrt = False
        self._baum = None
        self._baumdienst = None
        self._baum_post_timer = None
        self._baum_post_planung = False
        self._baum_post_stop = False
        self._baum_fehler = ''
        self.reports = []
    def __getattr__(self, name):
        return getattr(self.module.Fenster, name).__get__(self, type(self))
    def _baum_stand_melden(self):
        self.reports.append({'an': self._baum_zustand()['an'], 'fehler': self._baum_fehler})
    def _organizer_vertraut(self): return True


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    module = quellmodul_laden('baum_off_probe', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')
    monkeypatch.setattr(module, 'daten_verzeichnis', lambda: str(tmp_path))
    monkeypatch.setattr(module, 'GLib', SimpleNamespace(idle_add=lambda *_: 0))
    starts = []
    class Service:
        def __init__(self, *args, **kwargs): pass
        def starten(self): starts.append(True); return True
        def anhalten(self): pass
    monkeypatch.setattr(module, 'BaumDienst', Service)
    monkeypatch.setattr(module, 'baum_firewall_einrichten', lambda: (True, ''))
    module.baum_schreiben(module.baum_schluessel_erzeugen('Fixture'))
    return module, starts


def test_pending_enable_cannot_override_newer_off(native, monkeypatch):
    module, starts = native
    entered, release = threading.Event(), threading.Event()
    def firewall():
        entered.set()
        assert release.wait(3)
        return True, ''
    monkeypatch.setattr(module, 'baum_firewall_einrichten', firewall)
    host = Host(module)
    thread = threading.Thread(target=lambda: host._baum_schalten(True, 'Older request'))
    thread.start()
    try:
        assert entered.wait(3)
        host._baum_schalten(False, 'Latest request')
        assert module.baum_lesen()['an'] is False
    finally:
        release.set(); thread.join(3)
    assert not thread.is_alive()
    assert module.baum_lesen()['an'] is False, 'Late enable reactivated the saved opt-out'
    assert host._baum_zustand()['name'] == 'Latest request'
    assert not starts, 'Stale enable must not start a listener'


def test_disabled_identity_survives_reload_and_startup(native):
    module, starts = native
    identity = module.baum_lesen()['kennung']
    for _ in range(3):
        host = Host(module)
        assert host._baum_dienst_pflegen() is False
        assert host._baum_zustand()['an'] is False
        assert host._baum_zustand()['kennung'] == identity
    assert not starts


def test_phone_enable_and_pairing_do_not_change_tree_opt_out(native):
    module, starts = native
    path = Path(module.baum_datei()); before = path.read_bytes()
    host = Host(module)
    phone_actions = []
    host._telefon = SimpleNamespace(set_enabled=lambda value: phone_actions.append(value),
                                   open_pairing=lambda: phone_actions.append('pair'))
    host._telefon_dienst_pflegen = lambda: None
    host._telefon_stand_melden = lambda: None
    host._telefon_schalten(True)
    host._telefon_pairing_oeffnen()
    host._telefon_schalten(False)
    assert phone_actions == [True, 'pair', False]
    assert path.read_bytes() == before
    assert Host(module)._baum_dienst_pflegen() is False and not starts


def test_explicit_enable_and_disable_are_persisted(native):
    module, starts = native
    host = Host(module)
    host._baum_schalten(True, 'Chosen name')
    assert module.baum_lesen()['an'] is True and len(starts) == 1
    host._baum_schalten(False, 'Chosen name')
    reopened = Host(module)
    assert reopened._baum_zustand()['an'] is False
    assert reopened._baum_zustand()['name'] == 'Chosen name'
    assert reopened._baum_dienst_pflegen() is False and len(starts) == 1


def test_failed_save_does_not_publish_a_successful_toggle(native, monkeypatch):
    module, starts = native
    host = Host(module)
    def fail(*_args, **_kwargs): raise OSError('Synthetic write failure')
    monkeypatch.setattr(module, 'baum_schreiben', fail)
    host._baum_schalten(True, 'New name')
    assert host._baum_zustand()['an'] is False
    assert module.baum_lesen()['an'] is False
    assert host.reports and host.reports[-1]['fehler']
    assert not starts


def test_bridge_orders_intents_before_worker_threads_start(native, monkeypatch):
    module, starts = native
    tasks = []
    class QueuedThread:
        def __init__(self, target, args=(), daemon=False): tasks.append((target, args))
        def start(self): pass
    monkeypatch.setattr(module.threading, 'Thread', QueuedThread)
    host = Host(module)
    host.bei_nachricht(json.dumps({'cmd': 'baum_ein', 'an': True, 'name': 'Older'}))
    host.bei_nachricht(json.dumps({'cmd': 'baum_ein', 'an': False, 'name': 'Latest'}))
    for target, args in reversed(tasks): target(*args)
    assert module.baum_lesen()['an'] is False
    assert module.baum_lesen()['name'] == 'Latest'
    assert not starts
    host.bei_nachricht(json.dumps({'cmd': 'baum_ein', 'an': 'false'}))
    assert len(tasks) == 2, 'Text must not be treated as a true enable flag'


@pytest.mark.parametrize('enabled', [False, True])
def test_post_rename_warning_retains_actual_committed_state(native, monkeypatch, enabled):
    module, _ = native
    host = Host(module)
    host._baum_schalten(not enabled, 'Fixture')
    original = module.baum_schreiben
    def committed_then_failed(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('Synthetic directory fsync failure')
    monkeypatch.setattr(module, 'baum_schreiben', committed_then_failed)
    host._baum_schalten(enabled, 'Committed')
    assert host._baum_zustand()['an'] is enabled
    assert module.baum_lesen()['an'] is enabled
    assert host.reports[-1]['an'] is enabled and host.reports[-1]['fehler']
    assert (host._baumdienst is not None) is enabled


@pytest.mark.parametrize('value', ['false', 'true', 0, 1, None])
def test_invalid_stored_flags_do_not_start_or_replace_identity(native, value):
    module, starts = native
    state = module.baum_lesen(); state['an'] = value
    path = Path(module.baum_datei()); path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(RuntimeError): Host(module)._baum_dienst_pflegen()
    assert path.read_bytes() == before and not starts


def test_off_waits_for_inflight_listener_start_and_then_stops_it(native, monkeypatch):
    module, _ = native
    entered, release, saved_off = threading.Event(), threading.Event(), threading.Event()
    services = []
    class SlowService:
        def __init__(self, *args, **kwargs): self.running = False; services.append(self)
        def starten(self):
            entered.set(); assert release.wait(3)
            self.running = True; return True
        def anhalten(self): self.running = False
    monkeypatch.setattr(module, 'BaumDienst', SlowService)
    state = module.baum_lesen(); state['an'] = True; module.baum_schreiben(state)
    host = Host(module)
    original_save = host._baum_sichern
    def save(value):
        original_save(value)
        if value['an'] is False: saved_off.set()
    host._baum_sichern = save
    startup = threading.Thread(target=host._baum_dienst_pflegen)
    shutdown = threading.Thread(target=lambda: host._baum_schalten(False, ''))
    startup.start()
    try:
        assert entered.wait(3)
        shutdown.start(); assert saved_off.wait(3)
    finally:
        release.set(); startup.join(3)
        if shutdown.ident is not None: shutdown.join(3)
    assert not startup.is_alive() and not shutdown.is_alive()
    assert host._baumdienst is None and not any(service.running for service in services)
    assert module.baum_lesen()['an'] is False
