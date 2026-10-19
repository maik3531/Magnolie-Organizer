"""Native book authority lifetime; no document-tracking or transport side effects."""
import re
import sys
from pathlib import Path

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
