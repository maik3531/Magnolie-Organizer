"""Explicit historical lookup under real native service/catalog ownership."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_telefon import now_ms
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, accept, reconnect
from test_file_desktop_sources import status, response


@contextmanager
def original_job(fixture):
    accept(fixture)
    old = fixture[3]; job = old._run.receiver.job
    with reconnect(fixture) as fresh:
        status(fresh)
        fresh[3]._fixture_lookup_destination = {path.name: path.stat().st_ino for path in fresh[4].iterdir()}
        yield fresh, job


def request(fixture, job):
    connection = fixture[3]
    identity = connection.request_resume_lookup(connection.issue_receive_action(), job.owner)
    message = fixture[2].send.call_args.args[0]
    assert identity == message['message_id'] and message['kind'] == sources.REQUEST
    assert message['body']['source_id'] == job.accepted.manifest.source_id
    assert message['body']['transfer_id'] == job.accepted.manifest.transfer_id
    assert message['body']['manifest_sha256'] == job.accepted.manifest.fingerprint
    return message


def history(request, job, **changes):
    manifest = job.accepted.manifest
    value = dict(job_id='b' * 32, job_version='c' * 64, phase='sealed', source_id=manifest.source_id,
        transfer_id=manifest.transfer_id, manifest_sha256=manifest.fingerprint,
        remote_saved_history=False, attempt_phase='prepared')
    value.update(changes)
    result = response(request, sources.RESUME, version='b' * 64, history=value)
    result['expires_ms'] = min(result['expires_ms'], request['expires_ms'])
    return result


def assert_held(fixture, job):
    connection = fixture[3]
    assert connection._run is None and connection._source_run is None and connection._offer is None
    assert connection._catalog.jobs() == (job,)
    assert {path.name: path.stat().st_ino for path in fixture[4].iterdir()} == connection._fixture_lookup_destination


def test_explicit_native_lookup_after_reconnect_projects_only_history_without_stage_resume(receiving, monkeypatch):
    with original_job(receiving) as (fresh, job):
        def forbidden(*args, **kwargs): raise AssertionError('History cannot open or allocate a receive stage')
        monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume', forbidden)
        monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.accept', forbidden)
        message = request(fresh, job); result = history(message, job)
        fresh[0]._payload(fresh[1], fresh[2], result)
        projected = fresh[3].source_state()['resume_history']
        assert projected.job_id == 'b' * 32 and projected.attempt_phase == 'prepared'
        assert not hasattr(projected, 'ready') and not hasattr(projected, 'resumable')
        assert not fresh[3].source_state()['pending']; assert_held(fresh, job)


def test_native_lookup_lost_send_retries_exact_message_under_original_job_owner(receiving):
    with original_job(receiving) as (fresh, job):
        connection = fresh[3]; channel = fresh[2]
        channel.send.side_effect = OSError('fixture lookup secure output lost')
        with pytest.raises(OSError): request(fresh, job)
        held = deepcopy(connection._source_pending.message)
        assert not connection._source_pending.sent
        channel.send.side_effect = None
        connection.retry_source_command()
        assert channel.send.call_args.args[0] == held and connection._source_pending.sent
        fresh[0]._payload(fresh[1], channel, history(held, job))
        assert_held(fresh, job)


@pytest.mark.parametrize('change', ['source', 'transfer', 'manifest', 'request', 'deadline', 'ready'])
def test_native_lookup_rejects_foreign_or_fabricated_reply_without_losing_original(receiving, change):
    with original_job(receiving) as (fresh, job):
        message = request(fresh, job); result = history(message, job)
        if change in ('source', 'transfer', 'manifest'):
            key = {'source': 'source_id', 'transfer': 'transfer_id', 'manifest': 'manifest_sha256'}[change]
            result['body']['history'][key] = '9' * (64 if change == 'manifest' else 32)
        elif change == 'request': result['body']['request_id'] = str(uuid.uuid4())
        elif change == 'deadline':
            result['created_ms'] += 1000; result['expires_ms'] = message['expires_ms'] + 1000
        else: result['body']['history']['ready'] = True
        with pytest.raises(TransferError): fresh[0]._payload(fresh[1], fresh[2], result)
        assert fresh[3].source_state()['resume_history'] is None
        assert fresh[3].source_state()['pending']; assert_held(fresh, job)


def test_lookup_requires_requested_original_job_and_rejects_unasked_or_replayed_results(receiving):
    with original_job(receiving) as (fresh, job):
        connection = fresh[3]; count = fresh[2].send.call_count
        with pytest.raises(TransferError): connection.request_resume_lookup(connection.issue_receive_action(), '9' * 32)
        assert fresh[2].send.call_count == count
        fabricated = sources.create_command('resume_lookup', expected_version='b' * 64,
            source_id=job.accepted.manifest.source_id, transfer_id=job.accepted.manifest.transfer_id,
            manifest_sha256=job.accepted.manifest.fingerprint)
        with pytest.raises(TransferError): fresh[0]._payload(fresh[1], fresh[2], history(fabricated, job))
        message = request(fresh, job); result = history(message, job)
        fresh[0]._payload(fresh[1], fresh[2], result)
        before = connection.source_state()['resume_history']
        with pytest.raises(TransferError): fresh[0]._payload(fresh[1], fresh[2], result)
        assert connection.source_state()['resume_history'] == before; assert_held(fresh, job)


def test_lookup_authority_revocation_after_send_rejects_reply_and_retry(receiving):
    with original_job(receiving) as (fresh, job):
        message = request(fresh, job); connection = fresh[3]
        connection._authority.revoke()
        with pytest.raises(TransferError): connection.receive(history(message, job))
        with pytest.raises(TransferError): connection.retry_source_command()
        assert connection._resume_history is None and connection._run is None


def test_lookup_does_not_create_catalog_or_accept_arbitrary_action_without_original_job(receiving):
    status(receiving)
    connection = receiving[3]; count = receiving[2].send.call_count
    with pytest.raises(TransferError): connection.request_resume_lookup(object(), 'b' * 32)
    with pytest.raises(TransferError): connection.request_resume_lookup(connection.issue_receive_action(), 'b' * 32)
    assert connection._catalog is None and connection._source_pending is None
    assert receiving[2].send.call_count == count and not list(receiving[4].iterdir())


def test_lookup_cannot_cross_original_job_change_after_output_before_reply_or_retry(receiving, monkeypatch):
    with original_job(receiving) as (fresh, job):
        connection = fresh[3]
        message = request(fresh, job)
        monkeypatch.setattr(connection._catalog, 'jobs', lambda: ())
        with pytest.raises(TransferError): connection.receive(history(message, job))
        with pytest.raises(TransferError): connection.retry_source_command()
        assert connection._resume_history is None and connection._run is None


def test_lookup_expiry_after_actual_output_cannot_publish_sent_or_accept_historical_response(receiving):
    with original_job(receiving) as (fresh, job):
        connection = fresh[3]; wall = now_ms()
        def output(message):
            nonlocal wall
            if message['kind'] == sources.REQUEST: wall += 60_000
        fresh[2].send.side_effect = output
        with pytest.raises(TransferError):
            connection.request_resume_lookup(connection.issue_receive_action(), job.owner, clock=lambda:wall)
        pending = connection._source_pending
        assert pending is not None and not pending.sent
        fresh[2].send.side_effect = None
        with pytest.raises(TransferError): connection.retry_source_command(clock=lambda:wall)
        with pytest.raises(TransferError): connection.receive(history(pending.message, job), clock=lambda:wall)
        assert connection._resume_history is None; assert_held(fresh, job)


def test_active_receiver_or_foreign_old_action_cannot_launch_historical_lookup(receiving):
    accept(receiving)
    connection = receiving[3]; job = connection._run.receiver.job; before = receiving[2].send.call_count
    with pytest.raises(TransferError): connection.request_resume_lookup(connection.issue_receive_action(), job.owner)
    assert receiving[2].send.call_count == before
    old_action = connection.issue_receive_action()
    with reconnect(receiving) as fresh:
        status(fresh)
        before = fresh[2].send.call_count
        with pytest.raises(TransferError): fresh[3].request_resume_lookup(old_action, job.owner)
        assert fresh[2].send.call_count == before and fresh[3]._run is None
