"""Bounded, connection-bound staging for one reviewed incoming file list.

KDE aggregate hints are not authorization. Only a sealed list of fully received
files may be offered; accepting it must never admit another announcement.
"""

import os
from hashlib import sha256


class BatchError(ValueError):
    pass


def staged_digest(path, size):
    digest = sha256()
    read = 0
    with open(path, "rb") as source:
        while True:
            part = source.read(65536)
            if not part:
                break
            read += len(part)
            if read > size:
                raise BatchError("staged member changed size")
            digest.update(part)
    if read != size:
        raise BatchError("staged member changed size")
    return digest.hexdigest()


class IncomingFileBatch:
    MAX_FILES = 128
    MAX_BYTES = 400 * 1024 * 1024

    def __init__(self, device_id, connection, count, total, deadline, peer_certificate=None):
        self.device_id = device_id
        self.connection = connection
        self.deadline = deadline
        self.peer_certificate = peer_certificate
        self._count = 0
        self._total = 0
        self._entries = []
        self._sealed = False
        self._closed = False
        self.update(connection, count, total)

    def _require_connection(self, connection):
        if self._closed or self._sealed or connection is not self.connection:
            raise BatchError("batch is closed or belongs to another connection")

    def update(self, connection, count, total):
        self._require_connection(connection)
        if (type(count) is not int or not 1 <= count <= self.MAX_FILES
                or type(total) is not int or not 0 <= total <= self.MAX_BYTES
                or count < self._count or total < self._total):
            raise BatchError("invalid or shrinking batch bounds")
        self._count, self._total = count, total

    @property
    def reserved_bytes(self):
        return self._total

    @property
    def accepting_announcements(self):
        return not self._closed and not self._sealed and len(self._entries) < self._count

    def announce(self, connection, packet_id, name, size, count, total):
        self._require_connection(connection)
        if (type(packet_id) is not int or type(size) is not int or size < 0
                or not isinstance(name, str) or not name or name in (".", "..")
                or "/" in name or "\\" in name
                or any(entry["packet_id"] == packet_id for entry in self._entries)):
            raise BatchError("invalid or repeated batch member")
        self.update(connection, count, total)
        if len(self._entries) >= self._count or sum(e["size"] for e in self._entries) + size > self._total:
            raise BatchError("batch member exceeds advertised bounds")
        self._entries.append({"packet_id": packet_id, "name": name, "size": size,
                              "staged": None})

    def stage(self, connection, packet_id, path):
        self._require_connection(connection)
        entry = next((e for e in self._entries if e["packet_id"] == packet_id), None)
        if entry is None or entry["staged"] is not None:
            raise BatchError("unannounced or already staged batch member")
        if (not isinstance(path, str) or not os.path.isabs(path)
                or os.path.islink(path) or not os.path.isfile(path)
                or os.stat(path).st_size != entry["size"]):
            raise BatchError("staged batch member is missing or has the wrong size")
        digest = staged_digest(path, entry["size"])
        entry.update(staged=path, sha256=digest)
        complete = len(self._entries) == self._count and all(e["staged"] for e in self._entries)
        if complete:
            if sum(e["size"] for e in self._entries) != self._total:
                raise BatchError("complete batch does not match advertised byte total")
            self._sealed = True
        return complete

    def proposal(self):
        if not self._sealed or self._closed:
            raise BatchError("only a complete sealed batch can be reviewed")
        return tuple({"name": e["name"], "size": e["size"]} for e in self._entries)

    def take(self):
        """Hand ownership of exactly the reviewed staged list to one proposal."""
        self.proposal()
        result = tuple(dict(e) for e in self._entries)
        self._closed = True
        self._entries.clear()
        return result

    def discard(self):
        """Remove only staging files owned by this batch, never destination files."""
        self._closed = True
        for entry in self._entries:
            if entry["staged"]:
                try:
                    os.unlink(entry["staged"])
                except FileNotFoundError:
                    pass
        self._entries.clear()
