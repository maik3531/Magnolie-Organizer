#!/usr/bin/env python3
"""Regenerate both desktop templates, no-fuzzy merge, and report the manual queue.

Only Organizer POT/PO files are written. No compilation or translations are done.
The report retains the pre-merge catalog snapshot so preservation is auditable.
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import warnings
from pathlib import Path


def catalog(path):
    entries = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
        fields, flags, current = {}, [], None
        obsolete = any(line.startswith("#~") for line in block.splitlines())
        for line in block.splitlines():
            if line.startswith("#~ "):
                line = line[3:]
            if line.startswith("#,"):
                flags.extend(value.strip() for value in line[2:].split(","))
            match = re.match(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(".*")$', line)
            if match:
                current = match[1]
                fields[current] = ast.literal_eval(match[2])
            elif current and line.startswith('"'):
                fields[current] += ast.literal_eval(line)
        if fields.get("msgid"):
            entries.append(dict(fields, flags=flags, obsolete=obsolete))
    return entries


def key(entry):
    return (entry.get("msgctxt"), entry["msgid"], entry.get("msgid_plural"))


def values(entry):
    return {name: value for name, value in entry.items() if name.startswith("msgstr")}


def references(root, messages):
    result = {message: [] for message in messages}
    files = list(root.glob("*.cs")) + list((root / "bin").glob("*.py"))
    if (root / "bin/magnolie-organizer").is_file():
        files.append(root / "bin/magnolie-organizer")
    web = root / ("app/web" if (root / "app").is_dir() else "web")
    files.extend(web / name for name in ("i18n-markers.js", "anwendung.js"))
    for path in sorted(files):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py" or path.name == "magnolie-organizer":
            literals = [(node.value, node.lineno) for node in ast.walk(ast.parse(text))
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        else:
            literals = []
            literal = r'''"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*' '''
            for match in re.finditer(r"(?:" + literal + r")(?:\s*\+\s*(?:" + literal + r"))*", text, re.X):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        value = "".join(ast.literal_eval(part[0]) for part in re.finditer(literal, match[0], re.X))
                except (ValueError, SyntaxError):
                    continue
                literals.append((value, text.count("\n", 0, match.start()) + 1))
        for value, line in literals:
            if value in result:
                ref = f"{path.relative_to(root)}:{line}"
                if ref not in result[value]:
                    result[value].append(ref)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Reuse the original preservation baseline")
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    linux = Path(__file__).resolve().parents[1]
    roots = {"linux": (linux, linux / "po"),
             "windows": (linux.parent / "magnolie-organizer-windows",
                         linux.parent / "magnolie-organizer-windows/app/po")}
    baseline_path = args.report_dir / "before.json"
    if baseline_path.exists() and not args.resume:
        raise SystemExit("Report directory already has a baseline; use a fresh directory")
    if args.resume:
        before = json.loads(baseline_path.read_text(encoding="utf-8"))
    else:
        before = {}
        for platform, (root, po) in roots.items():
            before[platform] = {path.name: catalog(path) for path in sorted(po.glob("*.po"))}
            before[platform]["magnolie-organizer.pot"] = catalog(po / "magnolie-organizer.pot")
            assert len(before[platform]) == 20
        baseline_path.write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"canonical_root": str(linux.parent), "merge": "msgmerge --no-fuzzy --update --backup=none",
              "translations_authored": 0, "compiled": False, "platforms": {}}
    for platform, (root, po) in roots.items():
        command = ["python3", str(root / "werkzeuge/pot_erzeugen.py")]
        subprocess.run(command, check=True)
        pot = catalog(po / "magnolie-organizer.pot")
        required = {key(entry): entry for entry in pot}
        old_keys = {key(entry) for entry in before[platform]["magnolie-organizer.pot"] if not entry["obsolete"]}
        new_keys = required.keys() - old_keys
        refs = references(root, {entry["msgid"] for entry in pot})
        data = {"generator_command": command, "pot_count": len(pot), "new_key_count": len(new_keys),
                "new_keys": [], "per_locale": {}, "per_source": {}, "preservation_failures": [],
                "source_files": {}, "missing": []}
        missing_by_key = {}
        for path in sorted(po.glob("*.po")):
            previous = before[platform][path.name]
            subprocess.run(["msgmerge", "--no-fuzzy", "--update", "--backup=none", str(path),
                            str(po / "magnolie-organizer.pot")], check=True, capture_output=True)
            subprocess.run(["msgfmt", "--check", "--check-format", "-o", "/dev/null", str(path)],
                           check=True, capture_output=True)
            merged = catalog(path)
            active = {key(entry): entry for entry in merged if not entry["obsolete"]}
            assert required.keys() <= active.keys(), path
            for entry in previous:
                if any(values(entry).values()):
                    assert any(key(other) == key(entry) and values(other) == values(entry)
                               for other in merged), (path, entry["msgid"])
            previous_active = {key(entry): entry for entry in previous if not entry["obsolete"]}
            missing = []
            added = []
            for identity, entry in active.items():
                if identity not in required:
                    continue
                assert "fuzzy" not in entry["flags"], (path, entry["msgid"])
                if identity not in previous_active:
                    added.append(entry["msgid"])
                    # Exact obsolete reuse is allowed; fuzzy/English placeholder authoring is not.
                    if not any(key(old) == identity and values(old) == values(entry) for old in previous):
                        assert not any(values(entry).values()), (path, entry["msgid"])
                if not values(entry) or any(not value.strip() for value in values(entry).values()):
                    missing.append(entry["msgid"])
                    missing_by_key.setdefault(identity, []).append(path.stem)
            data["per_locale"][path.stem] = {"active_count": len(active), "missing_count": len(missing),
                                                "added_count": len(added), "missing_keys": sorted(missing),
                                                "added_keys": sorted(added), "fuzzy_count": 0}
        for identity in sorted(required, key=lambda item: (item[0] or "", item[1])):
            entry = required[identity]
            record = {"msgid": entry["msgid"], "msgctxt": entry.get("msgctxt"),
                      "msgid_plural": entry.get("msgid_plural"), "sources": refs[entry["msgid"]],
                      "missing_locales": missing_by_key.get(identity, [])}
            if identity in new_keys:
                data["new_keys"].append(record)
            if identity in missing_by_key:
                data["missing"].append(record)
                for ref in record["sources"]:
                    name = ref.rsplit(":", 1)[0]
                    source = data["per_source"].setdefault(name, {"keys": [], "per_locale": {}})
                    if entry["msgid"] not in source["keys"]:
                        source["keys"].append(entry["msgid"])
                    for locale in record["missing_locales"]:
                        items = source["per_locale"].setdefault(locale, [])
                        if entry["msgid"] not in items:
                            items.append(entry["msgid"])
        for name, source in data["per_source"].items():
            source["count"] = len(source["keys"])
            source["per_locale_counts"] = {locale: len(items) for locale, items in source["per_locale"].items()}
        all_source_names = {ref.rsplit(":", 1)[0] for items in refs.values() for ref in items}
        all_source_names.update(str(path.relative_to(root)) for path in root.glob("*.cs"))
        all_source_names.update(str(path.relative_to(root)) for path in (root / "bin").glob("*.py"))
        for name in sorted(all_source_names):
            path = root / name
            text = path.read_text(encoding="utf-8")
            data["source_files"][name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "classes": re.findall(r"\bclass\s+(\w+)", text)}
        data["missing_unique_count"] = len(missing_by_key)
        data["missing_locale_entries_count"] = sum(len(locales) for locales in missing_by_key.values())
        data["new_keys_without_literal_reference"] = [item for item in data["new_keys"] if not item["sources"]]
        assert not data["new_keys_without_literal_reference"], platform
        report["platforms"][platform] = data
    test_command = ["python3", "-m", "pytest", "-q",
        "magnolie-organizer/pruefungen/test_pot_source_coverage.py",
        "magnolie-organizer-windows/tests/test_windows_pot_source_coverage.py",
        "magnolie-organizer/pruefungen/test_setup_services.py",
        "magnolie-organizer/pruefungen/test_phone_setup_sessions.py",
        "magnolie-organizer/pruefungen/test_phone_bluetooth_setup.py"]
    tested = subprocess.run(test_command, cwd=linux.parent, capture_output=True, text=True)
    report["verification"] = {"command": test_command, "exit_code": tested.returncode,
        "summary": tested.stdout.strip().splitlines()[-1:] or tested.stderr.strip().splitlines()[-1:],
        "source_extraction_gaps": [] if tested.returncode == 0 else ["Source verification failed; inspect tests"],
        "catalog_syntax_and_format_checked": 38,
        "existing_translations_preserved": True,
        "new_fuzzy_entries": 0,
        "completion_gates": "Unmodified; empty translations and stale generated JS/MO/native catalogs still fail until manual translation and compilation.",
        "scope": ["Current desktop web gettext calls", "All Linux bin Python sources",
                  "All Windows root C# sources with native gettext boundaries",
                  "Deferred setup choices and conditional/switch gettext keys",
                  "SetupPhoneServices and PhoneSetupSessions daemon/client error boundaries",
                  "FirstRunSetupServices, FirstRunSetupPhoneServices and FirstRunPhoneStartup",
                  "Linux background service/stopping worker handoff", "Windows background four-key handoff",
                  "DIN letter six-key handoff"],
        "excluded": ["Handbook catalogs/content and protected English pool", "Android resources",
                     "Installer/release manifests and artifacts", "OS/provider diagnostics and raw credentials",
                     "Protocol identifiers and diagnostic-only logs", "Real hardware/GUI execution"]}
    tree = ast.parse((linux / "bin/magnolie-organizer").read_text(encoding="utf-8"))
    boundary = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fehler_deutsch")
    aliases = next(node for node in ast.walk(boundary) if isinstance(node, ast.Dict))
    report["native_error_aliases"] = [{"raw_app_message": source.value,
        "english_msgid": target.args[0].value, "runtime_boundary": "bin/magnolie-organizer:fehler_deutsch",
        "line": source.lineno} for source, target in zip(aliases.keys, aliases.values)]
    report["native_boundary_fixes"] = [
        "Linux setup PhoneService construction: four known storage diagnostics reuse The phone settings are damaged.; unknown errors pass through unchanged.",
        "Linux fehler_deutsch: known app-owned phone/call/personal-sync diagnostics use static English gettext keys; wire messages remain unchanged.",
        "Linux Bluetooth unavailable detail retains the protocol reason; personal-sync operation captions now use the English key.",
        "Windows TelefonCoordinator.ReadFrameWithinAsync: handshake timeout reuses Phone connection cancelled or timed out.; timeout type/control flow unchanged."]
    (args.report_dir / "missing-new-keys.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({platform: {name: data[name] for name in
          ("pot_count", "new_key_count", "missing_unique_count", "missing_locale_entries_count")}
          for platform, data in report["platforms"].items()}, indent=2))
    if tested.returncode:
        raise SystemExit(tested.returncode)


if __name__ == "__main__":
    main()
