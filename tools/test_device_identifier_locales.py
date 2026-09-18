"""Verify every manually authored string at the shipped source boundaries."""
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_twenty_manual_locales_match_both_desktops_and_android():
    data = load(ROOT / "tools/device_identifier_locales.py", "identifier_locales")
    parser = load(ROOT / "magnolie-organizer/werkzeuge/desktop_pot_merge.py", "identifier_catalog")
    native = json.loads((ROOT / "magnolie-organizer-windows/app/native-i18n.json").read_text())
    assert len(data.TEXT) == 20
    for locale, values in data.TEXT.items():
        folder = "values" if locale == "en" else "values-" + ("zh-rCN" if locale == "zh_CN" else locale)
        resources = ET.parse(ROOT / "magnolie-notes/app/src/main/res" / folder / "strings.xml")
        android = {item.attrib.get("name"): item.text for item in resources.findall("string")}
        for name, value in zip(data.IDS, values):
            assert android["device_identifiers_" + name].replace("\\'", "'") == value
        if locale == "en":
            continue
        for directory in ("magnolie-organizer/po", "magnolie-organizer-windows/app/po"):
            entries = {e["msgid"]: e for e in parser.catalog(ROOT / directory / (locale + ".po")) if not e["obsolete"]}
            assert not set(data.TEXT["en"][:2]) & entries.keys(), "Android-only consent labels must not enter desktop POT/PO"
            assert all(entries[k]["msgstr"] == v and "fuzzy" not in entries[k]["flags"] for k, v in zip(data.TEXT["en"][2:], values[2:]))
            script = (ROOT / directory).parent / "web/i18n" / (locale + ".js")
            generated = json.loads(re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\("[^"]+", (.*)\);\s*', script.read_text())[1])["messages"]
            assert not set(data.TEXT["en"][:2]) & generated.keys()
            assert all(generated[k] == v for k, v in zip(data.TEXT["en"][2:], values[2:]))
        assert not set(data.TEXT["en"][:2]) & native["locales"][locale].keys()
        assert all(native["locales"][locale][k] == v for k, v in zip(data.TEXT["en"][2:], values[2:]))
