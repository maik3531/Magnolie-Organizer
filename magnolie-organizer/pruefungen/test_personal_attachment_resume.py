"""Issue #81: manifest replay preserves the authenticated transfer lifetime."""
import hashlib
import io
from pathlib import Path
import sqlite3
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone


def test_manifest_reregistration_preserves_original_expiry_and_completion(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Synthetic")
    peer, run = str(uuid.uuid4()), str(uuid.uuid4())
    raw = b"%PDF-1.4\n"
    digest = hashlib.sha256(raw).hexdigest()
    aggregate = "a" * 64
    expiry = phone.now_ms() + 60_000
    args = (peer, run, True, aggregate, digest, len(raw), "application/pdf", "any")
    store.register_incoming_attachment(*args, expiry, "attachment")
    store.register_incoming_attachment(*args, expiry + 100, "attachment")
    store.stage_incoming_attachment(peer, run, True, aggregate, digest, len(raw), "application/pdf",
                                    0, raw, "any", expiry + 200, "attachment")
    assert store.verify_incoming_attachment(peer, run, True, aggregate, digest, io.BytesIO())
    store.register_incoming_attachment(*args, expiry + 300, "attachment")
    store.stage_incoming_attachment(peer, run, True, aggregate, digest, len(raw), "application/pdf",
                                    0, raw, "any", expiry + 400, "attachment")
    with sqlite3.connect(store.database_path) as db:
        metadata = store._load_attachment_metadata(db, peer, run, True, aggregate, digest, "incoming")
        assert metadata["expires_ms"] == expiry and metadata["complete"] is True
    with pytest.raises(ValueError):
        store.register_incoming_attachment(peer, run, True, aggregate, digest, len(raw) + 1,
                                            "application/pdf", "any", expiry, "attachment")
    with pytest.raises(ValueError):
        store.register_incoming_attachment(peer, run, True, aggregate, digest, len(raw),
                                            "image/png", "any", expiry, "attachment")
    with pytest.raises(ValueError):
        store.register_incoming_attachment(*args, expiry, "different-attachment")
    with pytest.raises(ValueError):
        store.stage_incoming_attachment(peer, run, True, aggregate, digest, len(raw), "application/pdf",
                                        0, b"%PDF-2.0\n", "any", expiry, "attachment")
