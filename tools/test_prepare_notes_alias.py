"""Root-coordinator tests with synthetic approval fixtures, never real approval."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "magnolie-organizer/pruefungen"))
from test_release_packaging import candidate, gate, sources
import prepare_notes_alias as tool


@pytest.mark.parametrize("remote_ok", [True, False])
def test_private_alias_preparation_uses_real_acceptance_gate(candidate, monkeypatch, tmp_path, remote_ok):
    root, directory, approval, identity = candidate
    monkeypatch.setattr(tool, "ROOT", root)
    urls = []
    def remote(url, expected):
        urls.append(url)
        assert expected == gate.artifact_map(directory, ["Magnolie-Notes-1.0.14.apk"])["Magnolie-Notes-1.0.14.apk"]
        if not remote_ok:
            raise ValueError("Remote APK differs")
    monkeypatch.setattr(tool, "remote_hash", remote)
    destination = tmp_path / "alias-output"
    before = sources.inventory(root)
    if remote_ok:
        tool.prepare(directory, approval, identity, destination)
        assert (destination / "Magnolie-Notes.apk").read_bytes() == (directory / "Magnolie-Notes-1.0.14.apk").read_bytes()
        assert sorted(p.name for p in destination.iterdir()) == ["Magnolie-Notes-latest-PRUEFSUMMEN.sha256", "Magnolie-Notes.apk"]
    else:
        with pytest.raises(ValueError, match="Remote APK"):
            tool.prepare(directory, approval, identity, destination)
        assert not destination.exists()
    assert sources.inventory(root) == before
    assert urls == ["https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes-1.0.14.apk"]
