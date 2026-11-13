"""Independently authored native Task series, not appointments relabelled as tasks."""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from test_or6_import import rotate
from magnolie_or6 import _Document, read_or6
from magnolie_recurrence import expand_calendar
from modul_laden import quellmodul_laden


CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-tasks.json').read_text())


def fixture():
    item = CONTRACT['files']['task-weekly-567.or6']
    raw = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    return raw


def task(result):
    values = [item for item in result['aufgaben'] if item['titel'] == CONTRACT['expected']['title'] and
              not any(line.startswith('RECURRENCE-ID:') for line in item.get('icsRoundtrip', []))]
    assert len(values) == 1, 'One original linked Task series must not be omitted or flattened'
    return values[0]


def dates(value):
    return [start.strftime('%Y-%m-%d') for start, end, all_day, identity in expand_calendar(
        value, datetime(2026, 12, 1), datetime(2027, 1, 1), timezone.utc, task=True)]


def test_original_task_series_is_one_expandable_todo_with_native_identity():
    raw = fixture(); document = _Document(raw)
    members = [entry for entry in document.entries(repeats=True) if entry[0] == 0x300 and entry[1].get(10) == b'\x01\0']
    assert len(members) == CONTRACT['expected']['nativeOccurrences']
    result = read_or6(raw); value = task(result)
    assert len(result['aufgaben']) == 2 and result['uebersprungen'] == 0
    assert value['erledigt'] is False and value['startDatum'] == '2026-12-01' and value['faellig'] == '2026-12-01'
    assert dates(value) == CONTRACT['expected']['dates']
    assert any(line.startswith('RRULE:FREQ=WEEKLY;') for line in value['icsRoundtrip'])
    assert any(line.startswith('DUE:') for line in value['icsRoundtrip'])
    assert not any(line.startswith('DTEND:') for line in value['icsRoundtrip'])
    definition, = [entry for entry in document.entries(repeats=True) if entry[0] == 0xfefffff2]
    assert value['uid'] == definition[2]
    assert not any(item['titel'] == value['titel'] for item in result['termine'])


def test_actual_linux_import_and_todo_export_keep_all_original_task_dates():
    product = quellmodul_laden('or6_task_series_product', Path(__file__).parents[1] / 'bin/magnolie-organizer')
    imported = product.import_rohdaten_lesen('lotus', fixture(), 'original-synthetic-task.or6')
    value = task(imported)
    exported = product.ics_schreiben_aufgaben([value])
    assert exported.count('BEGIN:VTODO') == 1 and 'BEGIN:VEVENT' not in exported
    reread = product.ics_lesen(exported)
    assert dates(task(reread)) == CONTRACT['expected']['dates']


@pytest.mark.parametrize('mutation', ('unknown_rule', 'freed_member', 'orphaned_member', 'unknown_status', 'conflicting_content', 'completed_member'))
def test_native_task_series_guards_and_finite_set_fallback(mutation):
    raw = fixture(); doc = _Document(raw); data = rotate(raw, True)
    entries = list(doc.entries(repeats=True))
    members = [entry for entry in entries if entry[0] == 0x300 and entry[1].get(10) == b'\x01\0']
    last = max(members, key=lambda entry: int.from_bytes(entry[1].get(14, b''), 'little'))
    owner = next(address for address, (tag, _) in doc.blocks.items() if tag == 0x300 and doc.reference(address + 12) == last[3])
    if mutation == 'unknown_rule':
        owner = next(address for address, (tag, _) in doc.blocks.items() if tag == 0xfefffff2)
    if mutation == 'freed_member':
        struct.pack_into('<I', data, owner, 0xfffffffc)
    elif mutation == 'orphaned_member':
        for address, (tag, size) in doc.blocks.items():
            if tag == 0xfffffffb and size >= 0x58 and doc.reference(address + 0x20) == last[3] and doc.reference(address + 0x30) != last[3]:
                if any(entry[0] == 0xfefffff2 and entry[3] == doc.reference(address + 0x30) for entry in entries):
                    struct.pack_into('<II', data, address + 0x38, 0xffffffff, 0xffffffff)
    else:
        field = 3 if mutation == 'unknown_rule' else 9 if mutation == 'conflicting_content' else 20
        for index in range(doc.u32(owner + 0x28)):
            prop = owner + 0x34 + index * 8
            if struct.unpack_from('<H', data, prop)[0] == field:
                if field == 9:
                    pointer = struct.unpack_from('<I', data, prop + 4)[0]
                    data[owner + pointer] = ord('X')
                else:
                    struct.pack_into('<I' if field == 20 else '<H', data, prop + 4,
                                     4 if mutation == 'completed_member' else 99)
                break
        else:
            raise AssertionError('Independent native field missing')
    result = read_or6(bytes(rotate(data, False)))
    if mutation in ('orphaned_member', 'unknown_status', 'conflicting_content'):
        assert not any(item['titel'] == CONTRACT['expected']['title'] for item in result['aufgaben'])
        assert result['uebersprungen'] == 3
    else:
        value = task(result)
        assert dates(value) == CONTRACT['expected']['dates'][:2 if mutation in ('freed_member', 'completed_member') else 3]
        if mutation == 'unknown_rule':
            assert any(line.startswith('RDATE:') for line in value['icsRoundtrip'])
        else:
            assert any(line.startswith('EXDATE:') for line in value['icsRoundtrip'])
        if mutation == 'completed_member':
            done, = [item for item in result['aufgaben'] if item['titel'] == CONTRACT['expected']['title'] and item['erledigt']]
            assert done['uid'] == last[2] and done['icsSerienUid'] == value['uid']
            assert dates(done) == ['2026-12-15']
            product = quellmodul_laden('or6_task_status_export_product', Path(__file__).parents[1] / 'bin/magnolie-organizer')
            exported = product.ics_schreiben_aufgaben([value, done])
            reread = product.ics_lesen(exported)
            assert dates(task(reread)) == CONTRACT['expected']['dates'][:2]
            assert sum(item['erledigt'] for item in reread['aufgaben']) == 1
