"""Real source bytes in isolated install/source fixtures; never build a product."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
from release_sources import audit_binary, source_files, sync_contracts

MANDATORY = ["test_recurrence.py", "test_recurrence_oracle.py",
             "test_recurrence_integration.py", "test_recurrence_timezones.py"]
CONTRACTS = ["recurrence-integration.json", "recurrence-timezones.json"]


def install_modules(kind):
    if kind == "deb":
        text = (ROOT / "debian/install").read_text()
        return set(re.findall(r"^bin/(magnolie_[\w]+\.py)\s+usr/bin$", text, re.M))
    if kind == "rpm":
        text = (ROOT / "rpm/magnolie-organizer.spec").read_text()
        return set(re.findall(r"^install -Dpm 0644 bin/(magnolie_[\w]+\.py) %\{buildroot\}%\{_bindir\}/\1$", text, re.M))
    if kind == "appimage":
        text = (ROOT / "werkzeuge/appimage_bauen.sh").read_text()
        return set(re.findall(r'^install -m 0644 "\$WURZEL/bin/(magnolie_[\w]+\.py)" "\$APPDIR/usr/bin/\1"$', text, re.M))
    manifest = json.loads((ROOT / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json").read_text())
    commands = [value for value in manifest["modules"][-1]["build-commands"]
                if value.startswith("install -m 0644 bin/") and value.endswith(" /app/bin/")]
    return set(re.findall(r"bin/(magnolie_[\w]+\.py)", "\n".join(commands)))


def environment(tmp_path):
    result = os.environ.copy()
    for name in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        path = tmp_path / name.lower()
        path.mkdir(parents=True, exist_ok=True)
        result[name] = str(path)
    result.update(TMPDIR=str(tmp_path), DISPLAY="", WAYLAND_DISPLAY="",
                  DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(tmp_path / "no-session-bus"),
                  PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return result


@pytest.mark.parametrize("kind,prefix", [("deb", "usr"), ("rpm", "usr"),
                                        ("flatpak", "app"), ("appimage", "AppDir/usr")])
def test_installed_imports_use_only_the_actual_package_file_list(kind, prefix, tmp_path):
    modules = install_modules(kind)
    assert modules == {path.name for path in (ROOT / "bin").glob("magnolie_*.py")}
    bindir = tmp_path / prefix / "bin"
    bindir.mkdir(parents=True)
    for name in sorted(modules | {"magnolie-organizer"}):
        shutil.copyfile(ROOT / "bin" / name, bindir / name)
    audit_binary(tmp_path / prefix)
    env = environment(tmp_path)
    # Deliberately offer the canonical tree as an accidental fallback: -I and
    # the origin assertions must still reject a missing installed helper.
    env["PYTHONPATH"] = str(ROOT / "bin")
    command = [sys.executable, "-I", "-B", str(ROOT / "werkzeuge/runtime_pruefen.py"), str(bindir)]
    if kind == "appimage":
        zoneinfo = tmp_path / prefix / "share/zoneinfo"
        for name in ("UTC", "Europe/Berlin", "America/New_York", "Australia/Lord_Howe",
                     "Pacific/Apia", "Africa/Casablanca", "America/Santiago"):
            target = zoneinfo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path("/usr/share/zoneinfo") / name, target)
        command += ["--tzpath", str(zoneinfo)]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    imports = '''
import importlib, pathlib, sys
bindir = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(bindir))
for name in sys.argv[2:]:
    module = importlib.import_module(pathlib.Path(name).stem)
    assert pathlib.Path(module.__file__) == bindir / name
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", imports, str(bindir), *sorted(modules)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    (bindir / "magnolie_recurrence.py").unlink()
    missing = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert missing.returncode != 0 and "magnolie_recurrence" in missing.stderr


def test_public_source_archive_replays_mandatory_suite_without_dateutil_or_siblings(tmp_path):
    projection = tmp_path / "projection"
    command = [sys.executable, "-B", str(ROOT / "werkzeuge/release_sources.py")]
    env = environment(tmp_path)
    subprocess.run(command + ["copy", str(ROOT), str(projection)], check=True, env=env)
    shared = ROOT.parent / "contracts"
    if shared.is_dir():
        subprocess.run(command + ["copy", str(shared), str(tmp_path / "contracts")], check=True, env=env)
    sync_contracts(projection)
    archive = tmp_path / "synthetic-source.tar"
    with tarfile.open(archive, "w") as output:
        for relative, path in source_files(projection):
            output.add(path, arcname="standalone/" + relative.as_posix(), recursive=False)
    extracted = tmp_path / "public"
    extracted.mkdir()
    with tarfile.open(archive) as source:
        # This archive was just constructed from checked regular source files.
        # Validate every member explicitly also on Python versions before the
        # tarfile extraction-filter API (supported runtime starts at 3.9).
        assert all(member.isfile() and Path(member.name).parts[0] == "standalone"
                   and ".." not in Path(member.name).parts for member in source.getmembers())
        source.extractall(extracted, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    standalone = extracted / "standalone"
    assert not (standalone.parent / "contracts").exists()
    for name in CONTRACTS:
        assert (standalone / "contracts" / name).is_file()
    for name in ("baum-1-receipt-v1-vectors.json", "baum-1-receipt-v1.md",
                 "phone-bluetooth-first-pair.md", "phone-setup-daemon-lifecycle.md", "phone-wlan-invitation.md"):
        assert (standalone / "contracts" / name).is_file()
    assert (standalone / "pruefungen/fixtures/recurrence-rfc-oracle.json").is_file()
    assert (standalone / "bin/magnolie_recurrence.py").is_file()
    driver = '''
import importlib.abc, sys
from pathlib import Path
class NoDateutil(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "dateutil" or fullname.startswith("dateutil."):
            raise ImportError("dateutil deliberately unavailable in public source replay")
sys.meta_path.insert(0, NoDateutil())
import pytest
class NoSkips:
    def pytest_sessionfinish(self, session, exitstatus):
        terminal = session.config.pluginmanager.getplugin("terminalreporter")
        if terminal.stats.get("skipped"):
            session.exitstatus = 1
sys.path.insert(0, str(Path("pruefungen").resolve()))
raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]], plugins=[NoSkips()]))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", driver,
                             *("pruefungen/" + name for name in MANDATORY + ["test_baum_receipts.py", "test_letter_layout.py"])],
                            cwd=standalone, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "skipped" not in result.stdout


@pytest.mark.parametrize("explicit_installation", [False, True])
def test_flatpak_builder_sees_explicit_installation_read_only(tmp_path, explicit_installation):
    source = tmp_path / "source"
    for directory in ("werkzeuge", "debian", "flatpak"):
        (source / directory).mkdir(parents=True)
    shutil.copyfile(ROOT / "werkzeuge/flatpak_bauen.sh", source / "werkzeuge/flatpak_bauen.sh")
    shutil.copyfile(ROOT / "debian/changelog", source / "debian/changelog")
    (source / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json").write_text(
        json.dumps({"modules": [{"build-commands": []}]}))
    tools = tmp_path / "tools"
    tools.mkdir()
    runtime = tmp_path / "runtime/files/bin/xgettext"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("synthetic dependency")
    runtime.chmod(0o755)
    flatpak = tools / "flatpak"
    flatpak.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["SYNTHETIC_CALLS"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "info" and "--show-location" in args:
    print(os.environ["SYNTHETIC_RUNTIME"])
elif args[0] == "run":
    if os.environ.get("FLATPAK_USER_DIR"):
        assert "--filesystem=" + os.environ["FLATPAK_USER_DIR"] + ":ro" in args
    if "--run" in args:
        print("Usage: synthetic test fixture")
elif args[0] == "build-bundle":
    pathlib.Path(args[-3]).write_text("synthetic bundle, not a product")
''')
    flatpak.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    env = environment(tmp_path)
    env.update(PATH=str(tools) + os.pathsep + env["PATH"],
               SYNTHETIC_CALLS=str(calls), SYNTHETIC_RUNTIME=str(runtime.parents[2]))
    env.pop("MAGNOLIE_CONTRIBUTOR_HASH", None)
    env.pop("FLATPAK_USER_DIR", None)
    if explicit_installation:
        env["FLATPAK_USER_DIR"] = str(tmp_path / "external installation")
    result = subprocess.run(["sh", str(source / "werkzeuge/flatpak_bauen.sh"), str(tmp_path / "fixture.flatpak")],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    runs = [args for args in map(json.loads, calls.read_text().splitlines()) if args[0] == "run"]
    assert len(runs) == 2
    assert all("--filesystem=" + str(source) in args for args in runs)
    assert all(sum(arg.startswith("--filesystem=") for arg in args) == 1 + explicit_installation for args in runs)


def test_all_build_gates_include_recurrence_and_runtime_locatability():
    for relative in ("debian/rules", "rpm/magnolie-organizer.spec", "werkzeuge/release_bauen.sh"):
        script = (ROOT / relative).read_text()
        for name in MANDATORY:
            assert "pruefungen/" + name in script, (relative, name)
        assert "runtime_pruefen.py" in script
    for relative in ("debian/rules", "rpm/magnolie-organizer.spec"):
        assert "bin/magnolie_recurrence.py" in (ROOT / relative).read_text()
    for name in MANDATORY:
        text = (ROOT / "pruefungen" / name).read_text()
        assert "importorskip" not in text
    requirements = (ROOT / "pruefungen/requirements-recurrence-oracle.txt").read_text()
    assert "python-dateutil==2.9.0.post0" in requirements
