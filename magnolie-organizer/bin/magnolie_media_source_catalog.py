"""Complete native source-job/exchange membership (#405), not restart rights.

An immutable original inode-bound anchor fences missing/reset metadata. Only an
actual live cache writer may initialize an unused scope. All head/member writes
share the caller's existing IMMEDIATE SQLite transaction; reads never repair.
There is no source-slot retirement, archive adoption or restart API here.
"""
from dataclasses import dataclass
from hashlib import sha256
import copy
import os
import secrets
import stat

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical,strict_json


@dataclass(frozen=True)
class NativeSourceCatalogSnapshot:
    version: str
    _body: dict
    @property
    def body(self):return copy.deepcopy(self._body)
    @property
    def grants_read_authority(self):return False
    @property
    def permits_slot_reuse(self):return False
    @property
    def is_saved_receipt(self):return False


class _NativeSourceCatalog:
    MAX_HEAD=131072
    def __init__(self,jobs):
        self._jobs=jobs;self._authority=jobs._authority
        self._key='native_media_source_catalog_v1/'+jobs._scope
        self._exchange='native_media_source_exchange_v1/'+jobs._scope+'/'
        self._retirement='native_media_source_retirement_v1/'+jobs._scope+'/'
        self._retry='native_media_source_retry_v1/'+jobs._scope+'/'
        self._anchor_name='.magnolie-source-catalog-'+jobs._scope+'.seal'
        self._domain='native-media-source-catalog-v1/'+jobs._scope+'/'
        self._observed=None;self._anchor_identity=None

    def _members(self,db):
        rows=db.execute('SELECT key,value FROM meta WHERE key GLOB ? OR key GLOB ? OR key GLOB ? OR key GLOB ? ORDER BY key LIMIT ?',
            (self._jobs._prefix+'*',self._exchange+'*',self._retirement+'*',self._retry+'*',4*self._jobs.MAX_RECORDS+1)).fetchall()
        if len(rows)>4*self._jobs.MAX_RECORDS:raise TransferError('media_source_catalog_capacity')
        members=[];job_ids=set();exchange_ids=set();retirement_ids=set();retry_ids=set()
        for name,blob in rows:
            prefix=next(p for p in (self._jobs._prefix,self._exchange,self._retirement,self._retry) if name.startswith(p))
            job=name[len(prefix):]
            if type(job) is not str or len(job)!=32 or not _hex(job*2):raise TransferError('media_source_catalog_invalid_member')
            bound=self._jobs.MAX_BYTES if prefix==self._jobs._prefix else 262144 if prefix==self._retry else 16384
            if type(blob) is not bytes or not 29<=len(blob)<=bound+28:raise TransferError('media_source_catalog_invalid_member')
            (job_ids if prefix==self._jobs._prefix else exchange_ids if prefix==self._exchange else retirement_ids if prefix==self._retirement else retry_ids).add(job)
            members.append([name,sha256(blob).hexdigest()])
        if len(job_ids)>self._jobs.MAX_RECORDS or not exchange_ids<=job_ids or not retirement_ids<=exchange_ids or not retry_ids<=exchange_ids:
            raise TransferError('media_source_catalog_invalid_member')
        return members

    @staticmethod
    def _signature(value):
        return value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns

    def _anchor_domain(self,key):return self._domain+'anchor/'+str(key[0])+':'+str(key[1])

    def _read_anchor(self,db_key):
        if self._jobs._fresh()!=db_key:raise TransferError('media_source_jobs_original_database_required')
        parent=self._authority.protection._root_fd
        try:fd=os.open(self._anchor_name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
        except FileNotFoundError:
            if self._anchor_identity is not None:raise TransferError('media_source_catalog_original_anchor_required')
            return None
        try:
            before=os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_nlink!=1
                    or before.st_mode&0o077 or not 29<=before.st_size<=8192):
                raise TransferError('media_source_catalog_original_anchor_required')
            key=before.st_dev,before.st_ino;blob=os.pread(fd,before.st_size+1,0)
            after=os.fstat(fd);named=os.stat(self._anchor_name,dir_fd=parent,follow_symlinks=False)
            if (len(blob)!=before.st_size or self._signature(before)!=self._signature(after)
                    or self._signature(named)!=self._signature(after)):
                raise TransferError('media_source_catalog_original_anchor_required')
            plain=self._authority.protection.unseal(blob,self._anchor_domain(key));body=strict_json(plain)
            if (type(body) is not dict or set(body)!={'format','scope','root_key','database_key','anchor_key','nonce'}
                    or type(body['format']) is not int or body['format']!=1 or body['scope']!=self._jobs._scope
                    or body['root_key']!=list(self._authority.protection.native_directory_identity)
                    or body['database_key']!=list(db_key) or body['anchor_key']!=list(key)
                    or not _hex(body['nonce']) or canonical(body)!=plain):
                raise TransferError('media_source_catalog_original_anchor_required')
            witness=dict(key=list(key),sha256=sha256(blob).hexdigest())
            if self._anchor_identity is not None and self._anchor_identity!=witness:
                raise TransferError('media_source_catalog_original_anchor_required')
            self._anchor_identity=witness
            if self._jobs._fresh()!=db_key:raise TransferError('media_source_jobs_original_database_required')
            return witness
        finally:os.close(fd)

    def verify(self,db,db_key):
        members=self._members(db);anchor=self._read_anchor(db_key)
        row=db.execute('SELECT value FROM meta WHERE key=?',(self._key,)).fetchone()
        if row is None:
            if members or anchor is not None or self._observed is not None:
                raise TransferError('media_source_catalog_original_head_required')
            return None
        if anchor is None:raise TransferError('media_source_catalog_original_anchor_required')
        cipher=row[0]
        if type(cipher) is not bytes or not 29<=len(cipher)<=self.MAX_HEAD+28:raise TransferError('media_source_catalog_invalid_head')
        plain=self._authority.protection.unseal(cipher,self._domain+'head');body=strict_json(plain)
        if (type(body) is not dict or set(body)!={'format','scope','database_key','anchor','revision','members'}
                or type(body['format']) is not int or body['format']!=1 or body['scope']!=self._jobs._scope
                or body['database_key']!=list(db_key) or body['anchor']!=anchor
                or type(body['revision']) is not int or not 1<=body['revision']<2**53
                or body['members']!=members or canonical(body)!=plain):raise TransferError('media_source_catalog_membership_changed')
        result=NativeSourceCatalogSnapshot(sha256(cipher).hexdigest(),body);mark=body['revision'],result.version
        if self._observed is not None and (mark[0]<self._observed[0] or mark[0]==self._observed[0] and mark[1]!=self._observed[1]):
            raise TransferError('media_source_catalog_rollback')
        if not db.in_transaction:self.observe(result)
        return result

    def observe(self,result):
        if result is None:return
        mark=result.body['revision'],result.version
        if self._observed is not None and (mark[0]<self._observed[0] or mark[0]==self._observed[0] and mark[1]!=self._observed[1]):
            raise TransferError('media_source_catalog_rollback')
        self._observed=mark

    def _write(self,db,db_key,revision,anchor):
        if not db.in_transaction:raise TransferError('media_source_catalog_transaction_required')
        if type(revision) is not int or not 1<=revision<2**53:raise TransferError('media_source_catalog_capacity')
        body=dict(format=1,scope=self._jobs._scope,database_key=list(db_key),anchor=anchor,revision=revision,members=self._members(db))
        plain=canonical(body)
        if len(plain)>self.MAX_HEAD:raise TransferError('media_source_catalog_capacity')
        cipher=self._authority.protection.seal(plain,self._domain+'head')
        db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(self._key,cipher))
        result=self.verify(db,db_key)
        if result is None or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_catalog_readback_failed')
        return result

    def initialize(self,writer,db,db_key):
        self._jobs._writer(writer)
        if not db.in_transaction or self.verify(db,db_key) is not None:raise TransferError('media_source_catalog_unused_scope_required')
        parent=self._authority.protection._root_fd
        fd=os.open(self._anchor_name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600,dir_fd=parent)
        try:
            value=os.fstat(fd);key=value.st_dev,value.st_ino
            body=dict(format=1,scope=self._jobs._scope,root_key=list(self._authority.protection.native_directory_identity),
                database_key=list(db_key),anchor_key=list(key),nonce=secrets.token_hex(32))
            blob=self._authority.protection.seal(canonical(body),self._anchor_domain(key));offset=0
            while offset<len(blob):
                self._jobs._writer(writer);written=os.write(fd,blob[offset:])
                if written<=0:raise TransferError('media_source_catalog_short_write')
                offset+=written
            os.fsync(fd);os.fsync(parent);self._jobs._writer(writer)
        finally:os.close(fd)
        writer._owner._boundary('source_catalog_anchor_durable');self._jobs._writer(writer)
        anchor=self._read_anchor(db_key)
        if anchor is None:raise TransferError('media_source_catalog_original_anchor_required')
        return self._write(db,db_key,1,anchor)

    def advance(self,db,db_key,expected):
        if type(expected) is not NativeSourceCatalogSnapshot or not db.in_transaction:
            raise TransferError('media_source_catalog_original_head_required')
        row=db.execute('SELECT value FROM meta WHERE key=?',(self._key,)).fetchone()
        if (row is None or sha256(row[0]).hexdigest()!=expected.version or self._read_anchor(db_key)!=expected.body['anchor']):
            raise TransferError('media_source_catalog_original_head_required')
        return self._write(db,db_key,expected.body['revision']+1,expected.body['anchor'])

    def lookup(self):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');result=self.verify(db,key)
        self.observe(result);return result

    def require_free_slot(self,parent,current):
        # Deny-only metadata/layout admission, never archive READ or adoption.
        from magnolie_media_source_retirement import _NativeSourceRetirementJournal,verify_archived_cache
        current();value=os.fstat(parent)
        if (value.st_dev,value.st_ino)!=self._authority.protection.native_directory_identity:
            raise TransferError('media_source_slot_original_parent_required')
        expected=set();journal=_NativeSourceRetirementJournal(self._jobs)
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');catalog=self.verify(db,key)
            members=[] if catalog is None else catalog.body['members']
            versions=dict(members)
            for name,_ in members:
                if not name.startswith(self._jobs._prefix):continue
                current();job=name[len(self._jobs._prefix):];ready=self._jobs._read(db,key,job)
                retired=journal._read(db,key,job)
                if ready is None or ready.state!='cache_ready' or retired is None or retired.body['state']!='archived':
                    raise TransferError('media_source_slot_pending_job')
                body=retired.body
                original=ready.body
                if (body['ready_version']!=ready.version or body['nonce']!=original['nonce'] or body['manifest']!=original['manifest']
                        or body['root_key']!=original['root_key'] or body['parent_key']!=original['parent_key']
                        or body['proof_witness']['sha256']!=original['proof_sha256']
                        or versions.get(self._exchange+job)!=body['exchange_version']):
                    raise TransferError('media_source_slot_original_job_required')
                verify_archived_cache(self._jobs,parent,body,current);expected.add(body['archive'])
        self.observe(catalog);current();prefix='.magnolie-source-'+self._jobs._scope[:32]
        found=set();count=0
        with os.scandir(parent) as entries:
            for entry in entries:
                count+=1
                if count>4096:raise TransferError('media_source_slot_directory_capacity')
                if entry.name.startswith(prefix):found.add(entry.name)
        if found!=expected:raise TransferError('media_source_slot_unknown_stage')
        current()
