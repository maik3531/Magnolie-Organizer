"""Two independent provider lanes, never two active capture starts/fallback grants."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_camera_provider import (CaptureProviderOffer, PreparedCaptureProvider,
    VIDEO_PROFILE, AUDIO_PROFILE, provider_choice_version)
from magnolie_phone_webcam import WebcamUnavailable


def offer(provider, profiles=(VIDEO_PROFILE, AUDIO_PROFILE)):
    return CaptureProviderOffer(provider, 'a' * 64, ('b' if provider == 'notes' else 'c') * 64,
        ('d' if provider == 'notes' else 'e') * 64, 1, profiles)


def prepare(offers, choice='auto', muted=False):
    current = lambda: tuple(offers)
    return PreparedCaptureProvider(current, provider_choice_version(current), choice, muted=muted, enabled=lambda: True)


def test_auto_prefers_notes_and_uses_kde_only_if_genuinely_supported_and_notes_unavailable():
    notes = offer('notes'); kde = offer('kdeconnect', ('android-camera-permission', 'android-record-audio-permission'))
    assert prepare([notes, kde]).offer == notes
    assert prepare([notes, offer('kdeconnect')]).offer.provider == 'notes'
    assert prepare([offer('kdeconnect')]).offer.provider == 'kdeconnect'
    with pytest.raises(WebcamUnavailable, match='unsupported'): prepare([kde])


def test_explicit_notes_selection_is_preserved_even_when_kde_streaming_is_available():
    choice = prepare([offer('notes'), offer('kdeconnect')], 'notes')
    assert choice.claim_start().provider == 'notes'
    with pytest.raises(WebcamUnavailable, match='already_claimed'): choice.claim_start()


def test_missing_or_video_only_kde_never_silently_replaces_explicit_choice_with_notes():
    with pytest.raises(WebcamUnavailable, match='unsupported'):
        prepare([offer('notes'), offer('kdeconnect', (VIDEO_PROFILE,))], 'kdeconnect')
    assert prepare([offer('kdeconnect', (VIDEO_PROFILE,))], 'kdeconnect', muted=True).offer.provider == 'kdeconnect'


@pytest.mark.parametrize('change', ['disconnect', 'channel', 'permission_metadata', 'peer'])
def test_original_provider_context_stays_retired_after_metadata_aba(change):
    original = offer('kdeconnect'); offers = [original, offer('notes')]
    choice = prepare(offers, 'kdeconnect')
    choice.claim_start()
    if change == 'disconnect': offers.pop(0)
    if change == 'channel': offers[0] = replace(original, channel_nonce='f' * 64)
    if change == 'permission_metadata': offers[0] = replace(original, revision=2)
    if change == 'peer': offers[0] = replace(original, paired_peer='f' * 64)
    with pytest.raises(WebcamUnavailable, match='retired'): choice.require()
    offers[:] = [original, offer('notes')]
    with pytest.raises(WebcamUnavailable, match='retired'): choice.require()
    with pytest.raises(WebcamUnavailable, match='retired'): choice.claim_start()


def test_an_unselected_provider_change_does_not_replace_the_selected_capture_owner():
    offers = [offer('notes'), offer('kdeconnect')]
    choice = prepare(offers, 'notes')
    offers.pop()
    choice.require()
    assert choice.claim_start().provider == 'notes'


def test_two_different_phones_cannot_be_merged_by_shared_display_name():
    with pytest.raises(WebcamUnavailable, match='binding_required'):
        prepare([offer('notes'), replace(offer('kdeconnect'), phone_binding='f' * 64)])


def test_stale_ui_snapshot_never_claims_new_native_provider_or_reconnect():
    offers = [offer('notes')]
    current = lambda: tuple(offers)
    version = provider_choice_version(current)
    offers[0] = replace(offers[0], channel_nonce='f' * 64)
    with pytest.raises(WebcamUnavailable, match='stale'):
        PreparedCaptureProvider(current, version, enabled=lambda: True)


def test_provider_close_never_transfers_start_to_other_app():
    choice = prepare([offer('notes'), offer('kdeconnect')])
    choice.close()
    with pytest.raises(WebcamUnavailable, match='retired'): choice.claim_start()


def test_optional_feature_defaults_off_without_even_querying_connected_apps():
    def forbidden():
        pytest.fail('Disabled webcam queried an installed provider')
    with pytest.raises(WebcamUnavailable, match='feature_disabled'):
        PreparedCaptureProvider(forbidden, 'any-old-ui-version')


def test_explicit_webcam_opt_out_permanently_retires_original_provider_start():
    offers = [offer('notes'), offer('kdeconnect')]
    enabled = [True]
    current = lambda: offers
    choice = PreparedCaptureProvider(current, provider_choice_version(current), enabled=lambda: enabled[0])
    assert choice.claim_start().provider == 'notes'
    enabled[0] = False
    with pytest.raises(WebcamUnavailable, match='retired'): choice.require()
    enabled[0] = True
    with pytest.raises(WebcamUnavailable, match='retired'): choice.require()
