#!/usr/bin/env python3
"""Explicit installed KDE probe; never uses an existing HOME or session bus."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tarfile
import io
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=("ubuntu24.04", "debian13", "ubuntu26.04"))
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    args.artifact = args.artifact.resolve(strict=True)
    assert args.artifact.name == f"magnolie-organizer-kde_{args.version}_amd64.deb"
    artifact_hash = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    if not args.inside:
        # Akonadi's MySQL socket path has a stricter limit than a normal filename.
        home = Path(tempfile.mkdtemp(prefix="mkde-"))
        for name in ("config", "data", "cache", "runtime"):
            (home / name).mkdir(mode=0o700)
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8", "HOME": str(home),
               "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
               "XDG_CACHE_HOME": str(home / "cache"), "XDG_RUNTIME_DIR": str(home / "runtime"),
               "QT_QPA_PLATFORM": "offscreen", "AKONADI_INSTANCE": "t" + home.name[-8:]}
        print("Private installed KDE evidence:", home, flush=True)
        with (home / "session.log").open("w") as log:
            result = subprocess.run(["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
                                     "--inside", "--version", args.version, "--artifact", str(args.artifact),
                                     "--profile", args.profile], env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=180)
        print((home / "session.log").read_text(), flush=True)
        return result.returncode
    home = Path(os.environ["HOME"])
    assert home.name.startswith("mkde-") and home.parent == Path("/tmp")
    assert os.environ["AKONADI_INSTANCE"] == "t" + home.name[-8:] and os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    helper = Path("/usr/libexec/magnolie-organizer/magnolie-akonadi-helper")
    installed = subprocess.check_output(["dpkg-query", "-W", "-f=${Status} ${Version}", "magnolie-organizer-kde"], text=True)
    assert installed == "install ok installed " + args.version, installed
    integrity = subprocess.run(["dpkg", "--verify", "magnolie-organizer-kde"], check=True, capture_output=True, text=True)
    assert not integrity.stdout.strip(), integrity.stdout
    payload = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(args.artifact)])
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if member.isfile() and name.startswith("usr/libexec/magnolie-organizer/"):
                installed_path = Path("/") / name
                assert ".." not in Path(name).parts and installed_path.resolve().is_relative_to(helper.parent)
                assert archive.extractfile(member).read() == installed_path.read_bytes(), name
    ready = subprocess.run([str(helper), "--check"], check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(ready.stdout) == {"ok": True, "target": args.profile, "activated": False}
    print(json.dumps({"artifact": args.artifact.name, "sha256": artifact_hash, "profile": args.profile}), flush=True)
    try:
        subprocess.run(["akonadictl", "start"], check=True, timeout=60)
        resource_created = False
        for attempt in range(30):
            probe = subprocess.run([str(helper)], input='{"command":"status"}', text=True,
                                   capture_output=True, timeout=25)
            print(probe.stdout, probe.stderr, flush=True)
            response = json.loads(probe.stdout)
            if probe.returncode == 0 and response.get("ok") is True and not resource_created:
                # Wait for server readiness before asking the agent manager.
                # This resource uses only the newly created XDG data directory.
                manager = "org.freedesktop.Akonadi.Control." + os.environ["AKONADI_INSTANCE"]
                created = subprocess.check_output(["gdbus", "call", "--session", "--dest", manager,
                                "--object-path", "/AgentManager", "--method",
                                "org.freedesktop.Akonadi.AgentManager.createAgentInstance",
                                "akonadi_contacts_resource"], text=True, timeout=25)
                resource = ast.literal_eval(created)[0]
                service = "org.freedesktop.Akonadi.Resource." + resource + "." + os.environ["AKONADI_INSTANCE"]
                for _ in range(25):
                    info = subprocess.run(["gdbus", "introspect", "--session", "--dest", service,
                                           "--object-path", "/Settings", "--xml"], capture_output=True, text=True, timeout=10)
                    if info.returncode == 0:
                        settings = next((i for i in ET.fromstring(info.stdout).findall("interface")
                                         if i.find("method[@name='setPath']") is not None), None)
                        if settings is not None:
                            break
                    time.sleep(1)
                else:
                    raise RuntimeError("Local contacts settings service did not become ready: " + info.stderr)
                contacts = home / "contacts"
                contacts.mkdir(mode=0o700)
                (home / "contact-settings.xml").write_text(info.stdout)
                methods = {method.attrib["name"] for method in settings.findall("method")}
                save = "save" if "save" in methods else "writeConfig"
                assert save in methods, methods
                for method, values in (("setPath", [str(contacts)]), (save, [])):
                    subprocess.run(["gdbus", "call", "--session", "--dest", service, "--object-path", "/Settings",
                                    "--method", settings.attrib["name"] + "." + method, *values], check=True, timeout=10)
                subprocess.run(["gdbus", "call", "--session", "--dest", service, "--object-path", "/",
                                "--method", "org.freedesktop.Akonadi.Agent.Control.reconfigure"], check=True, timeout=10)
                subprocess.run(["gdbus", "call", "--session", "--dest", manager, "--object-path", "/AgentManager",
                                "--method", "org.freedesktop.Akonadi.AgentManager.agentInstanceSynchronize", resource],
                               check=True, timeout=10)
                resource_created = True
            if probe.returncode == 0 and response.get("ok") is True and (
                    (response.get("calendars") and response.get("addressbooks")) or attempt == 29):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Private live Akonadi did not become ready")
        assert isinstance(response["calendars"], list) and isinstance(response["addressbooks"], list)
        snapshots = []
        crud = []
        for kind, key in (("calendar", "calendars"), ("addressbook", "addressbooks")):
            for collection in response[key]:
                request = {k: collection[k] for k in ("collection", "generation", "instance")}
                request.update(command="snapshot", kind=kind)
                result = subprocess.run([str(helper)], input=json.dumps(request), text=True, capture_output=True, timeout=25)
                print(result.stdout, result.stderr, flush=True)
                assert result.returncode == 0 and json.loads(result.stdout)["ok"] is True
                snapshots.append(json.loads(result.stdout))
            writable = next((c for c in response[key] if {"create", "change", "delete"} <= set(c["rights"])), None)
            if writable is None:
                continue
            binding = {k: writable[k] for k in ("collection", "generation", "instance")}
            for field, value in (("generation", binding["generation"] + 1), ("instance", "foreign-instance")):
                stale = dict(binding, command="snapshot", kind=kind)
                stale[field] = value
                refused = subprocess.run([str(helper)], input=json.dumps(stale), text=True, capture_output=True, timeout=25)
                print("stale-" + field, refused.stdout, flush=True)
                assert refused.returncode == 1 and "instance changed" in json.loads(refused.stdout)["error"]
            def call(command, **fields):
                request = dict(binding, command=command, kind=kind, **fields)
                result = subprocess.run([str(helper)], input=json.dumps(request), text=True, capture_output=True, timeout=25)
                print(command, result.stdout, result.stderr, flush=True)
                value = json.loads(result.stdout)
                assert result.returncode == 0 and value.get("ok") is True
                return value
            uid = home.name + "-" + kind
            assert call("exists", uid=uid)["exists"] is False
            if kind == "calendar":
                content = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Magnolie//Test//EN\r\n"
                           "BEGIN:VEVENT\r\nUID:" + uid + "\r\nDTSTART:20260911T120000Z\r\n"
                           "DTEND:20260911T130000Z\r\nSUMMARY:Synthetic KDE probe\r\n"
                           "RRULE:FREQ=DAILY;COUNT=2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
            else:
                content = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:" + uid + "\r\n"
                           "FN:Synthetic KDE probe\r\nN:Probe;Synthetic;;;\r\n"
                           "EMAIL:probe@example.invalid\r\nEND:VCARD\r\n")
            item = call("create", content=content)["item"]
            assert item["gid"] == uid and "Synthetic KDE probe" in item["content"]
            assert call("exists", uid=uid)["exists"] is True
            snapshot = call("snapshot")
            assert snapshot["complete"] is True and any(i["gid"] == uid for i in snapshot["items"])
            item = call("modify", id=item["id"], revision=item["revision"],
                        content=content.replace("Synthetic KDE probe", "Modified KDE probe"))["item"]
            assert "Modified KDE probe" in item["content"]
            call("delete", id=item["id"], revision=item["revision"])
            assert call("exists", uid=uid)["exists"] is False
            crud.append(kind)
        assert "addressbook" in crud, "Local contact resource did not complete synthetic CRUD"
        (home / "result.json").write_text(json.dumps({"version": args.version,
            "artifact": args.artifact.name, "sha256": artifact_hash, "profile": args.profile,
            "helperSha256": hashlib.sha256(helper.read_bytes()).hexdigest(), "installed": True,
            "isolatedLiveAkonadi": True, "status": response, "snapshots": snapshots,
            "syntheticCrud": crud}, indent=2) + "\n")
    finally:
        subprocess.run(["akonadictl", "stop"], timeout=30, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
