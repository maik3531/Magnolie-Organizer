#!/usr/bin/env python3
"""Project the reviewed, current desktop file codecs into an isolated Mac helper.

The desktop application is parsed, never imported or executed. New global or
local import dependencies require an explicit closure-policy review (#785).
"""
import argparse
import ast
import builtins
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import symtable
import tempfile
import urllib.parse
import urllib.request
import zipfile


BETA = Path(__file__).resolve().parents[1]
REPO = BETA.parent
POLICY = "Magnolie-Organizer-macOS-Beta/ImportHelper/closure-policy.json"
MONOLITH = "magnolie-organizer/bin/magnolie-organizer"
RECURRENCE = "magnolie-organizer/bin/magnolie_recurrence.py"
OR6 = "magnolie-organizer/bin/magnolie_or6.py"
SOCIAL = "magnolie-organizer/bin/magnolie_social_profiles.py"
PHONE = "magnolie-organizer/bin/magnolie_phone_region.py"
PHONE_PIN = "magnolie-organizer/werkzeuge/appimage_bauen.sh"
PHONE_SNAPSHOT = "macos-import-dependencies/phonenumbers.whl"
TZ_PREFIX = "port-adapters/timezones/"
TZ_HASHES = {
    "tzdb-2026egtz.json": "2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c",
    "provenance.json": "b6b926b73620b3ab9ba477195041e52925ee6b12376791e647f70beba6bcc2a0",
    "LICENSE-tzdb.txt": "0613408568889f5739e5ae252b722a2659c02002839ad970a63dc5e9174b27cf",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def safe_path(root, name):
    if not name or Path(name).is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError("Unsafe projection path")
    path = root / name
    for candidate in (root, path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("Symlinked projection path refused")
    return path


def canonical_temporary_root(directory):
    """#793: normalize only a freshly owned TemporaryDirectory before adding children.

    macOS may spell its temporary parent through /var -> /private/var.
    The owned directory itself must remain real; projection roots and child
    paths still pass through the unchanged no-symlink safe_path boundary.
    """
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Temporary projection root must be a real directory")
    return root.resolve(strict=True)


class Inputs:
    def __init__(self, snapshot):
        self.available = snapshot
        self.values = {}

    def read(self, name):
        if name not in self.values:
            if name not in self.available or not isinstance(self.available[name], bytes):
                raise ValueError("Import source snapshot is missing: " + name)
            self.values[name] = self.available[name]
        return self.values[name]


def phone_pin(source):
    values = {}
    for key in ("URL", "SHA"):
        matches = re.findall(r"^PHONENUMBERS_" + key + r"=(\S+)$", source.decode(), re.M)
        if len(matches) != 1:
            raise ValueError("Canonical phonenumbers pin changed")
        values[key] = matches[0]
    parsed = urllib.parse.urlsplit(values["URL"])
    match = re.fullmatch(r"phonenumbers-([0-9]+\.[0-9]+\.[0-9]+)-py2\.py3-none-any\.whl", parsed.path.rsplit("/", 1)[-1])
    if (parsed.scheme != "https" or parsed.netloc != "files.pythonhosted.org" or parsed.query or parsed.fragment
            or not match or not re.fullmatch(r"[0-9a-f]{64}", values["SHA"])):
        raise ValueError("Unsupported canonical phonenumbers pin")
    return {"url": values["URL"], "sha256": values["SHA"], "version": match[1],
            "filename": parsed.path.rsplit("/", 1)[-1]}


def dependency_path(root, pin):
    return safe_path(Path(root), "Magnolie-Organizer-macOS-Beta/.import-dependencies/" + pin["filename"])


def prepare_dependencies(root=REPO, wheel=None):
    """Explicit build-time acquisition; input capture and projection never fetch."""
    root = Path(root)
    pin = phone_pin(safe_path(root, PHONE_PIN).read_bytes())
    target = dependency_path(root, pin)
    if target.exists():
        data = target.read_bytes()
    elif wheel is not None:
        data = Path(wheel).read_bytes()
    else:
        with urllib.request.urlopen(pin["url"], timeout=45) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.netloc != "files.pythonhosted.org":
                raise ValueError("Unexpected dependency download redirect")
            data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024 or sha256(data) != pin["sha256"]:
        raise ValueError("Prepared phonenumbers wheel differs from the desktop pin")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".prepare-", delete=False) as temporary:
            temporary.write(data)
            pending = Path(temporary.name)
        try:
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    return pin


def input_snapshot(root=REPO):
    root = Path(root)
    names = [POLICY, MONOLITH, RECURRENCE, OR6, SOCIAL, PHONE, PHONE_PIN,
             "magnolie-organizer/werkzeuge/po_zu_js.py", "magnolie-organizer/po/LINGUAS",
             "Magnolie-Organizer-macOS-Beta/tools/project_import_helper.py",
             "Magnolie-Organizer-macOS-Beta/ImportHelper/helper.py",
             "Magnolie-Organizer-macOS-Beta/ImportHelper/import_context.py",
             "Magnolie-Organizer-macOS-Beta/ImportHelper/calendar_evidence.py"]
    names += [TZ_PREFIX + name for name in TZ_HASHES]
    languages = safe_path(root, "magnolie-organizer/po/LINGUAS").read_text().split()
    if any(not re.fullmatch(r"[A-Za-z_]+", language) for language in languages):
        raise ValueError("Unexpected catalog language")
    names += ["magnolie-organizer/po/" + language + ".po" for language in languages]
    result = {name: safe_path(root, name).read_bytes() for name in names}
    pin = phone_pin(result[PHONE_PIN])
    try:
        wheel = dependency_path(root, pin).read_bytes()
    except FileNotFoundError as error:
        raise ValueError("Run project_import_helper.py --prepare-dependencies before capturing sources") from error
    if len(wheel) > 8 * 1024 * 1024 or sha256(wheel) != pin["sha256"]:
        raise ValueError("Prepared phonenumbers wheel identity differs")
    result[PHONE_SNAPSHOT] = wheel
    return result


def bound_names(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name)]
    return []


