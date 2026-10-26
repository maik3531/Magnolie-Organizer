"""Cancellable, bounded PDF worker; no GTK work runs on its background thread."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading


class RenderProcess:
    def __init__(self, markup, web_root, options, complete, runtime_dir=None):
        self._payload = json.dumps({"html": markup, "options": options}, ensure_ascii=False).encode("utf-8")
        if len(self._payload) > 8_000_000:
            raise ValueError("Print request exceeds the size limit")
        self._root = str(Path(web_root).resolve(strict=True))
        self._runtime = Path(runtime_dir) if runtime_dir is not None else Path(__file__).with_name("pdf-runtime")
        self._complete = complete
        self._temporary = tempfile.TemporaryDirectory(prefix="magnolie-print-")
        self.path = Path(self._temporary.name) / "print.pdf"
        self._log = Path(self._temporary.name) / "renderer.log"
        self._worker = None
        self._cancelled = False
        self._delivered = False
        self._thread = None

    def start(self):
        from gi.repository import GLib
        if self._thread is not None or self._worker is not None:
            raise RuntimeError("PDF worker has already started")
        module = Path(__file__).with_name("magnolie_print_pdf.py")
        environment = dict(os.environ)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        paths = [str(module.parent), str(self._runtime)]
        if environment.get("PYTHONPATH"):
            paths.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        try:
            log = open(self._log, "xb")
            try:
                self._worker = subprocess.Popen([sys.executable, "-s", "-B", str(module), self._root,
                    str(self.path), "--runtime", str(self._runtime)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=log, env=environment, start_new_session=True)
            finally:
                log.close()
        except Exception as error:
            GLib.idle_add(self._finish, False, str(error)[:2000])
            return self

        def work():
            try:
                try:
                    output, _ = self._worker.communicate(self._payload, timeout=210)
                except subprocess.TimeoutExpired:
                    self._signal(signal.SIGKILL)
                    self._worker.communicate()
                    raise RuntimeError("The PDF renderer exceeded its time limit")
                if self._cancelled:
                    GLib.idle_add(self._finish, False, "cancelled")
                    return
                if self._worker.returncode != 0:
                    with open(self._log, "rb") as log:
                        detail = log.read(4096).decode("utf-8", "replace")
                    raise RuntimeError(detail[-2000:] or "The PDF renderer failed")
                if len(output) > 4096:
                    raise RuntimeError("Invalid PDF renderer response")
                reply = json.loads(output)
                if reply == {"ok": False, "cancelled": True}:
                    GLib.idle_add(self._finish, False, "cancelled")
                    return
                if reply.get("ok") is not True or type(reply.get("sheets")) is not int or not 1 <= reply["sheets"] <= 2000:
                    raise RuntimeError("Invalid PDF renderer response")
                if self.path.is_symlink() or not self.path.is_file() or not 0 < self.path.stat().st_size <= 64 * 1024 * 1024:
                    raise RuntimeError("The PDF renderer did not create a valid output")
                with open(self.path, "rb") as pdf:
                    if pdf.read(5) != b"%PDF-":
                        raise RuntimeError("The PDF renderer output is not a PDF")
                GLib.idle_add(self._finish, True, reply)
            except Exception as error:
                GLib.idle_add(self._finish, False, str(error)[:2000])

        self._thread = threading.Thread(target=work, name="handbook-pdf-worker", daemon=True)
        self._thread.start()
        return self

    def _finish(self, ok, result):
        if self._delivered:
            return False
        self._delivered = True
        self._payload = b""
        if self._cancelled:
            ok, result = False, "cancelled"
        if not ok:
            self.close()
        self._complete(ok, result)
        return False

    def _signal(self, value):
        if self._worker is not None and self._worker.poll() is None:
            try:
                os.killpg(self._worker.pid, value)
            except ProcessLookupError:
                pass

    def cancel(self):
        from gi.repository import GLib
        # A delivered PDF may already be consumed by GTK. Its owner releases it
        # after native completion; cancellation must not remove it underneath GTK.
        if self._delivered:
            return False
        self._cancelled = True
        self._signal(signal.SIGTERM)
        GLib.timeout_add(2000, lambda: (self._signal(signal.SIGKILL), False)[1])
        return True

    def close(self):
        if self._worker is not None and self._worker.poll() is None:
            raise RuntimeError("A running PDF worker must be cancelled and reaped before cleanup")
        self._temporary.cleanup()

    def shutdown(self):
        """Window/application teardown must not depend on another GLib turn."""
        if self._delivered:
            return
        self._cancelled = True
        self._signal(signal.SIGKILL)
        if self._worker is not None:
            self._worker.wait(timeout=2)
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.close()
