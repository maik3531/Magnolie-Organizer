"""#749: recognize uncompressed 24-bit BMP originals without trusting a name."""
from io import BytesIO
from pathlib import Path
import struct
import sys

from PIL import Image
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_mime import identify, identify_collection


def original_bmp():
    raw=BytesIO()
    Image.new('RGB',(2,3),(17,31,62)).save(raw,format='BMP')
    return raw.getvalue()


def test_native_sender_preserves_actual_24bit_bmp_and_separates_video():
    expected=original_bmp();value=bytearray(expected)
    with Image.open(BytesIO(value)) as decoded:
        decoded.load();assert decoded.size==(2,3) and decoded.getpixel((1,2))==(17,31,62)
    assert identify(value,len(value),'images')=='image/bmp'
    assert value==expected
    with pytest.raises(TransferError,match='media_source_mime_unknown'):identify(value,len(value),'video')
    with pytest.raises(TransferError,match='media_collection_known_other_type'):identify_collection(value,len(value),'video')


@pytest.mark.parametrize('offset,value,error',[(2,79,'unknown'),(10,53,'unknown'),(10,56,'unknown'),(14,12,'unknown'),
    (18,100_000,'dimensions'),(22,0x80000000,'dimensions'),(30,1,'unknown'),(34,1,'unknown')])
def test_bmp_rejects_wrong_length_offset_dimensions_and_compression(offset,value,error):
    raw=bytearray(original_bmp());struct.pack_into('<I',raw,offset,value)
    with pytest.raises(TransferError,match='media_source_mime_'+error):identify(raw,len(raw),'images')
