"""#488 actual selected-root offer composition, never physical Android acceptance."""
import base64
from pathlib import Path

import pytest

from test_media_source_pc import pc,source,mappings,receiving,native
from test_media_source_pc_connection import small_source
from test_media_source_connection import composition,agree,dispatch
from test_media_source_worker import start
from test_media_source_sender import acceptance,request,saved
from test_media_source_media_offer import readback
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_retirement import _NativeSourceRetirementJournal


def serve_file(h,service,worker,offer,publication):
    assert offer['kind']=='file_transfer.media_offer'
    sender=h.connection._media_sender;cache=sender._cache
    assert len(cache.manifest.files)==1 and not cache.original_references
    accepted=acceptance(sender,cache,offer);dispatch(h,service,accepted)
    for index in range(cache.manifest.files[0].chunks):
        dispatch(h,service,request(accepted,cache,index))
        chunk=base64.b64decode(h.wire.receive()['body']['data_base64'])
        assert chunk==(h.pc_file.parent/cache.manifest.files[0].path).read_bytes()[index*65536:(index+1)*65536]
    packet=saved(accepted,cache);packet['body']['receipts'][0]['receipt_sha256']=publication
    dispatch(h,service,packet)
    assert _NativeSourceRetirementJournal(_NativeSourceJobs(h.authority)).lookup(cache.manifest.source_id) is None
    h.wire.sock.settimeout(.2)
    with pytest.raises(TimeoutError):h.wire.receive() # Saved never starts the next original offer.
    h.wire.sock.settimeout(30)
    dispatch(h,service,readback(sender,cache,offer,publication=publication))
    return sender,cache


