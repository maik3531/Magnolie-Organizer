"""Normal authenticated factory/dispatcher with one original PC control owner."""
import base64
from pathlib import Path
import threading

import pytest

from test_media_source_pc import pc,source,mappings,receiving,native
from test_media_source_connection import composition,agree,dispatch
from test_media_source_sender import message,acceptance,request,saved
from test_media_source_media_offer import readback
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
from magnolie_file_transfer import TransferError


def small_source(h):
    h.raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
    h.pc_file.write_bytes(h.raw)
    with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:h.member=root.inventory().members[0]


def prepare(h):
    return h.connection.prepare_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member)


def completed_pc_send(h,service,cached,publication='a'*64,*,complete=True):
    from magnolie_media_backups import NativeMediaBackups
    from magnolie_media_source_backup import backup_prepared_source
    from magnolie_media_source_retirement import _NativeSourceRetirement
    sender=h.connection.open_prepared_media_sender(cached.manifest.source_id)
    offer=sender.send_media_offer();assert h.wire.receive()==offer
    if not complete:return offer # An actual offer is not Saved/readback/END.
    accepted=acceptance(sender,cached,offer);dispatch(h,service,accepted)
    for index in range(cached.manifest.files[0].chunks):
        dispatch(h,service,request(accepted,cached,index));assert base64.b64decode(h.wire.receive()['body']['data_base64'])==h.raw[index*65536:(index+1)*65536]
    packet=saved(accepted,cached);packet['body']['receipts'][0]['receipt_sha256']=publication
    dispatch(h,service,packet);dispatch(h,service,readback(sender,cached,offer,publication=publication))
    assert sender.observation().body['phase']=='peer_readback'
    with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,
            create=not (Path(h.selected.directory.path)/'Backup').exists()) as backups:
        version=backup_prepared_source(backups,sender._source,cached.manifest.source_id)
        ended=_NativeSourceRetirement(sender,backups,version).run()
        assert ended.body['state']=='archived'
    return offer


def test_fresh_completed_pc_successors_use_exact_protected_previous_publications_and_unchanged_native_bytes_create_nothing(pc,native):
    from test_media_source_media_offer import png
    with composition(pc,native[0]) as h:
        small_source(h);controls=agree(h,native[0]);first=prepare(h)
        old_origin=first.pc_origin;initial=completed_pc_send(h,native[0],first)
        assert initial['body']['pc_origins'][first.manifest.files[0].id]['previous_publication_sha256'] is None
        jobs=_NativeSourceJobs(h.authority);before=jobs.lookup(first.manifest.source_id)
        with pytest.raises(TransferError,match='existing_source_held'):prepare(h)
        parent=Path(h.authority.binding.native_directory);files=set(parent.iterdir())
        with pytest.raises(TransferError,match='latest_payload_already_sent'):
            h.connection.prepare_changed_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member)
        assert set(parent.iterdir())==files and jobs.lookup(first.manifest.source_id)==before
        previous='a'*64;job=first.manifest.source_id
        for salt,publication in ((1,'c'*64),(2,'d'*64)):
            h.raw=png(salt);h.pc_file.write_bytes(h.raw)
            with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:
                h.member=next(member for member in root.inventory().members if member.name==h.pc_file.name)
            cached=h.connection.prepare_changed_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member)
            assert cached.pc_origin==old_origin and not cached.original_references
            assert cached.manifest.source_id!=job and cached.manifest.transfer_id!=first.manifest.transfer_id
            offer=completed_pc_send(h,native[0],cached,publication,complete=salt==1)
            origin=offer['body']['pc_origins'][cached.manifest.files[0].id]
            assert origin['previous_publication_sha256']==previous
            assert origin['origin_sha256']==initial['body']['pc_origins'][first.manifest.files[0].id]['origin_sha256']
            assert str(h.pc_file) not in str(offer) and 'file_key' not in str(offer)
            assert jobs.lookup(first.manifest.source_id)==before
            assert h.connection._controls.packet().session_epoch==controls.session_epoch
            assert not h.connection._local().grants.receive_files and not h.connection._controls._remote.grants.send_files
            previous=publication;job=cached.manifest.source_id
        from magnolie_media_source_lineage import _NativeSourceLineage
        from magnolie_media_backups import NativeMediaBackups
        history=_NativeSourceLineage(jobs).lookup()
        assert len(history.records)==3 and history.records[0].body['job_id']==first.manifest.source_id
        assert not history.grants_read_authority
        with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True) as backups:
            assert len(backups.versions())==2 # Third offer is still pending, never a third completion.


