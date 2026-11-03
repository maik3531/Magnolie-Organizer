"""Native coordinator/staging fixtures; readiness override is test-only."""
from hashlib import sha256
from pathlib import Path
import base64
import sys
import threading
import uuid
from contextlib import contextmanager

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_control import FileControlPacket, FileGrantState, NativeFilePeer, NativeLocalFileGrant, NativeFileControlSession
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_file_offer import create_offer
from magnolie_file_transfer import FileManifest, ManifestFile, TransferError, CHUNK_BYTES
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity, ProtectedTransferJobCatalog
from magnolie_photo_destination import NativePhotoDestinationController
from test_file_authenticated_desktop import native, bind


@pytest.fixture
def receiving(native, tmp_path, monkeypatch, request):
    service, peer, _ = native
    # Private release gate overridden before native control-session construction.
    # Never a wire setting or an enabled production capability.
    monkeypatch.setattr(NativeDesktopFileConnection, '_data_handlers_ready', True)
    channel, binding = bind(service, peer)
    connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
    destination = tmp_path / 'native-photo-choice'; destination.mkdir(mode=0o700)
    chooser = NativePhotoDestinationController(connection._authority)
    try:
        choice = chooser.choose_custom(chooser.issue_action(), destination)
        prefs = connection._preferences
        prefs.configure(prefs.issue_action(), prefs.read(), enabled=True, mode='manual', destination_choice=choice)
        negotiate(service, peer, channel, connection, source_send=getattr(request, 'param', True))
        yield service, peer, channel, connection, destination
    finally:
        chooser.close(); service._end_native_file_connection(channel)


def negotiate(service, peer, channel, connection, *, source_send=True):
    local = connection._authority.identity
    remote_peer = NativeFilePeer(local.receiver_id, local.receiver_identity_sha256, object(), True, True, True, True, True)
    remote_local = NativeLocalFileGrant(FileGrantState(1, 'a'*64, source_send, False), object(), True)
    remote = NativeFileControlSession(NativeJobCatalogIdentity(peer['device_id'], sha256(phone.unb64(peer['static_public'], 32)).hexdigest()),
                                     lambda:remote_peer, lambda:remote_local)
    assert connection.send_controls()
    remote.observe_remote(FileControlPacket.parse(channel.send.call_args.args[0]['body']), remote_peer)
    packet = remote.packet()
    at = phone.now_ms()
    service._payload(peer, channel, dict(type='message', v=1, message_id=str(uuid.uuid4()), kind='file_transfer.control',
        created_ms=at, expires_ms=at+60_000, body=packet.wire()))
    remote.mark_sent(packet)
    remote.observe_remote(FileControlPacket.parse(channel.send.call_args.args[0]['body']), remote_peer)
    token = connection._preferences.read().policy.destination_token
    if source_send:
        assert connection._receive_binding() == remote.binding(token, sender_is_local=True)
    else:
        assert connection._controls.binding(token) is None and remote.binding(token, sender_is_local=True) is None
    channel.send.reset_mock()


@contextmanager
def reconnect(fixture):
    service, peer, old_channel, _, destination = fixture
    service._end_native_file_connection(old_channel)
    channel, binding = bind(service, peer)
    connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
    try:
        negotiate(service, peer, channel, connection)
        yield service, peer, channel, connection, destination
    finally: service._end_native_file_connection(channel)


def offer(fixture, data=b'hello', transfer='1'):
    service, peer, channel, connection, _ = fixture
    manifest = FileManifest(transfer*32, '2'*32, peer['device_id'], service.store.identity['device_id'],
        (ManifestFile('3'*32, 'Camera/photo.jpg', len(data), sha256(data).hexdigest()),), len(data))
    message = create_offer(manifest)
    service._payload(peer, channel, message)
    return message, manifest


def accept(fixture, data=b'hello'):
    message, manifest = offer(fixture, data)
    connection = fixture[3]
    connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    return message, manifest


def chunk(request, data):
    at = phone.now_ms()
    return dict(type='message', v=1, message_id=str(uuid.uuid4()), kind='file_transfer.chunk', created_ms=at, expires_ms=at+60_000,
        body=dict(request['body'], request_id=request['message_id'], data_base64=base64.b64encode(data).decode(), data_sha256=sha256(data).hexdigest()))