def import_bindings(node):
    if isinstance(node, ast.Import):
        return {item.asname or item.name.split(".")[0]: (item.name, None) for item in node.names}
    if isinstance(node, ast.ImportFrom):
        if node.level or any(item.name == "*" for item in node.names):
            raise ValueError("Relative or wildcard codec import refused")
        return {item.asname or item.name: (node.module, item.name) for item in node.names}
    return {}


def referenced_globals(node, source_name):
    # Symbol tables include decorators, defaults, nested functions and class
    # methods. Python 3.12 inlines comprehensions: their assigned temporary
    # names must not be mistaken for unresolved module dependencies.
    table = symtable.symtable(ast.unparse(node), source_name, "exec")
    found = set()

    def visit(scope):
        found.update(symbol.get_name() for symbol in scope.get_symbols()
                     if symbol.is_global() and symbol.is_referenced()
                     and not (scope is table and symbol.is_assigned()))
        for child in scope.get_children():
            visit(child)
    visit(table)
    return found - set(dir(builtins))


def local_imports(nodes):
    result = set()
    for node in nodes:
        for item in ast.walk(node):
            for module, member in import_bindings(item).values():
                result.add(module + (":" + member if member else ""))
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id in FORBIDDEN_CALLS:
                raise ValueError("Dynamic or interactive codec execution refused")
    return sorted(result)


def closure(source, source_name, roots, adapters):
    tree = ast.parse(source, filename=source_name)
    definitions, imports = {}, {}
    for node in tree.body:
        for name in bound_names(node):
            if name in definitions:
                raise ValueError("Duplicate top-level codec binding: " + name)
            definitions[name] = node
        for name, binding in import_bindings(node).items():
            imports[name] = binding
    pending, seen, selected, used_imports = list(roots), set(), {}, {}
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in adapters:
            continue
        if name in definitions:
            node = definitions[name]
            selected[name] = node
            pending.extend(referenced_globals(node, source_name))
        elif name in imports:
            used_imports[name] = imports[name]
        else:
            raise ValueError("Unreviewed codec global: " + name)
    description = {
        "definitions": sorted(selected),
        "imports": {name: list(value) for name, value in sorted(used_imports.items())},
        "localImports": local_imports(selected.values()),
    }
    return selected, used_imports, description


def emit_module(source, source_name, selected, imports, adapters):
    output = ["# Generated from the current desktop source; do not edit.\n"]
    for name, (module, member) in sorted(imports.items()):
        statement = (f"from {module} import {member}" if member else f"import {module}")
        original = member or module.split(".")[0]
        output.append(statement + (" as " + name if name != original else "") + "\n")
    for name, adapter in sorted(adapters.items()):
        output.append(f"from import_context import {adapter} as {name}\n")
    lines = source.splitlines(keepends=True)
    for node in sorted(set(selected.values()), key=lambda item: item.lineno):
        begin = min([node.lineno, *[item.lineno for item in getattr(node, "decorator_list", [])]])
        output.append(f"\n# {source_name}:{begin}-{node.end_lineno}\n")
        output.extend(lines[begin - 1:node.end_lineno])
        output.append("\n")
    result = "".join(output).encode("utf-8")
    ast.parse(result, filename=source_name + ".projected")
    return result


