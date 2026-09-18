#!/usr/bin/env python3
"""Merge manual UI translations; --ui-only excludes handbook and non-UI entries."""
import json
from pathlib import Path
import re
import subprocess
import sys
import importlib.util
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "contracts/personal-custom-ui.json").read_text(encoding="utf-8"))
IDS = DATA["ids"]
TRANSLATIONS = DATA["translations"]
UI = json.loads((ROOT / "contracts/ui-bugfixes.json").read_text(encoding="utf-8"))
assert set(UI["translations"]) == set(TRANSLATIONS)
for index, name in enumerate(UI["ids"]):
    if name not in IDS:
        IDS.append(name)
        for locale, values in TRANSLATIONS.items():
            values.append(UI["translations"][locale][index])
    else:
        for locale, values in TRANSLATIONS.items():
            values[IDS.index(name)] = UI["translations"][locale][index]
PRIVACY = json.loads((ROOT / "contracts/personal-custom-privacy.json").read_text(encoding="utf-8"))
assert set(PRIVACY) == set(TRANSLATIONS) and all(PRIVACY.values())
IDS.append("personal_custom_privacy")
for locale, values in TRANSLATIONS.items():
    values.append(PRIVACY[locale])
assert len(TRANSLATIONS) == 20 and all(len(v) == len(IDS) and all(v) for v in TRANSLATIONS.values())
ENGLISH = TRANSLATIONS["en"]
DESKTOP = {index for index, name in enumerate(IDS) if name not in {
    "personal_custom_title", "personal_custom_delete", "personal_custom_keep"}}
UI_ONLY = "--ui-only" in sys.argv
RETIRED_UI = {
    "Storage available / total", "Memory available / total",
    "Synchronize Custom tasks and appointments",
    "Both devices must opt in. Turning this off pauses Custom reminders and updates but keeps copies. Linked text blocks are not shared.",
    "This device does not support Custom synchronization.",
}
PO_ENTRY = r'(?m)^msgid ("[^\n]*"\n(?:"[^\n]*"\n)*)msgstr "[^\n]*"\n(?:"[^\n]*"\n)*'


def quoted(value):
    return json.dumps(value, ensure_ascii=False)


def merge_entry(content, msgid, msgstr):
    # Match decoded PO strings, including msgmerge's wrapped multiline entries.
    for match in re.finditer(PO_ENTRY, content):
        if "".join(json.loads(line) for line in match[1].splitlines()) == msgid:
            return content[:match.start()] + 'msgid ' + quoted(msgid) + '\nmsgstr ' + quoted(msgstr) + '\n' + content[match.end():]
    return content + '\n#. Manually translated UI text.\nmsgid ' + quoted(msgid) + '\nmsgstr ' + quoted(msgstr) + '\n'


def retire_ui(content):
    def retire(match):
        msgid = "".join(json.loads(line) for line in match[1].splitlines())
        return "".join("#~ " + line for line in match[0].splitlines(keepends=True)) if msgid in RETIRED_UI else match[0]
    return re.sub(PO_ENTRY, retire, content)


def generate_handbook():
    handbook = ROOT / "magnolie-handbuch-stamm/web/inhalt.js"
    content = handbook.read_text(encoding="utf-8")
    start, end = "// BEGIN GENERATED CUSTOM PRIVACY", "// END GENERATED CUSTOM PRIVACY"
    entries = {"zh-cn" if locale == "zh_CN" else locale: "<p>" + escape(text) + "</p>" for locale, text in PRIVACY.items()}
    original = json.loads(re.search(r'"personal-sync": \{\s*en: ("[^\n]+")\s*\}', content)[1])
    spec = importlib.util.spec_from_file_location("handbook_po", ROOT / "magnolie-handbuch-stamm/werkzeuge/po_zu_js.py")
    catalog_reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog_reader)
    prior = {"en": original}
    previous = re.search(r'const CUSTOM_PRIVACY_PRIOR = (\{.*?\});', content, re.S)
    if previous:
        prior = json.loads(previous[1])
    for locale in PRIVACY:
        if locale != "en" and not previous:
            messages = catalog_reader.read_catalog(ROOT / "magnolie-handbuch-stamm/po" / (locale + ".po"))["messages"]
            prior["zh-cn" if locale == "zh_CN" else locale] = messages[original]
    block = start + "\nconst CUSTOM_PRIVACY = " + json.dumps(entries, ensure_ascii=False, indent=2) + ";\n"
    block += 'const CUSTOM_PRIVACY_PRIOR = ' + json.dumps(prior, ensure_ascii=False, indent=2) + ';\n'
    block += 'for (const [locale, text] of Object.entries(CUSTOM_PRIVACY)) {\n'
    block += '  HANDBUCH_ANHAENGE["personal-sync"][locale] = CUSTOM_PRIVACY_PRIOR[locale] + text;\n'
    block += '  PORTABLE_SICHERUNG_INHALT[locale] += text;\n}\n' + end
    if start in content:
        content = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: block, content, flags=re.S)
    else:
        content = content.replace('const MOBILE_DOWNLOADS =', block + '\nconst MOBILE_DOWNLOADS =', 1)
    handbook.write_text(content, encoding="utf-8")


