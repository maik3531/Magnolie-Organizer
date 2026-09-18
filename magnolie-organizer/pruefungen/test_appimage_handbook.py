"""Handbook closure for a standalone AppImage, without a host handbook package."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

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
