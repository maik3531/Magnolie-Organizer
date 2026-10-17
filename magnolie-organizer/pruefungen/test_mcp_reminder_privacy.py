"""Actual encrypted primary/projection readback, without a user's profile or services."""
import json
from pathlib import Path
import tempfile

from modul_laden import quellmodul_laden


def test_projection_verification_filters_content_checks_binding_and_revocation():
    product = quellmodul_laden("owned_reminder_privacy", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    with tempfile.TemporaryDirectory(prefix="magnolie-privacy-", dir="/tmp/opencode") as root:
        primary, projection = Path(root) / "profile.json", Path(root) / "projection.json"
        data = {"einstellungen": {"sicherheit": {"erinnernTrotzKennwort": True, "vertraulicheErinnerungen": False}, "erinnerung": {"an": True}},
                "termine": [{"id": "public", "titel": "Owned public", "datum": "2030-01-01"},
                            {"id": "private", "titel": "Owned confidential", "vertraulich": True, "datum": "2030-01-01"}],
                "notizen": [{"text": "Never projected owned note"}], "kontakte": [{"nachname": "Never projected owned contact"}]}
        password = "owned-projection-password"
        def commit():
            primary.write_text(product.verschluesseln(json.dumps(data), password))
        def verify():
            return product.erinnerungsdatenschutz_pruefen(str(projection), profil_pfad=str(primary), kennwort=password)
        def regenerate():
            product.erinnerungsdaten_schreiben(pfad=str(projection), profil_pfad=str(primary), kennwort=password)
        commit()
        assert not verify()["projection_verified"]
        regenerate()
        state = verify()
        assert state == {"encrypted": True, "projection_present": True, "projection_verified": True,
                         "allow_when_locked": True, "include_confidential": False}
        assert [item["id"] for item in json.loads(projection.read_text())["termine"]] == ["public"]
        assert "Never projected" not in projection.read_text() and "Owned confidential" not in projection.read_text()
        # A readable but changed primary cannot authorize yesterday's projection.
        data["termine"][0]["titel"] = "Owned changed title"
        commit()
        assert not verify()["projection_verified"]
        regenerate()
        assert verify()["projection_verified"]
        # Unexpected projection fields and recoverable copies must not be ignored.
        original = projection.read_text()
        extra = json.loads(original); extra["notizen"] = data["notizen"]
        projection.write_text(json.dumps(extra))
        assert not verify()["projection_verified"]
        projection.write_text(original)
        backup = Path(str(projection) + ".bak"); backup.write_text(original)
        assert not verify()["projection_verified"]
        regenerate()
        assert not backup.exists() and verify()["projection_verified"]
        data["einstellungen"]["sicherheit"]["erinnernTrotzKennwort"] = False
        commit()
        assert not verify()["projection_verified"]
        regenerate()
        assert verify()["projection_verified"] and not projection.exists()
        # Plaintext profiles do not need or authorize a second projection either.
        primary.write_text(json.dumps(data))
        assert not verify()["encrypted"] and verify()["projection_verified"]
