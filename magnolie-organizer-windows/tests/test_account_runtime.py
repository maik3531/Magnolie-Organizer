import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile


def load_tool():
    path = Path(__file__).resolve().parents[1] / "werkzeuge/account_runtime.py"
    spec = importlib.util.spec_from_file_location("account_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_control_adapter_preserves_provider_authentication(tmp_path, monkeypatch):
    tool = load_tool()
    cache = tmp_path / "cache"
    cache.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    oauth = b"// Original provider authentication, not implemented by Magnolie.\n"
    specifications = {}
    for name, addon_id in (("tbsync", "tbsync@jobisoft.de"), ("eas", "eas4tbsync@jobisoft.de")):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"version": "5.0.0", "name": "Upstream",
                "browser_specific_settings": {"gecko": {"id": addon_id}}}))
            archive.writestr("background.mjs", 'async function openManagerTab() {\n  if (await focusManagerTab()) return;\n  await browser.tabs.create({ url: "manager/manager.html" });\n}\nasync function focusManagerTab() {\n  const id = await getManagerTabId();\n  return id !== null;\n}\n')
            archive.writestr("modules/eas-provider.mjs", 'const config = { setupPath: "dialogs/setup/setup.html" };')
            archive.writestr("modules/eas/oauth.mjs", oauth)
        data = stream.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        (cache / digest).write_bytes(data)
        specifications[name] = {"id": addon_id, "version": "5.0.0", "sha256": digest, "url": "https://example.invalid/unused"}
    tool.COMPONENTS = specifications
    monkeypatch.setattr(tool.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Cached components must be reused")))
    tool.prepare_extensions(output, cache)
    first = {}
    for name, spec in specifications.items():
        path = output / "magnolie-extensions" / (spec["id"] + ".xpi")
        first[name] = path.read_bytes()
        with zipfile.ZipFile(path) as archive:
            assert archive.read("modules/eas/oauth.mjs") == oauth
            manifest = json.loads(archive.read("manifest.json"))
            assert "Magnolie integration" in manifest["name"]
            assert manifest["version"] == "5.0.0.1"
            assert "MAGNOLIE-CHANGES.txt" in archive.namelist()
    tool.prepare_extensions(output, cache)
    for name, spec in specifications.items():
        assert (output / "magnolie-extensions" / (spec["id"] + ".xpi")).read_bytes() == first[name]


def test_download_rejects_changed_bytes_and_cleans_partial_file(tmp_path, monkeypatch):
    tool = load_tool()
    monkeypatch.setattr(tool.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"changed download"))
    try:
        tool.cached_download({"sha256": "0" * 64, "url": "https://example.invalid/component"}, tmp_path)
    except ValueError as error:
        assert "checksum" in str(error)
    else:
        raise AssertionError("An unverified component was accepted")
    assert list(tmp_path.iterdir()) == []
