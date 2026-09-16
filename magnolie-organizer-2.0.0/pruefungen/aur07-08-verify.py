"""Explicit two-desktop UI/backend integration gate; synthetic profiles only.

The Windows probe compiles the verbatim production ImportAsync with dialog/owner
stubs and the actual ExchangeCodec/AtomicStore. No product build or VM is used.
"""
import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "magnolie-organizer-2.0.0"
WINDOWS = ROOT / "Magnolie-Organizer-Windows-2.0.0"
DOTNET = "/tmp/opencode/fivefixnative/dotnet/dotnet"


def scope_proofs():
    result = {}
    for platform, web in (("linux", LINUX / "web"), ("windows", WINDOWS / "app/web")):
        source = (web / "anwendung.js").read_text()
        for name in ("starteImport", "druckStoff", "entferneAusDruckwahl", "oeffneDruckvorschau",
                     "planerKalenderModell", "planerMonatsModell", "planerDruckSeite"):
            body = source.split(f"  function {name}(", 1)[1].split("\n  function ", 1)[0]
            result[f"{platform}/{name}"] = hashlib.sha256(body.encode()).hexdigest()
    source = (LINUX / "bin/magnolie-organizer").read_text()
    method = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == "bei_import")
    result["linux/bei_import"] = hashlib.sha256(ast.get_source_segment(source, method).encode()).hexdigest()
    source = (WINDOWS / "BridgeDispatcher.cs").read_text()
    method = source.split("    private async Task ImportAsync(JsonElement message)", 1)[1].split(
        "    private async Task ImportLocalAsync", 1)[0]
    result["windows/ImportAsync"] = hashlib.sha256(method.encode()).hexdigest()
    return result


