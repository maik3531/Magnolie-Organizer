"""Dedicated file consent/echo/session ownership; no Notes/contact grant reuse."""
from dataclasses import replace
import json
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_control import (FileControlPacket, FileGrantState, NativeFileControlSession,
    NativeFilePeer, NativeLocalFileGrant, MAX_REVISION)
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity


class Side:
    def __init__(self, identity, peer_identity, grants):
        self.identity = identity
        self.peer = NativeFilePeer(peer_identity.receiver_id, peer_identity.receiver_identity_sha256,
            object(), True, True, True, True, True)
        self.local = NativeLocalFileGrant(grants, object(), True)
        self.session = self.new_session()

    def new_session(self):
        return NativeFileControlSession(self.identity, lambda: self.peer, lambda: self.local)


def pair():
    first = NativeJobCatalogIdentity("sender_fixture_01", "d" * 64)
    second = NativeJobCatalogIdentity("receiver_fixture_01", "e" * 64)
    return Side(first, second, FileGrantState(3, "a" * 64, True, False)), Side(second, first, FileGrantState(7, "b" * 64, False, True))


def send(sender, receiver):
    packet = sender.session.packet()
    # Explicit native successful-send completion; a decoded wire copy is not
    # that native ticket. Actual encrypted-channel I/O integration is separate.
    sender.session.mark_sent(packet)
    receiver.session.observe_remote(FileControlPacket.parse(json.loads(json.dumps(packet.wire()))), receiver.peer)
    return packet


def handshake(first, second):
    send(first, second)
    send(second, first)
    if first.session.needs_packet:
        send(first, second)
    if second.session.needs_packet:
        send(second, first)


def test_no_binding_before_fresh_bidirectional_echo_and_actual_native_send_completion():
    first, second = pair()
    assert first.session.binding("c" * 64, sender_is_local=True) is None
    initial = send(first, second)
    assert initial.echo is None and second.session.binding("c" * 64) is None
    reply = send(second, first)
    assert reply.echo == initial.challenge and first.session.binding("c" * 64, sender_is_local=True) is None
    echo = first.session.packet()
    with pytest.raises(TransferError, match="invalid_native_send_completion"):
        first.session.mark_sent(FileControlPacket.parse(echo.wire()))
    assert first.session.binding("c" * 64, sender_is_local=True) is None
    first.session.mark_sent(echo)
    second.session.observe_remote(FileControlPacket.parse(echo.wire()), second.peer)
    native_first = first.session.binding("c" * 64, sender_is_local=True)
    native_second = second.session.binding("c" * 64)
    assert native_first == native_second and native_first.sender_id == first.identity.receiver_id
    assert first.session.binding("c" * 64) is None  # Independent direction remains off.
    assert not first.session.needs_packet and not second.session.needs_packet


def test_fresh_channel_handshake_preserves_persistent_binding_but_old_echo_cannot_resume_it():
    first, second = pair()
    handshake(first, second)
    before = first.session.binding("c" * 64, sender_is_local=True)
    old_packet = first.session.packet()
    old_session = first.session
    first.peer = replace(first.peer, owner=object())
    second.peer = replace(second.peer, owner=object())
    assert old_session.binding("c" * 64, sender_is_local=True) is None
    first.session, second.session = first.new_session(), second.new_session()
    second.session.observe_remote(FileControlPacket.parse(old_packet.wire()), second.peer)
    assert second.session.binding("c" * 64) is None
    handshake(first, second)
    assert first.session.binding("c" * 64, sender_is_local=True) == second.session.binding("c" * 64) == before


@pytest.mark.parametrize("field", ["ready", "paired", "own_device", "remote_own_device", "control_supported"])
def test_native_current_peer_scope_not_wire_booleans_controls_readiness(field):
    first, second = pair()
    handshake(first, second)
    assert second.session.binding("c" * 64) is not None
    second.peer = replace(second.peer, **{field: False})
    assert second.session.binding("c" * 64) is None
    with pytest.raises(TransferError, match="native_scope_changed"):
        second.session.observe_remote(first.session.packet(), second.peer)


def test_receiver_key_owner_or_native_local_store_owner_change_is_sticky_not_adopted():
    for field in ("identity_sha256", "owner", "local_owner"):
        first, second = pair()
        handshake(first, second)
        original_peer, original_local = second.peer, second.local
        if field == "local_owner":
            second.local = replace(second.local, owner=object())
        else:
            second.peer = replace(second.peer, **{field: "f" * 64 if field == "identity_sha256" else object()})
        assert second.session.binding("c" * 64) is None
        second.peer, second.local = original_peer, original_local
        assert second.session.binding("c" * 64) is None


def test_grant_revocation_pauses_immediately_and_requires_fresh_echo_for_new_epoch():
    first, second = pair()
    handshake(first, second)
    old = second.session.binding("c" * 64)
    second.local = replace(second.local, grants=FileGrantState(8, "c" * 64, False, False))
    assert second.session.binding("c" * 64) is None
    send(second, first)
    assert first.session.binding("c" * 64, sender_is_local=True) is None
    second.local = replace(second.local, grants=FileGrantState(9, "d" * 64, False, True))
    assert second.session.binding("c" * 64) is None
    send(second, first)
    send(first, second)
    current = second.session.binding("c" * 64)
    assert current is not None and current.permission_epoch != old.permission_epoch


