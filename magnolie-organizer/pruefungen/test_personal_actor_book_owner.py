"""Native book authority lifetime; no document-tracking or transport side effects."""
import re
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_personal_actor_store import NativeBookOwnerScope


def test_readiness_alone_does_not_replace_actual_native_book_availability():
    owner = NativeBookOwnerScope()
    assert owner.current("profile-a", True) is None
    owner.set_ready(True)
    assert owner.current("profile-a", False) is None
    source = owner.current("profile-a", True)
    assert re.fullmatch(r"[0-9a-f]{64}", source)
    owner.set_ready(True)
    assert owner.current("profile-a", True) == source


def test_lock_regrant_profile_and_restore_changes_never_inherit_a_book_source():
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    first = owner.current("profile-a", True)
    owner.set_ready(False); owner.set_ready(True)
    unlocked = owner.current("profile-a", True)
    assert unlocked and unlocked != first
    other = owner.current("profile-b", True)
    assert other and other != unlocked
    owner.invalidate()
    restored = owner.current("profile-b", True)
    assert restored and restored != other
    assert owner.current("profile-b", False) is None
    assert owner.current("profile-b", True) != restored


def test_native_save_observations_require_actual_lifecycle_and_never_inherit_proofs():
    owner = NativeBookOwnerScope()
    assert owner.record_saved("profile-a", True, "a" * 64) is None
    owner.set_ready(True)
    source = owner.current("profile-a", True)
    assert owner.save_state("profile-a", True) == {"book_source": source, "sequence": 0, "sha256": ""}
    first = owner.record_saved("profile-a", True, "a" * 64)
    second = owner.record_saved("profile-a", True, "a" * 64)
    assert first["sequence"] == 1 and second["sequence"] == 2 and second["book_source"] == source
    second["sequence"] = 900
    assert owner.save_state("profile-a", True)["sequence"] == 2
    for retire in (lambda: owner.set_ready(False), owner.invalidate, lambda: owner.current("profile-b", True)):
        retire(); owner.set_ready(True)
        current = owner.save_state("profile-a", True)
        assert current["book_source"] != source and current["sequence"] == 0 and current["sha256"] == ""
        source = current["book_source"]
        owner.record_saved("profile-a", True, "b" * 64)
    assert owner.record_saved("profile-a", False, "c" * 64) is None


@pytest.mark.parametrize("value", [None, "client-saved", "A" * 64, "a" * 63])
def test_invalid_save_hashes_cannot_enter_native_observations(value):
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    with pytest.raises((TypeError, ValueError)): owner.record_saved("profile-a", True, value)
    assert owner.save_state("profile-a", True)["sequence"] == 0
