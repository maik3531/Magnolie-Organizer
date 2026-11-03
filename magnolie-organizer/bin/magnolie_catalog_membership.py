"""Authenticated transactional catalog membership; no automatic legacy upgrade."""
from hashlib import sha256
import json
import os
import sqlite3

from magnolie_file_transfer import TransferError


class CatalogMembership:
    NAME='membership.sqlite'
    MAX_BYTES=512*1024
    SCHEMA='CREATE TABLE head (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)'

    def __init__(self,catalog,*,create=False):
        self.catalog=catalog;self.fd=None;self.db=None;self.last=None;self.uncertain=False
        try:
            flags=os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK
            if create:flags|=os.O_CREAT|os.O_EXCL
            self.fd=os.open(self.NAME,flags,0o600,dir_fd=catalog._root_fd)
            self.key=catalog._key(os.fstat(self.fd));self.fresh()
            if not create:
                for suffix in ('-journal','-wal','-shm'):
                    try:os.stat(self.NAME+suffix,dir_fd=catalog._root_fd,follow_symlinks=False)
                    except FileNotFoundError:continue
                    raise TransferError('file_job_catalog_membership_journal_preserved')
            path=catalog._parent/catalog.NAME/self.NAME
            self.db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=5,check_same_thread=False)
            self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA busy_timeout=5000')
            if create:
                self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA max_page_count=128')
                with self.db:self.db.execute(self.SCHEMA);self.db.execute('PRAGMA user_version=1')
        except BaseException:self.close();raise

    def fresh(self):
        c=self.catalog;c._directories()
        named=os.stat(self.NAME,dir_fd=c._root_fd,follow_symlinks=False);opened=os.fstat(self.fd)
        c._private(named);c._private(opened)
        if c._key(named)!=self.key or c._key(opened)!=self.key or opened.st_size>self.MAX_BYTES:
            raise TransferError('file_job_catalog_membership_original_changed')
        if getattr(c,'_registry_key',None) is not None and self.key!=c._registry_key:
            raise TransferError('file_job_catalog_membership_original_changed')

    def schema(self):
        self.fresh()
        if (dict(self.db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))!={'head':self.SCHEMA}
                or self.db.execute('PRAGMA user_version').fetchone()!=(1,)
                or self.db.execute('PRAGMA journal_mode').fetchone()!=('delete',)
                or self.db.execute('PRAGMA synchronous').fetchone()!=(2,)
                or self.db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]):
            raise TransferError('file_job_catalog_membership_invalid_schema')

    def signature(self,jobs):
        return sha256(self.catalog._json([dict(owner=j.owner,digest=j.protected_record_sha256,reserved_bytes=j.reserved_bytes)
            for j in sorted(jobs,key=lambda j:j.owner)])).hexdigest()

    def value(self,jobs,revision):
        c=self.catalog
        return dict(format=1,root_key=list(c._root_key),database_key=list(self.key),owner_sha256=c._known['owner.enc'][1],
            revision=revision,count=len(jobs),reserved_bytes=sum(j.reserved_bytes for j in jobs),members_sha256=self.signature(jobs))

    def read(self,jobs):
        if self.uncertain:raise TransferError('file_job_catalog_membership_repair_pending')
        self.schema();rows=self.db.execute('SELECT id,payload FROM head').fetchall()
        if len(rows)!=1 or rows[0][0]!=1:raise TransferError('file_job_catalog_membership_head_required')
        blob=rows[0][1]
        if type(blob) is not bytes or not 28<=len(blob)<=8192:raise TransferError('file_job_catalog_membership_invalid_head')
        raw=self.catalog._unseal(blob,self.catalog._domain+'membership-head');value=json.loads(raw)
        revision=value.get('revision') if type(value) is dict else None
        if type(revision) is not int or not 1<=revision<2**63 or value!=self.value(jobs,revision) or self.catalog._json(self.value(jobs,revision))!=raw:
            raise TransferError('file_job_catalog_membership_changed')
        mark=(revision,sha256(blob).hexdigest())
        if self.last is not None and (revision<self.last[0] or revision==self.last[0] and mark!=self.last):
            raise TransferError('file_job_catalog_membership_rollback')
        self.last=mark;self.fresh();return mark

    def commit(self,jobs,expected,*,validate=lambda:None):
        self.schema();validate()
        if expected is None:
            if self.db.execute('SELECT count(*) FROM head').fetchone()!=(0,):raise TransferError('file_job_catalog_membership_exists')
            revision=1
        else:
            if self.last!=expected:raise TransferError('file_job_catalog_membership_cas_changed')
            revision=expected[0]+1
        value=self.value(jobs,revision)
        blob=self.catalog._seal(self.catalog._json(value),self.catalog._domain+'membership-head')
        if type(blob) is not bytes or not 28<=len(blob)<=8192:raise TransferError('file_job_catalog_membership_invalid_protection')
        self.fresh();validate();self.uncertain=True
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT OR REPLACE INTO head VALUES(1,?)',(blob,))
            self.fresh();validate()
        os.fsync(self.fd);os.fsync(self.catalog._root_fd);self.fresh();validate()
        self.uncertain=False
        try:
            result=self.read(jobs)
            if result!=(revision,sha256(blob).hexdigest()):raise TransferError('file_job_catalog_membership_readback_failed')
            return result
        except BaseException:self.uncertain=True;raise

    def close(self):
        if self.db is not None:self.db.close();self.db=None
        if self.fd is not None:os.close(self.fd);self.fd=None
