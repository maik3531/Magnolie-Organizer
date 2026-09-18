"""Source-only gates, independent of the subsequent manual translation phase."""

import importlib.util
import ast
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from test_locale_completeness import _catalog

LINUX = Path(__file__).resolve().parents[1]
WINDOWS = LINUX.parent / "magnolie-organizer-windows"


def generator(root):
    spec = importlib.util.spec_from_file_location("pot_generator", root / "werkzeuge/pot_erzeugen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_linux_all_runtime_helpers_are_scanned():
    sources = set(generator(LINUX).quellen_finden())
    assert {str(path) for path in (LINUX / "bin").glob("*.py")} <= sources


def test_installed_source_discovery_excludes_other_applications(tmp_path):
    root = tmp_path / "share/magnolie-organizer"
    web = root / "web"
    web.mkdir(parents=True)
    for name in ("i18n-markers.js", "anwendung.js"):
        (web / name).write_text("")
    binary = tmp_path / "bin"
    binary.mkdir()
    for name in ("magnolie-organizer", "magnolie_hintergrund.py", "magnolie_setup_ui.py",
                 "magnolie_setup_state.py", "unrelated_application.py"):
        (binary / name).write_text("")
    sources = generator(LINUX).quellen_finden(str(root))
    assert str(binary / "magnolie_setup_state.py") in sources
    assert str(binary / "unrelated_application.py") not in sources


def test_native_phone_diagnostics_have_english_runtime_boundaries(monkeypatch):
    monkeypatch.syspath_prepend(str(LINUX / "bin"))
    from magnolie_kdeconnect import NATIVE_KDE_LIMIT, NATIVE_KDE_UNAVAILABLE

    tree = ast.parse((LINUX / "bin/magnolie-organizer").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fehler_deutsch")
    namespace = {"_": lambda message: "translated:" + message}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "native-error-boundary", "exec"), namespace)
    translate = namespace["fehler_deutsch"]
    for message in (NATIVE_KDE_LIMIT, NATIVE_KDE_UNAVAILABLE):
        assert translate(RuntimeError(message)) == "translated:" + message
    own = next(node for node in ast.walk(function) if isinstance(node, ast.Dict))
    for source, target in zip(own.keys, own.values):
        assert isinstance(target, ast.Call) and target.func.id == "_"
        assert translate(RuntimeError(source.value)) == "translated:" + target.args[0].value
    assert translate(OSError("Bluetooth-Daten sind nicht verfügbar (radio_off).")) == \
        "translated:Bluetooth data is unavailable (radio_off)."
    assert translate(RuntimeError("Synthetic external detail")) == "Synthetic external detail"
    assert translate(OSError("Synthetic external detail"), "Persönlicher Sync") == \
        "translated:translated:Personal synchronization reported an unexpected error (technical detail: Synthetic external detail)."


