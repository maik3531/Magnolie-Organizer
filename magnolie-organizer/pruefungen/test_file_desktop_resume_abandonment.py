"""Explicit local stop + source END + exact historical head, never tokens alone."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_receive_stop import resumed
from test_file_desktop_resume_sources import cancel, ended, request, start, collect, offer, held, selected
from test_file_desktop_resume_lookup import history
from test_file_desktop_sources import response, catalog
from test_file_desktop_media import dispatch


@contextmanager
def stopped(fixture):
    with resumed(fixture) as (fresh, job, original):
        connection = fresh[3]
        assert connection.request_receive_stop(connection.issue_receive_action()).state == 'stopped'
        cancel(fresh); command = request(fresh, 'end_resume'); dispatch(fresh, ended(command))
        connection.request_resume_lookup(connection.issue_receive_action(), job.owner)
        lookup = fresh[2].send.call_args.args[0]
        dispatch(fresh, history(lookup, job, attempt_phase='accepted'))
        yield fresh, job, original


def abandon(fixture):
    connection = fixture[3]
    connection.request_resume_abandonment(connection.issue_receive_action())
    return fixture[2].send.call_args.args[0]


def receipt(command):
    body = command['body']
    result = response(command, sources.ABANDONED, version=body['expected_version'], run_id=body['run_id'],
        job_id=body['original_job_id'], job_version=body['original_job_version'], attempt_id=body['attempt_id'],
        attempt_sha256=body['attempt_sha256'], receipt_sha256='e' * 64)
    result['expires_ms'] = min(result['expires_ms'], command['expires_ms'])
    return result


def test_explicit_local_stop_end_and_abandonment_receipt_allow_only_new_original_stage_resume(receiving, monkeypatch):
    with stopped(receiving) as (fresh, job, original):
        connection = fresh[3]; command = abandon(fresh)
        assert command['body']['attempt_id'] == connection._resume_history.attempt_id
        assert connection._resume_abandonment is None
        dispatch(fresh, receipt(command))
        assert connection._resume_abandonment.receipt_sha256 == 'e' * 64
        assert connection._run is None and connection._source_run is None
        monkeypatch.setattr('test_file_desktop_resume_sources.RESUME_RUN', '66666666-6666-4666-8666-666666666666')
        catalog(fresh); start(fresh); collect(fresh, job); offered = offer(fresh, job)
        connection.resume_pending_offer(connection.issue_receive_action(), offered['message_id'], job.owner)
        assert connection.receive_progress().checkpoint_verified_bytes == 5
        assert connection._run.receiver._index.media_history == original
        assert connection._run.accepted == job.accepted
        held(fresh, job)


def test_pending_history_tokens_without_local_receiver_stop_and_source_end_cannot_repair(receiving):
    with selected(receiving, hints=dict(attempt_phase='accepted')) as (fresh, job, _):
        count = fresh[2].send.call_count
        with pytest.raises(TransferError, match='proof_required'):
            fresh[3].request_resume_abandonment(fresh[3].issue_receive_action())
        assert fresh[2].send.call_count == count and fresh[3]._resume_abandonment is None
        held(fresh, job)


def test_lost_abandonment_output_retries_exact_native_intent_without_early_new_attempt(receiving):
    with stopped(receiving) as (fresh, job, _):
        connection = fresh[3]
        fresh[2].send.side_effect = OSError('fixture abandonment output uncertain')
        with pytest.raises(OSError): abandon(fresh)
        command = deepcopy(connection._source_pending.message)
        assert connection._resume_abandonment is None
        fresh[2].send.side_effect = None; connection.retry_source_command()
        assert fresh[2].send.call_args.args[0] == command
        dispatch(fresh, receipt(command))
        assert connection._resume_abandonment is not None
        held(fresh, job)


@pytest.mark.parametrize('field', ['attempt_id', 'attempt_sha256', 'job_id', 'job_version', 'run_id', 'request_id', 'receipt_sha256'])
def test_changed_receipt_binding_never_releases_pending_head_hold(receiving, field):
    with stopped(receiving) as (fresh, job, _):
        connection = fresh[3]; command = abandon(fresh); result = receipt(command)
        result['body'][field] = None
        with pytest.raises(TransferError): dispatch(fresh, result)
        assert connection._resume_abandonment is None and connection._source_pending is not None
        assert connection._run is None and connection._source_run is None
        held(fresh, job)


def test_abandonment_codec_rejects_ignored_options_and_nonliteral_tokens():
    options = dict(expected_version='b' * 64, run_id='55555555-5555-4555-8555-555555555555',
        original_job_id='b' * 32, original_job_version='c' * 64,
        attempt_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', attempt_sha256='d' * 64)
    message = sources.create_command('abandon_resume', **options)
    parsed = sources.parse_command(message)
    assert parsed.attempt_sha256 == 'd' * 64
    for key, value in [('attempt_id', None), ('attempt_sha256', True), ('original_job_version', None),
                       ('run_id', None), ('path', '/private')]:
        changed = deepcopy(message); changed['body'][key] = value
        with pytest.raises(TransferError): sources.parse_command(changed)
    for key in ('run_ended', 'ready', 'read_granted'):
        result = receipt(message); result['body'][key] = True
        with pytest.raises(TransferError): sources.parse_resume_abandonment(result, parsed)
    with pytest.raises(TransferError): sources.create_command('status', attempt_id=options['attempt_id'])
