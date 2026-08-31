import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
HANDBOOK = ROOT.parent / "magnolie-handbuch-stamm"
sys.path.insert(0, str(BIN))
import magnolie_crash as crash


def captured_exception(message="private exception message"):
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


def test_report_is_private_sanitized_and_has_required_shape(tmp_path):
    state = tmp_path / "state"
    secret_values = (
        "argv-secret", "environment-secret", "clipboard-secret",
        "message-secret", "settings-secret",
    )
    exception = captured_exception(secret_values[3])
    with mock.patch.dict(os.environ, {
            "XDG_STATE_HOME": str(state), "PRIVATE_VALUE": secret_values[1]}), \
         mock.patch.object(sys, "argv", ["magnolie-organizer", secret_values[0]]):
        clipboard = secret_values[2]
        settings = {"password": secret_values[4]}
        assert clipboard and settings
        crash.write_exception("magnolie-organizer", "2.0.14", "organizer", *exception)

    path = state / "magnolie-organizer" / "crash.log"
    report = path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for heading in ("Timestamp:", "Version: 2.0.14", "Platform:",
                    "Component: organizer", "Traceback (most recent call last):",
                    "Exception: builtins.RuntimeError"):
        assert heading in report
    assert "traceback paths may reveal user or directory names" in report
    for secret in secret_values:
        assert secret not in report


