"""Local stop is checkpoint/descriptor evidence, not remote repair authority."""
from contextlib import contextmanager
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, chunk, accept
from test_file_desktop_resume_sources import selected, start, collect, offer, held, cancel
from test_file_desktop_media import dispatch


@contextmanager
def resumed(fixture):
    with selected(fixture, partial=True) as (fresh, job, history):
        start(fresh); collect(fresh, job); offered = offer(fresh, job)
        connection = fresh[3]
        connection.resume_pending_offer(connection.issue_receive_action(), offered['message_id'], job.owner)
        yield fresh, job, history


def test_idle_stop_checkpoints_closes_then_releases_only_local_receiver(receiving):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; run = connection._run; receiver = run.receiver
        result = connection.request_receive_stop(connection.issue_receive_action())
        assert result.state == 'stopped' and result.io_ended and result.resources_closed
        assert result.checkpoint_committed and result.checkpoint_verified_bytes == 5
        assert not result.is_saved_receipt and not result.grants_write_authority and not result.grants_repair_authority
        assert connection._run is None and receiver._closed and receiver._index._closed
        assert connection._source_run is not None
        with pytest.raises(TransferError): connection.request_next_chunk()
        held(fresh, job)


def test_checkpoint_readback_and_actual_close_precede_owner_release_without_new_output(receiving, monkeypatch):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; run = connection._run; receiver = run.receiver
        checkpoint = receiver.checkpoint; close = receiver.close; calls = []
        def checked():
            assert connection._run is run and not receiver._closed
            progress = checkpoint()
            assert progress.verified_bytes == progress.checkpoint_verified_bytes
            calls.append('checkpoint_readback'); return progress
        def closed():
            assert connection._run is run and calls == ['checkpoint_readback']
            close(); assert receiver._index._closed
            calls.append('actual_close')
        monkeypatch.setattr(receiver, 'checkpoint', checked)
        monkeypatch.setattr(receiver, 'close', closed)
        count = fresh[2].send.call_count
        state = connection.request_receive_stop(connection.issue_receive_action())
        assert calls == ['checkpoint_readback', 'actual_close'] and state.state == 'stopped'
        assert connection._run is None and fresh[2].send.call_count == count
        with pytest.raises(TransferError): connection.retry_acceptance()
        with pytest.raises(TransferError): connection.publish_received(connection.issue_receive_action())
        assert fresh[2].send.call_count == count
        held(fresh, job)


def test_normal_receiver_is_not_silently_stopped_by_resume_action(receiving):
    accept(receiving)
    connection = receiving[3]; run = connection._run
    with pytest.raises(TransferError): connection.request_receive_stop(connection.issue_receive_action())
    assert connection._run is run and not run.stop_requested.is_set() and not run.receiver._closed
    assert connection.receive_stop_state() is None


def test_stop_during_output_preflight_blocks_socket_before_attempt_marker(receiving):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; run = connection._run; count = fresh[2].send.call_count; marked = []
        def clock():
            connection.request_receive_stop(connection.issue_receive_action())
            return run.acceptance['created_ms']
        with pytest.raises(TransferError, match='stop_requested'):
            with connection._operation():
                connection._send_data(run.acceptance, clock, on_output=lambda:marked.append(True))
        assert not marked and fresh[2].send.call_count == count
        assert connection.receive_stop_state().state == 'stopped' and connection._run is None
        held(fresh, job)


def test_blocked_actual_stage_write_retains_owner_until_true_end_and_checkpoint_close(receiving, monkeypatch):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; request = connection.request_next_chunk(); run = connection._run
        receiver = run.receiver; write = receiver._stage.write_chunk
        entered = threading.Event(); release = threading.Event(); ended = threading.Event(); errors = []
        def blocked(*args):
            entered.set(); assert release.wait(5)
            return write(*args)
        monkeypatch.setattr(receiver._stage, 'write_chunk', blocked)
        def incoming():
            try: dispatch(fresh, chunk(request, b'hello'))
            except Exception as error: errors.append(error)
            finally: ended.set()
        worker = threading.Thread(target=incoming); worker.start()
        try:
            assert entered.wait(5)
            state = connection.request_receive_stop(connection.issue_receive_action())
            assert state.state == 'pending' and not state.io_ended
            assert connection._run is run and not receiver._index._closed and not ended.is_set()
        finally:
            release.set(); worker.join(5)
        assert not worker.is_alive() and ended.is_set() and not errors
        state = connection.receive_stop_state()
        assert state.state == 'stopped' and state.checkpoint_verified_bytes == 10 and state.resources_closed
        assert connection._run is None and receiver._index._closed
        dispatch(fresh, chunk(request, b'hello'))  # Already verified duplicate, no stage reopen.
        assert receiver._index._closed and connection._run is None
        held(fresh, job)


