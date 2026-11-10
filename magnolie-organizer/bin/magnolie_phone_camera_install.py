"""Explicitly confirmed driver installation through the system's PackageKit.

No root shell, repository edits or arbitrary package names/download URLs.
PackageKit retains its normal package trust, dependency and polkit checks.
"""
import platform
import os
import struct
import subprocess
import time

from magnolie_phone_camera_setup import ROOT_SETUP, system_tool
from magnolie_phone_camera_install_root import ROOT_PACKAGE, ROOT_LEASE, ROOT_ENTRY

# Reuse exactly the existing fixed setup functions, not a root import of a
# user-writable helper. There is ONE native entry and no renderer substitutions.
_setup, _marker, _unused_entry = ROOT_SETUP.partition("\nif __name__ == '__main__':")
if not _marker: raise RuntimeError('invalid_fixed_webcam_setup_payload')
ROOT_INSTALL_SETUP = _setup + ROOT_PACKAGE + ROOT_LEASE + ROOT_ENTRY


def package_api():
    import gi
    gi.require_version('PackageKitGlib', '1.0')
    from gi.repository import PackageKitGlib, Gio
    return PackageKitGlib, Gio


def host_release():
    # Python 3.9 is supported by the DEB; this stdlib helper arrived in 3.10.
    reader = getattr(platform, 'freedesktop_os_release', None)
    return reader() if reader is not None else {}


def installation_plan(*, release=host_release, api=package_api):
    try:
        info = release()
    except OSError:
        return None
    family = {info.get('ID', ''), *info.get('ID_LIKE', '').split()}
    # Other distributions need their own verified kernel/package mapping.
    if not family.intersection({'debian', 'ubuntu', 'linuxmint', 'arch', 'manjaro'}):
        return None
    try:
        api()
    except (ImportError, ValueError):
        return None
    return 'v4l2loopback-dkms'


def install_driver(current, plan, *, popen=subprocess.Popen, tool=system_tool, clock=time.monotonic):
    def require_current():
        if current() is False: raise PermissionError('webcam_original_choice_changed')
    require_current()
    if plan != 'v4l2loopback-dkms':
        return 'driver_installation_unavailable'
    python = tool(('/usr/bin/python3',))
    pkexec = tool(('/usr/bin/pkexec', '/bin/pkexec')) if os.geteuid() != 0 else None
    if python is None or os.geteuid() != 0 and pkexec is None:
        return 'driver_installation_unavailable'
    deadline = clock() + 710
    command = ([pkexec, '--disable-internal-agent'] if pkexec else []) + [python, '-I', '-c', ROOT_INSTALL_SETUP, format(deadline, '.6f')]
    require_current()
    try:
        process = popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
    except OSError: return 'driver_installation_unavailable'
    revoked = False
    try:
        os.set_blocking(process.stdin.fileno(), False)
        while process.poll() is None:
            try: require_current()
            except Exception:
                revoked = True; break
            if clock() >= deadline:
                revoked = True; break
            try: os.write(process.stdin.fileno(), struct.pack('!d', clock()))
            except BlockingIOError: pass  # Never block on a pending auth dialog.
            except BrokenPipeError: break
            try: process.wait(timeout=.1)
            except subprocess.TimeoutExpired: pass
    except OSError:
        revoked = True
    finally:
        process.stdin.close()  # EOF revokes ONLY this original root operation.
        if process.poll() is None:
            if revoked and os.geteuid() != 0:
                # pkexec before approval still belongs to the original user.
                # Once root, signals are denied; the fixed lease cancels safely.
                try: process.terminate()
                except (PermissionError, ProcessLookupError): pass
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: revoked = True
    if revoked: return 'driver_installation_pending'
    try: require_current()
    except Exception: return 'driver_installation_pending'
    return {0: '', 126: 'driver_authentication_cancelled', 127: 'driver_authentication_cancelled',
        70: 'driver_setup_failed', 71: 'driver_installation_failed', 72: 'driver_installation_pending',
        73: 'driver_installation_pending', 74: 'driver_installation_unavailable'}.get(process.returncode, 'driver_installation_failed')
