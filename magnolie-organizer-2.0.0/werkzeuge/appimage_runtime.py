"""Relocate WebKit's absolute sandbox helper paths in a private runtime copy."""
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys

from appimage_graphics import select


def sandbox_helper(env, bundled):
    policy = Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns')
    if not policy.exists() or policy.read_text().strip() != '1':
        return bundled
    # Ubuntu authorizes the distro executable's AppArmor path, not a relocated
    # copy. Verify it in the actual library environment; never relax the policy.
    native = Path('/usr/bin/bwrap')
    try:
        subprocess.run([str(native), '--unshare-user', '--unshare-pid',
                        '--ro-bind', '/', '/', '--proc', '/proc', '/bin/true'],
                       env=env, check=True, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError('The system bubblewrap cannot provide the required AppArmor-approved sandbox') from error
    return native


def relocate(data, old, new):
    old, new = os.fsencode(old), os.fsencode(new)
    if len(new) > len(old) or old + b"\0" not in data:
        raise RuntimeError(f"Unsupported WebKit helper path: {os.fsdecode(old)}")
    return data.replace(old + b"\0", new.ljust(len(old), b"\0") + b"\0")


def launch(appdir, args):
    # Informational CLI modes never create a WebView. Do not load Mesa/WebKit
    # twice or copy its library before printing help/version on headless hosts.
    if args and args[0] in {str(appdir / "usr/bin/magnolie-organizer"),
                            str(appdir / "usr/lib/magnolie-handbuch/magnolie-handbuch")} and any(
            arg in {"--help", "--hilfe", "-h", "--version", "-V"} for arg in args[1:]):
        os.execv(str(appdir / "usr/bin/python3"), [str(appdir / "usr/bin/python3"), *args])
    env = dict(os.environ)
    env["LD_PRELOAD"] = select(appdir)
    env["WEBKIT_FORCE_SANDBOX"] = "1"
    env.pop("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS", None)
    # The shortest compiled path is /usr/bin/bwrap (14 bytes). Exclusive mkdir
    # and 0700 protect the randomly named directory, including against symlinks.
    for attempt in range(128):
        runtime = Path("/tmp") / secrets.token_hex(3)
        try:
            runtime.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("Cannot allocate private WebKit runtime")
    try:
        # The proxy's namespace binds the helper file, not the application's
        # usr/bin. A symlink works accidentally under /tmp but breaks elsewhere.
        shutil.copy2(appdir / "usr/bin/bwrap", runtime / "b")
        shutil.copy2(appdir / "usr/bin/xdg-dbus-proxy", runtime / "p")
        bwrap = sandbox_helper(env, runtime / 'b')
        (runtime / "w").symlink_to(appdir / "usr/lib/webkit2gtk-4.1", target_is_directory=True)
        library = appdir / "usr/lib/libwebkit2gtk-4.1.so.0"
        data = library.read_bytes()
        for old, new in (("/proc/self/cwd//./usr/lib/webkit2gtk-4.1", runtime / "w"),
                         ("/usr/bin/bwrap", bwrap),
                         ("/usr/bin/xdg-dbus-proxy", runtime / "p")):
            data = relocate(data, old, new)
        (runtime / library.name).write_bytes(data)
        # WebKit read-only binds LD_LIBRARY_PATH into its sandbox. Include only
        # the packaged data directory so its fontconfig/fonts remain readable.
        env["LD_LIBRARY_PATH"] = f"{runtime}:{appdir}/usr/share:" + env["LD_LIBRARY_PATH"]
        child = subprocess.Popen([str(appdir / "usr/bin/python3"), *args], env=env)
        def forward(signum, frame):
            child.send_signal(signum)
        previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        try:
            return child.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    finally:
        shutil.rmtree(runtime)


if __name__ == "__main__":
    try:
        code = launch(Path(sys.argv[1]).resolve(), sys.argv[2:])
        sys.exit(code if code >= 0 else 128 - code)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Magnolie AppImage runtime: {error}", file=sys.stderr)
        sys.exit(1)
