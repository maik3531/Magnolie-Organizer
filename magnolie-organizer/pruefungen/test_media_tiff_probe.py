"""#749: bounded TIFF evidence does not grant an ordinary transfer."""
from base64 import b64decode
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_mime import _tiff_rgb_image, identify


VECTORS=json.loads((Path(__file__).resolve().parents[2]/'contracts'/'media-tiff-probe-vectors.json').read_text())


@pytest.mark.parametrize(('name','endian'), [('little','<'),('big','>')])
def test_real_tiff_original_remains_byte_exact_and_sender_gate_closed(name,endian):
    fixture=VECTORS[name];raw=b64decode(fixture['base64'],validate=True)
    assert _tiff_rgb_image(raw,len(raw))
    offset=struct.unpack_from(endian+'I',raw,4)[0]
    assert sha256(raw[8:offset]).hexdigest()==VECTORS['rgb_sha256']
    assert sha256(raw).hexdigest()==fixture['sha256']
    for kind in ('images','video'):
        with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(raw,len(raw),kind)
    assert not _tiff_rgb_image(raw[:-1],len(raw))
    assert not _tiff_rgb_image(raw,len(raw)-1)


@pytest.mark.parametrize('fault',['bigtiff','directory_before_header','duplicate_tag','truncated_table','second_ifd',
    'aliased_metadata','strip_over_metadata','wrong_strip_length','compressed','zero_dimensions','planar'])
def test_tiff_header_alone_and_raced_or_unsupported_layout_are_not_evidence(fault):
    raw=bytearray(b64decode(VECTORS['little']['base64'],validate=True));offset=struct.unpack_from('<I',raw,4)[0]
    count=struct.unpack_from('<H',raw,offset)[0]
    fields={struct.unpack_from('<H',raw,at)[0]:at for at in range(offset+2,offset+2+12*count,12)}
    match fault:
        case 'bigtiff':raw[2]=43
        case 'directory_before_header':struct.pack_into('<I',raw,4,4)
        case 'duplicate_tag':struct.pack_into('<H',raw,fields[257],256)
        case 'truncated_table':struct.pack_into('<H',raw,offset,48)
        case 'second_ifd':struct.pack_into('<I',raw,offset+2+12*count,offset)
        case 'aliased_metadata':struct.pack_into('<I',raw,fields[318]+8,230)
        case 'strip_over_metadata':struct.pack_into('<I',raw,fields[273]+8,offset)
        case 'wrong_strip_length':struct.pack_into('<I',raw,fields[279]+8,35)
        case 'compressed':struct.pack_into('<H',raw,fields[259]+8,5)
        case 'zero_dimensions':struct.pack_into('<H',raw,fields[256]+8,0)
        case 'planar':struct.pack_into('<H',raw,fields[284]+8,2)
    assert not _tiff_rgb_image(raw,len(raw))
