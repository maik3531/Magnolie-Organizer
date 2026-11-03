"""A mixed album transfers only the new native member, never known PC copies."""
from contextlib import contextmanager
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
from test_file_desktop_sources import ready_source, request, response
from test_file_desktop_media import collect, send_offer, dispatch, media
from test_photo_mappings import save
from test_file_desktop_photo_review import end_normal_source

SELECTED_RUN = '66666666-6666-4666-8666-666666666666'


@contextmanager
def mixed(fixture):
    connection = fixture[3]; receiver, _, association = save(fixture, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original = receiver.job; mapping = connection._mappings.lookup((association,))[1][0]
    target = fixture[4] / mapping.relative_path; target.write_bytes(b'keep PC crop')
    connection.finish_saved_receive(connection.issue_receive_action()); end_normal_source(fixture)
    ready_source(fixture)
    old = original.accepted.manifest
    full = replace(old, source_id='8' * 32, transfer_id='9' * 32, total_bytes=10,
        files=(replace(old.files[0], id='a' * 32), replace(old.files[0], id='b' * 32, path='Camera/new.jpg')))
    collect(fixture, full); offered, result = send_offer(fixture, full); dispatch(fixture, result)
    yield connection, original, mapping, target, full


def selected_result(message):
    value = response(message, sources.RUN_RESULT, version='b' * 64, run_id=SELECTED_RUN,
        state='snapshot_ready', source_io_ended=True)
    value['expires_ms'] = min(value['expires_ms'], message['expires_ms'])
    return value


def selected_media(fixture, subset):
    message = request(fixture, 'media_page'); value = media(message, subset)
    value['body']['run_id'] = SELECTED_RUN
    value['body']['page']['entries'][0]['photo_id'] = sha256(b'photo-1').hexdigest()
    return value


def selected_offer(fixture, subset):
    message = request(fixture, 'offer_run'); offered = create_offer(subset)
    offered['expires_ms'] = min(offered['expires_ms'], message['expires_ms']); dispatch(fixture, offered)
    result = response(message, sources.RUN_RESULT, version='b' * 64, run_id=SELECTED_RUN,
        state='snapshot_ready', source_io_ended=True, offer_id=offered['message_id'], manifest_sha256=subset.fingerprint)
    result['expires_ms'] = min(result['expires_ms'], offered['expires_ms']); dispatch(fixture, result)
    return offered


def test_mixed_album_lost_selection_retry_transfers_only_new_photo_and_preserves_pc_crop(receiving):
    with mixed(receiving) as (connection, original, mapping, target, full):
        before = (target.stat().st_ino, target.read_bytes())
        receiving[2].send.side_effect = OSError('fixture lost exact file selection command')
        with pytest.raises(OSError): connection.select_pending_new_photos(connection.issue_receive_action())
        held = deepcopy(connection._source_pending.message)
        assert held['body']['file_ids'] == ['b' * 32] and connection._run is None
        receiving[2].send.side_effect = None; connection.retry_source_command()
        assert receiving[2].send.call_args.args[0] == held
        dispatch(receiving, selected_result(held))
        subset = replace(full, source_id='c' * 32, transfer_id='d' * 32, files=(full.files[1],), total_bytes=5)
        dispatch(receiving, selected_media(receiving, subset)); offered = selected_offer(receiving, subset)
        connection.accept_pending_offer(connection.issue_receive_action(), offered['message_id'])
        requested = connection.request_next_chunk()
        assert requested['body']['file_id'] == 'b' * 32
        dispatch(receiving, chunk(requested, b'hello'))
        connection.publish_received(connection.issue_receive_action())
        assert (receiving[4] / 'Camera/new.jpg').read_bytes() == b'hello'
        assert (target.stat().st_ino, target.read_bytes()) == before
        assert connection._mappings.lookup((mapping.association,))[1][0] == mapping
        assert connection._mappings.read().count == 2
        assert len(connection._catalog.jobs()) == 2 and original in connection._catalog.jobs()
        connection.finish_saved_receive(connection.issue_receive_action()); end_normal_source(receiving)
        ready_source(receiving); collect(receiving, full); offered, result = send_offer(receiving, full); dispatch(receiving, result)
        review = connection.review_pending_photos(connection.issue_receive_action())
        assert [item.decision for item in review.items] == ['keep_local_edit', 'unchanged']
        assert review.nothing_to_download
        count = receiving[2].send.call_count
        assert connection.select_pending_new_photos(connection.issue_receive_action()) is None
        assert receiving[2].send.call_count == count and connection._run is None


@pytest.mark.parametrize('change', ['foreign_photo', 'known_member', 'owner_reused'])
def test_selected_source_cannot_substitute_old_photo_or_reuse_preview_owner(receiving, change):
    with mixed(receiving) as (connection, original, mapping, target, full):
        connection.select_pending_new_photos(connection.issue_receive_action())
        held = receiving[2].send.call_args.args[0]; reply = selected_result(held)
        if change == 'owner_reused':
            reply['body']['run_id'] = held['body']['run_id']
            with pytest.raises(TransferError): dispatch(receiving, reply)
        else:
            dispatch(receiving, reply)
            subset = replace(full, source_id='c' * 32, transfer_id='d' * 32, files=(full.files[1],), total_bytes=5)
            value = selected_media(receiving, subset)
            entry = value['body']['page']['entries'][0]
            if change == 'foreign_photo': entry['photo_id'] = '9' * 64
            else: entry['file_id'] = full.files[0].id
            with pytest.raises(TransferError): dispatch(receiving, value)
        assert connection._run is None and connection._catalog.jobs() == (original,)
        assert connection._mappings.read().count == 1 and target.read_bytes() == b'keep PC crop'


def test_select_run_codec_rejects_duplicate_unsorted_members_and_ignored_options():
    options = dict(expected_version='b' * 64, run_id='55555555-5555-4555-8555-555555555555',
        manifest_sha256='c' * 64, file_ids=['a' * 32, 'b' * 32])
    message = sources.create_command('select_run', **options)
    parsed = sources.parse_command(message)
    assert parsed.selected_file_ids == ('a' * 32, 'b' * 32) and parsed.selection_manifest_sha256 == 'c' * 64
    for ids in ([], [True], ['a' * 32, 'a' * 32], ['b' * 32, 'a' * 32], ['/private']):
        with pytest.raises(TransferError): sources.create_command('select_run', **dict(options, file_ids=ids))
    with pytest.raises(TransferError): sources.create_command('status', file_ids=options['file_ids'])
    with pytest.raises(TransferError): sources.create_command('select_run', **dict(options, source_id='d' * 32))
    result = selected_result(message)
    value = sources.parse_run_result(result, expected_request_id=parsed.request_id, expected_operation='select_run',
        expected_version=parsed.expected_version)
    assert value.run_id == SELECTED_RUN and not value.run_ended