def encode_tzif(row):
    """Serialize the existing normative model; no timezone arithmetic added."""
    initial, types, history, tail = row
    if initial != 0 or not 1 <= len(types) <= 256 or len(history) % 2:
        raise ValueError("Unsupported normative TZif shape")
    names, type_bytes = bytearray(), bytearray()
    for offset, daylight, abbreviation, standard, universal in types:
        label = abbreviation.encode("ascii") + b"\0"
        if len(names) > 255 or daylight not in (0, 1) or standard not in (0, 1) or universal not in (0, 1):
            raise ValueError("Unsupported normative TZif type")
        type_bytes.extend(struct.pack(">lBB", offset, daylight, len(names)))
        names.extend(label)
    standards = bytes(item[3] for item in types)
    universals = bytes(item[4] for item in types)

    def block(times, size):
        header = b"TZif3" + bytes(15) + struct.pack(">6l", len(types), len(types), 0, len(times), len(types), len(names))
        stamps = b"".join(struct.pack(">q" if size == 8 else ">l", stamp) for stamp, _ in times)
        indexes = bytes(index for _, index in times)
        return header + stamps + indexes + bytes(type_bytes) + bytes(names) + standards + universals
    times = list(zip(history[::2], history[1::2]))
    if any(not 0 <= index < len(types) for _, index in times):
        raise ValueError("Invalid normative TZif transition type")
    # A valid compatibility block precedes the complete 64-bit transition set.
    # Python 3.9+ reads the latter, including its unchanged POSIX future string.
    return block([], 4) + block(times, 8) + b"\n" + tail[6].encode("ascii") + b"\n"


def timezone_outputs(inputs):
    for name, expected in TZ_HASHES.items():
        if sha256(inputs.read(TZ_PREFIX + name)) != expected:
            raise ValueError("Normative timezone input differs: " + name)
    packet = json.loads(inputs.read(TZ_PREFIX + "tzdb-2026egtz.json"))
    if packet.get("schema") != 2 or packet.get("tzdbVersion") != "2026egtz":
        raise ValueError("Normative timezone schema differs")
    rules = [encode_tzif(row) for row in packet["rules"]]
    outputs = {}
    for name, index in packet["zones"].items():
        if not re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name) or ".." in name:
            raise ValueError("Unsafe normative timezone name")
        outputs["zones/" + name] = rules[index]
    outputs["LICENSE-tzdb.txt"] = inputs.read(TZ_PREFIX + "LICENSE-tzdb.txt")
    outputs["timezone-provenance.json"] = inputs.read(TZ_PREFIX + "provenance.json")
    return outputs, sorted(packet["zones"])


def catalogs(inputs):
    recipe_name = "magnolie-organizer/werkzeuge/po_zu_js.py"
    # Reuse only the existing small build-time PO compiler from the captured
    # snapshot. The desktop application and its module graph are never executed.
    namespace = {"__name__": "mac_import_po_recipe"}
    exec(compile(inputs.read(recipe_name), recipe_name, "exec"), namespace)
    languages = inputs.read("magnolie-organizer/po/LINGUAS").decode().split()
    result = {"en": {}}
    with tempfile.TemporaryDirectory(prefix="magnolie-import-catalogs-") as temporary:
        for language in languages:
            if not re.fullmatch(r"[A-Za-z_]+", language):
                raise ValueError("Unexpected catalog language")
            name = "magnolie-organizer/po/" + language + ".po"
            path = Path(temporary) / (language + ".po")
            path.write_bytes(inputs.read(name))
            values = namespace["katalog_lesen"](str(path))["messages"]
            result[language.replace("_", "-").lower()] = {
                key: value for key, value in values.items() if isinstance(value, str) and value
            }
    return json_bytes(result)


def phone_outputs(inputs):
    pin = phone_pin(inputs.read(PHONE_PIN))
    data = inputs.read(PHONE_SNAPSHOT)
    if len(data) > 8 * 1024 * 1024 or sha256(data) != pin["sha256"]:
        raise ValueError("Phonenumbers snapshot differs from the desktop pin")
    outputs, total = {}, 0
    license_name = "phonenumbers-" + pin["version"] + ".dist-info/licenses/LICENSE"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 1024:
            raise ValueError("Unexpected phonenumbers wheel file count")
        for entry in archive.infolist():
            if entry.filename == license_name:
                name = "LICENSE-phonenumbers.txt"
            elif entry.filename.startswith("phonenumbers/") and entry.filename.endswith(".py"):
                name = "vendor/" + entry.filename
            else:
                continue
            if entry.is_dir() or ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Unsafe phonenumbers wheel entry")
            if entry.file_size > 8 * 1024 * 1024 or name in outputs:
                raise ValueError("Unexpected phonenumbers wheel entry size or duplicate")
            safe_path(Path("/projection"), name)
            value = archive.read(entry)
            total += len(value)
            if total > 32 * 1024 * 1024:
                raise ValueError("Phonenumbers wheel expands beyond its limit")
            outputs[name] = value
    if "vendor/phonenumbers/__init__.py" not in outputs or "LICENSE-phonenumbers.txt" not in outputs:
        raise ValueError("Phonenumbers code or license is missing")
    return outputs, pin


