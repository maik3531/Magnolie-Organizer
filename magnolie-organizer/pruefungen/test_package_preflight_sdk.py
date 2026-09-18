"""SDK presence/discovery only: no SDK command, build, emulator or secret read."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'werkzeuge'))
import package_preflight as preflight


def sdk_files(root, complete=False):
    names = ['platform-tools/adb']
    if complete:
        names += ['platforms/android-35/android.jar', 'emulator/emulator',
                  'build-tools/35.0.0/aapt', 'build-tools/35.0.0/apksigner', 'build-tools/35.0.0/zipalign',
                  'system-images/android-34/google_apis/x86_64/system.img']
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Synthetic presence fixture; never executed')
        path.chmod(0o644 if path.suffix in {'.jar', '.img'} else 0o755)
    return root


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    partial = sdk_files(tmp_path / 'partial')
    complete = sdk_files(tmp_path / 'home/.local/share/android-sdk', complete=True)
    monkeypatch.delenv('ANDROID_SDK_ROOT', raising=False)
    monkeypatch.delenv('ANDROID_HOME', raising=False)
    monkeypatch.setattr(preflight, 'android_sdk_candidates', lambda: [partial, complete])
    root = tmp_path / 'source'
    for name in ('magnolie-organizer/po/magnolie-organizer.pot',
                 'magnolie-organizer/werkzeuge/source_selection.py',
                 'magnolie-organizer-windows/tests/Program.cs',
                 'magnolie-organizer-windows/app/po/magnolie-organizer.pot',
                 'magnolie-handbuch-stamm/po/magnolie-handbuch.pot',
                 'magnolie-handbuch-stamm/po/LINGUAS',
                 'magnolie-handbuch-stamm/po/english/protected.po',
                 'magnolie-handbuch-stamm/werkzeuge/source_selection.py',
                 'magnolie-notes-stamm/app/build.gradle.kts'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Synthetic source metadata')
    monkeypatch.setattr(preflight, 'bootstrap_check', lambda *_: None)
    monkeypatch.setattr(preflight, 'release_versions', lambda *_: ('2.0.18', '1.0.14'))
    monkeypatch.setattr(preflight, 'package_modules', lambda *_: {})
    monkeypatch.setattr(preflight, 'notes_inputs', lambda *_: [])
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=1, stdout='', stderr=''))
    for name in ('MAGNOLIE_SCHLUESSEL_PROPERTIES', 'MAGNOLIE_KEYSTORE_FILE',
                 'MAGNOLIE_AKONADI_BUILD_ROOTFS', 'MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE'):
        monkeypatch.setenv(name, str(tmp_path / 'not-supplied'))
    for name in ('MAGNOLIE_CONTRIBUTOR_HASH', 'MAGNOLIE_RELEASE_CERT_SHA256'):
        monkeypatch.delenv(name, raising=False)
    return root, partial, complete


def test_complete_sdk_wins_over_earlier_adb_only_and_is_not_modified(inputs):
    root, partial, complete = inputs
    before = {path: (path.stat().st_mode, path.read_bytes()) for path in complete.rglob('*') if path.is_file()}
    for _ in range(3):
        assert preflight.android_sdk() == complete
    value = preflight.report(root)
    assert value['android']['sdk'] == str(complete)
    assert value['android']['compileSdk35Ready'] is True
    assert value['android']['runtimeImages'] == {'34': True, '35': False}
    assert value['android']['emulator'] == str(complete / 'emulator/emulator')
    assert not any('Android SDK' in error or 'Android platform' in error for error in value['blockers'])
    assert value['brandingConfigured'] is False and value['buildAuthorized'] is False
    assert value['readyForWholeCandidateBuild'] is False  # Tools do not supply artifacts or credentials.
    assert before == {path: (path.stat().st_mode, path.read_bytes()) for path in before}


@pytest.mark.parametrize('override', ['argument', 'ANDROID_SDK_ROOT', 'ANDROID_HOME'])
def test_explicit_partial_sdk_is_reported_not_silently_replaced(inputs, monkeypatch, override):
    root, partial, complete = inputs
    argument = partial if override == 'argument' else None
    if override == 'argument':
        monkeypatch.setenv('ANDROID_SDK_ROOT', str(complete))
    else:
        monkeypatch.setenv(override, str(partial))
        if override == 'ANDROID_SDK_ROOT':
            monkeypatch.setenv('ANDROID_HOME', str(complete))
    assert preflight.android_sdk(argument) == partial
    value = preflight.report(root, sdk=argument)
    assert value['android']['sdk'] == str(partial)
    assert value['android']['compileSdk35Ready'] is False
    assert 'Android platform 35 missing' in value['blockers']
    assert any('explicit overrides are not replaced' in error for error in value['blockers'])


def test_complete_selection_is_stable_and_requires_a_coherent_tool_revision(inputs, monkeypatch):
    _, partial, complete = inputs
    other = sdk_files(partial.parent / 'other-complete', complete=True)
    monkeypatch.setattr(preflight, 'android_sdk_candidates', lambda: [partial, complete, other])
    assert preflight.android_sdk() == complete
    (complete / 'build-tools/34.0.0').mkdir()
    (complete / 'build-tools/35.0.0/aapt').rename(complete / 'build-tools/34.0.0/aapt')
    assert not preflight.android_sdk_complete(complete)
    assert preflight.android_sdk() == other
    monkeypatch.setattr(preflight, 'android_sdk_candidates', lambda: [partial])
    assert preflight.android_sdk() == partial


@pytest.mark.parametrize('xdg', [None, 'absolute', 'relative'])
def test_home_and_xdg_candidates_are_derived_not_username_specific(tmp_path, monkeypatch, xdg):
    home = tmp_path / 'different-user'
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    if xdg:
        monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg') if xdg == 'absolute' else 'relative-data')
    choices = preflight.android_sdk_candidates()
    assert home / '.local/share/android-sdk' in choices
    if xdg == 'absolute':
        assert tmp_path / 'xdg/android-sdk' in choices
    assert all(path.is_absolute() for path in choices)
