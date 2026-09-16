"""Handbook-only letter contract; application exporters have separate tests."""
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
from katalog_pruefen import entries
from pot_erzeugen import handbook_data


class Tags(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, tuple(sorted(attrs))))

    def handle_data(self, text):
        self.text.append(text)


def test_letter_page_documents_actual_default_and_geometry_in_all_languages():
    data = handbook_data()
    general = next(page for page in data["pages"] if page["id"] == "writing-letters")["inhalt"]
    variants = data["variants"]["writing-letters"]
    windows = variants["en"]
    for source in (general, windows):
        for claim in ("default for new or unset preferences", "45 mm reserved", "Form A reserves 27 mm",
                      "saved template choice is preserved", "single small return line",
                      "same left-hand address field", "no separate sender block",
                      "85 by 45 mm", "20 mm from the left", "printing at 100%",
                      "not DIN-certified", "Oversized addresses are rejected"):
            assert claim in source, claim
        assert "Compact sender line (default)" not in source
        for language in (ROOT / "po/LINGUAS").read_text().split():
            catalog = entries((ROOT / "po" / (language + ".po")).read_text())
            value = catalog[source]
            assert value and value != source, language
            original, translated = Tags(source), Tags(value)
            assert Counter(translated.tags) == Counter(original.tags), language
            assert Counter(re.findall(r"\d+", "".join(translated.text))) == \
                Counter(re.findall(r"\d+", "".join(original.text))), language
            assert "DIN 5008 Form B" in value and "LibreOffice Writer" in value
            if source == windows:
                assert "ODT" in value
                assert variants["zh-cn" if language == "zh_CN" else language] == value


def hindi_prose_errors(catalog):
    # Ordinary English prose is not a brand, command, filename or protocol ID.
    forbidden = set("""data local current default file folder window source entries only
        system password phone text export backup service archive note notebook date
        selected visible hidden display paired selected scope shared tree next install
        recipient sender letterhead preview readonly contains supports requires means
        notifications printouts permission permissions connection protection controls
        optional state restore delete deleted saving saved failure failed months years
        title heading range rows choose click first last total fields limit maximum
        numbers incoming outgoing computer desktop settings already grants grant
        appointments anniversaries tasks notes changes updated copied source""".split())
    errors = []
    for key, value in catalog.items():
        for text in Tags(value).text:
            text = text.strip()
            if not text:
                continue
            if not re.search(r"[\u0900-\u097f]", text) and (
                text.startswith(("/", "~", "$", "%", "--", "sudo ", "adb ", "magnolie-",
                                 "man ", "rpmbuild ", "chmod ", "sha256sum ", "Get-FileHash "))
                or re.fullmatch(r"[\w.%:+*\\/-]+", text) and any(c in text for c in "._/\\")
            ):
                continue
            for literal in ("No valid coffee allowance", "Microsoft Print to PDF", "Magnolie Notes",
                            "Standard Notes", "Samsung Notes", "Secret Service", "Google Drive", "Evolution Data Server",
                            "Google Keep", "DIN 5008 Form B", "format 2", "Page Up", "Page Down",
                            "Windows Contacts", "LibreOffice Writer", "Personal Sync"):
                text = text.replace(literal, "")
            # Literal CLI metavariables, environment names and Lotus column IDs.
            text = re.sub(r"\b(?:FILE|DISPLAY)\b|START DATE TIME|END DATE TIME", "", text)
            text = re.sub(r"(?m)^\s*sudo apt install [^\n]+", "", text)
            text = re.sub(r"\{(?:first|last|total)\}|\b(?:ar|be|cs|da|de|en|es|fr|hi|hsb|it|ja|nb|nl|pl|pt|ru|tr|uk|zh_CN|system)\b", "", text)
            text = re.sub(r"(?:[~$%\w{}:.-]+[/\\])+[\w.%+*\\/-]+", "", text)
            words = {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", text)}
            bad = words & forbidden
            if bad:
                errors.append((key[:70], sorted(bad), text))
    return errors


def test_hindi_active_catalog_has_no_old_english_sentence_fragments():
    catalog = entries((ROOT / "po/hi.po").read_text())
    assert not hindi_prose_errors(catalog)
    assert hindi_prose_errors({"probe": "<p>Saved data stays local.</p>"})
    assert catalog["Conflicts and attachments"] == "टकराव और संलग्नक"
    assert catalog["Forward one spread"] == "अगले दो पृष्ठ खोलें"


def test_reviewed_ui_quotes_and_permission_words_do_not_regress():
    for language, forbidden in {
        "zh_CN": (">Tree<", ">Shared<", "File ▸ Export", "Magolienbaum"),
        "ja": (">Downloads<", "SMS text was adjusted:", "1 SMS parts"),
        "be": (">Files<", ">Downloads<", ">Install<", ">Next<", ">Scope<",
               "Android Settings ▸ Apps", "1 SMS parts", "Незалежны грант", "Надмагіллі"),
        "ru": ("Независимый грант", "Надгробия", "заметкиMagnolienbaum"),
        "uk": ("Незалежний грант", "Надгробки", "нотаткиMagnolienbaum"),
    }.items():
        values = entries((ROOT / "po" / (language + ".po")).read_text()).values()
        for value in values:
            for fragment in forbidden:
                assert fragment not in value, (language, fragment)
