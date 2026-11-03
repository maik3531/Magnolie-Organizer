"""Explicit protected video selection; no Android permissions or video workers."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import NativeVideoDestinationController
from magnolie_photo_preferences import ProtectedPhotoPreferences, PhotoPreferences, VideoPreferences
from test_photo_preferences import preferences, configure
from test_file_authenticated_desktop import native,bind
import magnolie_telefon as phone


@pytest.fixture
def videos(preferences,tmp_path):
    _,authority,_,_,_,_=preferences
    target=tmp_path/'explicit-native-video-target';target.mkdir(mode=0o700)
    chooser=NativeVideoDestinationController(authority)
    try:yield chooser,target
    finally:chooser.close()


def choice(videos):
    chooser,target=videos
    return chooser.choose_custom(chooser.issue_action(),target)


def test_absent_and_preexisting_photo_policy_default_to_video_off_without_rewriting(preferences):
    service,_,prefs,_,_,_=preferences
    absent=prefs.read()
    assert not absent.include_videos and not (Path(service.store.root)/prefs._name).exists()
    saved=configure(preferences)
    assert saved.policy.videos is None and not saved.include_videos
    original=prefs._db.execute('SELECT payload FROM policy').fetchone()[0]
    wire=saved.policy.wire()
    assert 'videos' not in wire and PhotoPreferences.parse(wire).wire()==wire
    assert prefs.read()==saved and prefs._db.execute('SELECT payload FROM policy').fetchone()[0]==original


def test_video_folder_selection_is_not_opt_in_and_does_not_replace_the_photo_destination(preferences,videos):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    selected=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',video_destination_choice=choice(videos))
    assert not selected.include_videos and not selected.policy.videos.enabled
    assert selected.policy.videos.destination.path==str(videos[1])
    assert selected.policy.destination==photo.policy.destination and selected.policy.destination_token==photo.policy.destination_token
    assert not prefs.local_grant(False).grants.receive_files


def test_explicit_video_opt_in_and_separate_target_are_encrypted_cas_and_survive_reopen(preferences,videos):
    service,authority,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=True,video_destination_choice=choice(videos))
    assert saved.include_videos and saved.policy.videos.enabled
    assert saved.policy.destination==photo.policy.destination and saved.policy.destination_token==photo.policy.destination_token
    assert saved.policy.videos.destination_token!=saved.policy.destination_token
    assert saved.policy.revision==photo.policy.revision+1 and saved.policy.permission_epoch!=photo.policy.permission_epoch
    assert not prefs.local_grant(False).grants.receive_files # Configured is not native readiness/OS READ.
    database=Path(service.store.root)/prefs._name/'prefs.sqlite'
    assert str(videos[1]).encode() not in database.read_bytes()
    with pytest.raises(TransferError,match='cas_conflict'):
        prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=False)
    prefs.close();reopened=ProtectedPhotoPreferences(authority)
    try:assert reopened.read()==saved
    finally:reopened.close()


def test_photo_updates_preserve_video_setting_and_global_disable_does_not_erase_either_destination(preferences,videos):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=True,video_destination_choice=choice(videos))
    updated=prefs.configure(prefs.issue_action(),saved,enabled=True,mode='automatic')
    assert updated.policy.videos==saved.policy.videos and updated.include_videos
    disabled=prefs.configure(prefs.issue_action(),updated,enabled=False,mode='manual')
    assert not disabled.include_videos and disabled.policy.videos==saved.policy.videos
    assert disabled.policy.destination==saved.policy.destination
    assert not prefs.local_grant(True).grants.receive_files


def test_video_disable_preserves_missing_video_folder_witness_and_photo_consent(preferences,videos):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=True,video_destination_choice=choice(videos))
    videos[1].rmdir()
    disabled=prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',include_videos=False)
    assert not disabled.include_videos and disabled.policy.enabled
    assert disabled.policy.videos.destination==saved.policy.videos.destination
    assert disabled.policy.destination==photo.policy.destination and prefs.read()==disabled
    with pytest.raises(FileNotFoundError):
        prefs.configure(prefs.issue_action(),disabled,enabled=True,mode='manual',include_videos=True)
    assert prefs.read()==disabled


@pytest.mark.parametrize('value',[1,0,'true',[],{}])
def test_non_boolean_video_setting_is_rejected_without_creating_a_store(preferences,value):
    service,_,prefs,_,_,_=preferences
    with pytest.raises(TransferError,match='invalid_settings'):
        prefs.configure(prefs.issue_action(),prefs.read(),enabled=False,mode='manual',include_videos=value)
    assert not (Path(service.store.root)/prefs._name).exists()


def test_video_opt_in_requires_its_own_exact_native_choice_not_photo_or_wire_paths(preferences,videos):
    _,_,prefs,photochooser,phototarget,_=preferences
    saved=configure(preferences)
    with pytest.raises(TransferError,match='destination_required'):
        prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',include_videos=True)
    photoselection=photochooser.choose_custom(photochooser.issue_action(),phototarget)
    for foreign in (photoselection,{'path':str(videos[1])}):
        with pytest.raises(TransferError,match='foreign_destination_choice'):
            prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',include_videos=True,video_destination_choice=foreign)
    assert prefs.read()==saved


@pytest.mark.parametrize('value',[None,True,{},dict(enabled=1,destination=None,destination_token=None),
    dict(enabled=True,destination=None,destination_token=None),dict(enabled=False,destination=None,destination_token='a'*64)])
def test_malformed_optional_video_record_never_defaults_to_enabled_or_resets_legacy_photo_policy(preferences,value):
    saved=configure(preferences)
    wire=saved.policy.wire();wire['videos']=value
    with pytest.raises(TransferError):PhotoPreferences.parse(wire)
    assert preferences[2].read()==saved


def test_repairing_same_phone_keeps_video_record_but_not_video_opt_in_authority(preferences,videos):
    service,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=True,video_destination_choice=choice(videos))
    peer=service.store.peers[0]
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([7])*32)
    service.store.save_peers()
    channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    replacement=ProtectedPhotoPreferences(authority)
    try:
        observed=replacement.read()
        assert observed.policy==saved.policy and not observed.associated and not observed.include_videos
        assert not replacement.local_grant(True).grants.receive_files
        accepted=replacement.configure(replacement.issue_action(),observed,enabled=True,mode='manual')
        assert accepted.associated and not accepted.include_videos
        assert not accepted.policy.videos.enabled and accepted.policy.videos.destination==saved.policy.videos.destination
    finally:replacement.close();authority.close()
