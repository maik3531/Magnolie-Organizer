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
    if (set(source)!={'format','job_id','job_nonce','job_version','proof_sha256','book_version','manifest',
            'original_mapping_sha256','original_mapping'} or type(source['format']) is not int or source['format']!=1
            or any(not _hex(source[name]) for name in ('job_nonce','job_version','proof_sha256','book_version','original_mapping_sha256'))
            or type(source['original_mapping']) is not dict or type(source['original_mapping'].get('association')) is not dict):
        raise TransferError('media_backup_source_version_invalid')
    association=source['original_mapping']['association']
    if set(association)!={'source_epoch','photo_id','media_type'}:raise TransferError('media_backup_source_version_invalid')
    mapping=NativeSavedPhotoMapping.parse(source['original_mapping'],PhotoMappingAssociation(**association),source['original_mapping_sha256'])
    manifest=FileManifest.parse(source['manifest'])
    if (len(manifest.files)!=1 or manifest.source_id!=source['job_id'] or _source_version_id(source)!=key
            or value['object_key']!=content_key(manifest.files[0].size,manifest.files[0].sha256)
            or value['name']!=mapping.relative_path or manifest.files[0].path!=mapping.relative_path.rsplit('/',1)[-1]):
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
    from magnolie_media_source import NativeMappedMediaSource
    if (type(backups) is not NativeMediaBackups or type(source) is not NativeMappedMediaSource or not callable(boundary)
            or type(job_id) is not str or job_id not in source._prepared):
        raise TransferError('media_backup_actual_source_preparation_required')
    prepared=source._prepared[job_id];cached=prepared.cache;mapping=prepared.original_mapping
    if (type(mapping) is not NativeSavedPhotoMapping or mapping.destination!=backups.destination
            or backups.protection.native_directory_identity!=source._authority.protection.native_directory_identity
            or cached.original_references!={cached.manifest.files[0].id:mapping.phone_original_reference()}):
        raise TransferError('media_backup_original_source_owner_required')
    with source.prepared_cache(job_id) as reader,backups._operation():
        def current():reader._permission();backups._current();return True
        current();backups._ensure_native_owner();file=cached.manifest.files[0]
        provenance=dict(format=1,job_id=job_id,job_nonce=cached._job_nonce,job_version=cached._job_version,
            proof_sha256=cached.proof_sha256,book_version=prepared.book_version,manifest=cached.manifest.wire(),
            original_mapping_sha256=mapping.protected_record_sha256,original_mapping=mapping.wire())
        version_id=_source_version_id(provenance);key=content_key(file.size,file.sha256)
        before=backups._record('versions',version_id);obj=backups._record('objects',key)
        if before is not None:
            if before['source']!=provenance or obj is None:raise TransferError('media_backup_original_source_owner_required')
            backups._verify_object(obj);current();return backups._version(before)
        version=backups._pending(version_id)
        if version is None:
            if len(backups._members('versions'))+len(backups._pending_members())>=backups.MAX_VERSIONS:
                raise TransferError('media_backup_catalog_capacity')
            version=dict(id=version_id,object_key=key,saved_ms=backups._clock(),name=mapping.relative_path,source=provenance)
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