def test_native_offer_is_metadata_until_exact_explicit_action_then_admission_and_secure_accept(receiving):
    service, _, channel, connection, destination = receiving
    message, manifest = offer(receiving)
    root = Path(service.store.root)
    assert not (root/ProtectedTransferJobCatalog.NAME).exists() and not list(destination.iterdir())
    assert connection._run is None
    channel.send.assert_not_called()
    with pytest.raises(TransferError): connection.accept_pending_offer(connection.issue_receive_action(), str(uuid.uuid4()))
    result = connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert result.verified_bytes == 0 and not result.is_saved_receipt
    acceptance = channel.send.call_args.args[0]
    assert acceptance['kind'] == 'file_transfer.accept' and acceptance['body']['manifest_sha256'] == manifest.fingerprint
    assert acceptance['body']['acceptance_sha256'] == connection._run.accepted.fingerprint
    assert connection._run.acceptance_sent and len(connection._catalog.jobs()) == 1
    assert not (destination/'Camera/photo.jpg').exists()


@pytest.mark.parametrize('data', [b'hello', b'a'*CHUNK_BYTES+b'tail', b''], ids=['small', 'chunk-and-tail', 'empty'])
def test_actual_dispatch_receives_durable_chunks_then_explicit_publication_and_saved_projection(receiving, data):
    service, peer, channel, connection, destination = receiving
    _, manifest = accept(receiving, data)
    for index in range(manifest.files[0].chunks):
        request = connection.request_next_chunk()
        assert request['body']['chunk_index'] == index
        response = chunk(request, data[index*CHUNK_BYTES:(index+1)*CHUNK_BYTES])
        service._payload(peer, channel, response)
        service._payload(peer, channel, response)  # Exact durable duplicate, no recount.
    assert connection.request_next_chunk() is None
    progress = connection.receive_progress()
    assert progress.verified_bytes == len(data) and progress.checkpoint_verified_bytes == len(data)
    assert not progress.is_saved_receipt and not (destination/'Camera/photo.jpg').exists()
    saved = connection.publish_received(connection.issue_receive_action())
    assert saved.phase == 'saved_locally' and not saved.is_saved_receipt
    assert (destination/'Camera/photo.jpg').read_bytes() == data
    assert channel.send.call_args.args[0]['kind'] == 'file_transfer.saved'
    assert len(connection._catalog.jobs()) == 1  # Local save never retires source/cache quota or the whole slot.
    with pytest.raises(TransferError, match='run_held'): offer(receiving, transfer='4')


def test_failed_acceptance_output_retains_native_run_and_retries_exact_message(receiving):
    _, _, channel, connection, _ = receiving
    message, _ = offer(receiving)
    channel.send.side_effect = OSError('synthetic actual secure acceptance write failed')
    with pytest.raises(OSError): connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert not connection._run.acceptance_sent and len(connection._catalog.jobs()) == 1
    failed = channel.send.call_args.args[0]
    with pytest.raises(TransferError, match='acceptance_not_sent'): connection.request_next_chunk()
    channel.send.side_effect = None
    connection.retry_acceptance()
    assert channel.send.call_args.args[0] == failed and connection._run.acceptance_sent
    assert len(connection._catalog.jobs()) == 1


def test_unsolicited_or_wrongly_correlated_chunk_never_enters_native_stage(receiving):
    service, peer, channel, connection, _ = receiving
    accept(receiving)
    unsolicited = chunk(dict(body={}, message_id=str(uuid.uuid4())), b'hello')
    with pytest.raises(TransferError): service._payload(peer, channel, unsolicited)
    assert connection.receive_progress().verified_bytes == 0
    request = connection.request_next_chunk()
    wrong = chunk(request, b'hello'); wrong['body']['request_id'] = str(uuid.uuid4())
    with pytest.raises(TransferError): service._payload(peer, channel, wrong)
    assert connection.receive_progress().verified_bytes == 0