def home_countries(source):
    node = next(item for item in ast.parse(source).body if "ISO_ALPHA2" in bound_names(item))
    value = node.value
    if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset"
            and len(value.args) == 1 and isinstance(value.args[0], ast.Call)
            and isinstance(value.args[0].func, ast.Attribute) and value.args[0].func.attr == "split"
            and isinstance(value.args[0].func.value, ast.Constant)
            and isinstance(value.args[0].func.value.value, str) and not value.args[0].args):
        raise ValueError("Canonical country registry shape changed")
    result = value.args[0].func.value.value.split()
    if len(result) != len(set(result)) or any(not re.fullmatch("[A-Z]{2}", value) for value in result):
        raise ValueError("Canonical country registry is invalid")
    return sorted(result)


def build(snapshot):
    inputs = Inputs(snapshot)
    policy = json.loads(inputs.read(POLICY))
    if policy.get("schema") != 1:
        raise ValueError("Unsupported import closure policy")
    outputs, descriptions = {}, {}
    for output_name, rule in policy["projections"].items():
        source = inputs.read(rule["source"]).decode("utf-8")
        selected, imports, description = closure(source, rule["source"], rule["roots"], rule["adapters"])
        if description != rule["reviewed"]:
            raise ValueError("Import parser dependency closure changed: " + output_name)
        outputs[output_name] = emit_module(source, rule["source"], selected, imports, rule["adapters"])
        descriptions[output_name] = description
    for name, rule in policy["copiedModules"].items():
        data = inputs.read(rule["source"])
        if local_imports(ast.parse(data).body) != rule["imports"]:
            raise ValueError("Copied codec dependency closure changed: " + name)
        outputs[name] = data
    for name in ("helper.py", "import_context.py", "calendar_evidence.py"):
        outputs[name] = inputs.read("Magnolie-Organizer-macOS-Beta/ImportHelper/" + name)
    outputs["catalogs.json"] = catalogs(inputs)
    zones, registry = timezone_outputs(inputs)
    outputs.update(zones)
    package, dependency = phone_outputs(inputs)
    outputs.update(package)
    # The recipe itself and policy are part of the original-input proof.
    inputs.read("Magnolie-Organizer-macOS-Beta/tools/project_import_helper.py")
    manifest = {
        "schema": 1, "kind": "magnolie-macos-import-helper", "protocol": 1,
        "sourcePolicy": "current-checkout-files", "nativeValidation": False,
        "maximumInputBytes": 32 * 1024 * 1024, "maximumOutputBytes": 96 * 1024 * 1024,
        "formats": ["ics", "lotus", "vcf", "claws", "ldif", "muell"],
        "timezones": registry, "timezoneVersion": "2026egtz", "projections": descriptions,
        "homeCountries": home_countries(inputs.read(PHONE)), "dependencies": {"phonenumbers": dependency},
        "inputs": {name: {"sha256": sha256(data), "bytes": len(data)} for name, data in sorted(inputs.values.items())},
        "generated": {name: {"sha256": sha256(data), "bytes": len(data)} for name, data in sorted(outputs.items())},
    }
    outputs["manifest.json"] = json_bytes(manifest)
    return outputs, manifest


def project_snapshot(snapshot, target, verify=False):
    outputs, manifest = build(snapshot)
    target = Path(target)
    if verify:
        actual = {str(path.relative_to(target)) for path in target.rglob("*") if path.is_file()}
        if actual != set(outputs):
            raise ValueError("Generated import helper file set differs")
        for name, data in outputs.items():
            if safe_path(target, name).read_bytes() != data:
                raise ValueError("Generated import helper differs: " + name)
    else:
        if target.exists() and any(target.iterdir()):
            raise ValueError("Import helper output must be empty")
        for name, data in outputs.items():
            path = safe_path(target, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return manifest


def project(root, target, verify=False):
    return project_snapshot(input_snapshot(root), target, verify)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--prepare-dependencies", action="store_true")
    args = parser.parse_args()
    if args.prepare_dependencies:
        if args.output or args.verify:
            parser.error("Dependency preparation is a separate step")
        print(json.dumps(prepare_dependencies(args.repo_root), sort_keys=True))
        return
    if args.output is None:
        parser.error("--output is required for projection or verification")
    result = project(args.repo_root, args.output, args.verify)
    print(json.dumps({"generated": len(result["generated"]), "formats": result["formats"],
                      "timezones": len(result["timezones"]), "nativeValidation": False}, sort_keys=True))


if __name__ == "__main__":
    main()
