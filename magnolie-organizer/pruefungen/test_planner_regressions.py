"""Keep the shared Planner fix identical across desktop JavaScript copies."""
from pathlib import Path
import ast
from http.server import SimpleHTTPRequestHandler
import re
import unittest
from urllib.parse import urlsplit


class PlannerParityTests(unittest.TestCase):
    def test_http_probe_uses_the_same_active_catalog_as_native_scheme(self):
        driver = Path(__file__).with_name("planner_webkit_probe.py")
        handler = next(node for node in ast.walk(ast.parse(driver.read_text()))
                       if isinstance(node, ast.ClassDef) and node.name == "Handler")
        scope = {"SimpleHTTPRequestHandler": SimpleHTTPRequestHandler, "urlsplit": urlsplit}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(driver), "exec"), scope)
        server = object.__new__(scope["Handler"])
        server.directory = "/synthetic/web"
        self.assertEqual(server.translate_path("/i18n-active.js?probe=1"), "/synthetic/web/i18n/de.js")
        self.assertEqual(server.translate_path("/index.html"), "/synthetic/web/index.html")

    def test_shared_planner_functions(self):
        root = Path(__file__).resolve().parents[2]
        sources = [(root / relative).read_text() for relative in (
            "magnolie-organizer/web/anwendung.js",
            "magnolie-organizer-windows/app/web/anwendung.js")]
        for name in ("icsRuntime", "icsBasisExpansion", "terminVerzeichnis", "termineAm", "planerFeiertagVerzeichnis",
                     "feiertageAm", "planerSuchTreffer", "zeichnePlaner", "wechsel", "zeichneRegister",
                     "planerMonatsModell", "planerKalenderModell", "planerOdsNutzlast",
                     "planerMonatsDruckSeite", "oeffnePlanerDruckvorschau"):
            with self.subTest(function=name):
                bodies = [re.search(r"^  function " + name + r"\(.*?^  }", source, re.M | re.S)
                          for source in sources]
                self.assertTrue(all(bodies), name)
                self.assertEqual(bodies[0].group(), bodies[1].group(), name)
        for source in sources:
            for obsolete in ("icsPlanerTage", "planerSerienTage", "planner-view-start", "cancel-planner"):
                self.assertNotIn(obsolete, source)


if __name__ == "__main__":
    unittest.main()
