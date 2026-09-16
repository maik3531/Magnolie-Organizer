"""Conservative review gate: shared short Scandinavian wording is legitimate."""
import re
import sys
import textwrap
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
from katalog_pruefen import entries


def foreign_passage(norwegian, danish):
    text = re.sub(r"<[^>]*>", " ", norwegian)
    words = re.findall(r"\w+", text)
    # Require prose, not a shared label, command, or technical identifier.
    if len(words) < 60 or len(text) < 400 or not danish:
        return False
    if norwegian == danish:
        return True
    other = re.findall(r"\w+", re.sub(r"<[^>]*>", " ", danish))
    # A translated appendix must not hide an unchanged foreign-language body.
    match = SequenceMatcher(None, words, other, autojunk=False).find_longest_match()
    return match.size >= 60 and len(" ".join(words[match.a:match.a + match.size])) >= 400


def test_shared_short_wording_is_not_foreign():
    for text in ("Bluetooth", "Notater og kontakter", "Ingen data", "15 minutter"):
        assert not foreign_passage(text, text)


def test_long_danish_prose_is_flagged():
    text = (
        "Åbn indstillingerne, og vælg den ønskede side. De gemte oplysninger "
        "forbliver uændrede, når du lukker vinduet. Brug knappen til at gemme "
        "ændringerne, før du fortsætter til næste side. "
    ) * 4
    assert foreign_passage(text, text)
    assert foreign_passage(text + " Et nytt avsnitt på bokmål.", text)
    assert not foreign_passage(text, "En annen tekst på bokmål.")


def test_bokmal_has_no_long_danish_duplicates():
    nb = entries((ROOT / "po/nb.po").read_text())
    da = entries((ROOT / "po/da.po").read_text())
    affected = [key for key, value in nb.items() if foreign_passage(value, da.get(key))]
    assert not affected, f"{len(affected)} Danish passages in Bokmal: " + repr([key[:100] for key in affected])


if __name__ == "__main__":
    nb = entries((ROOT / "po/nb.po").read_text())
    da = entries((ROOT / "po/da.po").read_text())
    for key, value in nb.items():
        if foreign_passage(value, da.get(key)):
            print("SOURCE:", key[:100], "\nBOKMAL:\n", textwrap.fill(value, 120), "\n")
