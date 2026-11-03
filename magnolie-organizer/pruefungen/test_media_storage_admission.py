"""No media admission/resume before both explicit original storage bindings."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import status,catalog,request,response,RUN
from test_file_desktop_media import manifest,collect,send_offer,dispatch
from test_file_desktop_mapping_witness import anchor
from test_file_desktop_catalog_witness import anchor_catalog


@pytest.mark.parametrize('binding',['none','mapping-only','catalog-only'])
def test_unbound_or_half_bound_media_offer_is_held_before_new_reservation(receiving,monkeypatch,binding):
    connection=receiving[3]
    if binding=='mapping-only':anchor(receiving)
    elif binding=='catalog-only':anchor_catalog(receiving)
    # Deliberately do not use the positive media fixture's explicit joint setup.
    status(receiving);catalog(receiving);started=request(receiving,'run',album_id='33333333-3333-4333-8333-333333333333',desktop_choice=True)
    dispatch(receiving,response(started,'file_transfer.sources.run_result',version='b'*64,run_id=RUN,state='snapshot_ready',source_io_ended=True))
    full=manifest(receiving);collect(receiving,full);offered,result=send_offer(receiving,full);dispatch(receiving,result)
    parent=Path(connection._authority.binding.native_directory);before={entry.name for entry in parent.iterdir()}
    def forbidden(*args,**kwargs):raise AssertionError('unbound media must fail before mapping/history/catalog/reservation I/O')
    monkeypatch.setattr(connection._mappings,'lookup',forbidden)
    monkeypatch.setattr(connection,'_open_catalog',forbidden)
    with pytest.raises(TransferError,match='media_storage_bootstrap_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    with pytest.raises(TransferError,match='media_storage_bootstrap_required'):
        connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],'f'*32)
    assert connection._run is None and connection._catalog is None
    assert {entry.name for entry in parent.iterdir()}==before and not list(receiving[4].iterdir())


@pytest.mark.parametrize('bound',[False,True])
def test_first_gallery_source_run_cannot_bypass_storage_and_history_by_omitting_media_pages(receiving,monkeypatch,bound):
    connection=receiving[3]
    if bound:
        from magnolie_media_storage_bootstrap import NativeMediaStorageBootstrap
        from test_file_desktop_receive import negotiate
        setup=NativeMediaStorageBootstrap(connection._authority)
        try:setup.prepare(setup.issue_action(),connection.read_preferences())
        finally:setup.close()
        negotiate(*receiving[:4])
    status(receiving);catalog(receiving);started=request(receiving,'run',album_id='33333333-3333-4333-8333-333333333333',desktop_choice=True)
    dispatch(receiving,response(started,'file_transfer.sources.run_result',version='b'*64,run_id=RUN,state='snapshot_ready',source_io_ended=True))
    full=manifest(receiving);offered,result=send_offer(receiving,full);dispatch(receiving,result)
    assert not connection._source_media_pages and connection._source_run is not None
    parent=Path(connection._authority.binding.native_directory);before={entry.name for entry in parent.iterdir()}
    def forbidden(*args,**kwargs):raise AssertionError('missing source media must hold before historical/catalog I/O')
    monkeypatch.setattr(connection._mappings,'lookup',forbidden);monkeypatch.setattr(connection,'_open_catalog',forbidden)
    with pytest.raises(TransferError,match='source_media_history_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    with pytest.raises(TransferError,match='source_media_history_required'):
        connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],'f'*32)
    assert {entry.name for entry in parent.iterdir()}==before and connection._run is None and connection._catalog is None
