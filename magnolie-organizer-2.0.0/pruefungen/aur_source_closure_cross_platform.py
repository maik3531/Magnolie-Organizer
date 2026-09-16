"""Explicit source/install-list fixtures, not a product/package build."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / 'magnolie-organizer-2.0.0'
WINDOWS = ROOT / 'Magnolie-Organizer-Windows-2.0.0'
sys.path.insert(0, str(LINUX / 'werkzeuge'))
from release_sources import source_files

PROGRAMS = ('save-custom-regressions.js', 'planned-sms-save-regressions.js', 'aur-sms-regressions.js',
            'device-identifiers.js', 'call-audio-regressions.js')
ASSETS = ('anwendung.js', 'phone-metadata-LICENSE.txt', 'phone-metadata-NOTICE.txt')


def test_current_notes_manifest_matches_internal_alias_audit():
    source = ROOT / 'magnolie-notes-1.0.13/app/src/main/AndroidManifest.xml'
    aliases = ET.parse(source).findall('./application/activity-alias')
    assert len(aliases) == 1
    alias = aliases[0]
    android = '{http://schemas.android.com/apk/res/android}'
    assert alias.get(android + 'name') == '.MainActivityCustom'
    assert alias.get(android + 'targetActivity') == '.MainActivity' and alias.get(android + 'exported') == 'false'
    assert len(alias) == 0


def test_notes_audit_cases_run_in_standalone_linux_source(tmp_path):
    standalone = tmp_path / 'standalone-linux'
    subprocess.run([sys.executable, '-B', str(LINUX / 'werkzeuge/release_sources.py'),
                    'copy', str(LINUX), str(standalone)], check=True)
    assert not (standalone.parent / 'magnolie-notes-1.0.13').exists()
    result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                             'pruefungen/test_notes_provenance.py'], cwd=standalone,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'skipped' not in result.stdout


def test_new_checks_are_public_and_source_selected():
    linux = {str(name) for name, _ in source_files(LINUX)}
    windows = {str(name) for name, _ in source_files(WINDOWS)}
    for name in ('aur07-08-verify.py', 'aur07-08-ui.cjs', 'aur07-08-native.cs.txt',
                 'aur_import_print_cross_platform.py', 'aur_source_closure_cross_platform.py',
                 'aur_save_cross_platform.py', 'aur-save-native.py', 'aur-save-native.cs.txt',
                 'test_aur_sms.py', 'test_save_restore_boundary.py'):
        assert 'pruefungen/' + name in linux
    runner = (WINDOWS / 'tests/run.js').read_text()
    for name in PROGRAMS:
        assert 'tests/' + name in windows and '"' + name + '"' in runner
    assert 'tests/aur-phone-vectors.js' in windows
    assert 'werkzeuge/phone_metadata.py' in windows and 'werkzeuge/phone_metadata.py' in linux
    assert (LINUX / 'werkzeuge/phone_metadata.py').read_bytes() == (WINDOWS / 'werkzeuge/phone_metadata.py').read_bytes()
    assert 'aur-phone-vectors.js' in (LINUX / 'pruefungen/test_aur_sms.py').read_text()
    for name in ASSETS:
        assert 'web/' + name in linux and 'app/web/' + name in windows


def test_new_windows_checks_run_from_standalone_source(tmp_path):
    standalone = tmp_path / 'standalone-windows'
    selected = dict((str(name), path) for name, path in source_files(WINDOWS))
    for name, source in selected.items():
        if name in {'tests/' + name for name in PROGRAMS} or name.startswith('app/web/') or name == 'WindowsBluetoothRadio.cs':
            target = standalone / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copytree(ROOT / 'contracts', standalone / 'contracts')
    env = dict(os.environ, NODE_PATH=str(WINDOWS / 'node_modules'))
    runtime = os.environ.get('MAGNOLIE_BUN') or shutil.which('bun') or shutil.which('node')
    assert runtime
    for name in PROGRAMS:
        result = subprocess.run([runtime, str(standalone / 'tests' / name)], cwd=standalone,
                                env=env, text=True, capture_output=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'FAIL' not in result.stdout and 'SKIP' not in result.stdout
    rejected = subprocess.run([runtime, str(standalone / 'tests/aur-sms-regressions.js'), 'not-a-scenario'],
                              cwd=standalone, env=env, capture_output=True)
    assert rejected.returncode != 0


@pytest.mark.parametrize('kind', ['deb', 'rpm', 'appimage', 'flatpak', 'windows'])
def test_phone_asset_install_inventory(kind, tmp_path):
    web = LINUX / 'web'
    installed = tmp_path / 'web'
    installed.mkdir()
    if kind == 'deb':
        assert 'GPL-3+ and Apache-2.0' in (LINUX / 'debian/copyright').read_text()
        entries = [line.split()[0] for line in (LINUX / 'debian/install').read_text().splitlines()
                   if line.split() and len(line.split()) == 2 and line.split()[1] == 'usr/share/magnolie-organizer/web']
        for name in ASSETS:
            assert 'web/' + name in entries
    elif kind == 'rpm':
        recipe = (LINUX / 'rpm/magnolie-organizer.spec').read_text()
        assert 'Apache-2.0' in next(line for line in recipe.splitlines() if line.startswith('License:'))
        install = re.search(r'install -pm 0644 web/index.html.*?%\{buildroot\}%\{_datadir\}/%\{name\}/web/', recipe, re.S)[0]
        for name in ASSETS:
            assert 'web/' + name in install
    elif kind == 'appimage':
        assert 'cp -a "$WURZEL/web/." "$APPDIR/usr/share/magnolie-organizer/web/"' in (LINUX / 'werkzeuge/appimage_bauen.sh').read_text()
    elif kind == 'flatpak':
        recipe = json.loads((LINUX / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())
        assert 'cp -a web/. /app/share/magnolie-organizer/web/' in recipe['modules'][-1]['build-commands']
    else:
        web = WINDOWS / 'app/web'
        project = ET.parse(WINDOWS / 'MagnolieOrganizer.Windows.csproj')
        assert any(node.get('Include') == 'app\\web\\**\\*' and node.findtext('CopyToOutputDirectory')
                   for node in project.findall('.//Content'))
    for name in ASSETS:
        shutil.copyfile(web / name, installed / name)
        assert (installed / name).read_bytes() == (web / name).read_bytes()
    license_text = (installed / ASSETS[1]).read_text()
    assert 'Apache License' in license_text and 'END OF TERMS AND CONDITIONS' in license_text and len(license_text) > 10000
    notice = (installed / ASSETS[2]).read_text()
    assert '8.12.57' in notice and 'Libphonenumber Authors' in notice and 'python-phonenumbers' in notice
    assert (LINUX / 'web' / ASSETS[1]).read_bytes() == (WINDOWS / 'app/web' / ASSETS[1]).read_bytes()
    assert 'BEGIN GENERATED PHONE METADATA' in (installed / 'anwendung.js').read_text()
    assert not re.search(r'<script[^>]+src=["\'](?:https?:)?//', (web / 'index.html').read_text(), re.I)
