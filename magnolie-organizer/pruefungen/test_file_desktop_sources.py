"""Actual reserved desktop source commands, with fixture-only native readiness."""
from dataclasses import replace
from pathlib import Path
import sys
import threading
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
import magnolie_file_sources as sources
from magnolie_file_control import FileControlPacket, FileGrantState
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, offer as native_offer
from test_file_desktop_connection import forbid_legacy

CATALOG = '22222222-2222-4222-8222-222222222222'
ALBUM = '33333333-3333-4333-8333-333333333333'
RUN = '44444444-4444-4444-8444-444444444444'


def offer(fixture, **options):
    pending = fixture[3]._source_pending
    deadline = pending.message['expires_ms'] if pending is not None else None
    return native_offer(fixture, deadline=deadline, **options)


def response(request, kind, **fields):
    at = phone.now_ms()
    return dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=kind, created_ms=at, expires_ms=at+60_000,
        body=dict(format=1, request_id=request['message_id'], operation=request['body']['operation'], **fields))


def request(fixture, operation, **options):
    connection = fixture[3]
    identity = connection.request_source(connection.issue_receive_action(), operation, **options)
    message = fixture[2].send.call_args.args[0]
    assert identity == message['message_id'] and message['kind'] == sources.REQUEST
    return message


def status(fixture, *, enabled=True, associated=True, version='b'*64, revision=2):
    req = request(fixture, 'status')
    fixture[0]._payload(fixture[1], fixture[2], response(req, sources.RESULT, version=version, revision=revision,
        enabled=enabled, associated=associated, repair_pending=False, kinds=['camera'] if enabled else []))


def catalog(fixture, *, needs_choice=False):
    req = request(fixture, 'discover')
    fixture[0]._payload(fixture[1], fixture[2], response(req, sources.CATALOG, version='b'*64, page=dict(format=1,
        catalog_id=CATALOG, after=0, next_cursor=None, coverage='full_images', proves_deletion=False,
        albums=[dict(album_id=ALBUM, kind='camera', display_name='Camera', visible_images=1, needs_choice=needs_choice)])))


def updated_control(fixture):
    connection = fixture[3]
    previous = connection._controls._remote
    packet = replace(previous, sequence=previous.sequence+1, grants=FileGrantState(previous.grants.revision+1, 'd'*64, True, False))
    at = phone.now_ms()
    fixture[0]._payload(fixture[1], fixture[2], dict(type='message', v=1, message_id=str(uuid.uuid4()), kind='file_transfer.control',
        created_ms=at, expires_ms=at+60_000, body=packet.wire()))


@pytest.mark.parametrize('operation', ['resume_run', 'resume_status', 'cancel_resume', 'offer_resume'])
def test_new_resume_codecs_do_not_silently_enable_unfinished_native_receiver_commands(receiving, operation):
    status(receiving)
    connection = receiving[3]; count = receiving[2].send.call_count
    with pytest.raises(TransferError):
        connection.request_source(connection.issue_receive_action(), operation)
    assert receiving[2].send.call_count == count
    assert connection._source_pending is None and connection._source_run is None
    assert connection._run is None and connection._catalog is None
    assert not list(receiving[4].iterdir())


@pytest.mark.parametrize('receiving', [False], indirect=True)
def test_own_receive_consent_bootstraps_actual_status_route_while_source_send_stays_off(receiving, monkeypatch):
    service, peer, channel, connection, destination = receiving
    forbid_legacy(service, monkeypatch)
    req = request(receiving, 'status')
    ticket = connection._source_pending.ticket
    assert connection._controls.receiver_command_current(ticket)
    assert connection._controls.binding('f'*64) is None
    wrong = response(req, sources.RESULT, version='a'*64, revision=0, enabled=False, associated=False, repair_pending=False, kinds=[])
    wrong['body']['request_id'] = str(uuid.uuid4())
    with pytest.raises(TransferError): service._payload(peer, channel, wrong)
    assert connection.source_state()['pending'] and connection.source_state()['status'] is None
    service._payload(peer, channel, response(req, sources.RESULT, version='a'*64, revision=0,
        enabled=False, associated=False, repair_pending=False, kinds=[]))
    assert not connection.source_state()['pending'] and not connection.source_state()['status'].enabled
    assert not connection._controls.receiver_command_current(ticket)
    assert not connection._controls._receiver_commands and not list(destination.iterdir())
    assert connection._run is None and connection._catalog is None


