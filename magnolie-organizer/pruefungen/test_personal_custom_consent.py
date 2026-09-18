"""Contract tests only; these do not establish durable runtime integration."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_personal_sync as sync

CONTRACTS = ROOT.parent / "contracts"
if not (CONTRACTS / "personal-custom-consent-v4-vectors.json").is_file():
    CONTRACTS = ROOT / "contracts"
V = json.loads((CONTRACTS / "personal-custom-consent-v4-vectors.json").read_text())


def test_source_identity_vectors_and_no_truncation():
    for vector in V["identities"]:
        assert sync.custom_source_id(V["source_id"], vector["item_id"]) == vector["id"]
        assert sync.custom_source_id(V["other_source_id"], vector["item_id"]) != vector["id"]
    long = V["long_identity"]
    item = long["character"] * long["repeat"]
    assert sync.custom_source_id(V["source_id"], item) == long["id"]
    assert sync.custom_source_id(V["source_id"], item[:-1] + "b") != long["id"]
    assert sync.custom_source_id(V["source_id"], "\U0001f331" * 160) == V["unicode_identity"]["id"]
    assert sync.custom_source_id(V["source_id"], "a:b") != sync.custom_source_id(V["source_id"], "a")
    assert sync.custom_source_id(V["source_id"], " a") != sync.custom_source_id(V["source_id"], "a")
    for invalid in ("", item + "a", "\U0001f331" * 161, "\ud800", "a\0b", "a\nb", "a\x7fb"):
        with pytest.raises(ValueError):
            sync.custom_source_id(V["source_id"], invalid)


def test_exact_scope_schema():
    for key in ("local", "remote", "revoked", "reenabled"):
        assert sync.validate_custom_settings(V[key]) == V[key]
    for value in V["invalid_settings"] + [None, {}, [], True]:
        with pytest.raises(ValueError):
            sync.validate_custom_settings(value)


def test_published_json_schema_vectors():
    import jsonschema
    schema = json.loads((CONTRACTS / "personal-custom-consent-v4.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    for key in ("local", "remote", "revoked", "reenabled"):
        validator.validate(V[key])
    for value in V["invalid_settings"]:
        assert not validator.is_valid(value)


def test_bilateral_permission_and_captured_fences():
    local, remote = V["local"], V["remote"]
    def allowed(**changes):
        args = dict(local=local, remote=remote, local_versions=[1, 2, 3, 4],
                    remote_versions=[1, 2, 3, 4], own_device=True, remote_own_device=True,
                    sender_epoch=remote["epoch"], receiver_epoch=local["epoch"],
                    sender_revision=remote["revision"], receiver_revision=local["revision"])
        args.update(changes)
        return sync.custom_scope_allowed(**args)
    assert allowed()
    for changes in ({"local": None}, {"remote": None}, {"local": V["revoked"]},
                    {"remote": V["revoked"]}, {"own_device": False}, {"remote_own_device": False},
                    {"local_versions": [1, 2, 3]}, {"remote_versions": [1, 2, 3]},
                    {"local_versions": ["4"]}, {"sender_epoch": local["epoch"]},
                    {"receiver_epoch": remote["epoch"]}, {"remote": V["reenabled"]},
                    {"sender_revision": True}, {"receiver_revision": 2},
                    {"remote": dict(remote, revision=3)}):
        assert not allowed(**changes), changes
    assert allowed(remote=V["reenabled"], sender_epoch=V["reenabled"]["epoch"], sender_revision=3)


def test_settings_rollback_equivocation_and_restart_roundtrip():
    remote = sync.accept_custom_settings(None, V["remote"])
    assert sync.accept_custom_settings(remote, dict(remote)) == remote
    for key in ("revoked", "reenabled"):
        remote = sync.accept_custom_settings(remote, V[key])
        remote = json.loads(json.dumps(remote))
        with pytest.raises(ValueError):
            sync.accept_custom_settings(remote, V["remote"])
    for invalid in (dict(remote, enabled=False), dict(remote, revision=4)):
        with pytest.raises(ValueError):
            sync.accept_custom_settings(remote, invalid)


def test_ordinary_protocol_keeps_its_exact_versions_and_settings():
    assert sync.FORMATS == [1, 2, 3]
    sync.validate_body("personal_sync.settings", {"format": 1, "own_device": True})
    for body in (V["local"], {"format": 1, "own_device": True, "custom": True}):
        with pytest.raises(ValueError):
            sync.validate_body("personal_sync.settings", body)
    with pytest.raises(ValueError):
        sync.validate_body("personal_sync.custom_settings", V["local"])
    for version in (1, 2, 3):
        sync.validate_body("personal_sync.request", {"format": version, "run_id": V["source_id"],
            "trigger": "manual", "modules": ["notes", "tasks"]})
        with pytest.raises(ValueError):
            sync.validate_body("personal_sync.request", {"format": version, "run_id": V["source_id"],
                "trigger": "manual", "modules": ["custom"]})
