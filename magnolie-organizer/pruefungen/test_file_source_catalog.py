from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError

NOW = 1_800_000_000_000
REQUEST_ID = '11111111-1111-4111-8111-111111111111'
CATALOG_ID = '22222222-2222-4222-8222-222222222222'
ALBUM_ID = '33333333-3333-4333-8333-333333333333'


def catalog():
    message = sources.create_command('discover', expected_version='a' * 64, now=NOW, message_id=REQUEST_ID)
    message['kind'] = sources.CATALOG
    message['body'] = dict(format=1, request_id=REQUEST_ID, operation='discover', version='a' * 64,
        page=dict(format=1, catalog_id=CATALOG_ID, after=0, next_cursor=None, coverage='full_images', proves_deletion=False,
                  albums=[dict(album_id=ALBUM_ID, kind='camera', display_name='Camera', visible_images=3, needs_choice=False)]))
    return message


def parse(message, **options):
    return sources.parse_catalog(message, expected_request_id=REQUEST_ID, expected_operation='discover',
                                 expected_version='a' * 64, now=NOW, **options)


def test_discovery_and_page_requests_have_exact_policy_version_and_no_source_grants():
    request = sources.create_command('discover', expected_version='a' * 64, now=NOW)
    assert sources.parse_command(request, now=NOW).operation == 'discover'
    page = sources.create_command('catalog_page', expected_version='a' * 64, catalog_id=CATALOG_ID, after=1, now=NOW)
    parsed = sources.parse_command(page, now=NOW)
    assert parsed.catalog_id == CATALOG_ID and parsed.after == 1
    for key, value in [('after', True), ('after', -1), ('after', 129), ('catalog_id', '/private/path'), ('read_granted', True)]:
        invalid = deepcopy(page); invalid['body'][key] = value
        with pytest.raises(TransferError): sources.parse_command(invalid, now=NOW)


def test_catalog_is_correlated_immutable_display_metadata_not_a_read_or_delete_grant():
    message = catalog(); before = deepcopy(message)
    result = parse(message)
    assert result.catalog_id == CATALOG_ID and result.albums[0].display_name == 'Camera'
    assert not hasattr(result, 'read_granted') and not hasattr(result, 'proves_deletion')
    assert message == before
    message['body']['request_id'] = CATALOG_ID
    with pytest.raises(TransferError): parse(message)


@pytest.mark.parametrize('key,value', [('proves_deletion', True), ('proves_deletion', 0), ('after', True), ('after', 1),
    ('next_cursor', True), ('next_cursor', 0), ('next_cursor', 2), ('coverage', 'unrestricted'),
    ('catalog_id', '/private/path'), ('path', '/private/path'), ('format', True)])
def test_invalid_cursor_scope_or_deletion_claim_is_rejected(key, value):
    message = catalog(); message['body']['page'][key] = value
    with pytest.raises(TransferError): parse(message)


@pytest.mark.parametrize('key,value', [('album_id', 'technical-bucket'), ('kind', 'CAMERA'), ('display_name', ''),
    ('display_name', 'x' * 257), ('display_name', 'bad\nlabel'), ('visible_images', True), ('visible_images', 50001),
    ('needs_choice', 1), ('tree_uri', 'content://private')])
def test_album_fields_cannot_smuggle_authority_paths_or_unbounded_metadata(key, value):
    message = catalog(); message['body']['page']['albums'][0][key] = value
    with pytest.raises(TransferError): parse(message)


def test_duplicated_ids_and_hidden_visibility_do_not_become_an_inventory():
    message = catalog(); message['body']['page']['albums'] *= 2
    with pytest.raises(TransferError): parse(message)
    message = catalog(); message['body']['page']['coverage'] = 'none'
    with pytest.raises(TransferError): parse(message)
    message['body']['page']['albums'] = []
    assert parse(message).albums == ()


def test_page_reply_must_match_native_catalog_and_requested_cursor():
    message = catalog(); message['body']['operation'] = 'catalog_page'; message['body']['page']['after'] = 1
    result = sources.parse_catalog(message, expected_request_id=REQUEST_ID, expected_operation='catalog_page',
        expected_version='a' * 64, expected_catalog_id=CATALOG_ID, expected_after=1, now=NOW)
    assert result.after == 1
    with pytest.raises(TransferError):
        sources.parse_catalog(message, expected_request_id=REQUEST_ID, expected_operation='catalog_page',
            expected_version='a' * 64, expected_catalog_id=REQUEST_ID, expected_after=1, now=NOW)
