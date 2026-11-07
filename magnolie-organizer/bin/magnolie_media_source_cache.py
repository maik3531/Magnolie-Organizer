"""One bounded native PC source-cache builder (#338), never upload authority.

Only NativeMappedMediaSource invokes this while its actual source descriptor,
consent/action/intent and saved-book IO lease remain held. Existing stages always
HOLD, including completed ones: restart adoption, retirement and sender READ
require a separate native source-job lifecycle, not a guessed filename.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import secrets
import stat

from magnolie_file_transfer import FileManifest,ManifestFile,CHUNK_BYTES,MAX_FILE_BYTES,MAX_TOTAL_BYTES,TransferError
from magnolie_telefon import canonical,strict_json


@dataclass(frozen=True)
class FrozenNativeMediaSource:
    directory: Path
    manifest: FileManifest
    root_key: tuple
    proof_sha256: str
    _references: tuple
    _book_version: str

    @property
    def original_references(self):return {file_id:dict(fields) for file_id,fields in self._references}
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def proves_deletion(self):return False


class _NativeSourceCacheWriter:
    MAX_METADATA=65536

    def __init__(self,owner,mapping,size,signature,token,expected,kind,book_version,current):
        from magnolie_media_source import NativeMappedMediaSource
        if type(owner) is not NativeMappedMediaSource or not owner._gate.locked() or not callable(current):
            raise TransferError('media_source_cache_live_owner_required')
        self._owner=owner;self._authority=owner._authority;self._current=current;self._parent=self._root=None
        self._size=size;self._count=(size+CHUNK_BYTES-1)//CHUNK_BYTES;self._next=0;self._members=sha256();self._metadata={}
        from magnolie_file_control import _hex
        if not _hex(book_version):raise TransferError('media_source_cache_book_required')
        self._book_version=book_version
        if not 1<=size<=min(MAX_FILE_BYTES,MAX_TOTAL_BYTES):raise TransferError('media_source_cache_size_limit')
        peer=self._authority.current_peer()
        if peer is None:raise TransferError('media_source_cache_native_owner_required')
        self._scope=sha256(canonical(dict(local_id=self._authority.identity.receiver_id,
            local_key=self._authority.identity.receiver_identity_sha256,peer_id=peer.peer_id,peer_key=peer.identity_sha256))).hexdigest()
        self._name='.magnolie-source-'+self._scope[:32]+'.part'
        self._directory=Path(self._authority.binding.native_directory)
        self._job=secrets.token_hex(16);self._file=secrets.token_hex(16);self._reference=mapping.phone_original_reference()
        self._path=mapping.relative_path.rsplit('/',1)[-1]
        try:
            current()
            self._parent=os.open(self._directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            self._parent_key=self._key(os.fstat(self._parent));self._private(os.fstat(self._parent),directory=True)
            block=max(4096,os.fstatvfs(self._parent).f_frsize)
            budget=self._count*((CHUNK_BYTES+28+block-1)//block*block)+4*self.MAX_METADATA
            free=os.fstatvfs(self._parent)
            if free.f_bavail*free.f_frsize<budget+1024**3:raise TransferError('media_source_cache_insufficient_space')
            current()
            try:os.mkdir(self._name,mode=0o700,dir_fd=self._parent)
            except FileExistsError:raise TransferError('media_source_cache_existing_hold')
            self._root=os.open(self._name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self._parent)
            self._root_key=self._key(os.fstat(self._root));self._guard();os.fsync(self._parent)
            intent=dict(format=2,state='planned',job_id=self._job,file_id=self._file,scope=self._scope,book_version=book_version,
                parent_key=list(self._parent_key),root_key=list(self._root_key),size=size,chunks=self._count,media_type=kind,
                source_signature=list(signature),original_mapping_sha256=mapping.protected_record_sha256,
                original_reference=self._reference,source_policy_sha256=expected.version,pairing_epoch=peer.pairing_epoch,
                media_intent_sha256=sha256(canonical(token.body)).hexdigest(),source_path=mapping.relative_path)
            self._intent_sha256=sha256(canonical(intent)).hexdigest()
            self._metadata['intent.enc']=self._write('intent.enc',canonical(intent))
            self._owner._boundary('source_cache_intent_durable');self._guard()
            self._metadata['copying.enc']=self._write('copying.enc',canonical(dict(format=2,state='copying',intent_sha256=self._intent_sha256)))
            self._guard()
        except BaseException:
            self.close();raise

    @staticmethod
    def _key(value):return value.st_dev,value.st_ino

    @staticmethod
    def _signature(value):return value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns

    @staticmethod
    def _private(value,*,directory=False):
        if (value.st_uid!=os.geteuid() or value.st_mode&0o077 or not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
                or not directory and value.st_nlink!=1):raise TransferError('media_source_cache_unsafe_entry')

    def _guard(self):
        self._current()
        parent=os.fstat(self._parent);named_parent=os.stat(self._directory,follow_symlinks=False)
        root=os.fstat(self._root);named=os.stat(self._name,dir_fd=self._parent,follow_symlinks=False)
        for value in (parent,named_parent,root,named):self._private(value,directory=True)
        if self._key(parent)!=self._parent_key or self._key(named_parent)!=self._parent_key or self._key(root)!=self._root_key or self._key(named)!=self._root_key:
            raise TransferError('media_source_cache_directory_changed')

    def _domain(self,name,key):
        return 'native-media-source-cache-v1/'+self._scope+'/'+str(self._root_key[0])+':'+str(self._root_key[1])+'/'+name+'/'+str(key[0])+':'+str(key[1])

    def _write(self,name,plain):
        if not 1<=len(plain)<=CHUNK_BYTES:raise TransferError('media_source_cache_record_size_limit')
        self._guard()
        fd=os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600,dir_fd=self._root)
        try:
            before=os.fstat(fd);self._private(before);key=self._key(before)
            cipher=self._authority.protection.seal(bytes(plain),self._domain(name,key));offset=0
            if len(cipher)!=len(plain)+28:raise TransferError('media_source_cache_cipher_invalid')
            while offset<len(cipher):
                self._guard();written=os.write(fd,cipher[offset:])
                if written<=0:raise TransferError('media_source_cache_short_write')
                offset+=written
            os.fsync(fd);self._guard()
            witness=dict(key=list(key),sha256=sha256(cipher).hexdigest(),size=len(cipher))
        finally:os.close(fd)
        os.fsync(self._root)
        decoded=self._read(name,witness)
        if decoded!=bytes(plain):raise TransferError('media_source_cache_readback_changed')
        self._guard();return witness

    def _read(self,name,witness):
        self._guard();fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._root)
        try:
            before=os.fstat(fd);self._private(before)
            if list(self._key(before))!=witness['key'] or before.st_size!=witness['size'] or not 28<=before.st_size<=CHUNK_BYTES+28:
                raise TransferError('media_source_cache_original_member_required')
            cipher=os.pread(fd,before.st_size+1,0)
            after=os.fstat(fd);named=os.stat(name,dir_fd=self._root,follow_symlinks=False)
            if (len(cipher)!=before.st_size or self._signature(before)!=self._signature(after) or self._signature(named)!=self._signature(after)
                    or sha256(cipher).hexdigest()!=witness['sha256']):raise TransferError('media_source_cache_original_member_required')
            result=self._authority.protection.unseal(cipher,self._domain(name,self._key(after)));self._guard();return result
        finally:os.close(fd)

    def chunk(self,index,data):
        wanted=min(CHUNK_BYTES,self._size-index*CHUNK_BYTES)
        if index!=self._next or not 0<=index<self._count or len(data)!=wanted:raise TransferError('media_source_cache_chunk_order')
        witness=self._write('chunk-%08x.enc'%index,data)
        self._members.update(canonical(dict(index=index,**witness)));self._next+=1
        self._owner._boundary('source_cache_chunk_durable');self._guard()

    def finish(self,digest):
        if self._next!=self._count:raise TransferError('media_source_cache_incomplete')
        members=sha256();raw=sha256()
        for name,witness in self._metadata.items():
            body=strict_json(self._read(name,witness))
            if body['state']!=('planned' if name=='intent.enc' else 'copying'):raise TransferError('media_source_cache_intent_changed')
        for index in range(self._count):
            self._guard();name='chunk-%08x.enc'%index
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._root)
            try:
                value=os.fstat(fd);self._private(value)
                expected=min(CHUNK_BYTES,self._size-index*CHUNK_BYTES)+28
                if value.st_size!=expected:raise TransferError('media_source_cache_original_member_required')
                cipher=os.pread(fd,expected+1,0)
                if len(cipher)!=expected:raise TransferError('media_source_cache_original_member_required')
                witness=dict(key=list(self._key(value)),sha256=sha256(cipher).hexdigest(),size=expected)
            finally:os.close(fd)
            plain=bytearray(self._read(name,witness))
            try:raw.update(plain)
            finally:plain[:]=b'\0'*len(plain)
            members.update(canonical(dict(index=index,**witness)))
        if members.digest()!=self._members.digest() or raw.hexdigest()!=digest:raise TransferError('media_source_cache_final_digest_changed')
        expected_names={'intent.enc','copying.enc'}|{'chunk-%08x.enc'%index for index in range(self._count)}
        if set(os.listdir(self._root))!=expected_names:raise TransferError('media_source_cache_unknown_entry')
        manifest=FileManifest(secrets.token_hex(16),self._job,self._authority.identity.receiver_id,self._authority.binding.peer_id,
            (ManifestFile(self._file,self._path,self._size,digest),),self._size)
        proof=dict(format=2,state='sealed',intent_sha256=self._intent_sha256,book_version=self._book_version,manifest=manifest.wire(),
            chunks_sha256=members.hexdigest(),chunk_count=self._count,metadata=self._metadata,
            original_references={self._file:self._reference})
        witness=self._write('manifest.enc',canonical(proof));self._guard()
        if set(os.listdir(self._root))!=expected_names|{'manifest.enc'}:raise TransferError('media_source_cache_unknown_entry')
        self._owner._boundary('source_cache_sealed_durable');self._guard()
        return FrozenNativeMediaSource(self._directory/self._name,manifest,self._root_key,witness['sha256'],
            ((self._file,tuple(sorted(self._reference.items()))),),self._book_version)

    def close(self):
        for name in ('_root','_parent'):
            fd=getattr(self,name,None)
            if fd is not None:os.close(fd);setattr(self,name,None)

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
