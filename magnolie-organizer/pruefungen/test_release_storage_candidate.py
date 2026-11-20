"""Synthetic storage exports; these fixtures never authorize a product release."""

import base64
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_release_packaging import candidate, gate
import update_signieren as signer
from release_manifest import manifest_schreiben


@pytest.fixture
def synthetic_signer(candidate, monkeypatch, tmp_path):
    root, _, _, _ = candidate
    # Verify the production bootstrap before installing the synthetic test key.
    bootstrap = gate.bootstrap_check(root)
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "synthetic-storage-key.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    monkeypatch.setenv("MAGNOLIE_UPDATE_SIGNING_KEY", str(key_path))
    monkeypatch.setattr(gate, "PUBLIC_KEY", signer.oeffentlicher_text(key))
    verify_signature = gate.signed_manifest
    def signed(data):
        # Only those already cryptographically verified, byte-identical bootstrap
        # bytes use the production key. Every newly generated manifest is verified
        # by the real gate against the fresh synthetic Ed25519 key.
        return ET.fromstring(bootstrap) if data == bootstrap else verify_signature(data)
    monkeypatch.setattr(gate, "signed_manifest", signed)
    calls = []
    def run(command, **_kwargs):
        assert Path(command[1]).name == "update_signieren.py"
        calls.append(command)
        signer.haupt(command[1:])
    monkeypatch.setattr(gate.subprocess, "run", run)
    return calls, key


def contents(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and p.name != ".magnolie-desktop-release.lock"}


def test_storage_requires_exact_approval_before_signing_or_export(candidate, monkeypatch, tmp_path):
    root, directory, approval, _ = candidate
    destination = tmp_path / "export"
    monkeypatch.setattr(gate.subprocess, "run", lambda *_a, **_k: pytest.fail("Unapproved signer call"))
    before = contents(root)
    with pytest.raises(ValueError, match="accept-candidate"):
        gate.promote(root, directory, approval, None, storage_directory=destination)
    assert not destination.exists()
    assert contents(root) == before


def test_storage_exports_signed_registry_release_without_changing_sources(
        candidate, synthetic_signer, tmp_path):
    root, directory, approval, identity = candidate
    destination = tmp_path / "export"
    before, candidate_before = contents(root), contents(directory)
    gate.promote(root, directory, approval, identity, storage_directory=destination)
    record = gate.json_read(directory / "candidate.json")
    exported = gate.storage_candidate_check(destination, record, identity)
    assert len(synthetic_signer[0]) == 3
    assert contents(root) == before
    assert contents(directory) == candidate_before
    assert len(exported["artifacts"]) == 33
    assert not (destination / "storage-spec.json").exists()
    assert destination.stat().st_mode & 0o777 == 0o700
    xml = gate.signed_manifest((destination / "update.xml").read_bytes())
    urls = [node.text for node in xml.iter() if node.text and node.text.startswith("https://")]
    assert len(urls) == 6
    assert all(url.startswith(gate.storage_base("9.8.7")) for url in urls)
    assert not any(tmp_path.glob(".magnolie-desktop-promote-*"))


