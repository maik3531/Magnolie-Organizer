"""Live native completed-source archival (#406), never deletion or restart.

Keep every cache byte and original reference. Only an actual completed sender
plus independently verified local source backup can hand off drained READ to a
no-replace archive move while the original book/OS lane remains owned.
"""
from dataclasses import dataclass
from contextlib import nullcontext,ExitStack
from hashlib import sha256
import copy
import os
import stat
import threading

from magnolie_file_control import _hex
from magnolie_file_transfer import FileManifest,TransferError
from magnolie_media_trash import _move_no_replace
from magnolie_telefon import canonical,strict_json


@dataclass(frozen=True)
class NativeSourceRetirementObservation:
    version: str
    _body: dict
    @property
    def body(self):return copy.deepcopy(self._body)
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def permits_deletion(self):return False
    @property
    def permits_slot_reuse(self):return False


class _NativeSourceRetirementJournal:
    MAX_BYTES=16384
    BATCH_MAX_BYTES=262144
    def __init__(self,jobs):
        self._jobs=jobs;self._prefix=jobs._catalog._retirement

    def _read(self,db,key,job):
        name=self._prefix+job;row=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()
        if row is None:return None
        cipher=row[0]
        if type(cipher) is not bytes or not 29<=len(cipher)<=self.BATCH_MAX_BYTES+28:raise TransferError('media_source_retirement_invalid_record')
        plain=self._jobs._authority.protection.unseal(cipher,name);body=strict_json(plain)
        batch=type(body) is dict and type(body.get('format')) is int and body['format']==3
        if not batch and len(cipher)>self.MAX_BYTES+28:raise TransferError('media_source_retirement_invalid_record')
        retry=type(body) is dict and body.get('format')==2
        if (type(body) is not dict or set(body)!={'format','scope','database_key','job_id','nonce','ready_version','exchange_version',
                'state','stage','archive','root_key','parent_key','manifest','proof_witness'} | ({'backups'} if batch else {'backup'}) | ( {'retry_version','retry_attempt_id'} if retry else set())
                or type(body['format']) is not int or body['format'] not in (1,2,3) or body['scope']!=self._jobs._scope
                or body['database_key']!=list(key) or body['job_id']!=job or body['state'] not in ('archive_planned','archived')
                or any(not _hex(body[name]) for name in ('nonce','ready_version','exchange_version'))
                or body['stage']!='.magnolie-source-'+self._jobs._scope[:32]+'.part'
                or body['archive']!='.magnolie-source-'+self._jobs._scope[:32]+'-'+job+'.retired'
                or canonical(body)!=plain):raise TransferError('media_source_retirement_invalid_record')
        if retry and (not _hex(body['retry_version']) or type(body['retry_attempt_id']) is not str
                or len(body['retry_attempt_id'])!=32 or not _hex(body['retry_attempt_id']*2)):
            raise TransferError('media_source_retirement_invalid_record')
        manifest=FileManifest.parse(body['manifest'])
        if manifest.source_id!=job or not batch and len(manifest.files)!=1:raise TransferError('media_source_retirement_invalid_record')
        for field in ('root_key','parent_key'):
            value=body[field]
            if type(value) is not list or len(value)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in value) or value[1]==0:
                raise TransferError('media_source_retirement_invalid_record')
        proof=body['proof_witness']
        if (type(proof) is not dict or set(proof)!={'key','sha256','size'} or not _hex(proof['sha256'])
                or type(proof['size']) is not int or not 29<=proof['size']<=65564
                or type(proof['key']) is not list or len(proof['key'])!=2
                or any(type(n) is not int or not 0<=n<2**64 for n in proof['key']) or proof['key'][1]==0):
            raise TransferError('media_source_retirement_invalid_record')
        selections=body['backups'] if batch else {manifest.files[0].id:body['backup']}
        if type(selections) is not dict or set(selections)!={f.id for f in manifest.files}:
            raise TransferError('media_source_retirement_invalid_record')
        roots=set();versions=set()
        for file in manifest.files:
            backup=selections[file.id];_validate_retirement_backup(backup,file)
            roots.add((backup['scope'],tuple(backup['root_key']),canonical(backup['storage_parent'])))
            versions.add(backup['version_id'])
        if len(roots)!=1 or len(versions)!=len(manifest.files):
            raise TransferError('media_source_retirement_invalid_record')
        return NativeSourceRetirementObservation(sha256(cipher).hexdigest(),body)

    def lookup(self,job):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');catalog=self._jobs._catalog.verify(db,key);result=self._read(db,key,job)
        self._jobs._catalog.observe(catalog);return result

    def write(self,owner,expected,body):
        from magnolie_media_source_recovery import _NativeSourceRetirementRecovery,_NativeBatchSourceRetirementRecovery
        recovery=type(owner) in (_NativeSourceRetirementRecovery,_NativeBatchSourceRetirementRecovery)
        batch=type(owner) in (_NativeBatchSourceRetirement,_NativeBatchSourceRetirementRecovery)
        if (not recovery and type(owner) not in (_NativeSourceRetirement,_NativeBatchSourceRetirement)
                or owner._journal is not self):
            raise TransferError('media_source_retirement_live_owner_required')
        if recovery and expected is None:
            raise TransferError('media_source_retirement_original_intent_required')
        if recovery and (expected.body['format']==3)!=batch:
            raise TransferError('media_source_whole_batch_recovery_owner_required')
        owner._current();job=owner._job
        with self._jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=self._jobs._catalog.verify(db,key);before=self._read(db,key,job)
            if expected is None:
                if before is not None:raise TransferError('media_source_retirement_existing_intent_held')
                body=dict(body,format=3 if type(owner) is _NativeBatchSourceRetirement else 2 if owner._sender._retry_spec is not None else 1,
                    scope=self._jobs._scope,database_key=list(key),job_id=job)
                if body['state']!='archive_planned':raise TransferError('media_source_retirement_invalid_transition')
            elif (before is None or before.version!=expected.version or before.body['state']!='archive_planned'
                    or body!=dict(before.body,state='archived')):raise TransferError('media_source_retirement_original_intent_required')
            plain=canonical(body)
            if len(plain)>(self.BATCH_MAX_BYTES if batch else self.MAX_BYTES):
                raise TransferError('media_source_retirement_record_size')
            name=self._prefix+job;cipher=self._jobs._authority.protection.seal(plain,name)
            db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(name,cipher))
            self._read(db,key,job);self._jobs._catalog.advance(db,key,catalog);owner._current()
        owner._current();result=self.lookup(job)
        if result is None or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_retirement_readback_failed')
        return result


