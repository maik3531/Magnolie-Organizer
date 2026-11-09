"""Actual independent PC source/cache and encrypted private sender; no GUI/OS claim."""
import base64
from hashlib import sha256
from pathlib import Path
import threading

import pytest

from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_transport import echo,deliver as settings_deliver
from test_media_source_sender import handshake,acceptance,request,saved,deliver,message
from test_media_source_media_offer import png
from test_media_source_cache import decode
from magnolie_media_source_pc import NativeCollectionMediaSource
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_source_roots import ProtectedMediaCollectionRoots
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_offer import validate_media_offer
from magnolie_file_transfer import TransferError
from magnolie_file_published_readback import KIND as READBACK,destination_token,encode_body
from magnolie_telefon import strict_json,canonical


@pytest.fixture
def pc(source,tmp_path):
    h=source;h.source.close()
    h.policy=h.preferences.configure(h.preferences.issue_action(),h.policy,enabled=False,mode='manual')
    for field,value in [('enabled',True),('direction','pc_to_phone'),('collection_mode','entire_collection'),('photos_only',False)]:
        h.controller.change(field,value)
    sent=h.controller.send_settings();assert h.wire.receive()==sent
    settings_deliver(h,dict(type='ack',message_id=sent['message_id'],status='accepted',error='none'));echo(h,sent['body'])
    path=tmp_path/'native-pc';path.mkdir(mode=0o700);h.pc_file=path/'new-pc.png';h.raw=png();h.pc_file.write_bytes(h.raw)
    catalog=ProtectedMediaCollectionRoots(h.authority)
    with NativeCollectionRoot(path,lambda:True) as root:
        selected=catalog.add(catalog.issue_action(),catalog.read(),root,'images');h.member=root.inventory().members[0]
    h.selected=selected.roots[0]
    h.policy=h.preferences.bind_collection_roots(h.preferences.issue_action(),h.policy,catalog);catalog.close()
    h.source=NativeCollectionMediaSource(h.preferences,h.mappings,h.controller)
    assert not h.preferences.local_grant(True).grants.receive_files
    try:yield h
    finally:h.source.close()


def freeze_pc(h):return h.source.freeze(h.preferences.issue_action(),h.policy,h.selected,h.member)


def test_actual_pc_only_cache_and_encrypted_media_origin_chunk_saved_readback_remain_not_source_end(pc):
    h=pc;cached=freeze_pc(h)
    intent=strict_json(decode(h,cached.directory/'intent.enc'));proof=strict_json(decode(h,cached.directory/'manifest.enc'))
    assert intent['format']==proof['format']==3 and cached.original_references==proof['original_references']=={}
    assert 'original_mapping_sha256' not in intent and 'original_reference' not in intent
    assert proof['local_origin']==cached.pc_origin and proof['root_catalog']==h.policy.policy.collection_roots.wire()
    assert _NativeSourceJobs(h.authority).lookup(cached.manifest.source_id).body['format']==3
    with h.source.prepared_cache(cached.manifest.source_id) as reader:
        assert b''.join(reader.read_chunk(i) for i in range(cached.manifest.files[0].chunks))==h.raw
    sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    try:
        with pytest.raises(TransferError):sender.send_offer()
        handshake(h,sender)
        assert sender._local().grants.receive_files is False
        offer=sender.send_media_offer();assert h.wire.receive()==offer
        media=validate_media_offer(offer,cached.manifest.sender_id,cached.manifest.receiver_id)
        reference=media.pc_origins[cached.manifest.files[0].id]
        assert not media.originals and reference==dict(format=1,origin_sha256=sha256(b'magnolie-pc-media-origin-v1\0'+canonical(cached.pc_origin)).hexdigest(),previous_publication_sha256=None)
        assert b'native-pc' not in canonical(offer) and b'root_key' not in canonical(offer)
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        restored=bytearray()
        for index in range(cached.manifest.files[0].chunks):
            deliver(h,sender,request(accepted,cached,index));chunk=h.wire.receive()
            restored.extend(base64.b64decode(chunk['body']['data_base64'],validate=True))
        assert restored==h.raw
        deliver(h,sender,saved(accepted,cached));assert sender.observation().body['phase']=='peer_saved'
        file=cached.manifest.files[0]
        context=dict(format=1,offer_id=offer['message_id'],manifest_sha256=cached.manifest.fingerprint,transfer_id=cached.manifest.transfer_id,
            source_id=cached.manifest.source_id,file_id=file.id,size=file.size,sha256=file.sha256,media_type='images',mime_type='image/png',
            publication_sha256='a'*64,row_sha256='d'*64,permission_epoch=accepted['body']['permission_epoch'],readback_nonce='e'*64)
        binding=sender._controls.binding(destination_token(context),sender_is_local=True)
        deliver(h,sender,message(READBACK,encode_body(context,binding),offer['expires_ms']))
        observation=sender.observation();assert observation.body['phase']=='peer_readback'
        assert not observation.permits_retirement and not observation.is_saved_receipt and not observation.grants_read_authority
        assert cached.directory.exists() and h.pc_file.read_bytes()==h.raw
    finally:sender.close()


