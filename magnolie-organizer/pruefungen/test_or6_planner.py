"""Independent original-program planner scopes, labels and15actual colors (#568)."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
from test_or6_import import rotate, blocks
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _string

CONTRACT = json.loads((Path(__file__).parents[2] / 'contracts/or6-native-planner.json').read_text())


def fixture():
    meta = CONTRACT['file']
    raw = gzip.decompress(base64.b64decode(meta['gzip_base64'], validate=True))
    assert len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256']
    return raw


def selected(raw):
    return {item['titel']: item for item in read_or6(raw)['termine'] if item['titel'].startswith('OR6-568 ')}


def field(data, address, fid):
    for i in range(struct.unpack_from('<I', data, address + 0x28)[0]):
        offset = address + 0x34 + i * 8
        identifier, length, value = struct.unpack_from('<HHI', data, offset)
        if identifier == fid:
            return offset, length, offset + 4 if length <= 4 else address + value
    raise AssertionError('Expected independent source field missing')


def configs(data):
    return [address for address, tag, _ in blocks(data) if tag == 0x201]


def test_two_original_planner_sections_keep_their_own_names_and_all15colors():
    result = selected(fixture())
    assert len(result) == len(CONTRACT['expected']) == 17
    for expected in CONTRACT['expected']:
        item = result[expected['title']]
        assert (item['kategorien'], item['akzentFarbe'], item['datum']) == (expected['category'], expected['color'], expected['date'])
        assert item['zeit'] == item['endZeit'] == '' and item['endDatum'] == ''
    assert result['OR6-568 A04 original']['kategorien'] != result['OR6-568 B04 original']['kategorien']
    assert result['OR6-568 B01 palette']['akzentFarbe'] == '#00c200'


def test_explicit_first_key_has_verified_implicit_zero_without_invented_source_note():
    document = _Document(fixture())
    native = next(entry for entry in document.entries() if entry[0] == 0x200 and _string(entry[1], 9) == 'OR6-568 B00 palette')
    assert 19 not in native[1]
    item = selected(fixture())['OR6-568 B00 palette']
    assert item['kategorien'] == 'B00' and item['akzentFarbe'] == '#ff0000'
    assert 'Lotus planner KeyID' not in item['notiz']


def test_config_explicit_section_reference_not_shared_options_schema_owns_names():
    raw = fixture(); document = _Document(raw)
    options = [entry for entry in document.entries() if entry[0] == 0x201]
    assert len(options) == 2 and options[0][4] == options[1][4]
    assert options[0][1][3] != options[1][1][3]
    data = rotate(raw, True); a, b = configs(data)
    _, _, x = field(data, a, 3); _, _, y = field(data, b, 3)
    data[x:x+8], data[y:y+8] = data[y:y+8], data[x:x+8]
    result = selected(rotate(data, False))
    assert result['OR6-568 A04 original']['kategorien'] == 'B04'
    assert result['OR6-568 B04 original']['kategorien'] == 'A04'


@pytest.mark.parametrize('mutation', ('duplicate-config', 'missing-config', 'schema-name', 'duplicate-root', 'unknown-key', 'malformed-key', 'unrelated-root'))
def test_missing_ambiguous_or_unrelated_metadata_is_never_guessed(mutation):
    data = rotate(fixture(), True)
    a, b = configs(data)
    _, _, a_ref = field(data, a, 3); _, _, b_ref = field(data, b, 3)
    if mutation == 'duplicate-config':
        data[b_ref:b_ref+8] = data[a_ref:a_ref+8]
    elif mutation == 'missing-config':
        struct.pack_into('<I', data, b, 0x80000201)
    elif mutation == 'schema-name':
        schema = next(entry[4] for entry in _Document(fixture()).entries() if entry[0] == 0x200 and _string(entry[1], 9) == 'OR6-568 B04 original')
        address = next(offset for offset, tag, _ in blocks(data) if tag == 0xffffffff and struct.unpack_from('<II', data, offset+12) == schema)
        data[address+0x48:address+0xc8] = 'Detached'.encode('utf-16le').ljust(128, b'\0')
    elif mutation == 'duplicate-root':
        target = bytes(data[b_ref:b_ref+8])
        address = next(offset for offset, tag, _ in blocks(data) if tag == 0xfeffffff and data[offset+12:offset+20] == target)
        data[address+12:address+20] = data[a_ref:a_ref+8]
    elif mutation in ('unknown-key', 'malformed-key'):
        reference = next(entry[3] for entry in _Document(fixture()).entries() if entry[0] == 0x200 and _string(entry[1], 9) == 'OR6-568 B04 original')
        address = next(offset for offset, tag, _ in blocks(data) if tag == 0x200 and struct.unpack_from('<II', data, offset+12) == reference)
        entry, _, value = field(data, address, 19)
        if mutation == 'unknown-key':
            struct.pack_into('<H', data, value, 99)
        else:
            struct.pack_into('<H', data, entry+2, 1)
    else:
        address = next(offset for offset, tag, _ in blocks(data) if tag == 0xfeffffff and
                       any(struct.unpack_from('<HHI', data, offset+0x34+i*8) == (5, 4, 0x510)
                           for i in range(struct.unpack_from('<I', data, offset+0x28)[0])))
        entry, length, _ = field(data, address, 3)
        assert length > 4
        struct.pack_into('<I', data, entry+4, 0xffffffff)
    result = selected(rotate(data, False))
    assert len(result) == 17
    if mutation == 'unrelated-root':
        assert result['OR6-568 B04 original']['kategorien'] == 'B04'
    else:
        assert 'kategorien' not in result['OR6-568 B04 original'] and 'akzentFarbe' not in result['OR6-568 B04 original']


def test_planner_categories_and_colors_survive_actual_calendar_export(native):
    for item in selected(fixture()).values():
        text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + '\r\n'.join(native._vevent_zeilen(item)) + '\r\nEND:VCALENDAR\r\n'
        output = native.ics_lesen(text)['termine']
        assert len(output) == 1
        assert output[0]['kategorien'] == item['kategorien']
        assert output[0]['akzentFarbe'] == item['akzentFarbe']
