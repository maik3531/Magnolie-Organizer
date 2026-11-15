"""Source/translation coverage only; no GTK, provider, book, key or setup run."""
import gettext
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TERMS = (
    "Account access is temporarily unavailable. Automatic updates will wait.",
    "Add this original source without replacing existing permissions. Select the existing organizer contact explicitly. This grants persistent updates; no original contacts will be created or deleted. Automatic updates wait for Wi-Fi.",
    "Allow automatic updates only to the selected original address books, including after restarting. Existing contacts only; no creation or deletion. Updates wait for Wi-Fi. Nothing is selected by default. An empty selection revokes all approvals. You can revoke this permission at any time in Settings.",
    "Allow updates",
    "Notes original source",
    "Original address book",
    "Original contact sources",
    "Revoke",
    "Select the existing organizer contact for this Notes original source explicitly. This grants persistent updates; no original contacts will be created or deleted. Automatic updates wait for Wi-Fi.",
    "Set up account access once in Settings. Automatic updates will wait.",
    "The address book contains an ambiguous source binding.",
    "The contact source permission could not be saved. Automatic updates are paused.",
    "The saved account access is ambiguous. Check the account in Settings.",
    "Update original contact sources",
    "Waiting for Wi-Fi.",
    "Waiting for account access. Automatic contact updates will resume when available.",
    "Waiting for account access. Unlock the system keyring when convenient.",
)


def template_keys(path):
    text = subprocess.check_output(["msgattrib", "--no-wrap", str(path)],
                                   text=True, encoding="utf-8")
    return {json.loads(value) for value in re.findall(r'^msgid (".*")$', text, re.M)} - {""}


class ContactSourceCatalogueTests(unittest.TestCase):
    def test_committed_template_matches_current_source_keys(self):
        with tempfile.TemporaryDirectory(prefix="magnolie-contact-pot-") as directory:
            generated = Path(directory) / "source.pot"
            subprocess.run([sys.executable, "-B", str(ROOT / "werkzeuge/pot_erzeugen.py"),
                            "--output", str(generated)], check=True, capture_output=True)
            expected = template_keys(generated)
        self.assertTrue(set(TERMS) <= expected, "The actual native approval/status source was not extracted")
        self.assertEqual(template_keys(ROOT / "po/magnolie-organizer.pot"), expected,
                         "Committed POT omits current native source labels")

    def test_every_language_compiles_the_original_source_terms(self):
        languages = (ROOT / "po/LINGUAS").read_text(encoding="utf-8").split()
        self.assertEqual(len(languages), len(set(languages)))
        self.assertTrue({"de", "tr"} <= set(languages))
        with tempfile.TemporaryDirectory(prefix="magnolie-contact-catalogues-") as directory:
            for language in languages:
                output = Path(directory) / (language + ".mo")
                subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(output),
                                str(ROOT / "po" / (language + ".po"))], check=True, capture_output=True)
                with output.open("rb") as file:
                    catalogue = gettext.GNUTranslations(file)
                for key in TERMS:
                    value = catalogue.gettext(key)
                    self.assertTrue(value and value != key,
                                    f"{language}: original-source text is missing/untranslated: {key}")
                    if "Notes" in key:
                        self.assertIn("Notes", value, f"{language}: Notes identity must not be renamed")
                if language == "de":
                    consent = catalogue.gettext(TERMS[2]).casefold()
                    for fragment in ("neustart", "keine", "wlan", "leere auswahl", "widerruf", "einstellungen"):
                        self.assertIn(fragment, consent, "German approval text lost an explicit safety condition")


if __name__ == "__main__":
    unittest.main()
