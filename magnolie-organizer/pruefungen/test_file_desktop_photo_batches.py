"""Explicit album batches retain old saves and require confirmed native END."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_file_sources as sources
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, chunk
from test_file_desktop_sources import request, response, status, catalog, ALBUM, RUN
from test_file_desktop_media import dispatch, media
from test_photo_mappings import save
from test_file_desktop_photo_review import end_normal_source

NEXT = '77777777-7777-4777-8777-777777777777'


def result(message, run=RUN, final=False, state='snapshot_ready', **fields):
    body = dict(version='b' * 64, run_id=run, state=state,
        source_io_ended=state in ('snapshot_ready', 'empty_ready', 'canceled_held', 'failed_held'))
    if message['body']['operation'] in ('end_run', 'end_album'):
        body['run_ended'] = True
    else:
        body['batch_end'] = final
    value = response(message, sources.RUN_RESULT, **body, **fields)
    value['expires_ms'] = min(value['expires_ms'], message['expires_ms'])
    return value


def begin(fixture):
    status(fixture); catalog(fixture)
    message = request(fixture, 'batch_run', album_id=ALBUM, desktop_choice=True)
    dispatch(fixture, result(message))


def collect(fixture, manifest, run=RUN, photo=0):
    message = request(fixture, 'media_page')
    value = media(message, manifest)
    value['body']['run_id'] = run
    value['body']['page']['entries'][0]['photo_id'] = sha256(f'photo-{photo}'.encode()).hexdigest()
    dispatch(fixture, value)


def offer(fixture, manifest, run=RUN, final=False):
    message = request(fixture, 'offer_run'); offered = create_offer(manifest)
    offered['expires_ms'] = min(offered['expires_ms'], message['expires_ms'])
    dispatch(fixture, offered)
    value = result(message, run, final, offer_id=offered['message_id'], manifest_sha256=manifest.fingerprint)
    value['expires_ms'] = min(value['expires_ms'], offered['expires_ms']); dispatch(fixture, value)
    return offered


def end(fixture, run=RUN, final=False):
    for operation in ('cancel_run', 'end_run'):
        message = request(fixture, operation)
        dispatch(fixture, result(message, run, final, state='canceled_held'))


def test_actual_two_batch_album_keeps_known_photo_then_saves_only_new_photo_with_cache_reuse(receiving):
    connection = receiving[3]
    receiver, _, association = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original = receiver.job; old = original.accepted.manifest
    mapping = connection._mappings.lookup((association,))[1][0]
    target = receiving[4] / mapping.relative_path; before = (target.stat().st_ino, target.read_bytes())
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    end_normal_source(receiving)
    begin(receiving)
    full = replace(old, source_id='8' * 32, transfer_id='9' * 32, files=(replace(old.files[0], id='a' * 32),))
    collect(receiving, full); offer(receiving, full)
    review = connection.review_pending_photos(connection.issue_receive_action())
    assert review.nothing_to_download and review.items[0].decision == 'unchanged'
    with pytest.raises(TransferError): request(receiving, 'next_batch')
    end(receiving)
    receiving[2].send.side_effect = OSError('fixture next-batch output lost')
    with pytest.raises(OSError): request(receiving, 'next_batch')
    held = deepcopy(connection._source_pending.message)
    assert held['body']['run_id'] == RUN
    receiving[2].send.side_effect = None; connection.retry_source_command()
    assert receiving[2].send.call_args.args[0] == held
    dispatch(receiving, result(held, NEXT, True))
    new = replace(full, source_id='c' * 32, transfer_id='d' * 32,
        files=(replace(full.files[0], id='b' * 32, path='Camera/new.jpg'),))
    collect(receiving, new, NEXT, 1)
    offered = offer(receiving, new, NEXT, True)
    connection.accept_pending_offer(connection.issue_receive_action(), offered['message_id'])
    requested = connection.request_next_chunk(); assert requested['body']['file_id'] == 'b' * 32
    dispatch(receiving, chunk(requested, b'hello'))
    connection.publish_received(connection.issue_receive_action())
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    end(receiving, NEXT, True)
    assert (receiving[4] / 'Camera/new.jpg').read_bytes() == b'hello'
    assert (target.stat().st_ino, target.read_bytes()) == before
    assert connection._mappings.lookup((association,))[1][0] == mapping
    assert connection._mappings.read().count == 2
    assert len(connection._catalog.jobs()) == 2
    assert all(job.reserved_bytes == 0 for job in connection._catalog.jobs())
    count = receiving[2].send.call_count
    with pytest.raises(TransferError): request(receiving, 'next_batch')
    assert receiving[2].send.call_count == count and connection._run is None


@pytest.mark.parametrize('change', ['owner_reused', 'missing_flag', 'scope_changed'])
def test_batch_continuation_rejects_old_owner_missing_batch_identity_and_foreign_album_scope(receiving, change):
    begin(receiving)
    from test_file_desktop_media import manifest
    full = manifest(receiving, 1)
    collect(receiving, full); offer(receiving, full); end(receiving)
    message = request(receiving, 'next_batch'); value = result(message, NEXT, True)
    if change == 'owner_reused': value['body']['run_id'] = RUN
    elif change == 'missing_flag': del value['body']['batch_end']
    if change != 'scope_changed':
        with pytest.raises(TransferError): dispatch(receiving, value)
    else:
        dispatch(receiving, value)
        following = replace(full, source_id='c' * 32, transfer_id='d' * 32)
        message = request(receiving, 'media_page'); value = media(message, following)
        value['body']['run_id'] = NEXT; value['body']['page']['source_epoch'] = '9' * 64
        with pytest.raises(TransferError): dispatch(receiving, value)
    assert connection_no_receiver(receiving)


def connection_no_receiver(fixture):
    return fixture[3]._run is None and not list(fixture[4].glob('**/*.jpg'))


def test_batch_codecs_require_explicit_bounded_shape_and_literal_completion_metadata():
    message = sources.create_command('batch_run', expected_version='b' * 64,
        catalog_id='22222222-2222-4222-8222-222222222222', album_id=ALBUM, desktop_choice=True)
    assert sources.parse_command(message).operation == 'batch_run'
    value = result(message)
    options = dict(expected_request_id=message['message_id'], expected_operation='batch_run', expected_version='b' * 64)
    assert sources.parse_run_result(value, **options).batched
    for field in (None, 0, 1, 'false'):
        changed = deepcopy(value); changed['body']['batch_end'] = field
        with pytest.raises(TransferError): sources.parse_run_result(changed, **options)
    del value['body']['batch_end']
    with pytest.raises(TransferError): sources.parse_run_result(value, **options)
    with pytest.raises(TransferError): sources.create_command('next_batch', expected_version='b' * 64, run_id=RUN, album_id=ALBUM)


def test_explicit_album_stop_can_retry_but_never_continue_the_stopped_scan(receiving):
    begin(receiving); end(receiving)
    receiving[2].send.side_effect = OSError('fixture end-album output lost')
    with pytest.raises(OSError): request(receiving, 'end_album')
    held = deepcopy(receiving[3]._source_pending.message)
    receiving[2].send.side_effect = None; receiving[3].retry_source_command()
    assert receiving[2].send.call_args.args[0] == held
    dispatch(receiving, result(held, state='canceled_held'))
    with pytest.raises(TransferError): request(receiving, 'next_batch')
    with pytest.raises(TransferError): request(receiving, 'end_album')
    message = request(receiving, 'batch_run', album_id=ALBUM, desktop_choice=True)
    dispatch(receiving, result(message, NEXT, True))
    assert receiving[3]._source_run.run_id == NEXT
    assert connection_no_receiver(receiving)


def test_empty_batch_completion_has_no_offer_or_deletion_authority(receiving):
    status(receiving); catalog(receiving)
    message = request(receiving, 'batch_run', album_id=ALBUM, desktop_choice=True)
    dispatch(receiving, result(message, final=True, state='empty_ready'))
    assert receiving[3]._source_run.state == 'empty_ready'
    with pytest.raises(TransferError): request(receiving, 'offer_run')
    with pytest.raises(TransferError): request(receiving, 'media_page')
    end(receiving, final=True)
    with pytest.raises(TransferError): request(receiving, 'next_batch')
    assert connection_no_receiver(receiving)


def test_mixed_batch_selection_keeps_pc_edit_and_album_position_until_selected_save_then_next_empty_batch(receiving):
    connection = receiving[3]
    receiver, _, association = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    old = receiver.job.accepted.manifest
    mapping = connection._mappings.lookup((association,))[1][0]
    target = receiving[4] / mapping.relative_path; target.write_bytes(b'keep existing PC crop')
    before = (target.stat().st_ino, target.read_bytes())
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True); end_normal_source(receiving)
    begin(receiving)
    full = replace(old, source_id='8' * 32, transfer_id='9' * 32, total_bytes=10,
        files=(replace(old.files[0], id='a' * 32), replace(old.files[0], id='b' * 32, path='Camera/new.jpg')))
    collect(receiving, full); offer(receiving, full)
    connection.select_pending_new_photos(connection.issue_receive_action())
    selection = receiving[2].send.call_args.args[0]
    assert selection['body']['file_ids'] == ['b' * 32]
    dispatch(receiving, result(selection, NEXT))
    subset = replace(full, source_id='e' * 32, transfer_id='f' * 32, files=(full.files[1],), total_bytes=5)
    collect(receiving, subset, NEXT, 1); offered = offer(receiving, subset, NEXT)
    connection.accept_pending_offer(connection.issue_receive_action(), offered['message_id'])
    requested = connection.request_next_chunk(); assert requested['body']['file_id'] == 'b' * 32
    dispatch(receiving, chunk(requested, b'hello'))
    connection.publish_received(connection.issue_receive_action())
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    end(receiving, NEXT)
    message = request(receiving, 'next_batch')
    assert message['body']['run_id'] == NEXT
    final_run = '88888888-8888-4888-8888-888888888888'
    dispatch(receiving, result(message, final_run, True, state='empty_ready'))
    end(receiving, final_run, True)
    assert (target.stat().st_ino, target.read_bytes()) == before
    assert connection._mappings.lookup((association,))[1][0] == mapping
    assert (receiving[4] / 'Camera/new.jpg').read_bytes() == b'hello'
    assert connection._mappings.read().count == 2
    assert all(job.reserved_bytes == 0 for job in connection._catalog.jobs())
    with pytest.raises(TransferError): request(receiving, 'next_batch')
