"""Select a load-checked host graphics closure without discarding Jammy libraries."""
import os
from pathlib import Path
import re
import subprocess
import sys

LOADER = "/lib64/ld-linux-x86-64.so.2"
ROOTS = {"libEGL_mesa.so.0", "libGLX_mesa.so.0", "libgbm.so.1"}


def loader_paths(text):
    if "not found" in text:
        raise RuntimeError("Incomplete host graphics dependency closure")
    return dict(re.findall(r"^\s*(\S+) => (/\S+) \(0x[0-9a-f]+\)", text, re.M))


def select(appdir):
    bundled = appdir / "usr/lib"
    clean = {key: value for key, value in os.environ.items()
             if not key.startswith(("LD_", "PYTHON"))}
    clean["LC_ALL"] = "C"
    ldconfig = next((p for p in ("/sbin/ldconfig", "/usr/sbin/ldconfig")
                     if Path(p).is_file()), None)
    if ldconfig is None:
        raise RuntimeError("Host ldconfig is required to resolve graphics libraries")
    cache = subprocess.check_output([ldconfig, "-p"], env=clean, text=True, timeout=5)
    roots = {}
    for name, path in re.findall(r"^\s*(\S+) \([^\n]*x86-64[^\n]*\) => (/\S+)", cache, re.M):
        if name in ROOTS:
            roots.setdefault(name, Path(path).resolve())
    if not roots:
        return os.environ.get("LD_PRELOAD", "")
    drivers = set(roots.values())
    for directory in {path.parent for path in drivers}:
        drivers.update(path.resolve() for path in (directory / "dri").glob("*_dri.so"))
    checks = [str(bundled / name) for name in
              ("libwebkit2gtk-4.1.so.0", "libgtk-3.so.0", "libecal-2.0.so.1",
               "libecal-2.0.so.3", "libebook-1.2.so.20", "libebook-1.2.so.21")
              if (bundled / name).is_file()]
    checks += sorted(str(path) for path in drivers)
    probe = [str(appdir / "usr/bin/python3"), "-S", "-c",
             "import ctypes, os, sys; handles = [ctypes.CDLL(p, mode=os.RTLD_NOW) for p in sys.argv[1:]]",
             *checks]
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{bundled}/x86_64-linux-gnu:{bundled}"
    env["PYTHONHOME"] = str(appdir / "usr")
    def works(preload):
        result = subprocess.run(probe, env={**env, "LD_PRELOAD": preload},
                                capture_output=True, text=True, timeout=15)
        return result.returncode == 0, result.stderr
    inherited = env.get("LD_PRELOAD", "")
    ok, original_error = works(inherited)
    if ok:
        return inherited
    closure = {}
    for driver in sorted(drivers):
        result = subprocess.check_output([LOADER, "--list", str(driver)],
                                         env=clean, text=True, stderr=subprocess.STDOUT, timeout=5)
        for name, path in loader_paths(result).items():
            path = str(Path(path).resolve())
            if name in closure and closure[name] != path:
                raise RuntimeError(f"Conflicting host graphics dependency: {name}")
            closure[name] = path
    # Preempt only SONAME collisions with the bundle. Host libc/loader and
    # unrelated bundled GTK, fontconfig, EDS, etc. keep their normal resolution.
    replacements = [path for name, path in sorted(closure.items())
                    if (bundled / name).exists() or (bundled / "x86_64-linux-gnu" / name).exists()]
    if any(re.search(r"[\s:]", path) for path in replacements):
        raise RuntimeError("Unsafe graphics library path")
    preload = ":".join(replacements + ([inherited] if inherited else []))
    ok, error = works(preload)
    if not ok:
        raise RuntimeError("No compatible AppImage/host graphics closure:\n" + original_error + error)
    print("Magnolie: validated host graphics replacements: " + ":".join(replacements), file=sys.stderr)
    return preload


if __name__ == "__main__":
    try:
        print(select(Path(sys.argv[1]).resolve()))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Magnolie graphics runtime: {error}", file=sys.stderr)
        sys.exit(1)
