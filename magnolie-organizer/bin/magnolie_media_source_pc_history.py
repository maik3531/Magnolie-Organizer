"""Exact protected PC predecessor DATA (#487), never a native source permit.

The existing global source chronology supplies order. Receiver publications are
correlated only through completed Saved/readback/retirement evidence, not UUIDs,
catalog iteration order or a caller's previous-publication claim.
"""
from dataclasses import dataclass,replace

from magnolie_file_transfer import FileManifest,TransferError


@dataclass(frozen=True)
class NativePcSourcePredecessor:
    job_id: str
    ready_version: str
    retirement_version: str
    publication_sha256: str
    size: int
    sha256: str
    catalog_version: str | None = None

    @property
    def grants_read_authority(self):return False


def _related(old,origin):
    return old is not None and (old['file_key']==origin['file_key'] or
        old['root_id']==origin['root_id'] and old['file_path']==origin['file_path'])


def _completed(jobs,db,key,record,trail=()):
    from magnolie_media_source_lineage import _NativeSourceLineage
    from magnolie_media_source_exchange import _read_source_exchange
    from magnolie_file_saved_message import parse_saved
    retired=_NativeSourceLineage(jobs)._completed(db,key,record,pc_trail=trail)
    if retired.body['format']!=1:raise TransferError('media_collection_completed_source_required')
    exchange=_read_source_exchange(jobs,db,key,record.body['job_id'],record)
    if exchange is None or exchange.version!=retired.body['exchange_version'] or exchange.body['format']!=4:
        raise TransferError('media_collection_completed_source_required')
    manifest=FileManifest.parse(record.body['manifest']);file=manifest.files[0]
    saved=exchange.body['peer_saved'];receipt=parse_saved(saved,manifest,now=saved['created_ms']).receipts[0]
    return NativePcSourcePredecessor(record.body['job_id'],record.version,retired.version,receipt.receipt_sha256,file.size,file.sha256)


def admitted_predecessor(jobs,db,key,catalog,origin):
    """Admission candidate only; a new live native owner must still read bytes.

    Full chronology validation rejects pending predecessors/forks. Exact root
    and file generations remain required even for unchanged content.
    """
    from magnolie_media_source_lineage import _NativeSourceLineage
    snapshot=_NativeSourceLineage(jobs).inspect(db,key,catalog)
    related=[record for record in snapshot.records if _related(record.body.get('local_origin'),origin)]
    if not related:raise TransferError('media_collection_completed_source_required')
    if any(record.body['local_origin']!=origin for record in related):
        raise TransferError('media_collection_existing_source_held')
    if snapshot.records[-1] is not related[-1]:
        _NativeSourceLineage(jobs)._completed(db,key,snapshot.records[-1])
    return replace(_completed(jobs,db,key,related[-1]),catalog_version=catalog.version)


def previous_publication(jobs,db,key,ready,trail=()):
    """Resolve an existing job's exact earlier same-origin publication.

    Walk backwards through explicit ready/retirement hashes. Never call full
    chronology inspection from an exchange validator (which would recurse back
    into itself). Recursive same-source verification carries one bounded trail.
    """
    origin=ready.body.get('local_origin')
    if origin is None:return None
    job=ready.body['job_id']
    if job in trail or len(trail)>=jobs.MAX_RECORDS:raise TransferError('media_source_lineage_cycle')
    trail=(*trail,job);visited=set(trail);cursor=ready
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal
    journal=_NativeSourceRetirementJournal(jobs)
    while True:
        lineage=cursor.body.get('lineage')
        if lineage is None:raise TransferError('media_source_lineage_missing_predecessor')
        parent=lineage['previous_job']
        if parent is None:return None
        if parent in visited or len(visited)>=jobs.MAX_RECORDS:raise TransferError('media_source_lineage_cycle')
        visited.add(parent)
        record=jobs._read(db,key,parent);retired=journal._read(db,key,parent)
        if (record is None or retired is None or record.version!=lineage['previous_ready'] or
                retired.version!=lineage['previous_retirement'] or retired.body['state']!='archived'):
            raise TransferError('media_source_lineage_predecessor_changed')
        old=record.body.get('local_origin')
        if _related(old,origin):
            if old!=origin:raise TransferError('media_collection_existing_source_held')
            return _completed(jobs,db,key,record,trail).publication_sha256
        cursor=record
