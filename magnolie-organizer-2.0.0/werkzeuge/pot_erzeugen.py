#!/usr/bin/env python3
"""Erzeugt die englische POT-Vorlage reproduzierbar aus den Quellen."""

import os
import subprocess
import argparse
import shutil
import sys
import re
import json
import ast
import tempfile
from pathlib import Path


WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def paket_version(wurzel=WURZEL):
    metadata = os.path.join(wurzel, "version.json")
    if os.path.isfile(metadata):
        with open(metadata, encoding="utf-8") as datei:
            version = json.load(datei).get("version", "")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid installed version.json")
        return version
    with open(os.path.join(wurzel, "debian", "changelog"),
              "r", encoding="utf-8") as datei:
        erste = datei.readline()
    treffer = re.match(r"^[^(]+\(([^)]+)\)", erste)
    if not treffer:
        raise ValueError("debian/changelog")
    return treffer.group(1).strip()


def quellen_finden(wurzel=WURZEL, installierter_start=None):
    web = os.path.join(wurzel, "web")
    start = os.path.join(wurzel, "bin", "magnolie-organizer")
    if not os.path.isfile(start):
        start = installierter_start or os.path.normpath(os.path.join(
            wurzel, "..", "..", "bin", "magnolie-organizer"))
    hintergrund = os.path.join(wurzel, "bin", "magnolie_hintergrund.py")
    if not os.path.isfile(hintergrund):
        hintergrund = os.path.join(os.path.dirname(start), "magnolie_hintergrund.py")
    setup_ui = os.path.join(wurzel, "bin", "magnolie_setup_ui.py")
    if not os.path.isfile(setup_ui):
        setup_ui = os.path.join(os.path.dirname(start), "magnolie_setup_ui.py")
    quellen = [os.path.join(web, "i18n-markers.js"),
               os.path.join(web, "anwendung.js"), start, hintergrund, setup_ui]
    fehlend = [pfad for pfad in quellen if not os.path.isfile(pfad)]
    if fehlend:
        raise FileNotFoundError(", ".join(fehlend))
    return quellen + [str(path) for path in sorted(Path(os.path.dirname(start)).glob("magnolie_*.py"))
                      if str(path) not in quellen]


def deferred_messages(path):
    """Extract static choices passed through setup's dynamic gettext boundaries."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    messages = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in {"tr", "translate", "_"} and node.args and isinstance(node.args[0], ast.IfExp):
                for branch in (node.args[0].body, node.args[0].orelse):
                    if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                        messages.add(branch.value)
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            targets = list(node.target.elts) if isinstance(node.target, ast.Tuple) else [node.target]
            for index, target in enumerate(targets):
                if not isinstance(target, ast.Name):
                    continue
                for call in (item for statement in node.body for item in ast.walk(statement) if isinstance(item, ast.Call)):
                    name = getattr(call.func, "id", "")
                    position = 1 if name == "bind" else 0
                    if name not in {"tr", "check", "bind"} or len(call.args) <= position:
                        continue
                    if not isinstance(call.args[position], ast.Name) or call.args[position].id != target.id:
                        continue
                    for row in node.iter.elts:
                        value = row.elts[index] if isinstance(row, (ast.Tuple, ast.List)) else row
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            messages.add(value.value)
        # These daemon errors remain English on the wire; SetupPhoneServices translates them.
        if isinstance(node, ast.ClassDef) and node.name == "PhoneSetupSessions":
            for raised in ast.walk(node):
                if isinstance(raised, ast.Raise) and isinstance(raised.exc, ast.Call):
                    for arg in raised.exc.args[:1]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            messages.add(arg.value)
    return sorted(messages)


def haupt(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=os.path.join(
        WURZEL, "po", "magnolie-organizer.pot"))
    argumente = parser.parse_args(argv)
    ziel = os.path.abspath(argumente.output)
    if not shutil.which("xgettext"):
        raise FileNotFoundError("xgettext")
    marken, javascript, *python_sources = quellen_finden()
    version = paket_version()
    os.makedirs(os.path.dirname(ziel), exist_ok=True)

    subprocess.run([
        "xgettext", "--language=JavaScript", "--from-code=UTF-8",
        "--keyword=_", "--keyword=customText", "--keyword=msgid", "--keyword=uebersetzt", "--keyword=uebersetztMehrzahl:1,2",
        "--keyword=gettext",
        "--keyword=ngettext:1,2", "--keyword=pgettext:1c,2",
        "--no-location", "--sort-output",
        "--package-name=Magnolie Organizer", "--package-version=" + version,
        "--msgid-bugs-address=maik3531@gmail.com", "--output=" + ziel,
        marken, javascript
    ], check=True)

    subprocess.run([
        "xgettext", "--join-existing", "--language=Python", "--from-code=UTF-8",
        "--keyword=_", "--keyword=N_", "--keyword=tr:1", "--keyword=bind:2",
        "--keyword=label:1", "--keyword=check:1", "--keyword=radio:2",
        "--keyword=entry:1", "--keyword=field:3",
        "--keyword=page:1", "--keyword=section:2",
        "--keyword=translate:1", "--keyword=show_error:1",
        "--no-location", "--sort-output",
        "--package-name=Magnolie Organizer", "--package-version=" + version,
        "--msgid-bugs-address=maik3531@gmail.com",
        "--output=" + ziel, *python_sources
    ], check=True)
    with tempfile.TemporaryDirectory(prefix="magnolie-pot-deferred-") as directory:
        source = Path(directory) / "deferred.py"
        messages = sorted({message for path in python_sources for message in deferred_messages(path)})
        source.write_text("\n".join("_(" + json.dumps(message, ensure_ascii=False) + ")" for message in messages), encoding="utf-8")
        subprocess.run(["xgettext", "--join-existing", "--language=Python", "--from-code=UTF-8",
                        "--keyword=_", "--no-location", "--sort-output", "--output=" + ziel,
                        str(source)], check=True)
    with open(ziel, "r", encoding="utf-8") as datei:
        inhalt = datei.read()
    inhalt = re.sub(r'"POT-Creation-Date: [^"\\n]*\\n"',
                    lambda _treffer:
                    '"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\n"', inhalt)
    with open(ziel, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(inhalt)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(haupt())
    except (OSError, subprocess.SubprocessError) as fehler:
        sys.stderr.write(str(fehler) + "\n")
        sys.exit(1)
