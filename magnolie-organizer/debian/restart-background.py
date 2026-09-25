#!/usr/bin/python3
"""Renew already running installed user daemons after a Debian configure.

Never enable a service, kill a GUI, force-kill an owner, or run user code as root.
The daemon itself retains its settings, pairings and exclusive IPC lease.
"""
import os
from pathlib import Path
import pwd
import select
import signal
import subprocess
import sys
import time

ENTRY = "/usr/bin/magnolie-organizer"
ENVIRONMENT = {"XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
               "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY",
               "XAUTHORITY", "LANG", "LANGUAGE", "LC_ALL"}


def daemon_arguments(arguments):
    return (len(arguments) >= 3 and arguments[1] == ENTRY
            and arguments[2] in ("--hintergrunddienst", "--background-service", "-b"))


def environment(raw, account):
    result = dict(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name,
                  PATH="/usr/bin:/bin", PYTHONNOUSERSITE="1")
    for item in raw.split(b"\0"):
        key, sep, value = item.partition(b"=")
        if sep and key.decode("utf-8", "replace") in ENVIRONMENT:
            result[key.decode()] = os.fsdecode(value)
    result.setdefault("XDG_RUNTIME_DIR", f"/run/user/{account.pw_uid}")
    result.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=" + result["XDG_RUNTIME_DIR"] + "/bus")
    return result


def exited(fd, timeout=0):
    return bool(select.select([fd], [], [], timeout)[0])


def restart_owned(fd, env, spawn=subprocess.Popen, timeout=30, runner=subprocess.run):
    if exited(fd):
        return True  # The previous owner already stopped; do not re-enable it.
    signal.pidfd_send_signal(fd, signal.SIGTERM)
    if not exited(fd, timeout):
        return False  # No SIGKILL and no competing transport owner.
    command = ["/usr/bin/python3", ENTRY, "--hintergrunddienst"]
    if env.get("DBUS_SESSION_BUS_ADDRESS") and Path("/usr/bin/systemd-run").is_file():
        # A detached child could still be killed with the installer's cgroup.
        # Let the user's manager own the replacement beyond package configure.
        result = runner(["/usr/bin/systemd-run", "--user", "--collect", "--quiet",
            "--unit=magnolie-background-upgrade-%d" % os.getpid(), "--property=Type=exec",
            *["--setenv=" + key + "=" + value for key, value in sorted(env.items())], *command],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=15)
        return result.returncode == 0
    process = spawn(command, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    # A disabled setting or another GUI-started owner may legitimately exit 0.
    time.sleep(.2)
    return process.poll() in (None, 0)


def candidates():
    entry = os.stat(ENTRY)
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal():
            continue
        fd = None
        try:
            fd = os.pidfd_open(int(directory.name))
            arguments = [os.fsdecode(part) for part in (directory / "cmdline").read_bytes().split(b"\0") if part]
            uid = directory.stat().st_uid
            if not uid or not daemon_arguments(arguments) or exited(fd):
                continue
            # A Flatpak/container may use the same pathname in another root.
            visible = (directory / "root" / ENTRY.lstrip("/")).stat()
            if (visible.st_dev, visible.st_ino) != (entry.st_dev, entry.st_ino):
                continue
            account = pwd.getpwuid(uid)
            env = environment((directory / "environ").read_bytes(), account)
            if exited(fd):
                continue
            yield fd, account, env
        except (OSError, KeyError):
            continue  # Process disappeared or is not an accessible user session.
        finally:
            if fd is not None:
                os.close(fd)


def main():
    if os.geteuid() != 0:
        return 1
    failed = False
    # Snapshot descriptors before restarting: never rediscover our replacements.
    owners = [(os.dup(fd), account, env) for fd, account, env in candidates()]
    for fd, account, env in owners:
        child = os.fork()
        if child == 0:
            try:
                os.initgroups(account.pw_name, account.pw_gid)
                os.setgid(account.pw_gid)
                os.setuid(account.pw_uid)
                os.chdir("/")
                os._exit(0 if restart_owned(fd, env) else 1)
            except Exception:
                os._exit(1)
        _, status = os.waitpid(child, 0)
        os.close(fd)
        if status:
            failed = True
            print("Magnolie background service restart failed for uid %d." % account.pw_uid, file=sys.stderr)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
