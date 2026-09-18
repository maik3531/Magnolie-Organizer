"""Read-only catalog/resource checks and narrow merge regression; no Android build."""
import importlib.util
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ui_generator", ROOT / "tools/generate_personal_custom_ui.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class UiBugfixTranslations(unittest.TestCase):
    def test_all_twenty_languages_and_placeholders(self):
        data = generator.UI
        self.assertEqual(len(data["translations"]), 20)
        for locale, values in data["translations"].items():
            self.assertEqual(len(values), len(data["ids"]), locale)
            self.assertTrue(all(values), locale)
            self.assertEqual(re.findall(r"%\([^)]+\)s", values[7]), ["%(tab)s"], locale)
            for value in values[:3]:
                self.assertIn("SMS", value, locale)
            self.assertIn("KDE Connect", values[1], locale)

    def test_android_uses_generic_tab_not_a_desktop_name(self):
        resources = ROOT / "magnolie-notes/app/src/main/res"
        for locale, values in generator.UI["translations"].items():
            folder = "values" if locale == "en" else "values-" + ("zh-rCN" if locale == "zh_CN" else locale)
            strings = {entry.attrib["name"]: entry.text for entry in ET.parse(resources / folder / "strings.xml").getroot() if entry.tag == "string"}
            for index in range(3, 7):
                expected = values[index].replace("'", "\\'").replace('"', '\\"')
                self.assertEqual(strings[generator.UI["ids"][index]], expected, (locale, index))
                self.assertNotIn("%(tab)s", strings[generator.UI["ids"][index]])

    def test_multiline_merge_preserves_other_agents_entries(self):
        other = '#. Another agent\nmsgid "Call-specific UI"\nmsgstr "Untouched"\n'
        existing = 'msgid ""\n"Long "\n"owned message"\nmsgstr ""\n"Old "\n"translation"\n\n' + other
        merged = generator.merge_entry(existing, "Long owned message", "New translation")
        self.assertTrue(merged.endswith(other))
        self.assertEqual(merged.count('msgid "Long owned message"'), 1)
        self.assertEqual(generator.merge_entry(merged, "Long owned message", "New translation"), merged)
        retired = generator.retire_ui('msgid "Memory available / total"\nmsgstr "Keep historical translation"\n\n' + other)
        self.assertIn('#~ msgstr "Keep historical translation"', retired)
        self.assertTrue(retired.endswith(other))

    def test_both_catalogs_contain_new_messages_once(self):
        pattern = r'(?m)^msgid ("[^\n]*"\n(?:"[^\n]*"\n)*)msgstr "[^\n]*"\n(?:"[^\n]*"\n)*'
        for relative in ("magnolie-organizer/po", "magnolie-organizer-windows/app/po"):
            for path in (ROOT / relative).glob("*.po"):
                ids = ["".join(json.loads(line) for line in m[1].splitlines()) for m in re.finditer(pattern, path.read_text())]
                for index in (0, 1, 2, 3, 5, 6, 7):
                    self.assertEqual(ids.count(generator.UI["translations"]["en"][index]), 1, (path, index))


if __name__ == "__main__":
    unittest.main()
