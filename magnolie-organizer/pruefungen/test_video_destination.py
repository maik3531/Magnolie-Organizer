"""Native video folder choices are independent metadata, never video opt-in."""
from pathlib import Path
from dataclasses import replace
import sys
import types

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_destination import (NativeVideoDestinationController, NativeVideoDestinationChoice,
    NativePhotoDestinationController, photo_folder_component, video_folder_component, native_videos_directory)
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_file_transfer import TransferError
from test_photo_destination import chooser
from test_file_authenticated_desktop import native


@pytest.fixture
def video(chooser,tmp_path):
    service,peer,authority,photos,pictures,clock=chooser
    videos=tmp_path/'native-videos';videos.mkdir(mode=0o700)
    controller=NativeVideoDestinationController(authority,monotonic_ms=lambda:clock[0])
    try:yield service,peer,authority,photos,pictures,clock,controller,videos
    finally:controller.close()


def test_native_video_choice_is_inert_and_uses_videos_not_the_photo_location(video):
    service,peer,_,photos,pictures,_,controller,videos=video
    snapshot={p.name:p.read_bytes() for p in Path(service.store.root).iterdir() if p.is_file()}
    action=controller.issue_action()
    assert not list(videos.iterdir()) and not list(pictures.iterdir())
    chosen=controller.choose_default(action,videos_provider=lambda:videos)
    assert type(chosen) is NativeVideoDestinationChoice
    assert chosen.destination.path==str(videos/video_folder_component(peer['display_name']))
    assert chosen.destination.path.endswith('-Videos') and controller.verify_choice(chosen)==chosen.destination
    assert not chosen.destination.grants_write_authority and not list(pictures.iterdir())
    photo=photos.choose_default(photos.issue_action(),pictures_provider=lambda:pictures)
    assert photo.destination.path.endswith('-Fotos') and photo.destination_token!=chosen.destination_token
    assert snapshot=={p.name:p.read_bytes() for p in Path(service.store.root).iterdir() if p.is_file()}


def test_video_custom_choice_is_separate_and_cannot_substitute_for_photo_policy_consent(video,tmp_path):
    _,_,authority,photos,pictures,_,controller,videos=video
    custom=tmp_path/'explicit-video-choice';custom.mkdir(mode=0o700)
    choice=controller.choose_custom(controller.issue_action(),custom)
    assert type(choice) is NativeVideoDestinationChoice and choice.destination.path==str(custom)
    with pytest.raises(TransferError):photos.verify_choice(choice)
    photo=photos.choose_custom(photos.issue_action(),pictures)
    with pytest.raises(TransferError):controller.verify_choice(photo)
    prefs=ProtectedPhotoPreferences(authority)
    try:
        before=prefs.read()
        with pytest.raises(TransferError,match='foreign_destination_choice'):
            prefs.configure(prefs.issue_action(),before,enabled=True,mode='manual',destination_choice=choice)
        assert prefs.read().policy is None
    finally:prefs.close()
    assert not list(custom.iterdir()) and not list(videos.iterdir())


def test_native_video_resolution_uses_glib_videos_constant_without_home_or_pictures_fallback(video,monkeypatch):
    *_,videos=video
    requested=[];constant=object()
    glib=types.SimpleNamespace(UserDirectory=types.SimpleNamespace(DIRECTORY_VIDEOS=constant),
        get_user_special_dir=lambda kind:requested.append(kind) or str(videos))
    gi=types.ModuleType('gi');gi.__path__=[];repository=types.ModuleType('gi.repository');repository.GLib=glib
    monkeypatch.setitem(sys.modules,'gi',gi);monkeypatch.setitem(sys.modules,'gi.repository',repository)
    monkeypatch.setenv('HOME','/not-the-native-videos-folder')
    assert native_videos_directory()==str(videos) and requested==[constant]
    glib.get_user_special_dir=lambda kind:None
    with pytest.raises(TransferError,match='native_videos_unavailable'):native_videos_directory()


