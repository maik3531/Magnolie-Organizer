"""Original-program inclusive-date presentation with lossless local clocks (#609)."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
from test_or6_import import rotate, blocks
from test_or6_planner import field, selected, fixture as ordinary_fixture
from test_or6_extensions import fixture as extension_fixture
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _string

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-planner-boundaries.json').read_text())
PREFIX = 'X-MAGNOLIE-OR6-PLANNER-LOCAL-'


def fixture():
    item = CONTRACT['file']
    raw = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    return raw


def source_properties(expected):
    return [PREFIX + 'START:' + expected['sourceStart'], PREFIX + 'END:' + expected['sourceEnd']]


def test_verified_planner_boundary_cases_keep_inclusive_days_and_exact_local_clocks():
    raw = fixture(); result = read_or6(raw); items = selected(raw)
    assert result['uebersprungen'] == 0 and len(items) == 17
    for expected in CONTRACT['expected']:
        item = items[expected['title']]
        assert (item['datum'], item['endDatum'], item['zeit'], item['endZeit']) == (expected['date'], expected['endDate'], '', '')
        assert (item['kategorien'], item['akzentFarbe']) == (expected['category'], expected['color'])
        assert item['icsRoundtrip'] == source_properties(expected)
        assert not any(line.startswith(('DTSTART', 'DTEND', 'RRULE', 'RDATE', 'RECURRENCE-ID')) for line in item['icsRoundtrip'])
    ordinary = read_or6(ordinary_fixture())
    expected_titles = {item['title'] for item in CONTRACT['expected']}
    assert [item for item in ordinary['termine'] if item['titel'] not in expected_titles] == [item for item in result['termine'] if item['titel'] not in expected_titles]
    for key in ('kontakte', 'notizen', 'aufgaben', 'jahrestage', 'geburtstage'):
        assert ordinary[key] == result[key]


def test_actual_calendar_export_reimport_retains_display_dates_and_source_clock(native):
    items = selected(fixture())
    for expected in CONTRACT['expected']:
        item = items[expected['title']]
        text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + '\r\n'.join(native._vevent_zeilen(item)) + '\r\nEND:VCALENDAR\r\n'
        imported, = native.ics_lesen(text)['termine']
        assert imported['datum'] == expected['date'] and imported['endDatum'] == expected['endDate']
        assert imported['zeit'] == imported['endZeit'] == ''
        assert set(source_properties(expected)).issubset(imported['icsRoundtrip'])
        assert imported['akzentFarbe'] == expected['color'] and imported['kategorien'] == expected['category']


@pytest.mark.parametrize('mutation', ('reversed-clock', 'reversed-date', 'reserved-start', 'reserved-end', 'fractional-hour', 'repeat', 'confidential'))
def test_clock_support_does_not_remove_existing_safety_guards(mutation):
    raw = fixture(); data = rotate(raw, True)
    reference = next(entry[3] for entry in _Document(raw).entries() if entry[0] == 0x200 and _string(entry[1], 9) == 'OR6-568 B01 palette')
    owner = next(at for at, tag, _ in blocks(data) if tag == 0x200 and struct.unpack_from('<II', data, at+12) == reference)
    _, _, start = field(data, owner, 7); _, _, end = field(data, owner, 8)
    if mutation == 'reversed-clock':
        data[end+4] = 7
    elif mutation == 'reversed-date':
        data[end+3] = 3
    elif mutation == 'reserved-start':
        data[start+7] = 1
    elif mutation == 'reserved-end':
        data[end+7] = 1
    elif mutation == 'fractional-hour':
        data[start+5] = 15
    else:
        entry, _, _ = field(data, owner, 19)
        struct.pack_into('<H', data, entry, 10 if mutation == 'repeat' else 1)
    encoded = rotate(data, False); result = read_or6(encoded)
    assert result['uebersprungen'] == 1 and len(selected(encoded)) == 16
    assert 'OR6-568 B01 palette' not in selected(encoded)


def test_anniversary_does_not_acquire_planner_clock_semantics():
    raw = extension_fixture('sections-corrected-222.or6'); data = rotate(raw, True)
    reference = next(entry[3] for entry in _Document(raw).entries() if entry[0] == 0x600 and _string(entry[1], 9))
    owner = next(at for at, tag, _ in blocks(data) if tag == 0x600 and struct.unpack_from('<II', data, at+12) == reference)
    _, _, start = field(data, owner, 7); _, _, end = field(data, owner, 8)
    data[start+4] = 8; data[end+4] = 18; data[start+5] = data[end+5] = data[start+6] = data[end+6] = 0
    result = read_or6(rotate(data, False))
    assert result['jahrestage'] == [] and result['uebersprungen'] == 1
