#!/usr/bin/env python3
"""Compile PO into the normal runtime MO and JS outputs (no translation)."""
from pathlib import Path
import subprocess

from po_zu_js import main as javascript

ROOT = Path(__file__).resolve().parents[1]


def main():
    javascript(["po_zu_js.py", "en", str(ROOT / "po/english/protected.po"),
                str(ROOT / "web/i18n/en.js")])
    for language in (ROOT / "po/LINGUAS").read_text().split():
        source = ROOT / "po" / (language + ".po")
        target = ROOT / "locale" / language / "LC_MESSAGES/magnolie-handbuch.mo"
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(target), str(source)], check=True)
        javascript(["po_zu_js.py", language, str(source), str(ROOT / "web/i18n" / (language + ".js"))])


if __name__ == "__main__":
    main()