def test_existing_pc_edits_are_never_overwritten_by_explicit_publication(receiving):
    service, peer, _, connection, destination = receiving
    accept(receiving)
    request = connection.request_next_chunk()
    service._payload(peer, receiving[2], chunk(request, b'hello'))
    (destination/'Camera').mkdir()
    target = destination/'Camera/photo.jpg'; target.write_bytes(b'my PC edit'); inode = target.stat().st_ino
    with pytest.raises(TransferError): connection.publish_received(connection.issue_receive_action())
    assert target.read_bytes() == b'my PC edit' and target.stat().st_ino == inode
    assert len(connection._catalog.jobs()) == 1


def test_reply_arriving_before_actual_request_write_returns_waits_on_native_io_lane(receiving):
    service, peer, channel, connection, _ = receiving
    accept(receiving)
    entered = threading.Event(); release = threading.Event(); sent_end = threading.Event(); receive_end = threading.Event()
    incoming = threading.Event(); requests = []; errors = []
    def blocked(message):
        assert not service.lock._is_owned()
        requests.append(message); entered.set(); assert release.wait(5)
    channel.send.side_effect = blocked
    def request():
        try: connection.request_next_chunk()
        except Exception as error: errors.append(error)
        finally: sent_end.set()
    def receive():
        incoming.set()
        try: service._payload(peer, channel, chunk(requests[0], b'hello'))
        except Exception as error: errors.append(error)
        finally: receive_end.set()
    sender = threading.Thread(target=request); receiver = threading.Thread(target=receive)
    sender.start()
    try:
        assert entered.wait(5)
        receiver.start(); assert incoming.wait(5)
        assert not receive_end.wait(0.05), 'Immediate response was discarded instead of waiting behind native output'
        release.set(); assert sent_end.wait(5) and receive_end.wait(10)
        sender.join(5); receiver.join(5)
        assert not errors and connection.receive_progress().verified_bytes == 5
    finally:
        release.set(); sender.join(5)
        if receiver.ident is not None: receiver.join(10)
        assert not sender.is_alive() and not receiver.is_alive()


def test_native_close_during_staging_revokes_now_but_holds_descriptors_until_actual_io_end(receiving, monkeypatch):
    service, peer, channel, connection, destination = receiving
    accept(receiving)
    request = connection.request_next_chunk()
    native_receiver = connection._run.receiver
    write = native_receiver._stage.write_chunk
    entered = threading.Event(); release = threading.Event(); ended = threading.Event(); errors = []
    def blocked(*args):
        entered.set(); assert release.wait(5)
        return write(*args)
    monkeypatch.setattr(native_receiver._stage, 'write_chunk', blocked)
    def receive():
        try: service._payload(peer, channel, chunk(request, b'hello'))
        except Exception as error: errors.append(error)
        finally: ended.set()
    worker = threading.Thread(target=receive); worker.start()
    try:
        assert entered.wait(5)
        service._end_native_file_connection(channel)
        assert connection._closed.is_set() and not native_receiver._index._closed
        assert not connection._authority.protection._closed
        release.set(); assert ended.wait(10); worker.join(5)
        assert len(errors) == 1 and isinstance(errors[0], TransferError)
        assert native_receiver._index._closed and connection._authority.protection._closed
        assert not (destination/'Camera/photo.jpg').exists()
        assert (Path(service.store.root)/ProtectedTransferJobCatalog.NAME).exists()
    finally:
        release.set(); worker.join(10)
        assert not worker.is_alive()


def test_saved_confirmation_retry_preserves_later_pc_edit_without_republication(receiving):
    service, peer, channel, connection, destination = receiving
    accept(receiving)
    request = connection.request_next_chunk()
    service._payload(peer, channel, chunk(request, b'hello'))
    connection.publish_received(connection.issue_receive_action())
    saved = channel.send.call_args.args[0]
    target = destination/'Camera/photo.jpg'; target.write_bytes(b'my later PC edit'); inode = target.stat().st_ino
    connection.send_saved_confirmation()
    assert channel.send.call_args.args[0]['body'] == saved['body']
    assert target.read_bytes() == b'my later PC edit' and target.stat().st_ino == inode
    assert len(connection._catalog.jobs()) == 1


