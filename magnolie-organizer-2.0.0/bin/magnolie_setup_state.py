#!/usr/bin/env python3
"""Standard-library-only state for Magnolie's first-run setup."""

import json
import os
import tempfile
from datetime import datetime, timezone


PROGRAM_NAME = "magnolie-organizer"
MARKER_NAME = "setup-state.json"
SCHEMA_VERSION = 1
READY_STATES = frozenset(("complete", "adopted", "skipped"))


def config_directory():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, PROGRAM_NAME)


def marker_path():
    return os.path.join(config_directory(), MARKER_NAME)


def evidence_paths():
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return (
        os.path.join(data, PROGRAM_NAME),
        config_directory(),
    )


def _has_evidence(path, marker):
    if os.path.isfile(path) or os.path.islink(path):
        return os.path.abspath(path) != os.path.abspath(marker)
    if not os.path.lexists(path):
        return False
    try:
        entries = os.listdir(path)
    except OSError:
        return True
    return any(os.path.abspath(os.path.join(path, name)) != os.path.abspath(marker)
               for name in entries)


def _read_marker(path):
    try:
        if os.path.getsize(path) > 256 * 1024:
            return None
        with open(path, "r", encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA_VERSION:
        return None
    if value.get("status") not in READY_STATES | {"pending"}:
        return None
    return value


def classify(path=None, evidence=None):
    """Return fresh, pending, ready, or damaged without modifying storage."""
    path = path or marker_path()
    if os.path.lexists(path):
        marker = _read_marker(path)
        if marker is None:
            return "damaged"
        return "ready" if marker["status"] in READY_STATES else "pending"
    candidates = tuple(evidence if evidence is not None else evidence_paths())
    return "existing" if any(_has_evidence(item, path) for item in candidates) else "fresh"


def _atomic_json(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".setup-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            descriptor = -1
            json.dump(value, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_state(status, selections=None, path=None):
    if status not in READY_STATES | {"pending"}:
        raise ValueError("invalid setup status")
    value = {
        "schema": SCHEMA_VERSION,
        "status": status,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if selections is not None:
        encoded = json.dumps(selections, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 128 * 1024:
            raise ValueError("setup selections are too large")
        value["selections"] = json.loads(encoded)
    _atomic_json(path or marker_path(), value)
    return value


def classify_and_adopt(path=None, evidence=None):
    state = classify(path, evidence)
    if state == "existing":
        try:
            write_state("adopted", {"reason": "pre-existing-local-state"}, path)
        except OSError:
            return "damaged"
        return "ready"
    return state


def services_allowed(state=None):
    return (state if state is not None else classify()) in {"ready", "existing"}


def assistant_required(state):
    """Return whether a normal foreground start must run setup."""
    return state in {"fresh", "pending", "damaged"}