def test_completed_pc_entry_cannot_manufacture_missing_or_pending_completion_or_allocate_another_cache(pc,native):
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);parent=Path(h.authority.binding.native_directory)
        before=set(parent.iterdir())
        with pytest.raises(TransferError,match='completed_source_required'):
            h.connection.prepare_changed_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member)
        assert set(parent.iterdir())==before
        cached=prepare(h);original=_NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)
        before=set(parent.iterdir())
        with pytest.raises(TransferError,match='album_worker_busy'):
            h.connection.prepare_changed_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member)
        assert set(parent.iterdir())==before and cached.directory.exists()
        assert _NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)==original


@pytest.mark.parametrize('reason',['replacement','missing_archive','late_catalog'])
def test_completed_pc_entry_holds_reassociation_or_missing_actual_archives_before_new_cache(pc,native,reason,monkeypatch):
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);first=prepare(h);completed_pc_send(h,native[0],first)
        jobs=_NativeSourceJobs(h.authority);original=jobs.lookup(first.manifest.source_id)
        if reason=='replacement':
            h.pc_file.rename(h.pc_file.with_name('retained-original.png'));h.pc_file.write_bytes(h.raw)
            with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:
                h.member=next(member for member in root.inventory().members if member.name==h.pc_file.name)
        elif reason=='missing_archive':
            retired=_NativeSourceRetirementJournal(jobs).lookup(first.manifest.source_id)
            old=Path(h.authority.binding.native_directory)/retired.body['archive']
            old.rename(old.with_name(old.name+'-retained'))
        else:
            original_read=_NativeSourceJobs.completed_pc_origin
            def changed_after_admission(owner,origin):
                previous=original_read(owner,origin)
                with owner._database() as (db,key):
                    db.execute('BEGIN IMMEDIATE');catalog=owner._catalog.verify(db,key)
                    owner._catalog.advance(db,key,catalog)
                return previous
            monkeypatch.setattr(_NativeSourceJobs,'completed_pc_origin',changed_after_admission)
        parent=Path(h.authority.binding.native_directory);before=set(parent.iterdir());raw=h.pc_file.read_bytes()
        with pytest.raises((TransferError,FileNotFoundError)) as denied:
            h.connection.prepare_changed_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member)
        if reason=='late_catalog':assert str(denied.value)=='media_collection_original_predecessor_changed'
        assert set(parent.iterdir())==before and jobs.lookup(first.manifest.source_id)==original
        assert h.pc_file.read_bytes()==raw and not list(parent.glob('.magnolie-source-*.part'))


def test_completed_pc_entry_checks_revocation_during_real_fresh_hash_before_any_cache_or_new_job(pc,native,monkeypatch):
    from magnolie_media_source_collection import _CollectionReadLease
    from test_media_source_media_offer import png
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);first=prepare(h);completed_pc_send(h,native[0],first)
        h.raw=png(3);h.pc_file.write_bytes(h.raw)
        with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:
            h.member=next(member for member in root.inventory().members if member.name==h.pc_file.name)
        parent=Path(h.authority.binding.native_directory);before=set(parent.iterdir())
        original=_NativeSourceJobs(h.authority).lookup(first.manifest.source_id);revoked=[];reads=[]
        read=_CollectionReadLease.read_exact
        def actual_read(owner,offset,count):
            data=read(owner,offset,count)
            reads.append((offset,count))
            if len(reads)>=3 and offset==0 and count==65536:revoked.append(True)
            return data
        monkeypatch.setattr(_CollectionReadLease,'read_exact',actual_read)
        with pytest.raises(TransferError):
            h.connection.prepare_changed_collection_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.selected,h.member,
                native_current=lambda:not revoked)
        assert revoked and set(parent.iterdir())==before and h.pc_file.read_bytes()==h.raw
        assert _NativeSourceJobs(h.authority).lookup(first.manifest.source_id)==original