def test_actual_selected_collection_composes_two_original_offers_only_after_each_raw_backup_and_source_end_then_freshly_skips_unchanged(pc,native):
    with composition(pc,native[0]) as h:
        small_source(h);(h.pc_file.parent/'second.png').write_bytes(h.pc_file.read_bytes())
        controls=agree(h,native[0]);owner=h.connection._local().owner
        h.wire.sock.settimeout(30);workers=[];completed=[];publications={};session=h.connection.desktop_session()
        try:
            from test_media_source_worker import warm_metadata
            import magnolie_telefon as phone
            warm_metadata(h,native[0])
            native[0].photo_sync_action(h.peer['device_id'],phone.fingerprint(phone.unb64(h.peer['static_public'],32)),{'action':'sync_shared'})
            first_offer=h.wire.receive();worker=h.connection._mapped_worker;assert worker is not None
            workers.append(worker);assert worker._book_fence is not None
            for publication in ('a'*64,'c'*64):
                offer=h.wire.receive() if completed else first_offer
                if completed:
                    previous_sender,previous_cache=completed[-1]
                    retired=_NativeSourceRetirementJournal(_NativeSourceJobs(h.authority)).lookup(previous_cache.manifest.source_id)
                    assert retired is not None and retired.body['state']=='archived'
                    assert previous_sender._source._closed.is_set() and not previous_sender._source._held
                    archive=Path(h.authority.binding.native_directory)/retired.body['archive']
                    value=archive.stat();assert (value.st_dev,value.st_ino)==previous_cache.root_key
                    # This is the existing bounded reusable cache SLOT, not a
                    # job pathname. Its new native inode must not be confused
                    # with the old actual retired root/ended original owner.
                    current=h.connection._media_sender._cache
                    assert current.manifest.source_id!=previous_cache.manifest.source_id and current.root_key!=previous_cache.root_key
                    assert worker.progress()['saved_files']==1
                assert str(h.pc_file.parent) not in str(offer) and 'file_key' not in str(offer)
                completed.append(serve_file(h,native[0],worker,offer,publication))
                publications[completed[-1][1].manifest.files[0].path]=publication
            assert worker.join(60),worker.progress()
            assert worker.progress()['state']=='complete' and worker.progress()['saved_files']==2,worker.progress()
            assert worker.progress()['known_files']==1 # Unchanged original mapped member also actually checked.
            assert session.join(10) and session.snapshot()['state']=='complete',session.snapshot()
            assert session.snapshot()['saved_files']==2 and session.snapshot()['known_files']==1
            jobs=_NativeSourceJobs(h.authority);before=[jobs.lookup(cache.manifest.source_id) for _,cache in completed]
            second=start(h);workers.append(second);assert second.join(150),second.progress()
            assert second.progress()['state']=='complete' and second.progress()['known_files']==3,second.progress()
            assert second.progress()['saved_files']==0 and not second.progress()['filtered_files']
            assert [jobs.lookup(cache.manifest.source_id) for _,cache in completed]==before
            from test_media_source_media_offer import png
            h.raw=png(5);h.pc_file.write_bytes(h.raw)
            third=start(h);workers.append(third);offer=h.wire.receive();successor=h.connection._media_sender._cache
            origin=offer['body']['pc_origins'][successor.manifest.files[0].id]
            assert origin['previous_publication_sha256']==publications[h.pc_file.name]
            serve_file(h,native[0],third,offer,'d'*64)
            assert third.join(60),third.progress()
            assert third.progress()['state']=='complete' and third.progress()['saved_files']==1 and third.progress()['known_files']==2,third.progress()
            assert [jobs.lookup(cache.manifest.source_id) for _,cache in completed]==before
            assert h.connection._local().owner is owner and h.connection._controls.packet().grants==controls.grants
            assert not h.connection._local().grants.receive_files and not h.connection._controls._remote.grants.send_files
            assert h.connection._mapped_worker is None and h.connection._media_sender is None
            assert len(list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.retired')))==3
        finally:
            active=h.connection._mapped_worker
            if active is not None and active not in workers:workers.append(active)
            for active in workers:active.stop();assert active.join(30),active.progress()
            session.start('stop');assert session.join(30),session.snapshot()


def test_edit_after_actual_individual_source_end_cannot_turn_a_completed_file_into_whole_collection_completion(pc,native,monkeypatch):
    from magnolie_media_source_worker import NativeMappedMediaWorker
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);original=h.pc_file.read_bytes()
        archive=NativeMappedMediaWorker._archive;edited=[]
        def edit_after_end(worker,sender,record):
            archive(worker,sender,record)
            assert sender._source._closed.is_set() and not sender._source._held
            raw=bytearray(original);raw[-1]^=1;h.pc_file.write_bytes(raw);edited.append(bytes(raw))
        monkeypatch.setattr(NativeMappedMediaWorker,'_archive',edit_after_end)
        h.wire.sock.settimeout(30);worker=start(h)
        try:
            serve_file(h,native[0],worker,h.wire.receive(),'a'*64)
            assert worker.join(60),worker.progress()
            assert worker.progress()['state']=='held' and worker.progress()['error']=='media_collection_original_inventory_changed',worker.progress()
            assert worker.progress()['saved_files']==1 and h.pc_file.read_bytes()==edited[0]
            assert h.connection._media_sender is None and h.connection._mapped_worker is None
            assert len(list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.retired')))==1
        finally:worker.stop();assert worker.join(30),worker.progress()


def test_collection_photos_only_filters_actual_non_camera_metadata_without_cache_or_false_known_publication(pc,native):
    with composition(pc,native[0]) as h:
        small_source(h);h.controller.change('photos_only',True);agree(h,native[0])
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='complete' and worker.progress()['filtered_files']==2,worker.progress()
        assert worker.progress()['saved_files']==0 and worker.progress()['known_files']==0
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None
        assert not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def test_local_send_withdrawal_during_original_inventory_stops_before_any_source_cache_or_offer(pc,native,monkeypatch):
    from magnolie_media_source_collection import NativeCollectionRoot
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);inventory=NativeCollectionRoot.inventory;withdrawn=[]
        def withdraw(root,*args,**kwargs):
            result=inventory(root,*args,**kwargs)
            if not withdrawn:
                h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
                withdrawn.append(True)
            return result
        monkeypatch.setattr(NativeCollectionRoot,'inventory',withdraw)
        worker=start(h);assert worker.join(30),worker.progress()
        assert withdrawn and worker.progress()['state']=='held' and worker.progress()['saved_files']==0,worker.progress()
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None