def module():
    loader = importlib.machinery.SourceFileLoader("aur07_native", str(LINUX / "bin/magnolie-organizer"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


def backend(chosen):
    m = module()
    message = json.load(sys.stdin)
    if message["cmd"] == "persist":
        m.atomar_text_schreiben(chosen, message["text"], modus=0o600)
        print(Path(chosen).read_text())
        return
    dialogs, replies = [], []

    class Filter:
        def set_name(self, name):
            self.name = name

        def add_pattern(self, pattern):
            self.pattern = pattern

    class Dialog:
        def __init__(self, **kwargs):
            self.data = {"Title": kwargs["title"], "Action": kwargs["action"], "Filters": []}
            dialogs.append(self.data)

        def add_buttons(self, *args):
            self.data["Buttons"] = args

        def add_filter(self, value):
            self.data["Filters"].append([value.name, value.pattern])

        def run(self):
            return 0 if chosen == "cancel" else 1

        def get_filename(self):
            return chosen

        def destroy(self):
            self.data["Disposed"] = True

    m.Gtk = SimpleNamespace(FileChooserDialog=Dialog, FileFilter=Filter,
        FileChooserAction=SimpleNamespace(OPEN="open"), ResponseType=SimpleNamespace(CANCEL=0, ACCEPT=1))
    window = SimpleNamespace(antwort=lambda callback, payload: replies.append(dict(callback=callback, payload=payload)))
    window._datei_oeffnen = lambda title, filters: m.Fenster._datei_oeffnen(window, title, filters)
    assert message["cmd"] == "import"
    m.Fenster.bei_import(window, message)
    print(json.dumps(dict(dialog=dialogs[0] if dialogs else None, replies=replies)))


def main():
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    with tempfile.TemporaryDirectory(prefix="aur07-08-", dir="/tmp/opencode") as temp:
        work = Path(temp)
        env = dict(os.environ, HOME=str(work / "home"), XDG_CONFIG_HOME=str(work / "config"),
            XDG_DATA_HOME=str(work / "data"), XDG_CACHE_HOME=str(work / "cache"),
            XDG_RUNTIME_DIR=str(work / "runtime"), TMPDIR=str(work),
            DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent", PYTHONDONTWRITEBYTECODE="1",
            DOTNET_CLI_HOME=str(work / "dotnet-home"), DOTNET_PROCESSOR_COUNT="2",
            DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
            DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_NOLOGO="1",
            DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", LANG="C.UTF-8", TZ="UTC")
        for name in ("home", "config", "data", "cache", "runtime", "dotnet-home"):
            (work / name).mkdir(mode=0o700)
        os.environ.update(env)
        proofs = scope_proofs()
        m = module()
        vcard = ("BEGIN:VCARD\r\nVERSION:4.0\r\nUID:aur07-rich\r\n"
            "N:Example;Ada;Middle;Dr.;Jr.\r\nFN:Dr. Ada Example\r\nORG:Synthetic Org\r\n"
            "EMAIL;TYPE=HOME:ada@example.org\r\nEMAIL;TYPE=WORK:work@example.org\r\n"
            "TEL;TYPE=CELL:+447700900123\r\nADR;TYPE=HOME:;;Test Road 1;Test Town;Region;12345;GB\r\n"
            "TEL;TYPE=HOME:+12025550123\r\nADR;TYPE=WORK:;;Other Road 2;Other Town;;54321;DE\r\n"
            "PHOTO:data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZ8AAAAASUVORK5CYII=\r\n"
            "BDAY:--0229\r\nANNIVERSARY:20010607\r\nNOTE:Imported note\r\nTITLE:Engineer\r\n"
            "URL:https://example.invalid\r\nX-AUR07:Preserve original\r\nEND:VCARD\r\n")
        contact = m.vcf_lesen(vcard)["kontakte"][0]
        ldif = m.ldif_schreiben([contact]) + ("\r\ndn: uid=simple,dc=example\r\n"
            "objectClass: inetOrgPerson\r\nuid:aur07-simple\r\ncn:Simple Example\r\n"
            "givenName:Simple\r\nsn:Example\r\nmail:simple@example.org\r\n\r\n")
        for name in ("contacts.ldif", "contacts.ldi", "unexpected.txt"):
            (work / name).write_text(ldif)
            (work / name).chmod(0o400)
        (work / "invalid.ldif").write_text("dn:: !!!!\ncn:: !!!!\n")
        (work / "invalid.ldif").chmod(0o400)
        import zipfile
        with zipfile.ZipFile(work / "contacts.zip", "w") as archive:
            archive.writestr("synthetic.ldi", ldif)
        (work / "contacts.zip").chmod(0o400)
        source = (WINDOWS / "BridgeDispatcher.cs").read_text()
        method = source.split("    private async Task ImportAsync(JsonElement message)", 1)[1].split(
            "    private async Task ImportLocalAsync", 1)[0]
        method = "    private async Task ImportAsync(JsonElement message)" + method
        wrapper = Path(__file__).with_name("aur07-08-native.cs.txt").read_text().replace("    /* IMPORT_METHOD */", method)
        (work / "Program.cs").write_text(wrapper)
        project = (WINDOWS / "tests/native-import/NativeImportProbe.csproj").read_text()
        project = project.replace("$(MSBuildThisFileDirectory)../..", str(WINDOWS))
        project = project.replace('<Compile Include="Program.cs.txt" />', "")
        for unused in ("WindowsContactStore.cs", "ThunderbirdCalendarImporter.cs"):
            project = project.replace(f'<Compile Include="$(SourceRoot)/{unused}" />', "")
        (work / "Probe.csproj").write_text(project)
        (work / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
        subprocess.run([DOTNET, "build", str(work / "Probe.csproj"), "-m:1", "-v:q",
            "-p:UseSharedCompilation=false", "-p:NuGetAudit=false", "--configfile", str(work / "NuGet.Config")],
            cwd=work, env=env, check=True)
        subprocess.run([shutil.which("node") or shutil.which("bun"), str(Path(__file__).with_name("aur07-08-ui.cjs")), str(work), DOTNET],
            cwd=ROOT, env=env, check=True)
        assert scope_proofs() == proofs, "Owned code changed during verification"
        print("Scoped SHA-256 before = after:", json.dumps(proofs, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        backend(sys.argv[1])
    else:
        main()