@pytest.mark.parametrize('fault',['consent','intent','file','catalog','book'])
def test_original_pc_owner_changes_stop_cache_without_repair_or_new_history(pc,fault):
    h=pc;cached=freeze_pc(h);job=_NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)
    if fault=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    elif fault=='intent':h.controller.change('enabled',False)
    elif fault=='file':h.pc_file.write_bytes(png(1))
    elif fault=='catalog':
        catalog=h.preferences.open_collection_roots();catalog.close()
        path=Path(h.authority.binding.native_directory)/catalog._anchor;path.rename(path.with_name(path.name+'.retained'))
    else:
        from magnolie_media_retention import NativeMediaRetention
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:paused=retention.pause()
    with pytest.raises((TransferError,OSError)):
        with h.source.prepared_cache(cached.manifest.source_id) as reader:reader.read_chunk(0)
    assert _NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)==job
    assert cached.directory.exists()
    if fault=='book':
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            retention.publish_saved(paused,strict_json((Path(h.authority.binding.native_directory).parent/'daten.json').read_bytes()))
        with pytest.raises(TransferError):
            with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Restored book revived a retired source')


def test_existing_native_phone_mapping_cannot_be_relabelled_as_new_pc_origin(pc):
    h=pc;catalog=h.preferences.open_collection_roots()
    try:
        with NativeCollectionRoot(h.target.parent,lambda:True) as root:
            snapshot=catalog.add(catalog.issue_action(),catalog.read(),root,'images')
            selected=next(r for r in snapshot.roots if r.key==root.key)
            member=next(m for m in root.inventory().members if m.key==h.record.file_key)
        with pytest.raises(TransferError,match='existing_mapping_required'):
            h.source.freeze(h.preferences.issue_action(),h.policy,selected,member)
        assert not h.source._prepared and not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))
    finally:catalog.close()


def test_actual_cross_root_move_is_known_file_history_not_new_origin(pc):
    h=pc;cached=freeze_pc(h);jobs=_NativeSourceJobs(h.authority);before=jobs.lookup(cached.manifest.source_id)
    h.source.close();other=h.pc_file.parent.with_name('other-pc');other.mkdir(mode=0o700)
    h.pc_file.rename(other/h.pc_file.name)
    catalog=h.preferences.open_collection_roots()
    try:
        with NativeCollectionRoot(other,lambda:True) as root:
            selected=catalog.add(catalog.issue_action(),catalog.read(),root,'images')
            record=next(r for r in selected.roots if r.key==root.key);member=root.inventory().members[0]
        assert member.key==h.member.key and member.birthtime==h.member.birthtime
        origin=dict(cached.pc_origin,root_id=record.id,root_version=record.version,root_key=list(record.key),root_birthtime=list(record.birthtime),mount_id=record.mount_id)
        with pytest.raises(TransferError,match='existing_source_held'):jobs.require_new_pc_origin(origin)
        assert jobs.lookup(cached.manifest.source_id)==before
    finally:catalog.close()


