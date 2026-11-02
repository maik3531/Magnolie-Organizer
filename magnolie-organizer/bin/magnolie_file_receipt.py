"""Durable local file-save receipt, never a book SaveACK or a write grant."""
from dataclasses import dataclass
import re

from magnolie_file_transfer import TransferError


@dataclass(frozen=True)
class NativeSavedFileReceipt:
    owner: str
    manifest_sha256: str
    accepted_sha256: str
    file_id: str
    relative_path: str
    size: int
    sha256: str
    file_key: tuple
    parent_keys: tuple
    journal_phase: str
    journal_record_sha256: str
    checkpoint_sha256: str
    protected_record_sha256: str

    def wire(self):
        return {"format": 1, "owner": self.owner, "manifest_sha256": self.manifest_sha256,
            "accepted_sha256": self.accepted_sha256, "file_id": self.file_id, "relative_path": self.relative_path,
            "size": self.size, "sha256": self.sha256, "file_key": list(self.file_key),
            "parent_keys": [list(key) for key in self.parent_keys], "journal_phase": self.journal_phase,
            "journal_record_sha256": self.journal_record_sha256, "checkpoint_sha256": self.checkpoint_sha256}

    @classmethod
    def parse(cls, value, accepted, owner, file_id, record_sha256, head_hashes):
        fields = {"format", "owner", "manifest_sha256", "accepted_sha256", "file_id", "relative_path", "size", "sha256",
            "file_key", "parent_keys", "journal_phase", "journal_record_sha256", "checkpoint_sha256"}
        file = next((file for file in accepted.manifest.files if file.id == file_id), None)
        if (type(value) is not dict or set(value) != fields or type(value["format"]) is not int or value["format"] != 1
                or file is None or value["owner"] != owner or value["file_id"] != file_id
                or value["manifest_sha256"] != accepted.manifest.fingerprint or value["accepted_sha256"] != accepted.fingerprint
                or value["relative_path"] != dict(accepted.targets)[file_id] or type(value["size"]) is not int
                or value["size"] != file.size or value["sha256"] != file.sha256
                or value["journal_phase"] not in {"prepared", "linked", "verified"}
                or type(value["parent_keys"]) is not list or len(value["parent_keys"]) != len(value["relative_path"].split("/"))):
            raise TransferError("file_saved_receipt_context_mismatch")
        for text in (value["journal_record_sha256"], value["checkpoint_sha256"], record_sha256):
            if type(text) is not str or re.fullmatch(r"[0-9a-f]{64}", text) is None:
                raise TransferError("file_saved_receipt_invalid_hash")
        keys = [value["file_key"], *value["parent_keys"]]
        for key in keys:
            if (type(key) is not list or len(key) != 2 or any(type(number) is not int or not 0 <= number < 2**64 for number in key)
                    or key[1] == 0):
                raise TransferError("file_saved_receipt_invalid_witness")
        if (tuple(value["parent_keys"][0]) != accepted.destination.ancestor_keys[0]
                or value["file_key"][0] != value["parent_keys"][-1][0] or value["checkpoint_sha256"] not in head_hashes):
            raise TransferError("file_saved_receipt_original_scope_changed")
        return cls(owner, value["manifest_sha256"], value["accepted_sha256"], file_id, value["relative_path"], value["size"], value["sha256"],
            tuple(value["file_key"]), tuple(tuple(key) for key in value["parent_keys"]), value["journal_phase"],
            value["journal_record_sha256"], value["checkpoint_sha256"], record_sha256)

    @property
    def is_saved_receipt(self):
        return True  # Historical durable local save, not current file presence.

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_book_save_ack(self):
        return False
