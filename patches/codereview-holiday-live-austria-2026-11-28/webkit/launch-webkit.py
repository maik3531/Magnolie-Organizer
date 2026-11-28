#!/usr/bin/env python3
"""Run an owned WebKit probe with locally extracted dependencies in a mount namespace."""
from pathlib import Path
import json
import os
import subprocess
import sys

root = Path(__file__).resolve().parent
packages = root / "root"
host_lib = Path("/usr/lib/x86_64-linux-gnu")
saved_lib = root / "host-usr-lib-alias"
saved_lib.mkdir(exist_ok=True)
merged_lib = root / "merged-machine-libs"
merged_lib.mkdir(exist_ok=True)
namespace_original = Path("/usr/lib/magnolie-validation-original-machine-libs")
namespace_dependencies = Path("/usr/lib/magnolie-validation-webkit-dependencies")
for original in sorted(host_lib.iterdir()):
    link = merged_lib / original.name
    if not link.is_symlink():
        link.symlink_to(namespace_original / original.name)
(merged_lib / "webkit2gtk-4.1").symlink_to(namespace_dependencies / "webkit2gtk-4.1") if not (merged_lib / "webkit2gtk-4.1").is_symlink() else None
runtime = root / "runtime"
runtime.mkdir(mode=0o700, exist_ok=True)
probe = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "smoke.py"
args = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user",
        "--ro-bind", "/", "/", "--dev", "/dev", "--bind", str(root), str(root),
        "--tmpfs", "/usr/lib"]
bindings = []
for source in sorted(Path("/usr/lib").iterdir()):
    if source.name == "x86_64-linux-gnu":
        continue
    destination = Path("/usr/lib") / source.name
    if source.is_symlink():
        args += ["--symlink", os.readlink(source), str(destination)]
    else:
        args += ["--ro-bind", str(source), str(destination)]
    bindings.append(source.name)
args += ["--ro-bind", str(host_lib), str(namespace_original),
         "--ro-bind", str(packages / "usr/lib/x86_64-linux-gnu"), str(namespace_dependencies),
         "--ro-bind", str(merged_lib), str(host_lib), "--tmpfs", "/tmp",
         "--setenv", "XDG_RUNTIME_DIR", str(runtime),
         "--setenv", "PATH", str(packages / "usr/bin") + os.pathsep + os.environ["PATH"],
         "--setenv", "LD_LIBRARY_PATH", str(namespace_dependencies),
         "--setenv", "GI_TYPELIB_PATH", str(namespace_dependencies / "girepository-1.0"),
         "--setenv", "XDG_DATA_DIRS", str(packages / "usr/share") + ":/usr/local/share:/usr/share",
         "--setenv", "GSETTINGS_BACKEND", "memory",
         "/usr/bin/dbus-run-session", "--", str(packages / "usr/bin/xvfb-run"), "-a",
         "--server-args=-screen 0 1280x900x24 -nolisten tcp",
         "/usr/bin/python3", str(probe), *sys.argv[2:]]
(root / "namespace-recipe.json").write_text(json.dumps({
    "host_system_modified": False, "webkit_sandbox_disabled": False,
    "original_library_directory_preserved_via_readonly_alias": True,
    "reconstructed_directory_entries": len(bindings),
    "added_libexec_mount": "/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1",
    "network_namespace": "host; optional outer unshare-net unavailable, WebKit sandbox unchanged", "probe": str(probe),
    "writeable_owned_directory": str(root), "temporary_directory": "private tmpfs"
}, indent=2) + "\n")
completed = subprocess.run(args, text=True, capture_output=True)
(root / (probe.stem + ".stdout.log")).write_text(completed.stdout)
(root / (probe.stem + ".stderr.log")).write_text(completed.stderr)
print(completed.stdout, end="")
print(completed.stderr, end="", file=sys.stderr)
raise SystemExit(completed.returncode)
