"""Actual encrypted private media sender; no production readiness/retirement."""
import base64
import struct
import zlib
import pytest

from test_media_source_sender import source, native, receiving, mappings, freeze, handshake, acceptance, request, saved, deliver, message
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_offer import validate_media_offer
from magnolie_media_mime import identify, PREFIX_BYTES
from magnolie_file_published_readback import KIND, destination_token, encode_body
from magnolie_file_transfer import TransferError
from magnolie_telefon import now_ms


def png(salt=0):
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
    payload=bytes((index+salt)%251 for index in range(70013-len(image)-12)); chunk=b'npAD'+payload
    return image[:-12]+struct.pack('>I',len(payload))+chunk+struct.pack('>I',zlib.crc32(chunk))+image[-12:]


def media_offered(h):
    h.target.write_bytes(png());cached=freeze(h)
    sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    handshake(h,sender);offer=sender.send_media_offer();assert h.wire.receive()==offer
    return sender,cached,offer


def chunks(h,sender,cached,offer):
    accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
    for index in reversed(range(cached.manifest.files[0].chunks)):
        deliver(h,sender,request(accepted,cached,index));output=h.wire.receive()
        assert base64.b64decode(output['body']['data_base64'],validate=True)==png()[index*65536:(index+1)*65536]
    return accepted


def readback(sender,cached,offer,*,publication='a'*64,mime='image/png'):
    manifest=cached.manifest;file=manifest.files[0]
    context=dict(format=1,offer_id=offer['message_id'],manifest_sha256=manifest.fingerprint,
        transfer_id=manifest.transfer_id,source_id=manifest.source_id,file_id=file.id,size=file.size,sha256=file.sha256,
        media_type='images',mime_type=mime,publication_sha256=publication,row_sha256='b'*64,
        permission_epoch=sender._binding.permission_epoch,readback_nonce='c'*64)
    binding=sender._controls.binding(destination_token(context),sender_is_local=True)
    return message(KIND,encode_body(context,binding),offer['expires_ms'])


def test_actual_authenticated_cache_media_offer_chunks_saved_and_readback_keep_distinct_authorities(source):
    h=source;sender,cached,offer=media_offered(h)
    try:
        media=validate_media_offer(offer,cached.manifest.sender_id,cached.manifest.receiver_id)
        assert media.offer['message_id']==offer['message_id'] and media.manifest==cached.manifest
        assert media.mime_types=={cached.manifest.files[0].id:'image/png'} and media.originals==cached.original_references
        assert sender.observation().body['format']==4
        accepted=chunks(h,sender,cached,offer);peer_saved=saved(accepted,cached);deliver(h,sender,peer_saved)
        assert sender.observation().body['phase']=='peer_saved' and sender.observation().body['peer_readback'] is None
        output=readback(sender,cached,offer);deliver(h,sender,output);observed=sender.observation()
        assert observed.body['phase']=='peer_readback' and observed.body['peer_saved']==peer_saved and observed.body['peer_readback']==output
        assert not observed.grants_read_authority and not observed.is_saved_receipt and not observed.permits_retirement
        from magnolie_media_source_retirement import verify_completed_saved_exchange
        with pytest.raises(TransferError):verify_completed_saved_exchange(observed.body,cached.manifest)
        assert h.target.read_bytes()==png() and cached.directory.exists() and not h.preferences.local_grant(True).grants.send_files
    finally:sender.close()


@pytest.mark.parametrize('fault',['before_saved','publication','mime','expired','foreign_channel','duplicate'])
def test_media_readback_rejects_unowned_or_rehashed_semantic_substitution_without_retirement(source,fault):
    h=source;sender,cached,offer=media_offered(h)
    try:
        accepted=chunks(h,sender,cached,offer)
        if fault!='before_saved':deliver(h,sender,saved(accepted,cached))
        packet=readback(sender,cached,offer,publication='d'*64 if fault=='publication' else 'a'*64,
            mime='image/jpeg' if fault=='mime' else 'image/png')
        if fault=='expired':packet['expires_ms']=now_ms()-1
        if fault=='duplicate':deliver(h,sender,packet)
        before=sender.observation()
        with pytest.raises(TransferError):
            if fault=='foreign_channel':sender.observe(object(),packet)
            else:deliver(h,sender,packet)
        assert sender.observation()==before and cached.directory.exists() and h.target.read_bytes()==png()
    finally:sender.close()


def test_unknown_actual_cache_content_does_not_create_media_offer_or_wire_attempt(source):
    h=source;cached=freeze(h);sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    try:
        handshake(h,sender);received=h.wire.received
        with pytest.raises(TransferError,match='mime_unknown'):sender.send_media_offer()
        assert sender.observation() is None and h.wire.received==received and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:sender.close()


@pytest.mark.parametrize('kind,prefix,expected',[
    ('images',png(),'image/png'),
    ('images',b'\xff\xd8\xff\xc0\x00\x08\x08\x00\x01\x00\x02\x00','image/jpeg'),
    ('video',struct.pack('>I',16)+b'ftypisom'+b'\0'*4,'video/mp4'),
    ('video',struct.pack('>I',16)+b'ftypqt  '+b'\0'*4,'video/quicktime')],ids=['png','jpeg','mp4','quicktime'])
def test_mime_identification_uses_actual_bounded_container_bytes(kind,prefix,expected):
    assert identify(prefix,len(prefix),kind)==expected


@pytest.mark.parametrize('prefix,total,kind',[(b'<svg/>',6,'images'),(png(),len(png()),'video'),
    (b'\xff\xd8\xff\xda',4,'images'),(png()[:25],25,'images'),(b'x',True,'images'),(b'x'*(PREFIX_BYTES+1),PREFIX_BYTES+1,'images')],
    ids=['active','wrong-domain','sos-only','truncated','bool-size','oversize-prefix'])
def test_mime_unknown_active_truncated_wrong_domain_and_bounds_are_closed(prefix,total,kind):
    with pytest.raises(TransferError):identify(prefix,total,kind)


@pytest.mark.parametrize('kind,prefix,expected',[
    ('images',png(),'image/png'),('video',struct.pack('>I',16)+b'ftypisom'+b'\0'*4,'video/mp4'),
    ('images',struct.pack('>I',16)+b'ftypisom'+b'\0'*4,'media_collection_known_other_type'),
    ('video',png(),'media_collection_known_other_type'),('images',b'not-media','media_source_mime_unknown'),
    ('video',png()[:25],'media_source_mime_unknown'),('bad-kind',png(),'media_source_mime_unknown')])
def test_collection_kind_exclusion_is_positive_container_identification_not_relaxed_sender_mime(kind,prefix,expected):
    from magnolie_media_mime import identify_collection
    if expected.startswith('media_'):
        with pytest.raises(TransferError,match='^'+expected+'$'):identify_collection(prefix,len(prefix),kind)
        with pytest.raises(TransferError):identify(prefix,len(prefix),kind) # Real sender remains strict.
    else:assert identify_collection(prefix,len(prefix),kind)==identify(prefix,len(prefix),kind)==expected
