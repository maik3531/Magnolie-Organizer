#!/usr/bin/env python3
"""Report real source coverage and generated-catalog parity without modifying files."""
import gettext
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
from katalog_pruefen import entries
from pot_erzeugen import handbook_data, handbook_messages


def main():
    template = entries((ROOT / "po/magnolie-handbuch.pot").read_text())
    missing_source = set(handbook_messages()) - template.keys()
    failed = bool(missing_source)
    pending = set()
    print("POT: %d messages; source keys missing: %d" % (len(template), len(missing_source)))
    for language in (ROOT / "po/LINGUAS").read_text().split():
        path = ROOT / "po" / (language + ".po")
        text = path.read_text()
        catalog = entries(text)
        missing = set(template) - catalog.keys()
        extra = catalog.keys() - template.keys()
        empty = {key for key in template if not catalog.get(key, "").strip()}
        pending.update(empty)
        expected = {key: value for key, value in catalog.items() if value}
        with (ROOT / "locale" / language / "LC_MESSAGES/magnolie-handbuch.mo").open("rb") as source:
            mo = {key: value for key, value in gettext.GNUTranslations(source)._catalog.items() if key}
        js = (ROOT / "web/i18n" / (language + ".js")).read_text()
        messages = json.loads(js.split(",", 1)[1].rsplit(");", 1)[0])["messages"]
        syntax = subprocess.run(["msgfmt", "--check", "--check-format", "-o", os.devnull, str(path)],
                                capture_output=True, text=True)
        parity = mo == expected and messages == expected
        fuzzy = any(line.startswith("#,") and "fuzzy" in line for line in text.splitlines())
        failed |= bool(missing or extra or empty or not parity or fuzzy or syntax.returncode)
        print("%s: missing=%d extra=%d untranslated=%d fuzzy=%s MO/JS=%s msgfmt=%d" %
              (language, len(missing), len(extra), len(empty), fuzzy, "match" if parity else "DIFFER", syntax.returncode))
    data = handbook_data()
    for page in data["pages"]:
        if page.get("inhaltAnhang", {}).get("en") in pending:
            print("Pending appendix:", page["id"])
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