def _validate_retirement_backup(backup,file):
    from magnolie_media_backup_codec import content_key
    from magnolie_file_acceptance import NativeAcceptedDestination
    if (type(backup) is not dict or set(backup)!={'scope','root_key','storage_parent','version_id','record_sha256','object_key'}
            or any(not _hex(backup[field]) for field in ('scope','version_id','record_sha256'))
            or backup['object_key']!=content_key(file.size,file.sha256)):
        raise TransferError('media_source_retirement_invalid_record')
    NativeAcceptedDestination.parse(backup['storage_parent'])
    root=backup['root_key']
    if type(root) is not list or len(root)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in root) or root[1]==0:
        raise TransferError('media_source_retirement_invalid_record')


def _private(value,*,directory=False):
    if (value.st_uid!=os.geteuid() or value.st_mode&0o077 or not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
            or not directory and value.st_nlink!=1):raise TransferError('media_source_retirement_unsafe_entry')


_history_checks=threading.local()


def verify_retirement_exchange(jobs,db,key,ready,body,*,pc_trail=()):
    # Memoize only within this synchronous protected-DB verification call tree.
    # Otherwise 128-member predecessor roots could recursively reverify the
    # same older roots exponentially. This is DATA validation, not cached IO or
    # native rights, and no success survives the outer call/transaction scope.
    previous=getattr(_history_checks,'scope',None)
    same=previous is not None and previous[0] is jobs and previous[1] is db and previous[2]==key
    scope=previous if same else (jobs,db,key,set(),{})
    if not same:_history_checks.scope=scope
    token=(ready.version,sha256(canonical(body)).hexdigest())
    try:
        if token in scope[3]:raise TransferError('media_source_lineage_cycle')
        if token in scope[4]:return scope[4][token]
        if len(scope[3])>=jobs.MAX_RECORDS:raise TransferError('media_source_lineage_cycle')
        scope[3].add(token)
        try:exchange=_verify_retirement_exchange(jobs,db,key,ready,body,pc_trail=pc_trail)
        finally:scope[3].remove(token)
        scope[4][token]=exchange
        return exchange
    finally:
        if not same:_history_checks.scope=previous


def _verify_retirement_exchange(jobs,db,key,ready,body,*,pc_trail=()):
    """Exact pinned historical evidence, never current wire or raw READ rights."""
    from magnolie_media_source_exchange import _read_source_exchange
    job=body['job_id'];original=_read_source_exchange(jobs,db,key,job,ready)
    if original is None or original.version!=body['exchange_version']:
        raise TransferError('media_source_retirement_original_exchange_required')
    if body['format']==3:
        if (ready.body['format']!=4 or original.body['format']!=5
                or db.execute('SELECT 1 FROM meta WHERE key=?',(jobs._catalog._retry+job,)).fetchone()):
            raise TransferError('media_source_retirement_original_exchange_required')
        peer=jobs._authority.current_peer();local=jobs._authority.identity
        manifest=FileManifest.parse(ready.body['manifest'])
        if peer is None or manifest.sender_id!=local.receiver_id or manifest.receiver_id!=peer.peer_id:
            raise TransferError('media_source_retirement_readback_pair_required')
        from magnolie_media_source_pc_history import batch_predecessors
        previous=batch_predecessors(jobs,db,key,ready,pc_trail)
        verify_completed_batch_exchange(original.body,ready,local.receiver_identity_sha256,peer.identity_sha256,previous)
        return original
    if body['format']==1:
        if db.execute('SELECT 1 FROM meta WHERE key=?',(jobs._catalog._retry+job,)).fetchone():
            raise TransferError('media_source_retirement_original_exchange_required')
        if original.body['format']==4:
            peer=jobs._authority.current_peer();local=jobs._authority.identity
            manifest=FileManifest.parse(ready.body['manifest'])
            if peer is None or manifest.sender_id!=local.receiver_id or manifest.receiver_id!=peer.peer_id:
                raise TransferError('media_source_retirement_readback_pair_required')
            from magnolie_media_source_pc_history import previous_publication
            previous=previous_publication(jobs,db,key,ready,pc_trail)
            verify_completed_media_exchange(original.body,manifest,local.receiver_identity_sha256,
                peer.identity_sha256,ready.body['original_references'],pc_origin=ready.body.get('local_origin'),pc_previous=previous)
        elif original.body['phase']!='peer_saved':raise TransferError('media_source_retirement_original_exchange_required')
        return original
    from magnolie_media_source_retry import _read_retry_history
    history=_read_retry_history(jobs,db,key,job,ready,body['exchange_version'])
    if history is None or history.version!=body['retry_version'] or history.body['attempts'][-1]['id']!=body['retry_attempt_id']:
        raise TransferError('media_source_retirement_original_retry_required')
    record=history.body['attempts'][-1]['record'];manifest=FileManifest.parse(ready.body['manifest'])
    if record['phase']=='peer_readback':
        from magnolie_file_published_readback import parse_readback
        from magnolie_file_transfer import NativeTransferBinding
        if (record['format'] not in (2,3) or record['acceptance'] is not None or type(record['sent_bits']) is not int or record['sent_bits']!=0
                or record['pending_chunk'] is not None or record['peer_saved'] is not None or type(record.get('peer_readback')) is not dict):
            raise TransferError('media_source_retirement_completed_readback_required')
        peer=jobs._authority.current_peer();local=jobs._authority.identity
        if peer is None or manifest.sender_id!=local.receiver_id or manifest.receiver_id!=peer.peer_id:
            raise TransferError('media_source_retirement_readback_pair_required')
        message=record['peer_readback'];raw=message.get('body')
        if type(raw) is not dict:raise TransferError('media_source_retirement_completed_readback_required')
        # Historical binding DATA only; not a session, sender or current grant.
        binding=NativeTransferBinding(manifest.sender_id,manifest.receiver_id,local.receiver_identity_sha256,peer.identity_sha256,
            record['permission_epoch'],raw.get('destination_token'))
        kind=ready.body['original_references'][manifest.files[0].id]['media_type']
        parse_readback(message,record['offer'],binding,kind,now=message.get('created_ms'))
        return
    verify_completed_saved_exchange(record,manifest)


