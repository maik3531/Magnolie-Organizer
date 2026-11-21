"""#749: container evidence only; the ordinary transfer path remains held."""
from base64 import b64decode
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_mime import _webm_video, identify


VECTORS=json.loads((Path(__file__).resolve().parents[2]/'contracts'/'media-webm-probe-vectors.json').read_text())
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
