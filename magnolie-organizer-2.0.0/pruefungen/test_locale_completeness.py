import ast
import gettext
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PO_DIR = ROOT / "po"
PROTECTED = (
    "Magnolienbaum", "KDE Connect", "Magnolie Notes", "BlueZ", "Bluetooth",
    "WebDAV", "CalDAV", "CardDAV", "HTTPS", "JSON", "CSV",
    "ODS", "PDF", "SMS", "UID", "UFW", "GTK", "WebKit2GTK",
)
ENGLISH_EQUAL_ALLOWLIST = frozenset(PROTECTED)
PLACEHOLDER = re.compile(
    r"%\([A-Za-z_][A-Za-z0-9_]*\)[#0 +\-]*\d*(?:\.\d+)?[diouxXeEfFgGcrs]"
    r"|%(?:\d+\$)?[#0 +\-]*\d*(?:\.\d+)?[diouxXeEfFgGcrs]"
    r"|\{[A-Za-z_][A-Za-z0-9_]*\}"
)
IDENTIFIER = re.compile(
    r"https?://(?:[^\s\"'<>…。，、；：！？）】}]*[A-Za-z0-9/#?=&_%~-])?"
    r"|\.(?:magnolie|json|ics|vcf|ldif|csv|ods|pdf|jpe?g|png|webp|gif|deb|rpm|xml|contact|db)\b"
)


def _po_string(line):
    return ast.literal_eval(line[line.index('"'):])


def _catalog(path):
    entries = {}
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
        lines = block.splitlines()
        if not lines or any(line.startswith("#~") for line in lines):
            continue
        fields = {}
        current = None
        flags = set()
        for line in lines:
            if line.startswith("#,"):
                flags.update(part.strip() for part in line[2:].split(","))
            match = re.match(r"(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+", line)
            if match:
                current = match.group(1)
                fields[current] = _po_string(line)
            elif current and line.startswith('"'):
                fields[current] += ast.literal_eval(line)
        msgid = fields.get("msgid")
        if not msgid:
            continue
        key = (fields.get("msgctxt"), msgid)
        values = [value for name, value in sorted(fields.items()) if name.startswith("msgstr")]
        entries[key] = {
            "flags": flags,
            "plural": fields.get("msgid_plural"),
            "values": values,
        }
    return entries


def _tokens(text):
    return Counter(PLACEHOLDER.findall(text))


def _identifiers(text):
    return Counter(IDENTIFIER.findall(text))


def _sentence_length(text):
    plain = IDENTIFIER.sub("", PLACEHOLDER.sub("", text))
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", plain)) >= 4


def _compiled_catalog(po_path, mo_path):
    subprocess.run(
        ["msgfmt", "--check", "--check-format", "-o", str(mo_path), str(po_path)],
        check=True, capture_output=True, text=True,
    )
    with mo_path.open("rb") as stream:
        return gettext.GNUTranslations(stream)._catalog


def test_gettext_catalogs_are_complete_and_safe():
    source = _catalog(PO_DIR / "magnolie-organizer.pot")
    dormant = {(None, "Language & region")}
    locales = (PO_DIR / "LINGUAS").read_text(encoding="utf-8").split()
    assert set(locales) == {path.stem for path in PO_DIR.glob("*.po")}
    errors = []
    for locale in locales:
        entries = _catalog(PO_DIR / f"{locale}.po")
        missing = source.keys() - entries.keys()
        extra = entries.keys() - source.keys()
        if missing:
            errors.append(f"{locale}: missing keys: {sorted(missing)[:5]}")
        unexpected = extra - dormant
        if unexpected:
            errors.append(f"{locale}: unexpected dormant keys: {sorted(unexpected)[:5]}")
        for key, template in source.items():
            entry = entries.get(key)
            if not entry:
                continue
            label = f"{locale}: {key[1]!r}"
            if "fuzzy" in entry["flags"]:
                errors.append(f"{label} is fuzzy")
            expected_forms = 1 if not template["plural"] else None
            if not entry["values"] or any(not value.strip() for value in entry["values"]):
                errors.append(f"{label} has an empty active translation")
                continue
            if expected_forms and len(entry["values"]) != expected_forms:
                errors.append(f"{label} has unexpected translation forms")
            source_texts = [key[1]] + ([template["plural"]] if template["plural"] else [])
            for index, value in enumerate(entry["values"]):
                source_form = source_texts[min(index, len(source_texts) - 1)]
                valid_tokens = [_tokens(source_form)]
                if template["plural"]:
                    valid_tokens.append(_tokens(template["plural"]))
                if _tokens(value) not in valid_tokens:
                    errors.append(f"{label} changes placeholders in {value!r}")
                if _identifiers(value) != _identifiers(source_form):
                    errors.append(f"{label} changes technical identifiers in {value!r}")
                for token in PROTECTED:
                    if token in " ".join(source_texts) and token not in value:
                        errors.append(f"{label} does not preserve {token!r}")
                if (value == source_form and _sentence_length(source_form)
                        and source_form not in ENGLISH_EQUAL_ALLOWLIST):
                    errors.append(f"{label} is still the English sentence")
        delivered = entries.get((None, "Delivered"), {}).get("values", [""])[0].casefold()
        offline = entries.get((None, "Offline"), {}).get("values", [""])[0].casefold()
        if delivered in {"offline", offline} or offline == "delivered":
            errors.append(f"{locale}: Delivered/Offline state translations are inverted")
    assert not errors, "\n" + "\n".join(errors)


