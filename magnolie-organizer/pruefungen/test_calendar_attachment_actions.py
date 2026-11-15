"""Actual native URI policy, with controlled phone/launcher dependencies only."""
import ast
from pathlib import Path
import unittest


class CalendarAttachmentActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "sozial_oeffnen"]
        if len(functions) != 1:
            raise AssertionError("Exact native social-action function is missing/ambiguous")
        # The unrelated phone normalization never supplies authority to a custom
        # URI. Neither a user book nor the GUI/module startup is loaded here.
        scope = {"_": lambda text: text, "kanonischer_text": lambda text: text.casefold(),
                 "_telefon_schluessel": lambda value, country: ""}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), scope)
        cls.open_uri = staticmethod(scope["sozial_oeffnen"])

    def test_actual_https_policy_matches_attachment_actions(self):
        cases = [
            ("https://example.org/public%20attachment.pdf?part=1#section", True),
            ("https://drive.google.com/public-document", True),
            ("http://example.org/public%20attachment.pdf?part=1#section", False),
            ("https://user:password@example.org/private.pdf", False),
            ("file:///synthetic/not-a-real-file.pdf", False),
            ("javascript:throw('never executed')", False),
            ("webdav://example.org/synthetic.pdf", False),
        ]
        for uri, expected in cases:
            with self.subTest(uri=uri):
                calls = []
                result = self.open_uri("custom", uri, starter=calls.append,
                                       welcher=lambda name: "/synthetic/xdg-open" if name == "xdg-open" else None,
                                       land="DE", aktion_art="url", aktion_ziel=uri)
                self.assertEqual(result["ok"], expected)
                self.assertEqual(calls, [["/synthetic/xdg-open", uri]] if expected else [])


if __name__ == "__main__":
    unittest.main()
