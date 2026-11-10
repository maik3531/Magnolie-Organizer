"""Native provider selection, NOT a permission or a standard KDE capability.

Adapters may supply offers only from the actual authenticated connection of an
explicitly selected/associated phone. Display-name matching and Android manifest
permissions are never evidence for a streaming capability. Both adapters use the
same binary AV/output contract; no second app may start on a failed first start.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import threading

from magnolie_phone_webcam import WebcamUnavailable


VIDEO_PROFILE = 'i420-640x480-15'
AUDIO_PROFILE = 's16le-48000-1'


@dataclass(frozen=True)
class CaptureProviderOffer:
    provider: str
    phone_binding: str
    paired_peer: str
    channel_nonce: str
    revision: int
    profiles: tuple

    def validate(self):
        if (self.provider not in ('kdeconnect', 'notes') or
                any(type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value)
                    for value in (self.phone_binding, self.paired_peer, self.channel_nonce)) or
                type(self.revision) is not int or not 1 <= self.revision <= 9_007_199_254_740_991 or
                type(self.profiles) is not tuple or not 1 <= len(self.profiles) <= 8 or
                any(type(value) is not str or not re.fullmatch('[a-z0-9-]{1,64}', value) for value in self.profiles) or
                len(set(self.profiles)) != len(self.profiles)):
            raise WebcamUnavailable('webcam_provider_offer_invalid')

    def supports(self, muted):
        return VIDEO_PROFILE in self.profiles and (muted or AUDIO_PROFILE in self.profiles)


def _offers(current):
    offers = tuple(current())
    if len(offers) > 2 or any(type(value) is not CaptureProviderOffer for value in offers):
        raise WebcamUnavailable('webcam_provider_offer_invalid')
    for value in offers:
        value.validate()
    if len({value.provider for value in offers}) != len(offers) or len({value.phone_binding for value in offers}) > 1:
        raise WebcamUnavailable('webcam_provider_phone_binding_required')
    return offers


def provider_choice_version(current):
    # Only this digest, never native paired-peer/channel descriptors, goes to UI.
    raw = json.dumps([asdict(value) for value in sorted(_offers(current), key=lambda offer: offer.provider)],
        sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(b'magnolie-webcam-providers-v1\0' + raw).hexdigest()


class PreparedCaptureProvider:
    """Sticky, one-use native START selection. Metadata alone grants no capture.

    The selected adapter must independently obtain genuine Android consent and
    bind the original channel/secret. A refusal/pending result is NOT permission
    to invoke the other adapter. Both apps' permissions remain independent.
    """
    def __init__(self, current, expected_version, selection='auto', *, muted=False, enabled=lambda: False):
        if selection not in ('auto', 'kdeconnect', 'notes') or type(muted) is not bool:
            raise WebcamUnavailable('webcam_provider_choice_invalid')
        if not callable(enabled) or enabled() is not True:
            raise WebcamUnavailable('webcam_feature_disabled')
        self.enabled = enabled
        self.current = current
        self.lock = threading.RLock()
        self.retired = self.claimed = False
        offers = _offers(current)
        if provider_choice_version(lambda: offers) != expected_version:
            raise WebcamUnavailable('webcam_provider_choice_stale')
        ordered = ('notes', 'kdeconnect') if selection == 'auto' else (selection,)
        self.offer = next((offer for name in ordered for offer in offers if offer.provider == name and offer.supports(muted)), None)
        if self.offer is None:
            raise WebcamUnavailable('webcam_provider_streaming_unsupported')
        self.muted = muted
        self.require()

    def require(self):
        with self.lock:
            try:
                if self.retired or self.enabled() is not True or self.offer not in _offers(self.current):
                    raise WebcamUnavailable('webcam_provider_original_context_retired')
            except BaseException:
                self.retired = True
                raise

    def claim_start(self):
        with self.lock:
            self.require()
            if self.claimed:
                raise WebcamUnavailable('webcam_provider_start_already_claimed')
            self.claimed = True
            return self.offer  # Native adapter dispatch only, NOT a capture grant.

    def close(self):
        with self.lock:
            self.retired = True
