"""Exercise only the pure exporter functions, never the Organizer startup."""
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parents[2] / "magnolie-organizer/bin/magnolie-organizer"


def functions(region="system", system="fr_FR", environment=None):
    tree = ast.parse(SOURCE.read_text())
    names = {"datum_kurz", "_xml_sicher", "anschrift_zeilen", "_fodt_brief_kompakt", "fodt_brief"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    namespace = {"datetime": datetime, "_": lambda text: text,
                 "_REGIONAL": {"formatLocale": region}, "os": SimpleNamespace(environ=environment or {}),
                 "locale": SimpleNamespace(LC_TIME=2, getlocale=lambda category: (system, "UTF-8"))}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


def test_supported_numeric_dates_and_system_selection():
    date = datetime(2026, 9, 8)
    expected = {
        "de-DE": "08.09.2026", "en-US": "9/8/2026", "fr-FR": "08/09/2026",
        "es-ES": "8/9/2026", "it-IT": "08/09/2026", "nl-NL": "08-09-2026",
        "pt-PT": "08/09/2026", "ru-RU": "08.09.2026", "cs-CZ": "08.09.2026",
        "pl-PL": "8.09.2026", "hsb-DE": "8.9.2026", "da-DK": "08.09.2026",
        "nb-NO": "08.09.2026", "hi-IN": "8/9/2026", "zh_CN": "2026/9/8",
        "ja-JP": "2026/09/08", "ar-EG": "8\u200f/9\u200f/2026",
        "uk-UA": "08.09.2026", "be-BY": "8.09.2026", "tr-TR": "8.09.2026",
        "en-CA": "2026-09-08", "en-GB": "08/09/2026", "und": "2026-09-08",
    }
    for region, value in expected.items():
        assert functions(region)["datum_kurz"](date) == value, region
    assert functions(system="ja_JP")["datum_kurz"](date) == "2026/09/08"
    assert functions(system=None)["datum_kurz"](date) == "2026-09-08"
    assert functions("fr_FR.UTF-8", "en_US")["datum_kurz"](date) == "08/09/2026"
    assert functions(environment={"LANG": "ja_JP.UTF-8"})["datum_kurz"](date) == "2026/09/08"
    assert functions(environment={"LANG": "ja_JP", "LC_TIME": "en_US", "LC_ALL": "fr_FR"})["datum_kurz"](date) == "08/09/2026"


def test_both_letter_layouts_are_well_formed_and_escape_contact_text():
    namespace = functions("ar-EG")
    for layout in ("compact", "kompakt", "din5008"):
        xml = namespace["fodt_brief"](
            {"anzeigename": "Example & <Family>", "strasse": "Example 1", "ort": "Town"},
            "Sender & Company", datetime(2026, 9, 8), layout)
        root = ET.fromstring(xml)
        content = "".join(root.itertext())
        assert "Example & <Family>" in content
        assert "8\u200f/9\u200f/2026" in content
        assert "Dear Sir or Madam," in content
        assert "Yours sincerely," in content
