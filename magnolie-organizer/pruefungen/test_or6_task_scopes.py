"""Genuine original-program scoped task edits with reused segment indices (#567)."""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
from test_or6_import import rotate, blocks
from magnolie_or6 import _Document, _number, read_or6
from magnolie_recurrence import expand_calendar
from test_or6_planner import field
from test_startup_read_failure import native

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-task-scopes.json').read_text())


def fixture(name):
    meta = CONTRACT['files'][name]
    raw = gzip.decompress(base64.b64decode(meta['gzip_base64'], validate=True))
    assert len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256']
    return raw


def selected(result):
    return [item for item in result['aufgaben'] if item['titel'] == CONTRACT['expected']['title']]


def occurrences(items):
    values = {}
    for item in items:
        for start, *_ in expand_calendar(item, datetime(2026, 12, 1), datetime(2027, 1, 1), timezone.utc, task=True):
            date = start.strftime('%Y-%m-%d')
            assert date not in values, 'Linked historical occurrences were duplicated'
            values[date] = (item['erledigt'], item.get('kategorien', ''))
    return values


@pytest.mark.parametrize('name', CONTRACT['files'])
def test_original_scoped_category_and_completed_history_remain_exact_task_occurrences(name, native):
    raw = fixture(name); result = read_or6(raw); items = selected(result)
    expected = CONTRACT['expected']
    assert result['uebersprungen'] == 0 and len(items) == 3
    values = occurrences(items)
    assert sorted(values) == expected['datesByFile'][name]
    for date, (completed, category) in values.items():
        assert completed == (date in expected['completedDates'])
        assert category == expected['categoryByDate'][date]
    base, = [item for item in items if not any(line.startswith('RECURRENCE-ID:') for line in item['icsRoundtrip'])]
    assert base['uid'] == 'or6:0001b2d5:0000040e'
    assert any(line.startswith('RRULE:FREQ=WEEKLY;') for line in base['icsRoundtrip'])
    assert len({item['uid'] for item in items}) == 3
    exported = native.ics_schreiben_aufgaben(items)
    assert exported.count('BEGIN:VTODO') == 3 and 'BEGIN:VEVENT' not in exported
    assert occurrences(selected(native.ics_lesen(exported))) == values


def test_original_extended_segment_really_reuses_indices_without_replacing_earlier_links():
    doc = _Document(fixture('task-scoped-reopened4-567.or6')); entries = list(doc.entries(repeats=True))
    group = next(group for group in doc.repeat_groups(entries).values() if group[0][2] == 'or6:0001b2d5:0000040e')
    ordered = sorted(group[1], key=lambda entry: entry[1][7])
    assert [_number(entry[1], 14) for entry in ordered] == [0, 1, 0, 1]
    assert len(group[0][1][12]) // 8 == 2 and len(group[1]) == 4


@pytest.mark.parametrize('mutation', ('duplicate-date', 'current-index', 'historical-before-anchor', 'history-title', 'history-duration', 'unknown-state'))
def test_scoped_projection_never_guesses_ambiguous_history_or_changed_content(mutation):
    raw = fixture('task-scoped-reopened4-567.or6'); doc = _Document(raw); data = rotate(raw, True)
    entries = list(doc.entries(repeats=True)); group = next(group for group in doc.repeat_groups(entries).values() if group[0][2] == 'or6:0001b2d5:0000040e')
    ordered = sorted(group[1], key=lambda entry: entry[1][7])
    def owner(entry):
        return next(at for at, tag, _ in blocks(data) if tag == 0x300 and doc.reference(at+12) == entry[3])
    first = owner(ordered[0]); last = owner(ordered[-1])
    if mutation == 'duplicate-date':
        for fid in (7, 8):
            _, _, x = field(data, first, fid); _, _, y = field(data, owner(ordered[1]), fid)
            data[y:y+8] = data[x:x+8]
    elif mutation == 'current-index':
        _, _, at = field(data, last, 14); struct.pack_into('<I', data, at, 99)
    elif mutation == 'historical-before-anchor':
        for fid in (7, 8):
            _, _, at = field(data, first, fid); data[at+2] = 11
    elif mutation == 'history-title':
        _, _, at = field(data, first, 9); data[at] = ord('X')
    elif mutation == 'history-duration':
        _, _, at = field(data, first, 8); data[at+4] = 19
    else:
        _, _, at = field(data, first, 20); struct.pack_into('<I', data, at, 99)
    result = read_or6(rotate(data, False))
    assert not selected(result) and result['uebersprungen'] == 4
