"""Creation provenance is a negotiated, hashed part of record format 14."""
import copy
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))
import magnolie_personal_sync as sync


def value(kind):
    common = {"title": "Synthetic provenance", "created_ms": 1000, "modified_ms": 2000}
    if kind == "note":
        return dict(common, text="Text", html="<p>Text</p>", notebook_id="", symbol="note", attachments=[])
    return dict(common, note="Task", due="", priority=2, completed=False, remind=False,
                lead_days=0, reminder_minute=0, uid="task-uid", parent_uid="", order=0)


@pytest.mark.parametrize("kind", ["note", "task"])
@pytest.mark.parametrize("origin", ["", "notes", "organizer"])
def test_origin_is_explicit_and_covered_by_projection_hash(kind, origin):
    old = value(kind)
    original = dict(old, origin_app=origin)
    sync.validate_value(kind, original, 14)
    assert sync.projection_hash(original) != sync.projection_hash(old)
    for legacy in (1, 2, 3):
        with pytest.raises(ValueError):
            sync.validate_value(kind, original, legacy)
    with pytest.raises(ValueError):
        sync.validate_value(kind, old, 14)
    changed = copy.deepcopy(original)
    changed["origin_app"] = "organizer" if origin != "organizer" else "notes"
    assert sync.projection_hash(original) != sync.projection_hash(changed)


@pytest.mark.parametrize("kind", ["note", "task"])
@pytest.mark.parametrize("invalid", [None, True, 1, "last_sender", "Notes", [], {}])
def test_origin_cannot_encode_a_transport_sender_or_unvalidated_type(kind, invalid):
    with pytest.raises(ValueError):
        sync.validate_value(kind, dict(value(kind), origin_app=invalid), 14)
