#!/usr/bin/env python3
"""Prepare the pinned, application-local account runtime for Windows packages.

This is a build-time operation. End users need neither an installer for the
helper nor a separately configured Thunderbird profile.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

COMPONENTS = {
    "thunderbird": {
        "version": "155.0",
        "url": "https://archive.mozilla.org/pub/thunderbird/releases/155.0/win64/de/Thunderbird%20Setup%20155.0.exe",
        "sha256": "e1f2e6e73425284f6c374f89d54a814aae1d0f0c2a35abbf984893a6f700cb99",
    },
    "tbsync": {
        "version": "5.3.8",
        "id": "tbsync@jobisoft.de",
        "url": "https://github.com/jobisoft/TbSync/releases/download/v5.3.8/tbsync_5_3_8_beta.xpi",
        "sha256": "a6e59db46deb7ee096c1b2bbbca7b75cdbc2b4a216c0fa0bbd90ae8a243f9a0b",
    },
    "eas": {
        "version": "5.3.11",
        "id": "eas4tbsync@jobisoft.de",
        "url": "https://github.com/jobisoft/EAS-4-TbSync/releases/download/v5.3.11/eas-4-tbsync_5_3_11_beta.xpi",
        "sha256": "6d464761d934209f26e76e615edc2914bc54a10e6b132a0dfc3bd031540098c2",
    },
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cached_download(spec, cache):
    path = cache / spec["sha256"]
    if path.is_file() and digest(path) == spec["sha256"]:
        return path
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            with urllib.request.urlopen(spec["url"], timeout=60) as response:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 300 * 1024 * 1024:
                        raise ValueError("Account runtime download exceeds its limit")
                    stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(temporary) != spec["sha256"]:
            raise ValueError("Account runtime checksum mismatch")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def prepare_extensions(output, cache):
    source = Path(__file__).resolve().parents[1] / "app/account-bridge"
    target = output / "magnolie-extensions"
    target.mkdir(exist_ok=True)
    for name in ("tbsync", "eas"):
        spec = COMPONENTS[name]
        upstream = cached_download(spec, cache)
        with zipfile.ZipFile(upstream) as archive:
            files = {entry.filename: archive.read(entry) for entry in archive.infolist() if not entry.is_dir()}
        manifest = json.loads(files["manifest.json"])
        if manifest["version"] != spec["version"] or manifest["browser_specific_settings"]["gecko"]["id"] != spec["id"]:
            raise ValueError("Unexpected account provider identity")
        manifest["version"] += ".1"
        manifest["name"] = ("TbSync Manager" if name == "tbsync" else "Exchange ActiveSync") + " (Magnolie integration)"
        manifest["browser_specific_settings"]["gecko"].pop("update_url", None)
        files["manifest.json"] = json.dumps(manifest, indent=2).encode()
        adapter = name + "-managed.mjs"
        files["modules/" + adapter] = (source / adapter).read_bytes()
        files["background.mjs"] += ('\nimport "./modules/' + adapter + '";\n').encode()
        if name == "tbsync":
            original = files["background.mjs"].decode()
            old = 'async function openManagerTab() {\n  if (await focusManagerTab()) return;\n  await browser.tabs.create({ url: "manager/manager.html" });\n}'
            if original.count(old) != 1:
                raise ValueError("Unsupported account manager entry point")
            files["background.mjs"] = original.replace(old, "async function openManagerTab() { /* Managed account UI is supplied by Magnolie. */ }").encode()
            original = files["background.mjs"].decode()
            old = "async function focusManagerTab() {\n  const id = await getManagerTabId();"
            if original.count(old) != 1:
                raise ValueError("Unsupported account manager focus entry point")
            files["background.mjs"] = original.replace(old,
                "async function focusManagerTab() {\n  const id = null; // Magnolie owns the account UI.").encode()
        if name == "eas":
            original = files["modules/eas-provider.mjs"].decode()
            old = 'setupPath: "dialogs/setup/setup.html"'
            if original.count(old) != 1:
                raise ValueError("Unsupported provider setup entry point")
            files["modules/eas-provider.mjs"] = original.replace(old, 'setupPath: "magnolie-login.html"').encode()
            for file in ("magnolie-login.html", "magnolie-login.mjs"):
                files[file] = (source / file).read_bytes()
        files["MAGNOLIE-CHANGES.txt"] = (
            "This is a locally integrated variant for Magnolie Organizer.\n"
            "Upstream: " + spec["url"] + "\n"
            "Added a caller-scoped control adapter and a provider-owned sign-in page.\n"
            "Upstream OAuth implementation and registered authentication identity are unchanged.\n"
            "Adapter source: https://github.com/maik3531/Magnolie-Organizer/tree/main/magnolie-organizer-windows/app/account-bridge\n"
            "Modified/additional files are provided under MPL-2.0.\n"
        ).encode()
        temporary = target / (spec["id"] + ".tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, data in sorted(files.items()):
                info = zipfile.ZipInfo(filename, (2026, 9, 22, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        os.replace(temporary, target / (spec["id"] + ".xpi"))
    (output / "MAGNOLIE-NOTICES.txt").write_text(
        "Mozilla Thunderbird 155.0 is redistributed unmodified (MPL-2.0); see license.html.\n"
        "Source: https://archive.mozilla.org/pub/thunderbird/releases/155.0/source/\n"
        "TbSync 5.3.8 and EAS-4-TbSync 5.3.11 are locally integrated variants (MPL-2.0).\n"
        "Their upstream OAuth implementations are unchanged.\n"
        "See MAGNOLIE-CHANGES.txt inside each extension for the exact integration and source links.\n"
        "Upstream sources: https://github.com/jobisoft/TbSync/tree/v5.3.8\n"
        "https://github.com/jobisoft/EAS-4-TbSync/tree/v5.3.11\n"
        "These upstream add-on versions are beta releases compatible with Thunderbird 155.\n",
        encoding="utf-8")


def prepare(output, cache, seven_zip):
    cache.mkdir(parents=True, exist_ok=True)
    marker = output / "runtime.json"
    if marker.is_file() and (output / "thunderbird.exe").is_file():
        if json.loads(marker.read_text(encoding="utf-8")) == COMPONENTS:
            prepare_extensions(output, cache)
            print("Account runtime already prepared.")
            return
    if output.exists():
        raise ValueError("Refusing to replace a different runtime directory: " + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    downloads = {name: cached_download(spec, cache) for name, spec in COMPONENTS.items()}
    with tempfile.TemporaryDirectory(prefix="magnolie-account-runtime-", dir=output.parent) as temporary:
        stage = Path(temporary)
        subprocess.run([seven_zip, "x", "-y", "-o" + str(stage), str(downloads["thunderbird"])],
                       check=True, stdout=subprocess.DEVNULL)
        core = stage / "core"
        if not (core / "thunderbird.exe").is_file() or not (core / "application.ini").is_file():
            raise ValueError("The official archive has an unexpected layout")
        size = sum(file.stat().st_size for file in core.rglob("*") if file.is_file())
        if size > 1500 * 1024 * 1024:
            raise ValueError("Account runtime exceeds its extracted size limit")
        extensions = core / "magnolie-extensions"
        extensions.mkdir()
        for name in ("tbsync", "eas"):
            shutil.copyfile(downloads[name], extensions / (COMPONENTS[name]["id"] + ".xpi"))
        (core / "runtime.json").write_text(json.dumps(COMPONENTS, indent=2) + "\n", encoding="utf-8")
        (core / "MAGNOLIE-NOTICES.txt").write_text(
            "Account helper components (unmodified upstream distributions):\n"
            "Mozilla Thunderbird 155.0 — Mozilla Public License 2.0; see license.html.\n"
            "Source: https://archive.mozilla.org/pub/thunderbird/releases/155.0/source/\n"
            "TbSync 5.3.8 and EAS-4-TbSync 5.3.11 — Mozilla Public License 2.0.\n"
            "Source: https://github.com/jobisoft/TbSync/tree/v5.3.8\n"
            "Source: https://github.com/jobisoft/EAS-4-TbSync/tree/v5.3.11\n"
            "The latter components are upstream beta versions compatible with Thunderbird 155.\n"
            "The account helper is provided with Magnolie; it is not a separate user setup.\n",
            encoding="utf-8")
        core.rename(output)
    prepare_extensions(output, cache)
    print("Prepared application-local account runtime: " + str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".local/share/magnolie-release-tools/account-runtime")
    parser.add_argument("--seven-zip", default=os.environ.get("MAGNOLIE_7Z") or shutil.which("7z") or shutil.which("7zz"))
    args = parser.parse_args()
    if not args.seven_zip:
        raise SystemExit("The release builder requires 7-Zip (MAGNOLIE_7Z). End users do not.")
    prepare(args.output.resolve(), args.cache.resolve(), args.seven_zip)


if __name__ == "__main__":
    main()