@pytest.mark.parametrize('receiving', [False], indirect=True)
def test_configuration_result_does_not_substitute_for_updated_actual_source_control_echo(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving, enabled=False, associated=False, version='a'*64, revision=0)
    req = request(receiving, 'configure', enabled=True, kinds=('camera',))
    service._payload(peer, channel, response(req, sources.RESULT, version='b'*64, revision=2,
        enabled=True, associated=True, repair_pending=False, kinds=['camera']))
    assert connection.source_state()['status'].enabled
    assert connection._controls.binding('f'*64) is None
    with pytest.raises(TransferError, match='source_controls_pending'): request(receiving, 'discover')
    updated_control(receiving)
    catalog(receiving)
    assert connection.source_state()['albums'][0].album_id == ALBUM
    assert connection._catalog is None and connection._run is None


def test_native_catalog_selection_and_run_results_do_not_release_the_whole_run_or_grant_read(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving); catalog(receiving, needs_choice=True)
    with pytest.raises(TransferError, match='album_not_current'): request(receiving, 'run', album_id=ALBUM, desktop_choice=False)
    with pytest.raises(TransferError, match='album_not_current'): request(receiving, 'run', album_id=str(uuid.uuid4()), desktop_choice=True)
    req = request(receiving, 'run', album_id=ALBUM, desktop_choice=True)
    assert req['body']['catalog_id'] == CATALOG and req['body']['expected_version'] == 'b'*64
    service._payload(peer, channel, response(req, sources.RUN_RESULT, version='b'*64, run_id=RUN, state='preparing', source_io_ended=False))
    current = request(receiving, 'run_status')
    assert current['body']['run_id'] == RUN
    service._payload(peer, channel, response(current, sources.RUN_RESULT, version='b'*64, run_id=RUN, state='snapshot_ready', source_io_ended=True))
    with pytest.raises(TransferError, match='run_held'): request(receiving, 'run', album_id=ALBUM, desktop_choice=True)
    cancel = request(receiving, 'cancel_run')
    service._payload(peer, channel, response(cancel, sources.RUN_RESULT, version='b'*64, run_id=RUN, state='canceled_held', source_io_ended=True))
    assert connection.source_state()['run'].state == 'canceled_held'
    assert connection._run is None and connection._catalog is None
    with pytest.raises(TransferError, match='run_held'): request(receiving, 'run', album_id=ALBUM, desktop_choice=True)


def test_permission_attempt_result_is_only_metadata_and_not_android_os_read_authority(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving)
    req = request(receiving, 'request_read')
    service._payload(peer, channel, response(req, sources.PERMISSION_RESULT, version='b'*64, state='notification_posted'))
    result = connection.source_state()['result']
    assert result.state == 'notification_posted' and not hasattr(result, 'read_granted')
    assert connection._run is None and connection._catalog is None


def test_failed_native_output_holds_exact_source_attempt_and_retry_cannot_launch_a_new_command(receiving):
    service, peer, channel, connection, _ = receiving
    channel.send.side_effect = OSError('synthetic actual source-command output failed')
    with pytest.raises(OSError): request(receiving, 'status')
    original = channel.send.call_args.args[0]
    ticket = connection._source_pending.ticket
    with pytest.raises(TransferError, match='command_busy'): request(receiving, 'status')
    with pytest.raises(TransferError, match='not_requested'):
        service._payload(peer, channel, response(original, sources.RESULT, version='a'*64, revision=0,
            enabled=False, associated=False, repair_pending=False, kinds=[]))
    channel.send.side_effect = None
    connection.retry_source_command()
    assert channel.send.call_args.args[0] == original and connection._source_pending.ticket is ticket
    service._payload(peer, channel, response(original, sources.RESULT, version='a'*64, revision=0,
        enabled=False, associated=False, repair_pending=False, kinds=[]))
    assert connection._source_pending is None


def test_expired_original_command_cannot_be_revived_by_fresh_result_header(receiving):
    _, _, _, connection, _ = receiving
    req = request(receiving, 'status')
    message = response(req, sources.RESULT, version='a'*64, revision=0, enabled=False, associated=False, repair_pending=False, kinds=[])
    at = req['expires_ms']
    message.update(created_ms=at, expires_ms=at+60_000)
    with pytest.raises(TransferError): connection.receive(message, clock=lambda:at)
    assert connection.source_state()['status'] is None and connection.source_state()['pending']


