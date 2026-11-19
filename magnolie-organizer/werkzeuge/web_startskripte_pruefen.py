#!/usr/bin/env python3
"""Check entry-point scripts against a source manifest or the actual package tree."""
import argparse
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import shlex


class Startskripte(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pfade = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.pfade.append(attrs["src"])


def pruefen(web, manifest=None):
    web = Path(web).resolve(strict=True)
    parser = Startskripte()
    parser.feed((web / "index.html").read_text(encoding="utf-8"))
    if not parser.pfade:
        raise ValueError("No entry-point scripts found")
    eintraege = set()
    if manifest is not None:
        for zeile in Path(manifest).read_text(encoding="utf-8").splitlines():
            felder = shlex.split(zeile, comments=True)
            if len(felder) == 2:
                eintraege.add(tuple(felder))
    for name in parser.pfade:
        relativ = PurePosixPath(name)
        if (not name or relativ.is_absolute() or any(teil in ("", ".", "..") for teil in name.split("/"))
                or any(zeichen in name for zeichen in (":", "?", "#", "%", "\\"))):
            raise ValueError("Invalid entry-point script: " + name)
        # The native host generates the active catalog; its backing English
        # catalog must be present even though i18n-active.js is not a disk file.
        datei = "i18n-en.js" if name == "i18n-active.js" else name
        pfad = (web / datei).resolve(strict=True)
        if not pfad.is_relative_to(web) or not pfad.is_file():
            raise ValueError("Script escapes package web root: " + name)
        if manifest is not None and ("web/" + datei, "usr/share/magnolie-organizer/web") not in eintraege:
            raise ValueError("Script missing from Debian manifest: " + name)
    return len(parser.pfade)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("web", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    print("Entry-point scripts verified:", pruefen(args.web, args.manifest))


if __name__ == "__main__":
    main()
