"""Private, bounded local crash reporting for Magnolie Linux applications."""

import datetime
import faulthandler
import fcntl
import os
import platform
import stat
import sys
import threading
import traceback


MAX_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 256 * 1024
MAX_FATAL_BYTES = 1024 * 1024
_LOCK = threading.RLock()
_configuration = None
_fatal_stream = None
_original_sys_hook = None
_original_thread_hook = None


def report_path(application):
    base = os.environ.get("XDG_STATE_HOME")
    if not base or not os.path.isabs(base):
        base = os.path.expanduser("~/.local/state")
    return os.path.join(base, application, "crash.log")


def _directory(application):
    path = report_path(application)
    base = os.path.dirname(os.path.dirname(path))
    os.makedirs(base, mode=0o700, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    base_fd = os.open(base, flags)
    try:
        try:
            os.mkdir(application, mode=0o700, dir_fd=base_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(application, flags, dir_fd=base_fd)
    finally:
        os.close(base_fd)
    os.fchmod(directory_fd, 0o700)
    return path, directory_fd


def _open_log(directory_fd):
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("crash.log", flags, 0o600, dir_fd=directory_fd)
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        os.close(descriptor)
        raise OSError("crash report is not a regular file")
    os.fchmod(descriptor, 0o600)
    return descriptor


def _fatal_name_valid(name):
    parts = name[:-4].split("-") if name.endswith(".log") else ()
    return (len(parts) == 3 and parts[0] == "fatal" and parts[1].isdigit()
            and len(parts[2]) == 16
            and all(character in "0123456789abcdef" for character in parts[2]))


def _cleanup_fatal_files(directory_fd):
    stale = []
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for name in os.listdir(directory_fd):
        if not _fatal_name_valid(name):
            continue
        descriptor = None
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise OSError("fatal report is not a regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if details.st_size == 0:
                os.unlink(name, dir_fd=directory_fd)
                continue
            stale.append((details.st_mtime_ns, name, descriptor))
            descriptor = None
        except BlockingIOError:
            pass
        except OSError:
            try:
                details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                    os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    stale.sort(reverse=True)
    for index, (_modified, name, descriptor) in enumerate(stale):
        try:
            if index == 0:
                if os.fstat(descriptor).st_size > MAX_FATAL_BYTES:
                    os.ftruncate(descriptor, MAX_FATAL_BYTES)
            else:
                os.unlink(name, dir_fd=directory_fd)
        except OSError:
            pass
        finally:
            os.close(descriptor)


def _open_fatal_log(directory_fd):
    name = "fatal-%d-%s.log" % (os.getpid(), os.urandom(8).hex())
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        os.close(descriptor)
        raise OSError("fatal report is not a regular file")
    os.fchmod(descriptor, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


def _close_fatal_stream():
    global _fatal_stream
    if _fatal_stream is None:
        return
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except BaseException:
        pass
    try:
        _fatal_stream.close()
    except BaseException:
        pass
    _fatal_stream = None


def _enable_faulthandler(application):
    global _fatal_stream
    _close_fatal_stream()
    try:
        _path, directory_fd = _directory(application)
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            _cleanup_fatal_files(directory_fd)
            descriptor = _open_fatal_log(directory_fd)
        finally:
            os.close(directory_fd)
        stream = os.fdopen(descriptor, "ab", buffering=0)
        try:
            faulthandler.enable(file=stream, all_threads=True)
        except BaseException:
            stream.close()
            raise
        _fatal_stream = stream
    except BaseException:
        _fatal_stream = None


def _rotate(directory_fd, incoming):
    try:
        details = os.stat("crash.log", dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(details.st_mode):
        raise OSError("crash report is not a regular file")
    if details.st_size + incoming <= MAX_BYTES:
        return
    try:
        os.unlink("crash.log.old", dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.replace("crash.log", "crash.log.old", src_dir_fd=directory_fd,
               dst_dir_fd=directory_fd)


def _write_all(descriptor, data):
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short crash-report write")
        view = view[written:]


def _append(application, data):
    data = data[:MAX_REPORT_BYTES]
    with _LOCK:
        _path, directory_fd = _directory(application)
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            _rotate(directory_fd, len(data))
            descriptor = _open_log(directory_fd)
            try:
                _write_all(descriptor, data)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory_fd)
        if _configuration is not None and _fatal_stream is None:
            _enable_faulthandler(application)


def _traceback_lines(exception_type, exception_value, exception_traceback):
    lines = ["Traceback (most recent call last):\n"]
    for frame in traceback.extract_tb(exception_traceback):
        lines.append('  File "%s", line %d, in %s\n' % (
            frame.filename, frame.lineno, frame.name))
    module = getattr(exception_type, "__module__", "builtins")
    name = getattr(exception_type, "__qualname__", "Exception")
    lines.append("Exception: %s.%s\n" % (module, name))
    return lines


def write_exception(application, version, component, exception_type,
                    exception_value, exception_traceback):
    """Write sanitized exception metadata; failure is deliberately invisible."""
    try:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds")
        machine = platform.machine() or "unknown"
        release = platform.release() or "unknown"
        lines = [
            "\n=== Magnolie crash report ===\n",
            "Timestamp: %s\n" % timestamp,
            "Version: %s\n" % version,
            "Platform: %s %s %s\n" % (sys.platform, release, machine),
            "Component: %s\n" % component,
            "Privacy: no runtime data is collected; traceback paths may reveal user or directory names.\n",
        ]
        lines.extend(_traceback_lines(exception_type, exception_value,
                                      exception_traceback))
        _append(application, "".join(lines).encode("utf-8", "replace"))
    except BaseException:
        pass


def install(application, version, component):
    """Install chaining exception hooks and best-effort fatal-signal tracing."""
    global _configuration, _original_sys_hook, _original_thread_hook
    with _LOCK:
        if _configuration is not None:
            return report_path(application)
        _configuration = (application, str(version), str(component))
        _original_sys_hook = sys.excepthook
        _original_thread_hook = getattr(threading, "excepthook", None)

        def sys_hook(exception_type, exception_value, exception_traceback):
            try:
                if not issubclass(exception_type, (KeyboardInterrupt, SystemExit)):
                    write_exception(*_configuration, exception_type, exception_value,
                                    exception_traceback)
            finally:
                _original_sys_hook(exception_type, exception_value,
                                   exception_traceback)

        def thread_hook(arguments):
            try:
                if not issubclass(arguments.exc_type, (KeyboardInterrupt, SystemExit)):
                    write_exception(*_configuration, arguments.exc_type,
                                    arguments.exc_value, arguments.exc_traceback)
            finally:
                if _original_thread_hook is not None:
                    _original_thread_hook(arguments)

        sys.excepthook = sys_hook
        if _original_thread_hook is not None:
            threading.excepthook = thread_hook
        try:
            _path, directory_fd = _directory(application)
            try:
                fcntl.flock(directory_fd, fcntl.LOCK_EX)
                _rotate(directory_fd, 0)
            finally:
                os.close(directory_fd)
        except BaseException:
            pass
        _enable_faulthandler(application)
    return report_path(application)


def _reset_for_tests():
    global _configuration, _original_sys_hook, _original_thread_hook
    with _LOCK:
        _close_fatal_stream()
        if _original_sys_hook is not None:
            sys.excepthook = _original_sys_hook
        if _original_thread_hook is not None:
            threading.excepthook = _original_thread_hook
        _configuration = None
        _original_sys_hook = None
        _original_thread_hook = None
