"""Original native receiver + explicit new source ownership, never a new job."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, reconnect, chunk
from test_file_desktop_sources import request, status, catalog, response, ALBUM
from test_file_desktop_media import dispatch, media
from test_file_media_history import admit
from test_file_desktop_resume_lookup import history as lookup_reply, original_job

RESUME_RUN = '55555555-5555-4555-8555-555555555555'


@contextmanager
def selected(fixture, *, hints=None, partial=False):
    receiver = admit(fixture, count=2 if partial else 1)
    job = receiver.job; original_history = receiver._index.media_history
    if partial:
        receiver.receive_chunk(job.accepted.manifest.files[0].id, 0, b'hello'); receiver.checkpoint()
    with reconnect(fixture) as fresh:
        connection = fresh[3]; status(fresh)
        connection.request_resume_lookup(connection.issue_receive_action(), job.owner)
        message = fresh[2].send.call_args.args[0]
        result = lookup_reply(message, job, attempt_phase=None)
        result['body']['history'].update(hints or {})
        dispatch(fresh, result); catalog(fresh)
        yield fresh, job, original_history


def start(fixture):
    message = request(fixture, 'resume_run', album_id=ALBUM, desktop_choice=True)
    assert message['body']['original_job_id'] == 'b' * 32
    assert message['body']['original_job_version'] == 'c' * 64
    result = response(message, sources.RUN_RESULT, version='b' * 64, run_id=RESUME_RUN,
                      state='snapshot_ready', source_io_ended=True)
    result['expires_ms'] = min(result['expires_ms'], message['expires_ms'])
    dispatch(fixture, result)
    return message


def collect(fixture, job, change=None):
    full = job.accepted.manifest
    for after in range(0, len(full.files), 8):
        message = request(fixture, 'resume_media_page')
        assert message['body']['run_id'] == RESUME_RUN and message['body']['after'] == after
        value = media(message, full, after); value['body']['run_id'] = RESUME_RUN
        if change == 'epoch': value['body']['page']['source_epoch'] = '9' * 64
        elif change == 'photo': value['body']['page']['entries'][0]['photo_id'] = '9' * 64
        elif change == 'kind': value['body']['page']['entries'][0]['media_kind'] = 'unknown_image'
        dispatch(fixture, value)


def offer(fixture, job):
    message = request(fixture, 'offer_resume')
    offered = create_offer(job.accepted.manifest); offered['expires_ms'] = min(offered['expires_ms'], message['expires_ms'])
    dispatch(fixture, offered)
    result = response(message, sources.RUN_RESULT, version='b' * 64, run_id=RESUME_RUN, state='snapshot_ready',
                      source_io_ended=True, offer_id=offered['message_id'], manifest_sha256=job.accepted.manifest.fingerprint)
    result['expires_ms'] = min(result['expires_ms'], offered['expires_ms'])
    dispatch(fixture, result)
    return offered


def held(fixture, job):
    assert fixture[3]._catalog.jobs() == (job,)
    assert {path.name for path in fixture[4].iterdir()} == {'.magnolie-publication-' + job.owner}


def test_original_stage_checkpoint_and_acceptance_survive_lookup_resume_source_media_and_new_offer(receiving):
    with selected(receiving, partial=True) as (fresh, job, original_history):
        connection = fresh[3]
        start(fresh); collect(fresh, job); offered = offer(fresh, job)
        connection.resume_pending_offer(connection.issue_receive_action(), offered['message_id'], job.owner)
        progress = connection.receive_progress()
        assert progress.verified_bytes == 5 and progress.checkpoint_verified_bytes == 5
        assert connection._run.accepted == job.accepted and connection._run.receiver._index.media_history == original_history
        acceptance = fresh[2].send.call_args.args[0]
        assert acceptance['body']['offer_id'] == offered['message_id']
        assert acceptance['body']['acceptance_sha256'] == job.accepted.fingerprint
        next_request = connection.request_next_chunk()
        assert next_request['body']['file_id'] == job.accepted.manifest.files[1].id
        dispatch(fresh, chunk(next_request, b'hello'))
        assert connection.receive_progress().verified_bytes == 10
        assert connection._source_run.run_id == RESUME_RUN
        assert connection._run.receiver._index.media_history == original_history
        held(fresh, job)


@pytest.mark.parametrize('hints', [dict(phase='retired'), dict(remote_saved_history=True),
    dict(attempt_phase='prepared'), dict(attempt_phase='sent'), dict(attempt_phase='accepted')])
def test_saved_retired_or_persisted_phone_attempt_hints_require_reconcile_not_new_source_adoption(receiving, hints):
    with selected(receiving, hints=hints) as (fresh, job, _):
        count = fresh[2].send.call_count
        with pytest.raises(TransferError, match='history_requires_reconcile'):
            request(fresh, 'resume_run', album_id=ALBUM, desktop_choice=True)
        assert fresh[2].send.call_count == count and fresh[3]._source_run is None and fresh[3]._run is None
        held(fresh, job)


@pytest.mark.parametrize('change', ['epoch', 'photo', 'kind'])
def test_changed_original_media_association_is_held_before_opening_original_receive_stage(receiving, monkeypatch, change):
    with selected(receiving) as (fresh, job, _):
        start(fresh); collect(fresh, job, change); offered = offer(fresh, job)
        def forbidden(*args, **kwargs): raise AssertionError('Changed associations cannot restore a stage')
        monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume', forbidden)
        with pytest.raises(TransferError, match='resume_media_association_changed'):
            fresh[3].resume_pending_offer(fresh[3].issue_receive_action(), offered['message_id'], job.owner)
        assert fresh[3]._run is None; held(fresh, job)


def test_resume_source_cannot_use_normal_run_fallback_or_offer_before_fresh_original_media(receiving):
    with selected(receiving) as (fresh, job, _):
        start(fresh); count = fresh[2].send.call_count
        for operation in ('run_status', 'cancel_run', 'media_page', 'offer_run', 'offer_resume'):
            with pytest.raises(TransferError): request(fresh, operation)
        assert fresh[2].send.call_count == count
        collect(fresh, job); offered = offer(fresh, job)
        with pytest.raises(TransferError): fresh[3].resume_pending_offer(fresh[3].issue_receive_action(), offered['message_id'], '9' * 32)
        assert fresh[3]._run is None; held(fresh, job)


def test_resume_media_wrong_manifest_or_normal_operation_cannot_become_fresh_history(receiving):
    with selected(receiving) as (fresh, job, _):
        start(fresh); message = request(fresh, 'resume_media_page')
        correct = media(message, job.accepted.manifest); correct['body']['run_id'] = RESUME_RUN
        for change in ('manifest', 'operation'):
            value = deepcopy(correct)
            if change == 'manifest': value['body']['page']['manifest_sha256'] = '9' * 64
            else: value['body']['operation'] = 'media_page'
            with pytest.raises(TransferError): dispatch(fresh, value)
        assert fresh[3]._source_media_pages == () and fresh[3]._source_pending is not None
        assert fresh[3]._run is None; held(fresh, job)


def test_lost_resume_start_output_retries_same_original_phone_job_and_lookup_owner(receiving):
    with selected(receiving) as (fresh, job, _):
        connection = fresh[3]; fresh[2].send.side_effect = OSError('fixture lost resume start output')
        with pytest.raises(OSError): request(fresh, 'resume_run', album_id=ALBUM, desktop_choice=True)
        original = deepcopy(connection._source_pending.message)
        fresh[2].send.side_effect = None; connection.retry_source_command()
        assert fresh[2].send.call_args.args[0] == original and connection._source_pending.sent
        assert connection._run is None and connection._source_run is None
        held(fresh, job)


def test_resume_offer_cannot_replace_original_manifest_even_under_same_transfer_identity(receiving):
    with selected(receiving) as (fresh, job, _):
        start(fresh); collect(fresh, job); message = request(fresh, 'offer_resume')
        original = job.accepted.manifest
        changed = replace(original, files=(replace(original.files[0], path='Camera/other.jpg'),))
        offered = create_offer(changed); offered['expires_ms'] = min(offered['expires_ms'], message['expires_ms'])
        with pytest.raises(TransferError, match='original_manifest_changed'): dispatch(fresh, offered)
        assert fresh[3]._offer is None and fresh[3]._run is None; held(fresh, job)


def test_resumed_original_stage_holds_same_acceptance_for_retry_after_actual_output_loss(receiving):
    with selected(receiving, partial=True) as (fresh, job, original_history):
        connection = fresh[3]
        start(fresh); collect(fresh, job); offered = offer(fresh, job)
        fresh[2].send.side_effect = OSError('fixture resumed acceptance output lost')
        with pytest.raises(OSError): connection.resume_pending_offer(connection.issue_receive_action(), offered['message_id'], job.owner)
        acceptance = deepcopy(connection._run.acceptance)
        assert not connection._run.acceptance_sent and connection.receive_progress().verified_bytes == 5
        assert connection._run.receiver._index.media_history == original_history
        fresh[2].send.side_effect = None; connection.retry_acceptance()
        assert fresh[2].send.call_args.args[0] == acceptance and connection._run.acceptance_sent
        assert connection._run.accepted == job.accepted and connection.receive_progress().checkpoint_verified_bytes == 5
        held(fresh, job)


def test_resume_cancel_status_cannot_roll_back_into_ready_or_drop_held_original_job(receiving):
    with selected(receiving) as (fresh, job, _):
        start(fresh); message = request(fresh, 'cancel_resume')
        result = response(message, sources.RUN_RESULT, version='b' * 64, run_id=RESUME_RUN,
                          state='canceled_held', source_io_ended=True)
        result['expires_ms'] = min(result['expires_ms'], message['expires_ms']); dispatch(fresh, result)
        with pytest.raises(TransferError): request(fresh, 'offer_resume')
        status_request = request(fresh, 'resume_status')
        rollback = response(status_request, sources.RUN_RESULT, version='b' * 64, run_id=RESUME_RUN,
                            state='snapshot_ready', source_io_ended=True)
        rollback['expires_ms'] = min(rollback['expires_ms'], status_request['expires_ms'])
        with pytest.raises(TransferError, match='state_rollback'): dispatch(fresh, rollback)
        assert fresh[3]._source_run.state == 'canceled_held' and fresh[3]._run is None
        held(fresh, job)


def test_legacy_receiver_without_original_media_anchor_cannot_start_fresh_source_or_invent_history(receiving):
    with original_job(receiving) as (fresh, job):
        connection = fresh[3]
        connection.request_resume_lookup(connection.issue_receive_action(), job.owner)
        message = fresh[2].send.call_args.args[0]
        dispatch(fresh, lookup_reply(message, job, attempt_phase=None)); catalog(fresh)
        count = fresh[2].send.call_count
        with pytest.raises(TransferError, match='resume_media_history_required'):
            request(fresh, 'resume_run', album_id=ALBUM, desktop_choice=True)
        assert fresh[2].send.call_count == count and connection._source_run is None and connection._run is None
        held(fresh, job)
