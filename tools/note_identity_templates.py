#!/usr/bin/env python3
"""Capture immutable legacy welcome templates and project them to both runtimes."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/note-identity-templates.json"
BEGIN = "  // BEGIN GENERATED NOTE IDENTITY TEMPLATES"
END = "  // END GENERATED NOTE IDENTITY TEMPLATES"


def capture():
    source = (ROOT / "magnolie-organizer/web/anwendung.js").read_text(encoding="utf-8")
    block = re.search(r"function willkommensNotiz\(\) \{([\s\S]*?)\n  \}", source).group(1)
    messages = ["".join(json.loads(part) for part in re.findall(r'"(?:\\.|[^"\\])*"', match))
        for match in re.findall(r'_\(\s*((?:"(?:\\.|[^"\\])*"\s*\+?\s*)+)\)', block)]
    assert len(messages) == 11 and messages[0] == "Welcome ✱"
    sys.path.insert(0, str(ROOT / "magnolie-organizer/werkzeuge"))
    from po_zu_js import katalog_lesen
    languages = ["en", *(ROOT / "magnolie-organizer/po/LINGUAS").read_text(encoding="utf-8").split()]
    templates = []
    for language in languages:
        catalog = {} if language == "en" else katalog_lesen(str(ROOT / "magnolie-organizer/po" / (language + ".po")))["messages"]
        tr = lambda text: catalog.get(text, text)
        prefix = "\n\n".join(tr(text) for text in messages[1:-1])
        suffix = "\n\n" + tr(messages[-1])
        left, right = tr("Your data is stored at:\n%(path)s").split("%(path)s")
        templates.append(dict(locale=language, title=tr(messages[0]), before=prefix + "\n\n" + left,
                              after=right + suffix, text=prefix + suffix))
    return dict(format=1, templates=templates)


def render(path, block, check):
    text = path.read_text(encoding="utf-8")
    pattern = re.escape(BEGIN) + r"[\s\S]*?" + re.escape(END)
    updated, count = re.subn(pattern, lambda _: BEGIN + "\n" + block + "\n" + END, text)
    assert count == 1, path
    if check:
        assert updated == text, "Stale note identity templates: " + str(path)
    else:
        path.write_text(updated, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.capture:
        assert not CONTRACT.exists(), "Legacy templates are immutable; add a new revision instead"
        CONTRACT.write_text(json.dumps(capture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["format"] == 1 and len(data["templates"]) == 20
    values = [[t[key] for key in ("title", "before", "after", "text")] for t in data["templates"]]
    js = "  const NOTIZ_VORLAGEN = " + json.dumps(values, ensure_ascii=False, indent=2) + ";"
    for web in ("magnolie-organizer/web", "magnolie-organizer-windows/app/web"):
        render(ROOT / web / "anwendung.js", js, args.check)
    strings = lambda value: json.dumps(value, ensure_ascii=False).replace("$", "\\$")
    kotlin = "  private val templates = listOf(\n" + ",\n".join(
        "    arrayOf(" + ", ".join(strings(value) for value in template) + ")" for template in values) + "\n  )"
    render(ROOT / "magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/NotizVorlagen.kt", kotlin, args.check)


if __name__ == "__main__":
    main()
