"""#447: real Git CRLF checkout regression, bounded public inputs only."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location(
    "timezone_recipe", REPO / "magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py")
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)


class CheckoutInputsTests(unittest.TestCase):
    def test_actual_git_checkout_preserves_all_six_bound_inputs(self):
        git = shutil.which("git")
        self.assertIsNotNone(git, "The canonical checkout regression requires existing Git")
        original = recipe.read_inputs(HERE)
        recipe.build_assets(original)
        with tempfile.TemporaryDirectory(prefix="magnolie-timezone-checkout-") as temporary:
            root = Path(temporary)
            empty = root / "empty-config"
            empty.write_bytes(b"")
            hooks = root / "empty-hooks"
            hooks.mkdir()
            env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
            env.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1")
            command = [git, "-c", "core.autocrlf=true", "-c", "core.safecrlf=false",
                       "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + str(hooks),
                       "-c", "core.attributesFile=" + str(empty)]

            def run(*args):
                subprocess.run(command + list(args), cwd=root, env=env, check=True,
                               capture_output=True, timeout=20)

            run("init", "-q")
            for name, data in original.items():
                (root / name).write_bytes(data)
            run("add", "--", *original)
            for name in original:
                (root / name).unlink()
            run("checkout-index", "--all", "--force")
            converted = {name: (root / name).read_bytes() for name in original}
            self.assertNotEqual(hashlib.sha256(converted["resolver.js"]).hexdigest(),
                                hashlib.sha256(original["resolver.js"]).hexdigest(),
                                "The countercase did not perform a real text checkout")
            with self.assertRaisesRegex(ValueError, "Reviewed timezone input differs"):
                recipe.build_assets(converted)

            # Change only the checkout policy; no normalization in the recipe.
            for name, data in original.items():
                (root / name).write_bytes(data)
            (root / ".gitattributes").write_bytes((HERE / ".gitattributes").read_bytes())
            run("add", "--", ".gitattributes", *original)
            for name in original:
                (root / name).unlink()
            run("checkout-index", "--all", "--force")
            checked = {name: (root / name).read_bytes() for name in original}
            self.assertTrue(checked == original, "A bound input changed during checkout")
            assets = recipe.build_assets(checked)
            self.assertEqual(hashlib.sha256(assets["normative-timezones.js"]).hexdigest(),
                             "82a07365a6a4076609dfa3ed7b4eba4125b38b3daf16a5cf8e95278c0cb45c8b")
        self.assertTrue(recipe.read_inputs(HERE) == original, "Caller inputs changed")


if __name__ == "__main__":
    unittest.main()
