"""Issue #27: authenticated desktop availability is not a permission grant."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_personal_sync as sync
import magnolie_telefon as phone
from test_personal_sync import _personal_service
from test_personal_note_mode import NoteChannel, note_packet


def test_features_schema_is_exact_typed_and_monotonic():
    body = {"format": 6, "revision": 1, "custom_tab": False, "tree": True}
    assert sync.accept_desktop_features(None, body) == body
    assert sync.accept_desktop_features(body, body) == body
    for bad in (dict(body, custom_tab="false"), dict(body, tree=0), dict(body, revision=True),
                dict(body, revision=0), dict(body, extra=False), dict(body, format=5)):
        with pytest.raises(ValueError):
            sync.validate_desktop_features(bad)
    with pytest.raises(ValueError):
        sync.accept_desktop_features(body, dict(body, tree=False))
    newer = dict(body, revision=2, tree=False)
    assert sync.accept_desktop_features(body, newer) == newer
    with pytest.raises(ValueError):
        sync.accept_desktop_features(newer, body)


def test_features_are_durable_and_unchanged_updates_do_not_advance(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Synthetic")
    assert store.desktop_features() == {}
    first = store.set_desktop_features(True, False)
    assert store.set_desktop_features(True, False) == first
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Synthetic")
    assert reopened.desktop_features() == first
    newer = reopened.set_desktop_features(False, True)
    assert newer["revision"] > first["revision"]


def test_availability_waits_for_fresh_supported_peer_without_changing_permissions(tmp_path, monkeypatch):
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        body = original(*args, **kwargs)
        versions = body["items"]["personal_tasks_sync"]["versions"]
        if 6 not in versions:
            versions.append(6)
        return body
    monkeypatch.setattr(phone, "desktop_capabilities", capabilities)
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id)
    peer["capabilities"] = capabilities()
    service.store.save_peers()
    previous_grants = copy.deepcopy(peer["local_grants"])
    channel = NoteChannel(); service.connections[peer_id] = channel
    service.set_desktop_features(True, False)
    assert not any(item.get("kind") == sync.DESKTOP_FEATURES_KIND for item in channel.sent)
    service._payload(peer, channel, note_packet("capabilities.update", capabilities(2)))
    feature = next(item for item in channel.sent if item.get("kind") == sync.DESKTOP_FEATURES_KIND)
    assert feature["body"] == service.store.desktop_features()
    assert peer["local_grants"] == previous_grants
    legacy = capabilities(3); legacy["items"]["personal_tasks_sync"]["versions"].remove(6)
    service._payload(peer, channel, note_packet("capabilities.update", legacy))
    channel.sent.clear()
    service.set_desktop_features(False, True)
    assert not any(item.get("kind") == sync.DESKTOP_FEATURES_KIND for item in channel.sent)