def test_report_rotates_once_and_refuses_symlink_targets(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(crash, "MAX_BYTES", 650)
    exception = captured_exception()
    for _unused in range(4):
        crash.write_exception("magnolie-organizer", "2.0.14", "organizer", *exception)
    path = state / "magnolie-organizer" / "crash.log"
    old = state / "magnolie-organizer" / "crash.log.old"
    assert path.is_file() and old.is_file()
    assert stat.S_IMODE(old.stat().st_mode) == 0o600
    assert path.stat().st_size <= crash.MAX_BYTES

    other = tmp_path / "must-stay-empty"
    other.write_text("", encoding="utf-8")
    path.unlink()
    path.symlink_to(other)
    crash.write_exception("magnolie-organizer", "2.0.14", "organizer", *exception)
    assert other.read_text(encoding="utf-8") == ""


def test_normal_rotation_does_not_rename_open_fatal_descriptor(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(crash, "MAX_BYTES", 650)
    saved_sys_hook = sys.excepthook
    saved_thread_hook = threading.excepthook
    try:
        crash.install("magnolie-organizer", "2.0.14", "organizer")
        stream = crash._fatal_stream
        fatal_details = os.fstat(stream.fileno())
        directory = state / "magnolie-organizer"
        fatal_paths = list(directory.glob("fatal-*.log"))
        assert len(fatal_paths) == 1
        assert fatal_paths[0].stat().st_ino == fatal_details.st_ino
        assert stat.S_IMODE(fatal_paths[0].stat().st_mode) == 0o600

        crash._append("magnolie-organizer", b"a" * 400)
        crash._append("magnolie-organizer", b"b" * 400)
        assert crash._fatal_stream is stream
        assert os.fstat(stream.fileno()).st_ino == fatal_details.st_ino

        os.write(stream.fileno(), b"fatal-descriptor-marker\n")
        assert b"fatal-descriptor-marker" in fatal_paths[0].read_bytes()
        assert b"fatal-descriptor-marker" not in (directory / "crash.log.old").read_bytes()
        assert (directory / "crash.log.old").stat().st_ino != fatal_details.st_ino
    finally:
        crash._reset_for_tests()
        sys.excepthook = saved_sys_hook
        threading.excepthook = saved_thread_hook


def test_stale_fatal_files_are_private_bounded_and_symlinks_not_followed(
        tmp_path, monkeypatch):
    state = tmp_path / "state"
    directory = state / "magnolie-organizer"
    directory.mkdir(parents=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(crash, "MAX_FATAL_BYTES", 128)
    stale_names = ("fatal-100-0000000000000001.log",
                   "fatal-101-0000000000000002.log")
    for name in stale_names:
        (directory / name).write_bytes(b"f" * 512)
    os.utime(directory / stale_names[0], (1, 1))
    os.utime(directory / stale_names[1], (2, 2))
    empty = directory / "fatal-103-0000000000000004.log"
    empty.touch()
    os.utime(empty, (3, 3))
    victim = tmp_path / "victim"
    victim.write_bytes(b"untouched")
    symlink = directory / "fatal-102-0000000000000003.log"
    symlink.symlink_to(victim)

    try:
        crash._enable_faulthandler("magnolie-organizer")
        fatal_files = [path for path in directory.glob("fatal-*.log")
                       if not path.is_symlink()]
        assert len(fatal_files) == 2  # one bounded stale file and this process
        active_inode = os.fstat(crash._fatal_stream.fileno()).st_ino
        stale = [path for path in fatal_files if path.stat().st_ino != active_inode]
        assert len(stale) == 1 and stale[0].stat().st_size == 128
        assert stale[0].name == stale_names[1]
        assert stat.S_IMODE(stale[0].stat().st_mode) == 0o600
        assert not symlink.exists() and not symlink.is_symlink()
        assert victim.read_bytes() == b"untouched"
    finally:
        crash._reset_for_tests()


def test_hooks_chain_for_main_and_real_thread_without_masking(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    saved_sys_hook = sys.excepthook
    saved_thread_hook = threading.excepthook
    delegated = []
    sys.excepthook = lambda *arguments: delegated.append(("main", arguments[0]))
    threading.excepthook = lambda arguments: delegated.append(
        ("thread", arguments.exc_type))
    try:
        crash.install("magnolie-organizer", "2.0.14", "organizer")
        exception = captured_exception()
        sys.excepthook(*exception)

        worker = threading.Thread(target=lambda: (_ for _ in ()).throw(ValueError(
            "thread-private-message")))
        worker.start()
        worker.join()

        before = (state / "magnolie-organizer" / "crash.log").stat().st_size
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert (state / "magnolie-organizer" / "crash.log").stat().st_size == before
        assert delegated == [("main", RuntimeError), ("thread", ValueError),
                             ("main", KeyboardInterrupt)]
        report = (state / "magnolie-organizer" / "crash.log").read_text(
            encoding="utf-8")
        assert report.count("=== Magnolie crash report ===") == 2
        assert "thread-private-message" not in report
    finally:
        crash._reset_for_tests()
        sys.excepthook = saved_sys_hook
        threading.excepthook = saved_thread_hook


def _package_relationship(control, field, package):
    value = re.search(rf"^{field}:\s*(.+(?:\n .+)*)", control, re.MULTILINE)
    assert value, f"{field} fehlt"
    for relation in value.group(1).replace("\n", " ").split(","):
        match = re.fullmatch(rf"\s*{re.escape(package)}\s*\((<<|<=|=|>=|>>)\s*([^\s)]+)\)\s*", relation)
        if match:
            return match.groups()
    pytest.fail(f"{field} enthaelt keine versionierte Beziehung zu {package}")


def test_reporter_copy_and_organizer_package_manifests():
    organizer_debian = (ROOT / "debian" / "install").read_text()
    assert "bin/magnolie_crash.py                  usr/bin" in organizer_debian
    control = (ROOT / "debian" / "control").read_text()
    replaces = _package_relationship(control, "Replaces", "magnolie-handbuch")
    breaks = _package_relationship(control, "Breaks", "magnolie-handbuch")
    current_version = subprocess.check_output([
        "dpkg-parsechangelog", f"-l{ROOT / 'debian' / 'changelog'}", "-SVersion"
    ], text=True).strip()
    assert replaces == breaks == ("<<", "2.0.10")
    assert subprocess.run([
        "dpkg", "--compare-versions", current_version, "gt", "2.0.10"
    ]).returncode == 0
    assert "magnolie_crash.py" in (ROOT / "rpm" / "magnolie-organizer.spec").read_text()
    assert "magnolie_crash.py" in (ROOT / "werkzeuge" / "appimage_bauen.sh").read_text()
    assert "magnolie_crash.py" in (ROOT / "flatpak" /
        "io.gitlab.maik3531.MagnolieOrganizer.json").read_text()
    with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/magnolie-state"}):
        assert crash.report_path("magnolie-organizer") == \
            "/tmp/magnolie-state/magnolie-organizer/crash.log"
        assert crash.report_path("magnolie-handbuch") == \
            "/tmp/magnolie-state/magnolie-handbuch/crash.log"


def test_handbook_reporter_and_package_manifests(tmp_path):
    if not HANDBOOK.exists():
        if os.environ.get("MAGNOLIE_VOLLPRUEFUNG") == "1":
            pytest.fail("magnolie-handbuch-stamm fehlt bei verlangter Vollpruefung")
        pytest.skip("magnolie-handbuch-stamm liegt nicht daneben (Distributionsbau)")

    handbook_reporter = HANDBOOK / "bin" / "magnolie_crash.py"
    assert handbook_reporter.read_bytes() == (BIN / "magnolie_crash.py").read_bytes()
    handbook_debian = (HANDBOOK / "debian" / "install").read_text()
    assert "bin/magnolie_crash.py                 usr/lib/magnolie-handbuch" in handbook_debian
    assert "bin/magnolie_asset.py                 usr/lib/magnolie-handbuch" in handbook_debian
    handbook_rpm = (HANDBOOK / "rpm" / "magnolie-handbuch.spec").read_text()
    assert "%dir %{_prefix}/lib/%{name}" in handbook_rpm
    assert "%{_prefix}/lib/%{name}/magnolie_crash.py" in handbook_rpm
    assert "%{_prefix}/lib/%{name}/magnolie_asset.py" in handbook_rpm
    assert "%{_bindir}/magnolie_crash.py" not in handbook_rpm

    handbook_version = subprocess.check_output([
        "dpkg-parsechangelog", f"-l{HANDBOOK / 'debian' / 'changelog'}", "-SVersion"
    ], text=True).strip()

    installation = tmp_path / "installation"
    launcher = installation / "usr" / "bin" / "magnolie-handbuch"
    reporter_directory = installation / "usr" / "lib" / "magnolie-handbuch"
    reporter_directory.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    shutil.copy2(HANDBOOK / "bin" / "magnolie-handbuch", launcher)
    shutil.copy2(handbook_reporter, reporter_directory / "magnolie_crash.py")
    shutil.copy2(HANDBOOK / "bin" / "magnolie_asset.py",
                 reporter_directory / "magnolie_asset.py")
    link = tmp_path / "bin" / "handbuch"
    link.parent.mkdir()
    link.symlink_to(launcher)
    result = subprocess.run([link, "--version"], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == handbook_version

    (reporter_directory / "magnolie_crash.py").unlink()
    result = subprocess.run([link, "--version"], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr

    (reporter_directory / "magnolie_crash.py").write_text(
        "import absichtlich_fehlende_reporter_abhaengigkeit\n", encoding="utf-8")
    result = subprocess.run([link, "--version"], text=True, capture_output=True)
    assert result.returncode != 0
    assert "absichtlich_fehlende_reporter_abhaengigkeit" in result.stderr