def test_source_reply_before_actual_command_output_returns_waits_on_native_io_lane(receiving):
    service, peer, channel, connection, _ = receiving
    entered = threading.Event(); release = threading.Event(); sent = threading.Event(); done = threading.Event(); incoming = threading.Event()
    requests = []; errors = []
    def blocked(message):
        requests.append(message); entered.set(); assert release.wait(5)
    channel.send.side_effect = blocked
    def send():
        try: request(receiving, 'status')
        except Exception as error: errors.append(error)
        finally: sent.set()
    def receive():
        incoming.set()
        try: service._payload(peer, channel, response(requests[0], sources.RESULT, version='a'*64, revision=0,
            enabled=False, associated=False, repair_pending=False, kinds=[]))
        except Exception as error: errors.append(error)
        finally: done.set()
    sender = threading.Thread(target=send); receiver = threading.Thread(target=receive); sender.start()
    try:
        assert entered.wait(5); receiver.start(); assert incoming.wait(5)
        assert not done.wait(0.05)
        release.set(); assert sent.wait(5) and done.wait(5)
        sender.join(5); receiver.join(5)
        assert not errors and connection.source_state()['status'].revision == 0
    finally:
        release.set(); sender.join(5)
        if receiver.ident is not None: receiver.join(5)
        assert not sender.is_alive() and not receiver.is_alive()


def test_revocation_during_source_output_keeps_ticket_until_actual_io_end(receiving):
    service, _, channel, connection, _ = receiving
    entered = threading.Event(); release = threading.Event(); ended = threading.Event(); errors = []
    def blocked(message): entered.set(); assert release.wait(5)
    channel.send.side_effect = blocked
    def write():
        try: request(receiving, 'status')
        except Exception as error: errors.append(error)
        finally: ended.set()
    worker = threading.Thread(target=write); worker.start()
    try:
        assert entered.wait(5)
        ticket = connection._source_pending.ticket
        service._end_native_file_connection(channel)
        assert ticket in connection._controls._receiver_commands and not connection._authority.protection._closed
        release.set(); assert ended.wait(5); worker.join(5)
        assert len(errors) == 1 and isinstance(errors[0], TransferError)
        assert ticket not in connection._controls._receiver_commands and connection._authority.protection._closed
    finally:
        release.set(); worker.join(5)
        assert not worker.is_alive()


def test_changed_own_policy_cannot_authorize_a_reply_from_the_previous_native_attempt(receiving):
    service, peer, channel, connection, _ = receiving
    req = request(receiving, 'status')
    prefs = connection._preferences
    prefs.configure(prefs.issue_action(), prefs.read(), enabled=True, mode='automatic')
    with pytest.raises(TransferError, match='authority_changed'):
        service._payload(peer, channel, response(req, sources.RESULT, version='a'*64, revision=0,
            enabled=False, associated=False, repair_pending=False, kinds=[]))
    assert connection.source_state()['status'] is None and connection.source_state()['pending']


def test_source_status_revision_rollback_and_changed_same_revision_are_not_adopted(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving)
    req = request(receiving, 'status')
    for version, revision in [('a'*64, 1), ('c'*64, 2)]:
        with pytest.raises(TransferError, match='status_rollback'):
            service._payload(peer, channel, response(req, sources.RESULT, version=version, revision=revision,
                enabled=True, associated=True, repair_pending=False, kinds=['camera']))
        assert connection.source_state()['status'].version == 'b'*64
    service._payload(peer, channel, response(req, sources.RESULT, version='b'*64, revision=2,
        enabled=True, associated=True, repair_pending=False, kinds=['camera']))
    assert not connection.source_state()['pending']


def test_catalog_paging_uses_only_the_native_returned_cursor_and_rejects_repeated_album_ids(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving)
    req = request(receiving, 'discover')
    first = dict(format=1, catalog_id=CATALOG, after=0, next_cursor=1, coverage='full_images', proves_deletion=False,
        albums=[dict(album_id=ALBUM, kind='camera', display_name='Camera', visible_images=1, needs_choice=False)])
    service._payload(peer, channel, response(req, sources.CATALOG, version='b'*64, page=first))
    next_req = request(receiving, 'catalog_page')
    assert next_req['body']['after'] == 1 and next_req['body']['catalog_id'] == CATALOG
    repeated = dict(first, after=1, next_cursor=None)
    with pytest.raises(TransferError, match='duplicate_album'):
        service._payload(peer, channel, response(next_req, sources.CATALOG, version='b'*64, page=repeated))
    other = dict(first['albums'][0], album_id='55555555-5555-4555-8555-555555555555', display_name='Another camera album')
    service._payload(peer, channel, response(next_req, sources.CATALOG, version='b'*64, page=dict(repeated, albums=[other])))
    assert len(connection.source_state()['albums']) == 2
    with pytest.raises(TransferError, match='catalog_not_current'): request(receiving, 'catalog_page')


