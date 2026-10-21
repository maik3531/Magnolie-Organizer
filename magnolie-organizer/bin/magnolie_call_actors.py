"""Private bounded owners for the product's existing native call commands."""
import copy
import hmac
import re
import secrets
import sqlite3
import threading
import time
from uuid import uuid4


class CallActorError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _CallScope:
    def __init__(self, registry, actor):
        self.registry, self.actor = registry, actor

    def before(self):
        self.registry.guard(self.actor, full=True)

    def receipt_written(self):
        self.actor["receipt_persisted"] = True


class NativeCallActors:
    ACTIVE = {"reserved", "dispatching", "awaiting_phone"}
    KINDS = {"dial": "dial_request.command", "answer": "answer_call.command", "end": "end_call.command"}

    def __init__(self, service):
        self.service = service
        self.actors, self.references = {}, {}

    def fail(self, actor, code):
        if actor["phase"] not in ("cancelled", "reported"):
            actor["phase"], actor["error"] = "failed", code

    def reap(self):
        now = time.monotonic()
        for identity, actor in list(self.actors.items()):
            if actor["phase"] in self.ACTIVE and actor["deadline"] <= now:
                self.fail(actor, "native_timeout_after_dispatch" if actor["dispatch_started"] else "native_timeout")
            if actor["retain_until"] <= now and not actor["worker_active"]:
                self.actors.pop(identity)
                if self.references.get(actor["operation_id"]) is actor:
                    self.references.pop(actor["operation_id"])

    def get(self, request):
        actor = self.actors.get(request.get("actorId"))
        token = request.get("ownerToken")
        if (not actor or not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token) or
                not hmac.compare_digest(token, actor["owner_token"]) or request.get("peerId") != actor["peer_id"] or
                str(request.get("fingerprint", "")).upper() != actor["fingerprint"].upper()):
            raise CallActorError("not_found")
        return actor

    def guard(self, actor, full=False):
        if actor["phase"] not in self.ACTIVE or actor["cancel_requested"]:
            raise CallActorError("cancelled")
        if time.monotonic() >= actor["deadline"]:
            raise CallActorError("native_timeout_after_dispatch" if actor["dispatch_started"] else "native_timeout")
        try:
            authority, _, _, channel = self.service._call_context_source(actor["peer_id"], actor["fingerprint"])
        except (PermissionError, ValueError, KeyError):
            raise CallActorError("source_changed") from None
        current, expected = copy.deepcopy(authority), copy.deepcopy(actor["authority"])
        if not full:
            current.pop("call", None); expected.pop("call", None)
        if channel is not actor["channel"] or current != expected:
            raise CallActorError("source_changed")

    def summary(self, actor):
        return {"actor_id": actor["actor_id"], "operation_id": actor["operation_id"], "command": actor["command"],
            "phase": actor["phase"], "dispatch_started": actor["dispatch_started"], "transport_dispatched": actor["transport_dispatched"],
            "receipt_persisted": actor["receipt_persisted"], "phone_result_received": actor["result"] is not None,
            "phone_result": copy.deepcopy(actor["result"]), "cancel_requested": actor["cancel_requested"],
            "remote_recall_confirmed": False, "native_outcome_unknown": actor["dispatch_started"] and actor["result"] is None and actor["phase"] in ("failed", "cancelled"),
            "error_code": actor["error"]}

    def action(self, request):
        try:
            with self.service.lock:
                self.reap()
                action = request.get("action")
                if action == "call_actor_create":
                    expected = {"action", "peerId", "fingerprint", "sourceRevision", "operationId", "command", "destination", "callRef", "callRevision"}
                    if set(request) != expected:
                        raise ValueError("invalid_call_actor_fields")
                    authority, permissions, observed, channel = self.service._call_context_source(request["peerId"], request["fingerprint"])
                    source = request["sourceRevision"]
                    if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{64}", source):
                        raise ValueError("invalid_call_source_revision")
                    if not hmac.compare_digest(source, self.service._call_source_revision(authority)):
                        raise CallActorError("source_changed")
                    command = request["command"]
                    if command not in self.KINDS:
                        raise ValueError("invalid_call_command")
                    permission = {"dial": "dial_request", "answer": "answer_call", "end": "end_call"}[command]
                    if not permissions[permission]:
                        raise CallActorError("not_granted")
                    body = self.service._call_actor_body(request, observed)
                    reference = request["operationId"]
                    if reference in self.references or self.service.store.command_state(reference):
                        raise CallActorError("conflict")
                    if len(self.actors) >= 128 or sum(value["phase"] in self.ACTIVE or value["worker_active"] for value in self.actors.values()) >= 4:
                        raise CallActorError("native_busy")
                    identity = str(uuid4()); now = time.monotonic()
                    actor = dict(actor_id=identity, owner_token=secrets.token_hex(32), peer_id=request["peerId"], fingerprint=request["fingerprint"],
                        operation_id=reference, command=command, body=copy.deepcopy(body), authority=copy.deepcopy(authority), channel=channel,
                        phase="reserved", deadline=now + 15, retain_until=now + 1800, dispatch_started=False, transport_dispatched=False,
                        receipt_persisted=False, result=None, cancel_requested=False, worker_active=False, error="none")
                    self.actors[identity] = actor; self.references[reference] = actor
                    return {"ok": True, "callActorHandle": {"actor_id": identity, "owner_token": actor["owner_token"]}, "callActor": self.summary(actor)}
                if action not in ("call_actor_start", "call_actor_status", "call_actor_cancel") or set(request) != {"action", "peerId", "fingerprint", "actorId", "ownerToken"}:
                    raise ValueError("invalid_call_actor_action")
                actor = self.get(request)
                if action == "call_actor_cancel":
                    if actor["phase"] in self.ACTIVE:
                        actor["phase"], actor["cancel_requested"], actor["error"] = "cancelled", True, "cancelled"
                elif action == "call_actor_start":
                    self.guard(actor, full=True)
                    if actor["phase"] != "reserved":
                        raise CallActorError("conflict")
                    actor["phase"], actor["deadline"], actor["worker_active"] = "dispatching", time.monotonic() + 15, True
                    thread = threading.Thread(target=self.run, args=(actor,), name="magnolie-private-call", daemon=True)
                    try:
                        thread.start()
                    except RuntimeError:
                        actor["worker_active"] = False; self.fail(actor, "native_operation_failed")
                        raise
                elif actor["phase"] in self.ACTIVE:
                    try: self.guard(actor)
                    except CallActorError as error: self.fail(actor, error.code)
                return {"ok": True, "callActor": self.summary(actor)}
        except CallActorError as error:
            return {"ok": False, "code": error.code}
        except PermissionError:
            return {"ok": False, "code": "not_granted"}
        except (ValueError, TypeError, KeyError):
            return {"ok": False, "code": "invalid_selection"}

    def run(self, actor):
        try:
            scope = _CallScope(self, actor); body = actor["body"]
            if actor["command"] == "dial":
                self.service.request_dial(actor["peer_id"], body["to"], actor["operation_id"], origin="mcp", _scope=scope)
            elif actor["command"] == "answer":
                self.service.request_answer(actor["peer_id"], body["call_ref"], actor["operation_id"], origin="mcp", _scope=scope)
            else:
                self.service.request_end_call(actor["peer_id"], body["call_ref"], body["expected_revision"], actor["operation_id"], origin="mcp", _scope=scope)
            with self.service.lock:
                if actor["phase"] == "dispatching": self.fail(actor, "source_changed")
        except CallActorError as error:
            with self.service.lock: self.fail(actor, error.code)
        except (OSError, RuntimeError, ValueError, KeyError, sqlite3.Error):
            with self.service.lock: self.fail(actor, "native_operation_failed_after_dispatch" if actor["dispatch_started"] else "native_operation_failed")
        finally:
            with self.service.lock: actor["worker_active"] = False

    def send(self, channel, peer_id, message):
        body = message.get("body", {}); reference = body.get("client_ref") or body.get("command_ref")
        with self.service.lock:
            self.reap(); actor = self.references.get(reference)
            if (not actor or actor["phase"] != "dispatching" or actor["dispatch_started"] or peer_id != actor["peer_id"] or
                    channel is not actor["channel"] or message.get("kind") != self.KINDS[actor["command"]] or body != actor["body"] or
                    self.service.store.command_origin(peer_id, reference) != "mcp"):
                return False
            self.guard(actor, full=True)
            if self.service.store.outbox_policy(peer_id, message.get("message_id", "")) == "invalid":
                return False
            actor["dispatch_started"], actor["phase"], actor["receipt_persisted"] = True, "awaiting_phone", True
        channel.send(message)
        with self.service.lock:
            actor["transport_dispatched"] = True
            self.service.store.mark_attempt(peer_id, message["message_id"])
        return True

    def receive(self, peer_id, key, channel, kind, body):
        reference = body.get("client_ref") or body.get("command_ref")
        with self.service.lock:
            self.reap(); actor = self.references.get(reference)
            if (not actor or actor["phase"] != "awaiting_phone" or not actor["dispatch_started"] or peer_id != actor["peer_id"] or
                    key != actor["authority"]["key"] or channel is not actor["channel"] or
                    kind != self.KINDS[actor["command"]].replace(".command", ".result") or
                    actor["command"] != "dial" and body.get("call_ref") != actor["body"].get("call_ref")):
                return
            try: self.guard(actor)
            except CallActorError as error:
                self.fail(actor, error.code); return
            actor["result"], actor["phase"] = copy.deepcopy(body), "reported"
