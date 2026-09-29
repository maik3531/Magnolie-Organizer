"""Provision owned transports without changing user content-feature decisions."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_hintergrund as background


@pytest.fixture
def profile(tmp_path, monkeypatch):
    for key in ('HOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'):
        path = tmp_path / key
        path.mkdir(mode=0o700)
        monkeypatch.setenv(key, str(path))
    monkeypatch.delenv('APPIMAGE', raising=False)
    monkeypatch.delenv('FLATPAK_ID', raising=False)
    monkeypatch.setattr(background, 'classify_and_adopt', lambda: 'ready')
    monkeypatch.setattr(background, 'automatic_services_supported', lambda *_: True)
    monkeypatch.setattr(background, 'daemon_available', lambda: False)
    starts = []
    monkeypatch.setattr(background, 'start_service', lambda *args: starts.append(args) or True)
    return tmp_path, starts


def test_transport_provisioning_preserves_function_optouts_and_content_grants(profile):
    root, starts = profile
    tree = Path(background.data_directory()) / 'baum.json'
    tree.write_text('{"an":false,"partner":[]}')
    phone = tree.parent / 'telefon' / 'settings.json'
    phone.parent.mkdir()
    phone.write_text('{"enabled":false}')
    previous_tree, previous_phone = tree.read_bytes(), phone.read_bytes()
    background.write_settings({'permissions': {'phone_call_notifications': True}},
                              path=background.settings_path())
    executable = str(root / 'magnolie-organizer')
    assert background.ensure_automatic_services(executable, 'de')
    settings = background.read_settings()
    assert settings['enabled'] and settings['autostart']
    assert settings['permissions']['phone_call_notifications']
    assert {key for key, allowed in settings['permissions'].items() if allowed} == {
        'kde_pairing', 'phone_monitor', 'phone_pairing_decisions', 'phone_call_notifications'}
    assert tree.read_bytes() == previous_tree and phone.read_bytes() == previous_phone
    assert starts == [(executable, 'de')]
    assert '--hintergrunddienst' in Path(background.autostart_path()).read_text()


@pytest.mark.parametrize('setup_state,supported', [('fresh', True), ('pending', True), ('damaged', True), ('ready', False)])
def test_unsupported_or_unfinished_setup_never_starts_or_provisions(profile, monkeypatch, setup_state, supported):
    _, starts = profile
    monkeypatch.setattr(background, 'classify_and_adopt', lambda: setup_state)
    monkeypatch.setattr(background, 'automatic_services_supported', lambda *_: supported)
    assert not background.ensure_automatic_services('/fixture/program')
    assert not starts and not Path(background.autostart_path()).exists()
    assert not Path(background.settings_path()).exists()


@pytest.mark.parametrize('raw', ['{broken', '[false]', '{"enabled":"false"}', '{"permissions":{"phone_monitor":1}}'])
def test_invalid_existing_settings_are_not_replaced(profile, raw):
    _, starts = profile
    path = Path(background.settings_path())
    path.write_text(raw)
    with pytest.raises(ValueError):
        background.ensure_automatic_services('/fixture/program')
    assert path.read_text() == raw and not starts
    assert not Path(background.autostart_path()).exists()


def test_existing_daemon_is_updated_once_without_starting_another_owner(profile, monkeypatch):
    _, starts = profile
    monkeypatch.setattr(background, 'daemon_available', lambda: True)
    calls = []
    def request(method, payload):
        calls.append(method)
        assert method == 'set_settings'
        return background.write_settings(payload['settings'], path=background.settings_path())
    monkeypatch.setattr(background, 'ipc_request', request)
    assert background.ensure_automatic_services('/fixture/program')
    before = Path(background.settings_path()).read_bytes()
    assert background.ensure_automatic_services('/fixture/program')
    assert calls == ['set_settings'] and not starts
    assert Path(background.settings_path()).read_bytes() == before
