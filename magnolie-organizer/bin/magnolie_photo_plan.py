"""Read-only three-way photo comparison proposals (#329).

Inputs belong to native authenticated observations/receipt storage, not network
claims. This module performs no I/O and returns NO write/deletion permission,
saved receipt or accepted baseline. Real execution still requires fresh native
identity/grants/ownership/CAS and actual publication/readback.
"""
from dataclasses import dataclass
import re

from magnolie_file_transfer import MAX_FILE_BYTES, NativeTransferBinding, TransferError


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise TransferError("photo_plan_invalid_witness")


@dataclass(frozen=True)
class PhotoContentWitness:
    sha256: str
    size: int

    def __post_init__(self):
        _sha(self.sha256)
        if type(self.size) is not int or not 0 <= self.size <= MAX_FILE_BYTES:
            raise TransferError("photo_plan_invalid_content_size")


@dataclass(frozen=True)
class NativePhotoAssociation:
    binding: NativeTransferBinding
    source_epoch: str
    photo_id: str
    target_mapping_token: str

    def __post_init__(self):
        if type(self.binding) is not NativeTransferBinding or self.binding.sender_id == self.binding.receiver_id:
            raise TransferError("photo_plan_invalid_native_association")
        for value in (self.source_epoch, self.photo_id, self.target_mapping_token):
            _sha(value)


@dataclass(frozen=True)
class NativePhotoBaseline:
    association: NativePhotoAssociation
    content: PhotoContentWitness
    receipt_sha256: str

    def __post_init__(self):
        if type(self.association) is not NativePhotoAssociation or type(self.content) is not PhotoContentWitness:
            raise TransferError("photo_plan_invalid_native_baseline")
        _sha(self.receipt_sha256)


@dataclass(frozen=True)
class NativePhotoObservation:
    # "missing" is unconfirmed absence, never an authoritative deletion.
    # "deleted" is reserved for actual native deletion evidence, NOT a partial
    # gallery/SAF scan, invisible album or an Android READ-permission flag.
    state: str
    content: PhotoContentWitness | None = None
    managed: bool = False
    insertion_proven: bool = False

    def __post_init__(self):
        if (type(self.state) is not str or self.state not in {"present", "missing", "deleted", "unknown"}
                or type(self.managed) is not bool or type(self.insertion_proven) is not bool
                or self.state == "present" and type(self.content) is not PhotoContentWitness
                or self.state != "present" and (self.content is not None or self.managed or self.insertion_proven)):
            raise TransferError("photo_plan_invalid_native_observation")


@dataclass(frozen=True)
class PhotoSyncPlanPolicy:
    direction: str = "phone_to_desktop"
    phone_deletions_to_desktop: bool = False
    desktop_deletions_to_phone: bool = False

    def __post_init__(self):
        if (type(self.direction) is not str or self.direction not in {"phone_to_desktop", "bidirectional"}
                or type(self.phone_deletions_to_desktop) is not bool or type(self.desktop_deletions_to_phone) is not bool):
            raise TransferError("photo_plan_invalid_policy")


@dataclass(frozen=True)
class NativePhotoPlanSupport:
    # Genuine native no-loss adapters only, never enabled by a wire/UI Boolean.
    create_desktop: bool = False
    replace_desktop: bool = False
    trash_desktop: bool = False
    replace_phone: bool = False
    delete_phone: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in vars(self).values()):
            raise TransferError("photo_plan_invalid_native_support")


@dataclass(frozen=True)
class PhotoSyncProposal:
    kind: str
    baseline_receipt: str | None
    expected_phone: PhotoContentWitness | None
    expected_desktop: PhotoContentWitness | None

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_saved_receipt(self):
        return False


def compare_photo(association, baseline, phone, desktop, policy=None, support=None):
    policy = PhotoSyncPlanPolicy() if policy is None else policy
    support = NativePhotoPlanSupport() if support is None else support
    if (type(association) is not NativePhotoAssociation or baseline is not None and type(baseline) is not NativePhotoBaseline
            or type(phone) is not NativePhotoObservation or type(desktop) is not NativePhotoObservation
            or type(policy) is not PhotoSyncPlanPolicy or type(support) is not NativePhotoPlanSupport):
        raise TransferError("photo_plan_native_inputs_required")

    def result(kind):
        return PhotoSyncProposal(kind, baseline.receipt_sha256 if baseline is not None else None, phone.content, desktop.content)

    if baseline is not None and baseline.association != association:
        return result("pause_scope_changed")
    if "unknown" in {phone.state, desktop.state}:
        return result("pause_unknown")
    if baseline is None:
        if phone.state == "present":
            if desktop.state == "present":
                return result("conflict_unmanaged_target")  # Equal bytes do not adopt an unknown target.
            return result("copy_phone_new" if support.create_desktop else "unsupported_desktop_create")
        return result("keep_unmanaged_desktop" if desktop.state == "present" else "nothing_to_sync")
    if "missing" in {phone.state, desktop.state}:
        return result("pause_unconfirmed_absence")
    if desktop.state == "present" and not desktop.managed:
        return result("conflict_unmanaged_target")
    common = baseline.content
    if phone.state == desktop.state == "present":
        if phone.content == desktop.content == common:
            return result("unchanged")
        if phone.content == desktop.content:
            return result("confirm_equal_content" if phone.insertion_proven else "conflict_unproven_source_identity")
        if phone.content != common and desktop.content != common:
            return result("conflict_edit_edit")
        if phone.content != common:
            if not phone.insertion_proven:
                return result("conflict_unproven_source_identity")
            return result("replace_managed_desktop" if support.replace_desktop else "unsupported_desktop_replace")
        if policy.direction == "phone_to_desktop":
            return result("keep_local_edit")  # Do not resend unchanged phone bytes over a PC crop.
        if not phone.insertion_proven:
            return result("conflict_unproven_source_identity")
        return result("replace_phone" if support.replace_phone else "unsupported_phone_replace")
    if phone.state == desktop.state == "deleted":
        return result("both_deleted")
    if phone.state == "deleted":
        if desktop.content != common:
            return result("conflict_edit_delete")
        if not policy.phone_deletions_to_desktop:
            return result("keep_desktop_copy")
        return result("trash_managed_desktop" if support.trash_desktop else "unsupported_desktop_trash")
    if phone.content != common:
        return result("conflict_edit_delete")
    if not policy.desktop_deletions_to_phone:
        return result("keep_phone_copy")  # A local tombstone is not permission to recreate the PC file.
    if policy.direction != "bidirectional" or not support.delete_phone:
        return result("unsupported_phone_delete")
    return result("delete_phone" if phone.insertion_proven else "conflict_unproven_source_identity")
