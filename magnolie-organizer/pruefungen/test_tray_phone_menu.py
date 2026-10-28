"""Native tray phone state, persisted opt-out and non-pairing reconnection (#270)."""
import copy
from pathlib import Path
from types import SimpleNamespace
import threading
import sys

import pytest
from modul_laden import quellmodul_laden
sys.path.insert(0, str(Path(__file__).parents[1] / 'bin'))
import magnolie_telefon as telephone

product = quellmodul_laden('tray_phone_menu', str(Path(__file__).parents[1] / 'bin/magnolie-organizer'))


@pytest.mark.parametrize('enabled,preference,states,expected', [
    (True, True, [], True), (True, True, ['offline'], True),
    (True, True, ['online_wifi'], False), (True, True, ['online_bluetooth'], False),
    (False, True, [], False), (True, False, [], False),
    (True, False, ['offline'], False), (True, True, ['offline', 'offline'], False)])
def test_connection_action_visibility(enabled, preference, states, expected):
    peers = [{'state': state} for state in states]
    assert product.tray_telefon_verbinden_sichtbar({'telefonWlanVerbinden': preference}, enabled, peers) is expected


def test_preference_defaults_on_for_legacy_settings_and_survives_readback(tmp_path):
    assert product.tray_einstellungen({})['telefonWlanVerbinden'] is True
    path = tmp_path / 'tray.json'
    assert product.tray_einstellungen_schreiben({'aktiv': True, 'telefonWlanVerbinden': False}, str(path))['ok']
    assert product.tray_einstellungen_geprueft_lesen(str(path))['telefonWlanVerbinden'] is False


@pytest.mark.parametrize('connected,enabled,count,expected', [(False, True, 1, True),
    (True, True, 1, False), (False, False, 1, False), (False, True, 0, False), (False, True, 2, False)])
def test_reconnect_preserves_pairing_material_and_only_reannounces_a_known_disconnected_peer(connected, enabled, count, expected):
    phone = telephone.PhoneService.__new__(telephone.PhoneService)
    phone._lifecycle_lock = threading.RLock(); phone.lock = threading.RLock()
    phone.enabled = enabled; phone.server = object()
    phone.store = SimpleNamespace(peers=[{'device_id': str(index), 'static_public': 'owned-public-key'} for index in range(count)])
    phone.connections = {'0': object()} if connected else {}
    phone.pairing_token = b'unchanged-existing-token'; phone.pairing_until = 1234
    before = copy.deepcopy(phone.store.peers), phone.pairing_token, phone.pairing_until
    calls = []
    phone._start_owned = lambda: calls.append('start') or True
    phone._publish = lambda: calls.append('announce')
    phone.report = lambda: {'enabled': enabled}
    phone.callback = lambda *_: calls.append('status')
    assert phone.resume_connection() is expected
    assert (phone.store.peers, phone.pairing_token, phone.pairing_until) == before
    assert calls == (['start', 'announce', 'status'] if expected else [])
