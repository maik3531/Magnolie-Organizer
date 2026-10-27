"""Independently authored OR6 recurrence sets, category membership and phone contexts."""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'bin'))
from magnolie_or6 import read_or6, _Document
from magnolie_recurrence import expand_calendar
from modul_laden import quellmodul_laden
from test_or6_import import rotate, blocks

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-extensions.json').read_text())


def fixture(name='weekly-monday-222.or6'):
    item = CONTRACT['files'][name]
    data = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
    assert len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256']
    return data


def series(result):
    entries = [item for item in result['termine'] if item['titel'] == CONTRACT['expected']['weekly']['title']]
    assert len(entries) == 1, 'One linked native series must remain one series, not four unrelated appointments'
    return entries[0]


def dates(item):
    expanded = expand_calendar(item, datetime(2026, 11, 1), datetime(2027, 1, 1), timezone.utc)
    return [(start.strftime('%Y-%m-%d'), start.strftime('%H:%M'), end.strftime('%H:%M'))
            for start, end, all_day, identity in expanded]


def test_original_weekly_rule_remains_editable_and_expands_to_preselected_dates():
    result = read_or6(fixture())
    item = series(result)
    assert len(result['termine']) == 2 and result['uebersprungen'] == 0 and result['wiederholend'] == 0
    assert item['uid'] == 'or6:0006076f:0000040e'
    assert item['wiederholung']['art'] == 'weekly' and item['wiederholung']['intervall'] == 2
    assert item['wiederholung']['bis'] == '2026-12-14'
    assert dates(item) == [(day, '09:15', '10:00') for day in CONTRACT['expected']['weekly']['expectedDates']]
    assert any(line.startswith('RRULE:') for line in item['icsRoundtrip'])


def test_original_contact_category_and_sparse_phone_slots_keep_their_contexts():
    result = read_or6(fixture('contact-context-222.or6'))
    contact = next(item for item in result['kontakte'] if item['vorname'] == 'Grace')
    expected = CONTRACT['expected']['contact']
    for key in ('vorname', 'nachname', 'firma', 'email'):
        assert contact[key] == expected[key]
    assert {item['wert']:item['typen'] for item in contact['telefone']} == expected['phoneTypes']
    assert contact['vcardRoundtrip'] == ['CATEGORIES:' + ','.join(expected['categories'])]
    assert len(result['kontakte']) == 2 and result['wiederholend'] == 0


def test_unrecognized_native_rule_retains_the_exact_finite_series_set():
    data = rotate(fixture(), True)
    definition = next(offset for offset, tag, size in blocks(data) if tag == 0xfefffff2)
    for index in range(struct.unpack_from('<I', data, definition+0x28)[0]):
        entry = definition+0x34+index*8
        if struct.unpack_from('<H', data, entry)[0] == 3:
            struct.pack_into('<H', data, entry+4, 99)
            break
    result = read_or6(bytes(rotate(data, False)))
    item = series(result)
    assert item['wiederholung']['art'] == 'custom'
    assert dates(item) == [(day, '09:15', '10:00') for day in CONTRACT['expected']['weekly']['expectedDates']]
    assert any(line.startswith('RDATE:') for line in item['icsRoundtrip'])


def test_original_distribution_groups_map_only_live_explicit_memberships():
    result = read_or6(fixture('group-beta-222.or6'))
    assert len(result['kontakte']) == 2 and result['uebersprungen'] == 0
    for contact in result['kontakte']:
        expected = CONTRACT['expected']['groups'][contact['vorname']]
        assert contact['vcardRoundtrip'] == ['CATEGORIES:' + ','.join(expected)]


def test_original_deleted_occurrence_is_an_exception_not_a_resurrected_record():
    result = read_or6(fixture('weekly-deleted-222.or6'))
    item = series(result)
    assert result['wiederholend'] == 0 and result['uebersprungen'] == 0
    assert dates(item) == [(day, '09:15', '10:00') for day in CONTRACT['expected']['deletedWeeklyDates']]
    assert item['icsKomplex'] is True and 'EXDATE:20261116T091500' in item['icsRoundtrip']


