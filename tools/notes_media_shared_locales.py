#!/usr/bin/env python3
"""Reuse the reviewed desktop media labels in Notes without replacing resources (Refs #394)."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "medien_sync_titel": "Photos and videos",
    "medien_sync_aktivieren": "Enable photo and video synchronization",
    "medien_sync_scope_phone": "Only the phone inventory",
    "medien_sync_scope_all": "Entire collection",
    "medien_sync_direction_import": "Phone → PC",
    "medien_sync_zugriff": "Access rights",
    "medien_sync_einstellungen": "Synchronization settings",
    "medien_sync_umfang": "Scope",
    "medien_sync_richtung": "Direction",
    "medien_sync_fotos": "Synchronize photos",
    "medien_sync_videos": "Synchronize videos",
    "medien_sync_modus": "Synchronization",
}


def main():
    catalogs = json.loads((ROOT / "magnolie-organizer-windows/app/native-i18n.json").read_text())["locales"]
    for locale in ["en", *sorted(catalogs)]:
        folder = "values" if locale == "en" else "values-" + ("zh-rCN" if locale == "zh_CN" else locale)
        target = ROOT / "magnolie-notes/app/src/main/res" / folder / "strings.xml"
        text = target.read_text()
        existing = {entry.attrib["name"]: entry.text for entry in ET.fromstring(text).findall("string")}
        additions = []
        for name, key in LABELS.items():
            value = key if locale == "en" else catalogs[locale][key]
            assert value
            android = value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            if name in existing:
                assert existing[name] == android, (locale, name)
            else:
                additions.append(f'    <string name="{name}">{escape(android)}</string>')
        assert text.count("</resources>") == 1
        if additions:
            target.write_text(text.replace("</resources>", "\n".join(additions) + "\n</resources>"))
    print("Notes: twelve shared media labels in all twenty locales; existing entries preserved.")


if __name__ == "__main__":
    main()
