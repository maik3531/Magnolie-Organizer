"""Same-account local MCP transport; protocol and operations run in the book.

The abstract Unix socket has no network listener, stale socket file or token file.
Both ends verify SO_PEERCRED. Product results are correlated with unguessable,
ephemeral invocation IDs, independently of client-supplied JSON-RPC IDs.
"""
import hashlib
import json
import os
import secrets
import select
import socket
import struct
import sys
import threading

MAX_FRAME = 1024 * 1024


def address(profile):
    identity = os.path.realpath(os.fspath(profile)).encode("utf-8")
    return "\0magnolie-mcp-%d-%s" % (os.getuid(), hashlib.sha256(identity).hexdigest()[:40])


def same_account(connection):
    _pid, uid, _gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    return uid == os.getuid()


def encode(value):
    frame = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(frame) > MAX_FRAME:
        raise ValueError("MCP response exceeds frame limit")
    return frame


def error(code, message, request_id=None):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def decode(frame):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(_value):
        raise ValueError("Invalid JSON number")
    return json.loads(frame.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant)


def response_identity(message):
    value = message.get("id") if isinstance(message, dict) else None
    if type(value) is float and value.is_integer() and abs(value) <= 9007199254740991:
        value = int(value)
    request_id = value if isinstance(value, str) or type(value) is int and abs(value) <= 9007199254740991 else None
    notification = (isinstance(message, dict) and "id" not in message and message.get("jsonrpc") == "2.0"
                    and isinstance(message.get("method"), str)
                    and ("params" not in message or isinstance(message["params"], dict)))
    return request_id, notification


class LocalServer:
    def __init__(self, profile, send, close_session, timeout=35):
        self.send = send
        self.close_session = close_session
        self.timeout = timeout
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.clients = {}
        self.pending = {}
        self.threads = set()
        self.slots = threading.BoundedSemaphore(8)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.listener.bind(address(profile))
            self.listener.listen(8)
            self.listener.settimeout(0.25)
        except BaseException:
            self.listener.close()
            raise
        self._start(self._accept)

    def _start(self, target, *args):
        def run():
            try:
                target(*args)
            finally:
                with self.lock:
                    self.threads.discard(threading.current_thread())
        thread = threading.Thread(target=run, name="magnolie-mcp", daemon=True)
        with self.lock:
            self.threads.add(thread)
        thread.start()

    def _accept(self):
        while not self.stopped.is_set():
            try:
                connection, _peer = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.lock:
                if self.stopped.is_set() or len(self.clients) >= 8 or not same_account(connection):
                    connection.close()
                    continue
                session = secrets.token_hex(24)
                self.clients[session] = connection
            self._start(self._client, connection, session)

    def reply(self, session, invocation, response):
        """Called only by the existing trusted native/WebView bridge."""
        with self.lock:
            item = self.pending.get(invocation)
            if item is None or item["session"] != session or session not in self.clients or item["event"].is_set():
                return False
            if response is None:
                if not item["notification"]:
                    return False
            else:
                actual_id, _notification = response_identity(response)
                if (item["notification"] or not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
                        or "id" not in response or type(actual_id) is not type(item["request_id"])
                        or response["id"] is not None and actual_id is None
                        or actual_id != item["request_id"]):
                    return False
            # Bound and validate the bridge payload before waking a transport writer.
            if response is not None:
                try:
                    encode(response)
                except (ValueError, TypeError, RecursionError):
                    response = error(-32000, "Product result exceeds transport limit; use a smaller page",
                                     response.get("id") if isinstance(response, dict) else None)
            item["response"] = response
            item["event"].set()
            return True

    def _client(self, connection, session):
        writer_lock = threading.Lock()
        own_invocations = set()
        def write(response):
            if response is None:
                return
            try:
                with writer_lock:
                    connection.sendall(encode(response))
            except (OSError, ValueError):
                pass
        def finish(invocation, item, message):
            try:
                if not item["event"].wait(self.timeout):
                    request_id = message.get("id") if isinstance(message, dict) else None
                    if isinstance(message, dict) and "id" in message:
                        write(error(-32000, "Product response timed out; check current state before retrying", request_id))
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                elif not self.stopped.is_set():
                    write(item.get("response"))
            finally:
                with self.lock:
                    self.pending.pop(invocation, None)
                    own_invocations.discard(invocation)
                self.slots.release()
        try:
            with connection.makefile("rb") as reader:
                while not self.stopped.is_set():
                    frame = reader.readline(MAX_FRAME + 1)
                    if not frame:
                        break
                    if len(frame) > MAX_FRAME or not frame.endswith(b"\n"):
                        write(error(-32600, "MCP frame exceeds limit or is incomplete"))
                        break
                    try:
                        message = decode(frame)
                    except (ValueError, UnicodeError, RecursionError):
                        write(error(-32700, "Parse error"))
                        continue
                    if not self.slots.acquire(blocking=False):
                        if isinstance(message, dict) and "id" in message:
                            write(error(-32000, "Too many pending requests", message.get("id")))
                        continue
                    invocation = secrets.token_hex(24)
                    request_id, notification = response_identity(message)
                    item = {"session": session, "event": threading.Event(), "request_id": request_id, "notification": notification}
                    with self.lock:
                        self.pending[invocation] = item
                        own_invocations.add(invocation)
                    try:
                        # Enqueue in wire order before starting asynchronous waiters.
                        self.send({"session": session, "invocation": invocation, "message": message})
                    except Exception:
                        item["response"] = error(-32000, "Product interface unavailable", message.get("id")) if isinstance(message, dict) and "id" in message else None
                        item["event"].set()
                    self._start(finish, invocation, item, message)
        except OSError:
            pass
        finally:
            with self.lock:
                self.clients.pop(session, None)
                for invocation in list(own_invocations):
                    item = self.pending.get(invocation)
                    if item is not None:
                        item["response"] = None
                        item["event"].set()
            connection.close()
            self.close_session(session)

    def close(self):
        self.stopped.set()
        self.listener.close()
        with self.lock:
            connections = list(self.clients.values())
            for item in self.pending.values():
                item["response"] = None
                item["event"].set()
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self.lock:
            threads = list(self.threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1)


