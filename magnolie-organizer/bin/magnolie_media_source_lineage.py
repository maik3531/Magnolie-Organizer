"""Protected source chronology (#429), never source/read/deletion authority.

Legacy jobs remain an unordered authenticated baseline. Only new native plans
record exact completed predecessors; UUID/SQLite/catalog membership order is
never interpreted as completion order. Reads do not migrate or repair history.
"""
from dataclasses import dataclass
from hashlib import sha256

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical


def validate_lineage(value):
    if (type(value) is not dict or set(value)!={'legacy_sha256','previous_job','previous_ready','previous_retirement'}
            or not _hex(value['legacy_sha256'])):
        raise TransferError('media_source_lineage_invalid')
    job=value['previous_job']
    if job is None:
        if value['previous_ready'] is not None or value['previous_retirement'] is not None:
            raise TransferError('media_source_lineage_invalid')
    elif (type(job) is not str or len(job)!=32 or not _hex(job*2)
            or not _hex(value['previous_ready']) or not _hex(value['previous_retirement'])):
        raise TransferError('media_source_lineage_invalid')


@dataclass(frozen=True)
class NativeSourceLineageSnapshot:
    catalog_version: str | None
    legacy_sha256: str
    legacy_count: int
    records: tuple
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def permits_deletion(self):return False


class _NativeSourceLineage:
    def __init__(self,jobs):self._jobs=jobs

    def _completed(self,db,key,record):
        from magnolie_media_source_retirement import _NativeSourceRetirementJournal,verify_retirement_exchange
        original=record.body;retired=_NativeSourceRetirementJournal(self._jobs)._read(db,key,original['job_id'])
        if record.state!='cache_ready' or retired is None or retired.body['state']!='archived':
            raise TransferError('media_source_lineage_pending_job')
        body=retired.body
        if (body['ready_version']!=record.version or body['nonce']!=original['nonce'] or body['manifest']!=original['manifest']
                or body['root_key']!=original['root_key'] or body['parent_key']!=original['parent_key']
                or body['proof_witness']['sha256']!=original['proof_sha256']):
            raise TransferError('media_source_lineage_original_completion_required')
        verify_retirement_exchange(self._jobs,db,key,record,body)
        return retired

    def inspect(self,db,key,catalog):
        jobs=self._jobs
        members=[] if catalog is None else catalog.body['members']
        records={name[len(jobs._prefix):]:jobs._read(db,key,name[len(jobs._prefix):])
                 for name,_ in members if name.startswith(jobs._prefix)}
        legacy=[];ordered={}
        for job,record in records.items():
            if record is None:raise TransferError('media_source_lineage_missing_job')
            if record.body['format']==1:
                # Hash the complete unordered baseline; do not invent its tip.
                retired=self._completed(db,key,record)
                legacy.append([job,record.version,retired.version])
            else:ordered[job]=record
        baseline=sha256(canonical(sorted(legacy))).hexdigest()
        children={}
        for job,record in ordered.items():
            lineage=record.body['lineage'];parent=lineage['previous_job']
            if lineage['legacy_sha256']!=baseline:raise TransferError('media_source_lineage_legacy_changed')
            if parent in children:raise TransferError('media_source_lineage_fork')
            children[parent]=job
            if parent is not None:
                previous=ordered.get(parent)
                if previous is None:raise TransferError('media_source_lineage_missing_predecessor')
                retired=self._completed(db,key,previous)
                if previous.version!=lineage['previous_ready'] or retired.version!=lineage['previous_retirement']:
                    raise TransferError('media_source_lineage_predecessor_changed')
        chain=[];cursor=None
        while cursor in children:
            cursor=children[cursor]
            if len(chain)>=len(ordered):raise TransferError('media_source_lineage_cycle')
            chain.append(ordered[cursor])
        if len(chain)!=len(ordered):raise TransferError('media_source_lineage_unreachable')
        return NativeSourceLineageSnapshot(None if catalog is None else catalog.version,baseline,len(legacy),tuple(chain))

    def predecessor(self,db,key,catalog):
        snapshot=self.inspect(db,key,catalog)
        if not snapshot.records:
            return dict(legacy_sha256=snapshot.legacy_sha256,previous_job=None,previous_ready=None,previous_retirement=None)
        previous=snapshot.records[-1];retired=self._completed(db,key,previous)
        return dict(legacy_sha256=snapshot.legacy_sha256,previous_job=previous.body['job_id'],
                    previous_ready=previous.version,previous_retirement=retired.version)

    def lookup(self):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');catalog=self._jobs._catalog.verify(db,key);result=self.inspect(db,key,catalog)
        self._jobs._catalog.observe(catalog)
        return result
