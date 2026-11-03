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
    ATTEMPTS_SCHEMA='CREATE TABLE publication_attempts (owner TEXT NOT NULL, revision INTEGER NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(owner,revision))'
    MAX_ATTEMPTS=256

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
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        wanted={'head':self.SCHEMA} if version==1 else {'head':self.SCHEMA,'publication_attempts':self.ATTEMPTS_SCHEMA} if version==2 else None
        if (wanted is None or dict(self.db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))!=wanted
                or self.db.execute('PRAGMA journal_mode').fetchone()!=('delete',)
                or self.db.execute('PRAGMA synchronous').fetchone()!=(2,)
                or self.db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]):
            raise TransferError('file_job_catalog_membership_invalid_schema')
        self.version=version

    def attempts(self,jobs):
        """Authenticated history only. No parsed record grants publication."""
        if self.version==1:return ()
        known={job.owner:job for job in jobs};last={};records=[]
        rows=self.db.execute('SELECT owner,revision,payload FROM publication_attempts ORDER BY owner,revision LIMIT ?',
            (self.MAX_ATTEMPTS+1,)).fetchall()
        if len(rows)>self.MAX_ATTEMPTS:raise TransferError('file_job_catalog_publication_history_limit')
        for owner,revision,blob in rows:
            if (owner not in known or type(revision) is not int or type(blob) is not bytes or not 28<=len(blob)<=2048):
                raise TransferError('file_job_catalog_invalid_publication_history')
            raw=self.catalog._unseal(blob,self.catalog._domain+'publication-attempt/'+owner+'/'+str(revision))
            value=json.loads(raw);previous=last.get(owner)
            if (type(value) is not dict or set(value)!={'format','owner','revision','previous','operation','evidence'}
                    or type(value['format']) is not int or value['format']!=1 or value['owner']!=owner
                    or type(value['revision']) is not int or value['revision']!=revision
                    or revision!=(previous[0]['revision']+1 if previous else 1)
                    or value['previous']!=(previous[1] if previous else '') or self.catalog._json(value)!=raw):
                raise TransferError('file_job_catalog_invalid_publication_history')
            operation=value['operation'];evidence=value['evidence'];accepted=known[owner].accepted
            if operation=='closed':
                self.validate_end(evidence,known[owner])
                if previous is not None and previous[0]['operation']!='consumed':
                    raise TransferError('file_job_catalog_publication_history_order')
            elif operation=='consumed':
                if (previous is None or previous[0]['operation']!='closed' or type(evidence) is not dict
                        or evidence!={'accepted_sha256':accepted.fingerprint,'closed_sha256':previous[1]}):
                    raise TransferError('file_job_catalog_publication_history_order')
            else:raise TransferError('file_job_catalog_invalid_publication_history')
            item=(value,sha256(blob).hexdigest());last[owner]=item;records.append(item)
        if len(records)+sum(item[0]['operation']=='closed' for item in last.values())>self.MAX_ATTEMPTS:
            raise TransferError('file_job_catalog_publication_history_limit')
        self.fresh();return tuple(records)

    @staticmethod
    def validate_end(value,job):
        import re
        if (type(value) is not dict or set(value)!={'accepted_sha256','checkpoint_sha256','index_key','database_key',
                'stage_key','journal_key','publication_key'} or value['accepted_sha256']!=job.accepted.fingerprint
                or type(value['checkpoint_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',value['checkpoint_sha256']) is None):
            raise TransferError('file_job_catalog_invalid_publication_end')
        for name in ('index_key','database_key','stage_key','journal_key','publication_key'):
            key=value[name]
            if (type(key) is not list or len(key)!=2 or any(type(number) is not int or not 0<=number<2**64 for number in key)
                    or key[1]==0):raise TransferError('file_job_catalog_invalid_publication_end')

    def signature(self,jobs):
        members=[dict(owner=j.owner,digest=j.protected_record_sha256,reserved_bytes=j.reserved_bytes,
            **({'cache_retirement_sha256': j.cache_retirement_sha256} if j.cache_retirement_sha256 is not None else {}))
            for j in sorted(jobs,key=lambda j:j.owner)]
        if self.version==2:
            members=dict(jobs=members,publication_attempts=[digest for _,digest in self.attempts(jobs)])
        return sha256(self.catalog._json(members)).hexdigest()

    def value(self,jobs,revision):
        c=self.catalog
        return dict(format=self.version,root_key=list(c._root_key),database_key=list(self.key),owner_sha256=c._known['owner.enc'][1],
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

    def append_attempt(self,jobs,job,operation,evidence,*,validate):
        """Native caller already proved actual owner END, or an exact renewal.

        The optional table and new signed membership head commit atomically in
        the SAME existing bounded database. No absent-state bootstrap on resume.
        """
        expected=self.read(jobs);records=self.attempts(jobs)
        previous=next((item for item in reversed(records) if item[0]['owner']==job.owner),None)
        if operation=='closed' and previous is not None and previous[0]['operation']=='closed' and previous[0]['evidence']==evidence:
            return previous[1]
        if len(records)>=self.MAX_ATTEMPTS:raise TransferError('file_job_catalog_publication_history_limit')
        if operation=='closed':
            latest={record['owner']:record['operation'] for record,_ in records}
            if len(records)+sum(state=='closed' for state in latest.values())+2>self.MAX_ATTEMPTS:
                raise TransferError('file_job_catalog_publication_history_limit')
        value=dict(format=1,owner=job.owner,revision=previous[0]['revision']+1 if previous else 1,
            previous=previous[1] if previous else '',operation=operation,evidence=evidence)
        blob=self.catalog._seal(self.catalog._json(value),self.catalog._domain+'publication-attempt/'+job.owner+'/'+str(value['revision']))
        if type(blob) is not bytes or not 28<=len(blob)<=2048:raise TransferError('file_job_catalog_invalid_publication_history')
        validate();self.fresh();self.uncertain=True
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.last!=expected:raise TransferError('file_job_catalog_membership_cas_changed')
            original=self.db.execute('SELECT payload FROM head WHERE id=1').fetchone()
            if original is None or type(original[0]) is not bytes or sha256(original[0]).hexdigest()!=expected[1]:
                raise TransferError('file_job_catalog_membership_cas_changed')
            if self.version==1:
                self.db.execute(self.ATTEMPTS_SCHEMA);self.db.execute('PRAGMA user_version=2');self.version=2
            self.db.execute('INSERT INTO publication_attempts VALUES(?,?,?)',(job.owner,value['revision'],blob))
            head=self.catalog._seal(self.catalog._json(self.value(jobs,expected[0]+1)),self.catalog._domain+'membership-head')
            if type(head) is not bytes or not 28<=len(head)<=8192:raise TransferError('file_job_catalog_membership_invalid_head')
            self.db.execute('UPDATE head SET payload=? WHERE id=1',(head,));self.fresh();validate()
        os.fsync(self.fd);os.fsync(self.catalog._root_fd);self.fresh();validate()
        self.uncertain=False
        try:
            self.read(jobs)
            if not any(record==value and digest==sha256(blob).hexdigest() for record,digest in self.attempts(jobs)):
                raise TransferError('file_job_catalog_publication_readback_failed')
            return sha256(blob).hexdigest()
        except BaseException:self.uncertain=True;raise

    def close(self):
        if self.db is not None:self.db.close();self.db=None
        if self.fd is not None:os.close(self.fd);self.fd=None
