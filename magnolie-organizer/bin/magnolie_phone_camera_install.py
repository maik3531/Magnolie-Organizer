"""Explicitly confirmed driver installation through the system's PackageKit.

No root shell, repository edits or arbitrary package names/download URLs.
PackageKit retains its normal package trust, dependency and polkit checks.
"""
import platform
import threading
import time


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


def install_driver(current, plan, *, api=package_api, timer=threading.Timer, clock=time.monotonic):
    def require_current():
        if current() is False: raise PermissionError('webcam_original_choice_changed')
    require_current()
    if plan != 'v4l2loopback-dkms':
        return 'driver_installation_unavailable'
    try: pk, gio = api()
    except (ImportError, ValueError): return 'driver_installation_unavailable'
    cancellation = gio.Cancellable()
    expired = threading.Event()
    deadline = clock() + 600
    errors = []
    def timeout():
        expired.set(); cancellation.cancel()
    watchdog = timer(600, timeout)
    watchdog.daemon = True
    def check():
        if clock() >= deadline: timeout()
        if expired.is_set(): raise TimeoutError('driver_installation_pending')
        if errors: raise errors[0]
        require_current()
    def progress(*args):
        try: check()
        except Exception as error:
            errors.append(error); cancellation.cancel()
    watchdog.start()
    try:
        # pkcon --noninteractive also disables polkit interaction. Use the native
        # client instead: no CLI questions, but normal system authorization ON.
        client = pk.Client()
        client.set_interactive(True)
        check()
        filters = sum(1 << int(value) for value in (pk.FilterEnum.NOT_INSTALLED, pk.FilterEnum.ARCH, pk.FilterEnum.NEWEST))
        result = client.resolve(filters, [plan], cancellation, progress, None)
        check()
        if result.get_error_code() is not None or result.get_exit_code() != pk.ExitEnum.SUCCESS:
            return 'driver_installation_failed'
        packages = result.get_package_array()
        if len(packages) != 1 or packages[0].get_name() != plan:
            return 'driver_installation_unavailable'
        package_id = packages[0].get_id()
        # Resolve only a fixed package from already configured repositories.
        # The daemon resolves dependencies and verifies package trust normally.
        check()
        result = client.install_packages(1 << int(pk.TransactionFlagEnum.ONLY_TRUSTED),
            [package_id], cancellation, progress, None)
        check()
        return '' if result.get_error_code() is None and result.get_exit_code() == pk.ExitEnum.SUCCESS else 'driver_installation_failed'
    except PermissionError:
        raise
    except Exception:
        # Cancellation may leave a system transaction still unwinding. Never
        # describe it as rollback or automatically retry an unconfirmed result.
        if expired.is_set(): return 'driver_installation_pending'
        if errors: raise errors[0]
        return 'driver_installation_failed'
    finally:
        watchdog.cancel()
