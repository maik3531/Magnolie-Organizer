"""Independent, append-only native witness for the relocation database."""
from hashlib import sha256
import os
import struct

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical, strict_json


class RelocationAnchor:
    # Empty, prepared, and up to 128 spent attempts plus 128 outcomes.
    MAX_EVENTS=258
    MAX_EVENT_BYTES=2048
    MAX_BYTES=MAX_EVENTS*(4+MAX_EVENT_BYTES)

    def __init__(self,journal):
        self._journal=journal
        self.name='media-relocation-anchor-v1-'+journal._scope+'.seal'
        self._domain=journal._domain+'independent-anchor'
        self._identity=None

    def _open(self,flags):
        return os.open(self.name,flags|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600,dir_fd=self._journal._parent_fd)

    def _file(self,fd):
        owner=self._journal
        actual=os.fstat(fd);owner._private(actual)
        named=os.stat(self.name,dir_fd=owner._parent_fd,follow_symlinks=False);owner._private(named)
        key=owner._key(actual)
        if (key!=owner._key(named) or self._identity is not None and key!=self._identity
                or not 0<=actual.st_size<=self.MAX_BYTES):
            raise TransferError('photo_relocation_original_anchor_changed')
        return key,actual.st_size,actual.st_mtime_ns,actual.st_ctime_ns

    def _store_identity(self):
        owner=self._journal
        return [list(key) for key in (owner._root_key,owner._db_key,owner._lock_key)]

    @staticmethod
    def _checkpoint(snapshot):
        return (snapshot.version,snapshot.outcome_version,len(snapshot.records),len(snapshot.attempts),len(snapshot.outcomes))

    def _read(self,fd):
        stamp=self._file(fd);data=os.pread(fd,stamp[1]+1,0)
        if self._file(fd)!=stamp or len(data)!=stamp[1]:raise TransferError('photo_relocation_original_anchor_changed')
        owner=self._journal;offset=0;previous=None;digest=None
        for index in range(self.MAX_EVENTS):
            if offset==len(data):break
            if len(data)-offset<4:raise TransferError('photo_relocation_original_anchor_incomplete')
            length=struct.unpack_from('>I',data,offset)[0];offset+=4
            if not 28<=length<=self.MAX_EVENT_BYTES or offset+length>len(data):
                raise TransferError('photo_relocation_original_anchor_incomplete')
            blob=data[offset:offset+length];offset+=length
            plain=owner._protection().unseal(blob,self._domain)
            event=strict_json(plain)
            if (type(event) is not dict or set(event)!={'format','store','index','previous','checkpoint'}
                    or type(event['format']) is not int or event['format']!=1 or event['store']!=self._store_identity()
                    or type(event['index']) is not int or event['index']!=index or event['previous']!=digest or canonical(event)!=plain
                    or type(event['checkpoint']) is not list or len(event['checkpoint'])!=5):
                raise TransferError('photo_relocation_original_anchor_changed')
            checkpoint=tuple(event['checkpoint'])
            self._transition(previous,checkpoint,index)
            previous=checkpoint;digest=sha256(blob).hexdigest()
        if offset!=len(data):raise TransferError('photo_relocation_original_anchor_changed')
        self._identity=stamp[0]
        return previous,digest

    def _transition(self,before,after,index):
        version,head,records,attempts,outcomes=after
        if (not _hex(version) or not _hex(head) or any(type(value) is not int for value in (records,attempts,outcomes))
                or not 0<=max(attempts,outcomes)<=records<=self._journal.MAX_MEMBERS or min(attempts,outcomes)<0):
            raise TransferError('photo_relocation_invalid_anchor_checkpoint')
        if index==0:
            valid=before is None and records==attempts==outcomes==0 and version==self._journal._absent
        elif index==1:
            valid=before is not None and before[2:]==(0,0,0) and records>0 and attempts==outcomes==0 and version!=before[0] and head!=before[1]
        else:
            valid=(before is not None and version==before[0] and head!=before[1] and records==before[2]
                and (attempts-before[3],outcomes-before[4]) in ((1,0),(0,1)) and attempts+outcomes==index-1)
        if not valid:raise TransferError('photo_relocation_invalid_anchor_checkpoint')

    def _append(self,fd,before,digest,checkpoint):
        index=0 if before is None else 1 if before[2]==0 else before[3]+before[4]+2
        self._transition(before,checkpoint,index)
        blob=self._journal._protection().seal(canonical(dict(format=1,store=self._store_identity(),index=index,
            previous=digest,checkpoint=list(checkpoint))),self._domain)
        if not 28<=len(blob)<=self.MAX_EVENT_BYTES:raise TransferError('photo_relocation_invalid_anchor_checkpoint')
        entry=struct.pack('>I',len(blob))+blob
        if self._file(fd)[1]+len(entry)>self.MAX_BYTES or os.write(fd,entry)!=len(entry):
            raise TransferError('photo_relocation_original_anchor_incomplete')
        os.fsync(fd)
        if self._read(fd)!=(checkpoint,sha256(blob).hexdigest()):
            raise TransferError('photo_relocation_original_anchor_changed')

    def create(self,snapshot):
        fd=self._open(os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_EXCL)
        try:
            self._append(fd,None,None,self._checkpoint(snapshot))
            os.fsync(self._journal._parent_fd)
        finally:os.close(fd)

    def require(self,snapshot):
        fd=self._open(os.O_RDONLY)
        try:previous,_=self._read(fd)
        finally:os.close(fd)
        if previous!=self._checkpoint(snapshot):raise TransferError('photo_relocation_anchor_journal_mismatch')

    def append(self,expected,checkpoint):
        fd=self._open(os.O_RDWR|os.O_APPEND)
        try:
            previous,digest=self._read(fd)
            if previous!=self._checkpoint(expected):raise TransferError('photo_relocation_anchor_journal_mismatch')
            self._append(fd,previous,digest,checkpoint)
        finally:os.close(fd)