def test_no_native_status_or_wire_action_can_start_a_source_scan(receiving):
    _, _, channel, connection, _ = receiving
    with pytest.raises(TransferError): connection.request_source({'token': 'wire'}, 'status')
    with pytest.raises(TransferError, match='status_required'):
        request(receiving, 'run', album_id=ALBUM, desktop_choice=True)
    channel.send.assert_not_called()
    assert connection._source_pending is None and connection._run is None and connection._catalog is None


def test_completed_or_canceled_native_source_run_cannot_be_revived_by_later_metadata(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving); catalog(receiving)
    start = request(receiving, 'run', album_id=ALBUM, desktop_choice=True)
    service._payload(peer, channel, response(start, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='snapshot_ready', source_io_ended=True))
    poll = request(receiving, 'run_status')
    with pytest.raises(TransferError, match='state_rollback'):
        service._payload(peer, channel, response(poll, sources.RUN_RESULT, version='b'*64, run_id=RUN,
            state='preparing', source_io_ended=False))
    service._payload(peer, channel, response(poll, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='snapshot_ready', source_io_ended=True))
    cancel = request(receiving, 'cancel_run')
    service._payload(peer, channel, response(cancel, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='canceled_held', source_io_ended=True))
    poll = request(receiving, 'run_status')
    with pytest.raises(TransferError, match='state_rollback'):
        service._payload(peer, channel, response(poll, sources.RUN_RESULT, version='b'*64, run_id=RUN,
            state='snapshot_ready', source_io_ended=True))
    assert connection.source_state()['run'].state == 'canceled_held'


def test_failed_native_source_run_can_be_canceled_but_never_revived_as_a_ready_source(receiving):
    service, peer, channel, connection, _ = receiving
    status(receiving); catalog(receiving)
    start = request(receiving, 'run', album_id=ALBUM, desktop_choice=True)
    service._payload(peer, channel, response(start, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='failed_held', source_io_ended=True))
    poll = request(receiving, 'run_status')
    with pytest.raises(TransferError, match='state_rollback'):
        service._payload(peer, channel, response(poll, sources.RUN_RESULT, version='b'*64, run_id=RUN,
            state='snapshot_ready', source_io_ended=True))
    service._payload(peer, channel, response(poll, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='failed_held', source_io_ended=True))
    cancel = request(receiving, 'cancel_run')
    service._payload(peer, channel, response(cancel, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='canceled_held', source_io_ended=True))
    assert connection.source_state()['run'].state == 'canceled_held'
    assert connection._run is None and connection._catalog is None


def ready_source(fixture, *, state='snapshot_ready', ended=True,prepare_storage=True):
    # Explicit native setup in positive fixtures, BEFORE any source command.
    # This never runs in the product's packet/command path and renews no source
    # run. Negative storage-admission fixtures intentionally use raw commands.
    from magnolie_media_storage_bootstrap import NativeMediaStorageBootstrap
    from test_file_desktop_receive import negotiate
    connection=fixture[3];expected=connection._preferences.read()
    if prepare_storage and (expected.policy.mapping_store is None or expected.policy.job_catalog is None):
        controller=NativeMediaStorageBootstrap(connection._authority)
        try:controller.prepare(controller.issue_action(),expected)
        finally:controller.close()
        negotiate(*fixture[:4])
    status(fixture); catalog(fixture)
    start = request(fixture, 'run', album_id=ALBUM, desktop_choice=True)
    fixture[0]._payload(fixture[1], fixture[2], response(start, sources.RUN_RESULT,
        version='b'*64, run_id=RUN, state=state, source_io_ended=ended))


def offer_output(fixture, req, message, manifest, **fields):
    result = response(req, sources.RUN_RESULT, version='b'*64, run_id=RUN, state='snapshot_ready',
        source_io_ended=True, offer_id=message['message_id'], manifest_sha256=manifest.fingerprint)
    result['expires_ms'] = min(req['expires_ms'], message['expires_ms'])
    result['body'].update(fields)
    return result


