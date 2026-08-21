#!/usr/bin/env python3
"""Erzeugt die Windows-POT-Vorlage deterministisch aus Web- und C#-Quellen."""

import os
import re
import subprocess


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "po", "magnolie-organizer.pot")
PROPS = os.path.join(ROOT, "Directory.Build.props")


def run():
    version = re.search(r"<Version>([^<]+)</Version>", open(PROPS, encoding="utf-8").read()).group(1)
    common = ["--from-code=UTF-8", "--no-location", "--sort-output",
              "--package-name=Magnolie Organizer", "--package-version=" + version,
              "--msgid-bugs-address=maik3531@gmail.com", "--output=" + TARGET]
    subprocess.run(["xgettext", "--language=JavaScript", "--keyword=_", "--keyword=msgid",
                    "--keyword=uebersetzt", "--keyword=uebersetztMehrzahl:1,2",
                    "--keyword=ngettext:1,2", "--keyword=pgettext:1c,2", *common,
                    os.path.join(ROOT, "app", "web", "i18n-markers.js"),
                    os.path.join(ROOT, "app", "web", "anwendung.js")], check=True)
    sources = []
    for name in sorted(name for name in os.listdir(ROOT) if name.endswith(".cs")):
        text = open(os.path.join(ROOT, name), encoding="utf-8").read()
        if "NativeLocalization.Gettext" in text or (name.startswith("BridgeDispatcher") and
                                                       name != "BridgeDispatcherContract.cs"):
            sources.append(os.path.join(ROOT, name))
    subprocess.run(["xgettext", "--join-existing", "--language=C#", "--keyword=T",
                    "--keyword=Gettext", *common, *sources], check=True)
    text = open(TARGET, encoding="utf-8").read()
    text = re.sub(r'"POT-Creation-Date: [^"\\n]*\\n"',
                  lambda _: '"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\n"', text)
    with open(TARGET, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)


if __name__ == "__main__":
    run()
