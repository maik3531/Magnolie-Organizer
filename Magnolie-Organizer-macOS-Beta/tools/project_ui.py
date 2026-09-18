#!/usr/bin/env python3
"""Read-only canonical sources -> disposable macOS Beta projection, never a hand-maintained UI fork."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

BETA = Path(__file__).resolve().parents[1]
REPO = BETA.parent
LINUX = REPO / "magnolie-organizer-2.0.0"
FREEZE = BETA / "SourceFreeze.json"
GENERATED = BETA / "Generated"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    roots = [LINUX / "web", LINUX / "symbole", REPO / "contracts", BETA / "Projection", BETA / "Sources", BETA / "Resources"]
    files = []
    for root in roots:
        if root.is_symlink():
            raise ValueError("Symlinked source root refused: " + str(root))
        for file in sorted(root.rglob("*")):
            if file.is_symlink():
                raise ValueError("Symlinked source refused: " + str(file))
            if file.is_file():
                files.append(file)
    files += [LINUX / "bin/magnolie-organizer", REPO / "LICENSE.md", REPO / "PROTECTED-ASSETS-LICENSE.txt",
              REPO / "Magnolie-Organizer-Windows-2.0.0/LICENSE",
              REPO / "Magnolie-Organizer-Windows-2.0.0/BridgeDispatcherContract.cs",
              REPO / "Magnolie-Organizer-Windows-2.0.0/EncryptionService.cs",
              REPO / "magnolie-handbuch-stamm/web/mobile-downloads.json",
              BETA / "Package.swift", BETA / "tools/build_dev.py", Path(__file__).resolve()]
    return {str(file.relative_to(REPO)): file.read_bytes() for file in sorted(set(files))}


def inventory(snapshot):
    return {name: digest(data) for name, data in snapshot.items()}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Canonical UI anchor changed; review the projection: " + old[:100])
    return text.replace(old, new, 1)


def commands(snapshot):
    source = snapshot[str((BETA / "Sources/BetaCore/Contract.swift").relative_to(REPO))].decode()
    block = source.split("public enum Command: String, CaseIterable {", 1)[1].split("\n}", 1)[0]
    return [name.strip() for line in block.splitlines() if line.strip().startswith("case ")
             for name in line.strip()[5:].split(",")]


def shared_catalogs(snapshot):
    prefix = str(LINUX.relative_to(REPO)) + "/web/i18n/"
    result = {}
    for name, data in snapshot.items():
        if not name.startswith(prefix) or not name.endswith(".js"):
            continue
        match = re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\("([^"]+)", (.*)\);\s*', data.decode(), re.S)
        if not match:
            raise ValueError("Canonical gettext catalog wrapper changed: " + name)
        locale, payload = match.groups()
        result[locale.replace("_", "-").lower()] = {key: value for key, value in json.loads(payload)["messages"].items() if isinstance(value, str) and value}
    return result


def project(snapshot, target):
    """Also used by host tests in a temporary directory, without creating a source freeze."""
    if target.exists():
        raise ValueError("Projection destination must not exist.")
    target.mkdir(parents=True)
    prefix = str(LINUX.relative_to(REPO)) + "/"
    for name, data in snapshot.items():
        if name.startswith(prefix + "web/") or name.startswith(prefix + "symbole/"):
            path = target / name.removeprefix(prefix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    app = target / "web/anwendung.js"
    text = app.read_text()
    identity = json.loads(snapshot[str((BETA / "Resources/BetaIdentity.json").relative_to(REPO))])
    text, count = re.subn(r'^const FASSUNG = "[^"]+";', 'const FASSUNG = ' + json.dumps(identity["version"]) + ';', text, flags=re.M)
    if count != 1:
        raise ValueError("Canonical version binding changed.")
    text = replace_once(text, 'const SPEICHER_SCHLUESSEL = "magnolie-organizer-daten";',
                        'const SPEICHER_SCHLUESSEL = "magnolie-organizer-macOSBeta-daten";')
    # Desktop release notes advertise native services which this port does not have.
    # Generate Beta metadata using the same translated labels as the working controls.
    notes = {locale: [identity["name"] + " " + identity["version"]] +
             [messages.get(key, key) for key in ["Create backup", "Restore backup", "Language"]]
             for locale, messages in {"en": {}, **shared_catalogs(snapshot)}.items()}
    text, count = re.subn(r'const NEU_IN_DIESER_FASSUNG_FASSUNG = "[^"]+";\nconst NEU_IN_DIESER_FASSUNG = \{[\s\S]*?\n\};',
                         lambda _: 'const NEU_IN_DIESER_FASSUNG_FASSUNG = ' + json.dumps(identity["version"]) + ';\nconst NEU_IN_DIESER_FASSUNG = ' + json.dumps(notes) + ';', text)
    if count != 1:
        raise ValueError("Canonical release note binding changed.")
    text = replace_once(text, "window.webkit.messageHandlers[this.name].postMessage(JSON.stringify(obj));\n        return true;",
                        "return window.MacBeta.send(obj, this.name);")
    text = replace_once(text, "  function normalisiere(roh) {",
                        "  function normalisiere(roh) { return window.MacBeta.preserve(roh, normalisiereDesktop(roh)); }\n"
                        "  function normalisiereDesktop(roh) {")
    disabled = {
        "baueSeiteSync": "macOS Internet Accounts are not integrated. Linux EDS/Akonadi and DAV/Graph sync are not available. Read-only EventKit discovery is in the application menu.",
    }
    for function, message in disabled.items():
        anchor = "  function " + function + "(wurzel) {"
        text = replace_once(text, anchor, anchor + "\n    window.MacBeta.platformNotice(wurzel, " + json.dumps(message) + "); return;")
    for function in ["baueSicherungsdateien"]:
        anchor = "  function " + function + "(wurzel) {"
        text = replace_once(text, anchor, anchor + '''
    window.MacBeta.backupControls(wurzel, () => $("#knopf-sicherung").click(),
      () => Bruecke.sende({ cmd: "sicherung_waehlen" })); return;''')
    text = replace_once(text, "  function baueSeiteSicherungen(wurzel) {", '''  function baueSeiteSicherungen(wurzel) {
    window.MacBeta.platformNotice(wurzel, _("Recovery snapshots") + ": Recovery-macOS-Beta/*.json"); return;''')
    text = replace_once(text, '''          const pfad = DATEN.einstellungen.allgemein.sicherungsordner || "";
          if (pfad) zeigeSicherungsanlage(pfad);
          else Bruecke.sende({ cmd: "sicherung", pfad: "", kennwort: "" });''',
                        '''          Bruecke.sende({ cmd: "sicherung", pfad: "", kennwort: "" });''')
    text, regional_calls = re.subn(r'Bruecke\.sende\(\{ cmd: "regional_einstellungen", regional: \{[\s\S]*?\} \}\);',
        lambda match: "nachDauerhaftemSpeichern(() => " + match[0][:-1] + ");", text)
    if regional_calls != 1:
        raise ValueError("Canonical regional settings binding changed.")
    text = replace_once(text, '    { id: "ort", name: msgid("Country & holidays") },',
                        '    { id: "regional", name: msgid("Language and regional display") },\n'
                        '    { id: "ort", name: msgid("Country & holidays") },')
    text = replace_once(text, "  const App = {", '''  const App = {
    macOSBetaValidateRestore(text) {
      normalisiere(JSON.parse(text));
      return true;
    },''')
    start = text.index("    sicherungWiederhergestellt(nutzlast) {")
    end = text.index("    baumStand(nutzlast) {", start)
    callback = text[start:end]
    callback = replace_once(callback, "      raeumeTombstonesAuf();\n      raeumePapierkorbAuf();\n", "")
    callback = replace_once(callback, "      planeSpeichern();", '''      letzterSpeicherText = JSON.stringify(DATEN);
      setzeSpeicherStatus(_("Saved"), true);''')
    text = text[:start] + callback + text[end:]
    # Bind the platform modifier to the canonical handlers (no duplicate editor implementation).
    text = replace_once(text, 'if (ev.ctrlKey && !ev.altKey && ev.key >= "1" && ev.key <= "8")',
                        'if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key >= "1" && ev.key <= "8")')
    text = replace_once(text, 'if (!ev.ctrlKey || ev.altKey || ev.metaKey) return;',
                        'if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;')
    password_binding = "neu: neuFeld.value, sicherungen: true,"
    if text.count(password_binding) != 2:
        raise ValueError("Canonical password binding changed; review Beta's current-file-only encryption scope.")
    text = text.replace(password_binding, "neu: neuFeld.value, sicherungen: false,")
    text, password_calls = re.subn(r'Bruecke\.sende\(\{ cmd: "kennwort_setzen", alt: "",[\s\S]*?\}\);',
                                  lambda match: "nachDauerhaftemSpeichern(() => " + match[0][:-1] + ");", text)
    if password_calls != 2:
        raise ValueError("Canonical password command changed; review save-before-encryption binding.")
    text = replace_once(text, "  function baueSeiteSicherheit(wurzel) {",
                        "  function baueSeiteSicherheit(wurzel) {\n"
                        '    window.MacBeta.platformNotice(wurzel, "macOS Beta: encryption can be enabled for the current profile only. Password changes/removal, backup rekeying and closed-app reminders are unavailable. Recovery files retain their original encryption state. The desktop background-service controls below have no native effect.");')
    text = replace_once(text, "  function fuelleEdsAuswahl(nutzlast) {",
                        '  function fuelleEdsAuswahl(nutzlast) {\n'
                        '    const betaStatus = document.getElementById("sync-status");\n'
                        '    if (betaStatus) betaStatus.textContent = "macOS Internet Accounts are not integrated in this Beta.";\n'
                        '    const betaButton = document.getElementById("sync-jetzt");\n'
                        '    if (betaButton) betaButton.disabled = true; return;')
    # Preserve the existing timer and due-item calculation, not a new recurrence implementation.
    text = replace_once(text, "if (!Bruecke.vorhanden) {\n        setInterval(() => pruefeErinnerungen(false), 30000);",
                        "if (window.MacBeta) {\n        setInterval(() => pruefeErinnerungen(false), 30000);")
    reminder_start = text.index("  function pruefeErinnerungen(nurAufraeumen) {")
    reminder_end = text.index("\n  function ", reminder_start + 1)
    reminder = text[reminder_start:reminder_end]
    reminder = replace_once(reminder, "if (Bruecke.vorhanden) return;",
                            "if (!initialisiert || gesperrt) return;")
    task_start = reminder.index("    for (const aufgabe of DATEN.aufgaben.concat(customAufgabenFuerErinnerung())) {")
    task_end = reminder.index("\n    }\n  }", task_start) + len("\n    }")
    reminder = reminder[:task_start] + '''    for (const aufgabe of DATEN.aufgaben.concat(customAufgabenFuerErinnerung())) {
      let alarms;
      try { alarms = window.MacBeta.taskAlarms(aufgabe, organizerZeitzone()); }
      catch (_) { window.MacBeta.reminderError(); continue; }
      for (const alarm of alarms) {
        if (gemeldeteTermine.has(alarm.id) || +jetztWert < alarm.at || +jetztWert > alarm.at + 5 * 60000) continue;
        gemeldeteTermine.add(alarm.id);
        const dueDate = new Date(alarm.dueAt), dueParts = organizerDatumzeitTeile(dueDate);
        const wann = alarm.days ? uebersetztMehrzahl("in %(count)s day", "in %(count)s days", alarm.days)
          : (aufgabe.faelligZeit ? uebersetzt("at %(time)s", {
            time: zeitText(isoHeute(dueDate), pad2(dueParts.stunde) + ":" + pad2(dueParts.minute)) }) : _("today"));
        meldeErinnerung(alarm.days ? _("Task reminder") : _("Task is due"),
          uebersetzt("%(title)s - %(when)s", { title: aufgabe.titel, when: wann }));
      }
    }''' + reminder[task_end:]
    text = text[:reminder_start] + reminder + text[reminder_end:]
    # No automatic deletion of tombstones/trash in a port without a recovery journal.
    text = replace_once(text, "      raeumeTombstonesAuf();\n      const papierkorbBereinigt = raeumePapierkorbAuf();",
                        "      const papierkorbBereinigt = false;")
    app.write_text(text)
    adapter = snapshot[str((BETA / "Projection/macos-beta.js").relative_to(REPO))].decode()
    adapter = replace_once(adapter, "/*GENERATED_COMMANDS*/[]", json.dumps(commands(snapshot)))
    adapter = replace_once(adapter, "/*GENERATED_IDENTITY*/{}", json.dumps(identity))
    (target / "web/macos-beta.js").write_text(adapter)
    (target / "web/macos-beta.css").write_bytes(snapshot[str((BETA / "Projection/macos-beta.css").relative_to(REPO))])
    index = target / "web/index.html"
    html = replace_once(index.read_text(), "<title>Magnolie Organizer</title>",
                        "<title>Magnolie Organizer macOS Beta</title>\n<link rel=\"stylesheet\" href=\"macos-beta.css\">")
    # All existing catalogs are copied and registered; locale selection still belongs to the canonical UI.
    catalogs = sorted((target / "web/i18n").glob("*.js"))
    html = replace_once(html, '<script src="i18n-active.js"></script>',
                        "\n".join('<script src="i18n/' + file.name + '"></script>' for file in catalogs))
    html = replace_once(html, '<script src="anwendung.js"></script>',
                        '<script src="macos-beta.js"></script>\n<script src="anwendung.js"></script>')
    index.write_text(html)
    # Reuse the shared gettext-generated catalogs for native standard controls.
    native = shared_catalogs(snapshot)
    extras = json.loads(snapshot[str((BETA / "Resources/native-extra-i18n.json").relative_to(REPO))])
    for locale in native:
        native[locale].update(extras.get(locale, {}))
    (target / "native-i18n.json").write_text(json.dumps(native, ensure_ascii=False, sort_keys=True) + "\n")
    (target / "BetaIdentity.json").write_text(json.dumps(identity, sort_keys=True) + "\n")
    mobile = snapshot["magnolie-handbuch-stamm/web/mobile-downloads.json"]
    notes = json.loads(mobile)["notes"]
    if notes["filename"] != "Magnolie-Notes.apk" or not notes["url"].endswith("/Magnolie-Notes.apk"):
        raise ValueError("Canonical Notes download must use the version-independent MobileAlias.")
    (target / "web/mobile-downloads.json").write_bytes(mobile)
    licenses = target / "Licenses"
    licenses.mkdir()
    for source, name in [("LICENSE.md", "LICENSE.md"), ("PROTECTED-ASSETS-LICENSE.txt", "PROTECTED-ASSETS-LICENSE.txt"),
                         ("Magnolie-Organizer-Windows-2.0.0/LICENSE", "GPL-3.0.txt")]:
        (licenses / name).write_bytes(snapshot[source])


def tree_hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in generated output.")
        if path.is_file() and path.name != "ProjectionManifest.json":
            result[str(path.relative_to(root))] = digest(path.read_bytes())
    return result


def frozen(snapshot):
    freeze = json.loads(FREEZE.read_text())
    if freeze.get("inputs") != inventory(snapshot):
        raise ValueError("Desktop or adapter changed since the explicit freeze. Refusing stale UI; freeze again after desktop work finishes.")
    return freeze


def verify():
    snapshot = inputs()
    freeze = frozen(snapshot)
    manifest = json.loads((GENERATED / "ProjectionManifest.json").read_text())
    if manifest.get("inputs") != freeze["inputs"] or manifest.get("outputs") != tree_hashes(GENERATED):
        raise ValueError("Generated payload differs from its frozen input/output manifest.")
    # A manifest is not authority for hand-edited payloads; reproduce the projection and compare.
    with tempfile.TemporaryDirectory(prefix="macOS-Beta-check-") as temp:
        expected = Path(temp) / "UI"
        project(snapshot, expected)
        if tree_hashes(expected) != tree_hashes(GENERATED):
            raise ValueError("Generated UI is not the reproducible canonical projection.")
    if inventory(inputs()) != inventory(snapshot):
        raise ValueError("Sources changed during verification.")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit", "freeze", "generate", "check"])
    parser.add_argument("--confirm-desktop-frozen", action="store_true")
    args = parser.parse_args()
    snapshot = inputs()
    if args.action == "audit":
        print(json.dumps({"inputFiles": len(snapshot), "commands": commands(snapshot),
                          "freezeExists": FREEZE.exists(), "generatedExists": GENERATED.exists()}, indent=2))
    elif args.action == "freeze":
        if not args.confirm_desktop_frozen:
            raise ValueError("Explicit --confirm-desktop-frozen required; do not freeze ongoing desktop edits.")
        if inventory(inputs()) != inventory(snapshot):
            raise ValueError("Sources changed during freeze.")
        FREEZE.write_text(json.dumps({"format": 1, "inputs": inventory(snapshot)}, indent=2) + "\n")
        print("Recorded explicit macOS Beta source freeze; no UI or app built.")
    elif args.action == "generate":
        freeze = frozen(snapshot)
        with tempfile.TemporaryDirectory(prefix=".macOS-Beta-projection-", dir=BETA) as temp:
            stage = Path(temp) / "UI"
            project(snapshot, stage)
            if inventory(inputs()) != inventory(snapshot):
                raise ValueError("Sources changed during generation.")
            manifest = {"format": 1, "name": "Magnolie Organizer macOS Beta", "inputs": freeze["inputs"],
                        "outputs": tree_hashes(stage), "nativeValidated": False}
            (stage / "ProjectionManifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            if GENERATED.is_symlink():
                raise ValueError("Symlinked output refused.")
            if GENERATED.exists():
                if not (GENERATED / "ProjectionManifest.json").is_file():
                    raise ValueError("Existing unowned output refused.")
                previous = json.loads((GENERATED / "ProjectionManifest.json").read_text())
                if previous.get("name") != "Magnolie Organizer macOS Beta" or previous.get("outputs") != tree_hashes(GENERATED):
                    raise ValueError("Existing output was modified; retaining it instead of overwriting.")
                shutil.rmtree(GENERATED)
            stage.rename(GENERATED)
        print("Generated frozen macOS Beta UI. Native build/testing still required.")
    else:
        verify()
        print("Frozen macOS Beta projection verified; this is not native validation.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print("macOS Beta projection blocked: " + str(error), file=sys.stderr)
        sys.exit(1)
