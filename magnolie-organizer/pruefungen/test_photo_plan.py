"""Pure three-way proposals, no source/target I/O or manufactured saved receipts."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import NativeTransferBinding, TransferError
from magnolie_photo_plan import (NativePhotoAssociation, NativePhotoBaseline, NativePhotoObservation,
    NativePhotoPlanSupport, PhotoContentWitness, PhotoSyncPlanPolicy, compare_photo)

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "contracts/photo-sync-plan-v1-vectors.json").read_text())
CONTENTS = {name: PhotoContentWitness(**value) for name, value in VECTORS["contents"].items()}


def association():
    return NativePhotoAssociation(NativeTransferBinding("sender_fixture_01", "receiver_fixture_01", "d" * 64, "e" * 64,
        "f" * 64, "0" * 64), "a" * 64, "b" * 64, "c" * 64)


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["name"])
def test_shared_three_way_vectors_never_grant_writes_or_create_receipts(case):
    owner = association()
    baseline = NativePhotoBaseline(owner, CONTENTS[case["baseline"]], "9" * 64) if case["baseline"] else None
    def observation(value, desktop=False):
        if value in CONTENTS:
            return NativePhotoObservation("present", CONTENTS[value], managed=desktop and case.get("managed", True),
                insertion_proven=not desktop and case.get("insertion", True))
        return NativePhotoObservation(value)
    support = NativePhotoPlanSupport(**{name: True for name in case.get("support", VECTORS["default_support"])})
    policy = PhotoSyncPlanPolicy(case.get("direction", "phone_to_desktop"), case.get("phone_delete", False), case.get("pc_delete", False))
    phone, desktop = observation(case["phone"]), observation(case["desktop"], True)
    result = compare_photo(owner, baseline, phone, desktop, policy, support)
    assert result.kind == case["expected"]
    assert result.expected_phone == phone.content and result.expected_desktop == desktop.content
    assert not result.grants_write_authority and not result.is_saved_receipt
    assert result.requires_trash_entry == (result.kind in {"trash_managed_desktop", "trash_phone"})
    assert result.baseline_receipt == (baseline.receipt_sha256 if baseline is not None else None)


def test_source_destination_peer_or_binding_change_pauses_instead_of_reinterpreting_a_baseline():
    owner = association(); baseline = NativePhotoBaseline(owner, CONTENTS["old"], "9" * 64)
    phone = NativePhotoObservation("deleted")
    desktop = NativePhotoObservation("present", CONTENTS["old"], managed=True)
    policy = PhotoSyncPlanPolicy("bidirectional", True, True)
    support = NativePhotoPlanSupport(True, True, True, True, True)
    changes = [replace(owner, source_epoch="1" * 64), replace(owner, photo_id="1" * 64), replace(owner, target_mapping_token="1" * 64)]
    for field in ("sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token"):
        changes.append(replace(owner, binding=replace(owner.binding, **{field: "1" * 64})))
    for changed in changes:
        assert compare_photo(changed, baseline, phone, desktop, policy, support).kind == "pause_scope_changed"
    assert baseline.association == owner and baseline.content == CONTENTS["old"]


def test_default_policy_does_not_allow_reverse_writes_or_deletion_and_support_is_not_assumed():
    policy = PhotoSyncPlanPolicy()
    assert policy.direction == "phone_to_desktop" and not policy.phone_deletions_to_desktop and not policy.desktop_deletions_to_phone
    owner = association()
    result = compare_photo(owner, None, NativePhotoObservation("present", CONTENTS["old"]), NativePhotoObservation("missing"))
    assert result.kind == "unsupported_desktop_create" and not result.grants_write_authority


def test_native_input_shapes_are_strict_and_proposal_cannot_be_mutated_into_a_write_ack():
    for invalid in (True, -1, 50 * 1024 * 1024 + 1):
        with pytest.raises(TransferError):
            PhotoContentWitness("1" * 64, invalid)
    for state in ("present", "missing", "unknown", "deleted"):
        with pytest.raises(TransferError):
            NativePhotoObservation(state, CONTENTS["old"] if state != "present" else None)
    with pytest.raises(TransferError):
        NativePhotoObservation("present", CONTENTS["old"], managed=1)
    with pytest.raises(TransferError):
        NativePhotoPlanSupport(replace_phone=1)
    with pytest.raises(TransferError):
        NativePhotoPlanSupport(trash_phone=1)
    with pytest.raises(TransferError):
        PhotoSyncPlanPolicy(phone_deletions_to_desktop=1)
    owner = association()
    result = compare_photo(owner, None, NativePhotoObservation("missing"), NativePhotoObservation("missing"))
    with pytest.raises(FrozenInstanceError):
        result.kind = "delete_phone"
