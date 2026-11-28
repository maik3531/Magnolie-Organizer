#!/usr/bin/env python3
"""Generate the shipped catalogues and run the unchanged 20-language setup test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--gettext-prefix", type=Path, required=True)
    p.add_argument("--node-modules", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = str(args.gettext_prefix.resolve() / "usr/bin") + os.pathsep + env["PATH"]
    env["LD_LIBRARY_PATH"] = str(args.gettext_prefix.resolve() / "usr/lib/x86_64-linux-gnu")
    env["NODE_PATH"] = str(args.node_modules.resolve())
    env["MAGNOLIE_MSGFMT"] = str(args.gettext_prefix.resolve() / "usr/bin/msgfmt")
    log = []

    def run(argv, name):
        start = time.monotonic()
        r = subprocess.run(argv, cwd=source, env=env, text=True, capture_output=True)
        rec = {"name": name, "argv": argv, "returncode": r.returncode,
               "duration_seconds": round(time.monotonic() - start, 3),
               "stdout": r.stdout, "stderr": r.stderr}
        log.append(rec)
        (output / "commands.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n")
        if r.returncode:
            print(json.dumps(rec, ensure_ascii=False, indent=2))
            raise SystemExit(r.returncode)
        return r.stdout

    versions = {"msgfmt": run([env["MAGNOLIE_MSGFMT"], "--version"], "msgfmt-version"),
                "node": run(["node", "--version"], "node-version"),
                "python": sys.version,
                "jsdom": run(["node", "-p", "require('jsdom/package.json').version"], "jsdom-version")}
    generated, catalog_sources = [], []
    language_sets = []
    for component, po, web in [
        ("magnolie-organizer", "po", "web"),
        ("magnolie-organizer-windows", "app/po", "app/web"),
    ]:
        root = source / component
        languages = (root / po / "LINGUAS").read_text().split()
        assert len(languages) == len(set(languages)) == 19, languages
        assert sorted(languages) == sorted(f.stem for f in (root / po).glob("*.po"))
        language_sets.append(sorted(languages))
        for lang in languages:
            src, target = root / po / (lang + ".po"), root / web / "i18n" / (lang + ".js")
            generator = root / "werkzeuge/po_zu_js.py"
            run([sys.executable, str(generator), lang, str(src), str(target)], component + ":" + lang)
            catalog_sources.append({"path": str(src.relative_to(source)), "sha256": sha(src)})
            generated.append({"path": str(target.relative_to(source)), "bytes": target.stat().st_size,
                              "sha256": sha(target), "generator_sha256": sha(generator)})
    assert language_sets[0] == language_sets[1]
    native = output / "native-i18n.generated.json"
    native_args = [sys.executable, str(source / "magnolie-organizer-windows/werkzeuge/po_zu_native.py"), str(native)]
    for lang in language_sets[1]:
        native_args.extend([lang, str(source / "magnolie-organizer-windows/app/po" / (lang + ".po"))])
    run(native_args, "native-catalogue-generation")
    tracked_native = source / "magnolie-organizer-windows/app/native-i18n.json"
    tracked_native_bytes = tracked_native.read_bytes()
    tracked_native_hash = sha(tracked_native)
    native_equal = json.loads(native.read_text()) == json.loads(tracked_native.read_text())
    test = source / "magnolie-organizer-windows/tests/setup-holidays.js"
    test_hash_before = sha(test)
    # The original regression uses this parent for mkdtemp; no source edits.
    Path("/tmp/opencode").mkdir(exist_ok=True)
    stdout = run(["node", str(test)], "unchanged-full-setup-holidays")
    assert sha(test) == test_hash_before
    matched = re.fullmatch(r"Setup holidays: (\d+) cross-desktop cases passed; (\d+) languages\.\s*", stdout)
    assert matched, stdout
    assert int(matched[1]) == 88 and int(matched[2]) == 20, matched.groups()
    rebuilt_stdout = None
    if not native_equal:
        # A generated catalogue can differ from the committed cache. Keep both
        # real inputs explicit, run the same original regression, then restore.
        tracked_native.write_bytes(native.read_bytes())
        try:
            rebuilt_stdout = run(["node", str(test)], "unchanged-full-setup-holidays-rebuilt-native")
            assert rebuilt_stdout == stdout
        finally:
            tracked_native.write_bytes(tracked_native_bytes)
        assert sha(tracked_native) == tracked_native_hash
    receipt = {
        "issue": 855, "source_tree": "f4f94a2c2cf73a064448d3208f31d471e150dbe4",
        "test": str(test.relative_to(source)), "test_sha256_before_and_after": test_hash_before,
        "test_source_modified": False, "assertions_or_language_matrix_reduced": False,
        "passed": int(matched[1]), "total": int(matched[1]), "languages": ["en", *language_sets[0]],
        "language_specific_cases": 40, "additional_shared_flow_cases": 48,
        "stdout": stdout.strip(), "versions": versions,
        "native_catalogue_regenerated_semantic_match": native_equal,
        "native_catalogue_tracked_sha256": tracked_native_hash,
        "native_catalogue_regenerated_sha256": sha(native),
        "regenerated_native_regression_stdout": rebuilt_stdout,
        "catalogue_sources": catalog_sources, "generated_web_catalogues": generated,
        "limits": ["JSDOM with controlled native bridge; no native GUI acceptance",
                   "Existing setup-flow regression; not a semantic audit of every translation",
                   "No installable package built, installed or released"]
    }
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    (output / "setup-holidays-all-languages.log").write_text(stdout)
    print(stdout, end="")
    print("Catalogue sets:", len(generated), "generated; native catalogue matches tracked source:", native_equal)
    if rebuilt_stdout:
        (output / "setup-holidays-rebuilt-native-all-languages.log").write_text(rebuilt_stdout)
        print("Also passed with regenerated native catalogue:", rebuilt_stdout.strip())


if __name__ == "__main__":
    main()