def test_capability_versions_can_expand_without_rekeying_accepted_v1_consent():
    first, second = pair()
    handshake(first, second)
    old = second.session.binding("c" * 64)
    first.local = replace(first.local, grants=replace(first.local.grants, manifest_versions=(1, 2)))
    assert first.session.binding("c" * 64, sender_is_local=True) is None
    send(first, second)
    send(second, first)
    assert second.session.binding("c" * 64) == first.session.binding("c" * 64, sender_is_local=True) == old
    first.local = replace(first.local, grants=replace(first.local.grants, manifest_versions=(2,)))
    send(first, second)
    assert second.session.binding("c" * 64) is None


def test_same_sequence_or_grant_revision_equivocation_never_silently_updates_consent():
    first, second = pair()
    packet = send(first, second)
    assert not second.session.observe_remote(FileControlPacket.parse(packet.wire()), second.peer)
    forged = replace(packet, grants=replace(packet.grants, send_files=False))
    with pytest.raises(TransferError, match="equivocation"):
        second.session.observe_remote(forged, second.peer)
    assert second.session.binding("c" * 64) is None


def test_stale_metadata_does_not_replace_new_native_authenticated_grant_state():
    first, second = pair()
    old = send(first, second)
    send(second, first)
    newest = send(first, second)
    with pytest.raises(TransferError, match="stale_packet"):
        second.session.observe_remote(old, second.peer)
    assert not second.session.observe_remote(newest, second.peer)
    assert second.session.binding("c" * 64) is not None


def test_native_grant_counter_rollback_and_same_counter_mutation_fail_closed():
    for grants in (FileGrantState(6, "b" * 64, False, True), FileGrantState(7, "b" * 64, True, True)):
        first, second = pair()
        handshake(first, second)
        second.local = replace(second.local, grants=grants)
        assert second.session.binding("c" * 64) is None


@pytest.mark.parametrize("change", ["version-bool", "grant-revision-bool", "unsafe-integer", "flag-int", "unsorted", "duplicate", "echo", "extra"])
def test_strict_control_wire_shapes(change):
    packet = FileControlPacket(FileGrantState(1, "a" * 64), "b" * 64, 1, None).wire()
    if change == "version-bool":
        packet["format"] = True
    elif change == "grant-revision-bool":
        packet["grant_revision"] = True
    elif change == "unsafe-integer":
        packet["sequence"] = MAX_REVISION + 1
    elif change == "flag-int":
        packet["send_files"] = 1
    elif change == "unsorted":
        packet["manifest_versions"] = [2, 1]
    elif change == "duplicate":
        packet["manifest_versions"] = [1, 1]
    elif change == "echo":
        packet["echo"] = "peer-name-not-native-proof"
    else:
        packet["personal_notes_sync"] = True
    with pytest.raises(TransferError):
        FileControlPacket.parse(packet)


def test_packet_construction_or_remote_parse_is_not_native_local_authority():
    first, second = pair()
    packet = first.session.packet()
    with pytest.raises(TransferError, match="invalid_native_send_completion"):
        first.session.mark_sent(None)
    second.local = FileControlPacket.parse(packet.wire()).grants
    assert second.session.binding("c" * 64) is None
    with pytest.raises(TransferError, match="native_local_state_required"):
        NativeLocalFileGrant(packet.grants, None, True)
    with pytest.raises(TransferError, match="native_local_state_required"):
        NativeLocalFileGrant(replace(packet.grants, send_files=True), object(), False)


def test_no_echo_churn_after_fresh_exchange_and_close_removes_scope():
    first, second = pair()
    handshake(first, second)
    assert not first.session.needs_packet and not second.session.needs_packet
    first.session.close()
    assert first.session.binding("c" * 64, sender_is_local=True) is None and not first.session.needs_packet


def test_shared_control_canonical_challenge_and_persistent_permission_epoch():
    vector = json.loads((Path(__file__).resolve().parents[2] / "contracts/file-transfer-control-v1-vectors.json").read_text())
    packet = FileControlPacket.parse(vector["packet"])
    raw = json.dumps(packet.wire(), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(raw) == vector["canonical_bytes"] and sha256(raw).hexdigest() == vector["canonical_sha256"]
    assert packet.challenge == vector["challenge_sha256"]
    first, second = pair()
    handshake(first, second)
    assert first.session.binding("c" * 64, sender_is_local=True).permission_epoch == vector["permission_epoch"]


def test_native_pending_policy_blocks_io_and_packets_without_rekeying_confirmed_grants():
    first, second = pair()
    handshake(first, second)
    before = first.session.binding("c" * 64, sender_is_local=True)
    first.local = replace(first.local, policy_ready=False)
    assert first.session.binding("c" * 64, sender_is_local=True) is None and not first.session.needs_packet
    with pytest.raises(TransferError, match="policy_pending"):
        first.session.packet()
    first.local = replace(first.local, policy_ready=True)
    assert first.session.binding("c" * 64, sender_is_local=True) == before
