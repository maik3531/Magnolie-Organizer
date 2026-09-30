"""Jahrestage bleiben unabhängig von Terminen sichtbar; keine echten Meldungen."""
from datetime import datetime
from pathlib import Path
import subprocess

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    return quellmodul_laden('anniversary_dismissal_test', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


@pytest.mark.parametrize('automatic', [None, False, True])
def test_anniversary_lifetime_is_independent_from_appointments(native, monkeypatch, automatic):
    anniversaries = dict(an=True, tage=0, amTag=True, stunde=8)
    if automatic is not None:
        anniversaries['autoAusblenden'] = automatic
    data = dict(termine=[dict(id='appointment', titel='Appointment fixture', datum='2026-09-30', zeit='09:05')],
                jahrestage=[dict(id='birthday', name='Birthday fixture', datum='--09-30', typ='birthday')],
                einstellungen=dict(erinnerung=dict(an=True, art='notification', stil='magnolie',
                    vorlauf=15, jahrestage=anniversaries)))
    monkeypatch.setattr(native, 'daten_lesen_gepuffert', lambda: data)
    monkeypatch.setattr(native, 'sitzungsumgebung_uebernehmen', lambda: None)
    monkeypatch.setattr(native, 'erinnerung_zustand_lesen', lambda: {})
    monkeypatch.setattr(native, 'erinnerung_zustand_schreiben', lambda value: None)
    monkeypatch.setattr(native, 'wecker_notiz', lambda text: None)
    received = []
    monkeypatch.setattr(native, 'melden', lambda title, body, style, **options:
                        received.append((title, body, options)) or 'magnolie')
    result = native.erinnerungslauf(datetime(2026, 9, 30, 9, 0), als_wecker=True)
    assert result['gemeldet'] == 2
    birthday = next(entry for entry in received if 'Birthday fixture' in entry[1])
    appointment = next(entry for entry in received if 'Appointment fixture' in entry[1])
    assert birthday[2].get('wartezeit', 60) == (60 if automatic is True else 0)
    assert appointment[2].get('wartezeit', 60) == 60
    data['einstellungen']['sicherheit'] = {'erinnernTrotzKennwort': True}
    projected = native.erinnerungsdaten_auswaehlen(data)
    if automatic is not None:
        assert projected['einstellungen']['erinnerung']['jahrestage']['autoAusblenden'] is automatic


def test_notify_send_requests_persistent_notification_only_when_selected(native, monkeypatch):
    calls = []
    monkeypatch.setattr(native.shutil, 'which', lambda name: '/usr/bin/notify-send')
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kwargs: calls.append(args))
    assert native.benachrichtigen('Birthday', 'Fixture', wartezeit=0)
    assert '--expire-time=0' in calls[-1] and '--urgency=critical' in calls[-1]
    assert native.benachrichtigen('Appointment', 'Fixture', wartezeit=60)
    assert '--expire-time=0' not in calls[-1] and '--urgency=critical' not in calls[-1]
