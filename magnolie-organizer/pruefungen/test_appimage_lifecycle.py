"""Actual portable guard execution against synthetic registrations, never host units."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_appimage_lifecycle as lifecycle


@pytest.fixture
def portable(tmp_path, monkeypatch):
    config, data = tmp_path / 'config', tmp_path / 'private data'
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    fake_bin = tmp_path / 'tools'; fake_bin.mkdir()
    log = tmp_path / 'systemctl.log'
    systemctl = fake_bin / 'systemctl'
    systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(log)) + '\n')
    systemctl.chmod(0o700)
    monkeypatch.setenv('PATH', str(fake_bin) + os.pathsep + os.defpath)
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'unix:path=' + str(tmp_path / 'no-host-bus'))
    image = tmp_path / 'Magnolie $ "quoted" 100%.AppImage'
    calls = tmp_path / 'application.log'
    image.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> ' + shlex.quote(str(calls)) + '\n')
    image.chmod(0o700)
    guard = Path(lifecycle.ensure_installed(str(image)))
    marker = lifecycle.marker(str(image))
    files = [config / 'systemd/user' / name for name in ('magnolie-erinnerung.service', 'magnolie-erinnerung.timer')]
    files += [config / 'autostart' / name for name in ('magnolie-erinnerung.desktop', 'magnolie-organizer-tray.desktop',
              'io.gitlab.maik3531.MagnolieOrganizer.Background.desktop')]
    for file in files:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(marker + 'synthetic owned registration\n')
    return image, guard, files, config, data, calls, log


@pytest.mark.parametrize('removal', ['delete', 'move'])
def test_real_guard_executes_original_and_removes_only_bound_integration_when_image_disappears(portable, removal):
    image, guard, files, config, data, calls, log = portable
    profile = data / 'personal.json'; profile.write_text('untouched profile')
    subprocess.run([str(guard), '--wecker', 'literal $ % " data'], check=True, timeout=10)
    assert calls.read_text().splitlines() == ['--wecker', 'literal $ % " data']
    moved = image.with_suffix('.moved')
    if removal == 'delete': image.unlink()
    else: image.rename(moved)
    subprocess.run([str(guard), '--check'], check=True, timeout=10)
    assert all(not file.exists() for file in files)
    assert not guard.exists()
    assert not list((config / 'systemd/user').glob('magnolie-appimage-*'))
    assert profile.read_text() == 'untouched profile'
    assert '--user disable --now magnolie-erinnerung.timer' in log.read_text()
    assert '--user reset-failed magnolie-erinnerung.service' in log.read_text()
    if removal == 'move': assert moved.exists()


def test_old_guard_preserves_replacement_registrations_and_symlinks(portable):
    image, guard, files, _, _, _, _ = portable
    replacement = image.with_name('replacement.AppImage'); replacement.write_text('present')
    current_marker = lifecycle.marker(str(replacement))
    for file in files[:2]: file.write_text(current_marker + 'new installation\n')
    protected = image.with_name('protected.desktop'); protected.write_text(lifecycle.marker(str(image)))
    files[2].unlink(); files[2].symlink_to(protected)
    image.unlink()
    subprocess.run([str(guard), '--check'], check=True, timeout=10)
    assert all(file.read_text() == current_marker + 'new installation\n' for file in files[:2])
    assert files[2].is_symlink() and protected.exists()
    assert not any(file.exists() for file in files[3:])


def test_portable_watch_units_parse_with_real_systemd_analyzer(portable):
    if not shutil.which('systemd-analyze'):
        pytest.skip('systemd unit parser unavailable')
    _, _, _, config, _, _, _ = portable
    units = sorted((config / 'systemd/user').glob('magnolie-appimage-*'))
    result = subprocess.run(['systemd-analyze', '--user', 'verify', *(str(path) for path in units)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_legacy_missing_appimage_service_and_timer_are_disabled_together(portable):
    image, _, files, config, data, _, _ = portable
    service, timer = files[:2]
    legacy = image.with_name('Magnolie-Organizer-2.0.17-x86_64.AppImage')
    service.write_text('[Unit]\nDescription=Magnolie Organizer reminders\n[Service]\nExecStart="' + str(legacy) + '" --erinnerung\n')
    timer.write_text('[Timer]\nUnit=magnolie-erinnerung.service\n')
    files[2].write_text('[Desktop Entry]\nExec="' + str(legacy) + '" --wecker\n')
    original = data / 'notes.json'; original.write_text('untouched')
    calls = []
    assert lifecycle.cleanup_legacy(runner=lambda args: calls.append(args) or 0, config=config)
    assert calls[0][-2:] == ['magnolie-erinnerung.timer', 'magnolie-erinnerung.service']
    assert not service.exists() and not timer.exists() and not files[2].exists()
    assert original.read_text() == 'untouched'
    assert calls[-1][-3:] == ['reset-failed', 'magnolie-erinnerung.timer', 'magnolie-erinnerung.service']


def test_legacy_existing_image_and_non_appimage_registration_are_preserved(portable):
    image, _, files, config, _, _, _ = portable
    for program in (image, Path('/missing/normal-program')):
        escaped = str(program).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"').replace('$', '$$')
        files[0].write_text('[Unit]\nDescription=Magnolie\n[Service]\nExecStart="' + escaped + '" --erinnerung\n')
        assert not lifecycle.cleanup_legacy(runner=lambda _: pytest.fail('Unrelated manager mutation'), config=config)
        assert files[0].exists()
