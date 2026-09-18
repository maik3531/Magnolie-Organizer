"""Fast source guard; sms_webkit_probe.py verifies actual native geometry."""
from pathlib import Path
import re
import unittest


class SmsLayoutTests(unittest.TestCase):
    def test_composer_order_and_grid_in_both_frontends(self):
        root = Path(__file__).resolve().parents[2]
        for relative in ("magnolie-organizer/web", "magnolie-organizer-windows/app/web"):
            with self.subTest(web=relative):
                web = root / relative
                js = (web / "anwendung.js").read_text()
                dialog = re.search(r"  function oeffneSmsDialog\(.*?^  }", js, re.M | re.S).group()
                self.assertEqual(dialog.count("knoepfe.append(komponistText, senden, planen);"), 1)
                self.assertIn("komponistText.append(text, zaehler, vorschau);", dialog)
                self.assertIn('const anpassungKnoepfe = el("div", "dialog-knoepfe");', dialog)
                self.assertIn("anpassungKnoepfe.append(angepasstSenden, anpassungAbbrechen);", dialog)
                self.assertNotIn('el("div", "dialog-knoepfe", angepasstSenden', dialog)
                css = (web / "stil.css").read_text()
                composer = re.search(r"^\.sms-komponist \{([^}]+)", css, re.M).group(1)
                content = re.search(r"^\.sms-komponist-text \{([^}]+)", css, re.M).group(1)
                self.assertRegex(composer, r"display:\s*grid;")
                self.assertRegex(composer, r"align-items:\s*stretch;")
                self.assertRegex(composer, r"grid-template-columns:\s*minmax\(0, 1fr\) fit-content\(50%\);")
                self.assertRegex(css, r"\.sms-komponist button\s*\{\s*overflow-wrap:\s*anywhere;\s*\}")
                self.assertRegex(css, r"\.sms-anpassung \{[^}]*overflow-wrap:\s*anywhere;")
                self.assertRegex(content, r"grid-column:\s*1\s*/\s*-1;")
                dialog_css = re.search(r"^\.eingabe-dialog\.sms-dialog \{([^}]+)", css, re.M).group(1)
                self.assertRegex(dialog_css, r"overflow-y:\s*auto;")


if __name__ == "__main__":
    unittest.main()
