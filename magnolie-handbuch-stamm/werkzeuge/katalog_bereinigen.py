#!/usr/bin/env python3
"""Repair catalog metadata and unambiguous inline-HTML spacing defects."""

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTECTED_TITLES = {
    "License and acknowledgments",
    "In closing",
    "Support Magnolie with a coffee",
    "About the programmer and author of this book",
}
PROTECTED_IDS = {
    "license-and-acknowledgments", "in-closing",
    "support-with-a-coffee", "about-maik-walter",
}
PROTECTED_MESSAGES = set(PROTECTED_TITLES)
with open(os.path.join(ROOT, "web", "inhalt.js"), encoding="utf-8") as _source:
    _text = _source.read()
_pages = json.loads(_text[_text.index("["):_text.index("];", _text.index("[")) + 1])
_marker = "window.HANDBUCH_SEITEN.push("
if _marker in _text:
    _start = _text.index(_marker) + len(_marker)
    _end = _text.index("\n);", _start)
    _pages.extend(json.loads("[" + _text[_start:_end] + "]"))
for _page in _pages:
    if (_page.get("id") in PROTECTED_IDS or
            _page.get("titel") in PROTECTED_TITLES):
        PROTECTED_MESSAGES.update(_page.get(key) for key in ("titel", "inhalt"))
NO_WORD_SPACES = {"ar", "ja", "zh_CN"}
HEADER_FIELDS = (
    ("Project-Id-Version", "Magnolie Handbook 2.0.15"),
    ("Report-Msgid-Bugs-To", "maik3531@gmail.com"),
    ("POT-Creation-Date", "YEAR-MO-DA HO:MI+ZONE"),
    ("PO-Revision-Date", "2026-08-14 00:00+0200"),
    ("Last-Translator", "Magnolie translation team <maik3531@gmail.com>"),
    ("Language-Team", None),
    ("Language", None),
    ("MIME-Version", "1.0"),
    ("Content-Type", "text/plain; charset=UTF-8"),
    ("Content-Transfer-Encoding", "8bit"),
)


def field(block, name):
    match = re.search(r"(?m)^" + re.escape(name) + r'(?:\[\d+\])?\s+(".*")$', block)
    if not match:
        return None, None
    lines = [match.group(1)]
    end = match.end()
    while end < len(block):
        continuation = re.match(r'\n(".*")', block[end:])
        if not continuation:
            break
        lines.append(continuation.group(1))
        end += continuation.end()
    return "".join(ast.literal_eval(line) for line in lines), (match.start(), end)


def quoted_field(name, value):
    if not value:
        return name + ' ""'
    chunks = [value[index:index + 72] for index in range(0, len(value), 72)]
    return name + ' ""\n' + "\n".join(po_quote(chunk) for chunk in chunks)


def po_quote(value):
    return '"' + (value.replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\t", "\\t").replace("\r", "\\r")
                  .replace("\n", "\\n")) + '"'


def replace_field(block, name, value):
    _old, span = field(block, name)
    if not span:
        return block
    return block[:span[0]] + quoted_field(name, value) + block[span[1]:]


def html_spacing(value):
    inline = r"(?:b|i|kbd|span|a)"

    def repair(container):
        text = container.group(0)
        text = re.sub(r"(?<=\w)(<" + inline + r"\b)", r" \1", text)
        return re.sub(r"(</" + inline + r">)(?=\w)", r"\1 ", text)

    return re.sub(r"<(?:p|li)\b[^>]*>.*?</(?:p|li)>", repair, value,
                  flags=re.DOTALL)


def header(language):
    lines = ['msgid ""', 'msgstr ""']
    for key, value in HEADER_FIELDS:
        if key in ("Language-Team", "Language"):
            value = language
        lines.append(po_quote("%s: %s\n" % (key, value)))
    return "\n".join(lines)


def clean_catalog(path, language):
    with open(path, encoding="utf-8") as source:
        blocks = source.read().split("\n\n")
    blocks[0] = header(language)
    cleaned = []
    for index, block in enumerate(blocks):
        if index == 0:
            cleaned.append(block)
            continue
        msgid, _span = field(block, "msgid")
        msgstr, _span = field(block, "msgstr")
        if msgid in PROTECTED_MESSAGES or msgid is None or msgstr is None or block.startswith("#~"):
            cleaned.append(block)
            continue
        new_id = msgid.replace("<b>Today</b>is identified", "<b>Today</b> is identified")
        new_str = msgstr
        if "<b>Today</b>is identified" in msgid:
            new_str = re.sub(r"(</b>)(?=\w)", r"\1 ", new_str, count=1)
        if language not in NO_WORD_SPACES:
            new_id = html_spacing(new_id)
            new_str = html_spacing(new_str)
        if language == "es":
            new_str = new_str.replace("Configuración", "Ajustes")
            new_str = new_str.replace("Verificar ahora", "Comprobar ahora")
        if new_id != msgid:
            block = replace_field(block, "msgid", new_id)
        if new_str != msgstr:
            block = replace_field(block, "msgstr", new_str)
        cleaned.append(block)
    with open(path, "w", encoding="utf-8", newline="\n") as target:
        target.write("\n\n".join(cleaned).rstrip() + "\n")


def main(argv):
    languages = argv[1:] or open(os.path.join(ROOT, "po", "LINGUAS"),
                                 encoding="utf-8").read().split()
    for language in languages:
        clean_catalog(os.path.join(ROOT, "po", language + ".po"), language)


if __name__ == "__main__":
    main(sys.argv)
