"""Address-only setup regressions; no real profiles or desktop services."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_setup_ui as ui


@pytest.mark.parametrize("regional,expected", [
    ("de_AT.UTF-8", "AT"), ("de_CH", "CH"), ("en_DE", "DE"),
    ("de", ""), ("en", ""), ("C.UTF-8", ""), ("", ""),
])
def test_system_region_not_ui_language(regional, expected):
    assert ui._system_country({"LANG": regional, "LANGUAGE": "de:en"}) == expected


def test_address_locale_precedence():
    assert ui._system_country({"LC_ALL": "en_CH", "LC_ADDRESS": "de_AT", "LANG": "de_DE"}) == "CH"
    assert ui._system_country({"LC_ADDRESS": "de_AT", "LANG": "de_DE"}) == "AT"
    assert ui._system_country({"LC_ALL": "C", "LANG": "de_DE"}) == ""


class Input:
    def __init__(self, text="", choices=None):
        self.text, self.choices, self.active = text, choices, None
        self.focused, self.icon, self.tooltip = False, None, None

    def get_text(self): return self.text
    def set_text(self, text): self.text = text
    def get_child(self): return self
    def get_active_id(self): return self.active
    def set_active(self, index): self.active = None
    def set_active_id(self, value):
        if value not in self.choices: return False
        self.active, self.text = value, value
        return True
    def set_icon_from_icon_name(self, position, icon): self.icon = icon
    def set_icon_tooltip_text(self, position, text): self.tooltip = text
    def grab_focus(self): self.focused = True


def test_import_focus_and_optional_hints_preserve_country():
    # Execute the actual nested handlers with widgets, without launching services.
    tree = ast.parse((ROOT / "bin/magnolie_setup_ui.py").read_text())
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                and node.name in ("address_hints", "select_libreoffice")]
    fields = [Input() for _ in range(5)] + [Input(choices=("DE", "AT", "CH")), Input(choices=("", "DE-SN"))]
    fields[5].set_active_id("AT")
    fields[6].set_active_id("")
    payload = {"givenname": "Ada", "sn": "Example", "street": "Example 1", "postalcode": "123", "l": "City"}
    scope = dict(zip(("first_name", "last_name", "street", "postal_code", "city", "country", "state"), fields))
    scope.update(address_inputs=fields, libreoffice_selected=[False], tr=lambda text: text,
                 read_libreoffice=lambda: {"ok": True, "felder": payload},
                 Gtk=SimpleNamespace(EntryIconPosition=SimpleNamespace(SECONDARY=1)),
                 GERMAN_REGIONS=ui.GERMAN_REGIONS, AUSTRIAN_REGIONS=ui.AUSTRIAN_REGIONS,
                 SWISS_REGIONS=ui.SWISS_REGIONS)
    exec(compile(ast.Module(body=handlers, type_ignores=[]), "handlers", "exec"), scope)
    scope["select_libreoffice"](None)
    assert fields[5].active == "AT"  # An absent import country cannot erase a choice.
    assert fields[6].focused and fields[6].icon
    assert "leave every field empty" in fields[6].tooltip
    fields[6].focused = False
    fields[0].set_text("")
    scope["address_hints"]()
    assert fields[0].icon and not any(field.focused for field in fields)
    payload["c"] = "Switzerland"
    scope["select_libreoffice"](None)
    assert fields[5].active == "CH"
    payload["c"] = "NZ"
    scope["select_libreoffice"](None)
    assert fields[5].active is None and fields[5].text == "NZ"


def test_optional_cue_is_already_localized_in_all_native_catalogs():
    catalog = json.loads((ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/app/native-i18n.json").read_text())
    cue = "Magnolie can use this information when preparing routes and finding local weather. You can leave every field empty."
    sys.path.insert(0, str(ROOT / "werkzeuge"))
    from po_zu_js import katalog_lesen
    assert len(catalog["locales"]) + 1 == 20  # English is the source language.
    for path in (ROOT / "po").glob("*.po"):
        translated = katalog_lesen(str(path))["messages"][cue]
        assert translated and translated != cue, path.name
        native_po = ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/app/po" / path.name
        assert catalog["locales"][path.stem][cue] == katalog_lesen(str(native_po))["messages"][cue]


def test_empty_optional_address_does_not_block_finish(monkeypatch):
    monkeypatch.setattr(ui, "_persist_language", lambda _: None)
    selections = ui._default_selections()
    selections["address"] = dict.fromkeys(selections["address"], "")
    calls = []
    ui._finish_result(lambda *args: calls.append(args), "complete", selections)
    assert calls and calls[0][0] == "complete"