def test_pc_backup_and_owned_native_drain_archive_end_then_independent_offline_restore(pc,tmp_path):
    import os
    from magnolie_media_backups import NativeMediaBackups
    from magnolie_media_source_backup import backup_prepared_source,source_provenance
    from magnolie_media_source_retirement import _NativeSourceRetirement
    from magnolie_file_protection import ExistingFileTransferProtection
    h=pc
    # A separate valid small native image keeps the complete live operation
    # inside its unchanged 60-second action and wire deadlines.
    h.raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
    h.pc_file.write_bytes(h.raw)
    with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:h.member=root.inventory().members[0]
    cached=freeze_pc(h);job=cached.manifest.source_id;root,member,_=h.source._held[job]
    with pytest.raises(TransferError):h.source._handoff_original(object())
    sender=_NativeMediaSourceSender(h.source,job)
    try:
        with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
            backup=backup_prepared_source(backups,h.source,job)
            provenance=source_provenance(backups,backup)
            assert provenance['format']==2 and provenance['local_origin']==cached.pc_origin
            assert 'original_mapping' not in provenance
            with pytest.raises(TransferError,match='pc_restore_publication_owner_required'):backups._restore_lineage(backup)
            handshake(h,sender);offer=sender.send_media_offer();assert h.wire.receive()==offer
            accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
            deliver(h,sender,request(accepted,cached));assert base64.b64decode(h.wire.receive()['body']['data_base64'])==h.raw
            deliver(h,sender,saved(accepted,cached))
            checkpoints=[]
            def checkpoint(phase):
                if phase=='source_retirement_moved':
                    assert root._fd is None and member._owned==()
                    assert retirement._record.body['state']=='archive_planned'
                    with pytest.raises(TransferError):retirement._reader.read_chunk(0)
                    checkpoints.append(phase)
            retirement=_NativeSourceRetirement(sender,backups,backup,boundary=checkpoint)
            assert retirement._journal.lookup(job) is None and root._fd is not None and member._owned
            file=cached.manifest.files[0]
            context=dict(format=1,offer_id=offer['message_id'],manifest_sha256=cached.manifest.fingerprint,transfer_id=cached.manifest.transfer_id,
                source_id=job,file_id=file.id,size=file.size,sha256=file.sha256,media_type='images',mime_type='image/png',
                publication_sha256='a'*64,row_sha256='d'*64,permission_epoch=accepted['body']['permission_epoch'],readback_nonce='e'*64)
            binding=sender._controls.binding(destination_token(context),sender_is_local=True)
            deliver(h,sender,message(READBACK,encode_body(context,binding),offer['expires_ms']))
            ended=retirement.run()
            assert checkpoints==['source_retirement_moved']
            assert ended.body['state']=='archived' and root._fd is None and member._owned==()
            assert job not in h.source._prepared and not h.source._held and h.source._closed.is_set()
            assert not retirement._permits_pc_source_checkpoint(h.source,job)
            assert not cached.directory.exists() and h.pc_file.read_bytes()==h.raw
            archive=Path(h.authority.binding.native_directory)/ended.body['archive']
            archive.rename(archive.with_name('retained-offline-cache-fixture'))
    finally:sender.close()
    h.pc_file.unlink()
    h.authority.close();h.channel.sock.close() # Recovery must not consult a live peer/channel.
    with ExistingFileTransferProtection(h.authority.binding.native_directory) as protection:
        with NativeMediaBackups(h.selected.directory,protection,lambda:True) as offline:
            target=tmp_path/'offline-restored.png';fd=os.open(target,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
            try:offline.restore(backup,fd)
            finally:os.close(fd)
    assert target.read_bytes()==h.raw


def test_pc_cancellation_keeps_source_descriptors_and_book_lane_until_actual_cache_read_drains(pc):
    from magnolie_media_retention import NativeMediaRetention
    h=pc;cached=freeze_pc(h);job=cached.manifest.source_id;root,member,_=h.source._held[job]
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[]
    def boundary(phase):
        if phase=='source_cache_cipher_read':entered.set();assert release.wait(8)
    h.source._boundary=boundary
    def read():
        try:
            with h.source.prepared_cache(job) as reader:reader.read_chunk(0)
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=read);worker.start()
    try:
        assert entered.wait(5);h.source.close()
        assert not ended.is_set() and root._fd is not None and member._owned
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as activity:assert activity is None
    finally:release.set();worker.join(8)
    assert not worker.is_alive() and ended.is_set() and len(errors)==1 and isinstance(errors[0],TransferError)
    assert root._fd is None and member._owned==() and cached.directory.exists()
    assert _NativeSourceJobs(h.authority).lookup(job).state=='cache_ready'