def test_real_storage_export_is_accepted_by_linux_update_client(
        candidate, synthetic_signer, monkeypatch, tmp_path):
    root, directory, approval, identity = candidate
    destination = tmp_path / "export"
    gate.promote(root, directory, approval, identity, storage_directory=destination)
    # Use the actual client and the actual signed prepare-storage output. The
    # ephemeral fixture key never replaces the production signing key in source.
    source = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
    loader = importlib.machinery.SourceFileLoader("storage_update_client", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    client = importlib.util.module_from_spec(spec)
    loader.exec_module(client)
    xml = (destination / "update.xml").read_text(encoding="utf-8")
    public_key = signer.oeffentlicher_text(synthetic_signer[1])
    verified = client.update_manifest_pruefen(xml, public_key)
    base = gate.storage_base("9.8.7")
    assert verified["url"] == base + "magnolie-organizer_9.8.7_all.deb"
    assert verified["appimage"]["url"] == base + "Magnolie-Organizer-9.8.7-x86_64.AppImage"
    assert verified["handbuch"]["url"] == base + "magnolie-handbuch_9.8.7_all.deb"
    assert not verified["handbuchFehler"]
    assert client.UPDATE_XML == (
        "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/update.xml")
    monkeypatch.delenv("APPIMAGE", raising=False)
    deb = client.update_pruefen(lambda url: xml, public_key)
    assert deb["ok"] and not deb["aktuell"]
    assert deb["url"] == verified["url"]
    monkeypatch.setenv("APPIMAGE", "/synthetic/Magnolie.AppImage")
    appimage = client.update_pruefen(lambda url: xml, public_key)
    assert appimage["ok"] and not appimage["aktuell"]
    assert appimage["url"] == verified["appimage"]["url"]


@pytest.mark.parametrize("kind", ["existing", "source", "candidate", "parent-symlink", "symlink", "dotdot-source"])
def test_storage_rejects_unsafe_or_existing_destination(candidate, monkeypatch, tmp_path, kind):
    root, directory, approval, identity = candidate
    destination = tmp_path / "export"
    if kind == "existing":
        destination.mkdir()
        (destination / "owned.txt").write_text("preserve this synthetic file")
    elif kind == "source":
        destination = root / "export"
    elif kind == "candidate":
        destination = directory / "export"
    elif kind == "parent-symlink":
        alias = tmp_path / "linked-parent"
        alias.symlink_to(tmp_path, target_is_directory=True)
        destination = alias / "export"
    elif kind == "symlink":
        destination.symlink_to(tmp_path / "missing")
    else:
        sibling = tmp_path / "sibling"
        sibling.mkdir()
        destination = sibling / ".." / root.name / "export"
    monkeypatch.setattr(gate.subprocess, "run", lambda *_a, **_k: pytest.fail("Unsafe target reached signer"))
    before = contents(root)
    with pytest.raises(ValueError):
        gate.promote(root, directory, approval, identity, storage_directory=destination)
    assert contents(root) == before
    if kind == "existing":
        assert (destination / "owned.txt").read_text() == "preserve this synthetic file"


@pytest.mark.parametrize("damage", ["alias", "checksum", "signature", "source-url", "extra", "candidate-id"])
def test_storage_checker_rejects_tampering_even_if_export_hashes_are_rewritten(
        candidate, synthetic_signer, tmp_path, damage):
    root, directory, approval, identity = candidate
    destination = tmp_path / "export"
    gate.promote(root, directory, approval, identity, storage_directory=destination)
    record = gate.json_read(directory / "candidate.json")
    exported_path = destination / "storage-candidate.json"
    exported = gate.json_read(exported_path)
    if damage == "alias":
        (destination / "Magnolie-Notes.apk").write_text("SYNTHETIC CHANGED ALIAS")
    elif damage == "checksum":
        (destination / "Magnolie-Organizer-PRUEFSUMMEN.sha256").write_text("0" * 64 + "  wrong.deb\n")
    elif damage in {"signature", "source-url"}:
        xml = ET.parse(destination / "update.xml")
        if damage == "signature":
            xml.getroot().find("signature").text = base64.b64encode(bytes(64)).decode("ascii")
        else:
            # The existing signature format does not sign <source>; the storage
            # checker must still bind its exact URL to this approved source tar.
            xml.getroot().find("source").text = "https://example.invalid/changed.tar.xz"
        xml.write(destination / "update.xml", encoding="UTF-8", xml_declaration=True)
    elif damage == "extra":
        (destination / "unexpected.apk").write_text("SYNTHETIC EXTRA PACKAGE")
    else:
        exported["candidateSha256"] = "0" * 64
    exported["artifacts"] = gate.artifact_map(destination, exported["artifacts"])
    # Rewriting a self-reported export hash must not replace the candidate binding.
    exported_path.write_text(json.dumps(exported))
    with pytest.raises(ValueError):
        gate.storage_candidate_check(destination, record, identity)


def test_atomic_export_does_not_replace_a_raced_in_directory(candidate, synthetic_signer, monkeypatch, tmp_path):
    root, directory, approval, identity = candidate
    destination = tmp_path / "export"
    rename = gate.rename_new_directory
    def raced(source, target):
        target.mkdir()
        rename(source, target)
    monkeypatch.setattr(gate, "rename_new_directory", raced)
    before = contents(root)
    with pytest.raises(FileExistsError):
        gate.promote(root, directory, approval, identity, storage_directory=destination)
    assert destination.is_dir() and not list(destination.iterdir())
    assert contents(root) == before
    assert not any(tmp_path.glob(".magnolie-desktop-promote-*"))


@pytest.mark.parametrize("base", ["http://gitlab.com/", "https://example.invalid/",
    "https://gitlab.com/api/v4/projects/78301901/packages/generic/magnolie-desktop/9.8.6/",
    "https://gitlab.com/api/v4/projects/78301902/packages/generic/magnolie-desktop/9.8.7/"])
def test_manifest_builder_rejects_unapproved_registry_base(candidate, tmp_path, base):
    root, directory, _, _ = candidate
    manifest = tmp_path / "synthetic-update.xml"
    manifest.write_bytes((root / "update.xml").read_bytes())
    before = manifest.read_bytes()
    with pytest.raises(RuntimeError, match="Registry"):
        manifest_schreiben(str(manifest), str(directory / "magnolie-organizer_9.8.7_all.deb"),
            str(directory / "Magnolie-Organizer-9.8.7-x86_64.AppImage"),
            str(directory / "magnolie-handbuch_9.8.7_all.deb"),
            str(directory / "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe"), package_base=base)
    assert manifest.read_bytes() == before
