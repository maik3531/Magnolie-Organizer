"""Desktop payload composition; Notes and runtime consent are not key-gated."""
import importlib.util
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin')); sys.path.insert(0, str(ROOT / 'werkzeuge'))
import magnolie_optional_phone as policy
from phone_features import stage
from runtime_pruefen import package_modules
from test_file_authenticated_desktop import native


def payload(tmp_path, kind='deb'):
    bindir = tmp_path / 'usr/bin'; data = tmp_path / 'usr/share/magnolie-organizer'
    bindir.mkdir(parents=True); data.mkdir(parents=True)
    for name in package_modules(ROOT)[kind] | {'magnolie-organizer'}:
        shutil.copyfile(ROOT / 'bin' / name, bindir / name)
    return bindir, data


@pytest.mark.parametrize('photo,camera', [(False, False), (True, False), (False, True), (True, True)])
def test_actual_desktop_stage_contains_exact_selected_modules_and_resolves_all_remaining_imports(tmp_path, photo, camera):
    bindir, data = payload(tmp_path)
    selected = dict(photo_sync=photo, phone_camera=camera)
    assert stage(bindir, data, selection=selected) == selected
    runtime = data / 'python'
    all_modules = {path.name for path in (ROOT / 'bin').glob('*.py')}
    assert {path.name for path in runtime.glob('*.py')} == policy.selected_modules(all_modules, selected)
    assert {path.name for path in bindir.iterdir()} == {'magnolie-organizer'}
    assert (runtime / 'magnolie_file_desktop_connection.py').exists() is photo
    assert (runtime / 'magnolie_photo_schedule.py').exists() is photo
    assert json.loads((data / 'build-config.json').read_text())['phoneFeatures'] == selected
    result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'werkzeuge/runtime_pruefen.py'), str(bindir)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    code = '''import pathlib,sys
sys.path.insert(0,sys.argv[1])
import magnolie_optional_phone as p
assert p.available('photo_sync') is (sys.argv[2]=='True')
assert p.available('phone_camera') is (sys.argv[3]=='True')
import magnolie_telefon
assert pathlib.Path(magnolie_telefon.__file__).parent == pathlib.Path(sys.argv[1])
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(runtime), str(photo), str(camera)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unconfigured_self_build_omits_features_but_prepared_distribution_needs_no_user_key(tmp_path):
    bindir, data = payload(tmp_path)
    assert stage(bindir, data) == dict(photo_sync=False, phone_camera=False)
    assert not (data / 'python/magnolie_file_desktop_connection.py').exists()
    (data / 'build-config.json').write_text(json.dumps({'contributorHash': 'a' * 64}))
    assert stage(bindir, data) == dict(photo_sync=True, phone_camera=True)
    assert (data / 'python/magnolie_file_desktop_connection.py').is_file()
    # No personal preferences/key entry are read or changed by build composition.
    assert set(json.loads((data / 'build-config.json').read_text())) == {'contributorHash', 'phoneFeatures'}


@pytest.mark.parametrize('value', [True, [], {'photo_sync': 1}, {'phone_camera': 'true'}, {'unknown': True}])
def test_invalid_composition_never_changes_payload_or_config(tmp_path, value):
    bindir, data = payload(tmp_path)
    original = {path.name: path.read_bytes() for path in bindir.iterdir()}
    with pytest.raises(ValueError): stage(bindir, data, selection=value)
    assert {path.name: path.read_bytes() for path in bindir.iterdir()} == original
    assert not (data / 'build-config.json').exists()


@pytest.mark.parametrize('change', ['foreign_file', 'symlink', 'bytecode'])
def test_composition_refuses_unfamiliar_files_and_stale_compiled_payload(tmp_path, change):
    bindir, data = payload(tmp_path)
    target = bindir / 'magnolie_photo_plan.py'
    if change == 'foreign_file': target.write_bytes(b'preserve unfamiliar local edits')
    elif change == 'symlink': target.symlink_to(ROOT / 'bin/magnolie_photo_plan.py')
    else:
        cache = bindir / '__pycache__'; cache.mkdir(); (cache / 'magnolie_photo_plan.pyc').write_bytes(b'stale fixture bytecode')
    with pytest.raises(ValueError): stage(bindir, data)
    if change == 'foreign_file': assert target.read_bytes() == b'preserve unfamiliar local edits'
    elif change == 'symlink': assert target.is_symlink()
    else: assert (cache / 'magnolie_photo_plan.pyc').read_bytes() == b'stale fixture bytecode'
    assert not (data / 'build-config.json').exists()


def test_installed_audit_rejects_optional_code_left_in_disabled_payload(tmp_path):
    bindir, data = payload(tmp_path); stage(bindir, data)
    shutil.copyfile(ROOT / 'bin/magnolie_photo_plan.py', data / 'python/magnolie_photo_plan.py')
    result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'werkzeuge/runtime_pruefen.py'), str(bindir)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'composition differs' in result.stderr


def test_disabled_desktop_service_never_imports_optional_file_code_or_falls_back_to_personal_route(native, monkeypatch):
    service, peer, _ = native
    monkeypatch.setattr(service, '_native_photo_built', False)
    def forbidden(*_args): pytest.fail('Disabled desktop build imported optional implementation')
    monkeypatch.setattr(service, '_native_file_module', forbidden)
    before = {path.name: path.read_bytes() for path in Path(service.store.root).iterdir() if path.is_file()}
    channel = mock.Mock(); packet = dict(kind='file_transfer.sources.request', body={})
    assert service._send_message(channel, peer['device_id'], packet) is False
    assert service._send_message_locked(channel, peer['device_id'], packet) is False
    with pytest.raises(ValueError): service._payload(peer, channel, packet)
    assert service.current_native_file_identity(peer['device_id'], peer['static_public'], channel, service._generation) is None
    assert channel.send.call_count == 0
    assert {path.name: path.read_bytes() for path in Path(service.store.root).iterdir() if path.is_file()} == before


def test_desktop_packaging_is_selected_before_import_audit_and_never_applies_to_notes():
    for relative in ('debian/rules', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh', 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        text = (ROOT / relative).read_text()
        assert 'phone_features.py' in text and 'runtime_pruefen.py' in text
        assert text.index('phone_features.py') < text.index('runtime_pruefen.py')
    notes = ROOT.parent / 'magnolie-notes/app/build.gradle.kts'
    if notes.is_file():
        gradle = notes.read_text()
        assert 'MAGNOLIE_PHONE_FEATURES' not in gradle and 'phone_features.py' not in gradle
        assert 'contributorHash' not in gradle
    else:
        # A standalone desktop source archive has no Notes sibling to modify.
        assert stage.__globals__['ROOT'] == ROOT and ROOT.name != 'magnolie-notes'


def test_public_wrapper_executes_real_private_program_with_same_cli_and_without_personal_data(tmp_path):
    from test_runtime_packaging import environment
    bindir, data = payload(tmp_path); stage(bindir, data)
    env = environment(tmp_path)
    env['PYTHONPATH'] = str(ROOT / 'bin') # Deliberate wrong-source fallback must not be needed.
    for arguments, expected in ((['--version'], '2.0.30'), (['--language', 'en', '--help'], 'Usage:')):
        result = subprocess.run([sys.executable, '-I', '-B', str(bindir / 'magnolie-organizer'), *arguments],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert expected in result.stdout
    assert not list(bindir.glob('magnolie_*.py'))
    assert not (Path(env['XDG_DATA_HOME']) / 'magnolie-organizer/daten.json').exists()


def test_private_runtime_resource_finders_and_autostart_resolve_this_prefix_not_host_files(tmp_path, monkeypatch):
    import magnolie_hintergrund as background
    bindir, data = payload(tmp_path); stage(bindir, data)
    runtime = data / 'python'; share = data.parent
    for relative in ('web/index.html', 'klang/erinnerung.wav', 'werkzeuge/pot_erzeugen.py'):
        path = data / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture resource')
    locale = share / 'locale/de/LC_MESSAGES'; locale.mkdir(parents=True)
    icon = share / 'icons/hicolor/128x128/apps/magnolie-organizer.png'; icon.parent.mkdir(parents=True); icon.write_bytes(b'fixture icon')
    names = {'finde_web_verzeichnis', 'finde_locale_verzeichnis', 'eigener_pfad', 'magnolie_logo_pfad', 'finde_klang_datei', 'pot_erzeugen'}
    tree = ast.parse((runtime / 'magnolie-organizer').read_text())
    functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    assert {node.name for node in functions.body} == names
    calls = []
    class Process:
        DEVNULL = -3; PIPE = -1
        @staticmethod
        def run(arguments, **_options): calls.append(arguments)
    namespace = dict(os=os, sys=sys, subprocess=Process, __file__=str(runtime / 'magnolie-organizer'), PROGRAMM_NAME='magnolie-organizer')
    for name in ('MAGNOLIE_ORGANIZER_WEB', 'MAGNOLIE_ORGANIZER_KLANG', 'MAGNOLIE_LOCALE_DIR', 'APPIMAGE'):
        monkeypatch.delenv(name, raising=False)
    exec(compile(functions, str(runtime / 'magnolie-organizer'), 'exec'), namespace)
    assert namespace['finde_web_verzeichnis']() == str(data / 'web')
    assert namespace['finde_locale_verzeichnis']() == str(share / 'locale')
    assert namespace['magnolie_logo_pfad']() == str(icon)
    assert namespace['finde_klang_datei']() == str(data / 'klang/erinnerung.wav')
    assert namespace['eigener_pfad']() == str(bindir / 'magnolie-organizer')
    namespace['pot_erzeugen'](str(tmp_path / 'fixture.pot'))
    assert calls[0][1] == str(data / 'werkzeuge/pot_erzeugen.py')
    monkeypatch.setattr(background, '__file__', str(runtime / 'magnolie_hintergrund.py'))
    assert background._locale_directory() == str(share / 'locale')
    assert background.service_executable(str(runtime / 'magnolie-organizer')) == str(bindir / 'magnolie-organizer')


@pytest.mark.parametrize('change', ['foreign_module', 'symlink_directory'])
def test_private_layout_never_overwrites_unfamiliar_code_or_follows_directory_alias(tmp_path, change):
    bindir, data = payload(tmp_path)
    public = {path.name: path.read_bytes() for path in bindir.iterdir()}
    runtime = data / 'python'
    if change == 'foreign_module':
        runtime.mkdir(); held = runtime / 'magnolie_recurrence.py'; held.write_bytes(b'preserve unfamiliar implementation')
    else:
        held = tmp_path / 'unrelated'; held.mkdir(); (held / 'keep').write_bytes(b'preserve unrelated directory')
        runtime.symlink_to(held, target_is_directory=True)
    with pytest.raises(ValueError): stage(bindir, data)
    assert {path.name: path.read_bytes() for path in bindir.iterdir()} == public
    assert not (data / 'build-config.json').exists()
    if change == 'foreign_module': assert held.read_bytes() == b'preserve unfamiliar implementation'
    else: assert (held / 'keep').read_bytes() == b'preserve unrelated directory' and runtime.is_symlink()