def test_offer_trigger_joins_exact_native_ready_run_actual_offer_and_result_before_acceptance(receiving):
    service, peer, channel, connection, _ = receiving
    from magnolie_file_offer import create_offer
    from test_file_desktop_media import manifest as media_manifest,collect
    ready_source(receiving)
    manifest=media_manifest(receiving);collect(receiving,manifest)
    req = request(receiving, 'offer_run')
    assert req['body']['run_id'] == RUN and req['body']['expected_version'] == 'b'*64
    message=create_offer(manifest);message['expires_ms']=min(message['expires_ms'],req['expires_ms'])
    service._payload(peer,channel,message)
    with pytest.raises(TransferError, match='not_confirmed'):
        connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert connection._catalog is None and connection._run is None
    service._payload(peer, channel, offer_output(receiving, req, message, manifest))
    connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert channel.send.call_args.args[0]['body']['offer_id'] == message['message_id']
    assert connection._run.accepted.manifest == manifest


@pytest.mark.parametrize('changed', ['offer_id', 'manifest_sha256', 'deadline'])
def test_mismatched_offer_result_keeps_original_pending_envelope_and_no_native_reservation(receiving, changed):
    service, peer, channel, connection, _ = receiving
    ready_source(receiving); req = request(receiving, 'offer_run')
    message, manifest = offer(receiving)
    wrong = offer_output(receiving, req, message, manifest)
    if changed == 'deadline': wrong['expires_ms'] = min(req['expires_ms'], message['expires_ms'])+1
    else: wrong['body'][changed] = str(uuid.uuid4()) if changed == 'offer_id' else 'f'*64
    with pytest.raises(TransferError, match='correlation'): service._payload(peer, channel, wrong)
    assert connection._source_pending is not None and connection._source_offer is None
    assert connection._offer == message and connection._run is None and connection._catalog is None
    connection.retry_source_command()
    assert channel.send.call_args.args[0] == req
    service._payload(peer, channel, message)  # Exact offer replay, no replacement.
    service._payload(peer, channel, offer_output(receiving, req, message, manifest))
    assert connection._source_offer.offer_id == message['message_id']


def test_source_offer_cannot_be_unsolicited_replaced_or_requested_before_snapshot_readiness(receiving):
    service, peer, channel, connection, _ = receiving
    ready_source(receiving, state='preparing', ended=False)
    with pytest.raises(TransferError, match='not_ready'): request(receiving, 'offer_run')
    with pytest.raises(TransferError, match='not_requested'): offer(receiving)
    assert connection._offer is None and connection._run is None
    poll = request(receiving, 'run_status')
    service._payload(peer, channel, response(poll, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='snapshot_ready', source_io_ended=True))
    req = request(receiving, 'offer_run'); message, manifest = offer(receiving)
    with pytest.raises(TransferError, match='already_pending'): offer(receiving, transfer='4')
    service._payload(peer, channel, offer_output(receiving, req, message, manifest))
    cancel = request(receiving, 'cancel_run')
    service._payload(peer, channel, response(cancel, sources.RUN_RESULT, version='b'*64, run_id=RUN,
        state='canceled_held', source_io_ended=True))
    with pytest.raises(TransferError, match='not_confirmed'):
        connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert connection._catalog is None and connection._run is None


def test_offer_result_without_actual_offer_cannot_unlock_acceptance_or_finish_attempt(receiving):
    service, peer, channel, connection, _ = receiving
    ready_source(receiving); req = request(receiving, 'offer_run')
    early = response(req, sources.RUN_RESULT, version='b'*64, run_id=RUN, state='snapshot_ready',
        source_io_ended=True, offer_id=str(uuid.uuid4()), manifest_sha256='f'*64)
    with pytest.raises(TransferError, match='correlation'): service._payload(peer, channel, early)
    assert connection._source_pending is not None and connection._offer is None
    assert connection._source_offer is None and connection._catalog is None
    message, manifest = offer(receiving)
    service._payload(peer, channel, offer_output(receiving, req, message, manifest))
    assert connection._source_pending is None and connection._source_offer.offer_id == message['message_id']


def test_offer_cannot_outlive_original_native_source_command(receiving):
    ready_source(receiving); req = request(receiving, 'offer_run')
    with pytest.raises(TransferError, match='correlation'):
        native_offer(receiving, now=req['created_ms']+1)
    assert receiving[3]._offer is None and receiving[3]._source_pending is not None


def test_new_source_policy_status_cannot_leave_previous_offer_confirmed_for_admission(receiving):
    service, peer, channel, connection, _ = receiving
    ready_source(receiving); req = request(receiving, 'offer_run')
    message, manifest = offer(receiving)
    service._payload(peer, channel, offer_output(receiving, req, message, manifest))
    status(receiving, version='c'*64, revision=3)
    with pytest.raises(TransferError, match='not_confirmed'):
        connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert connection._run is None and connection._catalog is None and connection._offer == message
