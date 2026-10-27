"""Native saved-claim/scope correlation for queued deletion-decision ACKs.

Providers must be native source/scope/writer observations. This module neither
authorizes a caller, sends a packet nor mutates a document. Native controllers
record a control here only after protected metadata persistence succeeds.
"""
import copy
import re

import magnolie_personal_actor as actor
import magnolie_content_scope as scope
import magnolie_personal_sync as personal

HEX = re.compile(r"^[0-9a-f]{64}$")


class DecisionAckCompletion:
    def __init__(self, run_id, native_targets, queued_decisions, *, current_authority, current_scope, current_saved_book, persisted_controls):
        actor.start(run_id)
        if not all(callable(value) for value in (current_authority, current_scope, current_saved_book, persisted_controls)):
            raise TypeError("Native completion observations are required")
        self.run_id = run_id
        self.current_authority = current_authority
        self.current_scope = current_scope
        self.current_saved_book = current_saved_book
        self.persisted_controls = persisted_controls
        self.before = copy.deepcopy(current_scope())
        scope.validate(self.before)
        self.authority = current_authority()
        if not isinstance(self.authority, str) or not HEX.fullmatch(self.authority):
            raise PermissionError("actor_completion_not_ready")
        self.saved_book = self._checked_saved_book(current_saved_book())
        if not isinstance(queued_decisions, list) or not 1 <= len(queued_decisions) <= 256:
            raise ValueError("invalid_actor_completion_controls")
        self.controls = {}
        decisions = []
        for wire in queued_decisions:
            if not isinstance(wire, dict) or wire.get("kind") != actor.DATA_KIND:
                raise ValueError("invalid_actor_completion_controls")
            actor.start(wire.get("message_id"))
            kind, body = actor.unwrap(wire.get("body"))
            if (kind != "personal_sync.deletion_decision" or body["run_id"] != run_id or wire["message_id"] in self.controls):
                raise ValueError("invalid_actor_completion_controls")
            self.controls[wire["message_id"]] = copy.deepcopy(body)
            decisions.extend(body["decisions"])
        self.targets = copy.deepcopy(native_targets)
        self.decisions = copy.deepcopy(decisions)
        self.members = actor.completion_members(run_id, self.before, self.targets, self.decisions)
        self.received = {}
        # Stable native callback identity: it cannot be replaced on retry.
        self.validator = self.validate

    @staticmethod
    def _checked_saved_book(value):
        if (not isinstance(value, dict) or set(value) != {"book_source", "sequence", "sha256"} or
                type(value["sequence"]) is not int or value["sequence"] <= 0 or
                any(not isinstance(value[name], str) or not HEX.fullmatch(value[name]) for name in ("book_source", "sha256"))):
            raise PermissionError("native_book_not_saved")
        return copy.deepcopy(value)

    def _ack(self, wire):
        if not isinstance(wire, dict) or wire.get("kind") != actor.ACK_KIND:
            raise ValueError("unexpected_actor_completion_control")
        body = wire.get("body")
        actor.validate_ack(body)
        if body["run_id"] != self.run_id or body["message_id"] not in self.controls:
            raise ValueError("unexpected_actor_completion_control")
        previous = self.received.get(body["message_id"])
        if previous is not None and previous["status"] in ("accepted", "duplicate") and body["status"] == "rejected":
            raise ValueError("actor_completion_outcome_changed")
        return body

    def validate(self, operation, wire):
        body = self._ack(wire) if wire is not None else None
        try:
            if self._checked_saved_book(self.current_saved_book()) != self.saved_book:
                return False
        except PermissionError:
            return False
        authority = self.current_authority()
        if authority is None:
            return None
        if authority != self.authority:
            return False
        try:
            actual = self.current_scope()
            scope.validate(actual)
        except PermissionError:
            return None
        except (ValueError, TypeError):
            return False
        at_before = scope.reference(actual) == scope.reference(self.before)
        try:
            actor.require_completion_scope(self.run_id, self.before, self.targets, self.decisions, actual)
            at_after = True
        except ValueError:
            at_after = False
        if not at_before and not at_after:
            return False
        if body is not None and body["status"] in ("accepted", "duplicate") and not at_after:
            return None  # A success before fresh resulting membership is not evidence.
        if operation == "finish":
            if not at_after or set(self.received) != set(self.controls) or any(
                    value["status"] not in ("accepted", "duplicate") for value in self.received.values()):
                return None
        return True

    def record_persisted(self, wire):
        """Call only after the owner's protected metadata store committed it."""
        if self.validate("put", wire) is not True:
            raise PermissionError("actor_completion_not_ready")
        rows = self.persisted_controls()
        if not isinstance(rows, list) or not any(personal.canonical(value) == personal.canonical(wire) for value in rows):
            raise PermissionError("actor_completion_control_not_persisted")
        body = self._ack(wire)
        self.received[body["message_id"]] = copy.deepcopy(body)

    def summary(self):
        return {"expected":len(self.controls), "received":len(self.received),
            "saved":sum(value["status"] in ("accepted", "duplicate") for value in self.received.values()),
            "rejected":sum(value["status"] == "rejected" for value in self.received.values())}