def test_actual_linux_import_dispatch_preserves_new_series_and_membership_metadata(tmp_path):
    product = quellmodul_laden('or6_extended_import_product', str(Path(__file__).parents[1] / 'bin/magnolie-organizer'))
    raw = fixture('weekly-deleted-222.or6')
    result = product.import_rohdaten_lesen('lotus', raw, 'independent-extended.or6')
    assert dates(series(result)) == [(day, '09:15', '10:00') for day in CONTRACT['expected']['deletedWeeklyDates']]
    assert len(result['kontakte']) == 2
    assert next(item for item in result['kontakte'] if item['vorname'] == 'Ada')['vcardRoundtrip'] == ['CATEGORIES:OR6-222 Beta']
    class Window:
        _gesperrt = False
        def __init__(self): self.replies = []
        def _datei_oeffnen(self, *args): raise AssertionError('MCP opened an import dialog')
        def antwort(self, callback, payload): self.replies.append((callback, payload))
    path = tmp_path / 'extended.or6'; path.write_bytes(raw)
    window = Window()
    product.Fenster.bei_import(window, {'requestId':'extended-source', 'art':'lotus', 'pfad':str(path)})
    callback, reply = window.replies.pop()
    assert callback == 'App.importErgebnis' and reply['ok'] and reply['requestId'] == 'extended-source'
    assert reply['sha256'] == hashlib.sha256(raw).hexdigest() and path.read_bytes() == raw
    assert dates(series(reply)) == dates(series(result))


def test_freed_native_occurrence_never_reappears_from_original_date_array():
    raw = fixture(); data = rotate(raw, True); document = _Document(raw)
    members = [entry for entry in document.entries(repeats=True) if entry[0] == 0x100 and entry[1].get(10) == b'\x01\0']
    reference = members[-1][3]
    address = next(address for address,(tag,size) in document.blocks.items() if tag == 0x100 and document.reference(address+12) == reference)
    struct.pack_into('<I', data, address, 0xfffffffc)
    result = read_or6(bytes(rotate(data, False)))
    assert [day for day, start, end in dates(series(result))] == CONTRACT['expected']['weekly']['expectedDates'][:-1]


@pytest.mark.parametrize('mutation', ('foreign_links', 'conflicting_content'))
def test_partial_or_conflicting_native_sets_are_not_flattened_or_joined_by_title(mutation):
    raw = fixture(); data = rotate(raw, True); document = _Document(raw)
    entries = list(document.entries(repeats=True))
    members = [entry for entry in entries if entry[0] == 0x100 and entry[1].get(10) == b'\x01\0']
    addresses = {document.reference(address+12):address for address,(tag,size) in document.blocks.items() if tag == 0x100}
    if mutation == 'foreign_links':
        repeat_schema = next(entry[4] for entry in entries if entry[0] == 0xfefffff2)
        for address,(tag,size) in document.blocks.items():
            if tag == 0xfffffffb and size >= 0x58 and document.reference(address+0x38) == repeat_schema:
                struct.pack_into('<II', data, address+0x38, 0xffffffff, 0xffffffff)
    else:
        address = addresses[members[-1][3]]
        count = struct.unpack_from('<I', data, address+0x28)[0]
        for index in range(count):
            entry = address+0x34+index*8
            if struct.unpack_from('<H', data, entry)[0] == 9:
                pointer = struct.unpack_from('<I', data, entry+4)[0]
                data[address+pointer] = ord('X')
    result = read_or6(bytes(rotate(data, False)))
    assert not any(item['titel'].startswith(('OR6-222', 'XR6-222')) for item in result['termine'])
    assert result['wiederholend'] == 0 and result['uebersprungen'] >= 3