@pytest.mark.parametrize("message", [
    "Telefonidentitaet ist beschaedigt.", "Telefon-Speicherschluessel ist beschaedigt.",
    "Telefonablage ist beschaedigt.", "Telefon-Gegenstellenliste ist beschaedigt.",
    "Synthetic OS diagnostic",
])
def test_setup_storage_error_boundary_translates_only_owned_messages(monkeypatch, message):
    spec = importlib.util.spec_from_file_location("setup_state", LINUX / "bin/magnolie_setup_state.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def fail(*args, **kwargs):
        raise RuntimeError(message)
    monkeypatch.setitem(sys.modules, "magnolie_telefon", types.SimpleNamespace(PhoneService=fail))
    calls = []
    services = module.SetupPhoneServices(lambda: "/unused-fixture", lambda: "Fixture",
        translate=lambda key: calls.append(key) or "Translated fixture")
    with pytest.raises(RuntimeError) as error:
        services.connect("wifi", lambda _: None)
    if message == "Synthetic OS diagnostic":
        assert str(error.value) == message and calls == []
    else:
        assert str(error.value) == "Translated fixture"
        assert calls == ["The phone settings are damaged."]


def test_deferred_boundaries_extract_values_not_identifiers(tmp_path):
    source = tmp_path / "choices.py"
    source.write_text('''
for key, message in (("wire-id", "Visible choice"),):
    check(message)
for title in ("Visible field",):
    tr(title)
tr("First branch" if value == "wire-condition" else "Second branch")
self.translate("yes" if condition else "no")
''', encoding="utf-8")
    assert set(generator(LINUX).deferred_messages(source)) == {
        "Visible choice", "Visible field", "First branch", "Second branch", "yes", "no"}


def cross_windows_deferred_literals():
    windows = generator(WINDOWS)
    text = '''
T(kind == "wire-condition" ? "First branch" : "Second branch");
NativeLocalization.Gettext(error switch { IOException => "IO message", _ => "Other message" });
'''
    assert {json.loads(value) for value in windows.deferred_literals("Helper.cs", text)} == {
        "First branch", "Second branch", "IO message", "Other message"}


def test_current_desktop_sources_and_handoffs_are_in_generated_pots(tmp_path, roots=(LINUX,)):
    # Active letter labels, not historical prose/code blocks from the handoff.
    common = {
        "Letter template", "DIN 5008 Form B (default)",
        "Compact sender line", "DIN 5008 Form B with fold marks",
        "DIN 5008 Form A (27 mm letterhead)",
        "The address is too long for the letter's address field. Shorten the return address or recipient, or choose the compact template.",
        "Form B reserves 45 mm for the letterhead; Form A reserves 27 mm. Both place the return line and recipient in the left-hand address field and add fold and punch marks. Check long addresses and envelope fit in print preview before printing at 100%.",
        "Import preview", "Entries ready to import", "Thunderbird profile version",
        "Sources and imports", "Server", "Username", "Application password",
        "Connection discovery failed. Check the server and credentials.",
        "The file has an unsupported format.", "The import file is larger than 32 megabytes.",
        "Select your phone", "Confirm that the code matches on both devices.",
        "Bluetooth system pairing was not confirmed.", "Wrong Bluetooth device.",
        "Open the phone connection screen and try again.",
        "The background settings could not be saved.", "Delivery status uncertain",
    }
    for root in roots:
        output = tmp_path / (root.name + ".pot")
        command = ["python3", str(root / "werkzeuge/pot_erzeugen.py"), "--output", str(output)]
        subprocess.run(command, check=True, capture_output=True)
        first = output.read_bytes()
        subprocess.run(command, check=True, capture_output=True)
        assert output.read_bytes() == first
        keys = {key[1] for key in _catalog(output)}
        expected = set(common)
        if root == LINUX:
            expected.add("The connection settings could not be saved.")
            for source in (root / "bin").iterdir():
                if source.suffix != ".py" and source.name != "magnolie-organizer":
                    continue
                for call in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                    if not isinstance(call, ast.Call) or not call.args:
                        continue
                    name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
                    if name in {"_", "N_", "tr", "translate", "gettext"} and isinstance(call.args[0], ast.Constant):
                        if isinstance(call.args[0].value, str) and call.args[0].value:
                            expected.add(call.args[0].value)
            expected.update(line for line in (LINUX / "pruefungen/background-visible-msgids.txt").read_text().splitlines()
                            if line and not line.startswith("#"))
            expected.update(generator(LINUX).deferred_messages(LINUX / "bin/magnolie_setup_state.py"))
        else:
            background = (WINDOWS / "BACKGROUND-FIXES.md").read_text()
            expected.update(re.search(r"```text\n(.*?)\n```", background, re.S)[1].splitlines())
            for source in WINDOWS.glob("*.cs"):
                text = source.read_text(encoding="utf-8")
                expected.update(json.loads(value) for value in generator(WINDOWS).deferred_literals(source.name, text))
                if "NativeLocalization.Gettext" in text or source.name.startswith("BridgeDispatcher."):
                    expected.update(json.loads(match[1]) for match in re.finditer(
                        r'\b(?:T|Gettext)\(\s*("(?:\\.|[^"\\])*")\s*[,)]', text))
        assert not expected - keys, sorted(expected - keys)
        assert not {"wire-id", "nextcloud", "generic-dav", "bluetooth", "select"} & keys