def test_normal_pc_factory_dispatcher_uses_original_session_without_pc_receive_phone_read_or_grant_changes(pc,native):
    from magnolie_media_backups import NativeMediaBackups
    from magnolie_media_source_backup import backup_prepared_source
    from magnolie_media_source_retirement import _NativeSourceRetirement
    with composition(pc,native[0]) as h:
        small_source(h);controls=agree(h,native[0]);owner=h.connection._local().owner
        cached=prepare(h);sender=h.connection.open_prepared_media_sender(cached.manifest.source_id)
        assert sender._source is h.connection._media_pc_source and sender._controls is h.connection._controls
        assert sender._connection is h.connection and not h.connection._media_source._prepared
        assert not h.connection._local().grants.receive_files and not h.connection._controls._remote.grants.send_files
        offer=sender.send_media_offer();assert h.wire.receive()==offer and offer['body']['format']==2
        accepted=acceptance(sender,cached,offer);dispatch(h,native[0],accepted)
        dispatch(h,native[0],request(accepted,cached));assert base64.b64decode(h.wire.receive()['body']['data_base64'])==h.raw
        dispatch(h,native[0],saved(accepted,cached));assert sender.observation().body['phase']=='peer_saved'
        dispatch(h,native[0],readback(sender,cached,offer));assert sender.observation().body['phase']=='peer_readback'
        old_source=sender._source;root,member,_=old_source._held[cached.manifest.source_id]
        with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
            backup=backup_prepared_source(backups,old_source,cached.manifest.source_id)
            ended=_NativeSourceRetirement(sender,backups,backup).run()
            assert ended.body['state']=='archived' and root._fd is None and member._owned==()
        assert h.connection._media_sender is None and not cached.directory.exists()
        after=h.connection._controls.packet()
        assert after.session_epoch==controls.session_epoch and after.grants==controls.grants and h.connection._local().owner is owner
        assert h.pc_file.read_bytes()==h.raw
        # A different actual file may use a fresh native owner after real END,
        # without reviving the old one or rotating shared controls/grants.
        h.pc_file=h.pc_file.with_name('second-pc.png');h.pc_file.write_bytes(h.raw)
        with NativeCollectionRoot(h.pc_file.parent,lambda:True) as source:
            h.member=next(m for m in source.inventory().members if m.name==h.pc_file.name)
        next_cache=prepare(h)
        assert h.connection._media_pc_source is not old_source and old_source._closed.is_set()
        record=_NativeSourceJobs(h.authority).lookup(next_cache.manifest.source_id)
        assert record.body['lineage']['previous_job']==cached.manifest.source_id
        with pytest.raises(TransferError,match='lineage_pending_job'):
            _NativeSourceJobs(h.authority).completed_pc_origin(cached.pc_origin)
        current=h.connection._controls.packet()
        assert current.session_epoch==controls.session_epoch and current.grants==controls.grants


def test_normal_pc_prepare_requires_current_positive_ack_before_any_source_cache(pc,native):
    with composition(pc,native[0]) as h:
        with pytest.raises(TransferError,match='current_send_control_required'):prepare(h)
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None
        assert not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def test_normal_pc_preparation_cannot_renew_under_new_remote_session_even_same_persistent_permission_epoch(pc,native):
    with composition(pc,native[0]) as h:
        small_source(h);controls=agree(h,native[0]);binding=h.connection._controls.binding('0'*64,sender_is_local=True)
        cached=prepare(h);job=cached.manifest.source_id;jobs=_NativeSourceJobs(h.authority);before=jobs.lookup(job)
        changed=FileControlPacket(FileGrantState(1,'6'*64,False,True),'a'*64,1,controls.challenge)
        dispatch(h,native[0],message(CONTROL,changed.wire()));assert h.wire.receive()['kind']==CONTROL
        assert h.connection._controls.binding('0'*64,sender_is_local=True)==binding
        with pytest.raises(TransferError,match='original_send_binding_required'):
            with h.connection._media_pc_source.prepared_cache(job):pytest.fail('Later ACK replaced the original admitted source session')
        assert jobs.lookup(job)==before and cached.directory.exists()


def test_pending_pc_preparation_excludes_mapped_copy_plan_and_worker_before_source_io(pc,native,monkeypatch):
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);cached=prepare(h)
        monkeypatch.setattr(h.connection._media_source,'_file',lambda *args:pytest.fail('Mapped file opened during a pending PC preparation'))
        for method in (h.connection.prepare_media_source,h.connection.plan_media_source,h.connection.prepare_changed_media_source):
            with pytest.raises(TransferError,match='album_worker_busy'):
                method(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
        with pytest.raises(TransferError,match='album_worker_busy'):h.connection.start_mapped_media_worker(h.connection.issue_receive_action())
        for invalid in ([],{},None):
            with pytest.raises(TransferError,match='actual_preparation_required'):h.connection.open_prepared_media_sender(invalid)
        assert set(h.connection._media_pc_source._prepared)=={cached.manifest.source_id} and h.connection._mapped_worker is None


def test_normal_pc_close_drains_actual_secure_output_before_releasing_original_source_and_authority(pc,native,monkeypatch):
    import os
    import sqlite3
    from magnolie_file_protection import ExistingFileTransferProtection
    from magnolie_media_retention import NativeMediaRetention
    from magnolie_telefon import strict_json
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);cached=prepare(h);sender=h.connection.open_prepared_media_sender(cached.manifest.source_id)
        root,member,_=sender._source._held[cached.manifest.source_id]
        authority_fd=h.authority.protection._root_fd
        offer=sender.send_media_offer();assert h.wire.receive()==offer
        accepted=acceptance(sender,cached,offer);dispatch(h,native[0],accepted)
        entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[];send=h.channel.send
        def blocked(packet):
            if packet.get('kind')=='file_transfer.chunk':entered.set();assert release.wait(8)
            return send(packet)
        monkeypatch.setattr(h.channel,'send',blocked)
        def output():
            try:dispatch(h,native[0],request(accepted,cached))
            except BaseException as error:errors.append(error)
            finally:ended.set()
        worker=threading.Thread(target=output);worker.start()
        try:
            assert entered.wait(5);assert not h.connection.close()
            assert not ended.is_set() and root._fd is not None and member._owned
            assert not h.authority.protection._closed and os.fstat(authority_fd)
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                with retention.activity() as activity:assert activity is None
        finally:release.set();worker.join(8)
        assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
        assert h.wire.receive()['kind']=='file_transfer.chunk'
        assert root._fd is None and member._owned==() and h.authority.protection._closed
        # ExistingFileTransferProtection intentionally retains the numeric field
        # after close; verify the actual OS descriptor, not a None assignment.
        with pytest.raises(OSError):os.fstat(authority_fd)
        with ExistingFileTransferProtection(h.authority.binding.native_directory) as protection:
            with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
                blob=db.execute('SELECT value FROM meta WHERE key=?',(sender._journal._key,)).fetchone()[0]
            observation=strict_json(protection.unseal(blob,sender._journal._key))
        assert observation['phase']=='accepted' and observation['sent_bits']==0 and observation['pending_chunk'] is not None
        assert cached.directory.exists() and h.pc_file.read_bytes()==h.raw


