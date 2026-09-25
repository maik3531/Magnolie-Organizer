"""Upgrade hook with real inert processes; never stop the user's application."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("background_upgrade", ROOT / "debian/restart-background.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def test_only_installed_background_entry_is_selected():
    for option in ("--hintergrunddienst", "--background-service", "-b"):
        assert upgrade.daemon_arguments(["python3", upgrade.ENTRY, option, "--language", "de"])
    for command in (["python3", upgrade.ENTRY], ["python3", upgrade.ENTRY, "--wecker"],
                    ["python3", "/tmp/source/magnolie-organizer", "--hintergrunddienst"],
                    ["sh", "-c", "python3 /usr/bin/magnolie-organizer --hintergrunddienst"]):
        assert not upgrade.daemon_arguments(command)


def test_restart_retains_profile_and_session_but_not_privileged_environment():
    account = SimpleNamespace(pw_name="fixture", pw_dir="/home/fixture", pw_uid=1234)
    env = upgrade.environment(b"HOME=/root\0XDG_DATA_HOME=/profile/data\0XDG_CONFIG_HOME=/profile/config\0"
        b"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1234/bus\0PYTHONPATH=/untrusted\0LD_PRELOAD=/untrusted\0", account)
    assert env["HOME"] == "/home/fixture"
    assert env["XDG_DATA_HOME"] == "/profile/data" and env["XDG_CONFIG_HOME"] == "/profile/config"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1234/bus"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1234"
    assert not {"PYTHONPATH", "LD_PRELOAD"} & env.keys()


def test_real_old_process_flushes_before_replacement_is_started(tmp_path):
    saved = tmp_path / "flushed"
    script = "import signal,time,pathlib,sys\ndef stop(*_):\n pathlib.Path(sys.argv[1]).write_text('saved');sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nprint('ready',flush=True)\ntime.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", script, str(saved)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        fd = os.pidfd_open(child.pid)
        calls = []
        def spawn(command, **kwargs):
            assert saved.read_text() == "saved"
            assert upgrade.exited(fd)
            calls.append((command, kwargs))
            return SimpleNamespace(poll=lambda: None)
        try:
            assert upgrade.restart_owned(fd, {"HOME": str(tmp_path)}, spawn=spawn, timeout=3)
            assert len(calls) == 1 and calls[0][0] == ["/usr/bin/python3", upgrade.ENTRY, "--hintergrunddienst"]
            assert calls[0][1]["start_new_session"] and calls[0][1]["env"] == {"HOME": str(tmp_path)}
            assert upgrade.restart_owned(fd, {}, spawn=spawn)
            assert len(calls) == 1, "An already exited owner must not trigger another start"
        finally:
            os.close(fd)
    finally:
        if child.poll() is None: child.kill()
        child.wait(timeout=3)


def test_noncooperative_owner_is_not_force_killed_or_replaced():
    script = "import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nprint('ready',flush=True)\ntime.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        fd = os.pidfd_open(child.pid)
        try:
            def forbidden(*args, **kwargs):
                raise AssertionError("A live owner must never be replaced")
            assert not upgrade.restart_owned(fd, {}, spawn=forbidden, timeout=.05)
            assert child.poll() is None
        finally:
            os.close(fd)
    finally:
        child.kill(); child.wait(timeout=3)


def test_desktop_restart_is_owned_by_user_manager_not_installer_cgroup(monkeypatch):
    observations = iter([False, True])
    monkeypatch.setattr(upgrade, "exited", lambda *args: next(observations))
    monkeypatch.setattr(upgrade.signal, "pidfd_send_signal", lambda *args: None)
    monkeypatch.setattr(upgrade.Path, "is_file", lambda path: True)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    def forbidden(*args, **kwargs):
        raise AssertionError("Desktop daemon must not remain in installer cgroup")
    env = {"HOME": "/fixture", "XDG_DATA_HOME": "/fixture/data",
           "DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture/bus"}
    assert upgrade.restart_owned(99, env, spawn=forbidden, runner=run)
    assert calls[0][0][:4] == ["/usr/bin/systemd-run", "--user", "--collect", "--quiet"]
    assert "--setenv=XDG_DATA_HOME=/fixture/data" in calls[0][0]
    assert calls[0][0][-3:] == ["/usr/bin/python3", upgrade.ENTRY, "--hintergrunddienst"]
    assert calls[0][1]["env"] == env


@pytest.mark.parametrize("arguments, expected", [(["configure"], False),
    (["configure", "2.0.22"], True), (["abort-upgrade", "2.0.22"], False)])
def test_real_postinst_hook_includes_same_version_reinstallation(tmp_path, arguments, expected):
    marker = tmp_path / "restarted"
    fixture = tmp_path / "restart.py"
    fixture.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('called')\n")
    hook = (ROOT / "debian/postinst").read_text().replace(
        "/usr/bin/python3 -I /usr/lib/magnolie-organizer/restart-background.py",
        sys.executable + " " + str(fixture))
    subprocess.run(["/bin/sh", "-c", hook, "postinst", *arguments], env={"PATH": str(tmp_path)}, check=True)
    assert marker.exists() == expected
