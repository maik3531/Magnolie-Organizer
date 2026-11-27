"""Offline stdlib acceptance of #803: shared vectors, production projection and tzdb.

Run with `python3 -m unittest discover -s magnolie-organizer/pruefungen
-p test_cycle_forecast_stdlib.py -v` from the repository root. This deliberately
needs no pytest, GUI, network, user profile or Windows runtime.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'magnolie-organizer/bin'
sys.path.insert(0, str(BIN))
import magnolie_cycle as cycle


def profile(days):
    return {'zyklusmarker': [{'id': 'b', 'art': 'bleeding-light'}, {'id': 'other', 'art': 'ovulation'}],
            'tagmarken': [{'datum': day, 'zyklusIds': ['b']} for day in days],
            'einstellungen': {'regional': {'timeZone': 'UTC'}, 'kalender': {
                'zykluskalenderAn': True, 'zyklusErinnerungen': {
                    'prognose': True, 'abweichung': True, 'vorlauf': 2, 'abweichungTage': 7}}}}


class CycleForecastAcceptanceTests(unittest.TestCase):
    def test_shared_independent_golden_vectors(self):
        vectors = json.loads((ROOT / 'contracts/cycle-forecast-vectors.json').read_text())
        for case in vectors['cases']:
            with self.subTest(case=case['name']):
                result = cycle.estimate_cycle(case['data'], case['asOf'])
                for key, expected in case['expected'].items():
                    self.assertEqual(result[key], expected, key)

    def test_generated_history_invariants(self):
        randomizer = random.Random(803)
        for iteration in range(250):
            with self.subTest(iteration=iteration):
                intervals = [randomizer.randint(14, 60) for _ in range(randomizer.randint(2, 22))]
                days = [date(2000, 1, 1)]
                for interval in intervals:
                    days.append(days[-1] + timedelta(days=interval))
                data = profile([value.isoformat() for value in days])
                before = deepcopy(data)
                stats = cycle.estimate_cycle(data, days[-1].isoformat())
                self.assertEqual(data, before)
                data['tagmarken'] *= 2
                data['tagmarken'].append({'datum': '1999-01-01', 'zyklusIds': ['other']})
                randomizer.shuffle(data['tagmarken'])
                self.assertEqual(cycle.estimate_cycle(data, days[-1].isoformat()), stats)
                self.assertEqual(stats['usedIntervals'], intervals[-12:])
                self.assertLessEqual(stats['windowStart'], stats['predicted'])
                self.assertLessEqual(stats['predicted'], stats['windowEnd'])

    def test_all_bound_timezone_ids_reuse_the_cpython_tzif_reader(self):
        for identifier in cycle._normative_rules()['zones']:
            with self.subTest(zone=identifier):
                self.assertEqual(cycle._normative_zone(identifier).key, identifier)

    def test_bound_rules_reject_damage_and_missing_files_without_host_fallback(self):
        source = ROOT / 'port-adapters/timezones'
        names = ['tzdb-2026egtz.json', 'provenance.json', 'LICENSE-tzdb.txt']
        for damaged in names:
            with self.subTest(resource=damaged), tempfile.TemporaryDirectory(prefix='magnolie-cycle-rules-') as temporary:
                root = Path(temporary)
                target = root / 'web/timezones'
                target.mkdir(parents=True)
                for name in names:
                    (target / name).write_bytes((source / name).read_bytes() + (b' ' if name == damaged else b''))
                cycle._normative_rules.cache_clear()
                try:
                    with mock.patch.object(cycle, '__file__', str(root / 'bin/magnolie_cycle.py')):
                        with self.assertRaises(ValueError):
                            cycle._normative_rules()
                        (target / damaged).unlink()
                        with self.assertRaises(FileNotFoundError):
                            cycle._normative_rules()
                finally:
                    cycle._normative_rules.cache_clear()

    def test_packaged_resource_layout_uses_the_same_bound_rules(self):
        source = ROOT / 'port-adapters/timezones'
        with tempfile.TemporaryDirectory(prefix='magnolie-cycle-layout-') as temporary:
            root = Path(temporary) / 'usr'
            target = root / 'share/magnolie-organizer/web/timezones'
            target.mkdir(parents=True)
            for name in ['tzdb-2026egtz.json', 'provenance.json', 'LICENSE-tzdb.txt']:
                (target / name).write_bytes((source / name).read_bytes())
            cycle._normative_rules.cache_clear()
            try:
                with mock.patch.object(cycle, '__file__', str(root / 'bin/magnolie_cycle.py')):
                    self.assertEqual(cycle._normative_rules()['tzdbVersion'], '2026egtz')
            finally:
                cycle._normative_rules.cache_clear()

    def test_current_calendar_day_uses_normative_rules_and_book_zone(self):
        instant = datetime(2026, 11, 26, 5, 30, tzinfo=timezone.utc)
        for zone, expected in [('America/Winnipeg', '2026-11-26'), ('UTC', '2026-11-26'),
                               ('Europe/Berlin', '2026-11-26'), ('America/Los_Angeles', '2026-11-25'),
                               ('Pacific/Apia', '2026-11-26')]:
            with self.subTest(zone=zone):
                self.assertEqual(cycle.organizer_today({'einstellungen': {'regional': {'timeZone': zone}}}, instant), expected)
        with self.assertRaises(ValueError):
            cycle.organizer_today({'einstellungen': {'regional': {'timeZone': 'Missing/Zone'}}}, instant)

    def test_day_arithmetic_does_not_change_with_regional_zone(self):
        for zone in ['UTC', 'Europe/Berlin', 'America/New_York', 'Pacific/Apia']:
            with self.subTest(zone=zone):
                data = profile(['2026-02-01', '2026-03-01', '2026-03-29'])
                data['einstellungen']['regional']['timeZone'] = zone
                self.assertEqual(cycle.estimate_cycle(data, '2026-04-01')['predicted'], '2026-04-26')
                data['tagmarken'] = profile(['2026-08-30', '2026-09-27', '2026-10-25'])['tagmarken']
                self.assertEqual(cycle.estimate_cycle(data, '2026-10-26')['predicted'], '2026-11-22')

    def test_strict_dates_containers_and_switches(self):
        for value in ['', '2026-2-01', '2026-02-30', '0000-01-01', '20260101', '2026-01-01T00:00Z', 1, [], {}]:
            with self.subTest(as_of=value):
                with self.assertRaises((ValueError, TypeError)):
                    cycle.estimate_cycle({}, value)
        for data in [None, [], 1, True, 'invalid', {'zyklusmarker': {}},
                     {'tagmarken': [None, 3, []]}, {'zyklusmarker': [{'id': 'x', 'art': []}]}]:
            with self.subTest(data=data):
                self.assertIsNone(cycle.estimate_cycle(data, '2026-03-01')['predicted'])
                self.assertEqual(cycle.cycle_reminders(data, as_of='2026-03-01'), [])
        data = profile(['2026-01-01', '2026-01-29', '2026-02-26'])
        for value in ['true', 1, {}, [], None]:
            data['einstellungen']['kalender']['zyklusErinnerungen'] = {'anzeige': True, 'prognose': value, 'abweichung': value}
            self.assertEqual(cycle.cycle_reminders(data, as_of='2026-03-01'), [])

    def test_bounded_pause_suppresses_estimates_and_has_inclusive_end(self):
        data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-04-09'])
        data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = {
            'reason': 'pregnancy', 'startedOn': '2026-03-01', 'until': '2026-12-01'}
        for today in ['2026-03-01', '2026-05-01', '2026-12-01']:
            with self.subTest(today=today):
                result = cycle.estimate_cycle(data, today)
                self.assertTrue(result['paused'])
                self.assertEqual(result['reason'], 'paused')
                self.assertEqual(result['pauseReason'], 'pregnancy')
                self.assertEqual(result['pauseStart'], '2026-03-01')
                self.assertEqual(result['pauseUntil'], '2026-12-01')
                self.assertEqual(result['restartFrom'], '2026-12-02')
                self.assertEqual(result['starts'], [])
                self.assertIsNone(result['predicted'])
                self.assertIsNone(result['baseline'])
                self.assertEqual(cycle.cycle_reminders(data, as_of=today), [])
        expired = cycle.estimate_cycle(data, '2026-12-02')
        self.assertFalse(expired['paused'])
        self.assertEqual(expired['reason'], 'restart')
        self.assertFalse(expired['stale'])
        self.assertEqual(cycle.cycle_reminders(data, as_of='2026-12-02'), [])

    def test_indefinite_pauses_accept_known_reasons_and_ignore_all_unresumed_days(self):
        for reason in ['pregnancy', 'breastfeeding', 'medication', 'menopause', 'other']:
            for has_until in [False, True]:
                with self.subTest(reason=reason, explicit_null=has_until):
                    data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '9999-12-31'])
                    pause = {'reason': reason, 'startedOn': '2026-03-01'}
                    if has_until:
                        pause['until'] = None
                    data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = pause
                    result = cycle.estimate_cycle(data, '2026-11-26')
                    self.assertTrue(result['paused'])
                    self.assertEqual(result['reason'], 'paused')
                    self.assertEqual(result['pauseReason'], reason)
                    self.assertIsNone(result['pauseUntil'])
                    self.assertIsNone(result['restartFrom'])
                    self.assertEqual(result['futureIgnored'], 0)
                    self.assertEqual(result['starts'], [])
                    self.assertEqual(cycle.cycle_reminders(data, as_of='2026-11-26'), [])

    def test_resuming_starts_a_new_history_including_the_manual_resume_day(self):
        data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-04-09', '2026-04-10', '2026-05-08', '2026-06-05'])
        pause = {'reason': 'pregnancy', 'startedOn': '2026-03-01', 'until': '2026-12-01', 'resumedOn': '2026-04-10'}
        data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = pause
        first = cycle.estimate_cycle(data, '2026-04-10')
        self.assertFalse(first['paused'])
        self.assertEqual(first['reason'], 'restart')
        self.assertEqual(first['starts'], ['2026-04-10'])
        self.assertEqual(first['restartFrom'], '2026-04-10')
        self.assertEqual(first['resumedOn'], '2026-04-10')
        self.assertEqual(first['futureIgnored'], 2)
        self.assertIsNone(first['baseline'])
        ready = cycle.estimate_cycle(data, '2026-06-05')
        self.assertEqual(ready['starts'], ['2026-04-10', '2026-05-08', '2026-06-05'])
        self.assertEqual(ready['predicted'], '2026-07-03')
        self.assertEqual(ready['reason'], 'ready')
        self.assertIsNone(ready['baseline'])
        self.assertEqual(len(cycle.cycle_reminders(data, as_of='2026-06-05')), 1)
        pause['reason'] = 'menopause'
        pause['until'] = None
        self.assertEqual(cycle.estimate_cycle(data, '2026-06-05')['predicted'], '2026-07-03')

    def test_future_or_invalid_resume_does_not_end_pause(self):
        data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-04-10'])
        pause = {'reason': 'medication', 'startedOn': '2026-03-01', 'until': None}
        data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = pause
        for value in ['2026-05-01', '2026-02-28', '2026-02-30', '', True, {}, None]:
            with self.subTest(resumedOn=value):
                pause['resumedOn'] = value
                result = cycle.estimate_cycle(data, '2026-04-10')
                self.assertTrue(result['paused'])
                self.assertIsNone(result['resumedOn'])
                self.assertIsNone(result['restartFrom'])
                self.assertEqual(result['starts'], [])

    def test_expired_pause_never_uses_prepause_baseline(self):
        data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-03-01',
                        '2026-12-01', '2026-12-02', '2026-12-30', '2027-01-27'])
        data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = {
            'reason': 'pregnancy', 'startedOn': '2026-03-01', 'until': '2026-12-01'}
        result = cycle.estimate_cycle(data, '2027-01-27')
        self.assertEqual(result['starts'], ['2026-12-02', '2026-12-30', '2027-01-27'])
        self.assertEqual(result['predicted'], '2027-02-24')
        self.assertEqual(result['excludedIntervals'], 0)
        self.assertIsNone(result['baseline'])
        self.assertEqual(len(cycle.cycle_reminders(data, as_of='2027-01-27')), 1)
        data['tagmarken'] = profile(['2026-12-02', '2026-12-12'])['tagmarken']
        self.assertEqual(cycle.estimate_cycle(data, '2026-12-12')['reason'], 'gap')

    def test_invalid_or_not_started_pause_has_no_effect(self):
        data = profile(['2026-01-01', '2026-01-29', '2026-02-26'])
        baseline = cycle.estimate_cycle(data, '2026-03-01')
        cases = [None, [], 'pause', {'reason': 'unknown', 'startedOn': '2026-01-01'},
                 {'reason': 'hormonal-treatment', 'startedOn': '2026-01-01'},
                 {'reason': 'pregnancy', 'startedOn': '2026-02-30'},
                 {'reason': 'pregnancy', 'startedOn': '2026-01-01', 'until': ''},
                 {'reason': 'pregnancy', 'startedOn': '2026-01-01', 'until': True},
                 {'reason': 'pregnancy', 'startedOn': '2026-01-01', 'until': '2025-12-31'},
                 {'reason': 'pregnancy', 'startedOn': '2026-04-01', 'until': None}]
        for pause in cases:
            with self.subTest(pause=pause):
                data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = pause
                self.assertEqual(cycle.estimate_cycle(data, '2026-03-01'), baseline)
        for name in ['pauseReason', 'pauseStart', 'pauseUntil', 'resumedOn', 'restartFrom']:
            self.assertIsNone(baseline[name])
        self.assertFalse(baseline['paused'])

    def test_pause_at_upper_calendar_boundary_has_no_overflow(self):
        data = profile(['9999-11-02', '9999-11-30', '9999-12-28'])
        pause = {'reason': 'other', 'startedOn': '9999-12-01', 'until': '9999-12-31'}
        data['einstellungen']['kalender']['zyklusErinnerungen']['pause'] = pause
        result = cycle.estimate_cycle(data, '9999-12-31')
        self.assertTrue(result['paused'])
        self.assertIsNone(result['restartFrom'])
        self.assertEqual(result['starts'], [])
        pause['resumedOn'] = '9999-12-28'
        result = cycle.estimate_cycle(data, '9999-12-31')
        self.assertFalse(result['paused'])
        self.assertEqual(result['restartFrom'], '9999-12-28')
        self.assertEqual(result['starts'], ['9999-12-28'])
        self.assertEqual(result['reason'], 'restart')

    def test_actual_linux_projection_contains_only_authorized_ephemeral_notices(self):
        # Import the existing product module with GUI unavailable and temporary
        # XDG locations; do not replace the production projection/calculation.
        with tempfile.TemporaryDirectory(prefix='magnolie-cycle-native-') as temporary:
            environment = {name: str(Path(temporary) / name) for name in (
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR')}
            for value in environment.values():
                Path(value).mkdir()
            environment['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/nonexistent-cycle-test'
            with mock.patch.dict(os.environ, environment), mock.patch.dict(sys.modules, {'gi': None}):
                loader = importlib.machinery.SourceFileLoader('cycle_native_acceptance', str(BIN / 'magnolie-organizer'))
                spec = importlib.util.spec_from_loader(loader.name, loader)
                native = importlib.util.module_from_spec(spec)
                sys.modules[loader.name] = native
                try:
                    loader.exec_module(native)
                    today = date.fromisoformat(cycle.organizer_today({'einstellungen': {'regional': {'timeZone': 'UTC'}}}))
                    data = profile([(today - timedelta(days=offset)).isoformat() for offset in [98, 70, 42, 0]])
                    data['einstellungen']['sicherheit'] = {'erinnernTrotzKennwort': True}
                    data['einstellungen']['erinnerung'] = {'an': True}
                    data['kontakte'] = [{'notiz': 'Synthetic private text not needed by reminders'}]
                    before = deepcopy(data)
                    projection = native.erinnerungsdaten_auswaehlen(data)
                    self.assertEqual(len(projection['termine']), 2)
                    self.assertFalse({'kontakte', 'tagmarken', 'zyklusmarker'} & projection.keys())
                    self.assertTrue(all(value['id'].startswith('cycle-') for value in projection['termine']))
                    self.assertEqual(data, before)
                    options = data['einstellungen']['kalender']['zyklusErinnerungen']
                    options['pause'] = {'reason': 'pregnancy', 'startedOn': today.isoformat(), 'until': None}
                    self.assertEqual(native.erinnerungsdaten_auswaehlen(data)['termine'], [])
                    options.pop('pause')
                    data['einstellungen']['kalender']['zyklusErinnerungen'] = {'anzeige': True}
                    self.assertEqual(native.erinnerungsdaten_auswaehlen(data)['termine'], [])
                    data['einstellungen']['sicherheit']['erinnernTrotzKennwort'] = False
                    self.assertIsNone(native.erinnerungsdaten_auswaehlen(data))
                finally:
                    sys.modules.pop(loader.name, None)


if __name__ == '__main__':
    unittest.main()