def test_failed_request_write_can_only_be_retried_as_the_exact_pending_request(receiving):
    service, peer, channel, connection, _ = receiving
    accept(receiving)
    channel.send.side_effect = OSError('synthetic request write failure')
    with pytest.raises(OSError): connection.request_next_chunk()
    request = channel.send.call_args.args[0]
    with pytest.raises(TransferError, match='not_requested'): service._payload(peer, channel, chunk(request, b'hello'))
    assert connection.receive_progress().verified_bytes == 0
    channel.send.side_effect = None
    assert connection.request_next_chunk() == request
    service._payload(peer, channel, chunk(request, b'hello'))
    assert connection.receive_progress().verified_bytes == 5


def test_pending_offer_cannot_be_rebound_to_changed_native_policy(receiving):
    service, peer, channel, connection, _ = receiving
    message, _ = offer(receiving)
    prefs = connection._preferences
    old = prefs.read()
    prefs.configure(prefs.issue_action(), old, enabled=True, mode='automatic')
    negotiate(service, peer, channel, connection)
    with pytest.raises(TransferError, match='offer_authority_changed'):
        connection.accept_pending_offer(connection.issue_receive_action(), message['message_id'])
    assert connection._run is None and connection._catalog is None


def test_dispatcher_input_mutation_cannot_extend_the_frozen_native_offer(receiving):
    original, manifest = offer(receiving)
    connection = receiving[3]
    frozen = connection._offer
    # Mutate the actual dispatcher input after it has returned.
    original['body']['manifest_sha256'] = 'f'*64
    original['body']['manifest']['files'][0]['size'] = 999
    connection.accept_pending_offer(connection.issue_receive_action(), frozen['message_id'])
    assert connection._run.accepted.manifest == manifest


def test_foreign_or_wire_action_never_admits_a_native_receive_job(receiving):
    _, _, _, connection, _ = receiving
    message, _ = offer(receiving)
    for action in ({'token': 'wire'}, connection._preferences.issue_action()):
        with pytest.raises(TransferError): connection.accept_pending_offer(action, message['message_id'])
    assert connection._run is None and connection._catalog is None


def test_existing_job_discovery_without_catalog_never_creates_one(receiving):
    service, _, _, connection, _ = receiving
    assert connection.native_receive_jobs() == ()
    assert not (Path(service.store.root)/ProtectedTransferJobCatalog.NAME).exists()


def test_reconnect_resume_selects_only_actual_missing_checkpoint_bytes_and_does_not_republish(receiving):
    service, peer, channel, connection, destination = receiving
    data = b'a'*CHUNK_BYTES+b'tail'
    accept(receiving, data)
    first = connection.request_next_chunk()
    service._payload(peer, channel, chunk(first, data[:CHUNK_BYTES]))
    job = connection._run.job
    with reconnect(receiving) as new:
        resumed = new[3]
        assert resumed.native_receive_jobs() == (job,)
        message, _ = offer(new, data)
        progress = resumed.resume_pending_offer(resumed.issue_receive_action(), message['message_id'], job.owner)
        assert progress.verified_bytes == CHUNK_BYTES and progress.phase == 'receiving_publication_repair_pending'
        next_request = resumed.request_next_chunk()
        assert next_request['body']['chunk_index'] == 1 and next_request['body']['file_id'] == first['body']['file_id']
        new[0]._payload(new[1], new[2], chunk(next_request, b'tail'))
        assert resumed.request_next_chunk() is None
        assert resumed.receive_progress().checkpoint_verified_bytes == len(data)
        with pytest.raises(TransferError, match='publication_repair_required'):
            resumed.publish_received(resumed.issue_receive_action())
        with pytest.raises(TransferError): resumed.send_saved_confirmation()
        assert len(resumed._catalog.jobs()) == 1 and not (destination/'Camera/photo.jpg').exists()


