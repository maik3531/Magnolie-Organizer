"""Independent native video metadata CAS keeps original photo authority exact."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_preferences import ProtectedPhotoPreferences,PhotoPreferences
from magnolie_photo_destination import NativeVideoDestinationController
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_photo_preferences import preferences,configure
from test_video_preferences import videos,choice


def test_explicit_off_is_inert_and_video_enable_needs_existing_photo_consent_and_native_video_root(preferences):
    service,_,prefs,_,_,_=preferences
    absent=prefs.read()
    with pytest.raises(TransferError,match='destination_required'):
        prefs.set_video_scope(prefs.issue_action(),absent,enabled=True)
    assert not (Path(service.store.root)/prefs._name).exists()
    photo=configure(preferences)
    assert prefs.set_video_scope(prefs.issue_action(),photo,enabled=False)==photo
    with pytest.raises(TransferError,match='destination_required'):
        prefs.set_video_scope(prefs.issue_action(),photo,enabled=True)
    assert prefs.read()==photo and photo.policy.videos is None


def test_video_scope_cas_preserves_exact_photo_grant_and_original_scope_token_across_off_on(preferences,videos):
    service,authority,prefs,_,_,_=preferences
    photo=configure(preferences);grant=prefs.local_grant(True).grants
    selected=choice(videos)
    video=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=selected)
    assert video.include_videos and video.policy.videos.destination==selected.destination
    assert video.policy.videos.destination_token==selected.destination_token!=photo.policy.destination_token
    assert video.policy.permission_epoch==photo.policy.permission_epoch
    assert video.policy.permission_revision==photo.policy.revision
    assert replace(video.policy,revision=photo.policy.revision,permission_revision=photo.policy.permission_revision,videos=None)==photo.policy
    for enabled in (False,True,False):
        before=video;video=prefs.set_video_scope(prefs.issue_action(),before,enabled=enabled)
        assert video.include_videos is enabled and video.policy.revision==before.policy.revision+1
        assert video.policy.videos.destination==selected.destination and video.policy.videos.destination_token==selected.destination_token
        assert prefs.local_grant(True).grants==grant
        assert not prefs.local_grant(False).grants.receive_files
    assert str(videos[1]).encode() not in (Path(service.store.root)/prefs._name/'prefs.sqlite').read_bytes()
    prefs.close()
    reopened=ProtectedPhotoPreferences(authority)
    try:assert reopened.read()==video and reopened.local_grant(True).grants==grant
    finally:reopened.close()


def test_reselecting_same_native_video_root_retains_original_token_and_is_idempotent(preferences,videos):
    prefs=preferences[2];photo=configure(preferences)
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    blob=prefs._db.execute('SELECT payload FROM policy WHERE id=1').fetchone()[0]
    selected=choice(videos);assert selected.destination_token!=saved.policy.videos.destination_token
    assert prefs.set_video_scope(prefs.issue_action(),saved,enabled=True,destination_choice=selected)==saved
    assert prefs._db.execute('SELECT payload FROM policy WHERE id=1').fetchone()[0]==blob


def test_replacing_existing_video_destination_requires_separate_historical_reassociation(preferences,videos,tmp_path):
    prefs=preferences[2];photo=configure(preferences)
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    original=videos[1]/'original-user-video.mp4';original.write_bytes(b'preserve original edited video')
    other=tmp_path/'other-native-video-root';other.mkdir(mode=0o700)
    existing=other/'existing.mp4';existing.write_bytes(b'preserve unrelated video')
    before=(original.stat().st_ino,original.read_bytes(),existing.stat().st_ino,existing.read_bytes())
    selected=videos[0].choose_custom(videos[0].issue_action(),other)
    with pytest.raises(TransferError,match='destination_reassociation_required'):
        prefs.set_video_scope(prefs.issue_action(),saved,enabled=True,destination_choice=selected)
    assert prefs.read()==saved
    assert (original.stat().st_ino,original.read_bytes(),existing.stat().st_ino,existing.read_bytes())==before


def test_video_off_does_not_need_missing_root_and_cannot_silently_reenable_it(preferences,videos):
    prefs=preferences[2];photo=configure(preferences);grant=prefs.local_grant(True).grants
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    videos[1].rmdir()
    disabled=prefs.set_video_scope(prefs.issue_action(),saved,enabled=False)
    assert not disabled.include_videos and disabled.policy.videos.destination==saved.policy.videos.destination
    assert prefs.local_grant(True).grants==grant
    with pytest.raises(FileNotFoundError):prefs.set_video_scope(prefs.issue_action(),disabled,enabled=True)
    assert prefs.read()==disabled and prefs.local_grant(True).grants==grant


def test_video_scope_rejects_replacement_directory_without_rebuilding_original_witness(preferences,videos):
    prefs=preferences[2];photo=configure(preferences)
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    held=videos[1].with_name('preserved-native-video-root');videos[1].rename(held);videos[1].mkdir(mode=0o700)
    with pytest.raises(TransferError,match='destination_changed'):
        prefs.set_video_scope(prefs.issue_action(),saved,enabled=True)
    assert prefs.read()==saved
    disabled=prefs.set_video_scope(prefs.issue_action(),saved,enabled=False)
    with pytest.raises(TransferError,match='destination_reassociation_required'):
        prefs.set_video_scope(prefs.issue_action(),disabled,enabled=True,destination_choice=choice(videos))
    assert prefs.read()==disabled and held.is_dir()


@pytest.mark.parametrize('enabled',[0,1,'true',None])
def test_video_scope_requires_literal_native_boolean_without_creating_preferences(preferences,enabled):
    service,_,prefs,_,_,_=preferences
    with pytest.raises(TransferError,match='invalid_settings'):
        prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=enabled)
    assert not (Path(service.store.root)/prefs._name).exists()


@pytest.mark.parametrize('kind',['photo','wire','path'])
def test_video_scope_refuses_photo_choices_wire_objects_and_paths(preferences,videos,kind):
    _,_,prefs,photo_chooser,photo_target,_=preferences;photo=configure(preferences)
    selected={'photo':lambda:photo_chooser.choose_custom(photo_chooser.issue_action(),photo_target),
        'wire':lambda:dict(path=str(videos[1])),'path':lambda:str(videos[1])}[kind]()
    with pytest.raises(TransferError,match='invalid_settings'):
        prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=selected)
    assert prefs.read()==photo


def test_video_scope_rejects_stale_snapshot_and_consumes_attempted_native_action(preferences,videos):
    prefs=preferences[2];photo=configure(preferences)
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    action=prefs.issue_action()
    with pytest.raises(TransferError,match='cas_conflict'):prefs.set_video_scope(action,photo,enabled=False)
    with pytest.raises(TransferError,match='action_not_current'):prefs.set_video_scope(action,saved,enabled=False)
    assert prefs.read()==saved


def test_video_scope_cannot_alias_the_photo_destination_token_even_with_a_typed_native_choice(preferences,videos):
    prefs=preferences[2];photo=configure(preferences);selected=choice(videos)
    aliased=replace(selected,destination_token=photo.policy.destination_token)
    with pytest.raises(TransferError,match='distinct_destination_token_required'):
        prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=aliased)
    assert prefs.read()==photo
    wire=photo.policy.wire();wire['videos']=dict(enabled=True,destination=selected.destination.wire(),destination_token=photo.policy.destination_token)
    with pytest.raises(TransferError,match='distinct_destination_token_required'):PhotoPreferences.parse(wire)


def test_explicit_same_directory_still_has_an_independent_typed_video_token(preferences):
    _,authority,prefs,_,target,_=preferences;photo=configure(preferences);grant=prefs.local_grant(True).grants
    controller=NativeVideoDestinationController(authority)
    try:
        selected=controller.choose_custom(controller.issue_action(),target)
        video=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=selected)
        assert video.policy.videos.destination==photo.policy.destination
        assert video.policy.videos.destination_token!=photo.policy.destination_token
        assert prefs.local_grant(True).grants==grant
    finally:controller.close()


def test_video_scope_decrease_remains_possible_when_base_photo_consent_is_off(preferences,videos):
    prefs=preferences[2];photo=configure(preferences)
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    off=prefs.configure(prefs.issue_action(),saved,enabled=False,mode='manual')
    grant=prefs.local_grant(True).grants
    disabled=prefs.set_video_scope(prefs.issue_action(),off,enabled=False)
    assert not disabled.policy.enabled and not disabled.policy.videos.enabled
    assert disabled.policy.permission_epoch==off.policy.permission_epoch and prefs.local_grant(True).grants==grant
    with pytest.raises(TransferError,match='authority_changed'):
        prefs.set_video_scope(prefs.issue_action(),disabled,enabled=True)
    assert prefs.read()==disabled


def test_video_scope_uses_exact_authority_owner_even_for_same_relationship_and_folder(preferences,videos):
    service,authority,prefs,_,_,_=preferences;photo=configure(preferences)
    other=service.open_native_file_authority(authority.binding.peer_id,authority.binding.static_public,
        authority.native_channel,authority.binding.generation)
    controller=NativeVideoDestinationController(other)
    try:
        selected=controller.choose_custom(controller.issue_action(),videos[1])
        with pytest.raises(TransferError,match='foreign_destination_choice'):
            prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=selected)
        assert prefs.read()==photo
    finally:controller.close();other.close()


def test_video_scope_idempotent_request_still_needs_unexpired_native_action(preferences,videos,monkeypatch):
    _,_,prefs,_,_,clock=preferences;photo=configure(preferences)
    saved=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=choice(videos))
    snapshot=prefs._snapshot;action=prefs.issue_action()
    def late_readback():
        result=snapshot();clock[0]+=60_000;return result
    with monkeypatch.context() as patch:
        patch.setattr(prefs,'_snapshot',late_readback)
        with pytest.raises(TransferError,match='action_not_current'):
            prefs.set_video_scope(action,saved,enabled=True)
    assert prefs.read()==saved


def test_uncertain_video_metadata_write_holds_native_access_without_rekeying_persisted_photo_grants(preferences,videos,monkeypatch):
    _,authority,prefs,_,_,_=preferences;photo=configure(preferences);grant=prefs.local_grant(True).grants
    selected=choice(videos);sync=prefs._sync
    def uncertain_sync():
        sync();raise OSError('fixture video metadata postcommit output uncertain')
    with monkeypatch.context() as patch:
        patch.setattr(prefs,'_sync',uncertain_sync)
        with pytest.raises(OSError,match='postcommit'):
            prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=selected)
    with pytest.raises(TransferError,match='closed_or_pending'):prefs.local_grant(True)
    prefs.close();fresh=ProtectedPhotoPreferences(authority)
    try:
        actual=fresh.read()
        assert actual.policy.videos.enabled and actual.policy.videos.destination==selected.destination
        assert actual.policy.permission_epoch==photo.policy.permission_epoch
        assert fresh.local_grant(True).grants==grant
    finally:fresh.close()


def test_video_metadata_change_retains_actual_saved_photo_mapping_receipts_job_and_pc_edit(receiving,tmp_path):
    from test_photo_mappings import save
    from test_file_desktop_photo_review import end_normal_source
    from magnolie_transfer_job_index import ProtectedTransferJobIndex
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());job=receiver.job
    receipt=receiver._index.saved_mapping_receipt()
    connection.finish_saved_receive(connection.issue_receive_action());end_normal_source(receiving)
    prefs=connection._preferences;photo=prefs.read();binding=connection._receive_binding();grant=prefs.local_grant(True).grants
    mappings=connection._mappings.read();jobs=connection._catalog.jobs();sent=receiving[2].send.call_count
    path=receiving[4]/job.accepted.targets[0][1];path.write_bytes(b'keep edited photo during video setup')
    before=(path.stat().st_ino,path.read_bytes())
    target=tmp_path/'explicit-independent-video-root';target.mkdir(mode=0o700)
    with_controller=NativeVideoDestinationController(connection._authority)
    try:
        selected=with_controller.choose_custom(with_controller.issue_action(),target)
        changed=prefs.set_video_scope(prefs.issue_action(),photo,enabled=True,destination_choice=selected)
        assert changed.policy.destination==photo.policy.destination and prefs.local_grant(True).grants==grant
        assert connection._receive_binding()==binding and not connection.send_controls()
        assert connection._mappings.read()==mappings and connection._catalog.jobs()==jobs
        assert jobs==(job,) and jobs[0].saved_mapping_sha256 is None
        protection=connection._authority.protection
        with connection._catalog.inspect_jobs() as (parent,_):
            with ProtectedTransferJobIndex(parent,job.accepted.manifest,binding,connection._receive_binding,
                    protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                assert receipt is not None and index.saved_mapping_receipt()==receipt
        assert (path.stat().st_ino,path.read_bytes())==before
        assert receiving[2].send.call_count==sent and connection._run is None and connection._source_run is None
    finally:with_controller.close()
