"""Strict protocol UUID validation, not native identity/grant construction."""
from copy import deepcopy
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_telefon import valid_uuid
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError

NOW = 1_800_000_000_000
ID = '11111111-1111-4111-8111-111111111111'


def test_missing_uuid_is_invalid_not_a_type_error():
    assert valid_uuid(None) is False


@pytest.mark.parametrize('value', [True, False, 0, 1, 1.5, b'11111111-1111-4111-8111-111111111111', [], {}, uuid.UUID(ID)])
def test_nonstring_uuid_values_never_become_protocol_identifiers(value):
    assert valid_uuid(value) is False


def test_canonical_uuid_and_requested_version_rules_are_preserved():
    assert valid_uuid(ID) and valid_uuid(ID, version=4)
    assert not valid_uuid(ID, version=1)
    for value in [ID.replace('-', ''), '{' + ID + '}', 'urn:uuid:' + ID, ' ' + ID, ID + ' ', '', 'not-uuid']:
        assert not valid_uuid(value)
    with_letters = 'abcdefab-abcd-4abc-8abc-abcdefabcdef'
    assert valid_uuid(with_letters, version=4)
    assert not valid_uuid(with_letters.upper())


@pytest.mark.parametrize('field', ['message_id', 'run_id', 'catalog_id', 'album_id'])
def test_missing_normal_source_ids_raise_transfer_error_without_mutating_input(field):
    if field in ('catalog_id', 'album_id'):
        message = sources.create_command('run', expected_version='a' * 64, catalog_id=ID, album_id=ID,
                                         desktop_choice=True, now=NOW)
    else:
        message = sources.create_command('run_status', expected_version='a' * 64, run_id=ID, now=NOW)
    if field == 'message_id': message[field] = None
    else: message['body'][field] = None
    before = deepcopy(message)
    with pytest.raises(TransferError): sources.parse_command(message, now=NOW)
    assert message == before