def test_generated_js_and_mo_match_po_catalogs():
    locales = (PO_DIR / "LINGUAS").read_text(encoding="utf-8").split()
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        for locale in locales:
            po_path = PO_DIR / f"{locale}.po"
            generated_js = temporary / f"{locale}.js"
            subprocess.run(
                ["python3", str(ROOT / "werkzeuge" / "po_zu_js.py"), locale,
                 str(po_path), str(generated_js)], check=True,
            )
            assert generated_js.read_bytes() == (ROOT / "web" / "i18n" / f"{locale}.js").read_bytes(), \
                f"web/i18n/{locale}.js is stale"
            expected = _compiled_catalog(po_path, temporary / f"{locale}.mo")
            installed_path = ROOT / "locale" / locale / "LC_MESSAGES" / "magnolie-organizer.mo"
            assert installed_path.is_file(), f"missing generated MO for {locale}"
            with installed_path.open("rb") as stream:
                installed = gettext.GNUTranslations(stream)._catalog
            assert installed == expected, f"generated MO for {locale} is stale"


def test_manual_recovery_reason_has_its_own_translation_context():
    for locale in (PO_DIR / "LINGUAS").read_text(encoding="utf-8").split():
        entries = _catalog(PO_DIR / f"{locale}.po")
        assert entries[("recovery snapshot reason", "Manual")]["values"] == \
            entries[(None, "Custom")]["values"]
    german = _catalog(PO_DIR / "de.po")
    assert german[(None, "Manual")]["values"] == ["Handbuch"]
    assert german[("recovery snapshot reason", "Manual")]["values"] == \
        ["Benutzerdefiniert"]


def test_archive_and_contributor_ui_has_no_hardcoded_visible_strings():
    source = (ROOT / "web" / "anwendung.js").read_text(encoding="utf-8")
    function_names = (
        "aktualisiereContributorWasserzeichen", "zeigeContributorHinweis",
        "zeigeGesamtarchivExport", "zeigeGesamtarchivdialog",
        "bestaetigeSicherungswiederherstellung",
    )
    regions = []
    for name in function_names:
        match = re.search(
            rf"  function {name}\([^)]*\) \{{(?P<body>.*?)(?=\n  function |\n  let |\n  const )",
            source, re.DOTALL,
        )
        assert match, f"UI region {name} not found"
        regions.append(match.group("body"))
    handlers = re.search(
        r"    gesamtarchivExportiert\(nutzlast\) \{(?P<body>.*?)"
        r"\n    sicherungWiederhergestellt\(nutzlast\)", source, re.DOTALL,
    )
    assert handlers, "complete archive result handlers not found"
    regions.append(handlers.group("body"))
    contributor_result = re.search(
        r"    contributorGeprueft\(nutzlast\) \{(?P<body>.*?)\n    vorBeenden\(",
        source, re.DOTALL,
    )
    assert contributor_result, "Contributor result handler not found"
    regions.append(contributor_result.group("body"))

    visible_literal = re.compile(
        r"(?:textContent\s*=|\.title\s*=|\b(?:frage|zettel|knopf)\s*\(|"
        r"\bel\(\s*[\"'][^\"']*[\"']\s*,\s*[\"'][^\"']*[\"']\s*,)"
        r"\s*(?!_|uebersetzt)[\"'][^\"'\n]*[A-Za-zÀ-ž][^\"'\n]*[\"']"
    )
    violations = [match.group(0) for region in regions
                  for match in visible_literal.finditer(region)]
    assert not violations, "hardcoded visible UI strings: " + repr(violations)


def test_contributor_branding_is_not_translatable():
    source = (ROOT / "web" / "anwendung.js").read_text(encoding="utf-8")
    assert source.count('const CONTRIBUTOR_BRANDING = "No valid coffee allowance";') == 1
    assert '_("No valid coffee allowance")' not in source
    assert "No valid subscription" not in source
    template = _catalog(PO_DIR / "magnolie-organizer.pot")
    for branding in ("No valid coffee allowance", "No valid subscription"):
        assert (None, branding) not in template
        for locale in (PO_DIR / "LINGUAS").read_text(encoding="utf-8").split():
            assert (None, branding) not in _catalog(PO_DIR / f"{locale}.po")
