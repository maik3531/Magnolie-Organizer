#!/usr/bin/env python3
"""Actual OR6 bytes -> isolated helper -> actual projected UI -> synthetic save ACK."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import project_import_helper
import project_ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    parser.add_argument("--ui", type=Path, help="An already generated UI for independent integration review")
    parser.add_argument("--helper-python", default=os.environ.get("MACOS_BETA_IMPORT_PYTHON", sys.executable))
    args = parser.parse_args()
    snapshot = project_ui.inputs()
    with tempfile.TemporaryDirectory(prefix="macOS-file-import-ui-") as directory:
        root = Path(directory)
        ui = args.ui
        if ui is None:
            ui = root / "UI"
            project_ui.project(snapshot, ui)
            helper = ui / "ImportHelper"
        else:
            helper = root / "ImportHelper"
            project_import_helper.project_snapshot(snapshot, helper)
        contract = json.loads((project_ui.REPO / "contracts/or6-native-fixtures.json").read_text())
        proof = contract["files"]["known-values.or6"]
        source = gzip.decompress(base64.b64decode(proof["gzip_base64"], validate=True))
        assert len(source) == proof["bytes"] and hashlib.sha256(source).hexdigest() == proof["sha256"]
        header = {"schema": 1, "format": "lotus", "name": "known-values.or6", "language": "en",
                  "timeZone": "Europe/Berlin", "homeCountry": "DE", "byteLength": len(source), "sha256": proof["sha256"]}
        completed = subprocess.run([args.helper_python, "-I", "-S", "-B", str(helper / "helper.py")],
            input=json.dumps(header).encode() + b"\n" + source, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, timeout=60, cwd=root,
            env=dict(os.environ, PYTHONHOME="/not-the-runtime", PYTHONPATH="/not-an-import-grant"))
        response = json.loads(completed.stdout)
        assert response["ok"] and response["sourceSHA256"] == proof["sha256"] and not completed.stderr
        assert response["parserManifestSHA256"] == hashlib.sha256((helper / "manifest.json").read_bytes()).hexdigest()
        extension = json.loads((project_ui.REPO / "contracts/or6-native-extensions.json").read_text())
        contact_proof = extension["files"]["contact-context-222.or6"]
        contact_source = gzip.decompress(base64.b64decode(contact_proof["gzip_base64"], validate=True))
        assert len(contact_source) == contact_proof["bytes"] and hashlib.sha256(contact_source).hexdigest() == contact_proof["sha256"]
        contact_header = dict(header, name="contact-context-222.or6", byteLength=len(contact_source), sha256=contact_proof["sha256"])
        contact_process = subprocess.run([args.helper_python, "-I", "-S", "-B", str(helper / "helper.py")],
            input=json.dumps(contact_header).encode() + b"\n" + contact_source, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, timeout=60, cwd=root)
        contact_response = json.loads(contact_process.stdout)
        assert contact_response["ok"] and contact_response["sourceSHA256"] == contact_proof["sha256"] and not contact_process.stderr
        fixture = root / "fixture.json"
        fixture.write_text(json.dumps({"response": response, "expected": contract["expected"],
                                       "validContactResponse": contact_response}, ensure_ascii=False))
        command = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            command += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
        command += [str(project_ui.BETA / "tests/file_import.mjs"), str(ui), str(fixture)]
        subprocess.run(command, cwd=project_ui.BETA, check=True, timeout=120)
        print(json.dumps({"or6SourceSHA256": response["sourceSHA256"],
                          "parserManifestSHA256": response["parserManifestSHA256"],
                          "uiApplicationSHA256": hashlib.sha256((ui / "web/anwendung.js").read_bytes()).hexdigest(),
                          "nativePickerValidated": False, "nativePersistenceValidated": False}, sort_keys=True))
    if project_ui.inventory(project_ui.inputs()) != project_ui.inventory(snapshot):
        raise RuntimeError("Sources changed during the file-import UI check")


if __name__ == "__main__":
    main()
