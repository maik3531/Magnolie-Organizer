"""Actual native folder owners/configuration; never data-transfer acceptance."""
from pathlib import Path
from contextlib import closing
import threading

import pytest

from test_media_source_pc import pc,source,mappings,receiving,native
from test_media_source_connection import composition,agree,dispatch
from test_media_source_sender import message
from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
from magnolie_file_transfer import TransferError
from magnolie_media_source_choice import native_folder_witness
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_retention import NativeMediaRetention


def prepare(h,kind='images'):
    from test_media_source_worker import warm_metadata
    if not h.connection._native_metadata_current():warm_metadata(h,h.service)
    return h.connection.native_collection_choice('prepare',kind=kind,version=h.controller.display_snapshot()['version'])


def roots(h):
    with closing(h.preferences.open_collection_roots()) as catalog:return catalog.read()


def test_first_native_source_folders_bind_private_catalog_without_receive_consent_source_reads_or_wire_output(source,native,tmp_path,monkeypatch):
    source.controller.change('collection_mode','entire_collection')
    source.controller.change('videos_enabled',True)
    source.policy=source.preferences.configure_sending(source.preferences.issue_action(),source.preferences.read(),photos=True,videos=True)
    with composition(source,native[0]) as h:
        control=agree(h,native[0]);old=h.preferences.read();owner=h.connection._local().owner
        dispatch(h,native[0],message(CONTROL,FileControlPacket(FileGrantState(2,'b'*64,False,False),'7'*64,2,control.challenge).wire()))
        while True:
            try:packet=h.wire.receive()
            except TimeoutError:break
            assert packet['kind']==CONTROL
        control=h.connection._controls.packet()
        assert h.connection._controls.binding('0'*64,sender_is_local=True) is None
        assert old.policy.collection_roots is None
        monkeypatch.setattr(NativeCollectionRoot,'inventory',lambda *a,**k:pytest.fail('Choosing a root enumerated source files'))
        monkeypatch.setattr(NativeCollectionRoot,'open_member',lambda *a,**k:pytest.fail('Choosing a root read source bytes'))
        for kind in ('images','video'):
            folder=tmp_path/('chosen-'+kind);folder.mkdir(mode=0o700)
            page=prepare(h,kind)
            with NativeCollectionRoot(folder,lambda:True) as gui:
                selected=h.connection.native_collection_choice('commit',kind=kind,selection=page['selection'],
                    path=str(folder),witness=native_folder_witness(gui))
            assert any(root['media_type']==kind and root['display_path']==str(folder) for root in selected['roots'])
            assert list(folder.iterdir())==[]
        current=h.preferences.read();assert current.policy.collection_roots is not None
        ignored={'revision','permission_revision','collection_roots'}
        assert {k:v for k,v in current.policy.wire().items() if k not in ignored}=={k:v for k,v in old.policy.wire().items() if k not in ignored}
        assert len(roots(h).roots)==2 and h.connection._local().owner is owner
        after=h.connection._controls.packet();assert after.grants==control.grants and after.session_epoch==control.session_epoch
        assert not after.grants.receive_files and not h.connection._controls._remote.grants.send_files
        assert h.connection.desktop_snapshot()['collection_sources']['roots']==selected['roots']
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None
        with pytest.raises(TimeoutError):h.wire.receive()


def test_reading_absent_native_source_selection_is_metadata_only_and_does_not_create_catalog_or_source_owners(source,native,monkeypatch):
    from test_media_source_worker import warm_metadata
    source.controller.change('collection_mode','entire_collection')
    with composition(source,native[0]) as h:
        agree(h,native[0]);warm_metadata(h,h.service)
        parent=Path(h.authority.binding.native_directory);before=set(parent.iterdir());policy=h.preferences.read()
        monkeypatch.setattr(NativeCollectionRoot,'__init__',lambda *a,**k:pytest.fail('Metadata read opened a source directory'))
        result=h.connection.native_collection_choice('read',version=h.controller.display_snapshot()['version'])
        # SQLite may retire its existing WAL/SHM on close; metadata reads must
        # create no new catalog/storage and must preserve the saved policy.
        assert result['roots']==[] and not (set(parent.iterdir())-before) and h.preferences.read()==policy
        assert h.connection._media_collection_choice is None and not h.connection._media_pc_source._prepared


@pytest.mark.parametrize('fault',['intent','control','book','consent','substitution','extra_flag'])
def test_late_native_folder_results_cannot_adopt_changed_original_context_or_substituted_native_selection(pc,native,tmp_path,fault):
    with composition(pc,native[0]) as h:
        control=agree(h,native[0]);before=roots(h);page=prepare(h)
        folder=tmp_path/'native-choice';folder.mkdir(mode=0o700)
        with NativeCollectionRoot(folder,lambda:True) as gui:
            witness=native_folder_witness(gui)
            if fault=='intent':h.controller.change('auto_mode','wifi')
            elif fault=='control':
                dispatch(h,native[0],message(CONTROL,FileControlPacket(FileGrantState(1,'6'*64,False,True),'a'*64,1,control.challenge).wire()))
                assert h.wire.receive()['kind']==CONTROL
            elif fault=='book':
                with NativeMediaRetention(h.authority.binding.native_directory) as retention:retention.pause()
            elif fault=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
            elif fault=='substitution':folder.rename(folder.with_name('retained-native-choice'));folder.mkdir(mode=0o700)
            else:witness['confirmed']=True
            with pytest.raises((TransferError,OSError)):
                h.connection.native_collection_choice('commit',selection=page['selection'],path=str(folder),witness=witness)
        assert roots(h)==before and h.connection._media_collection_choice is None
        assert not h.connection._media_pc_source._prepared and h.connection._media_sender is None


def test_native_folder_choice_cancellation_retires_while_real_commit_io_keeps_its_original_slot_and_authority(pc,native,tmp_path,monkeypatch):
    with composition(pc,native[0]) as h:
        agree(h,native[0]);before=roots(h);page=prepare(h)
        folder=tmp_path/'native-choice';folder.mkdir(mode=0o700)
        entered=threading.Event();release=threading.Event();held=[];errors=[]
        with NativeCollectionRoot(folder,lambda:True) as gui:
            witness=native_folder_witness(gui);original=NativeCollectionRoot.__init__
            def blocked(root,path,current):
                original(root,path,current)
                if threading.current_thread().name=='native-folder-commit':
                    held.append(root);entered.set();assert release.wait(8)
            monkeypatch.setattr(NativeCollectionRoot,'__init__',blocked)
            def commit():
                try:h.connection.native_collection_choice('commit',selection=page['selection'],path=str(folder),witness=witness)
                except BaseException as error:errors.append(error)
            worker=threading.Thread(target=commit,name='native-folder-commit');worker.start()
            try:
                assert entered.wait(5)
                assert h.connection.native_collection_choice('cancel',selection=page['selection'])==dict(canceled=True)
                assert worker.is_alive() and held[0]._fd is not None and h.connection._media_collection_choice is not None
                with pytest.raises(TransferError):prepare(h)
            finally:release.set();worker.join(8)
        assert not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
        assert held[0]._fd is None and h.connection._media_collection_choice is None and roots(h)==before
