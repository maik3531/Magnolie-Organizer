#!/usr/bin/env python3
"""Resolve review-update fuzzy entries while preserving stable references."""

import ast
import json
import re
import subprocess
import sys


FACTUAL_MARKERS = (
    "<b>Phone connection</b>",
    "<b>KDE Connect is the only SMS path.</b>",
    "<p>A desktop can request that the phone",
    "<p>A remote deletion is a <b>proposal</b>",
    "<h3>Linux desktop</h3>",
    "<p>If you do not want everyone who uses the computer",
    "<h3>Linux main data and JSON restore</h3>",
    "<p>A backup on the same disk is no help",
    "<p>Use <span class='knopfwort'>Settings ▸ Export</span>",
)

REFERENCE_TARGETS = {
    "6": "installing-the-organizer",
    "34": "the-year-at-a-glance",
    "38": "the-year-at-a-glance",
    "39": "fetching-public-and-school-holidays",
    "40": "appointment-reminders",
    "43": "getting-timely-anniversary-reminders",
    "46": "exporting-data-to-other-programs",
    "47": "exporting-data-to-other-programs",
    "50": "password-protection-and-encryption",
    "53": "the-recycle-bin",
    "55": "reminders-with-password-protection",
    "56": "backing-up-and-restoring",
    "57": "external-backups",
    "58": "printing-and-saving-as-pdf",
}

LANGUAGES = {"zh_CN": "zh-CN", "nb": "no", "hsb": "de"}


def field(block, name):
    match = re.search(r"^" + name + r" (.*(?:\n\".*\")*)", block, re.M)
    if not match:
        return ""
    return "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', match.group(1)))


def replace_field(block, name, value):
    pattern = r"^" + name + r" .*\Z"
    replacement = name + " " + json.dumps(value, ensure_ascii=False)
    return re.sub(pattern, lambda _match: replacement, block, count=1, flags=re.M | re.S)


