"""Actual launcher dispatch methods, inert RPC target and controlled scheduling."""
import ast
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace


def test_gui_time_snapshots_keep_order_even_when_an_earlier_rpc_fails():
    source = Path(__file__).resolve().parents[1] / "bin/magnolie-organizer"
    window = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    methods = [node for node in window.body if isinstance(node, ast.FunctionDef) and
        node.name in {"_zeit_abgleich_senden_geordnet", "_personal_sync_senden"}]
    scope = dict(threading=threading, queue=queue, _=lambda text: text, fehler_deutsch=lambda error, _: str(error))
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), scope)
    started, release, done = threading.Event(), threading.Event(), threading.Event()
    received, responses = [], []

    def rpc(peer, kind, body, trigger):
        received.append(body["revision"])
        if body["revision"] == 1:
            started.set()
            assert release.wait(3)
            raise OSError("synthetic first RPC failure")
        if body["revision"] == 3:
            done.set()

    gui = SimpleNamespace(_telefon=SimpleNamespace(send_personal_sync=rpc),
        _zeit_abgleich_ausgang=queue.Queue(), _zeit_abgleich_ausgang_sperre=threading.Lock(),
        _zeit_abgleich_ausgang_aktiv=False, antwort=lambda name, value: responses.append((name, value)))
    for name, value in scope.items():
        if name.startswith("_zeit_") or name == "_personal_sync_senden":
            setattr(gui, name, MethodType(value, gui))
    gui._zeit_abgleich_senden_geordnet(("synthetic", "personal_sync.time_batch", {"revision": 1}, "manual"))
    try:
        assert started.wait(3)
        for revision in (2, 3):
            gui._zeit_abgleich_senden_geordnet(("synthetic", "personal_sync.time_batch", {"revision": revision}, "manual"))
        assert received == [1]
    finally:
        release.set()
    assert done.wait(3)
    assert received == [1, 2, 3]
    assert len(responses) == 1 and responses[0][0] == "App.personalSyncFehler"
