"""Shared native additive-restore identity cases, including issue #823."""
import copy
import json
from pathlib import Path

import pytest

from modul_laden import quellmodul_laden


ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "contracts/restore-additive-identity-vectors.json").read_text(encoding="utf-8"))["cases"]
native = quellmodul_laden("magnolie_restore_identity", ROOT / "magnolie-organizer/bin/magnolie-organizer")


@pytest.mark.parametrize("case", VECTORS, ids=lambda case: case["id"])
def test_additive_restore_identity(case, monkeypatch):
    monkeypatch.setattr(native, "jetzt_ms", lambda: 123456789)
    name = case["collection"]
    current = {name: copy.deepcopy(case["current"])}
    snapshot = {name: copy.deepcopy(case["snapshot"])}
    untouched = copy.deepcopy((current, snapshot))
    if case.get("error") == "ambiguous-local-id":
        with pytest.raises(ValueError):
            native.journal_restore_daten(snapshot, current, [case["area"]], "additive")
        assert (current, snapshot) == untouched
        return
    restored = native.journal_restore_daten(snapshot, current, [case["area"]], "additive")
    assert restored[name] == case["expected"]
    repeated = native.journal_restore_daten(snapshot, restored, [case["area"]], "additive")
    assert repeated[name] == case["expected"]
    assert (current, snapshot) == untouched


@pytest.mark.parametrize("case", VECTORS, ids=lambda case: case["id"])
def test_replace_restore_keeps_snapshot_selection(case, monkeypatch):
    monkeypatch.setattr(native, "jetzt_ms", lambda: 123456789)
    name = case["collection"]
    restored = native.journal_restore_daten(
        {name: case["snapshot"]}, {name: case["current"]}, [case["area"]], "replace")
    expected = copy.deepcopy(case["snapshot"])
    # Full Linux restoration deliberately refreshes live sync timestamps after
    # selection; the C# vectors exercise only the pure selection layer.
    if name in ("termine", "aufgaben", "kontakte"):
        for item in expected:
            if isinstance(item, dict) and item.get("sync"):
                item["geaendert"] = 123456789
    assert restored[name] == expected
