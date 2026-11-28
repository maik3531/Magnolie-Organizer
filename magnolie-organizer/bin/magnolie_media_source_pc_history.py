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


def _origins(record):
    body=record.body
    if body['format']==4:return [(fid,e['local_origin']) for fid,e in body['members'].items()]
    origin=body.get('local_origin')
    # The original identity is also protected in a planned single-file job
    # before there is a manifest. Only batch callers need the member ID here.
    return [] if origin is None else [(None,origin)]


def _completed(jobs,db,key,record,trail=(),*,origin=None):
    from magnolie_media_source_lineage import _NativeSourceLineage
    from magnolie_file_saved_message import parse_saved
    retired,exchange=_NativeSourceLineage(jobs)._completed_exchange(db,key,record,pc_trail=trail)
    batch=record.body['format']==4
    if retired.body['format']!=(3 if batch else 1):raise TransferError('media_collection_completed_source_required')
    if exchange is None or exchange.version!=retired.body['exchange_version'] or exchange.body['format']!=(5 if batch else 4):
        raise TransferError('media_collection_completed_source_required')
    manifest=FileManifest.parse(record.body['manifest'])
    if batch:
        matches=[fid for fid,old in _origins(record) if origin is not None and old==origin]
        if len(matches)!=1:raise TransferError('media_collection_completed_source_required')
        file=next(f for f in manifest.files if f.id==matches[0])
    else:file=manifest.files[0]
    saved=exchange.body['peer_saved']
    receipt=next(r for r in parse_saved(saved,manifest,now=saved['created_ms']).receipts if r.file_id==file.id)
    return NativePcSourcePredecessor(record.body['job_id'],record.version,retired.version,receipt.receipt_sha256,file.size,file.sha256)


def admitted_predecessor(jobs,db,key,catalog,origin):
    """Admission candidate only; a new live native owner must still read bytes.

    Full chronology validation rejects pending predecessors/forks. Exact root
    and file generations remain required even for unchanged content.
    """
    from magnolie_media_source_lineage import _NativeSourceLineage
    snapshot=_NativeSourceLineage(jobs).inspect(db,key,catalog)
    related=[record for record in snapshot.records if any(_related(old,origin) for _,old in _origins(record))]
    if not related:raise TransferError('media_collection_completed_source_required')
    if any(any(old!=origin for _,old in _origins(record) if _related(old,origin)) for record in related):
        raise TransferError('media_collection_existing_source_held')
    if snapshot.records[-1] is not related[-1]:
        _NativeSourceLineage(jobs)._completed(db,key,snapshot.records[-1])
    return replace(_completed(jobs,db,key,related[-1],origin=origin),catalog_version=catalog.version)


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
        related=[old for _,old in _origins(record) if _related(old,origin)]
        if related:
            if len(related)!=1 or related[0]!=origin:raise TransferError('media_collection_existing_source_held')
            return _completed(jobs,db,key,record,trail,origin=origin).publication_sha256
        cursor=record


def batch_predecessors(jobs,db,key,ready,trail=()):
    """Resolve all earlier member completions from the original lineage once.

    Old catalog stamps are immutable native-plan correlation DATA; independently
    resolve every job/ready/END/publication/size/hash instead of trusting a ready
    record's self-reported previous publication or choosing manifest.files[0].
    """
    from dataclasses import asdict
    from magnolie_media_source_lineage import _NativeSourceLineage
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal
    body=ready.body;job=body['job_id']
    if body['format']!=4 or job in trail or len(trail)>=jobs.MAX_RECORDS:raise TransferError('media_source_lineage_cycle')
    trail=(*trail,job);visited=set(trail);cursor=ready
    wanted={fid:e['local_origin'] for fid,e in body['members'].items()};result={}
    journal=_NativeSourceRetirementJournal(jobs)
    while wanted:
        lineage=cursor.body.get('lineage')
        if lineage is None:raise TransferError('media_source_lineage_missing_predecessor')
        parent=lineage['previous_job']
        if parent is None:break
        if parent in visited or len(visited)>=jobs.MAX_RECORDS:raise TransferError('media_source_lineage_cycle')
        visited.add(parent);record=jobs._read(db,key,parent);retired=journal._read(db,key,parent)
        if (record is None or retired is None or record.version!=lineage['previous_ready']
                or retired.version!=lineage['previous_retirement'] or retired.body['state']!='archived'):
            raise TransferError('media_source_lineage_predecessor_changed')
        _NativeSourceLineage(jobs)._completed(db,key,record,pc_trail=trail)
        for fid,origin in tuple(wanted.items()):
            matches=[old for _,old in _origins(record) if _related(old,origin)]
            if not matches:continue
            if len(matches)!=1 or matches[0]!=origin:raise TransferError('media_collection_existing_source_held')
            previous=asdict(_completed(jobs,db,key,record,trail,origin=origin))
            declared=body['predecessors'][fid]
            if declared is None:raise TransferError('media_collection_retirement_original_predecessors_required')
            previous['catalog_version']=declared['catalog_version']
            result[fid]=previous;del wanted[fid]
        cursor=record
    result.update({fid:None for fid in wanted})
    return result