def translate(language, text):
    protected = []
    pattern = re.compile(
        r"Magnolie Organizer|Magnolie Notes|Magnolienbaum|magnolie-phone/1|"
        r"[a-z]+(?:_[a-z]+)+|[A-Z]+(?:_[A-Z]+)+|phone\.db|AES-256-GCM|PBKDF2-HMAC-SHA-256|"
        r"SHA-256|%LOCALAPPDATA%\\\\Magnolie Organizer\\\\daten\.json|"
        r"Documents\\\\Magnolie Organizer\\\\Sicherungen|"
        r"~/.local/share/magnolie-organizer/daten\.json"
    )

    def hide(match):
        protected.append(match.group(0))
        return "{{%d}}" % (len(protected) - 1)

    hidden = pattern.sub(hide, text)
    command = ["trans", "-brief", "-no-ansi",
               "en:" + LANGUAGES.get(language, language)]
    if language == "de":
        result = subprocess.check_output(command + [hidden], text=True, timeout=120).strip()
        for index, value in enumerate(protected):
            result = result.replace("{{%d}}" % index, value)
        replacements = {
            "Organisatorrolle": "Rolle des Organizers", "Organisator": "Organizer",
            "Veranstalter": "Organizer", "Backups": "Sicherungen", "Backup": "Sicherung",
            "Passwort": "Kennwort", "passwort": "kennwort",
            "bestätigte Filiale": "bestätigten Zweig", "Befestigungen": "Anhänge",
            "Anlagen": "Anhänge", "; Verwenden Sie": "; verwenden Sie",
            "; Ältere": "; ältere", "; Das Entfernen": "; das Entfernen",
            "; Die Rücktaste": "; die Rücktaste", "; Veröffentlichen": "; veröffentlichen",
            "Fotos, und Anhänge": "Fotos und Anhänge",
            "Offline-Vermutungen": "Offline-Rateversuche",
            "Dokumente\\Magnolie Organizer\\Sicherungen": "Documents\\Magnolie Organizer\\Sicherungen",
            "Standardmäßige Sicherungskopien gehen zu": "Sicherungskopien werden standardmäßig abgelegt unter",
            "Verschlüsselte ausgewählte vollständige Archive": "Verschlüsselte Gesamtarchive ausgewählter Daten",
            "Extern ausgewählte Sicherungen sind <b>.magnolie</b> vollständige Archive":
                "Externe Sicherungen ausgewählter Daten sind <b>.magnolie</b>-Gesamtarchive",
            "es kann eine erratene Passphrase nicht kompensieren":
                "sie gleicht eine leicht zu erratende Passphrase nicht aus",
            "Eine App-Sperre stoppt Offline-Rateversuche bezüglich eines kopierten Archivs nicht":
                "Eine Sperrfrist der Anwendung verhindert keine Offline-Rateversuche an einem kopierten Archiv",
        }
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result
    if language in {"ar", "hi"}:
        command[1:1] = ["-e", "bing"]
    pieces = re.split(r"(<[^>]+>)", hidden)
    indexes = [index for index, piece in enumerate(pieces)
               if not piece.startswith("<") and piece.strip() and
               not re.fullmatch(r"\{\{\d+\}\}", piece.strip())]
    payload = "\n".join("{{SEG%d}}%s" % (number, pieces[index])
                        for number, index in enumerate(indexes))
    if language in {"ar", "hi", "ru"}:
        segments, group, size = {}, [], 0
        groups = []
        for number, index in enumerate(indexes):
            addition = len(pieces[index]) + 12
            if group and size + addition > 180:
                groups.append(group); group, size = [], 0
            group.append((number, index)); size += addition
        if group:
            groups.append(group)
        for group in groups:
            group_payload = "\n".join("{{SEG%d}}%s" % (number, pieces[index])
                                      for number, index in group)
            try:
                group_result = subprocess.check_output(
                    command + [group_payload], text=True, timeout=120).strip()
            except subprocess.CalledProcessError:
                continue
            segments.update({int(number): value.strip() for number, value in re.findall(
                r"\{\{SEG(\d+)\}\}(.*?)(?=\{\{SEG\d+\}\}|\Z)", group_result, re.S)})
    else:
        translated = subprocess.check_output(command + [payload], text=True, timeout=120).strip()
        segments = {int(number): value.strip() for number, value in re.findall(
            r"\{\{SEG(\d+)\}\}(.*?)(?=\{\{SEG\d+\}\}|\Z)", translated, re.S)}
    if len(segments) != len(indexes):
        segments = {}
        for number, index in enumerate(indexes):
            piece = pieces[index]
            if re.fullmatch(r"(?:\{\{\d+\}\}|\s)+", piece):
                segments[number] = piece
            else:
                portions = re.split(r"(\{\{\d+\}\})", piece)
                translated_portions = []
                for portion in portions:
                    if not portion or re.fullmatch(r"\{\{\d+\}\}", portion):
                        translated_portions.append(portion)
                        continue
                    words = re.findall(r"\S+\s*", portion)
                    chunks, current = [], ""
                    for word in words:
                        if current and len(current) + len(word) > 100:
                            chunks.append(current); current = ""
                        current += word
                    if current:
                        chunks.append(current)
                    translated_chunks = []
                    for chunk in chunks:
                        try:
                            translated_chunks.append(subprocess.check_output(
                                command + [chunk.strip()], text=True, timeout=120).strip())
                        except subprocess.CalledProcessError:
                            translated_chunks.append(chunk.strip())
                    translated_portions.append(" ".join(translated_chunks))
                segments[number] = "".join(translated_portions)
    for number, index in enumerate(indexes):
        pieces[index] = segments[number]
    result = "".join(pieces)
    if not result or "notranslate" in result or "MAGTOKEN" in result:
        raise RuntimeError("translation service returned an empty result")
    for index, value in enumerate(protected):
        result = result.replace("{{%d}}" % index, value)
    if language == "de":
        replacements = {
            "Organisatorrolle": "Rolle des Organizers",
            "Organisator": "Organizer",
            "Veranstalter": "Organizer",
            "Backups": "Sicherungen",
            "Backup": "Sicherung",
            "Passwort": "Kennwort",
            "passwort": "kennwort",
            "bestätigte Filiale": "bestätigten Zweig",
            "Befestigungen": "Anhänge",
            "Anlagen": "Anhänge",
            "; Verwenden Sie": "; verwenden Sie",
            "; Ältere": "; ältere",
            "; Das Entfernen": "; das Entfernen",
            "; Die Rücktaste": "; die Rücktaste",
            "; Veröffentlichen": "; veröffentlichen",
            "Fotos, und Anhänge": "Fotos und Anhänge",
            "Offline-Vermutungen": "Offline-Rateversuche",
        }
        for old, new in replacements.items():
            result = result.replace(old, new)
    return result


def resolve_references(text):
    def replacement(match):
        target = REFERENCE_TARGETS.get(match.group(1))
        return ("<b data-page='%s' class='knopfwort'></b>" % target) if target else match.group(0)
    return re.sub(r"<b>(\d+)</b>", replacement, text)


def update(path, language):
    with open(path, encoding="utf-8") as source:
        blocks = source.read().split("\n\n")
    changed = 0
    for index, block in enumerate(blocks):
        msgid = field(block, "msgid")
        msgstr = field(block, "msgstr")
        factual = any(marker in msgid for marker in FACTUAL_MARKERS)
        reference_update = "data-page=" in msgid and bool(re.search(r"<b>\d+</b>", msgstr))
        if "fuzzy" not in block.split("\nmsgid", 1)[0] and not factual and not reference_update:
            continue
        if factual:
            msgstr = translate(language, msgid)
        else:
            msgstr = resolve_references(msgstr)
        block = replace_field(block, "msgstr", msgstr)
        block = re.sub(r"^#, (.*)fuzzy, ?", r"#, \1", block, count=1, flags=re.M)
        block = re.sub(r"^#, fuzzy\n", "", block, count=1, flags=re.M)
        blocks[index] = block
        changed += 1
    with open(path, "w", encoding="utf-8", newline="\n") as target:
        target.write("\n\n".join(blocks))
    print("%s: %d entries" % (language, changed))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: fuzzy_uebersetzen.py LANGUAGE CATALOG.po")
    update(sys.argv[2], sys.argv[1])
