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


def resume_vector():
    return json.loads((Path(__file__).resolve().parents[2] / 'contracts/file-transfer-resume-sources-v1-vectors.json').read_text())


@pytest.mark.parametrize('index', range(7))
def test_shared_resume_command_goldens_roundtrip_without_native_authority(index):
    vector = resume_vector(); message = vector['commands'][index]; before = deepcopy(message)
    command = sources.parse_command(message, now=vector['now_ms'])
    assert hashlib.sha256(sources.canonical(message)).hexdigest() == vector['canonical_sha256'][index]
    options = dict(message['body']); operation = options.pop('operation'); options.pop('format')
    assert sources.create_command(operation, **options, now=NOW, message_id=message['message_id']) == message
    assert command.operation == operation and message == before
    assert not hasattr(command, 'read_granted') and not hasattr(command, 'allows_chunk_output')


@pytest.mark.parametrize('field,value', [('original_job_id', True), ('original_job_id', 'b' * 31),
    ('original_job_id', 'B' * 32), ('original_job_version', True), ('original_job_version', 'c' * 63),
    ('desktop_choice', 1), ('desktop_choice', 'true'), ('album_id', '/private'), ('catalog_id', None), ('album_id', None), ('run_id', ID),
    ('read_granted', True), ('quota_retired', True), ('path', 'DCIM/Camera')])
def test_resume_command_rejects_wrong_original_context_types_and_authority_fields(field, value):
    message = deepcopy(resume_vector()['commands'][0]); message['body'][field] = value
    with pytest.raises(TransferError): sources.parse_command(message, now=NOW)


@pytest.mark.parametrize('operation', ['status', 'run', 'run_status', 'offer_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume'])
def test_resume_original_context_cannot_be_silently_ignored_by_other_command_builders(operation):
    with pytest.raises(TransferError):
        sources.create_command(operation, expected_version='a' * 64, run_id=ID,
                               original_job_id='b' * 32, original_job_version='c' * 64, now=NOW)


@pytest.mark.parametrize('operation', ['resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume'])
def test_resume_results_correlate_exact_operation_owner_and_metadata_only_state(operation):
    message = sources.create_command('status', now=NOW, message_id=ID)
    message['kind'] = sources.RUN_RESULT
    body = dict(format=1, request_id=ID, operation=operation, version='a' * 64, run_id=ID,
                state='canceled_held' if operation in ('cancel_resume', 'end_resume') else 'snapshot_ready', source_io_ended=True)
    if operation == 'offer_resume': body.update(offer_id=ID, manifest_sha256='b' * 64)
    if operation == 'end_resume': body['run_ended'] = True
    message['body'] = body
    options = dict(expected_request_id=ID, expected_operation=operation, expected_version='a' * 64, now=NOW)
    if operation != 'resume_run': options['expected_run_id'] = ID
    parsed = sources.parse_run_result(message, **options)
    assert parsed.operation == operation and parsed.source_io_ended
    for key, value in [('operation', 'run' if operation == 'resume_run' else 'offer_run'), ('run_id', '22222222-2222-4222-8222-222222222222'),
                       ('request_id', None), ('run_id', None), ('source_io_ended', 1), ('state', 'synchronized'), ('saved', True), ('quota_retired', True)]:
        changed = deepcopy(message); changed['body'][key] = value
        if operation == 'resume_run' and key == 'run_id':
            with pytest.raises(TransferError): sources.parse_run_result(changed, **dict(options, expected_run_id=ID))
        else:
            with pytest.raises(TransferError): sources.parse_run_result(changed, **options)
    with pytest.raises(TransferError): sources.parse_run_result(message, **dict(options, now=NOW + 60_000))


def resume_history():
    command = deepcopy(resume_vector()['commands'][4]); command['kind'] = sources.RESUME
    command['body'] = dict(format=1, request_id=command['message_id'], operation='resume_lookup', version='a' * 64,
        history=dict(job_id='b' * 32, job_version='c' * 64, phase='sealed', source_id='d' * 32, transfer_id='e' * 32,
                     manifest_sha256='f' * 64, remote_saved_history=False, attempt_phase='prepared'))
    return command


def history_options():
    return dict(expected_request_id=resume_vector()['commands'][4]['message_id'], expected_version='a' * 64,
                expected_source_id='d' * 32, expected_transfer_id='e' * 32, expected_manifest_sha256='f' * 64, now=NOW)


@pytest.mark.parametrize('phase', [None, 'prepared', 'sent', 'accepted'])
def test_resume_lookup_history_is_only_a_correlated_hint_not_read_or_run_readiness(phase):
    message = resume_history(); message['body']['history']['attempt_phase'] = phase
    before = deepcopy(message); history = sources.parse_resume_history(message, **history_options())
    assert history.job_id == 'b' * 32 and history.attempt_phase == phase
    assert not hasattr(history, 'ready') and not hasattr(history, 'resumable') and not hasattr(history, 'allows_chunk_output')
    assert before == message
    with pytest.raises(TransferError): sources.parse_resume_history(message, **dict(history_options(), now=NOW + 60_000))


@pytest.mark.parametrize('field,value', [('job_id', True), ('job_version', 'c' * 63), ('phase', 'reserved'),
    ('source_id', '9' * 32), ('transfer_id', '9' * 32), ('manifest_sha256', '9' * 64), ('remote_saved_history', 1),
    ('attempt_phase', 'ready'), ('ready', True), ('path', '/personal'), ('read_granted', True)])
def test_resume_lookup_rejects_foreign_manifest_or_fabricated_authority_and_history_fields(field, value):
    message = resume_history(); message['body']['history'][field] = value
    with pytest.raises(TransferError): sources.parse_resume_history(message, **history_options())


@pytest.mark.parametrize('operation', ['status', 'run', 'resume_run', 'offer_resume'])
def test_resume_lookup_context_cannot_be_injected_into_other_command_builders(operation):
    with pytest.raises(TransferError): sources.create_command(operation, expected_version='a' * 64,
        source_id='d' * 32, transfer_id='e' * 32, manifest_sha256='f' * 64, now=NOW)


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
