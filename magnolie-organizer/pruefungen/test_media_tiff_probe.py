"""#749: TIFF evidence and Linux original-image receive/restore, not SEND."""
from base64 import b64decode
from gzip import decompress
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_mime import _tiff_rgb_image, identify
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving


CONTRACTS=Path(__file__).resolve().parents[2]/'contracts'
VECTORS=json.loads((CONTRACTS/'media-tiff-probe-vectors.json').read_text())


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


@pytest.mark.parametrize(('name','suffix'),[('little','.tiff'),('big','.tiff'),('heic','.heic')])
def test_image_original_survives_native_receive_backup_and_offline_restore(receiving,tmp_path,name,suffix):
    from dataclasses import replace
    from magnolie_file_acceptance import NativeAcceptedDestination
    from magnolie_media_backups import NativeMediaBackupLocations, NativeMediaBackupRestoreOwner, NativeMediaBackups
    from test_file_desktop_album_worker import prepared
    from test_photo_version_workflow import changed, cycle

    if name=='heic':
        fixture=json.loads((CONTRACTS/'media-heic-original-vector.json').read_text())
        raw=decompress(b64decode(fixture['gzip_base64'],validate=True))
        assert raw[4:12]==b'ftypheic'
        assert sha256(raw[raw.index(b'<x:xmpmeta'):]).hexdigest()==fixture['xmp_sha256']
        for kind in ('images','video'):
            with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(raw,len(raw),kind)
    else:
        fixture=VECTORS[name];raw=b64decode(fixture['base64'],validate=True)
    assert sha256(raw).hexdigest()==fixture['sha256']
    connection=receiving[3];root=receiving[4]
    seed=prepared(receiving)[0]
    relative='Camera/original'+suffix
    full=changed(replace(seed,files=(replace(seed.files[0],path=relative),)),'a',raw)
    state,chunks,saved=cycle(receiving,full,raw)
    assert state['state']=='complete' and len(chunks)==len(saved)==1,state
    original=root/relative
    assert original.read_bytes()==raw
    snapshot,(mapping,),cursor=connection._mappings.candidate_page('images')
    assert cursor is None and mapping.relative_path==relative and mapping.saved_sha256==fixture['sha256']
    before=(original.stat().st_ino,original.read_bytes());outputs=receiving[2].send.call_count
    directory=connection._authority.binding.native_directory;scope='9'*64
    storage=tmp_path/'local-tiff-backup';storage.mkdir(mode=0o700)
    restore=tmp_path/'local-tiff-restore';restore.mkdir(mode=0o700)
    parent=NativeAcceptedDestination.capture(storage);target=NativeAcceptedDestination.capture(restore)
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        locations.choose(locations.issue_action(),locations.read(),mapping.destination,parent)
        with NativeMediaBackups(mapping.destination,connection._authority.protection,lambda:True,
                create=True,storage_parent=parent) as backups:
            version=backups.save_from_mappings(connection._mappings,mapping.association,mapping.protected_record_sha256)
        assert connection._mappings.read()==snapshot
        connection.close()
        with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:
            result=owner.restore(owner.issue_action(),locations,mapping.destination,locations.source_id(parent),version,target)
            assert result.state=='restored' and result.original_mapping==mapping
            assert not result.grants_write_authority and not result.is_saved_receipt
            restored=restore/result.name
            assert restored.suffix==suffix and restored.read_bytes()==raw
            assert sha256(restored.read_bytes()).hexdigest()==fixture['sha256']
    assert (original.stat().st_ino,original.read_bytes())==before
    assert receiving[2].send.call_count==outputs


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
