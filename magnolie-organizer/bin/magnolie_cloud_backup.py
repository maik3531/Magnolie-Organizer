#!/usr/bin/env python3
"""Policy, Secret Service storage, and safe retention for automatic backups."""

import os
import re
from datetime import datetime, timedelta, timezone


PREFIX = "magnolie-auto-"
SUFFIX = ".magnolie"
LIST_LIMIT = 1000
ACCOUNT = "automatic-cloud-backup-v1"
OWNED_NAME = re.compile(
    r"^magnolie-auto-\d{8}-\d{6}-\d{6}-[0-9a-f]{32}\.magnolie$")


def utc_time(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc)


def due(enabled, interval, last_success, now=None):
    if not enabled or interval not in ("daily", "weekly"):
        return False
    try:
        last = utc_time(last_success)
    except (TypeError, ValueError):
        return True
    age = timedelta(days=1 if interval == "daily" else 7)
    return utc_time(now) >= last + age


def retention_count(value):
    try:
        return max(2, min(30, int(value)))
    except (TypeError, ValueError):
        return 7


def owned_regular_files(directory):
    entries = []
    with os.scandir(directory) as listing:
        for index, entry in enumerate(listing):
            if index >= LIST_LIMIT:
                raise OSError("The backup folder contains too many entries.")
            if not OWNED_NAME.fullmatch(entry.name) or entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                entries.append((entry.stat(follow_symlinks=False).st_mtime_ns,
                                entry.name, entry.path))
    entries.sort()
    return entries


def apply_retention(directory, keep, verified_path):
    """Delete only owned regular files after protecting the new verified file."""
    verified = os.path.abspath(verified_path)
    files = owned_regular_files(directory)
    if verified not in [os.path.abspath(item[2]) for item in files]:
        raise OSError("The verified backup is not an owned regular file.")
    excess = max(0, len(files) - retention_count(keep))
    deleted = []
    for _, _, path in files:
        if excess <= 0:
            break
        if os.path.abspath(path) == verified:
            continue
        current = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        os.unlink(path)
        deleted.append(path)
        excess -= 1
    return deleted


class ArchiveSecretStore:
    """Archive password exclusively in a dedicated Secret Service schema."""

    SCHEMA_NAME = "io.gitlab.maik3531.MagnolieOrganizer.AutomaticBackup"

    def __init__(self, backend=None):
        self.backend = backend

    def _secret(self):
        if self.backend is not None:
            return self.backend
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
            schema = Secret.Schema.new(self.SCHEMA_NAME, Secret.SchemaFlags.NONE,
                                       {"account": Secret.SchemaAttributeType.STRING})
            return Secret, schema
        except Exception as error:
            raise RuntimeError("secret_service_unavailable") from error

    def store(self, password):
        if not isinstance(password, str) or not 4 <= len(password) <= 4096:
            raise ValueError("invalid_password")
        backend = self._secret()
        try:
            if hasattr(backend, "store"):
                result = backend.store(ACCOUNT, password)
            else:
                Secret, schema = backend
                result = Secret.password_store_sync(
                    schema, {"account": ACCOUNT}, Secret.COLLECTION_DEFAULT,
                    "Magnolie Organizer automatic backup", password, None)
            if result is False:
                raise RuntimeError("secret_store_failed")
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError("secret_store_failed") from error

    def lookup(self):
        backend = self._secret()
        try:
            if hasattr(backend, "lookup"):
                value = backend.lookup(ACCOUNT)
            else:
                Secret, schema = backend
                value = Secret.password_lookup_sync(
                    schema, {"account": ACCOUNT}, None)
        except Exception as error:
            raise RuntimeError("secret_service_unavailable") from error
        return value if isinstance(value, str) and 4 <= len(value) <= 4096 else None

    def available(self):
        try:
            return bool(self.lookup())
        except RuntimeError:
            return False
