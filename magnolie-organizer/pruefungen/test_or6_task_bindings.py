"""Original bulk-edit indices and stale template dates, independently observed (#610)."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
from test_or6_import import rotate, blocks
from test_or6_planner import field
from test_or6_task_scopes import occurrences
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _string

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-task-bindings.json').read_text())


def fixture(name):
    item = CONTRACT['files'][name]
    raw = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    return raw


@pytest.mark.parametrize('expected', CONTRACT['expected'], ids=lambda value: value['file'])
def test_original_bulk_edits_keep_only_actual_linked_dates_and_preserve_template_provenance(expected, native):
    result = read_or6(fixture(expected['file']))
    items = [item for item in result['aufgaben'] if item['titel'] == expected['title']]
    assert result['uebersprungen'] == 0 and items
    values = occurrences(items)
    assert sorted(values) == expected['dates']
    for date, (completed, category) in values.items():
        assert completed == (date in expected['completedDates'])
        assert category == expected['categories'].get(date, '')
    master, = [item for item in items if not any(line.startswith('RECURRENCE-ID:') for line in item['icsRoundtrip'])]
    assert any(line.startswith('RRULE:') for line in master['icsRoundtrip']) == expected['ruleExpected']
    if not expected['ruleExpected']:
        assert any(line.startswith('RDATE:') for line in master['icsRoundtrip'])
        assert 'X-MAGNOLIE-OR6-TASK-TEMPLATE-STARTS:' + ','.join(expected['templateStarts']) in master['icsRoundtrip']
        assert 'X-MAGNOLIE-OR6-TASK-TEMPLATE-DUES:' + ','.join(expected['templateDues']) in master['icsRoundtrip']
    reread = native.ics_lesen(native.ics_schreiben_aufgaben(items))
    imported = [item for item in reread['aufgaben'] if item['titel'] == expected['title']]
    assert occurrences(imported) == values
    raw_properties = [line for line in master['icsRoundtrip'] if line.startswith('X-MAGNOLIE-OR6-TASK-TEMPLATE-')]
    assert all(any(line in item['icsRoundtrip'] for item in imported) for line in raw_properties)


@pytest.mark.parametrize('mutation', ('missing-member', 'unknown-index', 'mixed-indices', 'duplicate-date', 'changed-duration', 'changed-title', 'unknown-state'))
def test_bulk_recovery_requires_a_complete_unique_linked_set_with_known_fields(mutation):
    raw = fixture('task-bindings-all-dates-reopened-610.or6'); doc = _Document(raw); data = rotate(raw, True)
    members = sorted([e for e in doc.entries() if e[0] == 0x300 and _string(e[1], 9) == 'OR6-610 All'], key=lambda e: e[1][7])
    owners = [next(at for at, tag, _ in blocks(data) if tag == 0x300 and doc.reference(at+12) == member[3]) for member in members]
    owner = owners[-1]
    if mutation == 'missing-member':
        struct.pack_into('<I', data, owner, 0xfffffffc)
    elif mutation in ('unknown-index', 'mixed-indices'):
        entry, _, _ = field(data, owner, 18)
        struct.pack_into('<HHI', data, entry, 14, 4, 99 if mutation == 'unknown-index' else 1)
    elif mutation == 'duplicate-date':
        for fid in (7, 8):
            _, _, at = field(data, owner, fid); _, _, source = field(data, owners[0], fid)
            data[at:at+8] = data[source:source+8]
    elif mutation == 'changed-duration':
        _, _, at = field(data, owner, 8); data[at+4] = 19
    elif mutation == 'changed-title':
        _, _, at = field(data, owner, 9); data[at] = ord('X')
    else:
        _, _, at = field(data, owner, 20); struct.pack_into('<I', data, at, 99)
    result = read_or6(rotate(data, False))
    assert not any(item['titel'].startswith(('OR6-610', 'XR6-610')) for item in result['aufgaben'])
    assert result['uebersprungen'] == (2 if mutation == 'missing-member' else 3)
