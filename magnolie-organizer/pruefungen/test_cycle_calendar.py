"""Synthetic explicit-marker cycles and opt-in reminder projection (#79)."""
from pathlib import Path
from modul_laden import quellmodul_laden
from test_startup_read_failure import native

m = quellmodul_laden('cycle_calendar_test', Path(__file__).resolve().parents[1] / 'bin/magnolie_cycle.py')


def profile(days, enabled=True):
    return {'zyklusmarker': [{'id': 'light', 'art': 'bleeding-light', 'name': 'Renamed marker'},
                            {'id': 'other', 'art': 'ovulation', 'name': 'Bleeding'}],
            'tagmarken': [{'datum': day, 'zyklusIds': ['light']} for day in days],
            'einstellungen': {'kalender': {'zykluskalenderAn': enabled,
                'zyklusErinnerungen': {'prognose': True, 'vorlauf': 2, 'abweichung': True, 'abweichungTage': 7}}}}


def test_regular_cycles_group_bleeding_days_and_project_one_stable_estimate():
    data = profile(['2026-01-01', '2026-01-02', '2026-01-29', '2026-01-30', '2026-02-26'])
    stats = m.estimate_cycle(data)
    assert stats['starts'] == ['2026-01-01', '2026-01-29', '2026-02-26']
    assert stats['length'] == 28 and stats['predicted'] == '2026-03-26'
    reminders = m.cycle_reminders(data)
    assert len(reminders) == 1 and reminders[0]['individuelleErinnerungTage'] == 2
    assert reminders == m.cycle_reminders(data)
    data['einstellungen']['kalender']['zykluskalenderAn'] = False
    assert m.cycle_reminders(data) == []


def test_unusual_latest_interval_uses_earlier_baseline_and_separate_switch():
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-04-09'])
    stats = m.estimate_cycle(data)
    assert stats['baseline'] == 28 and stats['latest'] == 42
    assert stats['predicted'] == '2026-05-07'
    assert len(m.cycle_reminders(data)) == 2
    data['einstellungen']['kalender']['zyklusErinnerungen']['abweichung'] = False
    assert len(m.cycle_reminders(data)) == 1


def test_defaults_few_entries_free_text_and_invalid_dates_do_not_invent_forecasts():
    data = profile(['2026-01-01', '2026-01-29'])
    assert m.cycle_reminders(data) == []
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26'])
    data['einstellungen']['kalender'].pop('zyklusErinnerungen')
    assert m.cycle_reminders(data) == []
    for mark in data['tagmarken']: mark['zyklusIds'] = ['other']
    assert not m.estimate_cycle(data)['starts']
    assert m.estimate_cycle(profile(['2026-02-30', 'not-a-date']))['predicted'] is None


def test_correction_removes_old_estimate_and_year_overflow_is_bounded():
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26'])
    old = m.cycle_reminders(data)[0]['id']
    data['tagmarken'][-1]['datum'] = '2026-02-28'
    assert m.cycle_reminders(data)[0]['id'] != old
    assert m.estimate_cycle(profile(['9999-11-02', '9999-11-30', '9999-12-28']))['predicted'] is None


def test_native_reminder_projection_keeps_only_opted_in_forecast_entries(native):
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-04-09'])
    data['einstellungen']['sicherheit'] = {'erinnernTrotzKennwort': True}
    data['einstellungen']['erinnerung'] = {'an': True}
    data['kontakte'] = [{'notiz': 'Synthetic private text not needed by reminders'}]
    projection = native.erinnerungsdaten_auswaehlen(data)
    assert len(projection['termine']) == 2
    assert 'kontakte' not in projection and 'tagmarken' not in projection and 'zyklusmarker' not in projection
    assert all(entry['id'].startswith('cycle-') for entry in projection['termine'])
