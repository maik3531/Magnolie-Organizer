#!/usr/bin/env python3
"""Move existing hand-written inline translations into PO without translating text.

Only exact, already present translations are imported. Missing entries stay empty;
msgmerge never guesses a translation. The regular catalog checker reports them.
"""
import json
from pathlib import Path
import subprocess
import tempfile

from pot_erzeugen import ROOT, handbook_data


def main():
    root = Path(ROOT)
    data = handbook_data()
    mappings = list(data["variants"].values()) + [
        page["inhaltAnhang"] for page in data["pages"]
        if page.get("inhaltAnhang") and not page.get("inhaltAnhangNeutral")]
    with tempfile.TemporaryDirectory(prefix="magnolie-handbook-catalog-") as directory:
        seed = Path(directory) / "inline.po"
        merged = Path(directory) / "merged.po"
        for language in (root / "po" / "LINGUAS").read_text().split():
            locale = language.replace("_", "-").lower()
            entries = {}
            for mapping in mappings:
                if mapping.get(locale) and mapping.get("en"):
                    entries[mapping["en"]] = mapping[locale]
            seed.write_text('msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n' +
                "\n\n".join("msgid " + json.dumps(key, ensure_ascii=False) + "\nmsgstr " +
                            json.dumps(value, ensure_ascii=False) for key, value in entries.items()) + "\n",
                encoding="utf-8")
            catalog = root / "po" / (language + ".po")
            subprocess.run(["msgcat", "--use-first", "--no-wrap", "-o", str(merged), str(catalog), str(seed)], check=True)
            subprocess.run(["msgmerge", "--no-fuzzy-matching", "--quiet", "-o", str(catalog),
                            str(merged), str(root / "po" / "magnolie-handbuch.pot")], check=True)


if __name__ == "__main__":
    main()
