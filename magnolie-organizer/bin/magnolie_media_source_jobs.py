"""Native source-cache job intent (#338), never a receiver/Saved/READ grant.

Only the live source-cache writer creates/advances these records. Queries never
bootstrap or repair missing records. Source restart, offer/accept/chunk/Saved,
catalog retirement and production readiness remain separate native lifecycles.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import copy
import os
import sqlite3
import stat

from magnolie_file_control import _hex
from magnolie_file_transfer import FileManifest,TransferError
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_telefon import canonical,strict_json


@dataclass(frozen=True)
class NativeSourceJobRecord:
    version: str
    _body: dict
    @property
    def body(self):return copy.deepcopy(self._body)
    @property
    def state(self):return self._body['state']
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False


class _NativeSourceJobs:
    MAX_RECORDS=128
    MAX_BYTES=8192
    def __init__(self,authority):
        if type(authority) is not NativeDesktopFileAuthority:raise TransferError('media_source_jobs_native_owner_required')
        self._authority=authority;self._store=authority.binding.store_owner
        peer=authority.current_peer()
        if peer is None:raise TransferError('media_source_jobs_native_owner_required')
        self._scope=sha256(canonical(dict(local_id=authority.identity.receiver_id,local_key=authority.identity.receiver_identity_sha256,
            peer_id=peer.peer_id,peer_key=peer.identity_sha256))).hexdigest()
        self._prefix='native_media_source_jobs_v1/'+self._scope+'/'
        self._database_key=self._fresh()
        from magnolie_media_source_catalog import _NativeSourceCatalog
        self._catalog=_NativeSourceCatalog(self)

    def _key(self,job):
        if type(job) is not str or len(job)!=32 or not _hex(job*2):raise TransferError('media_source_jobs_invalid_job')
        return self._prefix+job

    def _fresh(self):
        if self._authority.current_peer() is None:raise TransferError('media_source_jobs_native_owner_changed')
        value=os.stat(self._store.database_path,follow_symlinks=False)
        if not stat.S_ISREG(value.st_mode) or value.st_uid!=os.geteuid() or value.st_nlink!=1 or value.st_mode&0o077:
            raise TransferError('media_source_jobs_original_database_required')
        return value.st_dev,value.st_ino

    @contextmanager
    def _database(self):
        key=self._fresh();db=sqlite3.connect(Path(self._store.database_path).absolute().as_uri()+'?mode=rw',uri=True,timeout=0)
        try:
            if key!=self._database_key or self._fresh()!=key:raise TransferError('media_source_jobs_original_database_required')
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db,key
                if self._fresh()!=key:raise TransferError('media_source_jobs_original_database_required')
            if self._fresh()!=key:raise TransferError('media_source_jobs_original_database_required')
        finally:db.close()

    def _decode(self,job,cipher,db_key):
        if type(cipher) is not bytes or not 29<=len(cipher)<=self.MAX_BYTES+28:raise TransferError('media_source_jobs_record_invalid')
        plain=self._authority.protection.unseal(cipher,self._key(job));body=strict_json(plain)
        if (type(body) is not dict or set(body)!={'format','scope','database_key','job_id','nonce','state','intent_sha256','root_key',
                'parent_key','book_version','source_policy_sha256','pairing_epoch','manifest','proof_sha256','original_references'}
                or type(body['format']) is not int or body['format']!=1 or body['scope']!=self._scope or body['job_id']!=job
                or body['database_key']!=list(db_key) or canonical(body)!=plain):raise TransferError('media_source_jobs_record_invalid')
        for name in ('nonce','intent_sha256','book_version','source_policy_sha256','pairing_epoch'):
            if not _hex(body[name]):raise TransferError('media_source_jobs_record_invalid')
        for name in ('root_key','parent_key'):
            key=body[name]
            if type(key) is not list or len(key)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in key) or key[1]==0:
                raise TransferError('media_source_jobs_record_invalid')
        if body['state']=='cache_planned':
            if body['manifest'] is not None or body['proof_sha256'] is not None or body['original_references'] is not None:
                raise TransferError('media_source_jobs_record_invalid')
        elif body['state']=='cache_ready':
            manifest=FileManifest.parse(body['manifest'])
            if manifest.source_id!=job or len(manifest.files)!=1 or not _hex(body['proof_sha256']) or type(body['original_references']) is not dict:
                raise TransferError('media_source_jobs_record_invalid')
        else:raise TransferError('media_source_jobs_record_invalid')
        return NativeSourceJobRecord(sha256(cipher).hexdigest(),body)

    def _read(self,db,db_key,job):
        row=db.execute('SELECT value FROM meta WHERE key=?',(self._key(job),)).fetchone()
        return self._decode(job,row[0],db_key) if row else None

    def lookup(self,job):
        with self._database() as (db,key):
            db.execute('BEGIN');catalog=self._catalog.verify(db,key);result=self._read(db,key,job)
        self._catalog.observe(catalog);return result

    def _writer(self,writer):
        from magnolie_media_source_cache import _NativeSourceCacheWriter
        if type(writer) is not _NativeSourceCacheWriter or writer._authority is not self._authority or writer._scope!=self._scope:
            raise TransferError('media_source_jobs_live_writer_required')
        writer._guard()

    def plan(self,writer,intent):
        self._writer(writer);job=writer._job
        if (sha256(canonical(intent)).hexdigest()!=writer._intent_sha256 or intent['job_id']!=job
                or intent['scope']!=self._scope):raise TransferError('media_source_jobs_original_plan_required')
        with self._database() as (db,key):
            db.execute('BEGIN IMMEDIATE')
            catalog=self._catalog.verify(db,key)
            if catalog is None:catalog=self._catalog.initialize(writer,db,key)
            if self._read(db,key,job) is not None:raise TransferError('media_source_jobs_original_plan_required')
            count=db.execute('SELECT COUNT(*) FROM meta WHERE key LIKE ?',(self._prefix+'%',)).fetchone()[0]
            if count>=self.MAX_RECORDS:raise TransferError('media_source_jobs_capacity')
            body=dict(format=1,scope=self._scope,database_key=list(key),job_id=job,nonce=intent['job_nonce'],state='cache_planned',
                intent_sha256=writer._intent_sha256,root_key=list(writer._root_key),parent_key=list(writer._parent_key),
                book_version=intent['book_version'],source_policy_sha256=intent['source_policy_sha256'],pairing_epoch=intent['pairing_epoch'],
                manifest=None,proof_sha256=None,original_references=None)
            plain=canonical(body)
            if len(plain)>self.MAX_BYTES:raise TransferError('media_source_jobs_record_size')
            cipher=self._authority.protection.seal(plain,self._key(job));self._decode(job,cipher,key);self._writer(writer)
            db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._key(job),cipher));self._writer(writer)
            self._catalog.advance(db,key,catalog);self._writer(writer)
        self._writer(writer)
        result=self.lookup(job)
        if result is None or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_jobs_plan_readback_failed')
        return result

    def ready(self,writer,planned,manifest,proof_sha256):
        self._writer(writer);job=writer._job
        if getattr(writer,'_planned_job',None) is not planned:raise TransferError('media_source_jobs_original_plan_required')
        body=planned.body;body.update(state='cache_ready',manifest=manifest.wire(),proof_sha256=proof_sha256,
            original_references={writer._file:writer._reference})
        plain=canonical(body)
        if len(plain)>self.MAX_BYTES:raise TransferError('media_source_jobs_record_size')
        with self._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=self._catalog.verify(db,key);before=self._read(db,key,job)
            if before is None or before.version!=planned.version or before.state!='cache_planned':raise TransferError('media_source_jobs_plan_changed')
            cipher=self._authority.protection.seal(plain,self._key(job));self._decode(job,cipher,key);self._writer(writer)
            db.execute('UPDATE meta SET value=? WHERE key=?',(cipher,self._key(job)));self._writer(writer)
            self._catalog.advance(db,key,catalog);self._writer(writer)
        self._writer(writer);result=self.lookup(job)
        if result is None or result.body!=body or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_jobs_ready_readback_failed')
        return result

    def require_version(self,job,version):
        record=self.lookup(job)
        if record is None or record.version!=version or record.state!='cache_ready':raise TransferError('media_source_jobs_ready_record_required')
        return record
