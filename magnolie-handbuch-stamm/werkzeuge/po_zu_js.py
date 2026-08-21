#!/usr/bin/env python3
"""Compile a checked PO catalog deterministically for WebKit."""

import gettext
import json
import os
import subprocess
import sys
import tempfile


def read_catalog(po_path):
    with tempfile.TemporaryDirectory(prefix="magnolie-po-") as directory:
        mo_path = os.path.join(directory, "catalog.mo")
        subprocess.run(["msgfmt", "--check", "--check-format", "-o", mo_path,
                        po_path], check=True)
        with open(mo_path, "rb") as source:
            translation = gettext.GNUTranslations(source)
    messages = {}
    for key, value in translation._catalog.items():
        if key and isinstance(key, str) and isinstance(value, str):
            messages[key] = value
    return {"messages": messages}


def main(argv):
    if len(argv) != 4:
        raise SystemExit("usage: po_zu_js.py LANGUAGE SOURCE.po TARGET.js")
    language, source, target = argv[1:]
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    text = "window.MagnolieI18n.registerCatalog(%s, %s);\n" % (
        json.dumps(language, ensure_ascii=False),
        json.dumps(read_catalog(source), ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")))
    with open(target, "w", encoding="utf-8", newline="\n") as output:
        output.write(text)


if __name__ == "__main__":
    main(sys.argv)
