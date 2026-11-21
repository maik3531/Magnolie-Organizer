"""#749: static WebP built and decoded as actual bytes, not a suffix alias."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import sys

from PIL import Image
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_mime import identify, identify_collection


@pytest.mark.parametrize('variant',['lossy','lossless','exif'])
def test_webp_original_identifies_without_rewriting_bytes_or_metadata(variant):
    image=Image.new('RGB',(7,9),(17,31,62));raw=BytesIO();options={}
    if variant=='lossless':options['lossless']=True
    if variant=='exif':
        exif=Image.Exif();exif[271]='Synthetic camera';options['exif']=exif
    image.save(raw,format='WEBP',**options)
    original=bytearray(raw.getvalue());before=sha256(original).digest()
    with Image.open(BytesIO(original)) as decoded:
        decoded.load();assert decoded.format=='WEBP' and decoded.size==(7,9)
        if variant=='exif':assert decoded.getexif()[271]=='Synthetic camera'
    assert identify(original,len(original),'images')=='image/webp'
    assert sha256(original).digest()==before
    with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(original,len(original),'video')
    with pytest.raises(TransferError,match='media_collection_known_other_type'):identify_collection(original,len(original),'video')
    with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(original[:22],len(original),'images')
    with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(original,len(original)+1,'images')


def test_webp_does_not_claim_animation_or_an_empty_metadata_container():
    raw=BytesIO();first=Image.new('RGB',(7,9),'red');second=Image.new('RGB',(7,9),'blue')
    first.save(raw,format='WEBP',save_all=True,append_images=[second],duration=200,loop=0)
    animated=raw.getvalue()
    with Image.open(BytesIO(animated)) as decoded:assert decoded.is_animated and decoded.n_frames==2
    with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(animated,len(animated),'images')
    metadata_only=b'WEBPVP8X'+struct.pack('<I',10)+bytes(10)
    malformed=b'RIFF'+struct.pack('<I',len(metadata_only))+metadata_only
    with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(malformed,len(malformed),'images')
