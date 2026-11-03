from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError

NOW = 1_800_000_000_000
ID = "11111111-1111-4111-8111-111111111111"


def configure():
    return sources.create_command("configure", expected_version="a" * 64, enabled=True,
                                  kinds=("camera", "screenshots"), now=NOW, message_id=ID)


def result():
    message = sources.create_command("status", now=NOW, message_id=ID)
    message["kind"] = sources.RESULT
    message["body"] = dict(format=1, request_id=ID, operation="configure", version="b" * 64, revision=2,
                           enabled=True, associated=True, repair_pending=False, kinds=["camera"])
    return message


def test_strict_status_and_configure_roundtrip_is_metadata_only():
    command = configure()
    before = deepcopy(command)
    parsed = sources.parse_command(command, now=NOW)
    assert parsed.kinds == ("camera", "screenshots") and parsed.expected_version == "a" * 64
    assert command == before
    assert sources.parse_command(sources.create_command("status", now=NOW), now=NOW).operation == "status"


@pytest.mark.parametrize('key,value', [('enabled', 1), ('enabled', 'true'), ('format', True),
    ('expected_version', 'absent'), ('kinds', ['camera', 'camera']), ('kinds', ['screenshots', 'camera']),
    ('kinds', ['CAMERA']), ('kinds', []), ('send_files', True), ('read_granted', True), ('automatic', True), ('path', '/personal')])
def test_aliases_extra_authority_and_unordered_selection_fail(key, value):
    command = configure(); command['body'][key] = value
    with pytest.raises(TransferError): sources.parse_command(command, now=NOW)


@pytest.mark.parametrize('operation', ['run', 'delete', 'grant_read'])
def test_unsupported_actions_cannot_be_disguised_as_metadata(operation):
    with pytest.raises(TransferError): sources.create_command(operation, now=NOW)


def test_deadline_and_whole_envelope_are_strict():
    command = configure()
    with pytest.raises(TransferError): sources.parse_command(command, now=NOW + 60_000)
    command['body']['oversized'] = 'x' * 9000
    with pytest.raises(TransferError): sources.parse_command(command, now=NOW)


def test_result_is_correlated_immutable_metadata_not_a_native_grant():
    status = sources.parse_result(result(), expected_request_id=ID, expected_operation='configure', now=NOW)
    assert status.enabled and status.associated and status.kinds == ('camera',)
    assert not hasattr(status, 'send_files') and not hasattr(status, 'read_granted')
    with pytest.raises(TransferError):
        sources.parse_result(result(), expected_request_id='22222222-2222-4222-8222-222222222222', expected_operation='configure', now=NOW)


@pytest.mark.parametrize('key,value', [('revision', True), ('revision', -1), ('revision', 0), ('enabled', 1),
    ('associated', 'true'), ('operation', 'run'), ('read_granted', True), ('kinds', ['camera', 'camera'])])
def test_corrupt_status_never_becomes_accepted_state(key, value):
    message = result(); message['body'][key] = value
    with pytest.raises(TransferError): sources.parse_result(message, expected_request_id=ID, expected_operation='configure', now=NOW)


def test_shared_source_command_golden_matches_canonical_bytes():
    vector = json.loads((Path(__file__).resolve().parents[2] / 'contracts/file-transfer-sources-v1-vectors.json').read_text())
    assert configure() == vector['configure']
    wire = sources.canonical(configure())
    assert len(wire) == vector['canonical_bytes']
    assert hashlib.sha256(wire).hexdigest() == vector['canonical_sha256']
    assert sources.parse_command(vector['configure'], now=vector['now_ms']).kinds == ('camera', 'screenshots')


def offer_result():
    message = result()
    message['kind'] = sources.RUN_RESULT
    message['body'] = dict(format=1, request_id=ID, operation='offer_run', version='a'*64, run_id=ID,
                           state='snapshot_ready', source_io_ended=True, offer_id=ID, manifest_sha256='b'*64)
    return message


def parse_offer(message, **options):
    return sources.parse_run_result(message, expected_request_id=options.get('request', ID),
        expected_operation=options.get('operation', 'offer_run'), expected_version=options.get('version', 'a'*64),
        expected_run_id=options.get('run', ID), now=options.get('now', NOW))


def test_offer_request_binds_exact_policy_and_native_run_but_never_selects_an_offer():
    command = sources.create_command('offer_run', expected_version='a'*64, run_id=ID, now=NOW)
    parsed = sources.parse_command(command, now=NOW)
    assert parsed.run_id == ID and parsed.expected_version == 'a'*64
    for key, value in [('offer_id', ID), ('manifest_sha256', 'b'*64), ('run_id', 'path'), ('read_granted', True)]:
        changed = deepcopy(command); changed['body'][key] = value
        with pytest.raises(TransferError): sources.parse_command(changed, now=NOW)
    with pytest.raises(TransferError): sources.create_command('offer_run', expected_version='a'*64, run_id=ID, enabled=True, now=NOW)


def test_offer_result_is_exact_ready_output_metadata_not_a_save_or_grant():
    parsed = parse_offer(offer_result())
    assert parsed.offer_id == ID and parsed.manifest_sha256 == 'b'*64
    assert not hasattr(parsed, 'saved') and not hasattr(parsed, 'read_granted')
    for missing in ('offer_id', 'manifest_sha256'):
        changed = offer_result(); del changed['body'][missing]
        with pytest.raises(TransferError): parse_offer(changed)


@pytest.mark.parametrize('key,value', [('offer_id', 'path'), ('manifest_sha256', 'B'*64),
    ('source_io_ended', False), ('source_io_ended', 1), ('state', 'preparing'), ('state', 'failed_held'),
    ('state', 'canceled_held'), ('success', True), ('operation', 'run_status')])
def test_offer_output_fields_cannot_be_aliased_or_added_to_other_run_results(key, value):
    changed = offer_result(); changed['body'][key] = value
    with pytest.raises(TransferError): parse_offer(changed)


@pytest.mark.parametrize('option,value', [('request', '22222222-2222-4222-8222-222222222222'),
    ('run', '22222222-2222-4222-8222-222222222222'), ('version', 'c'*64),
    ('operation', 'run_status'), ('now', NOW+60_000)])
def test_offer_result_cannot_escape_original_command_correlation_or_deadline(option, value):
    with pytest.raises(TransferError): parse_offer(offer_result(), **{option: value})
