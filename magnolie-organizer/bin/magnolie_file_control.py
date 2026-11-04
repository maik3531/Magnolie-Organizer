"""Dedicated authenticated own-peer file-control negotiation (#330).

Never mutates the global contacts/notes grant set or treats device_status itself
as file consent. Discovery version 21 is reserved but MUST NOT be advertised
before actual native file handlers are ready. Local state is a distinct native
type, not deserialized remote data; current native peer/channel ownership is
checked independently of the wire packet. No I/O, timers, store or listeners.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
import secrets
import threading
import time

from magnolie_file_transfer import NativeTransferBinding, TransferError
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity


KIND = "file_transfer.control"
DISCOVERY_VERSION = 21
VIDEO_DISCOVERY_VERSION = 22
MAX_REVISION = 2**53 - 1
MAX_WIRE_BYTES = 8192
MAX_TTL_MS = 60_000


def _hex(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _revision(value):
    return type(value) is int and 1 <= value <= MAX_REVISION


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class FileGrantState:
    revision: int
    epoch: str
    send_files: bool = False
    receive_files: bool = False
    manifest_versions: tuple = (1,)

    def __post_init__(self):
        if (not _revision(self.revision) or not _hex(self.epoch) or type(self.send_files) is not bool
                or type(self.receive_files) is not bool or type(self.manifest_versions) is not tuple
                or not 1 <= len(self.manifest_versions) <= 8
                or any(type(version) is not int or not 1 <= version <= 65535 for version in self.manifest_versions)
                or tuple(sorted(set(self.manifest_versions))) != self.manifest_versions):
            raise TransferError("file_control_invalid_grant_state")

    def wire(self):
        return {"grant_revision": self.revision, "grant_epoch": self.epoch, "send_files": self.send_files,
            "receive_files": self.receive_files, "manifest_versions": list(self.manifest_versions)}

    def permission_wire(self):
        # Supported future formats are capability metadata, not a new consent
        # epoch for an already accepted format-1 operation.
        return {key: value for key, value in self.wire().items() if key != "manifest_versions"}


@dataclass(frozen=True)
class FileControlPacket:
    grants: FileGrantState
    session_epoch: str
    sequence: int
    echo: str | None

    def __post_init__(self):
        if (type(self.grants) is not FileGrantState or not _hex(self.session_epoch) or not _revision(self.sequence)
                or self.echo is not None and not _hex(self.echo)):
            raise TransferError("file_control_invalid_packet")

    def wire(self):
        return dict(self.grants.wire(), format=1, session_epoch=self.session_epoch, sequence=self.sequence, echo=self.echo)

    @property
    def challenge(self):
        # Sequence/echo are deliberately excluded to avoid an echo feedback loop.
        value = dict(self.grants.wire(), format=1, session_epoch=self.session_epoch)
        return sha256(b"magnolie-file-control-challenge-v1\0" + _canonical(value)).hexdigest()

    @classmethod
    def parse(cls, value):
        fields = {"format", "grant_revision", "grant_epoch", "send_files", "receive_files", "manifest_versions",
            "session_epoch", "sequence", "echo"}
        if (type(value) is not dict or set(value) != fields or type(value["format"]) is not int or value["format"] != 1
                or type(value["manifest_versions"]) is not list):
            raise TransferError("file_control_invalid_packet")
        return cls(FileGrantState(value["grant_revision"], value["grant_epoch"], value["send_files"], value["receive_files"],
            tuple(value["manifest_versions"])), value["session_epoch"], value["sequence"], value["echo"])


@dataclass(frozen=True, eq=False)
class NativeLocalFileGrant:
    grants: FileGrantState
    owner: object
    handlers_ready: bool
    policy_ready: bool = True

    def __post_init__(self):
        if (type(self.grants) is not FileGrantState or self.owner is None or type(self.handlers_ready) is not bool or type(self.policy_ready) is not bool
                or not self.handlers_ready and (self.grants.send_files or self.grants.receive_files)):
            raise TransferError("file_control_native_local_state_required")


@dataclass(frozen=True, eq=False)
class NativeFilePeer:
    peer_id: str
    identity_sha256: str
    owner: object
    ready: bool
    paired: bool
    own_device: bool
    remote_own_device: bool
    control_supported: bool
    pairing_epoch: str | None = None

    def __post_init__(self):
        if (type(self.peer_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{16,160}", self.peer_id) is None
                or not _hex(self.identity_sha256) or self.owner is None
                or any(type(value) is not bool for value in (self.ready, self.paired, self.own_device,
                    self.remote_own_device, self.control_supported))
                or self.pairing_epoch is not None and not _hex(self.pairing_epoch)):
            raise TransferError("file_control_native_peer_required")

    @property
    def allowed(self):
        return self.ready and self.paired and self.own_device and self.remote_own_device and self.control_supported


class NativeReceiverCommandTicket:
    """Exact in-process receiver command attempt, never a wire permission."""


@dataclass
class _ReceiverCommandScope:
    local_permission: dict
    remote_session: str
    remote_sequence: int
    issued: int
    expires: int
    last_checked: int
    invalidated: bool = False


class NativeFileControlSession:
    def __init__(self, identity, current_peer, current_local, *, monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if (type(identity) is not NativeJobCatalogIdentity or not callable(current_peer) or not callable(current_local)
                or not callable(monotonic_ms)):
            raise TransferError("file_control_native_scope_required")
        peer, local = current_peer(), current_local()
        if (type(peer) is not NativeFilePeer or not peer.allowed or peer.peer_id == identity.receiver_id
                or type(local) is not NativeLocalFileGrant):
            raise TransferError("file_control_native_scope_required")
        self._identity, self._peer, self._local = identity, peer, local
        self._current_peer, self._current_local = current_peer, current_local
        self._session_epoch = secrets.token_hex(32)
        self._sequence = 0
        self._remote = None
        self._pending_packet = None
        self._sent_grants = None
        self._sent_echo = None
        self._faulted = False
        self._gate = threading.RLock()
        self._monotonic_ms = monotonic_ms
        self._receiver_commands = {}

    def _scope(self):
        peer, local = self._current_peer(), self._current_local()
        if (type(peer) is NativeFilePeer and (peer.owner is not self._peer.owner or peer.peer_id != self._peer.peer_id
                or peer.identity_sha256 != self._peer.identity_sha256 or peer.pairing_epoch != self._peer.pairing_epoch)
                or type(local) is NativeLocalFileGrant and local.owner is not self._local.owner):
            self._faulted = True
        if (self._faulted or type(peer) is not NativeFilePeer or not peer.allowed or peer.owner is not self._peer.owner
                or peer.peer_id != self._peer.peer_id or peer.identity_sha256 != self._peer.identity_sha256 or peer.pairing_epoch != self._peer.pairing_epoch
                or type(local) is not NativeLocalFileGrant or local.owner is not self._local.owner):
            return None
        if (local.grants.revision < self._local.grants.revision
                or local.grants.revision == self._local.grants.revision
                    and local.grants.permission_wire() != self._local.grants.permission_wire()):
            self._faulted = True
            return None
        self._local = local
        return peer, local

    def packet(self):
        with self._gate:
            scope = self._scope()
            if scope is None or self._sequence >= MAX_REVISION:
                raise TransferError("file_control_native_scope_changed")
            if not scope[1].policy_ready:
                raise TransferError("file_control_policy_pending")
            self._sequence += 1
            result = FileControlPacket(scope[1].grants, self._session_epoch, self._sequence,
                self._remote.challenge if self._remote is not None else None)
            self._pending_packet = result
            return result

    def mark_sent(self, packet):
        """Exact native ticket AFTER actual guarded secure-channel send.
        A decoded/copied packet or a merely constructed message cannot grant I/O.
        """
        with self._gate:
            scope = self._scope()
            if (scope is None or not scope[1].policy_ready or type(packet) is not FileControlPacket or packet is not self._pending_packet or packet.grants != scope[1].grants
                    or packet.echo != (self._remote.challenge if self._remote is not None else None)):
                raise TransferError("file_control_invalid_native_send_completion")
            self._sent_grants, self._sent_echo = packet.grants, packet.echo
            self._pending_packet = None

    @property
    def needs_packet(self):
        with self._gate:
            scope = self._scope()
            return scope is not None and scope[1].policy_ready and (self._sent_grants != scope[1].grants
                or self._remote is not None and self._sent_echo != self._remote.challenge)

    def observe_remote(self, packet, bound_peer):
        with self._gate:
            scope = self._scope()
            if (scope is None or type(bound_peer) is not NativeFilePeer or not bound_peer.allowed or bound_peer.owner is not self._peer.owner
                    or bound_peer.peer_id != self._peer.peer_id or bound_peer.identity_sha256 != self._peer.identity_sha256
                    or bound_peer.pairing_epoch != self._peer.pairing_epoch):
                raise TransferError("file_control_native_scope_changed")
            if type(packet) is not FileControlPacket:
                raise TransferError("file_control_invalid_packet")
            previous = self._remote
            if previous is not None:
                same_session = packet.session_epoch == previous.session_epoch
                if same_session and packet.sequence < previous.sequence or packet.grants.revision < previous.grants.revision:
                    raise TransferError("file_control_stale_packet")
                if (same_session and packet.sequence == previous.sequence and packet != previous
                        or packet.grants.revision == previous.grants.revision
                            and packet.grants.permission_wire() != previous.grants.permission_wire()):
                    self._faulted = True
                    raise TransferError("file_control_equivocation")
                if same_session and packet == previous:
                    return False
                if not same_session:
                    for held in self._receiver_commands.values():
                        held.invalidated = True
            self._remote = packet
            return True

    def _agreed(self):
        scope = self._scope()
        if scope is None:
            return None
        peer, local = scope
        remote = self._remote
        local_challenge = FileControlPacket(local.grants, self._session_epoch, 1, None).challenge
        if (not local.handlers_ready or not local.policy_ready or remote is None or remote.echo != local_challenge
                or self._sent_grants != local.grants or self._sent_echo != remote.challenge
                or 1 not in local.grants.manifest_versions or 1 not in remote.grants.manifest_versions):
            return None
        return peer, local, remote

    def receiver_command_ticket(self):
        """Bootstrap a source metadata/configuration command from the receiver.
        Own native receive consent and completed bilateral control echo are needed;
        remote send may still be OFF. No source READ/scan/data grant is implied.
        """
        with self._gate:
            agreed = self._agreed()
            if agreed is None or not agreed[1].grants.receive_files or self._receiver_commands:
                raise TransferError('file_control_receiver_command_not_ready')
            at = self._monotonic_ms()
            if type(at) is not int or not 0 <= at <= 2**63-1-MAX_TTL_MS:
                raise TransferError('file_control_receiver_command_clock')
            ticket = NativeReceiverCommandTicket()
            self._receiver_commands[ticket] = _ReceiverCommandScope(agreed[1].grants.permission_wire(),
                agreed[2].session_epoch, agreed[2].sequence, at, at+MAX_TTL_MS, at)
            return ticket

    def receiver_command_witness(self, ticket):
        """Captured native control position, not authority or completion."""
        with self._gate:
            if type(ticket) is not NativeReceiverCommandTicket or ticket not in self._receiver_commands:
                raise TransferError('file_control_foreign_receiver_command_ticket')
            held = self._receiver_commands[ticket]
            return held.remote_session, held.remote_sequence

    def remote_control_witness(self):
        with self._gate:
            if self._scope() is None or self._remote is None:
                return None
            return self._remote.session_epoch, self._remote.sequence

    def receiver_command_current(self, ticket):
        with self._gate:
            if type(ticket) is not NativeReceiverCommandTicket:
                return False
            held = self._receiver_commands.get(ticket)
            if held is None or held.invalidated:
                return False
            try:
                scope = self._scope()
                remote = self._remote
                at = self._monotonic_ms()
                if (scope is None or remote is None or type(at) is not int or at < held.last_checked or at >= held.expires
                        or not scope[1].handlers_ready or not scope[1].policy_ready or not scope[1].grants.receive_files
                        or scope[1].grants.permission_wire() != held.local_permission
                        or remote.session_epoch != held.remote_session
                        or 1 not in scope[1].grants.manifest_versions or 1 not in remote.grants.manifest_versions):
                    held.invalidated = True
                    return False
                held.last_checked = at
                # The source may change its own send policy during this exact
                # command. Do not mistake that intended update for local receive
                # consent, and do not require a new data echo to read its result.
                return True
            except Exception:
                held.invalidated = True
                raise

    def finish_receiver_command(self, ticket):
        with self._gate:
            if type(ticket) is not NativeReceiverCommandTicket or ticket not in self._receiver_commands:
                raise TransferError('file_control_foreign_receiver_command_ticket')
            del self._receiver_commands[ticket]

    def binding(self, destination_token, *, sender_is_local=False):
        with self._gate:
            agreed = self._agreed()
            if agreed is None or type(sender_is_local) is not bool:
                return None
            peer, local, remote = agreed
            sender = (self._identity.receiver_id, self._identity.receiver_identity_sha256) if sender_is_local else (peer.peer_id, peer.identity_sha256)
            receiver = (peer.peer_id, peer.identity_sha256) if sender_is_local else (self._identity.receiver_id, self._identity.receiver_identity_sha256)
            if not ((local.grants.send_files and remote.grants.receive_files) if sender_is_local
                    else (remote.grants.send_files and local.grants.receive_files)):
                return None
            # Persistent native grant state, not ephemeral channel/session
            # nonces: a fresh handshake can resume the same accepted binding.
            entries = sorted([(self._identity.receiver_id, self._identity.receiver_identity_sha256, local.grants.permission_wire()),
                (peer.peer_id, peer.identity_sha256, remote.grants.permission_wire())], key=lambda value: value[0])
            epoch = sha256(b"magnolie-file-permission-v1\0" + _canonical(entries)).hexdigest()
            return NativeTransferBinding(sender[0], receiver[0], sender[1], receiver[1], epoch, destination_token)

    def close(self):
        with self._gate:
            self._faulted = True
            for held in self._receiver_commands.values():
                held.invalidated = True
            self._remote = None
            self._pending_packet = None