def test_normal_pc_only_from_fresh_settings_never_creates_phone_mapping_or_receive_destination(native,tmp_path,monkeypatch):
    import socket
    from types import SimpleNamespace
    import magnolie_telefon as phone
    from magnolie_file_native_authority import capture_authenticated_binding
    from magnolie_file_desktop_connection import NativeDesktopFileConnection
    from magnolie_media_source_roots import ProtectedMediaCollectionRoots
    from magnolie_media_retention import NativeMediaRetention
    from test_media_transport import PeerWire
    service,peer,_=native
    # Actual normal product classes; private native feature gate only, not
    # production discovery enablement or a deserialized RECEIVE choice.
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    peer['capabilities']['items']['device_status']['versions'].append(23);service.store.save_peers()
    left,right=socket.socketpair();left.settimeout(2);right.settimeout(2)
    channel=phone.SecureChannel(left,bytes([3])*16,bytes([1])*32,bytes([1])*4,bytes([2])*32,bytes([2])*4)
    binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
    service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
    connection=service.open_native_file_connection(peer['device_id'],peer['static_public'],channel,binding.generation)
    try:
        book=tmp_path/'daten.json';book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":0}}}',encoding='utf-8');book.chmod(0o600)
        with NativeMediaRetention(service.store.root) as retention:assert retention.adopt_existing_saved()
        prefs=connection._preferences
        assert prefs.read().policy is None and connection._mappings.read().count==0
        policy=prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=True,videos=False)
        h=SimpleNamespace(connection=connection,authority=connection._authority,preferences=prefs,controller=connection._media_transport,
            peer=peer,channel=channel,wire=PeerWire(right),pc_file=tmp_path/'fresh-pc'/'new-pc.png')
        h.pc_file.parent.mkdir(mode=0o700);h.raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
        h.pc_file.write_bytes(h.raw);catalog=ProtectedMediaCollectionRoots(h.authority)
        try:
            with NativeCollectionRoot(h.pc_file.parent,lambda:True) as root:
                h.member=root.inventory().members[0]
                h.selected=catalog.add(catalog.issue_action(),catalog.read(),root,'images').roots[0]
            prefs.bind_collection_roots(prefs.issue_action(),policy,catalog)
        finally:catalog.close()
        for field,value in [('enabled',True),('direction','pc_to_phone'),('collection_mode','entire_collection'),('photos_only',False)]:
            h.controller.change(field,value)
        agree(h,service);cached=prepare(h);sender=connection.open_prepared_media_sender(cached.manifest.source_id)
        offer=sender.send_media_offer();assert h.wire.receive()==offer
        accepted=acceptance(sender,cached,offer);dispatch(h,service,accepted)
        dispatch(h,service,request(accepted,cached));assert base64.b64decode(h.wire.receive()['body']['data_base64'])==h.raw
        dispatch(h,service,saved(accepted,cached));dispatch(h,service,readback(sender,cached,offer))
        assert sender.observation().body['phase']=='peer_readback'
        observed=prefs.read().policy
        assert not observed.enabled and observed.destination is None and observed.mapping_store is None
        assert not connection._local().grants.receive_files and not connection._controls._remote.grants.send_files
        assert connection._mappings.read().count==0 and not (Path(service.store.root)/connection._mappings._name).exists()
        assert cached.original_references=={} and h.pc_file.read_bytes()==h.raw
    finally:service._end_native_file_connection(channel);left.close();right.close()
