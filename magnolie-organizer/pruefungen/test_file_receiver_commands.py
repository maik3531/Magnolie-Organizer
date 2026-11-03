"""Exact native receiver-command authority; no photo read or transfer implied."""
from dataclasses import replace

import pytest

from test_file_control import pair, handshake, send
from magnolie_file_control import FileGrantState, NativeFileControlSession, NativeReceiverCommandTicket
from magnolie_file_transfer import TransferError


def sides(*, ready=True):
    source, receiver = pair()
    source.local = replace(source.local, grants=FileGrantState(1, 'a'*64, False, False))
    source.session = source.new_session()
    clock = [100]
    receiver.session = NativeFileControlSession(receiver.identity, lambda:receiver.peer, lambda:receiver.local, monotonic_ms=lambda:clock[0])
    if ready: handshake(source, receiver)
    return source, receiver, clock


def test_completed_native_echo_and_own_receive_consent_bootstrap_metadata_while_source_send_off():
    _, receiver, _ = sides()
    ticket = receiver.session.receiver_command_ticket()
    assert receiver.session.receiver_command_current(ticket)
    assert receiver.session.binding('f'*64) is None
    with pytest.raises(TransferError, match='not_ready'): receiver.session.receiver_command_ticket()
    receiver.session.finish_receiver_command(ticket)
    assert not receiver.session.receiver_command_current(ticket)
    fresh = receiver.session.receiver_command_ticket()
    assert fresh is not ticket and receiver.session.receiver_command_current(fresh)
    receiver.session.finish_receiver_command(fresh)


def test_received_or_queued_control_without_actual_sent_echo_cannot_issue_a_command_ticket():
    source, receiver, _ = sides(ready=False)
    send(source, receiver)
    with pytest.raises(TransferError): receiver.session.receiver_command_ticket()
    send(receiver, source)
    with pytest.raises(TransferError): receiver.session.receiver_command_ticket()
    pending = source.session.packet()  # Queued/constructed is not native send completion.
    assert not receiver.session._remote.echo
    with pytest.raises(TransferError): receiver.session.receiver_command_ticket()
    source.session.mark_sent(pending)
    receiver.session.observe_remote(pending, receiver.peer)
    assert receiver.session.receiver_command_current(receiver.session.receiver_command_ticket())


def test_other_native_session_or_serialized_copy_cannot_adopt_a_command_ticket():
    _, receiver, _ = sides()
    ticket = receiver.session.receiver_command_ticket()
    _, other, _ = sides()
    for foreign in (ticket, NativeReceiverCommandTicket(), {'ticket': 'wire'}, None):
        assert not other.session.receiver_command_current(foreign)
        with pytest.raises(TransferError): other.session.finish_receiver_command(foreign)
    assert receiver.session.receiver_command_current(ticket)
    receiver.session.finish_receiver_command(ticket)
    with pytest.raises(TransferError): receiver.session.finish_receiver_command(ticket)


@pytest.mark.parametrize('change', ['expiry', 'rollback'])
def test_deadline_or_observed_monotonic_rollback_permanently_fences_the_attempt(change):
    _, receiver, clock = sides()
    ticket = receiver.session.receiver_command_ticket()
    clock[0] = 200
    assert receiver.session.receiver_command_current(ticket)
    clock[0] = 60_100 if change == 'expiry' else 199
    assert not receiver.session.receiver_command_current(ticket)
    clock[0] = 201
    assert not receiver.session.receiver_command_current(ticket)
    receiver.session.finish_receiver_command(ticket)


def test_local_policy_pending_is_not_consent_and_restoring_it_cannot_revive_old_ticket():
    _, receiver, _ = sides()
    ticket = receiver.session.receiver_command_ticket()
    original = receiver.local
    receiver.local = replace(original, policy_ready=False)
    assert not receiver.session.receiver_command_current(ticket)
    receiver.local = original
    assert not receiver.session.receiver_command_current(ticket)
    receiver.session.finish_receiver_command(ticket)


def test_source_send_policy_may_change_during_authorized_configuration_but_data_needs_fresh_echo():
    source, receiver, _ = sides()
    ticket = receiver.session.receiver_command_ticket()
    source.local = replace(source.local, grants=FileGrantState(2, 'c'*64, True, False))
    send(source, receiver)
    assert receiver.session.receiver_command_current(ticket)
    assert receiver.session.binding('f'*64) is None
    send(receiver, source)
    assert receiver.session.binding('f'*64) is not None
    receiver.session.finish_receiver_command(ticket)


def test_remote_session_switch_is_sticky_even_if_old_session_packet_is_restored():
    source, receiver, _ = sides()
    ticket = receiver.session.receiver_command_ticket()
    original = source.session
    source.session = source.new_session()
    send(source, receiver)
    assert not receiver.session.receiver_command_current(ticket)
    source.session = original
    send(source, receiver)
    assert not receiver.session.receiver_command_current(ticket)
    receiver.session.finish_receiver_command(ticket)


@pytest.mark.parametrize('change', ['receive-off', 'pairing', 'close', 'io-error'])
def test_native_consent_pairing_lifecycle_or_io_failure_cannot_be_restored_into_ticket_authority(change):
    _, receiver, _ = sides()
    ticket = receiver.session.receiver_command_ticket()
    original_local, original_peer = receiver.local, receiver.peer
    if change == 'receive-off': receiver.local = replace(receiver.local, grants=FileGrantState(8, 'd'*64, False, False))
    elif change == 'pairing': receiver.peer = replace(receiver.peer, pairing_epoch='e'*64)
    elif change == 'close': receiver.session.close()
    else:
        def failed(): raise OSError('synthetic native metadata I/O failure')
        original_callback = receiver.session._current_peer
        receiver.session._current_peer = failed
        with pytest.raises(OSError): receiver.session.receiver_command_current(ticket)
        receiver.session._current_peer = original_callback
    assert not receiver.session.receiver_command_current(ticket)
    receiver.local, receiver.peer = original_local, original_peer
    assert not receiver.session.receiver_command_current(ticket)
    assert ticket in receiver.session._receiver_commands  # End/close is not actual attempt-finally.
    receiver.session.finish_receiver_command(ticket)


def test_local_send_or_remote_receive_alone_cannot_substitute_for_own_native_receive_consent():
    source, receiver = pair()
    handshake(source, receiver)
    with pytest.raises(TransferError): source.session.receiver_command_ticket()
