"""Independent native Calendar Just-this-one slot evidence (#614)."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from test_or6_import import rotate, blocks
from test_or6_planner import field
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _string, _finite_calendar_series, _stamp

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-appointment-overrides.json').read_text())


def fixture(name):
    meta = CONTRACT['files'][name]
    raw = gzip.decompress(base64.b64decode(meta['gzip_base64'], validate=True))
    assert len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256']
    return raw


@pytest.mark.parametrize('name', list(CONTRACT['files'])[:2])
def test_original_slot_is_not_replaced_by_actual_moved_datetime(name, native):
    result = read_or6(fixture(name)); expected = CONTRACT['expected']
    assert result['uebersprungen'] == 0
    master, = [item for item in result['termine'] if item['uid'] == expected['definitionUid']]
    moved, = [item for item in result['termine'] if item['uid'] == expected['movedUid']]
    assert 'EXDATE:' + expected['originalSlot'] in master['icsRoundtrip']
    assert 'RECURRENCE-ID:' + expected['originalSlot'] in moved['icsRoundtrip']
    assert 'DTSTART:' + expected['movedStart'] in moved['icsRoundtrip']
    assert 'DTEND:' + expected['movedEnd'] in moved['icsRoundtrip']
    assert (moved['datum'], moved['zeit'], moved['endZeit']) == ('2026-11-01', '14:30', '16:00')
    if 'clock-content' in name:
        changed, = [item for item in result['termine'] if item['uid'] == expected['changedUid']]
        assert changed['titel'] == expected['changedTitle'] and changed['kategorien'] == expected['changedCategory']
        assert 'RECURRENCE-ID:20261107T101500' in changed['icsRoundtrip']
    text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + '\r\n'.join(line for item in result['termine'] for line in native._vevent_zeilen(item)) + '\r\nEND:VCALENDAR\r\n'
    reread = native.ics_lesen(text)['termine']
    child, = [item for item in reread if 'RECURRENCE-ID:' + expected['originalSlot'] in item.get('icsRoundtrip', [])]
    assert (child['datum'], child['zeit'], child['endZeit']) == ('2026-11-01', '14:30', '16:00')
    assert 'X-MAGNOLIE-OR6-OBJECT-UID:' + expected['movedUid'] in child['icsRoundtrip']


def test_genuine_pencil_busy_difference_remains_guarded():
    result = read_or6(fixture('appointment-overrides-reopened-v1-614.or6'))
    assert result['termine'] == [] and result['uebersprungen'] == 3


@pytest.mark.parametrize('kind', (3, 0x2002, None))
def test_absent_zero_requires_exact_calendar_uint32_declaration(kind):
    doc = _Document(fixture('appointment-one-moved-v1-614.or6'))
    entries = list(doc.entries(repeats=True)); group = next(iter(doc.repeat_groups(entries).values()))
    for member in group[1]:
        declarations = doc.schemas[member[4]][1]
        if kind is None:
            declarations.pop(14, None)
        else:
            declarations[14] = kind
    assert _finite_calendar_series(group, set(), doc.schemas) is None


def test_missing_original_slot_stays_excluded_and_active_orphan_blocks_conversion():
    doc = _Document(fixture('appointment-overrides-clock-content-reopened-v1-614.or6'))
    entries = list(doc.entries(repeats=True)); group = next(iter(doc.repeat_groups(entries).values()))
    removed = next(member for member in group[1] if member[2] == CONTRACT['expected']['changedUid'])
    partial = (group[0], [member for member in group[1] if member is not removed])
    converted = _finite_calendar_series(partial, set(), doc.schemas)
    assert converted is not None and len(converted) == 2
    assert 'EXDATE:20261107T101500' in converted[0]['icsRoundtrip']
    orphaned = {(removed[4], 2, _stamp(group[0][1][12][16:24]))}
    assert _finite_calendar_series(partial, orphaned, doc.schemas) is None


@pytest.mark.parametrize('mutation', ('bad-index-width', 'duplicate-index', 'unknown-field', 'empty-category'))
def test_unknown_or_ambiguous_overrides_are_not_normalized_away(mutation):
    import struct
    raw = fixture('appointment-overrides-clock-content-reopened-v1-614.or6')
    doc = _Document(raw); data = rotate(raw, True)
    ref = next(e[3] for e in doc.entries() if e[0] == 0x100 and _string(e[1], 9) == 'OR6-614 Changed')
    owner = next(at for at, tag, _ in blocks(data) if tag == 0x100 and doc.reference(at+12) == ref)
    if mutation == 'bad-index-width':
        entry, _, _ = field(data, owner, 14); struct.pack_into('<H', data, entry+2, 2)
    elif mutation == 'duplicate-index':
        _, _, at = field(data, owner, 14); struct.pack_into('<I', data, at, 1)
    elif mutation == 'unknown-field':
        _, _, at = field(data, owner, 15); data[at] = 0
    else:
        _, length, at = field(data, owner, 3); data[at:at+length] = bytes(length)
    result = read_or6(rotate(data, False))
    assert not result['termine'] and result['uebersprungen'] == 3