def verify_completed_saved_exchange(record,manifest):
    """Validate historical completion as candidate DATA, not a fresh grant."""
    from magnolie_file_accept_message import parse_acceptance
    from magnolie_file_saved_message import parse_saved
    from magnolie_file_offer import validate_offer
    if (record['phase']!='peer_saved' or record['pending_chunk'] is not None or type(record['sent_bits']) is not int
            or record['sent_bits']!=(1<<manifest.files[0].chunks)-1
            or any(type(record[field]) is not dict for field in ('offer','acceptance','peer_saved'))):
        raise TransferError('media_source_retirement_completed_retry_required')
    offer=record['offer'];accepted_message=record['acceptance'];saved_message=record['peer_saved']
    if validate_offer(offer,sender_id=manifest.sender_id,receiver_id=manifest.receiver_id,now=offer.get('created_ms'))!=manifest:
        raise TransferError('media_source_retirement_completed_retry_required')
    accepted=parse_acceptance(accepted_message,now=accepted_message.get('created_ms'))
    saved=parse_saved(saved_message,manifest,now=saved_message.get('created_ms'))
    if (accepted.offer_id!=offer['message_id'] or accepted.manifest_sha256!=manifest.fingerprint
            or accepted.transfer_id!=manifest.transfer_id or accepted.permission_epoch!=record['permission_epoch']
            or any(getattr(accepted,field)!=getattr(saved,field) for field in
                ('transfer_id','manifest_sha256','acceptance_sha256','permission_epoch','destination_token'))):
        raise TransferError('media_source_retirement_completed_retry_required')


def verify_completed_media_exchange(record,manifest,local_key,peer_key,originals,*,pc_origin=None,pc_previous=None):
    """Pinned historical DATA only; native reader, backup and drain stay separate."""
    from magnolie_media_offer import validate_media_offer
    from magnolie_file_accept_message import parse_acceptance
    from magnolie_file_saved_message import parse_saved
    from magnolie_file_published_readback import parse_readback
    from magnolie_file_transfer import NativeTransferBinding
    if (record['format']!=4 or record['phase']!='peer_readback' or record['pending_chunk'] is not None
            or type(record['sent_bits']) is not int or record['sent_bits']!=(1<<manifest.files[0].chunks)-1
            or any(type(record.get(field)) is not dict for field in ('offer','acceptance','peer_saved','peer_readback'))):
        raise TransferError('media_source_retirement_completed_media_required')
    offer=record['offer'];accepted_message=record['acceptance'];saved_message=record['peer_saved'];readback_message=record['peer_readback']
    media=validate_media_offer(offer,manifest.sender_id,manifest.receiver_id,now=offer.get('created_ms'))
    if media.manifest!=manifest or media.originals!=originals:raise TransferError('media_source_retirement_completed_media_required')
    if pc_origin is not None:
        expected={manifest.files[0].id:dict(format=1,origin_sha256=sha256(b'magnolie-pc-media-origin-v1\0'+canonical(pc_origin)).hexdigest(),
            previous_publication_sha256=pc_previous)}
        if media.pc_origins!=expected:raise TransferError('media_collection_retirement_original_origin_required')
    elif media.pc_origins:raise TransferError('media_collection_retirement_original_origin_required')
    accepted=parse_acceptance(accepted_message,now=accepted_message.get('created_ms'))
    saved=parse_saved(saved_message,manifest,now=saved_message.get('created_ms'))
    raw=readback_message.get('body')
    if type(raw) is not dict:raise TransferError('media_source_retirement_completed_media_required')
    binding=NativeTransferBinding(manifest.sender_id,manifest.receiver_id,local_key,peer_key,record['permission_epoch'],raw.get('destination_token'))
    parsed=parse_readback(readback_message,media.offer,binding,media.media_type,now=readback_message.get('created_ms'))
    file=manifest.files[0]
    if (accepted.offer_id!=offer['message_id'] or accepted.manifest_sha256!=manifest.fingerprint or accepted.transfer_id!=manifest.transfer_id
            or accepted.permission_epoch!=record['permission_epoch'] or any(getattr(accepted,field)!=getattr(saved,field) for field in
                ('transfer_id','manifest_sha256','acceptance_sha256','permission_epoch','destination_token'))
            or saved_message['created_ms']<offer['created_ms'] or saved_message['expires_ms']>offer['expires_ms']
            or parsed.body['publication_sha256']!=saved.receipts[0].receipt_sha256 or parsed.body['mime_type']!=media.mime_types[file.id]):
        raise TransferError('media_source_retirement_completed_media_required')


