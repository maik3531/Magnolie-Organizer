"""Native ordinary-sync review results, never permission to replace/delete files."""
from dataclasses import dataclass


@dataclass(frozen=True)
class NativePhotoReviewItem:
    file_id: str
    photo_id: str
    decision: str
    original_job_owner: str | None = None
    prior_mapping_sha256: str | None = None


@dataclass(frozen=True)
class NativePhotoReview:
    manifest_sha256: str
    items: tuple

    @property
    def nothing_to_download(self):
        return bool(self.items) and all(item.decision in ('unchanged', 'keep_local_edit') for item in self.items)

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_saved_receipt(self):
        return False