def test_attempted_request_stop_waits_for_correlated_chunk_not_premature_close(receiving):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; request = connection.request_next_chunk(); run = connection._run
        state = connection.request_receive_stop(connection.issue_receive_action())
        assert state.state == 'pending' and connection._run is run and not run.receiver._closed
        with pytest.raises(TransferError): connection.request_next_chunk()
        dispatch(fresh, chunk(request, b'hello'))
        assert connection.receive_stop_state().checkpoint_verified_bytes == 10
        assert connection._run is None
        held(fresh, job)


def test_ordered_source_cancel_barrier_allows_stop_without_unreceived_chunk(receiving):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; connection.request_next_chunk(); run = connection._run
        assert connection.request_receive_stop(connection.issue_receive_action()).state == 'pending'
        cancel(fresh)
        assert run.stop_barrier_confirmed and connection._run is None
        state = connection.receive_stop_state()
        assert state.state == 'stopped' and state.checkpoint_verified_bytes == 5
        held(fresh, job)


def test_blocked_socket_output_stop_keeps_uncertain_request_until_actual_response(receiving):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; run = connection._run
        entered = threading.Event(); release = threading.Event(); errors = []; sent = []
        def output(message):
            sent.append(message); entered.set(); assert release.wait(5)
            raise OSError('fixture uncertain socket output')
        fresh[2].send.side_effect = output
        def outgoing():
            try: connection.request_next_chunk()
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=outgoing); worker.start()
        try:
            assert entered.wait(5)
            assert connection.request_receive_stop(connection.issue_receive_action()).state == 'pending'
            assert connection._run is run and not run.receiver._closed
        finally:
            release.set(); worker.join(5); fresh[2].send.side_effect = None
        assert not worker.is_alive() and len(errors) == 1 and isinstance(errors[0], OSError)
        assert run.request_output_started and not run.request_sent and connection._run is run
        assert connection.receive_stop_state().state == 'pending'
        dispatch(fresh, chunk(sent[0], b'hello'))
        assert connection.receive_stop_state().state == 'stopped'
        assert connection.receive_stop_state().checkpoint_verified_bytes == 10
        held(fresh, job)


def test_stopped_duplicate_still_requires_valid_bytes_binding_and_current_authority(receiving):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; request = connection.request_next_chunk()
        dispatch(fresh, chunk(request, b'hello'))
        connection.request_receive_stop(connection.issue_receive_action())
        assert connection.receive_stop_state().state == 'stopped'
        with pytest.raises(TransferError): dispatch(fresh, chunk(request, b'other'))
        foreign = chunk(request, b'hello'); foreign['body']['request_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        with pytest.raises(TransferError): dispatch(fresh, foreign)
        connection._authority.revoke()
        with pytest.raises(TransferError): connection.receive(chunk(request, b'hello'))
        assert connection._run is None and not connection.receive_stop_state().grants_repair_authority


def test_revocation_during_checkpoint_keeps_failed_owner_after_real_cleanup(receiving, monkeypatch):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; run = connection._run; checkpoint = run.receiver.checkpoint
        def revoked():
            progress = checkpoint(); connection._authority.revoke()
            return progress
        monkeypatch.setattr(run.receiver, 'checkpoint', revoked)
        state = connection.request_receive_stop(connection.issue_receive_action())
        assert state.state == 'failed' and state.resources_closed and state.checkpoint_committed
        assert connection._run is run and run.receiver._index._closed
        assert not state.grants_repair_authority


@pytest.mark.parametrize('failure', ['checkpoint', 'close', 'already_closed'])
def test_uncertain_checkpoint_or_close_retains_failed_owner_and_cannot_retry_as_success(receiving, monkeypatch, failure):
    with resumed(receiving) as (fresh, job, _):
        connection = fresh[3]; run = connection._run; receiver = run.receiver
        def fail(): raise OSError('fixture stop boundary failure')
        if failure == 'checkpoint': monkeypatch.setattr(receiver, 'checkpoint', fail)
        elif failure == 'close':
            close = receiver.close
            def uncertain():
                close(); fail()
            monkeypatch.setattr(receiver, 'close', uncertain)
        else: receiver.close()
        state = connection.request_receive_stop(connection.issue_receive_action())
        assert state.state == 'failed' and connection._run is run
        assert not state.grants_repair_authority
        assert connection.request_receive_stop(connection.issue_receive_action()) == state
        with pytest.raises(TransferError): connection.request_next_chunk()
        held(fresh, job)
