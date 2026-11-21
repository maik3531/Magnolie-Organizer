"""#749: container evidence and Linux receive/restore, not desktop SEND."""
from base64 import b64decode
from gzip import decompress
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_mime import _webm_video, identify
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving


CONTRACTS=Path(__file__).resolve().parents[2]/'contracts'
VECTORS=json.loads((CONTRACTS/'media-webm-probe-vectors.json').read_text())
WEBM=b64decode(VECTORS['webm']['base64'],validate=True)


def test_real_webm_probe_leaves_the_original_and_transfer_gate_untouched():
    assert _webm_video(WEBM,len(WEBM))
    assert _webm_video(WEBM[:407],len(WEBM))
    assert sha256(WEBM).hexdigest()==VECTORS['webm']['sha256']
    for kind in ('images','video'):
        with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(WEBM,len(WEBM),kind)


def test_mkv_remux_with_same_video_codec_is_not_webm():
    mkv=b64decode(VECTORS['matroska']['base64'],validate=True)
    assert sha256(mkv).hexdigest()==VECTORS['matroska']['sha256']
    assert not _webm_video(mkv,len(mkv))


@pytest.mark.parametrize(('name','suffix'),[('webm','.webm'),('matroska','.mkv'),('avi','.avi')])
def test_typed_linux_video_receive_and_offline_restore_preserve_original(receiving,tmp_path,monkeypatch,name,suffix):
    from dataclasses import replace
    from magnolie_file_acceptance import NativeAcceptedDestination
    from magnolie_media_backups import NativeMediaBackupLocations, NativeMediaBackupRestoreOwner, NativeMediaBackups
    from test_file_desktop_video_album_worker import ALBUM, prepared_video, video_phone

    if name=='avi':
        vector=json.loads((CONTRACTS/'media-avi-original-vector.json').read_text())
        raw=decompress(b64decode(vector['gzip_base64'],validate=True))
        assert raw[:4]==b'RIFF' and raw[8:12]==b'AVI '
        assert all(vector[tag].encode() in raw for tag in ('title','comment'))
        with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(raw,len(raw),'video')
    else:
        vector=VECTORS[name];raw=b64decode(vector['base64'],validate=True)
    assert sha256(raw).hexdigest()==vector['sha256']
    connection=receiving[3]
    root,(seed,_)=prepared_video(receiving,tmp_path,monkeypatch)
    relative='Camera/original'+suffix
    video=replace(seed.files[0],path=relative,size=len(raw),sha256=vector['sha256'])
    batch=replace(seed,files=(video,),total_bytes=len(raw))
    with video_phone(receiving,root,[batch],monkeypatch,content=raw) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert worker.join(60) and not errors and worker.progress()['state']=='complete',worker.progress()
        assert chunks==[video.id] and len(saved)==1
    snapshot,(mapping,),cursor=connection._mappings.candidate_page('video')
    assert cursor is None and mapping.relative_path==relative and mapping.saved_sha256==vector['sha256']
    assert mapping.destination.path==str(root) and not list(receiving[4].iterdir())
    original=root/relative
    inode=original.stat().st_ino
    assert original.read_bytes()==raw
    directory=connection._authority.binding.native_directory;scope='a'*64
    restore=tmp_path/'video-offline-restore';restore.mkdir(mode=0o700)
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        locations.choose(locations.issue_action(),locations.read(),mapping.destination,None)
        with NativeMediaBackups(mapping.destination,connection._authority.protection,lambda:True,create=True) as backups:
            version=backups.save_from_mappings(connection._mappings,mapping.association,mapping.protected_record_sha256)
        assert connection._mappings.read()==snapshot
        outputs=receiving[2].send.call_count
        connection.close()
        with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:
            result=owner.restore(owner.issue_action(),locations,mapping.destination,locations.source_id(mapping.destination),
                version,NativeAcceptedDestination.capture(restore))
            assert result.state=='restored' and result.original_mapping==mapping and not result.is_saved_receipt
            restored=restore/result.name
            assert restored.suffix==suffix and restored.read_bytes()==raw
    assert (original.stat().st_ino,original.read_bytes())==(inode,raw)
    assert receiving[2].send.call_count==outputs


@pytest.mark.parametrize('before,after',[
    (b'webm',b'mkv '),                         # Cannot guess from generic EBML.
    (b'\x83\x81\x01',b'\x83\x81\x02'),          # No video track.
    (b'V_VP8',b'V_AV1'),                       # Different codec is not proven.
    (b'\xb0\x81\x10',b'\xb0\x81\x00'),          # Invalid dimensions.
    (b'\xba\x81\x10',b'\xb0\x81\x10'),          # Duplicate width, missing height.
    (b'\x18\x53\x80\x67\x01',b'\x18\x53\x80\x67\xff'), # Unknown Segment size outside this subset.
])
def test_webm_requires_exact_document_type_video_track_and_finite_bounds(before,after):
    assert WEBM.count(before)==1
    assert not _webm_video(WEBM.replace(before,after),len(WEBM))


@pytest.mark.parametrize('prefix_length',[0,4,17,52,250,315,406])
def test_webm_probe_holds_truncated_original_metadata(prefix_length):
    assert not _webm_video(WEBM[:prefix_length],len(WEBM))


def test_webm_probe_holds_a_wrong_reported_total():
    assert not _webm_video(WEBM,len(WEBM)+1)
    assert not _webm_video(WEBM,len(WEBM)-1)
