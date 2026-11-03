"""Ordinary second sync compares real old saves/current targets before download."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, reconnect
from test_file_desktop_sources import ready_source, request, response
from test_file_desktop_media import collect, send_offer, dispatch
from test_photo_mappings import save
import magnolie_file_sources as sources


@pytest.mark.parametrize('change,expected', [
    ('none', 'unchanged'), ('pc_edit', 'keep_local_edit'), ('pc_missing', 'pause_unconfirmed_absence'),
    ('pc_replaced', 'conflict_unmanaged_target'), ('phone_edit', 'conflict_unproven_source_identity'),
    ('both_edit', 'conflict_edit_edit')])
def test_second_native_album_review_preserves_original_target_and_requests_no_photo_bytes(receiving, monkeypatch, change, expected):
    connection = receiving[3]
    receiver, _, association = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original_job = receiver.job; original_history = receiver._index.media_history
    original_mapping = connection._mappings.lookup((association,))
    target = receiving[4] / receiver._index.saved_receipts()[0].relative_path
    if change in ('pc_edit', 'both_edit'): target.write_bytes(b'preserve PC crop')
    elif change == 'pc_missing': target.unlink()  # Fixture user action only, not a deletion claim.
    elif change == 'pc_replaced':
        replacement = target.with_name('replacement.jpg'); replacement.write_bytes(b'preserve replacement')
        replacement.chmod(0o600); replacement.replace(target)
    before = target.read_bytes() if target.exists() else None
    with reconnect(receiving) as fresh:
        current = fresh[3]; ready_source(fresh)
        file = original_job.accepted.manifest.files[0]
        if change in ('phone_edit', 'both_edit'): file = replace(file, sha256=sha256(b'phone edit').hexdigest(), size=10)
        full = replace(original_job.accepted.manifest, transfer_id='8' * 32, source_id='9' * 32,
            files=(replace(file, id='a' * 32),), total_bytes=file.size)
        collect(fresh, full); offered, result = send_offer(fresh, full); dispatch(fresh, result)
        def forbidden(*args, **kwargs): raise AssertionError('Review must not reserve or open any receive stage')
        monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.accept', forbidden)
        monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume', forbidden)
        count = fresh[2].send.call_count
        review = current.review_pending_photos(current.issue_receive_action())
        assert review.manifest_sha256 == full.fingerprint and len(review.items) == 1
        assert review.items[0].file_id == 'a' * 32 and review.items[0].decision == expected
        assert review.items[0].original_job_owner == original_job.owner
        assert review.nothing_to_download == (change in ('none', 'pc_edit'))
        assert not review.grants_write_authority and not review.is_saved_receipt
        assert fresh[2].send.call_count == count and current._run is None
        assert current._catalog.jobs() == (original_job,)
        assert current._mappings.lookup((association,)) == original_mapping
        assert (target.read_bytes() if target.exists() else None) == before
        assert original_history.entries[0].photo_id == review.items[0].photo_id


def end_normal_source(fixture):
    connection = fixture[3]
    for operation in ('cancel_run', 'end_run'):
        message = request(fixture, operation)
        body = dict(version=connection._source_status.version, run_id=connection._source_run.run_id,
            state='canceled_held', source_io_ended=True)
        if operation == 'end_run': body['run_ended'] = True
        result = response(message, sources.RUN_RESULT, **body)
        result['expires_ms'] = min(result['expires_ms'], message['expires_ms'])
        dispatch(fixture, result)


def test_first_save_then_two_ordinary_unchanged_runs_keep_one_photo_and_original_job(receiving, monkeypatch):
    connection = receiving[3]; receiver, _, association = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original_job = receiver.job
    progress = connection.finish_saved_receive(connection.issue_receive_action())
    assert progress.verified_bytes == 5 and receiver._closed and connection._run is None
    end_normal_source(receiving)
    assert connection._source_run is None
    mapping = connection._mappings.lookup((association,))
    def forbidden(*args, **kwargs): raise AssertionError('An unchanged second/third run cannot allocate or resume data')
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.accept', forbidden)
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume', forbidden)
    target = receiving[4] / mapping[1][0].relative_path
    before = (target.stat().st_ino, target.read_bytes())
    for value in ('a', 'b'):
        ready_source(receiving)
        old = original_job.accepted.manifest
        full = replace(old, source_id=value * 32, transfer_id=value * 32, files=(replace(old.files[0], id=value * 32),))
        collect(receiving, full); offered, result = send_offer(receiving, full); dispatch(receiving, result)
        count = len([call for call in receiving[2].send.call_args_list if call.args[0]['kind'] == 'file_transfer.chunk.request'])
        reviewed = connection.review_pending_photos(connection.issue_receive_action())
        assert reviewed.nothing_to_download and reviewed.items[0].decision == 'unchanged'
        end_normal_source(receiving)
        assert connection._run is None and connection._source_run is None and connection._offer is None
        assert len([call for call in receiving[2].send.call_args_list if call.args[0]['kind'] == 'file_transfer.chunk.request']) == count
        assert connection._catalog.jobs() == (original_job,)
        assert connection._mappings.lookup((association,)) == mapping
        assert (target.stat().st_ino, target.read_bytes()) == before


def test_ordinary_end_result_requires_exact_owner_and_literal_io_end_not_saved_claim():
    from copy import deepcopy
    from magnolie_file_transfer import TransferError
    message = sources.create_command('end_run', expected_version='a' * 64,
        run_id='55555555-5555-4555-8555-555555555555')
    parsed = sources.parse_command(message)
    result = response(message, sources.RUN_RESULT, version=parsed.expected_version, run_id=parsed.run_id,
        state='canceled_held', source_io_ended=True, run_ended=True)
    result['expires_ms'] = min(result['expires_ms'], message['expires_ms'])
    options = dict(expected_request_id=parsed.request_id, expected_operation='end_run',
        expected_version=parsed.expected_version, expected_run_id=parsed.run_id)
    assert sources.parse_run_result(result, **options).run_ended
    for field, value in [('run_ended', 1), ('run_ended', False), ('source_io_ended', False),
                         ('state', 'snapshot_ready'), ('operation', 'end_resume'), ('saved', True)]:
        changed = deepcopy(result); changed['body'][field] = value
        with pytest.raises(TransferError): sources.parse_run_result(changed, **options)