@pytest.mark.parametrize('reason',['expired','rollback','closed','revoked','photo-action','wire','unavailable','late-provider'])
def test_unready_video_choice_does_not_create_default_folders(video,reason):
    _,_,authority,photos,pictures,clock,controller,videos=video
    action=controller.issue_action()
    if reason=='expired':clock[0]+=60_000
    elif reason=='rollback':clock[0]-=1
    elif reason=='closed':controller.close()
    elif reason=='revoked':authority.revoke()
    elif reason=='photo-action':action=photos.issue_action()
    elif reason=='wire':action={'token':'wire'}
    def provider():
        if reason=='late-provider':clock[0]+=60_000
        return None if reason=='unavailable' else videos
    with pytest.raises(TransferError):controller.choose_default(action,videos_provider=provider)
    assert not list(videos.iterdir()) and not list(pictures.iterdir())


def test_existing_video_edits_and_custom_folder_are_preserved_without_symlink_adoption(video,tmp_path):
    _,peer,_,_,_,_,controller,videos=video
    folder=videos/video_folder_component(peer['display_name']);folder.mkdir(mode=0o700)
    existing=folder/'user-video.mp4';existing.write_bytes(b'user edited video');inode=existing.stat().st_ino
    controller.choose_default(controller.issue_action(),videos_provider=lambda:videos)
    assert existing.read_bytes()==b'user edited video' and existing.stat().st_ino==inode
    linked=tmp_path/'linked-videos';linked.mkdir(mode=0o700)
    (linked/folder.name).symlink_to(folder,target_is_directory=True)
    with pytest.raises(TransferError):controller.choose_default(controller.issue_action(),videos_provider=lambda:linked)
    assert (linked/folder.name).is_symlink() and existing.read_bytes()==b'user edited video'


@pytest.mark.parametrize('name',['../Downloads','Maiks Telefon','Phone: Videos\\Other','📱'])
def test_video_folder_name_is_one_safe_native_component(name):
    component=video_folder_component(name)
    assert component.endswith('-Videos') and Path(component).name==component
    assert len(component)<=67 and all(c.isalnum() or c in ' -_' for c in component)


@pytest.mark.parametrize('folder',[photo_folder_component,video_folder_component])
def test_phone_name_wins_and_username_is_only_a_safe_fallback(folder):
    suffix='-Videos' if folder is video_folder_component else '-Fotos'
    assert folder('Pixel 9',fallback_user_name='Maik')=='Pixel 9'+suffix
    assert folder('',fallback_user_name='Maik')=='Maik'+suffix
    assert folder('   ',fallback_user_name='../Maik/Downloads')=='Maik_Downloads'+suffix
    assert folder('',fallback_user_name='')=='Telefon'+suffix


def test_known_native_phone_name_does_not_even_read_the_account_name(video):
    _,peer,authority,_,_,clock,_,videos=video
    controller=NativeVideoDestinationController(authority,monotonic_ms=lambda:clock[0],
        username_provider=lambda:pytest.fail('Known phone name was replaced by username lookup'))
    try:
        choice=controller.choose_default(controller.issue_action(),videos_provider=lambda:videos)
        assert Path(choice.destination.path).name==video_folder_component(peer['display_name'])
    finally:controller.close()


@pytest.mark.parametrize('kind',['photo','video'])
def test_native_missing_phone_name_uses_username_fallback_without_changing_custom_paths(video,monkeypatch,kind):
    _,_,authority,_,pictures,clock,_,videos=video
    cls=NativePhotoDestinationController if kind=='photo' else NativeVideoDestinationController
    controller=cls(authority,monotonic_ms=lambda:clock[0],username_provider=lambda:'native-account')
    peer=replace(authority.current_peer(),display_name='')
    monkeypatch.setattr(controller,'_peer',lambda:peer)
    base=pictures if kind=='photo' else videos
    try:
        selected=controller.choose_default(controller.issue_action(),**{('pictures_provider' if kind=='photo' else 'videos_provider'):lambda:base})
        assert Path(selected.destination.path).name=='native-account'+('-Fotos' if kind=='photo' else '-Videos')
        custom=controller.choose_custom(controller.issue_action(),base)
        assert custom.destination.path==str(base)
    finally:controller.close()
