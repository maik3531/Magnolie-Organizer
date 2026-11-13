"""Independent native Calendar later-segment extension, not a Task oracle (#616)."""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
from test_or6_import import rotate, blocks
from test_or6_planner import field
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _number, _stamp, _calendar_history_series
from magnolie_recurrence import expand_calendar

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-calendar-history.json').read_text())


def fixture():
    meta = next(iter(CONTRACT['files'].values()))
    raw = gzip.decompress(base64.b64decode(meta['gzip_base64'], validate=True))
    assert len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256']
    return raw


def group():
    doc = _Document(fixture()); entries = list(doc.entries(repeats=True))
    return doc, next(iter(doc.repeat_groups(entries).values()))


def test_original_calendar_history_preserves_all_four_dates_and_current_template_roundtrip(native):
    doc, source = group(); expected = CONTRACT['expected']
    ordered = sorted(source[1], key=lambda member: _stamp(member[1][7]))
    assert [_number(member[1], 14) for member in ordered] == expected['indices']
    assert len(source[0][1][12]) == 16
    result = read_or6(fixture()); item, = result['termine']
    assert result['uebersprungen'] == 0 and item['uid'] == expected['definitionUid']
    assert item['kategorien'] == expected['category'] and item['zeit'] == expected['startTime'] and item['endZeit'] == expected['endTime']
    def dates(item):
        return [start.strftime('%Y-%m-%d') for start, *_ in expand_calendar(item, datetime(2026, 10, 1), datetime(2026, 12, 1), timezone.utc)]
    assert dates(item) == expected['dates']
    assert 'X-MAGNOLIE-OR6-CALENDAR-TEMPLATE-STARTS:' + ','.join(expected['currentTemplateStarts']) in item['icsRoundtrip']
    text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + '\r\n'.join(native._vevent_zeilen(item)) + '\r\nEND:VCALENDAR\r\n'
    reread, = native.ics_lesen(text)['termine']
    assert dates(reread) == expected['dates'] and reread['kategorien'] == expected['category']
    for line in item['icsRoundtrip']:
        if line.startswith('X-MAGNOLIE-OR6-CALENDAR-TEMPLATE-'):
            assert line in reread['icsRoundtrip']


@pytest.mark.parametrize('mutation', ('history-index', 'current-index', 'history-busy', 'duplicate-date', 'before-anchor', 'different-duration'))
def test_calendar_history_does_not_guess_ambiguous_indices_or_unexplained_content(mutation):
    doc, source = group(); data = rotate(fixture(), True)
    ordered = sorted(source[1], key=lambda member: _stamp(member[1][7]))
    owners = [next(at for at, tag, _ in blocks(data) if tag == 0x100 and doc.reference(at+12) == member[3]) for member in ordered]
    if mutation in ('history-index', 'current-index'):
        owner = owners[1] if mutation == 'history-index' else owners[-1]
        _, _, at = field(data, owner, 14); struct.pack_into('<I', data, at, 99)
    elif mutation == 'history-busy':
        _, _, at = field(data, owners[0], 15); data[at] ^= 1
    elif mutation == 'duplicate-date':
        for fid in (7, 8):
            _, _, at = field(data, owners[1], fid); _, _, source_at = field(data, owners[0], fid)
            data[at:at+8] = data[source_at:source_at+8]
    elif mutation == 'before-anchor':
        for fid in (7, 8):
            _, _, at = field(data, owners[0], fid); data[at+3] = 23
    else:
        _, _, at = field(data, owners[0], 8); data[at+4] = 12
    result = read_or6(rotate(data, False))
    assert result['termine'] == [] and result['uebersprungen'] == 4


def test_active_unlinked_current_slot_is_not_guessed_deleted():
    doc, source = group()
    last = max(source[1], key=lambda member: _stamp(member[1][7]))
    partial = (source[0], [member for member in source[1] if member is not last])
    recovered = _calendar_history_series(partial, set(), doc.schemas)
    assert recovered is not None and 'EXDATE:20261114T101500' in recovered[0]['icsRoundtrip']
    assert _calendar_history_series(partial, {(last[4], 1, _stamp(last[1][7]))}, doc.schemas) is None
