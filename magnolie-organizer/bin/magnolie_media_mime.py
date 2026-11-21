"""Bounded authenticated-byte container identification, not pixel validation.

Matches Windows NativeMediaContentMime. No filename/MIME guess grants a source
owner; the receiver still inspects the full hash-verified native media file.
"""
import struct
from magnolie_file_transfer import TransferError

PREFIX_BYTES = 1024 * 1024
_SOF_MARKERS = frozenset((*range(0xc0, 0xc4), *range(0xc5, 0xc8), *range(0xc9, 0xcc), *range(0xcd, 0xd0)))


def identify_collection(prefix,total_bytes,kind):
    """Deny-only known opposite-container exclusion, never a video SEND grant.

    Only an independently admitted native collection source calls this. Unknown,
    broken or out-of-bound bytes still HOLD; do not catch mime_unknown as skip.
    Sender/receiver identification remains strict and unchanged.
    """
    if kind not in ('images','video'):raise TransferError('media_source_mime_unknown')
    try:return identify(prefix,total_bytes,kind)
    except TransferError as error:
        if str(error)!='media_source_mime_unknown':raise
    identify(prefix,total_bytes,'video' if kind=='images' else 'images')
    raise TransferError('media_collection_known_other_type')


def _dimensions(width, height):
    if not 1 <= width <= 32768 or not 1 <= height <= 32768 or width * height > 24000000:
        raise TransferError('media_source_mime_dimensions')


def _gif_image(prefix):
    if len(prefix)<13:return False
    width,height=struct.unpack_from('<HH',prefix,6)
    _dimensions(width,height)
    global_table=3*(2<<(prefix[10]&7)) if prefix[10]&128 else 0
    offset=13+global_table
    while offset<len(prefix):
        marker=prefix[offset];offset+=1
        if marker==0x2c: # Image descriptor, not an extension or an empty trailer.
            if len(prefix)-offset<9:return False
            left,top,columns,rows,flags=struct.unpack_from('<HHHHB',prefix,offset)
            _dimensions(columns,rows)
            if left+columns>width or top+rows>height:return False
            local_table=3*(2<<(flags&7)) if flags&128 else 0
            if not (global_table or local_table):return False
            offset+=9+local_table
            return (len(prefix)-offset>=3 and 2<=prefix[offset]<=8
                    and 0<prefix[offset+1]<=len(prefix)-offset-2)
        if marker!=0x21 or offset>=len(prefix):return False
        offset+=1 # Extension label; walk bounded data sub-blocks, not a byte search.
        while offset<len(prefix):
            size=prefix[offset];offset+=1
            if size==0:break
            offset+=size
        else:return False
    return False


def _webp_image(prefix, total_bytes):
    if len(prefix)<20 or prefix[:4]!=b'RIFF' or prefix[8:12]!=b'WEBP':return False
    if struct.unpack_from('<I',prefix,4)[0]+8!=total_bytes:return False
    offset=12;canvas=None
    while len(prefix)-offset>=8:
        kind=prefix[offset:offset+4]
        size=struct.unpack_from('<I',prefix,offset+4)[0]
        start=offset+8;end=start+size+(size&1)
        if not size or end>total_bytes:return False
        if kind==b'VP8X':
            if offset!=12 or size!=10 or len(prefix)-start<10:return False
            # Static originals only here. An animation container must not be
            # mistaken for a still image from a metadata or thumbnail chunk.
            if prefix[start]&0xc3 or prefix[start+1:start+4]!=b'\0'*3:return False
            canvas=(1+int.from_bytes(prefix[start+4:start+7],'little'),1+int.from_bytes(prefix[start+7:start+10],'little'))
            _dimensions(*canvas)
        elif kind==b'VP8 ':
            if size<=10 or len(prefix)-start<10 or prefix[start]&1 or prefix[start+3:start+6]!=b'\x9d\x01\x2a':return False
            width,height=struct.unpack_from('<HH',prefix,start+6)
            size_found=(width&0x3fff,height&0x3fff)
            _dimensions(*size_found)
            return size_found==canvas if canvas is not None else offset==12 and end==total_bytes
        elif kind==b'VP8L':
            if size<=5 or len(prefix)-start<5 or prefix[start]!=0x2f:return False
            bits=struct.unpack_from('<I',prefix,start+1)[0]
            if bits>>29:return False
            size_found=(1+(bits&0x3fff),1+((bits>>14)&0x3fff))
            _dimensions(*size_found)
            return size_found==canvas if canvas is not None else offset==12 and end==total_bytes
        elif canvas is None or kind in (b'ANIM',b'ANMF'):
            return False
        offset=end
    return False


