"""Native local relationship generations; no personal stores or key creation."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
from test_telefon import _complete_peer


def test_legacy_validation_and_plain_roundtrip_do_not_create_file_authority():
    peer = _complete_peer()
    peer['personal_sync'].update(own_device=True, remote_own_device=True)
    before = deepcopy(peer)
    phone.PhoneStore._validate_peer(peer)  # Static validation, no store constructor.
    assert phone.current_native_file_pairing_epoch(peer) is None
    assert peer == before and 'file_pairing_epoch' not in peer
    assert phone.current_native_file_pairing_epoch(json.loads(json.dumps(peer))) is None


def test_new_pairing_of_same_id_key_has_distinct_local_generation_but_reconnect_preserves_it():
    peer = _complete_peer()
    peer['personal_sync'].update(own_device=True, remote_own_device=True)
    peer['file_pairing_epoch'] = phone.native_file_pairing_epoch(bytes([1]) * 32)
    phone.PhoneStore._validate_peer(peer)
    resumed = json.loads(json.dumps(peer))
    resumed['last_contact_ms'] = 1000
    assert phone.current_native_file_pairing_epoch(resumed) == peer['file_pairing_epoch']
    re_paired = deepcopy(peer)
    re_paired['file_pairing_epoch'] = phone.native_file_pairing_epoch(bytes([2]) * 32)
    assert peer['device_id'] == re_paired['device_id'] and peer['static_public'] == re_paired['static_public']
    assert phone.current_native_file_pairing_epoch(peer) != phone.current_native_file_pairing_epoch(re_paired)


@pytest.mark.parametrize('change', ['pending', 'own', 'remote-own', 'missing', 'corrupt'])
def test_only_current_complete_native_own_relationship_exposes_generation(change):
    peer = _complete_peer()
    peer['personal_sync'].update(own_device=True, remote_own_device=True)
    peer['file_pairing_epoch'] = phone.native_file_pairing_epoch(bytes([1]) * 32)
    if change == 'pending': peer['state'] = 'pair_commit_pending'
    elif change == 'own': peer['personal_sync']['own_device'] = False
    elif change == 'remote-own': peer['personal_sync']['remote_own_device'] = False
    elif change == 'missing': del peer['file_pairing_epoch']
    else: peer['file_pairing_epoch'] = 'device-label'
    assert phone.current_native_file_pairing_epoch(peer) is None


@pytest.mark.parametrize('value', [None, True, '', 'A' * 64, 'x' * 64])
def test_corrupt_persisted_epoch_is_not_reset_or_treated_as_absent(value):
    peer = _complete_peer()
    peer['file_pairing_epoch'] = value
    before = deepcopy(peer)
    with pytest.raises(RuntimeError): phone.PhoneStore._validate_peer(peer)
    assert peer == before


@pytest.mark.parametrize('value', [bytes(31), bytes(33), bytearray(32), 'label'])
def test_native_transcript_shape_is_not_coerced(value):
    with pytest.raises(ValueError): phone.native_file_pairing_epoch(value)
