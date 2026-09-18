"""Embedded zones through the real codecs, schedulers, UI and own ICS exports."""
import json
import copy
import hashlib
import struct
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from test_recurrence_integration import CONTRACTS, m, native, check_cross_language, test_launcher_codec_and_window_partitions as check_native
from magnolie_recurrence import calendar_zones, timezone_definition

FIXTURES = json.loads((CONTRACTS / 'recurrence-timezones.json').read_text())


@pytest.mark.parametrize('test', FIXTURES, ids=lambda t: t['name'])
def test_native_timezone_consumers(test):
    check_native(test)
    _, items = native(test)
    lower, upper = (datetime.fromisoformat(test[k].replace('Z', '+00:00')) for k in ('lower', 'upper'))
    values = sorted((v for item in items for v in m._ics_vorkommen(item, lower, upper, aufgabe=test.get('task', False))),
                    key=lambda v: v.get('startDatum', v.get('datum')))
    if 'expectedTitles' in test:
        assert [v['titel'] for v in values] == test['expectedTitles']
        assert [v.get('ort') or next(text for name, _, text in m.ics_properties(v['icsRoundtrip']) if name == 'LOCATION') for v in values] == test['expectedLocations']


@pytest.mark.parametrize('zone', ['Europe/Berlin', 'Australia/Lord_Howe', 'Pacific/Apia', 'America/New_York', 'Africa/Casablanca', 'America/Santiago', 'UTC'])
def test_own_timezone_history_and_unbounded_future(zone):
    definition = timezone_definition(zone)
    embedded = calendar_zones([definition])(zone)
    system = ZoneInfo(zone)
    for year in (1900, 1970, 1998, 2011, 2026, 2040, 2100, 2400):
        for month in range(1, 13):
            value = datetime(year, month, 15, 12, 34, 56, tzinfo=timezone.utc)
            assert value.astimezone(embedded).replace(tzinfo=None) == value.astimezone(system).replace(tzinfo=None), (zone, value)


@pytest.mark.parametrize('clock', ['-1', '24', '26'])
def test_posix_extended_clocks_are_folded_by_public_export(monkeypatch, clock):
    header = b'TZif2' + bytes(15) + struct.pack('>6I', 0, 0, 0, 1, 1, 4)
    stamp = int(datetime(2037, 1, 1, tzinfo=timezone.utc).timestamp())
    info = b'\0' + struct.pack('>iBB', 0, 0, 0) + b'STD\0'
    data = (header + struct.pack('>i', stamp) + info + header + struct.pack('>q', stamp) + info +
            ('\nSTD0DST,M3.2.0/' + clock + ',M11.1.0/' + clock + '\n').encode('ascii'))
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_bytes', lambda self: data)
        definition = timezone_definition.__wrapped__('Europe/Berlin')
    dates = [line for line in definition if line.startswith('RDATE:')]
    assert len(dates) == 2 and all(len(line.split(',')) > 7900 for line in dates)
    monkeypatch.setitem(m._REGIONAL, 'timeZone', 'Europe/Berlin')
    monkeypatch.setattr(m, 'timezone_definition', lambda tzid: definition)
    exported = m.ics_schreiben_termine([{'uid': 'footer-fixture', 'titel': 'Footer',
        'datum': '2026-07-01', 'zeit': '09:00', 'endZeit': '10:00',
        'wiederholung': {'art': 'yearly'}}])
    assert '\r\n ' in exported
    assert max(len(line.encode('utf-8')) for line in exported.split('\r\n')) <= 75
    assert [line for line in m._entfalte_zeilen(exported) if line.startswith('RDATE:')] == dates