def test_collection_cleanup_failure_still_releases_the_actual_worker_slot_after_root_and_catalog_drain(pc,native,monkeypatch):
    from magnolie_media_source_collection_pass import NativeCollectionPass
    with composition(pc,native[0]) as h:
        small_source(h);h.controller.change('photos_only',True);agree(h,native[0]);close=NativeCollectionPass.close;closed=[]
        def fail_after_drain(owner):
            close(owner);closed.extend(root for _,root,_,_ in owner._frames)
            raise RuntimeError('collection-test-close-after-actual-drain')
        monkeypatch.setattr(NativeCollectionPass,'close',fail_after_drain)
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='collection-test-close-after-actual-drain'
        assert closed and all(root._fd is None for root in closed)
        assert h.connection._mapped_worker is None and h.connection._media_sender is None


@pytest.mark.parametrize('forgery',['member','root','worker'])
def test_equal_copied_inventory_metadata_or_foreign_worker_is_not_an_original_batch_member_permit(pc,native,monkeypatch,forgery):
    from dataclasses import replace
    from types import SimpleNamespace
    from magnolie_file_transfer import TransferError
    from magnolie_media_source_collection_pass import NativeCollectionPass
    with composition(pc,native[0]) as h:
        small_source(h);h.controller.change('photos_only',True);agree(h,native[0]);members=NativeCollectionPass.members;denied=[]
        def forged(owner):
            for selected,member in members(owner):
                worker=owner._worker
                target=replace(member) if forgery=='member' else member
                root=replace(selected) if forgery=='root' else selected
                if forgery=='worker':worker=SimpleNamespace(_collection=owner,_kind='images')
                with pytest.raises(TransferError):h.connection.prepare_worker_collection_media_source(worker,h.preferences.read(),root,target)
                denied.append(True);assert not h.connection._media_pc_source._prepared
                yield selected,member
        monkeypatch.setattr(NativeCollectionPass,'members',forged)
        worker=start(h);assert worker.join(30),worker.progress()
        assert denied and worker.progress()['state']=='complete' and worker.progress()['filtered_files']==2,worker.progress()
        assert worker.progress()['saved_files']==0 and h.connection._media_sender is None


def test_collection_native_inventory_bound_holds_without_allocating_a_source_cache_or_evicting_history(pc,native,monkeypatch):
    from magnolie_media_source_collection_pass import NativeCollectionPass
    with composition(pc,native[0]) as h:
        small_source(h);(h.pc_file.parent/'another.png').write_bytes(h.pc_file.read_bytes());agree(h,native[0])
        monkeypatch.setattr(NativeCollectionPass,'MAX_MEMBERS',1) # Exercise boundary, never raise product's bound.
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='media_collection_inventory_bound',worker.progress()
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None
        assert _NativeSourceJobs(h.authority).MAX_RECORDS==128 and not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def test_whole_collection_automatic_export_stays_explicitly_gated_without_native_acceptance(pc,native,monkeypatch):
    from test_media_source_worker import warm_metadata
    from magnolie_media_source_collection import NativeCollectionRoot
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);warm_metadata(h,native[0])
        monkeypatch.setattr(NativeCollectionRoot,'inventory',lambda *a,**k:pytest.fail('Unaccepted automatic export began native inventory'))
        worker=h.connection.start_mapped_media_worker(h.connection.issue_receive_action(),automatic=True)
        assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='media_source_entire_collection_automatic_acceptance_required'
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None


