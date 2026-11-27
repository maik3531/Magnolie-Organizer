"""A failed background status read retires UI claims and recovers (Refs #760)."""
from copy import deepcopy
from pathlib import Path
from types import MethodType, SimpleNamespace
import sys

import pytest

from modul_laden import quellmodul_laden

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
from magnolie_hintergrund import IPCError

product = quellmodul_laden('phone_status_failure', ROOT / 'bin/magnolie-organizer')


class Phone:
    def __init__(self, error, stage):
        self.error, self.stage = error, stage
        self.live = dict(possible=True, enabled=True, listening=True, port=8741,
            peers=[dict(device_id='synthetic-phone', display_name='Fixture phone', state='online_wifi')],
            media_activity=dict(synchronizing=True, camera=True, mirroring=True))
        self.replayed = 0

    def check(self, stage):
        if self.stage == stage:
            raise self.error('synthetic background failure')

    @property
    def enabled(self):
        self.check('enabled')
        return True

    def report(self):
        self.check('report')
        return deepcopy(self.live)

    def replay_personal_sync(self):
        self.check('replay')
        self.replayed += 1

    def tray_sync_activity(self):
        return {'synchronizing': False}


@pytest.fixture
def status_host(monkeypatch):
    queued, answers, diagnostics = [], [], []
    monkeypatch.setattr(product, '_', lambda text: text)
    monkeypatch.setattr(product, 'debug_ausnahme', lambda event: diagnostics.append(event))
    monkeypatch.setattr(product, '_kdeconnect_backend', lambda *args: None)
    monkeypatch.setattr(product, 'kdeconnect_sms_stand', lambda: {'available': True})
    monkeypatch.setattr(product, 'tray_kde_verbindungsstand', lambda: {'connected': True, 'count': 1})
    monkeypatch.setattr(product, 'GLib', SimpleNamespace(idle_add=lambda callback: queued.append(callback)))
    window = SimpleNamespace(_telefon_fehler='', _gesperrt=False,
        _telefon_dienst_pflegen=lambda: None, _kde_legacy_einstellungen_migrieren=lambda: None,
        _kde_ereignis=lambda *args: None, antwort=lambda *args: answers.append(args),
        _tray_telefone_aktualisieren=lambda: None, _tray_zaehler_anzeigen=lambda: None)
    for name in ('_telefon_bericht', '_tray_medien_aktualisieren'):
        setattr(window, name, MethodType(getattr(product.Fenster, name), window))
    return window, queued, answers, diagnostics


@pytest.mark.parametrize('error', [IPCError, OSError])
@pytest.mark.parametrize('stage', ['report', 'maintenance'])
def test_failed_phone_status_clears_stale_capabilities_and_recovers(status_host, error, stage):
    window, _, _, diagnostics = status_host
    window._telefon = phone = Phone(error, stage)
    window._telefon_dienst_pflegen = lambda: phone.check('maintenance')
    saved = deepcopy(phone.live)

    unavailable = window._telefon_bericht()
    assert unavailable['error'] == 'The phone connection is not available.'
    assert unavailable['possible'] is unavailable['enabled'] is unavailable['listening'] is False
    assert unavailable['peers'] == []
    assert unavailable['kdeconnect'] == {'available': True}
    assert window._telefon is phone and phone.live == saved and window._telefon_fehler == ''
    assert diagnostics

    phone.stage = None
    fresh = window._telefon_bericht()
    assert fresh['possible'] and fresh['enabled'] and fresh['listening']
    assert fresh['peers'] == saved['peers'] and fresh['error'] == ''
    assert window._telefon is phone and phone.live == saved


@pytest.mark.parametrize('error', [IPCError, OSError])
def test_replay_failure_does_not_suppress_status_or_later_tray_refresh(status_host, error):
    window, queued, answers, diagnostics = status_host
    window._telefon = phone = Phone(error, 'replay')
    product.Fenster._telefon_stand_melden(window)
    assert answers[-1][0] == 'App.telefonStand' and answers[-1][1]['listening']
    assert len(queued) == 1 and queued.pop()() is False
    assert window._tray_verbindungen == (True, True) and diagnostics
    phone.stage = None
    product.Fenster._telefon_stand_melden(window)
    assert phone.replayed == 1 and len(answers) == 2 and queued.pop()() is False


@pytest.mark.parametrize('error', [IPCError, OSError])
def test_failed_media_status_retires_phone_icons_but_preserves_other_native_activity(status_host, error):
    window, _, _, diagnostics = status_host
    window._telefon = phone = Phone(error, 'report')
    window._tray_medien = (True, True)
    window._tray_verbindungen = (True, True)
    window._tray_spiegelung = True
    window._sync_laeuft = True
    assert window._tray_medien_aktualisieren() is False
    assert window._tray_medien == (True, False)
    assert window._tray_verbindungen == (False, True)
    assert window._tray_spiegelung is False and diagnostics
    phone.stage = None
    assert window._tray_medien_aktualisieren() is False
    assert window._tray_medien == (True, True)
    assert window._tray_verbindungen == (True, True) and window._tray_spiegelung is True


class Menu:
    def __init__(self): self.items = []
    def append(self, item): self.items.append(item)
    def show_all(self): pass


class Item:
    def __init__(self, label=''): self.label, self.visible, self.submenu = label, True, None
    def connect(self, *args): pass
    def set_visible(self, visible): self.visible = visible
    def set_submenu(self, menu): self.submenu = menu


@pytest.mark.parametrize('error', [IPCError, OSError])
@pytest.mark.parametrize('stage', ['enabled', 'report'])
def test_failed_tray_phone_read_hides_stale_peer_but_keeps_existing_stop_action(status_host, monkeypatch, error, stage):
    window, _, _, diagnostics = status_host
    monkeypatch.setattr(product, 'Gtk', SimpleNamespace(Menu=Menu, MenuItem=Item))
    window._telefon = phone = Phone(error, stage)
    window._tray_telefone = Item()
    window._tray_telefon_verbinden_eintrag = Item()
    window._tray_einstellungen = {}
    window._tray_telefon_zeigen = lambda *args: None
    window._phone_screen_window = SimpleNamespace(available=True, show=lambda: None, stop=lambda: None)

    product.Fenster._tray_telefone_aktualisieren(window)
    assert [item.label for item in window._tray_telefone.submenu.items] == ['Show phone screen', 'Stop screen mirroring']
    assert window._tray_telefone.visible and not window._tray_telefon_verbinden_eintrag.visible
    assert diagnostics
    window._phone_screen_window = None
    product.Fenster._tray_telefone_aktualisieren(window)
    assert not window._tray_telefone.visible and window._tray_telefone.submenu.items == []
    phone.stage = None
    product.Fenster._tray_telefone_aktualisieren(window)
    assert window._tray_telefone.visible
    assert [item.label for item in window._tray_telefone.submenu.items] == ['Fixture phone']


@pytest.mark.parametrize('method,stage', [
    ('_telefon_bericht', 'report'), ('_telefon_stand_melden', 'replay'),
    ('_tray_medien_aktualisieren', 'report'), ('_tray_telefone_aktualisieren', 'enabled')])
def test_status_guards_do_not_hide_unrelated_programming_errors(status_host, method, stage):
    window, _, _, _ = status_host
    window._telefon = Phone(TypeError, stage)
    window._tray_telefone = Item()
    with pytest.raises(TypeError, match='synthetic background failure'):
        getattr(product.Fenster, method)(window)
