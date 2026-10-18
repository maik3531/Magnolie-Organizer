"""Explicit note-document handoff to installed mail/HylaFAX adapters (#88).

The caller owns PDF creation, settings persistence and asynchronous job lifetime.
No adapter is invoked by discovery. A successful handoff is never delivery proof.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import secrets
import threading
import time


MAX_PDF_BYTES = 32 * 1024 * 1024


class SendError(Exception):
    def __init__(self, code, dispatched=False):
        super().__init__(code)
        self.code = code
        self.dispatched = dispatched


def fax_server(value):
    value = str(value or "").strip()
    if not value:
        return ""
    match = re.fullmatch(r"([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::([0-9]{1,5}))?", value)
    if not match or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in match[1].split(".")):
        raise SendError("invalid_fax_server")
    if match[2] and not 1 <= int(match[2]) <= 65535:
        raise SendError("invalid_fax_server")
    return match[1].lower() + (":" + str(int(match[2])) if match[2] else "")


def settings(value):
    value = value if isinstance(value, dict) else {}
    return {"enabled": value.get("enabled") is True, "faxServer": fax_server(value.get("faxServer"))}


def recipient(kind, value):
    value = str(value or "").strip()
    if kind == "email":
        if len(value) > 320 or not re.fullmatch(r"[^\s@<>;,\x00-\x1f\x7f]+@[^\s@<>;,\x00-\x1f\x7f]+\.[^\s@<>;,\x00-\x1f\x7f]+", value) or value.startswith("-"):
            raise SendError("invalid_recipient")
        return value
    if kind == "fax":
        if len(value) > 80 or not re.fullmatch(r"\+?[0-9][0-9 ().-]*[0-9]", value):
            raise SendError("invalid_recipient")
        number = re.sub(r"[ ().-]", "", value)
        if not 3 <= sum(character.isdigit() for character in number) <= 30:
            raise SendError("invalid_recipient")
        return number
    raise SendError("unsupported_adapter")


def mail_platform_supported():
    return not os.path.exists("/.flatpak-info")


def registered_mail_client():
    # xdg-email's path attachment cannot cross a Flatpak file namespace. A
    # future portal-FD adapter must be implemented before advertising that route.
    if not mail_platform_supported():
        return None
    try:
        from gi.repository import Gio
        app = Gio.AppInfo.get_default_for_uri_scheme("mailto")
        return {"id": app.get_id() or "", "name": app.get_display_name() or ""} if app else None
    except (ImportError, ValueError, RuntimeError):
        return None


def capabilities(config, which=shutil.which, discover_mail=registered_mail_client):
    config = settings(config)
    mail = discover_mail()
    email_program = which("xdg-email")
    fax_program = which("sendfax")
    mail_supported = mail_platform_supported()
    return {"enabled": config["enabled"],
        "email": {"supported": mail_supported, "available": bool(mail_supported and email_program and mail), "client": str((mail or {}).get("name") or "")},
        "fax": {"supported": True, "available": bool(config["faxServer"] and fax_program), "configured": bool(config["faxServer"])}}


def pdf_receipt(path, owned_directory):
    path, directory = Path(path), Path(owned_directory)
    try:
        directory_info = directory.lstat()
    except OSError as error:
        raise SendError("invalid_document") from error
    if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != os.getuid() or stat.S_IMODE(directory_info.st_mode) & 0o077:
        raise SendError("invalid_document")
    if path.parent.resolve() != directory.resolve():
        raise SendError("invalid_document")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or not 8 <= info.st_size <= MAX_PDF_BYTES or stat.S_IMODE(info.st_mode) & 0o077:
                raise SendError("invalid_document")
            digest = hashlib.sha256()
            first, end, size = source.read(8), b"", 0
            if not first.startswith(b"%PDF-"):
                raise SendError("invalid_document")
            digest.update(first); size += len(first)
            while block := source.read(65536):
                digest.update(block); size += len(block); end = (end + block)[-1024:]
                if size > MAX_PDF_BYTES:
                    raise SendError("invalid_document")
            after = os.fstat(source.fileno())
            if "%%EOF".encode() not in (first + end)[-1024:] or size != info.st_size or (info.st_mtime_ns, info.st_size) != (after.st_mtime_ns, after.st_size):
                raise SendError("invalid_document")
    except OSError as error:
        raise SendError("invalid_document") from error
    return {"bytes": size, "sha256": digest.hexdigest()}


def command(config, kind, target, subject, pdf_path, which=shutil.which, discover_mail=registered_mail_client):
    config = settings(config)
    if not config["enabled"]:
        raise SendError("feature_disabled")
    target = recipient(kind, target)
    subject = str(subject or "").strip()
    if len(subject) > 200 or re.search(r"[\x00-\x1f\x7f]", subject):
        raise SendError("invalid_subject")
    if kind == "email":
        if not mail_platform_supported():
            raise SendError("unsupported_adapter")
        program = which("xdg-email")
        if not program or not discover_mail():
            raise SendError("native_unavailable")
        return [program, "--utf8", "--subject", subject, "--attach", str(Path(pdf_path).absolute()), target]
    program = which("sendfax")
    if not config["faxServer"] or not program:
        raise SendError("native_unavailable")
    return [program, "-h", config["faxServer"], "-n", "-d", target, str(Path(pdf_path).absolute())]


def handoff(config, kind, target, subject, pdf_path, owned_directory, runner=None, which=shutil.which, discover_mail=registered_mail_client):
    receipt = pdf_receipt(pdf_path, owned_directory)
    arguments = command(config, kind, target, subject, pdf_path, which, discover_mail)
    if runner is None:
        def runner(argv):
            return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        result = runner(arguments)
    except (OSError, subprocess.SubprocessError) as error:
        raise SendError("native_operation_failed", dispatched=not isinstance(error, FileNotFoundError)) from error
    if result.returncode != 0:
        raise SendError("native_operation_failed", dispatched=True)
    return {"stage": "handed_off", "adapter": "xdg-email" if kind == "email" else "hylafax-sendfax",
        "accepted": True, "delivery_confirmed": False, "document": receipt}


class SendJobs:
    """Bounded, opaque native operations; the UI/MCP caller owns its job tokens.

    PDF generation is scheduled by the existing GUI renderer. External clients
    may keep a compose dialog open: cancellation after dispatch cannot recall it.
    Completed handoff PDFs stay private for one day for client attachment pickup.
    """
    def __init__(self, spool_root, read_settings, render_pdf, *, which=shutil.which,
                 discover_mail=registered_mail_client, runner=None, clock=time.time):
        self.root = Path(spool_root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SendError("invalid_document")
        self.read_settings, self.render_pdf = read_settings, render_pdf
        self.which, self.discover_mail, self.runner, self.clock = which, discover_mail, runner, clock
        self.lock, self.jobs = threading.RLock(), {}
        self.revision_key = secrets.token_bytes(32)
        self._prune()

    def _context(self):
        config = settings(self.read_settings())
        mail = self.discover_mail()
        programs = {kind: self.which(name) for kind, name in (("email", "xdg-email"), ("fax", "sendfax"))}
        material = {"settings": config, "programs": programs, "mail": mail, "email_supported": mail_platform_supported()}
        revision = hmac.new(self.revision_key, json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        return config, revision, capabilities(config, self.which, lambda: mail)

    def read(self):
        self._prune()
        config, revision, available = self._context()
        return {"settings": config, "revision": revision, "capabilities": available}

    def _prune(self):
        now = self.clock()
        with self.lock:
            for token, job in list(self.jobs.items()):
                if job["finished"] and not job["rendering"] and now - job["finished"] > 86400:
                    self.jobs.pop(token)
            # Only this narrowly named private spool is inspected; active jobs
            # and symlinks are never traversed by the retention cleanup.
            for directory in self.root.iterdir():
                if not re.fullmatch(r"[a-f0-9]{48}", directory.name) or directory.name in self.jobs:
                    continue
                try:
                    info = directory.lstat()
                    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or now - info.st_mtime < 86400:
                        continue
                    marker = directory / "owned.json"
                    if marker.is_symlink() or json.loads(marker.read_text()) != {"version": 1, "owner": "magnolie-note-send"}:
                        continue
                    shutil.rmtree(directory)
                except (OSError, ValueError):
                    continue

    def _job(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{48}", token):
            raise SendError("not_found")
        job = self.jobs.get(token)
        if not job:
            raise SendError("not_found")
        return job

    def _value(self, job):
        return {"operation_id": job["id"], "phase": job["phase"], "error_code": job["error"],
            "native_outcome_unknown": job["unknown"] or job["phase"] == "external_pending", "cancel_requested": job["cancel"],
            "can_cancel": not job["dispatched"] and job["phase"] in ("preparing", "ready"),
            "handed_off": job["phase"] == "handed_off", "delivery_confirmed": False,
            "adapter": job["receipt"].get("adapter") if job["receipt"] else None,
            "document": dict(job["receipt"]["document"]) if job["receipt"] else None}

    def status(self, token):
        self._prune()
        with self.lock:
            return self._value(self._job(token))

    def begin(self, html, kind, target, subject, expected_revision, operation_id=None):
        self._prune()
        config, revision, _available = self._context()
        if revision != expected_revision:
            raise SendError("conflict")
        if not isinstance(html, str) or not html.strip() or len(html.encode("utf-8")) > 750000:
            raise SendError("invalid_document")
        # Validate all adapter/recipient/settings choices before creating a PDF.
        command(config, kind, target, subject, self.root / "pending.pdf", self.which, self.discover_mail)
        request_hash = hashlib.sha256(json.dumps([html, kind, target, subject, expected_revision], ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            token = operation_id or secrets.token_hex(24)
            if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{48}", token):
                raise SendError("invalid_selection")
            if token in self.jobs:
                if self.jobs[token]["request_hash"] != request_hash:
                    raise SendError("conflict")
                return self._value(self.jobs[token])
            if sum(not job["finished"] or job["rendering"] for job in self.jobs.values()) >= 4 or len(self.jobs) >= 32:
                raise SendError("native_busy")
            directory = self.root / token
            directory.mkdir(mode=0o700)
            descriptor = os.open(directory / "owned.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as marker:
                json.dump({"version": 1, "owner": "magnolie-note-send"}, marker)
            job = {"id": token, "request_hash": request_hash, "directory": directory, "pdf": directory / "document.pdf", "revision": revision,
                "kind": kind, "target": recipient(kind, target), "subject": subject, "phase": "preparing", "error": "none",
                "cancel": False, "dispatched": False, "unknown": False, "receipt": None, "finished": 0, "renderer": None, "rendering": True}
            self.jobs[token] = job
        try:
            rendered = self.render_pdf(html, str(job["pdf"]), lambda result: self._pdf_ready(token, result))
            with self.lock:
                job["renderer"] = rendered
            if isinstance(rendered, dict) and rendered.get("ok") is False:
                self._pdf_ready(token, rendered)
        except Exception:
            self._pdf_ready(token, {"ok": False})
        return self.status(token)

    def _pdf_ready(self, token, result):
        with self.lock:
            job = self._job(token)
            job["rendering"], job["renderer"] = False, None
            if job["phase"] != "preparing":
                if job["cancel"] and not job["dispatched"]:
                    shutil.rmtree(job["directory"], ignore_errors=True)
                return
            if job["cancel"] or not isinstance(result, dict) or result.get("ok") is not True:
                job["phase"] = "cancelled" if job["cancel"] else "failed"
                job["error"] = "none" if job["cancel"] else "document_failed"
                job["finished"] = self.clock()
                shutil.rmtree(job["directory"], ignore_errors=True)
                return
            try:
                descriptor = os.open(job["pdf"], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
                pdf_receipt(job["pdf"], job["directory"])
            except (OSError, SendError):
                job["phase"], job["error"], job["finished"] = "failed", "invalid_document", self.clock()
                shutil.rmtree(job["directory"], ignore_errors=True)
                return
            job["phase"] = "ready"
        threading.Thread(target=self._dispatch, args=(token,), name="magnolie-note-send", daemon=True).start()

    def _dispatch(self, token):
        with self.lock:
            job = self._job(token)
            if job["cancel"] or job["finished"]:
                return
        try:
            config, revision, _available = self._context()
            with self.lock:
                if job["cancel"] or job["finished"]:
                    return
                if revision != job["revision"]:
                    raise SendError("conflict")
                job["dispatched"], job["phase"] = True, "external_pending"
            receipt = handoff(config, job["kind"], job["target"], job["subject"], job["pdf"], job["directory"],
                runner=self.runner, which=self.which, discover_mail=self.discover_mail)
            with self.lock:
                job["receipt"], job["phase"] = receipt, "handed_off"
        except SendError as error:
            with self.lock:
                job["dispatched"], job["unknown"], job["phase"], job["error"] = error.dispatched, error.dispatched, "failed", error.code
                if not error.dispatched:
                    shutil.rmtree(job["directory"], ignore_errors=True)
        except Exception:
            with self.lock:
                job["phase"], job["error"], job["unknown"] = "failed", "native_operation_failed", job["dispatched"]
        finally:
            with self.lock:
                if job["phase"] in ("handed_off", "failed", "cancelled"):
                    job["finished"] = self.clock()
                    try:
                        os.utime(job["directory"], (job["finished"], job["finished"]), follow_symlinks=False)
                    except OSError:
                        pass

    def cancel(self, token):
        with self.lock:
            job = self._job(token)
            accepted = not job["dispatched"] and job["phase"] in ("preparing", "ready")
            if accepted:
                previous = job["phase"]
                job["cancel"], job["phase"], job["finished"] = True, "cancelled", self.clock()
                if previous != "preparing":
                    shutil.rmtree(job["directory"], ignore_errors=True)
            return {**self._value(job), "cancel_accepted": accepted}
