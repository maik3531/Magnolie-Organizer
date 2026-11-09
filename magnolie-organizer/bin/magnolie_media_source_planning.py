"""Native mapped-source comparison (#429); no cache, transfer or read grant."""
from dataclasses import dataclass
import os

from magnolie_file_transfer import FileManifest,TransferError
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_lineage import _NativeSourceLineage


@dataclass(frozen=True)
class NativeMediaSourcePlanObservation:
    observation: object
    changed: bool
    basis: str
    latest_job_id: str | None
    catalog_version: str | None
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def permits_deletion(self):return False


@dataclass(frozen=True)
class NativeMediaSourcePreparation:
    plan: NativeMediaSourcePlanObservation
    cache: object | None
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False


def compare_current_source(source,mapping,observation,current):
    """Called only inside actual source/book/mapping/file/OS-I/O ownership.

    No file is restored and no preparation is created. A later actual sender
    must independently reopen/freeze the then-current source with fresh consent.
    """
    from magnolie_media_source import NativeMappedMediaSource,NativeMediaSourceObservation
    if (type(source) is not NativeMappedMediaSource or not source._gate.locked()
            or type(observation) is not NativeMediaSourceObservation or not callable(current)):
        raise TransferError('media_source_planning_native_owner_required')
    current();jobs=_NativeSourceJobs(source._authority)
    before=jobs._catalog.lookup()
    parent=os.open(source._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:jobs._catalog.require_free_slot(parent,current)
    finally:os.close(parent)
    with jobs._database() as (db,key):
        db.execute('BEGIN');catalog=jobs._catalog.verify(db,key)
        if catalog!=before:raise TransferError('media_source_planning_history_changed')
        lineage=_NativeSourceLineage(jobs);history=lineage.inspect(db,key,catalog)
        reference=mapping.phone_original_reference()
        latest=None;legacy=False
        members=[] if catalog is None else catalog.body['members']
        for name,_ in members:
            if not name.startswith(jobs._prefix):continue
            record=jobs._read(db,key,name[len(jobs._prefix):])
            if record.body['format']==1 and reference in (record.body['original_references'] or {}).values():legacy=True
        # This is protected chronological order, NEVER membership/UUID order.
        for record in history.records:
            if reference in (record.body['original_references'] or {}).values():latest=record
        basis='original_mapping';job=None
        size,digest=mapping.saved_size,mapping.saved_sha256
        if latest is not None:
            lineage._completed(db,key,latest)
            body=latest.body;manifest=FileManifest.parse(body['manifest'])
            if body['original_references']!={manifest.files[0].id:reference}:
                raise TransferError('media_source_planning_original_reference_required')
            from magnolie_media_source_exchange import _read_source_exchange
            exchange=_read_source_exchange(jobs,db,key,body['job_id'],latest)
            # Older generic file-Saved history is not normal media readback.
            # It may establish a predecessor, but never a deduplication right.
            if exchange is None or exchange.body['format']!=4:
                basis='completion_not_comparable';size=digest=None
            else:
                basis='latest_completed';size,digest=manifest.files[0].size,manifest.files[0].sha256
            job=body['job_id']
        elif legacy:
            basis='legacy_order_unknown';size=digest=None
        changed=(observation.size,observation.sha256)!=(size,digest)
    jobs._catalog.observe(catalog);current()
    return NativeMediaSourcePlanObservation(observation,changed,basis,job,history.catalog_version)
