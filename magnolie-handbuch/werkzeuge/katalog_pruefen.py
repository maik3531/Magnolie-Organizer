#!/usr/bin/env python3
"""Check a PO catalog for syntax, metadata, and fuzzy entries."""

import os
import re
import subprocess
import sys

from katalog_bereinigen import NO_WORD_SPACES, PROTECTED_MESSAGES, field


def entries(text):
    result = {}
    for block in re.split(r"\n\s*\n", text):
        if any(line.startswith("#~") for line in block.splitlines()):
            continue
        key, _span = field(block, "msgid")
        value, _span = field(block, "msgstr")
        if key:
            if key in result:
                raise ValueError("duplicate msgid: " + key[:100])
            result[key] = value or ""
    return result


def entry_count(text):
    blocks = [block for block in text.split("\n\n") if "msgid " in block]
    return max(0, len(blocks) - 1)


def output(*arguments):
    return subprocess.check_output(arguments, text=True)


def missing_inline_spacing(value):
    for container in re.findall(r"<(?:p|li)\b[^>]*>.*?</(?:p|li)>", value,
                                flags=re.DOTALL):
        if re.search(r"</(?:b|i|kbd|span|a)>[A-Za-zÀ-žА-я]", container):
            return True
        if re.search(r"[A-Za-zÀ-žА-я]<(?:b|i|kbd|span|a)\b", container):
            return True
    return False


def main(argv):
    if len(argv) != 3:
        raise SystemExit("usage: katalog_pruefen.py TEMPLATE.pot LANGUAGE.po")
    template, catalog = argv[1:]
    language = os.path.splitext(os.path.basename(catalog))[0]
    with open(catalog, encoding="utf-8") as catalog_file:
        text = catalog_file.read()
    header = text.split("\n\n", 1)[0]
    required = {
        "Project-Id-Version": "Magnolie Handbook 2.0.19",
        "Language-Team": language,
        "Language": language,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }
    for key, value in required.items():
        if ('"%s: %s\\n"' % (key, value)) not in header:
            raise SystemExit("invalid %s header: %s" % (language, key))
    with open(template, encoding="utf-8") as source:
        expected = entries(source.read())
    actual = entries(text)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    empty = sorted(key for key in expected if key in actual and not actual[key].strip())
    if missing or extra or empty:
        details = ["%s: missing=%d extra=%d untranslated=%d" %
                   (language, len(missing), len(extra), len(empty))]
        details.extend("untranslated: " + key[:120] for key in empty)
        details.extend("missing: " + key[:120] for key in missing)
        raise SystemExit("\n".join(details))
    if language not in NO_WORD_SPACES:
        for block in text.split("\n\n"):
            msgid, _span = field(block, "msgid")
            msgstr, _span = field(block, "msgstr")
            if (msgid not in PROTECTED_MESSAGES and msgstr and
                    missing_inline_spacing(msgstr)):
                raise SystemExit("missing whitespace around inline HTML tag: %s" % catalog)
    subprocess.run(["msgfmt", "--check", "--check-format", "-o", "/dev/null",
                    catalog], check=True)
    fuzzy = entry_count(output("msgattrib", "--only-fuzzy", "--no-obsolete", catalog))
    if fuzzy:
        raise SystemExit("fuzzy catalog: %d entries" % fuzzy)


if __name__ == "__main__":
    main(sys.argv)
