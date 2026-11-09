"""Authenticated local backup of prepared PC bytes (#401), not remote Saved.

The unchanged original Saved mapping is historical provenance only. Current
source bytes have their own manifest, source job and immutable backup version.
Existing objects deduplicate by raw hash/size; source versions remain pinned.
"""
from hashlib import sha256
import copy
import os

from magnolie_file_control import _hex
from magnolie_file_transfer import FileManifest,TransferError
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_media_backup_codec import content_key,verify_raw
from magnolie_photo_mappings import NativeSavedPhotoMapping,PhotoMappingAssociation
from magnolie_telefon import canonical


def _source_version_id(source):
    return sha256(b'magnolie-native-source-backup-v1\0'+canonical(source)).hexdigest()


def _validate_source_version(value,key):
    fields={'id','object_key','saved_ms','name','source'}
    if (set(value)!=fields or value['id']!=key or not _hex(key) or type(value['saved_ms']) is not int
            or not 0<value['saved_ms']<=253402300799999 or type(value['source']) is not dict):
        raise TransferError('media_backup_source_version_invalid')
    source=value['source']
    if type(source.get('format')) is int and source['format']==2:
        from magnolie_media_source_pc import validate_pc_origin
        from magnolie_media_source_roots import NativeMediaCollectionRootsWitness
        if (set(source)!={'format','job_id','job_nonce','job_version','proof_sha256','book_version','manifest','local_origin','root_catalog','media_type','source_path'}
                or any(not _hex(source[name]) for name in ('job_nonce','job_version','proof_sha256','book_version'))
                or source['media_type'] not in ('images','video') or type(source['source_path']) is not str
                or not source['source_path'] or '/' in source['source_path'] or '\\' in source['source_path']
                or source['source_path'] in ('.','..')):
            raise TransferError('media_backup_source_version_invalid')
        validate_pc_origin(source['local_origin']);NativeMediaCollectionRootsWitness.parse(source['root_catalog'])
        manifest=FileManifest.parse(source['manifest'])
        if (len(manifest.files)!=1 or manifest.source_id!=source['job_id'] or _source_version_id(source)!=key
                or value['object_key']!=content_key(manifest.files[0].size,manifest.files[0].sha256)
                or value['name']!=source['source_path'] or manifest.files[0].path!=source['source_path']
                or source['local_origin']['file_path'].rsplit('/',1)[-1]!=source['source_path']):
            raise TransferError('media_backup_source_version_invalid')
        return value
    fields={'format','job_id','job_nonce','job_version','proof_sha256','book_version','manifest','original_mapping_sha256','original_mapping'}
    if (set(source) not in (fields,fields|{'restored_source'}) or type(source['format']) is not int or source['format']!=1
            or any(not _hex(source[name]) for name in ('job_nonce','job_version','proof_sha256','book_version','original_mapping_sha256'))
            or type(source['original_mapping']) is not dict or type(source['original_mapping'].get('association')) is not dict):
        raise TransferError('media_backup_source_version_invalid')
    association=source['original_mapping']['association']
    if set(association)!={'source_epoch','photo_id','media_type'}:raise TransferError('media_backup_source_version_invalid')
    mapping=NativeSavedPhotoMapping.parse(source['original_mapping'],PhotoMappingAssociation(**association),source['original_mapping_sha256'])
    manifest=FileManifest.parse(source['manifest'])
    name=mapping.relative_path
    if 'restored_source' in source:
        restored=source['restored_source']
        if (type(restored) is not dict or set(restored)!={'destination','relative_path','file_key','parent_keys',
                'restore_record_sha256','original_mapping_sha256'} or not _hex(restored['restore_record_sha256'])
                or restored['original_mapping_sha256']!=source['original_mapping_sha256']):
            raise TransferError('media_backup_source_version_invalid')
        destination=NativeAcceptedDestination.parse(restored['destination']);name=restored['relative_path']
        if (type(name) is not str or not name or '/' in name or '\\' in name or name in ('.','..')
                or restored['parent_keys']!=[list(destination.ancestor_keys[0])]):
            raise TransferError('media_backup_source_version_invalid')
        key_value=restored['file_key']
        if (type(key_value) is not list or len(key_value)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in key_value)
                or key_value[0]!=destination.ancestor_keys[0][0] or key_value[1]==0):
            raise TransferError('media_backup_source_version_invalid')
    if (len(manifest.files)!=1 or manifest.source_id!=source['job_id'] or _source_version_id(source)!=key
            or value['object_key']!=content_key(manifest.files[0].size,manifest.files[0].sha256)
            or value['name']!=name or manifest.files[0].path!=name.rsplit('/',1)[-1]):
        raise TransferError('media_backup_source_version_invalid')
    return value


def source_provenance(backups,selected):
    from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
    if type(backups) is not NativeMediaBackups or type(selected) is not NativeMediaBackupVersion:
        raise TransferError('media_backup_native_selection_required')
    with backups._operation():
        value=backups._selected_version(selected)
        if 'source' not in value:raise TransferError('media_backup_source_version_required')
        return copy.deepcopy(value['source']) # History only, no READ/Saved/retirement token.