def verify_completed_batch_exchange(record,ready,local_key,peer_key,predecessors):
    """Complete pinned batch evidence DATA, never a native archive/move permit.

    The caller supplies the independently resolved ORIGINAL predecessor map;
    a ready record's self-declared publications cannot authorize retirement.
    Native book, source/cache descriptors, backup verification and drain remain
    separately owned by the actual retirement scope.
    """
    from magnolie_media_source_jobs import NativeSourceJobRecord
    from magnolie_media_source_batch_cache import validate_batch_members,validate_batch_predecessors
    from magnolie_media_source_exchange import _validate_exchange_body
    from magnolie_file_published_batch_readback import parse_batch_readback
    from magnolie_file_transfer import NativeTransferBinding
    if (type(ready) is not NativeSourceJobRecord or ready.state!='cache_ready' or ready.body['format']!=4
            or type(record) is not dict or record.get('format')!=5 or record.get('phase')!='peer_readback'):
        raise TransferError('media_source_retirement_completed_batch_required')
    body=ready.body;manifest=FileManifest.parse(body['manifest'])
    validate_batch_members(body['members']);validate_batch_predecessors(body['members'],predecessors)
    if body['predecessors']!=predecessors:
        raise TransferError('media_collection_retirement_original_predecessors_required')
    # Reuse only the parsed values from this complete validation of this
    # record. The independent native pair binding is still verified below.
    media,saved=_validate_exchange_body(record,body['database_key'],body['scope'],body['job_id'],body['nonce'],ready.version,
        manifest=manifest,predecessors=predecessors)
    packet=record['peer_readback']
    expected={fid:dict(format=1,origin_sha256=sha256(b'magnolie-pc-media-origin-v1\0'+canonical(entry['local_origin'])).hexdigest(),
        previous_publication_sha256=None if predecessors[fid] is None else predecessors[fid]['publication_sha256'])
        for fid,entry in body['members'].items()}
    if media.manifest!=manifest or media.originals!={} or media.pc_origins!=expected or media.media_type!=body['media_type']:
        raise TransferError('media_collection_retirement_original_origin_required')
    raw=packet.get('body')
    if type(raw) is not dict:raise TransferError('media_source_retirement_completed_batch_required')
    binding=NativeTransferBinding(manifest.sender_id,manifest.receiver_id,local_key,peer_key,record['permission_epoch'],raw.get('destination_token'))
    parsed=parse_batch_readback(packet,media.offer,binding,media.media_type,now=packet.get('created_ms'))
    receipts={r.file_id:r for r in saved.receipts}
    for file in manifest.files:
        member=parsed.body['members'][file.id]
        if member['publication_sha256']!=receipts[file.id].receipt_sha256 or member['mime_type']!=media.mime_types[file.id]:
            raise TransferError('media_source_retirement_completed_batch_required')


def verified_batch_source_backups(backups,selected,batch,current):
    """Independently reread the FULL local backup map inside native batch IO.

    Returns historical witnesses only. A dictionary, backup observation or this
    result cannot close originals, move a cache, or free a source slot.
    """
    from magnolie_media_source_batch import NativeCollectionMediaBatch
    from magnolie_media_source_batch_cache import FrozenNativeMediaBatch
    from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
    from magnolie_media_source_backup import batch_source_provenances
    if (type(batch) is not NativeCollectionMediaBatch or type(batch._cache) is not FrozenNativeMediaBatch
            or type(backups) is not NativeMediaBackups or type(selected) is not dict or not callable(current)
            or set(selected)!={f.id for f in batch._cache.manifest.files}
            or any(type(v) is not NativeMediaBackupVersion for v in selected.values())
            or backups.destination!=batch._selected.directory):
        raise TransferError('media_source_retirement_complete_batch_backup_required')
    def live():
        current()
        if batch._active_reader is None:raise TransferError('media_source_retirement_live_lease_required')
        batch._active_reader._permission();return True
    expected=batch_source_provenances(batch)
    return _verified_source_backup_map(backups,selected,expected,batch._owner._authority.protection,live)


def _verified_source_backup_map(backups,selected,expected,protection,live):
    """Shared whole-map RO verification; returns DATA, not native move rights."""
    from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
    if (type(backups) is not NativeMediaBackups or type(selected) is not dict or type(expected) is not dict
            or not expected or set(selected)!=set(expected) or any(type(v) is not NativeMediaBackupVersion for v in selected.values())):
        raise TransferError('media_source_retirement_complete_batch_backup_required')
    live()
    if backups.protection.native_directory_identity!=protection.native_directory_identity:
        raise TransferError('media_source_retirement_exact_local_backup_required')
    # Validate each committed version and hash its canonical bytes in ONE
    # held operation. A per-member pass that closes the FD before this pass
    # adds no witness to the complete map returned below.
    from magnolie_media_backup_codec import verify_raw,verify_xz
    signature=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    with backups._operation(),ExitStack() as held:
        result={};objects={};identities=set()
        def backup_live():live();backups._current();return True
        for fid,source in expected.items():
            backup_live();selection=selected[fid];value=backups._record('versions',selection.id)
            if value is None or backups._version(value)!=selection or value.get('source')!=source:
                raise TransferError('media_source_retirement_complete_batch_backup_required')
            obj=backups._record('objects',value['object_key'])
            if obj is None or obj['prepared']:raise TransferError('media_source_retirement_complete_batch_backup_required')
            result[fid]=dict(scope=backups.scope,root_key=list(backups._root_key),storage_parent=backups.storage_parent.wire(),
                version_id=selection.id,record_sha256=selection.record_sha256,object_key=selection.object_key)
            if obj['id'] in objects:continue # Raw content dedup is not original-file aliasing.
            representation=backups._representation(obj)
            fd=held.enter_context(backups._object(obj));before=os.fstat(fd)
            identity=(before.st_dev,before.st_ino)
            if identity in identities:raise TransferError('media_backup_original_object_changed')
            identities.add(identity);objects[obj['id']]=(obj,representation,fd,signature(before))
        # All actual canonical RO descriptors stay open through every read and
        # the final ALL-member witness check, including earlier members.
        for obj,representation,fd,before in objects.values():
            # Both verifiers call backup_live before inspecting the descriptor.
            if representation.codec=='raw':
                value=verify_raw(fd,representation.raw_size,representation.raw_sha256,backup_live)
                if representation.stored_size!=value.st_size or representation.stored_sha256!=representation.raw_sha256:
                    raise TransferError('media_backup_object_invalid')
            elif verify_xz(fd,representation.raw_size,representation.raw_sha256,backup_live)!=representation:
                raise TransferError('media_backup_original_object_changed')
        for obj,representation,fd,before in objects.values():
            backup_live()
            named=os.stat(obj['name'],dir_fd=backups._root,follow_symlinks=False)
            if signature(os.fstat(fd))!=before or signature(named)!=before:
                raise TransferError('media_backup_original_object_changed')
        backup_live()
    return result