def cross_language_timezone_differential_and_own_linux_export():
    fixtures = list(FIXTURES)
    collision = copy.deepcopy(next(t for t in FIXTURES if t['name'] == 'separate-calendar-tzid-collision'))
    a, b = collision['components'], collision['additionalCalendars'][0]
    alias = 'Magnolie/' + hashlib.sha256('\n'.join(a[0]).encode()).hexdigest()
    b = [[line.replace('Europe/Berlin', alias) for line in block] for block in b]
    collision.update(name='colliding-generated-tzid', components=b, additionalCalendars=[a, collision['additionalCalendars'][1]])
    fixtures.append(collision)
    for zone, expected in [('Europe/Berlin', '07:00:00'), ('Australia/Lord_Howe', '22:30:00')]:
        m._REGIONAL['timeZone'] = zone
        own = m.ics_schreiben_termine([{'uid': 'own-' + zone, 'titel': 'Own recurring export', 'datum': '2026-07-01', 'zeit': '09:00', 'endZeit': '10:00', 'wiederholung': {'art': 'yearly'}}])
        blocks, current = [], []
        for line in m._entfalte_zeilen(own):
            if line in ('BEGIN:VTIMEZONE', 'BEGIN:VEVENT'):
                current = []
            if current or line in ('BEGIN:VTIMEZONE', 'BEGIN:VEVENT'):
                current.append(line)
            if line in ('END:VTIMEZONE', 'END:VEVENT'):
                blocks.append(current)
                current = []
        start = datetime.fromisoformat('2040-07-01T' + expected) - (timedelta(days=1) if zone == 'Australia/Lord_Howe' else timedelta())
        fixtures.append({'name': 'own-linux-future-' + zone, 'zone': 'UTC', 'lower': '2040-06-30T00:00:00Z', 'upper': '2040-07-02T23:59:59Z',
            'components': blocks, 'roundtrip': True, 'expected': [start.isoformat() + '/' + (start + timedelta(hours=1)).isoformat()]})
    check_cross_language(fixtures)


def test_native_next_wakeup_seeks_beyond_a_year():
    m._REGIONAL['timeZone'] = 'UTC'
    data = m.ics_lesen('BEGIN:VEVENT\nUID:next-biennial\nSUMMARY:Every other year\nDTSTART:20260105T090000Z\nDURATION:PT1H\nRRULE:FREQ=YEARLY;INTERVAL=2;COUNT=3\nEND:VEVENT')
    assert m.naechster_weckzeitpunkt(data, datetime(2026, 2, 1), vorlauf=15) == datetime(2028, 1, 5, 8, 45)
    assert m.naechster_weckzeitpunkt(data, datetime(2031, 1, 1), vorlauf=15) is None


def test_unreferenced_invalid_definition_does_not_poison_calendar():
    m._REGIONAL['timeZone'] = 'UTC'
    data = m.ics_lesen('BEGIN:VCALENDAR\nBEGIN:VTIMEZONE\nTZID:Unused\nBEGIN:STANDARD\nDTSTART:19700101T000000\nEND:STANDARD\nEND:VTIMEZONE\nBEGIN:VEVENT\nUID:independent\nSUMMARY:Independent\nDTSTART:20260907T090000Z\nDURATION:PT1H\nRRULE:FREQ=DAILY;COUNT=2\nEND:VEVENT\nEND:VCALENDAR')
    assert len(m._ics_vorkommen(data['termine'][0], datetime(2026, 9, 7), datetime(2026, 9, 9))) == 2


def cross_language_448_windows_oracles():
    from dateutil.rrule import rrulestr
    from test_recurrence_oracle import CASES, MATRIX
    fixtures = []
    lower, upper = (datetime.fromisoformat(MATRIX[key]) for key in ('lower', 'upper'))
    for index, (anchor, rule, ending) in enumerate(CASES):
        start = datetime.fromisoformat(anchor)
        expected = rrulestr(rule + ending, dtstart=start).between(lower, upper, inc=True)
        wire_rule = rule + ending + ('Z' if 'UNTIL=' in ending else '')
        fixtures.append({'name': 'frozen-oracle-' + str(index), 'oracle': True, 'zone': 'UTC', 'lower': MATRIX['lower'] + 'Z', 'upper': MATRIX['upper'] + 'Z',
            'components': [['BEGIN:VEVENT', 'UID:oracle-' + str(index), 'SUMMARY:Oracle', 'DTSTART:' + start.strftime('%Y%m%dT%H%M%SZ'), 'DURATION:PT1H', 'RRULE:' + wire_rule, 'END:VEVENT']],
            'expected': [v.isoformat() + '/' + (v + timedelta(hours=1)).isoformat() for v in expected]})
    check_cross_language(fixtures)
