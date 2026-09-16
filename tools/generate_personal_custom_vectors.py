#!/usr/bin/env python3
"""Reproducible synthetic vectors, independent of product validators."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def generate():
    consent = json.loads((ROOT / "contracts/personal-custom-consent-v4-vectors.json").read_text())
    source = consent["source_id"]
    recurrence = dict(frequency="monthly", interval=1, until="", dates=[], ordinal=0, weekday=0)
    value = dict(module_id="custom-module-appointments", module_title="Garden", title="Water plants", note="Own item note only",
        date="2028-01-31", time="09:00", timezone="Europe/Berlin", completed=False,
        module_reminders=True, item_reminder=True, lead_minutes=15, default_minute=480, recurrence=recurrence)
    item = "custom-item-1"
    record = dict(id="custom:" + digest(["personal-custom-v1", source, item]), item_id=item,
        kind="appointment", hash=digest(value), value=value)
    body = dict(format=4, source_id=source, revision=1, trigger="manual",
        sender_epoch=consent["remote"]["epoch"], receiver_epoch=consent["local"]["epoch"],
        sender_revision=1, receiver_revision=1, upserts=[record], deletions=[])
    deletion = dict(body, revision=2, upserts=[], deletions=[dict(id=record["id"], item_id=item, prior_hash=record["hash"])])
    result = dict(batch=body, deletion=deletion, canonical=json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        alarms=[dict(after="2028-01-01T00:00:00Z", expected="2028-01-31T07:45:00Z"),
                dict(after="2028-01-31T07:45:00Z", expected="2028-02-29T07:45:00Z"),
                dict(after="2028-02-29T07:45:00Z", expected="2028-03-31T06:45:00Z")])
    (ROOT / "contracts/personal-custom-v4-vectors.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    generate()
