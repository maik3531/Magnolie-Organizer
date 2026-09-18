"""Handbook closure for a standalone AppImage, without a host handbook package."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('appimage_handbook', ROOT / 'werkzeuge/appimage_handbook.py')
packer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packer)


def test_bundled_handbook_has_own_program_assets_and_all_locales(tmp_path):
    source = ROOT.parent / 'magnolie-handbuch'
    appdir = tmp_path / 'AppDir'
    packer.bundle(appdir, source, '2.0.19')
    program = appdir / 'usr/lib/magnolie-handbuch/magnolie-handbuch'
    assert (appdir / 'usr/bin/magnolie-handbuch').stat().st_mode & 0o111
    assert (appdir / 'usr/share/magnolie-handbuch/web/index.html').is_file()
    assert (appdir / 'usr/share/magnolie-handbuch/web/i18n/en.js').is_file()
    languages = (source / 'po/LINGUAS').read_text().split()
    assert len(languages) == 19
    for language in languages:
        assert (appdir / 'usr/share/magnolie-handbuch/web/i18n' / (language + '.js')).is_file()
        assert (appdir / 'usr/share/locale' / language / 'LC_MESSAGES/magnolie-handbuch.mo').is_file()
    env = dict(os.environ, HOME=str(tmp_path), XDG_STATE_HOME=str(tmp_path / 'state'),
               PATH='', MAGNOLIE_HANDBUCH_WEB=str(appdir / 'usr/share/magnolie-handbuch/web'),
               MAGNOLIE_HANDBUCH_LOCALE=str(appdir / 'usr/share/locale'))
    result = subprocess.run([sys.executable, str(program), '--version'], env=env,
                            capture_output=True, text=True, timeout=20, check=True)
    assert result.stdout.strip() == '2.0.19'


@pytest.mark.parametrize('mounted', [True, False])
def test_launcher_reinitializes_runtime_and_preserves_session(tmp_path, mounted):
    appdir = tmp_path / 'AppDir with spaces'
    binary = appdir / 'usr/bin'
    binary.mkdir(parents=True)
    (binary / 'python3').symlink_to(sys.executable)
    launcher = binary / 'magnolie-handbuch'
    packer.write_launcher(launcher)
    target = tmp_path / 'Organizer with spaces.AppImage' if mounted else appdir / 'AppRun'
    keys = ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME', 'PYTHONPATH', 'SSL_CERT_FILE',
            'HOME', 'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
            'MAGNOLIE_GRAPHICS_COMPAT', 'PATH', 'XDG_DATA_DIRS')
    target.write_text('#!' + sys.executable + '\nimport json, os, sys\n'
                      f'keys = {keys!r}\n'
                      'print(json.dumps({"args": sys.argv[1:], "env": '
                      '{key: os.environ[key] for key in keys if key in os.environ}}))\n')
    target.chmod(0o755)
    env = dict(os.environ, APPDIR=str(appdir), APPIMAGE=str(target) if mounted else '',
               PATH=str(binary) + os.pathsep + os.defpath,
               XDG_DATA_DIRS=str(appdir / 'usr/share') + ':/usr/share',
               LD_LIBRARY_PATH=str(appdir / 'usr/lib'), LD_PRELOAD='libm.so.6',
               PYTHONHOME=sys.prefix, PYTHONPATH=str(appdir / 'usr/lib/python3/dist-packages'),
               SSL_CERT_FILE=str(appdir / 'usr/share/certs/ca-certificates.crt'),
               HOME=str(tmp_path), DISPLAY=':42', XAUTHORITY=str(tmp_path / 'xauth'),
               DBUS_SESSION_BUS_ADDRESS='unix:path=/test/session', MAGNOLIE_GRAPHICS_COMPAT='1')
    result = subprocess.run([str(launcher), '--language', 'de', 'literal value; not a shell command'],
                            env=env, capture_output=True, text=True, timeout=20, check=True)
    data = json.loads(result.stdout)
    assert data['args'] == ['--handbook', '--language', 'de', 'literal value; not a shell command']
    for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME', 'PYTHONPATH', 'SSL_CERT_FILE'):
        assert name not in data['env']
    for name in ('HOME', 'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'MAGNOLIE_GRAPHICS_COMPAT'):
        assert data['env'][name] == env[name]
    assert str(appdir) not in data['env']['PATH']
    assert data['env']['XDG_DATA_DIRS'] == '/usr/share'