def verify_archived_cache(jobs,parent,body,current,*,name=None):
    name=body['archive'] if name is None else name
    if name!=body['archive'] and (body.get('format')!=3 or name!=body['stage'] or body['state']!='archive_planned'):
        raise TransferError('media_source_recovery_original_stage_required')
    current();value=os.fstat(parent);_private(value,directory=True)
    if [value.st_dev,value.st_ino]!=body['parent_key']:raise TransferError('media_source_retirement_original_parent_required')
    try:root=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
    except FileNotFoundError:raise TransferError('media_source_retirement_original_archive_required')
    try:
        value=os.fstat(root);_private(value,directory=True)
        if [value.st_dev,value.st_ino]!=body['root_key']:raise TransferError('media_source_retirement_original_archive_required')
        manifest=FileManifest.parse(body['manifest']);expected={'intent.enc','copying.enc','manifest.enc'}
        batch=body.get('format')==3
        if batch:
            from magnolie_media_source_batch_cache import _NativeBatchCacheWriter
            expected|={_NativeBatchCacheWriter.chunk_name(f.id,i) for f in manifest.files for i in range(f.chunks)}
        else:expected|={'chunk-%08x.enc'%i for i in range(manifest.files[0].chunks)}
        if set(os.listdir(root))!=expected:raise TransferError('media_source_retirement_archive_layout_changed')
        for leaf in expected:_private(os.stat(leaf,dir_fd=root,follow_symlinks=False))
        fd=os.open('manifest.enc',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root)
        try:
            before=os.fstat(fd);_private(before);proof=body['proof_witness']
            if [before.st_dev,before.st_ino]!=proof['key'] or before.st_size!=proof['size']:
                raise TransferError('media_source_retirement_original_proof_required')
            cipher=os.pread(fd,before.st_size+1,0);after=os.fstat(fd);named=os.stat('manifest.enc',dir_fd=root,follow_symlinks=False)
            signature=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
            if (signature(before)!=signature(after) or signature(named)!=signature(after) or len(cipher)!=proof['size']
                    or sha256(cipher).hexdigest()!=proof['sha256']):raise TransferError('media_source_retirement_original_proof_required')
        finally:os.close(fd)
        if batch:_verify_archived_batch_cipher(jobs,root,body,manifest,cipher,current)
        named=os.stat(name,dir_fd=parent,follow_symlinks=False);_private(named,directory=True)
        if [named.st_dev,named.st_ino]!=body['root_key']:raise TransferError('media_source_retirement_original_archive_required')
        current()
    finally:os.close(root)


