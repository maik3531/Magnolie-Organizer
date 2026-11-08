from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_offer import validate_offer
from magnolie_file_transfer import TransferError
from magnolie_media_offer import create_media_offer, validate_media_offer
from magnolie_media_sync import change
from magnolie_telefon import canonical

ROOT = Path(__file__).resolve().parents[2]
A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
FILE = '1' * 32


def vector():return json.loads((ROOT / 'contracts/media-offer-v1-vectors.json').read_text())


def test_shared_media_offer_roundtrip_preserves_standard_offer_and_exact_reference():
    v = vector();message = v['message'];result = validate_media_offer(message, A, B, now=v['now'])
    assert len(canonical(message)) == v['canonical_bytes'] and sha256(canonical(message)).hexdigest() == v['canonical_sha256']
    assert validate_offer(result.offer, A, B, now=v['now']).fingerprint == result.manifest.fingerprint
    assert result.offer['message_id'] == message['message_id'] and result.originals[FILE]['original_size'] == 123
    assert create_media_offer(result.manifest, result.settings, result.media_type, result.mime_types, result.originals,
        now=v['now'], message_id=message['message_id']) == message
    result.settings['settings'].clear();assert message['body']['settings']['settings']
    with pytest.raises(TransferError):validate_offer(message, A, B, now=v['now'])


@pytest.mark.parametrize('case', ['unknown_header','unknown_body','expired','peer','fingerprint','missing_mime','foreign_mime',
    'wrong_mime_family','mime_parameters','missing_original','foreign_original','bad_size','float_size','bad_reference',
    'partial_settings','disabled','wrong_direction','import_only'])
def test_media_offer_holds_malformed_or_unrequested_metadata_before_native_io(case):
    v = vector();message = v['message'];body = message['body'];sender = A
    if case == 'unknown_header':message['extra'] = True
    elif case == 'unknown_body':body['confirmed'] = True
    elif case == 'expired':message['expires_ms'] = v['now']
    elif case == 'peer':sender = B
    elif case == 'fingerprint':body['offer']['manifest_sha256'] = '0' * 64
    elif case == 'missing_mime':body['mime_types'].clear()
    elif case == 'foreign_mime':body['mime_types']['f' * 32] = 'image/png'
    elif case == 'wrong_mime_family':body['mime_types'][FILE] = 'video/mp4'
    elif case == 'mime_parameters':body['mime_types'][FILE] = 'image/png; charset=utf-8'
    elif case == 'missing_original':body['originals'].clear()
    elif case == 'foreign_original':body['originals']['f' * 32] = deepcopy(body['originals'][FILE])
    elif case == 'bad_size':body['originals'][FILE]['original_size'] = True
    elif case == 'float_size':body['originals'][FILE]['original_size'] = 123.0
    elif case == 'bad_reference':body['originals'][FILE]['confirmed'] = True
    elif case == 'partial_settings':del body['settings']['settings']['photos_only']
    else:
        field, value = {'disabled':('enabled', False), 'wrong_direction':('direction','phone_to_pc'), 'import_only':('collection_mode','import_only')}[case]
        body['settings'] = change(body['settings'], A, B, field, value)
    with pytest.raises(TransferError):validate_media_offer(message, sender, B, now=v['now'])


def test_entire_collection_may_offer_new_members_without_inventing_phone_references():
    v = vector();body = v['message']['body'];body['settings'] = change(body['settings'], A, B, 'collection_mode', 'entire_collection')
    body['originals'].clear();assert not validate_media_offer(v['message'], A, B, now=v['now']).originals
