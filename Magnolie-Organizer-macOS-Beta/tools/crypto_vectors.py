#!/usr/bin/env python3
"""Generate public synthetic fixtures using the canonical Linux crypto functions, not a reimplementation."""
import ast
import base64
import json
from pathlib import Path
import sys

BETA = Path(__file__).resolve().parents[1]
SOURCE = BETA.parent / "magnolie-organizer/bin/magnolie-organizer"
OUTPUT = BETA / "Tests/BetaCoreTests/Fixtures/desktop-envelopes.json"
FUNCTIONS = {"_schluessel_ableiten", "verschluesseln", "_daten_huelle_felder", "_daten_dek_umschlag",
             "daten_verschluesseln", "daten_entschluesseln"}
CONSTANTS = {"KENNWORT_RUNDEN", "KENNWORT_RUNDEN_MIN", "KENNWORT_RUNDEN_MAX", "KENNWORT_KENNUNG",
             "KENNWORT_VERFAHREN", "DATEN_VERFAHREN", "DATEN_AAD"}


def canonical():
    tree = ast.parse(SOURCE.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
             or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets)]
    if {n.name for n in nodes if isinstance(n, ast.FunctionDef)} != FUNCTIONS:
        raise ValueError("Canonical encryption function set changed.")

    class SyntheticEntropy:
        counter = 0

        def urandom(self, length):
            result = bytes((self.counter + i) % 256 for i in range(length))
            self.counter += length
            return result

    namespace = {"json": json, "base64": base64, "os": SyntheticEntropy(), "_": lambda text: text}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


def vectors():
    native = canonical()
    # Public test values, never real profile data, passwords or keychain contents.
    password = "macOS Beta public fixture \u00e4\U0001f338"
    plain = '{ "termine": [], "aufgaben": [], "kontakte": [], "notizen": [], "future": {"opaque":[1,true,null,"\\u00e4"]}, "format": 7 }\n'
    v1 = native["verschluesseln"](plain, password, salz=bytes(range(16)), nonce=bytes(range(12)))
    v2 = native["daten_verschluesseln"](plain, password, dek=bytes(range(32)), dek_kennung=bytes(range(16)))
    extended = json.loads(v2)
    extended["futureEnvelope"] = {"preserve": [1, True, None]}
    return {"notice": "PUBLIC SYNTHETIC TEST VECTORS. No production secrets. Not evidence of a Swift/macOS run.",
            "password": password, "plain": plain, "v1": v1, "v2": json.dumps(extended, ensure_ascii=True)}


if __name__ == "__main__":
    result = vectors()
    if sys.argv[1:] == ["--write"]:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n")
        print("Generated public Linux crypto fixtures for macOS Beta tests.")
    elif sys.argv[1:] == ["--check"]:
        if json.loads(OUTPUT.read_text()) != result:
            raise SystemExit("Canonical encryption contract changed; review fixtures before regenerating.")
        print("Public macOS Beta fixtures match canonical Linux crypto output.")
    else:
        raise SystemExit("Use --check or --write.")