def _verify_archived_batch_cipher(jobs,root,body,manifest,proof_cipher,current):
    """Whole sealed encrypted layout, not plaintext READ or restart authority."""
    from magnolie_file_transfer import CHUNK_BYTES
    from magnolie_media_source_batch_cache import validate_batch_members,validate_batch_predecessors,_NativeBatchCacheWriter
    from magnolie_media_source_roots import NativeMediaCollectionRootsWitness
    signature=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    def domain(name,key):
        return ('native-media-source-cache-v1/'+jobs._scope+'/'+str(body['root_key'][0])+':'+str(body['root_key'][1])
            +'/'+name+'/'+str(key[0])+':'+str(key[1]))
    plain=jobs._authority.protection.unseal(proof_cipher,domain('manifest.enc',body['proof_witness']['key']))
    proof=strict_json(plain)
    if (type(proof) is not dict or set(proof)!={'format','state','intent_sha256','job_nonce','book_version','manifest',
            'chunks_sha256','chunk_count','metadata','members','predecessors','root_catalog','media_type'}
            or type(proof['format']) is not int or proof['format']!=4 or proof['state']!='sealed'
            or proof['job_nonce']!=body['nonce'] or proof['manifest']!=manifest.wire()
            or any(not _hex(proof[n]) for n in ('intent_sha256','book_version','chunks_sha256'))
            or type(proof['chunk_count']) is not int or proof['chunk_count']!=sum(f.chunks for f in manifest.files)
            or type(proof['metadata']) is not dict or set(proof['metadata'])!={'intent.enc','copying.enc'}
            or proof['media_type'] not in ('images','video') or canonical(proof)!=plain):
        raise TransferError('media_source_retirement_original_proof_required')
    validate_batch_members(proof['members']);validate_batch_predecessors(proof['members'],proof['predecessors'])
    if ({fid:(v['path'],v['size']) for fid,v in proof['members'].items()}!={f.id:(f.path,f.size) for f in manifest.files}
            or NativeMediaCollectionRootsWitness.parse(proof['root_catalog']).scope!=jobs._root_scope):
        raise TransferError('media_source_retirement_original_proof_required')
    identities={tuple(body['proof_witness']['key']):'manifest.enc'};checks={}
    def read_cipher(name,expected=None):
        current();fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root)
        try:
            before=os.fstat(fd);_private(before)
            if not 29<=before.st_size<=CHUNK_BYTES+28:raise TransferError('media_source_retirement_original_archive_required')
            blob=os.pread(fd,before.st_size+1,0);after=os.fstat(fd);named=os.stat(name,dir_fd=root,follow_symlinks=False)
            if len(blob)!=before.st_size or signature(before)!=signature(after) or signature(named)!=signature(after):
                raise TransferError('media_source_retirement_original_archive_required')
            witness=dict(key=[after.st_dev,after.st_ino],size=len(blob),sha256=sha256(blob).hexdigest())
            if expected is not None and expected!=witness:raise TransferError('media_source_retirement_original_archive_required')
            identity=tuple(witness['key'])
            if identity in identities and identities[identity]!=name:raise TransferError('media_source_retirement_original_archive_required')
            identities[identity]=name;checks[name]=signature(after);current();return blob,witness
        finally:os.close(fd)
    metadata={}
    for name,witness in proof['metadata'].items():
        blob,actual=read_cipher(name,witness)
        metadata[name]=strict_json(jobs._authority.protection.unseal(blob,domain(name,actual['key'])))
    intent=metadata['intent.enc']
    if (type(intent) is not dict or intent.get('format')!=4 or type(intent.get('format')) is not int
            or intent.get('state')!='planned' or intent.get('job_id')!=body['job_id'] or intent.get('job_nonce')!=body['nonce']
            or intent.get('scope')!=jobs._scope or intent.get('book_version')!=proof['book_version']
            or intent.get('root_key')!=body['root_key'] or intent.get('parent_key')!=body['parent_key']
            or any(intent.get(n)!=proof[n] for n in ('members','predecessors','root_catalog','media_type'))
            or sha256(canonical(intent)).hexdigest()!=proof['intent_sha256']
            or metadata['copying.enc']!=dict(format=4,state='copying',intent_sha256=proof['intent_sha256'])):
        raise TransferError('media_source_retirement_original_proof_required')
    members=sha256()
    for file in manifest.files:
        for index in range(file.chunks):
            blob,witness=read_cipher(_NativeBatchCacheWriter.chunk_name(file.id,index))
            if witness['size']!=min(CHUNK_BYTES,file.size-index*CHUNK_BYTES)+28:
                raise TransferError('media_source_retirement_original_archive_required')
            members.update(canonical(dict(file_id=file.id,index=index,**witness)))
    if members.hexdigest()!=proof['chunks_sha256']:raise TransferError('media_source_retirement_original_archive_required')
    # No 6400-FD fanout: the owned encrypted root plus exact witnesses fence
    # all chunk routes. Recheck earlier signatures after the final actual read,
    # and reauthenticate the original sealed metadata, before the root CAS.
    read_cipher('manifest.enc',body['proof_witness'])
    for name,witness in proof['metadata'].items():read_cipher(name,witness)
    for name,before in checks.items():
        current();named=os.stat(name,dir_fd=root,follow_symlinks=False);_private(named)
        if signature(named)!=before:raise TransferError('media_source_retirement_original_archive_required')
    current()
    return intent


def verified_source_backup(backups,selected,expected,protection,current):
    from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
    from magnolie_media_source_backup import source_provenance
    if type(backups) is not NativeMediaBackups or type(selected) is not NativeMediaBackupVersion:
        raise TransferError('media_source_retirement_exact_local_backup_required')
    current();source=source_provenance(backups,selected)
    if (any(source.get(key)!=value for key,value in expected.items())
            or backups.protection.native_directory_identity!=protection.native_directory_identity):
        raise TransferError('media_source_retirement_exact_local_backup_required')
    with backups._operation():
        value=backups._record('versions',selected.id)
        if value is None or backups._version(value)!=selected:
            raise TransferError('media_source_retirement_complete_local_backup_required')
        obj=backups._record('objects',value['object_key'])
        if obj is None or obj['prepared']:raise TransferError('media_source_retirement_complete_local_backup_required')
        backups._verify_object(obj)
    current()
    return dict(scope=backups.scope,root_key=list(backups._root_key),storage_parent=backups.storage_parent.wire(),
        version_id=selected.id,record_sha256=selected.record_sha256,object_key=selected.object_key)