def backup_prepared_source(backups,source,job_id,*,boundary=lambda _:None):
    from magnolie_media_backups import NativeMediaBackups
    from magnolie_media_source_pc import native_source_kind
    local=native_source_kind(source)=='collection'
    if (type(backups) is not NativeMediaBackups or not callable(boundary)
            or type(job_id) is not str or job_id not in source._prepared):
        raise TransferError('media_backup_actual_source_preparation_required')
    prepared=source._prepared[job_id];cached=prepared.cache;mapping=prepared.original_mapping
    restored=prepared.restored_source
    if local:
        held=source._held.get(job_id)
        if held is None or mapping is not None or restored is not None or cached.pc_origin is None or cached.original_references!={}:
            raise TransferError('media_backup_original_source_owner_required')
        destination=held[0]._directory
    else:destination=mapping.destination if restored is None else restored.destination
    if ((not local and type(mapping) is not NativeSavedPhotoMapping) or destination!=backups.destination
            or backups.protection.native_directory_identity!=source._authority.protection.native_directory_identity
            or not local and cached.original_references!={cached.manifest.files[0].id:mapping.phone_original_reference()}):
        raise TransferError('media_backup_original_source_owner_required')
    with source.prepared_cache(job_id) as reader,backups._operation():
        def current():reader._permission();backups._current();return True
        current();backups._ensure_native_owner();file=cached.manifest.files[0]
        provenance=dict(format=2 if local else 1,job_id=job_id,job_nonce=cached._job_nonce,job_version=cached._job_version,
            proof_sha256=cached.proof_sha256,book_version=prepared.book_version,manifest=cached.manifest.wire())
        if local:provenance.update(local_origin=cached.pc_origin,root_catalog=cached._pc_selection.catalog,media_type=cached._media_type,source_path=file.path)
        else:provenance.update(original_mapping_sha256=mapping.protected_record_sha256,original_mapping=mapping.wire())
        if restored is not None:provenance['restored_source']=restored.wire()
        version_id=_source_version_id(provenance);key=content_key(file.size,file.sha256)
        before=backups._record('versions',version_id);obj=backups._record('objects',key)
        if before is not None:
            if before['source']!=provenance or obj is None:raise TransferError('media_backup_original_source_owner_required')
            backups._verify_object(obj);current();return backups._version(before)
        version=backups._pending(version_id)
        if version is None:
            if len(backups._members('versions'))+len(backups._pending_members())>=backups.MAX_VERSIONS:
                raise TransferError('media_backup_catalog_capacity')
            name=file.path if local else mapping.relative_path if restored is None else restored.relative_path
            version=dict(id=version_id,object_key=key,saved_ms=backups._clock(),name=name,source=provenance)
            _validate_source_version(version,version_id);current();backups._commit(pending=version)
        elif version['source']!=provenance:raise TransferError('media_backup_original_source_owner_required')
        boundary('source_backup_intent_durable');current()
        if obj is None:
            free=os.fstatvfs(backups._root)
            if free.f_bavail*free.f_frsize<file.size+1024**3:raise TransferError('media_backup_insufficient_space')
            name='object-'+key+'.raw'
            fd=os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=backups._root)
            try:
                file_key=list(backups._key(os.fstat(fd)))
                obj=dict(id=key,size=file.size,sha256=file.sha256,codec='raw',name=name,key=file_key,
                    stored_size=file.size,stored_sha256=file.sha256,raw_name=name,raw_key=file_key,
                    raw_retired=False,trial=False,prepared=True,candidate=None)
                os.fsync(fd);os.fsync(backups._root);current();backups._commit(obj=obj)
            finally:os.close(fd)
        if obj['prepared']:
            if any(backups._record('versions',item)['object_key']==key for item,_ in backups._members('versions')):
                raise TransferError('media_backup_object_not_complete')
            with backups._object(obj,writable=True) as fd:
                try:verify_raw(fd,file.size,file.sha256,current,candidate=True)
                except TransferError as error:
                    if str(error)!='media_backup_original_content_changed':raise
                    current();os.ftruncate(fd,0)
                    for index in range(file.chunks):
                        data=bytearray(reader.read_chunk(index))
                        try:
                            offset=0
                            while offset<len(data):
                                current();written=os.write(fd,data[offset:])
                                if written<=0:raise TransferError('media_backup_source_short_write')
                                offset+=written
                            os.fsync(fd);boundary('source_backup_chunk_durable');current()
                        finally:data[:]=b'\0'*len(data)
                verify_raw(fd,file.size,file.sha256,current,candidate=True)
            obj=dict(obj,prepared=False)
        # Close the writable candidate, then independently reopen/read/hash the
        # exact registered inode read-only before claiming verified payload.
        backups._verify_object(obj)
        boundary('source_backup_payload_verified');current();backups._commit(version=version,obj=obj)
        backups._verify_object(obj);current();boundary('source_backup_complete');current()
        return backups._version(version)
