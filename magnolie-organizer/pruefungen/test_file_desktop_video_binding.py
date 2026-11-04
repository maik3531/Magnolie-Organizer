"""Native current video destination/token binding; no source/worker admission."""
import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_video_metadata import prepare
from test_file_desktop_media import manifest
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_file_transfer import TransferError


def test_separate_video_readiness_remains_off_even_with_acknowledged_peer_and_native_video_consent(receiving,tmp_path,monkeypatch):
    prepare(receiving,tmp_path,monkeypatch);connection=receiving[3]
    assert not connection._video_data_handlers_ready
    with pytest.raises(TransferError,match='video_data_join_unavailable'):connection._receive_binding(media_type='video')
    assert connection._receive_binding().destination_token==connection._preferences.read().policy.destination_token
    assert connection._run is None and connection._catalog is None


def test_native_video_binding_uses_its_exact_original_root_and_distinct_token_without_photo_grant_churn(receiving,tmp_path,monkeypatch):
    target=prepare(receiving,tmp_path,monkeypatch);connection=receiving[3]
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)
    photo=connection._receive_binding();grant=connection._preferences.local_grant(True).grants
    video=connection._receive_binding(media_type='video');scope=connection._preferences.read()
    destination=connection._receive_destination(scope,media_type='video')
    assert destination.path==str(target) and destination==scope.policy.videos.destination
    assert video.destination_token==scope.policy.videos.destination_token!=photo.destination_token
    assert video.permission_epoch==photo.permission_epoch and video.sender_id==photo.sender_id
    assert connection._receive_binding()==photo and connection._preferences.local_grant(True).grants==grant
    current=lambda:connection._receive_binding(media_type='video')
    full=manifest(receiving)
    accepted=NativeAcceptedTransfer.capture(full,video,{file.id:file.path for file in full.files},destination.path,current)
    accepted.verify(current)
    assert accepted.destination==destination and not connection.send_controls()
    assert connection._run is None and connection._catalog is None and not list(target.iterdir())


@pytest.mark.parametrize('failure',['withdrawal','local_off','missing','replaced'])
def test_video_binding_rechecks_current_consent_capability_and_native_directory_while_photo_binding_survives(
        receiving,tmp_path,monkeypatch,failure):
    target=prepare(receiving,tmp_path,monkeypatch);connection=receiving[3]
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)
    photo=connection._receive_binding();original=connection._receive_binding(media_type='video')
    if failure=='withdrawal':
        receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    elif failure=='local_off':
        prefs=connection._preferences;prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    elif failure=='missing':target.rmdir()
    else:target.rename(target.with_name('preserved-original-video-root'));target.mkdir(mode=0o700)
    with pytest.raises((TransferError,FileNotFoundError)):connection._receive_binding(media_type='video')
    assert connection._receive_binding()==photo
    assert connection._preferences.read().policy.videos.destination_token==original.destination_token
    assert connection._catalog is None and connection._run is None


def test_video_binding_rechecks_withdrawal_after_native_root_verification_before_return(receiving,tmp_path,monkeypatch):
    prepare(receiving,tmp_path,monkeypatch);connection=receiving[3]
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)
    scope=connection._preferences.read();destination_type=type(scope.policy.videos.destination)
    verify=destination_type.verify
    def withdrawn(self):
        result=verify(self)
        if self==scope.policy.videos.destination:
            receiving[0]._native_file_controls[receiving[2]].pop('capabilities.update',None)
        return result
    monkeypatch.setattr(destination_type,'verify',withdrawn)
    with pytest.raises(TransferError,match='video_metadata_unavailable'):connection._receive_binding(media_type='video')
    assert connection._receive_binding().destination_token==scope.policy.destination_token
