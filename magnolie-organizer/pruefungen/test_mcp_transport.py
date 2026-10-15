"""Real same-account socket transport with isolated, explicitly owned fixtures."""
import importlib.util
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import os
import threading

import pytest

SPEC = importlib.util.spec_from_file_location("magnolie_mcp", Path(__file__).parents[1] / "bin/magnolie_mcp.py")
mcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcp)


def connect(profile):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(3)
    client.connect(mcp.address(profile))
    assert mcp.same_account(client)
    return client


def test_real_socket_correlation_parse_failure_and_owned_cleanup(tmp_path):
    incoming, closed = queue.Queue(), queue.Queue()
    server = mcp.LocalServer(tmp_path, incoming.put, closed.put, timeout=2)
    try:
        with connect(tmp_path) as client, client.makefile("rb") as reader:
            client.sendall(b'{"jsonrpc":"2.0","id":1,"method":"fixture/save"}\n')
            request = incoming.get(timeout=2)
            response = {"jsonrpc": "2.0", "id": 1, "result": {"saved": "fixture"}}
            assert not server.reply("wrong-session", request["invocation"], response)
            assert not server.reply(request["session"], "wrong-invocation", response)
            assert not server.reply(request["session"], request["invocation"], dict(response, id=2))
            assert not server.reply(request["session"], request["invocation"], None)
            assert server.reply(request["session"], request["invocation"], response)
            assert not server.reply(request["session"], request["invocation"], response)
            assert json.loads(reader.readline()) == response
            client.sendall(b'{"id":1,"id":2}\n')
            assert json.loads(reader.readline())["error"]["code"] == -32700
            client.sendall(b'{"value":NaN}\n')
            assert json.loads(reader.readline())["error"]["code"] == -32700
            client.sendall(b'not json\n')
            assert json.loads(reader.readline())["error"]["code"] == -32700
        assert closed.get(timeout=2) == request["session"]
        assert not server.reply(request["session"], request["invocation"], response)
    finally:
        server.close()
    assert not server.clients
    assert not server.pending
    assert not server.threads
    # No stale path/token file; a new owned listener can immediately reuse the address.
    replacement = mcp.LocalServer(tmp_path, incoming.put, closed.put)
    replacement.close()


def test_out_of_order_product_results_stay_with_their_requests(tmp_path):
    incoming = queue.Queue()
    server = mcp.LocalServer(tmp_path, incoming.put, lambda _: None, timeout=2)
    try:
        with connect(tmp_path) as client, client.makefile("rb") as reader:
            client.sendall(b'{"jsonrpc":"2.0","id":"a","method":"fixture"}\n'
                           b'{"jsonrpc":"2.0","id":"b","method":"fixture"}\n')
            first, second = incoming.get(timeout=2), incoming.get(timeout=2)
            assert first["message"]["id"] == "a"
            assert second["message"]["id"] == "b"
            for request in (second, first):
                assert server.reply(request["session"], request["invocation"],
                    {"jsonrpc": "2.0", "id": request["message"]["id"], "result": {}})
                assert json.loads(reader.readline())["id"] == request["message"]["id"]
    finally:
        server.close()


def test_timeout_disconnects_and_rejects_late_product_result(tmp_path):
    incoming, closed = queue.Queue(), queue.Queue()
    server = mcp.LocalServer(tmp_path, incoming.put, closed.put, timeout=0.1)
    try:
        with connect(tmp_path) as client, client.makefile("rb") as reader:
            client.sendall(b'{"jsonrpc":"2.0","id":5,"method":"fixture"}\n')
            request = incoming.get(timeout=2)
            assert json.loads(reader.readline())["error"]["code"] == -32000
            assert reader.readline() == b""
            assert closed.get(timeout=2) == request["session"]
            assert not server.reply(request["session"], request["invocation"], {"jsonrpc": "2.0", "id": 5, "result": {}})
    finally:
        server.close()


def test_oversized_request_never_reaches_product(tmp_path):
    incoming = queue.Queue()
    server = mcp.LocalServer(tmp_path, incoming.put, lambda _: None)
    try:
        with connect(tmp_path) as client, client.makefile("rb") as reader:
            client.sendall(b"x" * (mcp.MAX_FRAME + 1) + b"\n")
            assert json.loads(reader.readline())["error"]["code"] == -32600
            assert incoming.empty()
    finally:
        server.close()


def test_same_profile_second_server_cannot_replace_listener(tmp_path):
    server = mcp.LocalServer(tmp_path, lambda _: None, lambda _: None)
    try:
        with pytest.raises(OSError):
            mcp.LocalServer(tmp_path, lambda _: None, lambda _: None)
        assert not server.stopped.is_set()
    finally:
        server.close()


def test_stdio_child_exits_on_product_disconnect_even_with_stdin_open(tmp_path):
    incoming = queue.Queue()
    profile = tmp_path / "magnolie-organizer"
    server = mcp.LocalServer(profile, incoming.put, lambda _: None)
    child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).parents[1] / "bin/magnolie-organizer"), "--mcp-stdio"],
        env=dict(os.environ, XDG_DATA_HOME=str(tmp_path)), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        child.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        child.stdin.flush()
        incoming.get(timeout=3)
        server.close()
        assert child.wait(timeout=3) == 1
        assert not child.stdin.closed
        assert child.stderr.read() == b""
    finally:
        server.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)
        child.stdin.close()
