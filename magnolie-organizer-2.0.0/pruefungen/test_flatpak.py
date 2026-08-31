#!/usr/bin/env python3
"""Prueft Flatpak-Manifest und gebautes Einzeldateibuendel."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.gitlab.maik3531.MagnolieOrganizer"
manifest = json.loads((ROOT / "flatpak" / f"{APP_ID}.json").read_text(encoding="utf-8"))

assert manifest["app-id"] == APP_ID
assert manifest["runtime"] == "org.gnome.Platform"
assert manifest["runtime-version"] == "49"
assert manifest["sdk"] == "org.gnome.Sdk"
assert manifest["command"] == "magnolie-organizer"
permissions = set(manifest["finish-args"])
for required in ("--share=network", "--socket=wayland", "--socket=fallback-x11",
                 "--socket=pulseaudio"):
    assert required in permissions
assert not any(value.startswith("--filesystem=home") or value == "--device=dri"
               for value in permissions)
assert "0" * 64 not in json.dumps(manifest)
builder = (ROOT / "werkzeuge/flatpak_bauen.sh").read_text(encoding="utf-8")
assert 'if contributor_hash:' in builder
assert '/app/share/magnolie-organizer/build-config.json' in builder
commands = "\n".join(manifest["modules"][-1]["build-commands"])
assert "web/kaffee-qr.mga" not in commands  # the complete reviewed web tree is copied
assert "cp -a web/. /app/share/magnolie-organizer/web/" in commands
assert "bin/magnolie_asset.py" in commands
assert "PROTECTED-ASSETS-LICENSE.txt /app/share/doc/magnolie-organizer/" in commands
assert not (ROOT / "web" / "kaffee-qr.png").exists()
assert (ROOT / "web" / "kaffee-qr.mga").read_bytes().startswith(b"MGA1")

dependencies = json.loads(
    (ROOT / "flatpak/python3-dependencies.json").read_text(encoding="utf-8"))
dependency_text = json.dumps(dependencies)
for package in ("cryptography", "pyOpenSSL", "zeroconf", "ifaddr", "pyenchant", "qrcode"):
    assert package.lower() in dependency_text.lower()
for source in dependencies["modules"]:
    for item in source.get("sources", []):
        assert item.get("sha256"), item
        assert item.get("url", "").startswith("https://files.pythonhosted.org/")

def bundle_commit(bundle):
    bundle = Path(bundle).resolve()
    assert bundle.is_file() and bundle.stat().st_size > 0
    with tempfile.TemporaryDirectory(prefix="magnolie-flatpak-test-") as work:
        repo = Path(work) / "repo"
        ostree = ["flatpak", "run", "--user", f"--filesystem={work}",
                  "--command=ostree", "org.flatpak.Builder"]
        subprocess.run([*ostree, "init", f"--repo={repo}", "--mode=archive"], check=True)
        subprocess.run(["flatpak", "build-import-bundle", str(repo), str(bundle)], check=True)
        refs = subprocess.check_output(
            [*ostree, f"--repo={repo}", "refs"], text=True).splitlines()
        ref = f"app/{APP_ID}/x86_64/stable"
        assert ref in refs
        return subprocess.check_output(
            [*ostree, f"--repo={repo}", "rev-parse", ref], text=True).strip()


if len(sys.argv) > 1:
    commit = bundle_commit(sys.argv[1])
    if len(sys.argv) > 2:
        assert bundle_commit(sys.argv[2]) == commit, "Flatpak-Nutzlast ist nicht reproduzierbar"

print("FLATPAK-PRUEFUNG BESTANDEN")
