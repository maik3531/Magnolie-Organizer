#!/usr/bin/env python3
"""Check existing manual SMS/time translations and regenerate desktop catalogs only."""
import argparse
import gettext
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "magnolie-organizer"
WINDOWS = ROOT / "magnolie-organizer-windows"
INVALID = "Enter both hours and minutes, or leave the time completely empty."
HINT = "Use the mouse wheel to change the time in 5-minute steps (hold Shift for whole hours)"
LABELS = ["Time", "New appointment", "New task", "Add", "Save changes", "Cancel",
          "SMS settings", "Schedule", "Pending SMS messages"]
parser = argparse.ArgumentParser()
parser.add_argument("--generate", action="store_true")
args = parser.parse_args()
translations = json.loads((ROOT / "contracts/ui-bugfixes.json").read_text())["translations"]
assert len(translations) == 20
native_args = []
for po in sorted((WINDOWS / "app/po").glob("*.po")):
    native_args += [po.stem, str(po)]
if args.generate:
    subprocess.run([sys.executable, str(WINDOWS / "werkzeuge/po_zu_native.py"),
                    str(WINDOWS / "app/native-i18n.json"), *native_args], check=True)
native = json.loads((WINDOWS / "app/native-i18n.json").read_text())["locales"]
manual_time = {}
for base, app in ((LINUX, LINUX), (WINDOWS, WINDOWS / "app")):
    catalogs = sorted((app / "po").glob("*.po"))
    assert {po.stem for po in catalogs} == set(translations) - {"en"}
    for po in catalogs:
        locale = po.stem
        subprocess.run([sys.executable, str(LINUX / "werkzeuge/katalog_pruefen.py"),
                        str(app / "po/magnolie-organizer.pot"), str(po)], check=True)
        js = app / "web/i18n" / (locale + ".js")
        if args.generate:
            subprocess.run([sys.executable, str(base / "werkzeuge/po_zu_js.py"), locale, str(po), str(js)], check=True)
        messages = json.loads(js.read_text().split(", ", 1)[1].rsplit(");", 1)[0])["messages"]
        if base == LINUX:
            mo = base / "locale" / locale / "LC_MESSAGES/magnolie-organizer.mo"
            if args.generate:
                subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(mo), str(po)], check=True)
            with mo.open("rb") as stream:
                compiled = gettext.GNUTranslations(stream)
            runtime = {key: compiled.gettext(key) for key in [INVALID, HINT, *LABELS, *translations["en"][:3]]}
            manual_time[locale] = messages[INVALID]
        else:
            runtime = native[locale]
            assert messages[INVALID] == manual_time[locale], locale
        for key in [INVALID, HINT, *LABELS, *translations["en"][:3]]:
            assert messages[key] and runtime[key] == messages[key], (base.name, locale, key)
        for index, key in enumerate(translations["en"][:3]):
            assert messages[key] == translations[locale][index], (base.name, locale, key)
        assert messages[INVALID] != INVALID and messages[HINT] != HINT, locale
    print(base.name + ": 19 complete PO catalogs; SMS/time JS and native runtime parity")
for locale, text in manual_time.items():
    print(locale + ": " + text)
print("PASS: English source + 19 manual translations, both desktop trees")