def generate():
    if not UI_ONLY:
        generate_handbook()
    for component, web, po in (("magnolie-organizer", "web", "po"),
                               ("magnolie-organizer-windows", "app/web", "app/po")):
        base = ROOT / component
        for locale, values in TRANSLATIONS.items():
            if locale == "en":
                continue
            catalog = base / po / (locale + ".po")
            content = retire_ui(catalog.read_text(encoding="utf-8"))
            for index, (msgid, msgstr) in enumerate(zip(ENGLISH, values)):
                if UI_ONLY and IDS[index] not in UI["ids"]:
                    continue
                entry = 'msgid ' + quoted(msgid) + '\nmsgstr ' + quoted(msgstr) + '\n'
                if index not in DESKTOP:
                    content = content.replace('\n#. Personal Custom synchronization; manually translated.\n' + entry, '\n')
                    continue
                content = merge_entry(content, msgid, msgstr)
            catalog.write_text(content, encoding="utf-8")
            js = base / web / "i18n" / (locale + ".js")
            subprocess.run([sys.executable, str(base / "werkzeuge/po_zu_js.py"), locale, str(catalog), str(js)], check=True)
            mo = base / "locale" / locale / "LC_MESSAGES/magnolie-organizer.mo"
            if component == "magnolie-organizer" and mo.parent.is_dir():
                subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(mo), str(catalog)], check=True)
        pot = base / po / "magnolie-organizer.pot"
        content = retire_ui(pot.read_text(encoding="utf-8"))
        for index, text in enumerate(ENGLISH):
            if UI_ONLY and IDS[index] not in UI["ids"]:
                continue
            if index not in DESKTOP:
                content = content.replace('\n#. Personal Custom synchronization.\nmsgid ' + quoted(text) + '\nmsgstr ""\n', '\n')
                continue
            content = merge_entry(content, text, "")
        pot.write_text(content, encoding="utf-8")
    native = ROOT / "magnolie-organizer-windows/app/native-i18n.json"
    arguments = [sys.executable, str(ROOT / "magnolie-organizer-windows/werkzeuge/po_zu_native.py"), str(native)]
    for locale in TRANSLATIONS:
        if locale != "en":
            arguments.extend([locale, str(ROOT / "magnolie-organizer-windows/app/po" / (locale + ".po"))])
    subprocess.run(arguments, check=True)
    resources = ROOT / "magnolie-notes/app/src/main/res"
    for locale, values in TRANSLATIONS.items():
        folder = "values" if locale == "en" else "values-" + ("zh-rCN" if locale == "zh_CN" else locale)
        target = resources / folder / "strings.xml"
        content = target.read_text(encoding="utf-8")
        for name, text in zip(IDS, values):
            if UI_ONLY and name not in UI["ids"]:
                continue
            if name.startswith("sms_scheduling_") or name == "personal_custom_named_optin":
                continue
            escaped = escape(text).replace("'", "\\'").replace('"', '\\"')
            entry = f'    <string name="{name}">{escaped}</string>'
            pattern = r'(?m)^\s*<string name="' + name + r'">.*?</string>'
            if re.search(pattern, content):
                content = re.sub(pattern, lambda _: entry, content)
            else:
                content = content.replace('</resources>', entry + '\n</resources>')
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    generate()
