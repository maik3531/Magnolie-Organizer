import gettext
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "magnolie-handbuch-stamm/werkzeuge"))
from katalog_bereinigen import field


def test_temporal_endpoint_is_not_a_route_or_means():
    expected = {
        "de": "Bis einschließlich", "fr": "Jusqu’à", "es": "Hasta", "it": "Fino a",
        "nl": "Tot en met", "pt": "Até", "ru": "До", "cs": "Do", "pl": "Do",
        "hsb": "Hač do", "da": "Til og med", "nb": "Til og med", "hi": "तक",
        "zh_CN": "截至", "ja": "まで", "ar": "حتى", "uk": "До", "be": "Да", "tr": "Bitiş",
    }
    linux = ROOT / "magnolie-organizer-2.0.0"
    windows = ROOT / "Magnolie-Organizer-Windows-2.0.0/app"
    native = json.loads((windows / "native-i18n.json").read_text())["locales"]
    for language, value in expected.items():
        for base in (linux, windows):
            blocks = (base / "po" / (language + ".po")).read_text().split("\n\n")
            values = [field(block, "msgstr")[0] for block in blocks
                      if "#~" not in block and field(block, "msgid")[0] == "Through"]
            assert values == [value], (base, language)
            js = (base / "web/i18n" / (language + ".js")).read_text()
            catalog = json.loads(js.split(",", 1)[1].rsplit(");", 1)[0])
            assert catalog["messages"]["Through"] == value
        assert native[language]["Through"] == value
        translation = gettext.translation("magnolie-organizer", localedir=str(linux / "locale"), languages=[language])
        assert translation.gettext("Through") == value
