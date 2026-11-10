"""Explicit native activation setup, never startup/capture or package installation.

The privileged invocation has no renderer-controlled arguments, file paths or
imports. Isolated SYSTEM Python executes the fixed standard-library payload;
normal polkit authorization applies (no custom permissive policy). This also
works for an AppImage without executing its user-writable files as root.
"""
from pathlib import Path
import os
import subprocess
import time


ROOT_SETUP = r'''
import math, os, secrets, signal, stat, subprocess, sys, time

HEADER = b'# Managed by Magnolie Organizer: explicit phone webcam activation.\n'
LOAD = HEADER + b'v4l2loopback\n'
OPTIONS = HEADER + b'options v4l2loopback devices=1 exclusive_caps=1 card_label=Magnolie-Phone\n'

def remaining(value, now):
    deadline = float(value)
    seconds = deadline - now
    if not math.isfinite(deadline) or not 0 < seconds <= 110: raise RuntimeError('setup_deadline_expired')
    return seconds

def trusted_tool(names):
    for name in names:
        path = os.path.realpath(name)
        try: info = os.stat(path)
        except FileNotFoundError: continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022 and os.access(path, os.X_OK):
            return path
    raise RuntimeError('setup_tool_missing')

def directory(parent, name):
    try: os.mkdir(name, 0o755, dir_fd=parent)
    except FileExistsError: pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022: raise RuntimeError('unsafe_setup_directory')
        return fd
    except BaseException:
        os.close(fd); raise

def existing(fd, name, wanted):
    try: item = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
    except FileNotFoundError: return False
    try:
        info = os.fstat(item)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022 or
                info.st_nlink != 1 or info.st_size != len(wanted) or os.read(item, len(wanted) + 1) != wanted):
            raise RuntimeError('foreign_setup_configuration')
        return True
    finally: os.close(item)

def enable(root='/', run=subprocess.run, tool=None):
    # root/run/tool are private test adapters, never CLI arguments or IPC fields.
    base = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    opened = [base]; created = []
    try:
        info = os.fstat(base)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022: raise RuntimeError('unsafe_setup_directory')
        etc = directory(base, 'etc'); opened.append(etc)
        load = directory(etc, 'modules-load.d'); opened.append(load)
        options = directory(etc, 'modprobe.d'); opened.append(options)
        filename = 'magnolie-phone-webcam.conf'
        have_load = existing(load, filename, LOAD)
        have_options = existing(options, filename, OPTIONS)
        modprobe = tool or trusted_tool(('/usr/sbin/modprobe', '/sbin/modprobe'))
        environment = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
        configured = run([modprobe, '--showconfig'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=10, check=True, env=environment).stdout
        if not isinstance(configured, bytes) or len(configured) > 4 * 1024 * 1024: raise RuntimeError('setup_configuration_too_large')
        configured_options = any(line.split()[:2] == [b'options', b'v4l2loopback'] for line in configured.splitlines())
        # Never override another application's/user's module parameters.
        already_loaded = os.path.isdir(os.path.join(root, 'sys/module/v4l2loopback'))
        arguments = [] if configured_options or already_loaded else ['devices=1', 'exclusive_caps=1', 'card_label=Magnolie-Phone']
        run([modprobe, 'v4l2loopback', *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=30, check=True, env=environment)
        for parent, data, present in ((load, LOAD, have_load), (options, OPTIONS, have_options)):
            if present or parent == options and (configured_options or already_loaded): continue
            temporary = '.magnolie-webcam-' + secrets.token_hex(16)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(data); output.flush(); os.fchmod(output.fileno(), 0o644); os.fsync(output.fileno())
                    identity = os.fstat(output.fileno()).st_ino
                os.link(temporary, filename, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                created.append((parent, filename, identity, data))
            finally: os.unlink(temporary, dir_fd=parent)
            os.fsync(parent)
        # Re-read our own exact bytes, including concurrent changes, before success.
        if not existing(load, filename, LOAD): raise RuntimeError('setup_configuration_changed')
        if have_options or not (configured_options or already_loaded):
            if not existing(options, filename, OPTIONS): raise RuntimeError('setup_configuration_changed')
    except BaseException:
        for parent, name, identity, data in reversed(created):
            try:
                if os.stat(name, dir_fd=parent, follow_symlinks=False).st_ino == identity and existing(parent, name, data):
                    os.unlink(name, dir_fd=parent); os.fsync(parent)
            except (OSError, RuntimeError): pass
        raise
    finally:
        for fd in reversed(opened): os.close(fd)

if __name__ == '__main__':
    if os.geteuid() != 0 or len(sys.argv) != 2: sys.exit(77)
    try:
        # Share the ORIGINAL caller deadline across the administrator prompt.
        # A late authorization cannot create a fresh privileged IO interval.
        seconds = remaining(sys.argv[1], time.monotonic())
        def expired(signum, frame): raise TimeoutError('setup_deadline_expired')
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        enable()
    except Exception: sys.exit(70)
'''


def system_tool(names):
    for name in names:
        path = Path(name).resolve()
        try: info = path.stat()
        except FileNotFoundError: continue
        if path.is_file() and info.st_uid == 0 and not info.st_mode & 0o022 and os.access(path, os.X_OK):
            return str(path)
    return None


def prepare_driver(current, *, run=subprocess.run, tool=system_tool, loaded=lambda: Path('/sys/module/v4l2loopback').is_dir(), clock=time.monotonic):
    def require_current():
        if current() is False: raise PermissionError('webcam_original_choice_changed')
    require_current()
    modinfo = tool(('/usr/sbin/modinfo', '/sbin/modinfo'))
    if modinfo is None: return 'driver_probe_unavailable'
    try:
        result = run([modinfo, '-F', 'filename', 'v4l2loopback'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError): return 'driver_probe_unavailable'
    require_current()
    if result.returncode: return 'driver_not_installed'
    python = tool(('/usr/bin/python3',))
    pkexec = tool(('/usr/bin/pkexec', '/bin/pkexec')) if os.geteuid() != 0 else None
    if python is None or os.geteuid() != 0 and pkexec is None: return 'driver_authentication_unavailable'
    deadline = format(clock() + 110, '.6f')
    command = ([pkexec, '--disable-internal-agent'] if pkexec else []) + [python, '-I', '-c', ROOT_SETUP, deadline]
    require_current()
    try:
        result = run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=120, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
    except (OSError, subprocess.SubprocessError): return 'driver_setup_failed'
    require_current()
    if result.returncode in (126, 127): return 'driver_authentication_cancelled'
    if result.returncode or not loaded(): return 'driver_setup_failed'
    return ''
