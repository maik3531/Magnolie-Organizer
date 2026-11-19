"""#447: portable cold asset recipe; no UI, native provider or account startup."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "port-adapters/timezones"
if not SHARED.exists():
    SHARED = ROOT / "werkzeuge/timezones"
EXPECTED_BOOTSTRAP = "82a07365a6a4076609dfa3ed7b4eba4125b38b3daf16a5cf8e95278c0cb45c8b"


def recipe():
    path = ROOT / "werkzeuge/zeitzonen_erzeugen.py"
    if not path.is_file():
        raise AssertionError("The canonical cold-source timezone recipe is missing")
    spec = importlib.util.spec_from_file_location("normative_timezone_recipe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NormativeTimezoneRecipeTests(unittest.TestCase):
    def test_assets_match_the_existing_reviewed_port_bootstrap_vector(self):
        module = recipe()
        assets = module.build_assets(module.read_inputs(SHARED))
        self.assertEqual(set(assets), {"normative-timezones.js", "timezones/tzdb-2026egtz.json",
                                      "timezones/provenance.json", "timezones/LICENSE-tzdb.txt"})
        self.assertEqual(hashlib.sha256(assets["normative-timezones.js"]).hexdigest(), EXPECTED_BOOTSTRAP)
        for name in ("tzdb-2026egtz.json", "provenance.json", "LICENSE-tzdb.txt"):
            self.assertEqual(assets["timezones/" + name], (SHARED / name).read_bytes())

    def test_every_bound_input_is_required_and_tamper_is_rejected(self):
        module = recipe()
        original = module.read_inputs(SHARED)
        for name in module.INPUT_SHA256:
            with self.subTest(name=name):
                changed = dict(original)
                changed[name] += b" "
                with self.assertRaises(ValueError):
                    module.build_assets(changed)
                missing = dict(original)
                del missing[name]
                with self.assertRaises(ValueError):
                    module.build_assets(missing)

    def test_recipe_rejects_symlinked_input_before_reading_it(self):
        module = recipe()
        with tempfile.TemporaryDirectory(prefix="magnolie-tz-recipe-") as temporary:
            source = Path(temporary)
            for name in module.INPUT_SHA256:
                (source / name).symlink_to(SHARED / name)
            with self.assertRaises(ValueError):
                module.read_inputs(source)

    def test_cold_embedded_source_layout_uses_the_same_exact_bytes(self):
        module = recipe()
        with tempfile.TemporaryDirectory(prefix="magnolie-tz-cold-") as temporary:
            root = Path(temporary) / "shared/magnolie-organizer"
            source = root / "werkzeuge/timezones"
            source.mkdir(parents=True)
            for name, data in module.read_inputs(SHARED).items():
                (source / name).write_bytes(data)
            self.assertEqual(module.source_directory(root), source)
            assets = module.build_assets(module.read_inputs(module.source_directory(root)))
            self.assertEqual(hashlib.sha256(assets["normative-timezones.js"]).hexdigest(), EXPECTED_BOOTSTRAP)

    def test_present_but_bad_primary_source_never_silently_falls_back(self):
        module = recipe()
        with tempfile.TemporaryDirectory(prefix="magnolie-tz-primary-") as temporary:
            root = Path(temporary) / "magnolie-organizer"
            primary = root.parent / "port-adapters/timezones"
            embedded = root / "werkzeuge/timezones"
            primary.mkdir(parents=True)
            embedded.mkdir(parents=True)
            for name, data in module.read_inputs(SHARED).items():
                (embedded / name).write_bytes(data)
            self.assertEqual(module.source_directory(root), primary)
            with self.assertRaises((FileNotFoundError, ValueError)):
                module.read_inputs(module.source_directory(root))

    def test_failed_generation_does_not_replace_existing_output(self):
        module = recipe()
        with tempfile.TemporaryDirectory(prefix="magnolie-tz-output-") as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "web"
            source.mkdir()
            output.mkdir()
            existing = output / "normative-timezones.js"
            existing.write_bytes(b"previous checked output")
            for name, data in module.read_inputs(SHARED).items():
                (source / name).write_bytes(data)
            (source / "resolver.js").write_bytes(b"invalid reviewed input")
            with self.assertRaises(ValueError):
                module.generate(source, output)
            self.assertEqual(existing.read_bytes(), b"previous checked output")
            self.assertEqual(set(output.iterdir()), {existing})

    def test_cli_check_validates_without_materializing_assets(self):
        module = recipe()
        with tempfile.TemporaryDirectory(prefix="magnolie-tz-check-") as temporary:
            output = Path(temporary) / "web"
            module.main(["--source", str(SHARED), "--output", str(output), "--check"])
            self.assertFalse(output.exists())

    def test_linux_cold_source_copy_contains_bound_inputs_not_stale_outputs(self):
        with tempfile.TemporaryDirectory(prefix="magnolie-tz-projection-") as temporary:
            base = Path(temporary)
            source = base / "canonical/magnolie-organizer"
            (source / "werkzeuge").mkdir(parents=True)
            for name in ("release_sources.py", "source_selection.py", "zeitzonen_erzeugen.py"):
                (source / "werkzeuge" / name).write_bytes((ROOT / "werkzeuge" / name).read_bytes())
            shared = source.parent / "port-adapters/timezones"
            shared.mkdir(parents=True)
            for name, data in recipe().read_inputs(SHARED).items():
                (shared / name).write_bytes(data)
            (source / "web/timezones").mkdir(parents=True)
            (source / "web/normative-timezones.js").write_text("stale bootstrap")
            (source / "web/timezones/provenance.json").write_text("stale manifest")
            cold = base / "cold/magnolie-organizer"
            subprocess.run([sys.executable, "-B", str(source / "werkzeuge/release_sources.py"),
                            "copy", str(source), str(cold)], check=True, capture_output=True)
            self.assertFalse((cold / "web/normative-timezones.js").exists())
            self.assertFalse((cold / "web/timezones").exists())
            self.assertEqual(set(path.name for path in (cold / "werkzeuge/timezones").iterdir()),
                             set(recipe().INPUT_SHA256))
            subprocess.run([sys.executable, "-B", "-c",
                            "import sys; from pathlib import Path; "
                            "sys.path.insert(0,sys.argv[1]); import release_sources as s; "
                            "r={'magnolie-organizer/'+str(p):s.source_identity(f) "
                            "for p,f in s.projection_files(Path(sys.argv[2]))}; "
                            "s.verify_projection(r,'magnolie-organizer',Path(sys.argv[3]))",
                            str(source / "werkzeuge"), str(source), str(cold)],
                           check=True, capture_output=True)
            output = cold / "web"
            subprocess.run([sys.executable, "-I", "-B", str(cold / "werkzeuge/zeitzonen_erzeugen.py"),
                            "--output", str(output)], check=True, capture_output=True)
            self.assertEqual(hashlib.sha256((output / "normative-timezones.js").read_bytes()).hexdigest(),
                             EXPECTED_BOOTSTRAP)
            # A damaged primary must fail before creating a second projection.
            (shared / "resolver.js").write_text("changed")
            rejected = base / "rejected"
            result = subprocess.run([sys.executable, "-B", str(source / "werkzeuge/release_sources.py"),
                                     "copy", str(source), str(rejected)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(rejected.exists())

    def test_existing_linux_build_entrypoints_generate_normative_assets(self):
        for relative in ("debian/rules", "rpm/magnolie-organizer.spec",
                         "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json",
                         "werkzeuge/appimage_bauen.sh"):
            with self.subTest(entrypoint=relative):
                self.assertIn("werkzeuge/zeitzonen_erzeugen.py", (ROOT / relative).read_text())
        deb = (ROOT / "debian/install").read_text()
        rpm = (ROOT / "rpm/magnolie-organizer.spec").read_text()
        for name in ("normative-timezones.js", "timezones/tzdb-2026egtz.json",
                     "timezones/provenance.json", "timezones/LICENSE-tzdb.txt"):
            self.assertIn("web/" + name, deb)
            self.assertIn("web/" + name, rpm)


if __name__ == "__main__":
    unittest.main()
