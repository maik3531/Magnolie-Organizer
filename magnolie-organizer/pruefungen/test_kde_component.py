"""Read-only component proof; set MAGNOLIE_KDE_COMPONENT to an actual build.

No VM, user session, production aggregate or publication is involved. The optional
unpack test uses a private dpkg database and never configures missing dependencies.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
import release_gate as gate
import release_sources as sources
from kde_profiles import PROFILES, artifacts


@pytest.fixture
def component():
    directory = os.environ.get("MAGNOLIE_KDE_COMPONENT")
    if not directory:
        pytest.skip("No actual KDE component supplied")
    directory = Path(directory)
    proof = json.loads((directory / "kde-2.0.18-provenance.json").read_text())
    return directory, proof


def test_component_hashes_sources_and_same_artifact_gates(component):
    directory, proof = component
    selected = {str(n): sources.source_identity(p) for n, p in sources.source_files(ROOT / "native/akonadi-helper")}
    record = {gate.LINUX + "/native/akonadi-helper/" + n: v for n, v in selected.items()}
    gate.kde_binding(directory, "2.0.18", record, gate.artifact_map(directory, artifacts("2.0.18")))
    assert proof["artifacts"] == {n: sources.digest(directory / n) for n in artifacts("2.0.18")[:-1]}
    with tarfile.open(directory / "magnolie-organizer-kde_2.0.18.tar.xz") as archive:
        members = {m.name.removeprefix("akonadi-helper/"): m for m in archive if m.isfile()}
        assert set(members) == set(selected)
        for name, member in members.items():
            assert hashlib.sha256(archive.extractfile(member).read()).hexdigest() == selected[name]["sha256"]
            assert member.mode == selected[name]["mode"]
    assert proof["reproducible"] and proof["installedLiveKde"] is False and proof["published"] is False


def test_component_payload_has_three_real_elfs_and_complete_audits(component):
    directory, proof = component
    package = directory / artifacts("2.0.18")[0]
    data = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(package)])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = {m.name.removeprefix("./"): m for m in archive if m.isfile()}
        prefix = "usr/libexec/magnolie-organizer/"
        launcher = archive.extractfile(members[prefix + "magnolie-akonadi-helper"]).read()
        assert launcher == (ROOT / "native/akonadi-helper/launcher.py").read_bytes()
        for target, profile in PROFILES.items():
            path = prefix + "kde/" + target + "/"
            binary = archive.extractfile(members[path + "backend"]).read()
            manifest = json.load(archive.extractfile(members[path + "manifest.json"]))
            audit = json.load(archive.extractfile(members[path + "build-audit.json"]))
            database = archive.extractfile(members[path + "build-packages.tsv"]).read()
            for filename in ("manifest.json", "build-audit.json", "build-packages.tsv"):
                assert members[path + filename].mode == 0o644
            assert binary.startswith(b"\x7fELF\x02") and len(binary) < 300_000
            assert hashlib.sha256(binary).hexdigest() == manifest["sha256"]
            assert manifest == audit["manifest"] == proof["profiles"][target]["manifest"]
            assert manifest["abi"] == profile["abi"]
            assert audit["shlibdeps"].startswith("shlibs:Depends=")
            assert manifest["requirements"] == "akonadi-server, " + audit["shlibdeps"].strip().removeprefix("shlibs:Depends=")
            assert hashlib.sha256(database).hexdigest() == audit["packageDatabaseSha256"]
            assert any(p["Package"] == "akonadi-server" for p in audit["closure"].values())
            assert len(audit["libraries"]) > 10 and len(audit["closure"]) > 10
        assert not any("autostart" in n or "dbus-1/" in n or n.endswith(".so") for n in members)
    control = subprocess.check_output(["dpkg-deb", "-f", str(package)], text=True)
    assert "Depends: python3 (>= 3.10), libc6 (>= 2.34), magnolie-organizer (>= 2.0.18)" in control
    assert "Suggests: akonadi-server, kdepim-runtime" in control and "Recommends:" not in control


def test_actual_old_package_unpack_upgrade_transfers_helper_ownership(component, tmp_path):
    directory, _ = component
    old = ROOT.parent / "magnolie-organizer-akonadi_1.0.0_amd64.deb"
    if not old.is_file():
        pytest.skip("Released 1.0.0 package is not available in this source checkout")
    root, admin = tmp_path / "root", tmp_path / "dpkg"
    root.mkdir()
    admin.mkdir()
    (admin / "status").touch()
    # Keep the suite non-root for real permission tests. Only this private unpack
    # needs namespace-local root ownership; neither its database nor log is global.
    command = ["unshare", "--user", "--map-root-user", "dpkg", "--force-not-root",
               "--instdir=" + str(root), "--admindir=" + str(admin), "--log=" + str(admin / "unpack.log")]
    # Real released DEB, real dpkg conflict/replacement handling, no fake baseline,
    # --force-depends or maintainer-script execution. This proves unpack ownership,
    # NOT configured installation/live KDE acceptance on a complete desktop.
    subprocess.run(command + ["--unpack", str(old)], check=True, capture_output=True, text=True)
    subprocess.run(command + ["--unpack", str(directory / artifacts("2.0.18")[0])], check=True, capture_output=True, text=True)
    owner = subprocess.check_output(["dpkg-query", "--admindir=" + str(admin), "-S",
        "/usr/libexec/magnolie-organizer/magnolie-akonadi-helper"], text=True)
    assert owner.strip() == "magnolie-organizer-kde: /usr/libexec/magnolie-organizer/magnolie-akonadi-helper"
    status = subprocess.check_output(["dpkg-query", "--admindir=" + str(admin), "-W", "-f=${Status}", "magnolie-organizer-kde"], text=True)
    assert status == "install ok unpacked"


@pytest.mark.parametrize("target", PROFILES)
def test_final_launcher_rejects_missing_unconfigured_abi_and_loader_inputs(component, tmp_path, target):
    directory, proof = component
    profile = PROFILES[target]
    rootfs = Path(os.environ.get(profile["env"], profile["rootfs"]))
    installed = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "-x", str(directory / artifacts("2.0.18")[0]), str(installed)], check=True)
    database = (rootfs / "var/lib/dpkg/status").read_text()
    (tmp_path / "empty-library").touch()
    base = ["bwrap", "--unshare-all", "--die-with-parent", "--uid", "0", "--gid", "0",
        "--ro-bind", str(rootfs), "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--ro-bind", str(tmp_path), "/tmp/test", "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/tmp", "--setenv", "DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/no-session"]
    helper = "/tmp/test/installed/usr/libexec/magnolie-organizer/magnolie-akonadi-helper"
    for failure in ("server", "abi", "unconfigured-transitive", "loader"):
        paragraphs = []
        changed = False
        for paragraph in database.split("\n\n"):
            if failure == "server" and paragraph.startswith("Package: akonadi-server\n"):
                changed = True
                continue
            if failure == "unconfigured-transitive" and paragraph.startswith("Package: libzstd1\n"):
                paragraph = paragraph.replace("Status: install ok installed", "Status: install ok unpacked")
                changed = True
            if failure == "abi":
                lines = []
                for line in paragraph.splitlines():
                    if line.startswith("Provides: ") and profile["abi"] in line:
                        # Remove a real Provide, never invent an ABI provider.
                        provides = [p for p in line.removeprefix("Provides: ").split(", ")
                                    if p.split()[0] != profile["abi"]]
                        changed = True
                        if not provides:
                            continue
                        line = "Provides: " + ", ".join(provides)
                    lines.append(line)
                paragraph = "\n".join(lines)
            paragraphs.append(paragraph)
        overlay = []
        if failure == "loader":
            library = next(value["realpath"] for path, value in proof["profiles"][target]["libraries"].items()
                           if f"libQt{profile['qt']}DBus.so" in path)
            overlay = ["--ro-bind", str(tmp_path / "empty-library"), library]
        else:
            assert changed, failure
            (tmp_path / "status").write_text("\n\n".join(paragraphs))
            overlay = ["--ro-bind", str(tmp_path / "status"), "/var/lib/dpkg/status"]
        result = subprocess.run(base + overlay + [helper, "--check"], capture_output=True, text=True, timeout=30)
        reply = json.loads(result.stdout)
        assert result.returncode == 1 and reply["ok"] is False and reply["error"], (failure, result)
        assert "items" not in reply and "calendars" not in reply
    # Normal protocol requests use the same final launcher and reject an absent
    # service before any job can be created. No desktop bus is made available.
    result = subprocess.run(base + [helper], input='{"command":"status"}', capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "KDE service is not running" in json.loads(result.stdout)["error"]
