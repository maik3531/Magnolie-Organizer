"""Refs #330: shared whole-offer codecs only, never native proof fixtures."""
from dataclasses import replace
from pathlib import Path
import copy
import json
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_control import MAX_WIRE_BYTES
from magnolie_file_offer import create_offer
from magnolie_file_transfer import FileManifest, MAX_FILES, NativeTransferBinding, TransferError
from magnolie_file_published_batch_readback import CONTEXT, destination_token, encode_body, parse_batch_readback
from magnolie_file_published_readback import parse_readback
from magnolie_telefon import APPLICATION_MAX, canonical


def vector(): return json.loads((Path(__file__).resolve().parents[2] / 'contracts/file-published-readback-batch-v2-vectors.json').read_text())
def binding(v): return NativeTransferBinding(**v['binding'])
def context(v): return {key: copy.deepcopy(v['message']['body'][key]) for key in CONTEXT}
def parse(v): return parse_batch_readback(v['message'], v['offer'], binding(v), 'images', now=v['now_ms'])
def rebound(v, c):
    b = replace(binding(v), destination_token=destination_token(c))
    v['binding']['destination_token'] = b.destination_token
    v['message']['body'] = encode_body(c, b)


def test_three_shared_digest_domains_complete_members_and_defensive_data_only_copy():
    v = vector(); c = context(v); b = binding(v)
    assert destination_token(c) == b.destination_token and encode_body(c, b) == v['message']['body']
    result = parse(v)
    assert result.body == v['message']['body'] and not result.grants_write_authority and not result.is_saved_receipt and not result.allows_chunk_output
    altered = result.body; altered['members'].clear(); assert len(result.body['members']) == 2
    with pytest.raises(TransferError): parse_readback(v['message'], v['offer'], b, 'images', now=v['now_ms'])


def test_whole_readback_uses_the_application_limit_for_all_manifest_members():
    v = vector()
    c = context(v)
    raw_manifest = v['offer']['body']['manifest']
    raw_manifest['files'] = [
        dict(id=f'{index:032x}', path=f'Camera/{index}.png', size=123, sha256='a' * 64)
        for index in range(MAX_FILES)
    ]
    raw_manifest['total_bytes'] = 123 * MAX_FILES
    manifest = FileManifest.parse(raw_manifest)
    v['offer'] = create_offer(manifest, now=v['offer']['created_ms'], message_id=c['offer_id'])
    c['manifest_sha256'] = manifest.fingerprint
    c['members'] = {
        file.id: dict(size=file.size, sha256=file.sha256, mime_type='image/png',
                      publication_sha256=f'{index:064x}', row_sha256=f'{index + MAX_FILES:064x}')
        for index, file in enumerate(manifest.files)
    }
    rebound(v, c)
    assert MAX_WIRE_BYTES < len(canonical(v['message'])) < APPLICATION_MAX
    assert parse(v).body['members'] == c['members']


@pytest.mark.parametrize('change', ['subset', 'extra_id', 'wrong_size', 'wrong_sha', 'wrong_manifest', 'wrong_offer', 'wrong_transfer', 'wrong_source', 'wrong_kind'])
def test_rehashed_whole_context_still_requires_the_entire_original_offer(change):
    v = vector(); c = context(v); ids = list(c['members'])
    if change == 'subset': del c['members'][ids[1]]
    elif change == 'extra_id': c['members']['6' * 32] = c['members'].pop(ids[1])
    elif change == 'wrong_size': c['members'][ids[1]]['size'] += 1
    elif change == 'wrong_sha': c['members'][ids[1]]['sha256'] = '0' * 64
    elif change == 'wrong_manifest': c['manifest_sha256'] = '0' * 64
    elif change == 'wrong_offer': c['offer_id'] = '99999999-9999-4999-8999-999999999999'
    elif change == 'wrong_transfer': c['transfer_id'] = '0' * 32
    elif change == 'wrong_source': c['source_id'] = '0' * 32
    else:
        c['media_type'] = 'video'
        for member in c['members'].values(): member['mime_type'] = 'video/mp4'
    rebound(v, c)
    with pytest.raises(TransferError): parse(v)


@pytest.mark.parametrize('field,value', [('size', True), ('size', '456'), ('size', 456.0), ('size', 0), ('size', -1), ('size', None),
    ('sha256', 'A' * 64), ('mime_type', 'video/mp4'), ('allows_write', True)])
def test_member_types_and_unknown_rights_cannot_be_encoded(field, value):
    v = vector(); c = context(v); c['members'][list(c['members'])[1]][field] = value
    with pytest.raises(TransferError): destination_token(c)


@pytest.mark.parametrize('change', ['publication_alias', 'row_alias', 'empty', 'array', 'format_bool', 'format_string', 'format_v1', 'extra_root', 'too_many', 'total_budget'])
def test_aliases_and_unbounded_or_nonbatch_contexts_are_denied(change):
    v = vector(); c = context(v); ids = list(c['members'])
    if change.endswith('_alias'):
        key = 'publication_sha256' if change == 'publication_alias' else 'row_sha256'
        c['members'][ids[1]][key] = c['members'][ids[0]][key]
    elif change == 'empty': c['members'] = {}
    elif change == 'array': c['members'] = list(c['members'].values())
    elif change == 'format_bool': c['format'] = True
    elif change == 'format_string': c['format'] = '2'
    elif change == 'format_v1': c['format'] = 1
    elif change == 'extra_root': c['grants_write_authority'] = True
    else:
        count = 129 if change == 'too_many' else 9
        c['members'] = {f'{i:032x}': dict(size=1 if change == 'too_many' else 50 * 1024 * 1024,
            sha256='a' * 64, mime_type='image/png', publication_sha256=f'{i:064x}', row_sha256=f'{i + 1024:064x}') for i in range(count)}
    with pytest.raises(TransferError): destination_token(c)


@pytest.mark.parametrize('change', ['binding', 'expired', 'future_offer', 'later_expiry', 'extra_header', 'wrong_wire_kind', 'digest', 'created_before_offer'])
def test_original_header_binding_lifetime_and_digest_are_independent_guards(change):
    v = vector()
    if change == 'binding': v['binding']['receiver_identity_sha256'] = '0' * 64
    elif change == 'expired': v['message']['expires_ms'] = v['now_ms']
    elif change == 'future_offer': v['offer']['created_ms'] = v['now_ms'] + 1
    elif change == 'later_expiry': v['message']['expires_ms'] = v['offer']['expires_ms'] + 1
    elif change == 'extra_header': v['message']['allows_write'] = True
    elif change == 'wrong_wire_kind': v['message']['kind'] = 'file_transfer.saved'
    elif change == 'digest': v['message']['body']['readback_sha256'] = '0' * 64
    else:
        v['message']['created_ms'] = v['offer']['created_ms'] - 1
        v['message']['expires_ms'] -= 1
    with pytest.raises(TransferError): parse(v)


def test_single_root_nonce_changes_all_domains_without_changing_the_original_offer():
    v = vector(); c = context(v); original = copy.deepcopy(v['offer']); old = v['message']['body']
    c['readback_nonce'] = '2' * 64; rebound(v, c)
    assert parse(v).body == v['message']['body'] and v['offer'] == original
    for key in ('destination_token', 'binding_sha256', 'readback_sha256'): assert old[key] != v['message']['body'][key]