class _NativeSourceRetirement:
    def __init__(self,sender,backups,selected,*,boundary=lambda _:None):
        from magnolie_media_source_sender import _NativeMediaSourceSender
        from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
        if type(sender) is _NativeMediaSourceSender and sender._batch is not None:
            raise TransferError('media_source_whole_batch_retirement_owner_required')
        if (type(sender) is not _NativeMediaSourceSender or type(backups) is not NativeMediaBackups
                or type(selected) is not NativeMediaBackupVersion or not callable(boundary)):
            raise TransferError('media_source_retirement_native_completed_owner_required')
        self._sender=sender;self._job=sender._job;self._backups=backups;self._selected=selected;self._boundary=boundary
        self._jobs=sender._jobs;self._journal=_NativeSourceRetirementJournal(self._jobs)
        self._reader=None;self._permit=None;self._record=None;self._closed=threading.Event();self._thread=None;self._planned=None

    def close(self):self._closed.set() # Never release another thread's actual IO.

    def _permits_pc_source_checkpoint(self,source,job):
        active=getattr(self._sender._active,'retirement',None)
        # The outer saved-book lease performs one final checkpoint after the
        # sender's active pointer is cleared, but before the original exact IO
        # permit/thread is released. Only this already-archived record qualifies;
        # neither a new reader nor Saved/readback can enter this cleanup branch.
        completed=(active is None and self._record is not None and self._planned is not None
            and self._record.body==dict(self._planned,format=2 if self._sender._retry_spec is not None else 1,
                scope=self._jobs._scope,database_key=list(self._jobs._database_key),job_id=self._job,state='archived'))
        return (not self._closed.is_set() and self._thread==threading.get_ident() and self._planned is not None
            and self._sender._source is source and self._job==job and self._reader is not None
            and getattr(self._reader,'_retirement_handoff',None) is self
            and (active is self or completed)
            and getattr(source._cache_scope,'permit',None) is self._permit and self._permit[3]==threading.get_ident())

    def _permits_retry_record(self,record):
        if (self._closed.is_set() or self._thread!=threading.get_ident() or self._planned is None or record is None
                or self._reader is None or getattr(self._sender._active,'reader',None) is not self._reader
                or getattr(self._sender._source._cache_scope,'permit',None) is not self._permit
                or self._permit[3]!=threading.get_ident()):return False
        expected=dict(self._planned,format=2,scope=self._jobs._scope,database_key=list(self._jobs._database_key),job_id=self._job)
        return record.body==expected or record.body==dict(expected,state='archived')

    def _current(self):
        sender=self._sender
        if self._closed.is_set() or self._thread!=threading.get_ident() or self._reader is None:
            raise TransferError('media_source_retirement_live_lease_required')
        sender._permission()
        if getattr(sender._source._cache_scope,'permit',None) is not self._permit:
            raise TransferError('media_source_retirement_live_lease_required')
        self._permit[2]()
        if sender._record is None:
            raise TransferError('media_source_retirement_actual_completed_sender_required')
        record=sender._record.body
        if record['format']==4:
            peer=sender._authority.current_peer()
            if peer is None:raise TransferError('media_source_retirement_readback_pair_required')
            verify_completed_media_exchange(record,sender._cache.manifest,sender._authority.identity.receiver_identity_sha256,
                peer.identity_sha256,sender._cache.original_references,pc_origin=sender._cache.pc_origin,
                pc_previous=self._jobs.pc_previous_publication(sender._cache.manifest.source_id,sender._cache._job_version))
        elif not (record['phase']=='peer_saved' or sender._retry_spec is not None and record['phase']=='peer_readback'):
            raise TransferError('media_source_retirement_actual_completed_sender_required')
        sender._journal.require(sender._record)
        if sender._controls.binding(sender._binding.destination_token,sender_is_local=True)!=sender._binding:
            raise TransferError('media_source_sender_binding_changed')

    def _backup_proof(self):
        cache=self._sender._cache
        expected=dict(job_id=self._job,job_nonce=cache._job_nonce,job_version=cache._job_version,
            proof_sha256=cache.proof_sha256,book_version=cache._book_version,manifest=cache.manifest.wire())
        return verified_source_backup(self._backups,self._selected,expected,self._sender._authority.protection,self._current)

    def _require_planned(self):
        self._current();record=self._journal.lookup(self._sender._job)
        if self._record is None or record is None or record.version!=self._record.version or record.body['state']!='archive_planned':
            raise TransferError('media_source_retirement_original_intent_required')

    def run(self):
        connection=self._sender._connection
        with connection._operation() if connection is not None else nullcontext():
            result=self._run()
            if connection is not None and connection._media_sender is self._sender:
                self._sender.close();connection._media_sender=None
            return result

    def _run(self):
        sender=self._sender
        if not sender._gate.acquire(blocking=False):raise TransferError('media_source_sender_busy')
        parent=None;handed=False
        try:
            with sender._source.prepared_cache(sender._job) as reader:
                self._reader=reader;self._thread=threading.get_ident();self._permit=sender._source._cache_scope.permit
                self._current();sender._active.reader=reader;sender._active.retirement=self
                try:
                    sender._current();backup=self._backup_proof();cache=sender._cache
                    parent=os.open(sender._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                    value=os.fstat(parent);parent_key=[value.st_dev,value.st_ino]
                    archive='.magnolie-source-'+self._jobs._scope[:32]+'-'+sender._job+'.retired'
                    body=dict(nonce=cache._job_nonce,ready_version=cache._job_version,exchange_version=sender._record.version,
                        state='archive_planned',stage=cache.directory.name,archive=archive,root_key=list(cache.root_key),parent_key=parent_key,
                        manifest=cache.manifest.wire(),proof_witness=copy.deepcopy(reader._proof_witness),backup=backup)
                    if sender._retry_spec is not None:
                        body.update(exchange_version=sender._journal._original_version,retry_version=sender._record.version,
                            retry_attempt_id=sender._journal._attempt)
                    self._planned=copy.deepcopy(body)
                    self._record=self._journal.write(self,None,body);self._boundary('source_retirement_planned');self._require_planned()
                    reader._handoff_retirement(self);handed=True
                    from magnolie_media_source_pc import NativeCollectionMediaSource
                    if type(sender._source) is NativeCollectionMediaSource:sender._source._handoff_original(self)
                    self._current();_move_no_replace(parent,body['stage'],archive);os.fsync(parent)
                    self._boundary('source_retirement_moved');self._current();verify_archived_cache(self._jobs,parent,body,self._current)
                    self._backup_proof();self._require_planned()
                    self._record=self._journal.write(self,self._record,dict(self._record.body,state='archived'))
                    self._boundary('source_retirement_archived');self._current();result=self._record
                finally:sender._active.reader=None;sender._active.retirement=None
            return result
        except BaseException:
            sender.close();raise
        finally:
            if parent is not None:os.close(parent)
            if handed:sender.close()
            self._reader=None;self._permit=None;self._thread=None;self._planned=None;sender._gate.release()


class _NativeBatchSourceRetirement:
    """One actual whole-source drain/archive, never a legacy single-file owner.

    Construction and observations do not grant a move. The private checkpoint
    exists only after every original/cache FD really closed inside this same
    native book/thread scope and its complete planned journal was read back.
    """
    def __init__(self,sender,backups,selected,*,boundary=lambda _:None):
        from magnolie_media_source_sender import _NativeMediaSourceSender
        from magnolie_media_source_batch import NativeCollectionMediaBatch
        from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
        if (type(sender) is not _NativeMediaSourceSender or type(sender._batch) is not NativeCollectionMediaBatch
                or sender._retry_spec is not None
                or type(backups) is not NativeMediaBackups or type(selected) is not dict or not callable(boundary)
                or set(selected)!={f.id for f in sender._cache.manifest.files}
                or any(type(v) is not NativeMediaBackupVersion for v in selected.values())):
            raise TransferError('media_source_retirement_native_batch_owner_required')
        self._sender=sender;self._batch=sender._batch;self._backups=backups;self._selected=dict(selected)
        self._jobs=sender._jobs;self._job=sender._job;self._journal=_NativeSourceRetirementJournal(self._jobs)
        self._reader=None;self._thread=None;self._ready=None;self._record=None;self._planned=None
        self._handed=False;self._closed=threading.Event();self._boundary=boundary

    def close(self):self._closed.set() # Only the actual owning thread drains IO and closes FDs.

    def _permits_batch_checkpoint(self,batch):
        if (batch is not self._batch or self._closed.is_set() or not self._handed
                or self._thread!=threading.get_ident() or batch._active_thread!=self._thread
                or batch._active_book is None or not batch._owner._gate.locked()
                or batch._retirement is not self or self._reader is None
                or getattr(self._sender._active,'reader',None) is not self._reader
                or self._reader._retirement_handoff is not self or not self._reader._closed
                or self._reader._root is not None or self._reader._parent is not None
                or batch._root is None or batch._root._fd is not None
                or any(lease._owned for lease in batch._leases.values())
                or self._record is None or self._planned is None):return False
        original=dict(self._planned,format=3,scope=self._jobs._scope,
            database_key=list(self._jobs._database_key),job_id=self._job)
        return self._record.body==original or self._record.body==dict(original,state='archived')

    def _permits_cache_checkpoint(self,reader):
        return reader is self._reader and self._permits_batch_checkpoint(self._batch)

    def _current(self):
        sender=self._sender
        if (self._closed.is_set() or self._thread!=threading.get_ident() or self._reader is None
                or getattr(sender._active,'reader',None) is not self._reader
                or sender._batch is not self._batch or self._ready is None):
            raise TransferError('media_source_retirement_live_lease_required')
        sender._current() # Includes actual root/book/cache scope, controls and ORIGINAL offer expiry.
        ready=self._jobs.require_version(self._job,sender._cache._job_version)
        if ready!=self._ready or sender._record is None:raise TransferError('media_source_retirement_original_intent_required')
        from dataclasses import asdict
        predecessors={fid:asdict(s.previous) if s.previous is not None else None for fid,s in self._batch._selections.items()}
        peer=sender._authority.current_peer()
        if peer is None:raise TransferError('media_source_retirement_readback_pair_required')
        verify_completed_batch_exchange(sender._record.body,ready,sender._authority.identity.receiver_identity_sha256,
            peer.identity_sha256,predecessors)

    def _backup_proof(self):
        return verified_batch_source_backups(self._backups,self._selected,self._batch,self._current)

    def _require_planned(self):
        self._current();record=self._journal.lookup(self._job)
        if (self._record is None or record is None or record.version!=self._record.version
                or record.body['state']!='archive_planned'):
            raise TransferError('media_source_retirement_original_intent_required')

    def run(self):
        sender=self._sender;connection=sender._connection
        with (connection._operation() if connection is not None else nullcontext()):
            if connection is not None:sender._permission()
            try:return self._run()
            finally:
                if connection is not None and sender._closed.is_set() and connection._media_sender is sender:
                    connection._media_sender=None

    def _run(self):
        sender=self._sender
        if self._handed or self._record is not None:raise TransferError('media_source_retirement_existing_intent_held')
        if not sender._gate.acquire(blocking=False):raise TransferError('media_source_sender_busy')
        parent=None
        try:
            with self._batch.cached_reader() as reader:
                self._reader=reader;self._thread=threading.get_ident()
                self._ready=self._jobs.require_version(self._job,sender._cache._job_version)
                sender._active.reader=reader;self._current()
                reader.verify();backups=self._backup_proof();self._current()
                cache=sender._cache
                parent=os.open(sender._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                value=os.fstat(parent);_private(value,directory=True)
                body=dict(nonce=cache._job_nonce,ready_version=cache._job_version,exchange_version=sender._record.version,
                    state='archive_planned',stage=cache.directory.name,
                    archive='.magnolie-source-'+self._jobs._scope[:32]+'-'+self._job+'.retired',
                    root_key=list(cache.root_key),parent_key=[value.st_dev,value.st_ino],manifest=cache.manifest.wire(),
                    proof_witness=copy.deepcopy(reader._proof_witness),backups=backups)
                self._planned=copy.deepcopy(body)
                self._record=self._journal.write(self,None,body)
                self._boundary('source_batch_retirement_planned')
                # The drain itself rereads the planned journal after this
                # boundary, before it can close even one original descriptor.
                self._batch._drain_retirement_originals(self)
                reader.close() # Same owning thread, after every actual read returned.
                self._batch._retirement=self;reader._retirement_handoff=self;self._handed=True
                self._current()
                _move_no_replace(parent,body['stage'],body['archive']);os.fsync(parent)
                self._boundary('source_batch_retirement_moved');self._current()
                verify_archived_cache(self._jobs,parent,self._record.body,self._current)
                self._backup_proof();self._require_planned()
                self._record=self._journal.write(self,self._record,dict(self._record.body,state='archived'))
                self._boundary('source_batch_retirement_archived');self._current()
                result=self._record
            return result
        finally:
            sender._active.reader=None
            if parent is not None:os.close(parent)
            sender.close();self._batch.close()
            self._reader=None;self._thread=None;self._ready=None
            sender._gate.release()