def test_actual_already_checked_mapped_file_inside_a_selected_root_is_not_relabelled_or_counted_twice(pc,native):
    from magnolie_media_source_collection import NativeCollectionRoot
    with composition(pc,native[0]) as h:
        # Keep the other explicit source's original intact but outside its
        # eligible namespace; this case needs no new PC offer or receiver model.
        h.pc_file.rename(h.pc_file.with_name('.magnolie-test-retained-original'))
        catalog=h.preferences.open_collection_roots()
        try:
            with NativeCollectionRoot(h.target.parent,lambda:True) as root:
                catalog.add(catalog.issue_action(),catalog.read(),root,'images')
        finally:catalog.close()
        agree(h,native[0]);before=h.target.read_bytes();worker=start(h)
        assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='complete' and worker.progress()['known_files']==1,worker.progress()
        assert worker.progress()['saved_files']==0 and h.target.read_bytes()==before
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None
        with pytest.raises(TimeoutError):h.wire.receive()


def test_images_root_can_explicitly_filter_known_video_container_without_video_send_rights_but_never_labels_it_known(pc,native):
    import struct
    with composition(pc,native[0]) as h:
        h.pc_file.write_bytes(struct.pack('>I',16)+b'ftypisom'+b'\0'*4)
        agree(h,native[0]);worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='complete' and worker.progress()['filtered_files']==1,worker.progress()
        assert worker.progress()['saved_files']==0 and worker.progress()['known_files']==1
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None


@pytest.mark.parametrize('scenario',['unknown','broken_dimensions','photos_only_mixed'])
def test_collection_kind_exclusion_never_swallows_unknown_bytes_or_turns_filtered_files_into_publications(pc,native,scenario):
    import struct
    from test_media_source_media_offer import png
    with composition(pc,native[0]) as h:
        if scenario=='unknown':h.pc_file.write_bytes(b'not a media file')
        elif scenario=='broken_dimensions':
            raw=bytearray(png());struct.pack_into('>I',raw,16,40000);h.pc_file.write_bytes(raw)
        else:
            h.pc_file.write_bytes(png())
            (h.pc_file.parent/'not-an-image.jpg').write_bytes(struct.pack('>I',16)+b'ftypisom'+b'\0'*4)
            h.controller.change('photos_only',True)
        agree(h,native[0]);worker=start(h);assert worker.join(30),worker.progress()
        result=worker.progress()
        if scenario=='photos_only_mixed':assert result['state']=='complete' and result['filtered_files']==3 and result['known_files']==0,result
        else:assert result['state']=='held' and result['error']==('media_source_mime_unknown' if scenario=='unknown' else 'media_source_mime_dimensions'),result
        assert result['saved_files']==0 and not h.connection._media_pc_source._prepared and h.connection._media_sender is None


@pytest.mark.parametrize('fault',['symlink','root_catalog','same_size_edit'])
def test_collection_inventory_or_original_catalog_changes_hold_without_claiming_mapped_subset_complete(pc,native,monkeypatch,fault):
    from magnolie_media_source_collection_pass import NativeCollectionPass
    from magnolie_media_source_collection import NativeCollectionRoot
    with composition(pc,native[0]) as h:
        small_source(h);agree(h,native[0]);before=h.pc_file.read_bytes()
        if fault=='symlink':(h.pc_file.parent/'foreign-link').symlink_to(h.pc_file)
        else:
            original=NativeCollectionPass.members
            def changed(owner):
                if fault=='same_size_edit':
                    raw=bytearray(h.pc_file.read_bytes());raw[-1]^=1;h.pc_file.write_bytes(raw)
                else:
                    folder=h.pc_file.parent.parent/'another-explicit-source';folder.mkdir(mode=0o700)
                    catalog=h.preferences.open_collection_roots()
                    try:
                        with NativeCollectionRoot(folder,lambda:True) as root:catalog.add(catalog.issue_action(),catalog.read(),root,'images')
                    finally:catalog.close()
                yield from original(owner)
            monkeypatch.setattr(NativeCollectionPass,'members',changed)
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['saved_files']==0,worker.progress()
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None
        if fault!='same_size_edit':assert h.pc_file.read_bytes()==before
