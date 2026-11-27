"""Explicit-marker estimates and the actual native reminder projection (#79, #803)."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import random

import pytest

from modul_laden import quellmodul_laden
from test_startup_read_failure import native

m = quellmodul_laden('cycle_calendar_test', Path(__file__).resolve().parents[1] / 'bin/magnolie_cycle.py')


def profile(days, enabled=True):
    return {'zyklusmarker': [{'id': 'light', 'art': 'bleeding-light', 'name': 'Renamed marker'},
                            {'id': 'other', 'art': 'ovulation', 'name': 'Bleeding'}],
            'tagmarken': [{'datum': day, 'zyklusIds': ['light']} for day in days],
            'einstellungen': {'regional': {'timeZone': 'UTC'}, 'kalender': {'zykluskalenderAn': enabled,
                'zyklusErinnerungen': {'prognose': True, 'vorlauf': 2, 'abweichung': True, 'abweichungTage': 7}}}}


def dated_intervals(intervals, start='2026-01-01'):
    days = [date.fromisoformat(start)]
    for interval in intervals:
        days.append(days[-1] + timedelta(days=interval))
    return [day.isoformat() for day in days]


def test_regular_cycles_group_bleeding_days_and_project_one_stable_estimate():
    data = profile(['2026-01-01', '2026-01-02', '2026-01-29', '2026-01-30', '2026-02-26'])
    stats = m.estimate_cycle(data, '2026-03-01')
    assert stats['starts'] == ['2026-01-01', '2026-01-29', '2026-02-26']
    assert stats['length'] == 28 and stats['predicted'] == '2026-03-26'
    assert (stats['windowStart'], stats['windowEnd']) == ('2026-03-24', '2026-03-28')
    assert stats['reason'] == 'ready' and stats['usedIntervals'] == [28, 28]
    reminders = m.cycle_reminders(data, as_of='2026-03-01')
    assert len(reminders) == 1 and reminders[0]['individuelleErinnerungTage'] == 2
    assert reminders[0]['id'] == 'cycle-estimate:2026-02-26:2026-03-26'
    assert reminders == m.cycle_reminders(data, as_of='2026-03-01')
    data['einstellungen']['kalender']['zykluskalenderAn'] = False
    assert m.cycle_reminders(data, as_of='2026-03-01') == []


def test_unusual_latest_interval_uses_earlier_baseline_and_separate_switch():
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26', '2026-04-09'])
    stats = m.estimate_cycle(data, '2026-04-10')
    assert stats['baseline'] == 28 and stats['latest'] == 42
    assert stats['predicted'] == '2026-05-07'
    assert (stats['windowStart'], stats['windowEnd']) == ('2026-05-05', '2026-05-23')
    assert len(m.cycle_reminders(data, as_of='2026-04-10')) == 2
    data['einstellungen']['kalender']['zyklusErinnerungen']['abweichung'] = False
    assert len(m.cycle_reminders(data, as_of='2026-04-10')) == 1


def test_defaults_few_entries_free_text_and_invalid_dates_do_not_invent_forecasts():
    data = profile(['2026-01-01', '2026-01-29'])
    assert m.cycle_reminders(data, as_of='2026-02-01') == []
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26'])
    data['einstellungen']['kalender'].pop('zyklusErinnerungen')
    assert m.cycle_reminders(data, as_of='2026-03-01') == []
    for mark in data['tagmarken']:
        mark['zyklusIds'] = ['other']
    assert not m.estimate_cycle(data, '2026-03-01')['starts']
    assert m.estimate_cycle(profile(['2026-02-30', 'not-a-date']), '2026-03-01')['predicted'] is None


def test_correction_removes_old_estimate_and_year_overflow_is_bounded():
    data = profile(['2026-01-01', '2026-01-29', '2026-02-26'])
    old = m.cycle_reminders(data, as_of='2026-03-01')[0]['id']
    data['tagmarken'][-1]['datum'] = '2026-02-28'
    assert m.cycle_reminders(data, as_of='2026-03-01')[0]['id'] != old
    data['tagmarken'].pop()
    assert m.cycle_reminders(data, as_of='2026-03-01') == []
    overflow = m.estimate_cycle(profile(['9999-11-02', '9999-11-30', '9999-12-28']), '9999-12-31')
    assert overflow['predicted'] is None and overflow['reason'] == 'range'
    assert overflow['windowStart'] is None and overflow['windowEnd'] is None


def test_native_reminder_projection_keeps_only_opted_in_forecast_entries(native):
    # Keep the real native default-date path: synthetic history ends on today's
    # book-local day, so this integration check does not expire with wall time.
    today = date.fromisoformat(m.organizer_today({'einstellungen': {'regional': {'timeZone': 'UTC'}}}))
    data = profile([(today - timedelta(days=offset)).isoformat() for offset in (98, 70, 42, 0)])
    data['einstellungen']['sicherheit'] = {'erinnernTrotzKennwort': True}
    data['einstellungen']['erinnerung'] = {'an': True}
    data['kontakte'] = [{'notiz': 'Synthetic private text not needed by reminders'}]
    projection = native.erinnerungsdaten_auswaehlen(data)
    assert len(projection['termine']) == 2
    assert 'kontakte' not in projection and 'tagmarken' not in projection and 'zyklusmarker' not in projection
    assert all(entry['id'].startswith('cycle-') for entry in projection['termine'])
    data['einstellungen']['kalender']['zyklusErinnerungen'] = {'anzeige': True}
    assert native.erinnerungsdaten_auswaehlen(data)['termine'] == []


@pytest.mark.parametrize('interval', [14, 24, 28, 35, 45, 60])
def test_individual_lengths_use_start_to_start_days(interval):
    days = dated_intervals([interval, interval])
    result = m.estimate_cycle(profile(days), days[-1])
    assert result['length'] == interval and result['reason'] == 'ready'
    assert result['predicted'] == (date.fromisoformat(days[-1]) + timedelta(days=interval)).isoformat()
    assert result['usedIntervals'] == [interval, interval]


@pytest.mark.parametrize('gap', [4, 13, 61, 365])
def test_discontinuous_history_does_not_reuse_old_intervals(gap):
    days = dated_intervals([28, 28, gap])
    result = m.estimate_cycle(profile(days), days[-1])
    assert result['length'] is None and result['usedIntervals'] == []
    assert result['reason'] == 'gap' and result['excludedIntervals'] == 1
    assert result['baseline'] == 28 and result['latest'] == gap
    assert result['predicted'] is None
    # A second new complete interval establishes a fresh history.
    recovered = dated_intervals([28, 28, gap, 30, 32])
    result = m.estimate_cycle(profile(recovered), recovered[-1])
    assert result['length'] == 31 and result['usedIntervals'] == [30, 32]
    assert result['baseline'] is None
    assert result['excludedIntervals'] == 1 and result['reason'] == 'ready'


def test_median_half_rounding_and_limit_of_twelve_recent_intervals():
    days = dated_intervals([14] * 3 + [28, 29] * 6, '2024-01-01')
    result = m.estimate_cycle(profile(days), days[-1])
    assert result['length'] == 29
    assert result['usedIntervals'] == [28, 29] * 6
    assert len(result['intervals']) == 15


@pytest.mark.parametrize(('today', 'overdue'), [('2026-03-23', 0), ('2026-03-24', 0),
    ('2026-03-26', 0), ('2026-03-28', 0), ('2026-03-29', 1), ('2026-04-28', 31)])
def test_estimate_never_rolls_forward_after_window(today, overdue):
    result = m.estimate_cycle(profile(dated_intervals([28, 28])), today)
    assert result['predicted'] == '2026-03-26'
    assert result['windowEnd'] == '2026-03-28' and result['overdueDays'] == overdue


def test_stale_threshold_is_not_a_claim_of_missed_periods():
    data = profile(dated_intervals([28, 28]))
    assert m.estimate_cycle(data, '2026-06-26')['stale'] is False  # exactly 120 days
    stats = m.estimate_cycle(data, '2026-06-27')
    assert stats['stale'] is True and stats['predicted'] == '2026-03-26'
    assert m.cycle_reminders(data, as_of='2026-06-27') == []
    long = dated_intervals([60, 60])
    anchor = date.fromisoformat(long[-1])
    assert not m.estimate_cycle(profile(long), (anchor + timedelta(days=124)).isoformat())['stale']
    assert m.estimate_cycle(profile(long), (anchor + timedelta(days=125)).isoformat())['stale']


def test_future_dates_are_deduplicated_and_do_not_move_the_anchor():
    data = profile(dated_intervals([28, 28]) + ['2026-03-26', '2026-03-26', '2027-01-01'])
    stats = m.estimate_cycle(data, '2026-03-01')
    assert stats['futureIgnored'] == 2 and stats['starts'][-1] == '2026-02-26'
    assert stats['predicted'] == '2026-03-26'
    stats = m.estimate_cycle(data, '2026-03-26')
    assert stats['futureIgnored'] == 1 and stats['starts'][-1] == '2026-03-26'
    assert stats['predicted'] == '2026-04-23' and stats['overdueDays'] == 0


@pytest.mark.parametrize('bad', ['', '2026-2-01', '2026-02-30', '2026-13-01', '0000-01-01',
    '20260101', '2026-W01-1', '2026-01-01T00:00:00Z', '２０２６-01-01', '2026-01-01\n', None, 1, [], {}])
def test_bad_mark_dates_are_ignored(bad):
    data = profile([bad])
    stats = m.estimate_cycle(data, '2026-03-01')
    assert stats['starts'] == [] and stats['futureIgnored'] == 0


@pytest.mark.parametrize('bad', ['', '2026-2-01', '2026-02-30', '0000-01-01', 1, [], {}])
def test_bad_explicit_as_of_is_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        m.estimate_cycle({}, bad)


@pytest.mark.parametrize('bad', [None, [], 1, 'not an object', True,
    {'zyklusmarker': {}}, {'tagmarken': [None, [], 1]},
    {'zyklusmarker': [None, {'id': '', 'art': 'bleeding-light'}, {'id': 'x', 'art': []}],
     'tagmarken': [{'datum': '2026-01-01', 'zyklusIds': ['', 'x']}]},
    {'einstellungen': {'kalender': {'zyklusErinnerungen': []}}}])
def test_malformed_containers_are_safe(bad):
    assert m.estimate_cycle(bad, '2026-03-01')['predicted'] is None
    assert m.cycle_reminders(bad, as_of='2026-03-01') == []


def test_episode_bridging_is_not_counted_as_continuous_bleeding():
    data = profile(dated_intervals([28, 28]) + ['2026-02-27', '2026-03-01', '2026-03-02'])
    stats = m.estimate_cycle(data, '2026-03-02')
    assert stats['starts'] == ['2026-01-01', '2026-01-29', '2026-02-26']
    assert stats['recordedRun'] == 2 and stats['lastBleeding'] == '2026-03-02'
    eight = profile(dated_intervals([28, 28]) + [
        (date(2026, 2, 26) + timedelta(days=n)).isoformat() for n in range(8)])
    assert m.estimate_cycle(eight, '2026-03-05')['recordedRun'] == 8
    eight['tagmarken'].append({'datum': '2026-03-26', 'zyklusIds': ['light']})
    assert m.estimate_cycle(eight, '2026-03-26')['recordedRun'] == 1


def test_recorded_bleeding_overlapping_estimate_suppresses_misleading_forecast():
    days = dated_intervals([14, 14])
    days += [(date.fromisoformat(days[-1]) + timedelta(days=n)).isoformat() for n in range(1, 13)]
    stats = m.estimate_cycle(profile(days), days[-1])
    assert stats['reason'] == 'ongoing' and stats['length'] == 14
    assert stats['predicted'] is None and stats['windowStart'] is None and stats['windowEnd'] is None
    assert m.cycle_reminders(profile(days), as_of=days[-1]) == []


@pytest.mark.parametrize(('starts', 'expected'), [
    (['2028-01-01', '2028-01-29', '2028-02-26'], '2028-03-25'),
    (['2100-01-01', '2100-01-29', '2100-02-26'], '2100-03-26'),
    (['2026-11-10', '2026-12-08', '2027-01-05'], '2027-02-02'),
    (['0001-01-01', '0001-01-29', '0001-02-26'], '0001-03-26')])
def test_gregorian_calendar_boundaries(starts, expected):
    assert m.estimate_cycle(profile(starts), starts[-1])['predicted'] == expected


@pytest.mark.parametrize(('zone', 'expected'), [('UTC', '2026-11-26'), ('Europe/Berlin', '2026-11-26'),
    ('America/Los_Angeles', '2026-11-25'), ('Pacific/Apia', '2026-11-26'), ('Pacific/Kiritimati', '2026-11-26'), ('Z', '2026-11-26')])
def test_book_local_today_does_not_use_utc_date_unconditionally(zone, expected):
    data = {'einstellungen': {'regional': {'timeZone': zone}}}
    assert m.organizer_today(data, datetime(2026, 11, 26, 0, 30, tzinfo=timezone.utc)) == expected


@pytest.mark.parametrize('zone', ['UTC', 'Europe/Berlin', 'America/New_York', 'Pacific/Apia'])
def test_day_arithmetic_is_independent_of_dst_and_zone(zone):
    data = profile(['2026-02-01', '2026-03-01', '2026-03-29'])
    data['einstellungen']['regional']['timeZone'] = zone
    assert m.estimate_cycle(data, '2026-04-01')['predicted'] == '2026-04-26'
    data['tagmarken'] = profile(['2026-08-30', '2026-09-27', '2026-10-25'])['tagmarken']
    assert m.estimate_cycle(data, '2026-10-26')['predicted'] == '2026-11-22'


@pytest.mark.parametrize(('length', 'count'), [(34, 1), (35, 2)])
def test_deviation_threshold_uses_previous_history(length, count):
    days = dated_intervals([28, 28, length])
    assert len(m.cycle_reminders(profile(days), as_of=days[-1])) == count


@pytest.mark.parametrize('value', ['true', 1, {}, [], None])
def test_only_boolean_true_enables_reminders(value):
    data = profile(dated_intervals([28, 28]))
    data['einstellungen']['kalender']['zyklusErinnerungen'] = {'prognose': value, 'abweichung': value, 'anzeige': True}
    assert m.cycle_reminders(data, as_of='2026-03-01') == []


def test_invalid_numeric_options_use_bounded_defaults():
    data = profile(dated_intervals([28, 28, 35]))
    opts = data['einstellungen']['kalender']['zyklusErinnerungen']
    for value in (True, -1, 31, '7', 3.5, None, [], {}):
        opts['vorlauf'] = opts['abweichungTage'] = value
        reminders = m.cycle_reminders(data, as_of='2026-04-02')
        assert len(reminders) == 2 and reminders[0]['individuelleErinnerungTage'] == 1


def test_deterministic_generated_histories_preserve_input_and_observation_invariants():
    rng = random.Random(803)
    for _ in range(250):
        intervals = [rng.randint(14, 60) for _ in range(rng.randint(2, 22))]
        days = dated_intervals(intervals, '2000-01-01')
        data = profile(days)
        before = deepcopy(data)
        stats = m.estimate_cycle(data, days[-1])
        assert data == before
        shuffled = deepcopy(data)
        shuffled['tagmarken'] *= 2
        shuffled['tagmarken'].append({'datum': '1999-01-01', 'zyklusIds': ['other']})
        rng.shuffle(shuffled['tagmarken'])
        assert m.estimate_cycle(shuffled, days[-1]) == stats
        assert stats['windowStart'] <= stats['predicted'] <= stats['windowEnd']
        assert stats['usedIntervals'] == intervals[-12:]