def _bmp_image(prefix,total_bytes):
    # Only the verified 40-byte Windows DIB, uncompressed packed RGB pixels.
    if len(prefix)<54 or prefix[:2]!=b'BM':return False
    length,reserved,offset,dib,width,height,planes,bits,compression,size=struct.unpack_from('<IIIIiiHHII',prefix,2)
    if (length!=total_bytes or reserved or offset<54 or dib!=40 or planes!=1
            or bits!=24 or compression!=0):return False
    _dimensions(width,abs(height))
    pixel_bytes=((width*bits+31)//32)*4*abs(height)
    return size in (0,pixel_bytes) and offset+pixel_bytes<=total_bytes


def _ebml_element(prefix,offset,parent_end):
    """Read one finite EBML element header without following SeekHead offsets."""
    def vint(at,max_width,identifier=False):
        if at>=min(len(prefix),parent_end) or not prefix[at]:raise ValueError('ebml_vint')
        width=9-prefix[at].bit_length()
        if width>max_width or at+width>min(len(prefix),parent_end):raise ValueError('ebml_vint')
        value=int.from_bytes(prefix[at:at+width],'big')
        if not identifier:
            maximum=(1<<(7*width))-1;value&=maximum
            if value==maximum:raise ValueError('ebml_unknown_length')
        return value,at+width
    element,payload=vint(offset,4,True)
    length,payload=vint(payload,8)
    end=payload+length
    if end>parent_end:raise ValueError('ebml_parent_length')
    return element,payload,end


def _ebml_children(prefix,start,end):
    for _ in range(1024):
        if start==end:return
        element,payload,next_element=_ebml_element(prefix,start,end)
        yield element,payload,next_element
        start=next_element
    if start!=end:raise ValueError('ebml_child_bound')


def _ebml_witnesses(prefix,start,end,wanted):
    if end>len(prefix):raise ValueError('ebml_truncated_metadata')
    items={}
    for element,payload,next_element in _ebml_children(prefix,start,end):
        if element in wanted:
            if element in items:raise ValueError('ebml_duplicate_metadata')
            items[element]=(payload,next_element)
    return items


def _ebml_uint(prefix,bounds):
    start,end=bounds
    if not 1<=end-start<=8:raise ValueError('ebml_integer')
    return int.from_bytes(prefix[start:end],'big')


def _webm_video(prefix,total_bytes):
    """Conservative source proof for a finite WebM with one VP8/VP9 video track.

    This does not decode frames or authorize a wire offer. Keep separate from
    identify() until the native counterpart can verify the entire original.
    """
    if (type(prefix) not in (bytes,bytearray) or type(total_bytes) is not int or len(prefix)>min(PREFIX_BYTES,total_bytes)
            or prefix[:4]!=b'\x1a\x45\xdf\xa3'):
        return False
    try:
        _,start,end=_ebml_element(prefix,0,total_bytes)
        if end>1024:return False
        doc_start,doc_end=_ebml_witnesses(prefix,start,end,{0x4282})[0x4282]
        if prefix[doc_start:doc_end]!=b'webm':return False
        segment,start,end=_ebml_element(prefix,end,total_bytes)
        if segment!=0x18538067 or end!=total_bytes:return False
        video=False;seen_tracks=False
        for element,payload,next_element in _ebml_children(prefix,start,end):
            if element==0x1F43B675: # The first Cluster must have a payload, not just an empty header.
                return video and payload<min(next_element,len(prefix))
            if element!=0x1654AE6B:continue
            if seen_tracks or next_element>len(prefix):return False
            seen_tracks=True
            for entry,track_start,track_end in _ebml_children(prefix,payload,next_element):
                if entry!=0xAE:continue
                track=_ebml_witnesses(prefix,track_start,track_end,{0x83,0x86,0xE0})
                if _ebml_uint(prefix,track[0x83])!=1:continue  # Audio-only is not video.
                codec_start,codec_end=track[0x86]
                if video or prefix[codec_start:codec_end] not in (b'V_VP8',b'V_VP9'):return False
                dimensions=_ebml_witnesses(prefix,*track[0xE0],{0xB0,0xBA})
                _dimensions(_ebml_uint(prefix,dimensions[0xB0]),_ebml_uint(prefix,dimensions[0xBA]))
                video=True
        return False
    except (KeyError,ValueError,TransferError):return False


def identify(prefix, total_bytes, kind):
    if type(prefix) not in (bytes, bytearray) or type(total_bytes) is not int or len(prefix) > PREFIX_BYTES or total_bytes < len(prefix) or total_bytes < 1:
        raise TransferError('media_source_mime_bound')
    if kind == 'images':
        if prefix[:6] in (b'GIF87a',b'GIF89a') and _gif_image(prefix):return 'image/gif'
        if _webp_image(prefix,total_bytes):return 'image/webp'
        if _bmp_image(prefix,total_bytes):return 'image/bmp'
        if len(prefix) >= 33 and prefix[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            _dimensions(*struct.unpack_from('>ii', prefix, 16))
            if prefix[24] not in (1, 2, 4, 8, 16) or prefix[25] not in (0, 2, 3, 4, 6) or prefix[26] != 0 or prefix[27] != 0 or prefix[28] > 1:
                raise TransferError('media_source_mime_unknown')
            return 'image/png'
        if len(prefix) >= 4 and prefix[:2] == b'\xff\xd8':
            offset = 2
            while offset < len(prefix):
                if prefix[offset] != 255:break
                while offset < len(prefix) and prefix[offset] == 255:offset += 1
                if offset >= len(prefix):break
                marker = prefix[offset]; offset += 1
                if marker in (0, 0xd9, 0xda):break
                if marker == 1 or 0xd0 <= marker <= 0xd8:continue
                if offset + 2 > len(prefix):break
                size = struct.unpack_from('>H', prefix, offset)[0]
                if size < 2 or size > len(prefix) - offset:break
                if marker in _SOF_MARKERS:
                    if size < 8 or prefix[offset + 2] not in (8, 12):break
                    height, width = struct.unpack_from('>HH', prefix, offset + 3)
                    _dimensions(width, height)
                    return 'image/jpeg'
                offset += size
    elif kind == 'video' and len(prefix) >= 16 and prefix[4:8] == b'ftyp':
        size = struct.unpack_from('>I', prefix)[0]
        if 16 <= size <= 1024 and size <= len(prefix) and (size - 16) % 4 == 0:
            brand = prefix[8:12]
            if brand == b'qt  ':return 'video/quicktime'
            if brand in (b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V '):return 'video/mp4'
    raise TransferError('media_source_mime_unknown')