def test_corrupt_actual_staged_bytes_fence_resume_without_replacement_or_new_reservation(receiving):
    service, peer, channel, connection, destination = receiving
    data = b'a'*CHUNK_BYTES+b'tail'
    accept(receiving, data)
    first = connection.request_next_chunk()
    service._payload(peer, channel, chunk(first, data[:CHUNK_BYTES]))
    job = connection._run.job
    parent = connection._catalog.require_reserved(job)
    service._end_native_file_connection(channel)
    path = parent/('file-transfer-'+job.owner)/(first['body']['file_id']+'-0.enc')
    original = path.read_bytes(); damaged = original[:-1]+bytes([original[-1]^1]); path.write_bytes(damaged)
    with reconnect(receiving) as new:
        resumed = new[3]
        message, _ = offer(new, data)
        with pytest.raises(TransferError, match='start_pending'):
            resumed.resume_pending_offer(resumed.issue_receive_action(), message['message_id'], job.owner)
        assert resumed._run.job == job and resumed._run.receiver is None
        assert path.read_bytes() == damaged and len(resumed._catalog.jobs()) == 1
        with pytest.raises(TransferError): resumed.request_next_chunk()
        assert not (destination/'Camera/photo.jpg').exists()


def test_resume_requires_exact_native_job_and_whole_manifest(receiving):
    accept(receiving)
    job = receiving[3]._run.job
    with reconnect(receiving) as new:
        resumed = new[3]
        message, _ = offer(new, b'other')
        with pytest.raises(TransferError, match='resume_not_current'):
            resumed.resume_pending_offer(resumed.issue_receive_action(), message['message_id'], job.owner)
        with pytest.raises(TransferError, match='resume_not_current'):
            resumed.resume_pending_offer(resumed.issue_receive_action(), message['message_id'], 'f'*32)
        assert resumed._run is None and len(resumed._catalog.jobs()) == 1


def test_saved_job_resume_exports_historical_receipts_without_overwriting_later_pc_edits(receiving):
    service, peer, channel, connection, destination = receiving
    accept(receiving)
    request = connection.request_next_chunk()
    service._payload(peer, channel, chunk(request, b'hello'))
    connection.publish_received(connection.issue_receive_action())
    job = connection._run.job; saved = channel.send.call_args.args[0]
    target = destination/'Camera/photo.jpg'; target.write_bytes(b'my later PC edit'); inode = target.stat().st_ino
    with reconnect(receiving) as new:
        resumed = new[3]
        message, _ = offer(new)
        resumed.resume_pending_offer(resumed.issue_receive_action(), message['message_id'], job.owner)
        assert resumed.request_next_chunk() is None
        resumed.send_saved_confirmation()
        assert new[2].send.call_args.args[0]['body'] == saved['body']
        assert target.read_bytes() == b'my later PC edit' and target.stat().st_ino == inode
        assert len(resumed._catalog.jobs()) == 1


def test_expiry_during_actual_stage_readback_does_not_report_a_late_received_chunk(receiving, monkeypatch):
    _, _, _, connection, destination = receiving
    accept(receiving)
    at = [phone.now_ms()]
    request = connection.request_next_chunk(clock=lambda:at[0])
    receive = connection._run.receiver.receive_chunk_message
    def late(*args, **kwargs):
        result = receive(*args, **kwargs)
        at[0] = request['expires_ms']
        return result
    monkeypatch.setattr(connection._run.receiver, 'receive_chunk_message', late)
    with pytest.raises(TransferError, match='expired_during_native_io'):
        connection.receive(chunk(request, b'hello'), clock=lambda:at[0])
    assert connection._run.request == request and not (destination/'Camera/photo.jpg').exists()
    assert len(connection._catalog.jobs()) == 1


def test_cleanup_fault_does_not_skip_other_resources_or_report_native_owner_release(receiving, monkeypatch):
    service, _, channel, connection, _ = receiving
    accept(receiving)
    receiver = connection._run.receiver
    close = receiver.close
    def uncertain():
        close()
        raise OSError('synthetic receiver-close uncertainty')
    monkeypatch.setattr(receiver, 'close', uncertain)
    assert service._end_native_file_connection(channel) is False
    assert connection._authority.protection._closed and receiver._index._closed
    assert service._native_file_connections[channel] is connection
    assert channel not in service._file_channel_bindings and not connection._release_reported
    monkeypatch.setattr(receiver, 'close', close)
    assert service._end_native_file_connection(channel) is False
    assert connection._cleanup_error == 'OSError' and not connection._release_reported
