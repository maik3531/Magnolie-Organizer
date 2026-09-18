#!/usr/bin/env python3
"""Erzeugt die Windows-POT-Vorlage deterministisch aus Web- und C#-Quellen."""

import os
import re
import subprocess
import tempfile
import argparse


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "po", "magnolie-organizer.pot")
PROPS = os.path.join(ROOT, "Directory.Build.props")


def deferred_literals(name, text):
    """Static setup choices translated only when rendered, not when constructed."""
    literal = r'"(?:\\.|[^"\\])*"'
    result = []
    if name == "FirstRunSetupForm.cs":
        for match in re.finditer(r'private static readonly (?:CountryChoice|RegionChoice)\[\].*?=\s*\[(.*?)\];', text, re.S):
            for row in re.finditer(r'new\(([^()]*)\)', match[1]):
                result.append(re.findall(literal, row[1])[-1])
        for match in re.finditer(r'foreach\s*\(var\s*\([^)]*\b(?:caption|label)\)\s*in\s*new\[\]\s*\{(.*?)\}\)', text, re.S):
            for row in re.finditer(r'\(\s*' + literal + r'\s*,\s*(' + literal + r')\s*\)', match[1]):
                result.append(row[1])
        match = re.search(r'ModuleLabel\(string type\).*?switch\s*\{(.*?)\}', text, re.S)
        if not match:
            raise ValueError("Setup module labels not found")
        result.extend(re.findall(r'=>\s*(' + literal + r')', match[1]))
    if name == "FirstRunSetupPhoneServices.cs":
        match = re.search(r'Capabilities\s*=>\s*\[(.*?)\];', text, re.S)
        if not match:
            raise ValueError("Setup phone capabilities not found")
        for row in re.finditer(r'new\(([^()]*)\)', match[1]):
            values = re.findall(literal, row[1])
            if len(values) > 1:
                result.append(values[-1])
    # Only branch values, never condition literals such as transport IDs.
    for match in re.finditer(r'\b(?:T|Gettext)\([^;\n]*?\?\s*(' + literal + r')\s*:\s*(' + literal + r')\s*\)', text):
        result.extend(match.groups())
    for match in re.finditer(r'\b(?:T|Gettext)\([^{};]*\bswitch\s*\{(.*?)\}\s*\)', text, re.S):
        result.extend(re.findall(r'=>\s*(' + literal + r')', match[1]))
    return result


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=TARGET)
    target = os.path.abspath(parser.parse_args(argv).output)
    version = re.search(r"<Version>([^<]+)</Version>", open(PROPS, encoding="utf-8").read()).group(1)
    common = ["--from-code=UTF-8", "--no-location", "--sort-output",
              "--package-name=Magnolie Organizer", "--package-version=" + version,
              "--msgid-bugs-address=maik3531@gmail.com", "--output=" + target]
    subprocess.run(["xgettext", "--language=JavaScript", "--keyword=_", "--keyword=msgid",
                    "--keyword=customText",
                    "--keyword=uebersetzt", "--keyword=uebersetztMehrzahl:1,2",
                    "--keyword=ngettext:1,2", "--keyword=pgettext:1c,2", *common,
                    os.path.join(ROOT, "app", "web", "i18n-markers.js"),
                    os.path.join(ROOT, "app", "web", "anwendung.js")], check=True)
    csharp_literals = []
    for name in sorted(name for name in os.listdir(ROOT) if name.endswith(".cs")):
        text = open(os.path.join(ROOT, name), encoding="utf-8").read()
        if "NativeLocalization.Gettext" in text or (name.startswith("BridgeDispatcher") and
                                                       name != "BridgeDispatcherContract.cs"):
            csharp_literals.extend(match.group("literal") for match in re.finditer(
                r"\b(?:NativeLocalization\.)?(?:T|Gettext)\(\s*"
                r"(?P<literal>\"(?:\\.|[^\"\\])*\")\s*(?=[,)])", text))
            csharp_literals.extend(deferred_literals(name, text))
    if not csharp_literals:
        raise ValueError("Keine übersetzbaren C#-Zeichenketten gefunden")
    with tempfile.TemporaryDirectory(prefix="magnolie-pot-csharp-") as directory:
        source = os.path.join(directory, "gettext.cs")
        with open(source, "w", encoding="utf-8", newline="\n") as file:
            file.write("static class Catalog { static void Add() {\n")
            for literal in csharp_literals:
                file.write("Gettext(" + literal + ");\n")
            file.write("} static string Gettext(string value) => value; }\n")
        subprocess.run(["xgettext", "--join-existing", "--language=C#",
                        "--keyword=Gettext", *common, source], check=True)
    text = open(target, encoding="utf-8").read()
    text = re.sub(r'"POT-Creation-Date: [^"\\n]*\\n"',
                  lambda _: '"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\n"', text)
    with open(target, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)


if __name__ == "__main__":
    run()
