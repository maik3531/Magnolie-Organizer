"""One set of start vectors shared by the Kotlin, C# and Python contracts."""
import copy
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "magnolie-organizer/bin"))
import magnolie_personal_actor as actor

VECTORS = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-start.json").read_text())["cases"]
DATA_VECTORS = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-data.json").read_text())["cases"]


@pytest.mark.parametrize("case", VECTORS, ids=lambda case: case["name"])
def test_shared_start_vector(case):
    if case["valid"]:
        assert actor.validate_start(case["body"]) == case["body"]
        assert actor.start(case["body"]["run_id"]) == case["body"]
    else:
        with pytest.raises(ValueError):
            actor.validate_start(case["body"])


def test_declared_support_requires_shared_and_actor_markers_for_both_modules_and_peers():
    values = {name: {"available": True, "versions": [9, 12]} for name in ("personal_notes_sync", "personal_tasks_sync")}
    assert actor.supported(values, values)
    for name in values:
        for versions in ([9], [12], [9, 12.0]):
            missing = copy.deepcopy(values); missing[name]["versions"] = versions
            assert not actor.supported(values, missing) and not actor.supported(missing, values)
        unavailable = copy.deepcopy(values); unavailable[name]["available"] = False
        assert not actor.supported(values, unavailable)


@pytest.mark.parametrize("case", DATA_VECTORS, ids=lambda case: case["name"])
def test_shared_actor_data_vector_and_roundtrip(case):
    body = case["body"]
    if not case["valid"]:
        with pytest.raises(ValueError):
            actor.validate_data(body)
        return
    assert actor.validate_data(body) == body
    assert actor.wrap(body["run_id"], body["kind"], body["body"]) == body
    kind, original = actor.unwrap(body)
    assert kind == body["kind"] and original == body["body"]
    original["owned_mutation"] = True
    assert "owned_mutation" not in body["body"]