def test_pc_jobs_do_not_relax_legacy_reference_or_accept_malformed_authenticated_origin(pc):
    h=pc;cached=freeze_pc(h);jobs=_NativeSourceJobs(h.authority);record=jobs.lookup(cached.manifest.source_id)
    # Invoke the actual strict protected decoder with freshly authenticated
    # malformed records; do not write or repair the real retained job.
    for mutate in [lambda body:body.update(format=2),lambda body:body.update(original_references={'fake':{}}),
                   lambda body:body['local_origin'].update(file_birthtime=[0,1_000_000_000]),
                   lambda body:body['root_catalog'].update(scope='f'*64),lambda body:body.pop('root_catalog')]:
        body=record.body;mutate(body);cipher=h.authority.protection.seal(canonical(body),jobs._key(cached.manifest.source_id))
        with pytest.raises(TransferError):jobs._decode(cached.manifest.source_id,cipher,jobs._database_key)
    assert jobs.lookup(cached.manifest.source_id)==record


def test_independent_pc_denial_authenticates_and_retains_older_mapping_generations(receiving,tmp_path):
    from test_photo_version_history_safety import version
    connection,association=version(receiving);owner=connection._mappings
    before=owner.read();records=owner._mapping_records(association)
    assert len(records)==2
    for _,record in records:
        with pytest.raises(TransferError,match='existing_mapping_required'):owner.require_independent_native_file(record.file_key)
    new=tmp_path/'independent.png';new.write_bytes(b'new source identity');value=new.stat()
    assert owner.require_independent_native_file((value.st_dev,value.st_ino))==before
    assert owner.read()==before


def test_pc_cancel_during_actual_secure_output_retains_original_handles_and_pending_checkpoint(pc,monkeypatch):
    from magnolie_media_retention import NativeMediaRetention
    h=pc;cached=freeze_pc(h);job=cached.manifest.source_id;root,member,_=h.source._held[job]
    sender=_NativeMediaSourceSender(h.source,job);handshake(h,sender)
    offer=sender.send_media_offer();assert h.wire.receive()==offer
    accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[];send=h.channel.send
    def blocked(packet):
        if packet.get('kind')=='file_transfer.chunk':entered.set();assert release.wait(8)
        return send(packet)
    monkeypatch.setattr(h.channel,'send',blocked)
    def output():
        try:deliver(h,sender,request(accepted,cached))
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=output);worker.start()
    try:
        assert entered.wait(5);sender.close()
        assert not ended.is_set() and root._fd is not None and member._owned
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as activity:assert activity is None
    finally:release.set();worker.join(8);sender.close()
    assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
    assert h.wire.receive()['kind']=='file_transfer.chunk'
    record=sender.observation().body
    assert record['sent_bits']==0 and record['pending_chunk'] is not None and record['phase']=='accepted'
    assert root._fd is None and member._owned==() and cached.directory.exists()


def test_actual_new_inode_at_known_source_path_is_uncertain_reassociation_not_new_origin(pc):
    h=pc;cached=freeze_pc(h);jobs=_NativeSourceJobs(h.authority);before=jobs.lookup(cached.manifest.source_id)
    h.source.close();h.pc_file.rename(h.pc_file.with_name('retained-original-source.png'));h.pc_file.write_bytes(h.raw)
    with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:
        member=next(m for m in root.inventory().members if m.name==h.pc_file.name)
    assert member.key!=h.member.key
    origin=dict(cached.pc_origin,file_key=list(member.key),file_birthtime=list(member.birthtime))
    with pytest.raises(TransferError,match='existing_source_held'):jobs.require_new_pc_origin(origin)
    assert jobs.lookup(cached.manifest.source_id)==before
