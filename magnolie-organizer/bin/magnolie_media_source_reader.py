"""Read-only native prepared-cache lease (#338), not transfer authority.

Only an actual in-process source preparation and the owning thread's live
book/action/consent/intent lease can open these descriptors. Frozen metadata,
sealed filenames and a newly constructed source owner never grant READ.
"""
from hashlib import sha256
from pathlib import Path
import os
import stat
import threading

from magnolie_file_transfer import FileManifest,CHUNK_BYTES,TransferError
from magnolie_telefon import canonical,strict_json


class _NativeSourceCacheReader:
    def __init__(self,owner,job_id):
        from magnolie_media_source_pc import native_source_kind,_NativePcSelection
        self._local=native_source_kind(owner)=='collection';self._format=3 if self._local else 2
        self._owner=owner;self._permit=getattr(owner._cache_scope,'permit',None)
        if self._permit is None or self._permit[0]!=job_id or owner._prepared.get(job_id) is not self._permit[1]:
            raise TransferError('media_source_cache_live_lease_required')
        self._prepared=self._permit[1];self._cache=self._prepared.cache;self._authority=owner._authority
        if self._local:
            if type(self._cache._pc_selection) is not _NativePcSelection or self._cache.original_references!={}:
                raise TransferError('media_collection_cache_original_selection_required')
        elif self._cache._pc_selection is not None:raise TransferError('media_source_cache_original_mapping_required')
        from magnolie_media_source_jobs import _NativeSourceJobs
        self._jobs=_NativeSourceJobs(self._authority)
        self._parent=self._root=None;self._closed=threading.Event();self._chunks=[]
        try:
            self._permission();peer=self._authority.current_peer()
            if peer is None:raise TransferError('media_source_cache_native_owner_required')
            self._scope=sha256(canonical(dict(local_id=self._authority.identity.receiver_id,
                local_key=self._authority.identity.receiver_identity_sha256,peer_id=peer.peer_id,peer_key=peer.identity_sha256))).hexdigest()
            self._directory=Path(self._authority.binding.native_directory);self._name='.magnolie-source-'+self._scope[:32]+'.part'
            if self._cache.directory!=self._directory/self._name:raise TransferError('media_source_cache_original_directory_required')
            self._parent=os.open(self._directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            self._parent_key=self._key(os.fstat(self._parent))
            self._root=os.open(self._name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self._parent)
            self._guard()
            proof,proof_witness=self._metadata('manifest.enc')
            if proof_witness['sha256']!=self._cache.proof_sha256:raise TransferError('media_source_cache_original_proof_required')
            if (set(proof)!={'format','state','intent_sha256','job_nonce','book_version','manifest','chunks_sha256','chunk_count','metadata','original_references'} | ({'local_origin','root_catalog','media_type'} if self._local else set())
                    or type(proof['format']) is not int or proof['format']!=self._format or proof['state']!='sealed'
                    or proof['book_version']!=self._prepared.book_version or proof['book_version']!=self._cache._book_version
                    or proof['job_nonce']!=self._cache._job_nonce
                    or FileManifest.parse(proof['manifest'])!=self._cache.manifest
                    or proof['original_references']!=self._cache.original_references):
                raise TransferError('media_source_cache_original_proof_required')
            if self._local and (proof['local_origin']!=self._cache.pc_origin or proof['root_catalog']!=self._cache._pc_selection.catalog
                    or proof['media_type']!=self._cache._media_type):
                raise TransferError('media_collection_cache_original_selection_required')
            self._manifest=self._cache.manifest
            if len(self._manifest.files)!=1:raise TransferError('media_source_cache_manifest_scope_required')
            self._count=self._manifest.files[0].chunks
            if type(proof['chunk_count']) is not int or proof['chunk_count']!=self._count:
                raise TransferError('media_source_cache_original_proof_required')
            metadata=proof['metadata']
            if type(metadata) is not dict or set(metadata)!={'intent.enc','copying.enc'}:
                raise TransferError('media_source_cache_original_proof_required')
            intent,_=self._metadata('intent.enc',metadata['intent.enc']);copying,_=self._metadata('copying.enc',metadata['copying.enc'])
            if (type(intent.get('format')) is not int or intent['format']!=self._format or intent.get('state')!='planned' or intent.get('scope')!=self._scope
                    or intent.get('job_id')!=job_id or intent.get('file_id')!=self._manifest.files[0].id
                    or intent.get('job_nonce')!=self._cache._job_nonce
                    or intent.get('size')!=self._manifest.total_bytes or intent.get('chunks')!=self._count
                    or intent.get('book_version')!=self._prepared.book_version
                    or intent.get('parent_key')!=list(self._parent_key) or intent.get('root_key')!=list(self._cache.root_key)
                    or sha256(canonical(intent)).hexdigest()!=proof['intent_sha256']
                    or copying!=dict(format=self._format,state='copying',intent_sha256=proof['intent_sha256'])):
                raise TransferError('media_source_cache_original_intent_required')
            if self._local and (set(intent)!={'format','state','job_id','job_nonce','file_id','scope','book_version','parent_key','root_key',
                    'size','chunks','media_type','source_signature','source_policy_sha256','pairing_epoch','media_intent_sha256','source_path','local_origin','root_catalog'}
                    or intent['local_origin']!=self._cache.pc_origin or intent['root_catalog']!=self._cache._pc_selection.catalog
                    or intent['media_type']!=self._cache._media_type or intent['source_path']!=self._cache._pc_selection.path):
                raise TransferError('media_collection_cache_original_selection_required')
            record=self._jobs.require_version(job_id,self._cache._job_version).body
            if (record['intent_sha256']!=proof['intent_sha256'] or record['parent_key']!=list(self._parent_key)):
                raise TransferError('media_source_jobs_ready_record_required')
            self._proof_witness=proof_witness;self._metadata_witnesses=metadata;self._members_sha256=proof['chunks_sha256']
            self.media_intent_sha256=intent['media_intent_sha256']
            self._names={'intent.enc','copying.enc','manifest.enc'}|{'chunk-%08x.enc'%index for index in range(self._count)}
            self._layout();members=sha256()
            for index in range(self._count):
                _,witness=self._cipher('chunk-%08x.enc'%index)
                expected=min(CHUNK_BYTES,self._manifest.total_bytes-index*CHUNK_BYTES)+28
                if witness['size']!=expected:raise TransferError('media_source_cache_original_member_required')
                members.update(canonical(dict(index=index,**witness)));self._chunks.append(witness)
            if members.hexdigest()!=self._members_sha256:raise TransferError('media_source_cache_membership_changed')
            self._guard();self._layout()
        except BaseException:
            self._close_owned();raise

    @staticmethod
    def _key(value):return value.st_dev,value.st_ino
    @staticmethod
    def _signature(value):return value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns
    @staticmethod
    def _private(value,*,directory=False):
        if (value.st_uid!=os.geteuid() or value.st_mode&0o077 or not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
                or not directory and value.st_nlink!=1):raise TransferError('media_source_cache_unsafe_entry')

    def _permission(self):
        if (self._closed.is_set() or getattr(self._owner._cache_scope,'permit',None) is not self._permit
                or self._permit[3]!=threading.get_ident()):raise TransferError('media_source_cache_live_lease_required')
        self._permit[2]()
        record=self._jobs.require_version(self._cache.manifest.source_id,self._cache._job_version).body
        if (record['nonce']!=self._cache._job_nonce or record['book_version']!=self._prepared.book_version
                or record['root_key']!=list(self._cache.root_key) or record['manifest']!=self._cache.manifest.wire()
                or record['proof_sha256']!=self._cache.proof_sha256 or record['original_references']!=self._cache.original_references):
            raise TransferError('media_source_jobs_ready_record_required')
        if self._local and (record['format']!=3 or record['local_origin']!=self._cache.pc_origin
                or record['root_catalog']!=self._cache._pc_selection.catalog or record['media_type']!=self._cache._media_type):
            raise TransferError('media_collection_cache_original_selection_required')
        self._permit[2]()

    def _guard(self):
        self._permission()
        for value,key in ((os.fstat(self._parent),self._parent_key),(os.stat(self._directory,follow_symlinks=False),self._parent_key),
                (os.fstat(self._root),self._cache.root_key),(os.stat(self._name,dir_fd=self._parent,follow_symlinks=False),self._cache.root_key)):
            self._private(value,directory=True)
            if self._key(value)!=key:raise TransferError('media_source_cache_directory_changed')

    def _layout(self):
        self._guard()
        if set(os.listdir(self._root))!=self._names:raise TransferError('media_source_cache_unknown_entry')

    def _domain(self,name,key):
        return 'native-media-source-cache-v1/'+self._scope+'/'+str(self._cache.root_key[0])+':'+str(self._cache.root_key[1])+'/'+name+'/'+str(key[0])+':'+str(key[1])

    def _cipher(self,name,expected=None):
        self._guard();fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._root)
        try:
            before=os.fstat(fd);self._private(before)
            if not 29<=before.st_size<=CHUNK_BYTES+28:raise TransferError('media_source_cache_original_member_required')
            cipher=os.pread(fd,before.st_size+1,0)
            self._owner._boundary('source_cache_cipher_read');self._guard()
            after=os.fstat(fd);named=os.stat(name,dir_fd=self._root,follow_symlinks=False)
            witness=dict(key=list(self._key(after)),sha256=sha256(cipher).hexdigest(),size=len(cipher))
            if (len(cipher)!=before.st_size or self._signature(before)!=self._signature(after) or self._signature(named)!=self._signature(after)
                    or expected is not None and witness!=expected):raise TransferError('media_source_cache_original_member_required')
            return cipher,witness
        finally:os.close(fd)

    def _plain(self,name,witness=None):
        cipher,actual=self._cipher(name,witness)
        plain=self._authority.protection.unseal(cipher,self._domain(name,actual['key']));self._guard()
        return plain,actual

    def _metadata(self,name,witness=None):
        plain,actual=self._plain(name,witness);body=strict_json(plain)
        if type(body) is not dict or canonical(body)!=plain:raise TransferError('media_source_cache_invalid_metadata')
        return body,actual

    @property
    def manifest(self):self._permission();return self._manifest

    def read_chunk(self,index):
        self._permission()
        if type(index) is not int or not 0<=index<self._count:raise TransferError('media_source_cache_invalid_chunk')
        self._layout();plain,_=self._plain('chunk-%08x.enc'%index,self._chunks[index]);self._layout();return plain

    def verify(self):
        self._layout();self._metadata('manifest.enc',self._proof_witness)
        for name,witness in self._metadata_witnesses.items():self._metadata(name,witness)
        for index,witness in enumerate(self._chunks):self._cipher('chunk-%08x.enc'%index,witness)
        self._layout()

    def close(self):self._closed.set() # No premature descriptor/OS-lane release.

    def _handoff_retirement(self,retirement):
        from magnolie_media_source_retirement import _NativeSourceRetirement
        if type(retirement) is not _NativeSourceRetirement or retirement._reader is not self or retirement._sender._source is not self._owner:
            raise TransferError('media_source_retirement_native_handoff_required')
        retirement._current();self.verify();retirement._require_planned()
        self._retirement_handoff=retirement;self._close_owned()

    def _close_owned(self):
        self._closed.set()
        for name in ('_root','_parent'):
            fd=getattr(self,name,None)
            if fd is not None:os.close(fd);setattr(self,name,None)

    def __enter__(self):return self
    def __exit__(self,kind,*_):
        try:
            if kind is None and getattr(self,'_retirement_handoff',None) is None:self.verify()
        finally:self._close_owned()
