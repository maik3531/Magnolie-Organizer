"""Future-only native animation grouping keeps original jobs and PC edits."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import ALBUM
from test_file_desktop_album_worker import prepared,phone_batches
from test_photo_desktop_workflow import native_ui,converge_controls


def animation(fixture):
    base=prepared(fixture)[0]
    return replace(base,files=(replace(base.files[0],path='Camera/old.gif'),))


@pytest.mark.parametrize('grouped',[False,True])
def test_special_folder_origin_uses_authenticated_manifest_not_the_album_prefix(receiving,grouped):
    from magnolie_photo_destination import plan_special_folder_path
    service,peer,channel,connection,target=receiving
    converge_controls(service,peer,channel)
    original='Animationen/Camera/old.gif'
    full=animation(receiving);full=replace(full,files=(replace(full.files[0],path=original),))
    if grouped:connection.set_future_animation_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    with phone_batches(receiving,[full],media_kinds={original:'animation'}) as (_,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(40) and worker.progress()['state']=='complete',worker.progress()
        assert not errors and len(saved)==1
    before,mappings,next_cursor=connection._mappings.candidate_page('images')
    assert next_cursor is None
    mapping,=mappings
    wire_before=channel.send.call_count
    accepted_path=('Animationen/' if grouped else '')+original
    file=target/accepted_path;file.write_bytes(b'edited local bytes')
    edited=(file.stat().st_ino,file.read_bytes())
    with pytest.raises(TransferError,match='original_job_required'):
        connection.inspect_special_folder_origin(connection.issue_receive_action(),mapping.association,'f'*64)
    result=connection.inspect_special_folder_origin(connection.issue_receive_action(),mapping.association,mapping.protected_record_sha256)
    assert (result.original_path,result.mapped_path,result.was_animation,result.was_capture)==(original,accepted_path,grouped,False)
    proposed=plan_special_folder_path(result.original_path,result.mapped_path,was_animation=result.was_animation,
        was_capture=result.was_capture,verified_animation=False,verified_capture=False,setting='animation',separate=True) if not grouped else None
    assert proposed is None # Historical media label is not current-byte eligibility.
    assert (file.stat().st_ino,file.read_bytes())==edited and connection._mappings.read()==before
    assert channel.send.call_count==wire_before


def test_saved_job_and_edited_animation_can_prepare_exact_local_journal_without_touching_receive_history(receiving,monkeypatch):
    from contextlib import closing
    import os
    from test_media_relocation_record import ANIMATED
    from magnolie_media_relocation_record import MediaRelocationRecord, RelocationFileWitness, bind_relocation_selection
    from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal
    from magnolie_media_retention import NativeMediaActivity, NativeMediaRetention
    from magnolie_media_source import NativeMappedMediaSource
    from magnolie_photo_destination import plan_special_folder_path
    from magnolie_photo_plan import NativePhotoAssociation, NativePhotoBaseline, NativePhotoObservation, PhotoContentWitness, compare_photo
    from magnolie_transfer_job_index import ProtectedTransferJobIndex

    service,peer,channel,connection,target=receiving
    converge_controls(service,peer,channel)
    full=animation(receiving)
    with phone_batches(receiving,[full],media_kinds={'Camera/old.gif':'animation'}) as (_,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(40) and worker.progress()['state']=='complete',worker.progress()
        assert not errors and len(saved)==1
    mapping_snapshot,(mapping,),_=connection._mappings.candidate_page('images')
    preference_snapshot=connection._preferences.read();jobs=connection._catalog.jobs();messages=channel.send.call_count
    protection=connection._authority.protection
    with connection._catalog.inspect_jobs() as (parent,catalog_jobs):
        job=next(item for item in catalog_jobs if item.owner==mapping.job_owner)
        accepted=job.accepted
        with ProtectedTransferJobIndex(parent,accepted.manifest,accepted.binding,connection._receive_binding,
                protection.seal,protection.unseal,owner=job.owner,accepted=accepted) as index:
            with index._locked():
                receipt,=index.saved_receipts()
    assert receipt.protected_record_sha256==mapping.receipt_sha256
    origin=connection.inspect_special_folder_origin(connection.issue_receive_action(),mapping.association,mapping.protected_record_sha256)
    original=target/origin.mapped_path;original.write_bytes(ANIMATED)
    planned=plan_special_folder_path(origin.original_path,origin.mapped_path,was_animation=origin.was_animation,
        was_capture=origin.was_capture,verified_animation=True,verified_capture=False,setting='animation',separate=True)
    destination=target/planned
    destination.parent.parent.mkdir(mode=0o700);destination.parent.mkdir(mode=0o700)
    def key(path):
        info=path.stat();return info.st_dev,info.st_ino
    with NativeMediaRetention(connection._authority.binding.native_directory) as book:
        saved_book=book.saved_book_version()
    record=MediaRelocationRecord('4'*32,'0'*64,saved_book,preference_snapshot.version,origin.mapping_sha256,key(target),
        mapping.parent_keys,(key(target),key(destination.parent.parent),key(destination.parent)),origin.mapped_path,planned,
        RelocationFileWitness(mapping.file_key,len(ANIMATED),sha256(ANIMATED).hexdigest()))
    assert record.file.sha256!=mapping.saved_sha256
    selection=bind_relocation_selection((record,),occupied=());confirmed=selection[0].selection_sha256
    def original_current():
        return (connection._mappings.lookup((mapping.association,))==(mapping_snapshot,(mapping,))
            and connection._preferences.read()==preference_snapshot and connection._catalog.jobs()==jobs)
    with closing(ProtectedMediaRelocationJournal(connection._authority)) as journal:
        assert record.observe_native(mapping.destination,original_current,require_animation=True)=='at_source'
        prepared=journal.prepare(journal.issue_action(),journal.read(),selection,confirmed,mapping.destination,require_original=original_current)
        assert journal.require_prepared(prepared.version,confirmed).records==selection
        assert original_current() and original.read_bytes()==ANIMATED and not destination.exists()
        with pytest.raises(TransferError,match='moved_mapping_required'):
            journal.resolve_moved_read_location(prepared,mapping,require_original=original_current)
        committed=journal.move_prepared_animation(journal.issue_action(),prepared,0,mapping.destination,
            require_original=original_current)
        assert committed.attempts==(0,) and committed.outcomes[0][1].phase=='moved'
        with pytest.raises(TransferError,match='original_journal_changed'):
            journal.resolve_moved_read_location(prepared,mapping,require_original=original_current)
        def content_changed_at_relocated_path():
            location=journal.resolve_moved_read_location(committed,mapping,require_original=original_current)
            with NativeMappedMediaSource._file(location,original_current) as (fd,length,_,unchanged):
                raw=os.pread(fd,length,0);unchanged();assert len(raw)==length
                return (length,sha256(raw).hexdigest())!=(mapping.saved_size,mapping.saved_sha256)
        def observe(*,record=mapping,check=original_current):
            return journal.observe_moved_saved_target(committed,record,accepted,receipt,connection._receive_binding,
                require_original=check)
        association=NativePhotoAssociation(accepted.binding,mapping.association.source_epoch,mapping.association.photo_id,
            mapping.protected_record_sha256)
        saved_content=PhotoContentWitness(receipt.sha256,receipt.size)
        baseline=NativePhotoBaseline(association,saved_content,receipt.protected_record_sha256)
        phone=NativePhotoObservation('present',saved_content,insertion_proven=True)
        with pytest.raises(TransferError,match='original_receipt_changed'):
            observe(record=replace(mapping,receipt_sha256='0'*64))
        with pytest.raises(TransferError,match='lease_changed'):
            observe(check=lambda:False)
        with NativeMediaActivity(connection._authority.binding.native_directory) as activity:
            with activity.activity(exclusive=True) as exclusive:
                assert exclusive is not None
                with pytest.raises(TransferError,match='activity_busy'):observe()
        assert content_changed_at_relocated_path() # The pre-move local edit is still an edit.
        changed=observe()
        assert changed.saved_record_sha256==receipt.protected_record_sha256 and changed.observation.managed
        assert not changed.is_saved_receipt and not changed.grants_write_authority
        assert compare_photo(association,baseline,phone,changed.observation).kind=='keep_local_edit'
        destination.write_bytes(b'hello') # Restore the exact saved fixture bytes, same inode.
        assert not content_changed_at_relocated_path() # New path alone is not a change.
        assert observe().observation.content==saved_content
        assert compare_photo(association,baseline,phone,observe().observation).kind=='unchanged'
        local_edit=b'edited again after moving'
        destination.write_bytes(local_edit)
        assert content_changed_at_relocated_path()
        located=journal.resolve_moved_read_location(committed,mapping,require_original=original_current)
        assert located.original==mapping and located.original.saved_sha256==sha256(b'hello').hexdigest()
        assert located.relative_path==planned and located.parent_keys==record.target_parents
        assert (target/located.relative_path).read_bytes()==local_edit and key(destination)==mapping.file_key
        read=os.read
        injected=[]
        def recreate_source_during_read(fd,count):
            data=read(fd,count)
            info=os.fstat(fd)
            if not injected and data and (info.st_dev,info.st_ino)==mapping.file_key:
                original.write_bytes(b'concurrent original-path occupant')
                injected.append(True)
            return data
        with monkeypatch.context() as patch:
            patch.setattr(os,'read',recreate_source_during_read)
            with pytest.raises(TransferError,match='original_file_changed'):observe()
        assert injected and original.read_bytes()==b'concurrent original-path occupant'
        original.write_bytes(b'unrelated new original')
        with pytest.raises(TransferError,match='original_file_changed'):observe()
        with pytest.raises(TransferError,match='original_file_changed'):
            journal.resolve_moved_read_location(committed,mapping,require_original=original_current)
    assert original_current() and channel.send.call_count==messages
    assert original.read_bytes()==b'unrelated new original' and destination.read_bytes()==local_edit


@pytest.mark.parametrize('capture',[False,True],ids=['animations_only','camera_and_animations'])
def test_gtk_layout_applies_only_to_new_animations_and_preserves_pc_edits_and_original_grants(receiving,request,capture):
    service,peer,channel,connection,target=receiving;converge_controls(service,peer,channel)
    first=animation(receiving)
    photos={'Camera/old.gif':sha256(b'old-photo').hexdigest(),'Camera/new.gif':sha256(b'new-photo').hexdigest(),
        'Camera/still.jpg':sha256(b'still-photo').hexdigest()}
    kinds={path:'animation' if path.endswith('.gif') else 'image' for path in photos}
    session=connection.desktop_session();session._local_enabled(True)
    action=native_ui(service,peer,request)
    with phone_batches(receiving,[first],photo_ids=photos,media_kinds=kinds):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(30) and worker.progress()['state']=='complete',worker.progress()
    original=target/'Camera/old.gif';original.write_bytes(b'keep PC animation edit')
    before=(original.stat().st_ino,original.read_bytes())
    binding=connection._receive_binding();grant=connection._preferences.local_grant(True).grants
    records=connection._mappings.read();jobs=connection._catalog.jobs()
    session._automatic_paused=True
    action(dict(action='animations_separate',historical_choice='keep_existing'))
    assert session.join(15) and session.snapshot()['separate_animations'],session.snapshot()
    if capture:
        action(dict(action='captures_separate',historical_choice='keep_existing'))
        assert session.join(15) and session.snapshot()['separate_own_recordings'],session.snapshot()
    assert session._automatic_paused
    assert connection._receive_binding()==binding and connection._preferences.local_grant(True).grants==grant
    assert connection._mappings.read()==records and connection._catalog.jobs()==jobs
    files=(first.files[0],replace(first.files[0],id='e'*32,path='Camera/new.gif'),
        replace(first.files[0],id='d'*32,path='Camera/still.jpg'))
    full=replace(first,source_id='f'*32,transfer_id='f'*32,files=files,total_bytes=15)
    with phone_batches(receiving,[full],photo_ids=photos,media_kinds=kinds,block_chunk=True) as (chunks,saved,entered,release,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10),worker.progress()
        with pytest.raises(TransferError,match='already_active'):
            worker._call(lambda:connection.set_future_animation_layout(connection.issue_receive_action(),separate=False,historical_choice='keep_existing'))
        release.set();assert worker.join(30),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert chunks==[files[1].id,files[2].id] and len(saved)==1
    prefix='Eigene Aufnahmen/' if capture else ''
    grouped=target/(prefix+'Animationen/Camera/new.gif');assert grouped.read_bytes()==b'hello'
    assert (target/(prefix+'Camera/still.jpg')).read_bytes()==b'hello' and not (target/(prefix+'Animationen/Camera/still.jpg')).exists()
    assert not (target/'Camera/new.gif').exists() and (original.stat().st_ino,original.read_bytes())==before
    grouped_before=(grouped.stat().st_ino,grouped.read_bytes())
    action(dict(action='animations_together',historical_choice='keep_existing'))
    assert session.join(15) and not session.snapshot()['separate_animations'],session.snapshot()
    assert connection._receive_binding()==binding and connection._preferences.local_grant(True).grants==grant
    with phone_batches(receiving,[full],photo_ids=photos,media_kinds=kinds) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(30) and worker.progress()['state']=='complete',worker.progress()
        assert not errors and not chunks and not saved
    assert (grouped.stat().st_ino,grouped.read_bytes())==grouped_before
    assert (original.stat().st_ino,original.read_bytes())==before


def test_layout_change_keeps_stopped_original_acceptance_and_resume_target(receiving):
    connection=receiving[3];full=animation(receiving);kinds={'Camera/old.gif':'animation'}
    with phone_batches(receiving,[full],media_kinds=kinds,block_chunk=True) as (_,_,entered,release,_):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        worker.stop();release.set();assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='canceled',worker.progress()
    connection.set_future_animation_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    with phone_batches(receiving,[full],media_kinds=kinds,resume_job=job,resume_media=history) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(45),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert not chunks and len(saved)==1
        assert connection._catalog.jobs()[0].accepted==job.accepted
        assert (receiving[4]/'Camera/old.gif').read_bytes()==b'hello'
        assert not (receiving[4]/'Animationen/Camera/old.gif').exists()


@pytest.mark.parametrize('choice',[None,'move_existing','copy_existing',True])
def test_future_layout_requires_explicit_keep_existing_decision(receiving,choice):
    connection=receiving[3];before=connection._preferences.read();grant=connection._preferences.local_grant(True).grants
    with pytest.raises(TransferError,match='historical_layout_choice_required'):
        connection.set_future_animation_layout(connection.issue_receive_action(),separate=True,historical_choice=choice)
    assert connection._preferences.read()==before and connection._preferences.local_grant(True).grants==grant


@pytest.mark.parametrize('body',[dict(action='animations_separate'),
    dict(action='animations_together',historical_choice='move_existing'),
    dict(action='inspect_recovery',historical_choice='keep_existing'),
    dict(action='animations_separate',historical_choice='keep_existing',album_id='other')])
def test_layout_service_refuses_implicit_or_unimplemented_historical_decisions(receiving,body):
    from magnolie_telefon import fingerprint,unb64
    service,peer,_,connection,_=receiving
    with pytest.raises(ValueError,match='invalid_action'):
        service.photo_sync_action(peer['device_id'],fingerprint(unb64(peer['static_public'],32)),body)
    assert connection._desktop_session is None and connection._album_worker is None


def test_idempotent_layout_still_requires_live_explicit_native_action(receiving,monkeypatch):
    from magnolie_photo_destination import NativePhotoDestinationAction
    prefs=receiving[3]._preferences
    before=prefs.set_animation_layout(prefs.issue_action(),prefs.read(),separate=False,historical_choice='keep_existing')
    clock=[1000];action=NativePhotoDestinationAction(prefs,lambda:clock[0]);snapshot=prefs._snapshot
    def expired_readback():
        result=snapshot();clock[0]+=60_000;return result
    with monkeypatch.context() as patch:
        patch.setattr(prefs,'_snapshot',expired_readback)
        with pytest.raises(TransferError,match='action_not_current'):
            prefs.set_animation_layout(action,before,separate=False,historical_choice='keep_existing')
    assert prefs.read()==before