def stdio_main(profile, source=None, target=None):
    source = source or sys.stdin.buffer
    target = target or sys.stdout.buffer
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    output = None
    try:
        connection.connect(address(profile))
        if not same_account(connection):
            return 1
        disconnected = threading.Event()
        def responses():
            try:
                with connection.makefile("rb") as reader:
                    while True:
                        frame = reader.readline(MAX_FRAME + 1)
                        if not frame or len(frame) > MAX_FRAME or not frame.endswith(b"\n"):
                            return
                        target.write(frame)
                        target.flush()
            except (OSError, ValueError):
                return
            finally:
                disconnected.set()
        output = threading.Thread(target=responses, name="magnolie-mcp-stdio", daemon=True)
        output.start()
        try:
            descriptor = source.fileno()
        except (AttributeError, OSError):
            descriptor = None
        if descriptor is None:
            while not disconnected.is_set():
                frame = source.readline(MAX_FRAME + 1)
                if not frame:
                    break
                if len(frame) > MAX_FRAME or not frame.endswith(b"\n"):
                    return 2
                connection.sendall(frame)
        else:
            buffered = bytearray()
            while not disconnected.is_set():
                ready, _write, _error = select.select([descriptor], [], [], 0.25)
                if not ready:
                    continue
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    if buffered:
                        return 2
                    break
                buffered.extend(chunk)
                while b"\n" in buffered:
                    frame, _separator, remainder = buffered.partition(b"\n")
                    buffered = bytearray(remainder)
                    if len(frame) + 1 > MAX_FRAME:
                        return 2
                    connection.sendall(frame + b"\n")
                if len(buffered) >= MAX_FRAME:
                    return 2
            if disconnected.is_set():
                return 1
        connection.shutdown(socket.SHUT_WR)
        output.join(timeout=40)
        return 0 if not output.is_alive() else 1
    except OSError:
        return 1
    finally:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()
        if output is not None:
            output.join(timeout=1)
