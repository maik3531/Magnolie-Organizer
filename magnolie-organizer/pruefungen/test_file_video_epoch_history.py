"""Protected historical VIDEO anchors never become first use after off/on.

These are inert native-index tests, not video worker or OS READ acceptance.
"""
from dataclasses import replace
from hashlib import sha256

import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import ready_source,RUN
from test_file_desktop_media import manifest
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_media import SourceMediaPage,SourceMediaEntry
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_index import ProtectedTransferJobIndex


@pytest.mark.parametrize('scope',['new_epoch','version_hint','same_epoch','other_id','images'])
def test_actual_protected_video_anchor_is_inspected_without_stage_read_or_new_reservation(receiving,monkeypatch,scope):
    connection=receiving[3];ready_source(receiving)
    full=manifest(receiving)
    binding=connection._receive_binding()
    accepted=NativeAcceptedTransfer.capture(full,binding,{file.id:file.path for file in full.files},
        receiving[4],connection._receive_binding)
    entry=SourceMediaEntry(full.files[0].id,sha256(b'native-video-id').hexdigest(),'video')
    page=SourceMediaPage('11111111-1111-4111-8111-111111111111','b'*64,RUN,full.fingerprint,
        'c'*64,'video',False,0,None,1,(entry,))
    history=NativeMediaHistory.capture(accepted,(page,))
    connection._open_catalog()
    job=connection._catalog.reserve(accepted,connection._receive_binding)
    protection=connection._authority.protection
    with connection._catalog.inspect_jobs() as (parent,_):
        with ProtectedTransferJobIndex(parent,full,binding,connection._receive_binding,protection.seal,protection.unseal,
                owner=job.owner,create=True,accepted=accepted,media_history=history) as index:
            assert index.media_history==history and not index.saved_receipts()
    jobs=connection._catalog.jobs();sent=receiving[2].send.call_count
    before={path.relative_to(parent):path.read_bytes() for path in parent.rglob('*') if path.is_file()}
    fresh=replace(page,source_epoch='d'*64)
    if scope=='same_epoch':fresh=page
    elif scope=='other_id':fresh=replace(fresh,entries=(replace(entry,photo_id='e'*64),))
    elif scope=='images':fresh=replace(fresh,media_type='images',entries=(replace(entry,media_kind='image'),))
    connection._source_media_pages=(fresh,);connection._source_media_entries=fresh.entries
    def forbidden(*args,**kwargs):raise AssertionError('History guard attempted source/stage/target authority')
    monkeypatch.setattr(connection,'_receive_binding',forbidden)
    monkeypatch.setattr(NativeAcceptedTransfer,'verify',forbidden)
    if scope in ('new_epoch','version_hint'):
        with pytest.raises(TransferError,match='video_source_reassociation_required'):
            connection._require_unreserved_media_history(None,version_parents={entry.photo_id:'f'*64} if scope=='version_hint' else None)
    elif scope=='same_epoch':
        with pytest.raises(TransferError,match='photo_job_requires_reconcile'):
            connection._require_unreserved_media_history(None)
    else:assert connection._require_unreserved_media_history(None)==jobs
    assert connection._catalog.jobs()==jobs and receiving[2].send.call_count==sent
    assert not list(receiving[4].iterdir()) and connection._run is None
    assert {path.relative_to(parent):path.read_bytes() for path in parent.rglob('*') if path.is_file()}==before
