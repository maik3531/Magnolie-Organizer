"""Genuine original single/weekly appointment categories, not a guessed enum (#613)."""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from test_or6_import import native_fixture
from test_or6_import import rotate, blocks
from test_or6_planner import field
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _number, _string
from magnolie_recurrence import expand_calendar

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-appointment-categories.json').read_text())


def fixture(name):
    meta = CONTRACT['files'][name]
    raw = gzip.decompress(base64.b64decode(meta['gzip_base64'], validate=True))
    assert len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256']
    return raw


@pytest.mark.parametrize('name', CONTRACT['files'])
def test_single_and_uniform_weekly_native_categories_survive_calendar_roundtrip(name, native):
    expected = CONTRACT['expected']; result = read_or6(fixture(name))
    item, = [item for item in result['termine'] if item['titel'] == expected['title']]
    assert result['uebersprungen'] == 0 and item.get('kategorien') == expected['category']
    assert item['zeit'] == expected['startTime'] and item['endZeit'] == expected['endTime']
    def dates(item):
        values = expand_calendar(item, datetime(2026, 10, 1), datetime(2026, 12, 1), timezone.utc)
        return [item['datum']] if values is None else [start.strftime('%Y-%m-%d') for start, *_ in values]
    assert dates(item) == expected['datesByFile'][name]
    text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + '\r\n'.join(native._vevent_zeilen(item)) + '\r\nEND:VCALENDAR\r\n'
    imported, = native.ics_lesen(text)['termine']
    assert imported['kategorien'] == expected['category'] and dates(imported) == expected['datesByFile'][name]
    assert imported['zeit'] == expected['startTime'] and imported['endZeit'] == expected['endTime']
    basis = read_or6(native_fixture())
    for key in ('kontakte', 'notizen', 'aufgaben', 'jahrestage', 'geburtstage'):
        assert result[key] == basis[key]


def test_absent_native_appointment_category_stays_absent():
    item, = read_or6(native_fixture())['termine']
    assert not item.get('kategorien') and not item.get('akzentFarbe')


def test_different_category_on_one_series_member_is_not_spread_to_the_whole_set():
    raw = fixture('appointment-category-final-v1-613.or6'); doc = _Document(raw); data = rotate(raw, True)
    last = max((entry for entry in doc.entries() if entry[0] == 0x100 and _string(entry[1], 9) == CONTRACT['expected']['title']), key=lambda entry: _number(entry[1], 14))
    owner = next(at for at, tag, _ in blocks(data) if tag == 0x100 and doc.reference(at+12) == last[3])
    _, length, at = field(data, owner, 3)
    source = bytes(data[at:at+length]); changed = source.replace('Work'.encode('utf-16le'), 'Home'.encode('utf-16le'))
    assert changed != source and len(changed) == length
    data[at:at+length] = changed
    result = read_or6(rotate(data, False))
    selected = [item for item in result['termine'] if item['titel'] == CONTRACT['expected']['title']]
    assert result['uebersprungen'] == 0 and len(selected) == 2
    master, = [item for item in selected if not any(line.startswith('RECURRENCE-ID:') for line in item['icsRoundtrip'])]
    child, = [item for item in selected if any(line.startswith('RECURRENCE-ID:') for line in item['icsRoundtrip'])]
    assert master['kategorien'] == 'OR6-613 Work' and child['kategorien'] == 'OR6-613 Home'
    assert 'RECURRENCE-ID:20261107T101500' in child['icsRoundtrip']
