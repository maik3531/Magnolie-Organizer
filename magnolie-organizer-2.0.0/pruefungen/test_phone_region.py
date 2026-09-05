import importlib.util
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("magnolie_phone_region", ROOT / "bin" / "magnolie_phone_region.py")
region = importlib.util.module_from_spec(spec)
spec.loader.exec_module(region)


def test_shared_phone_region_vectors():
    vectors = json.loads((ROOT / "contracts" / "phone-region-vectors.json").read_text())
    for vector in vectors["vectors"]:
        result = region.analyze(vector["number"], vector["number_status"],
                                vector["home_country"], vector["language"])
        assert result["phone_origin_status"] == vector["status"]
        if vector["status"] == "known":
            assert result["phone_e164"] == vector["e164"]
            assert result["phone_region"] == vector["region"]
            assert result["phone_is_foreign"] is vector["foreign"]
            assert result["phone_country_name"]


def test_missing_library_and_sensitive_statuses_never_guess(monkeypatch):
    monkeypatch.setattr(region, "phonenumbers", None)
    monkeypatch.setattr(region, "geocoder", None)
    assert region.analyze("+12025550123", country="DE")["phone_origin_status"] == "unknown"
    for status in ("withheld", "unavailable", "permission_missing", "not_shared"):
        assert region.analyze("+12025550123", status, "DE", "de")["phone_e164"] == ""


def test_home_country_migration_and_validation(tmp_path):
    path = tmp_path / "locale.json"
    path.write_text('{"language":"fr"}', encoding="utf-8")
    assert region.regional_context(path) == ("DE", "fr")
    path.write_text('{"homeCountry":"us","language":"en"}', encoding="utf-8")
    assert region.regional_context(path) == ("US", "en")
    path.write_text('{"homeCountry":"ZZ"}', encoding="utf-8")
    assert region.regional_context(path)[0] == "DE"


def test_all_linux_packages_carry_libphonenumber():
    files = {
        "debian": ROOT / "debian" / "control",
        "rpm": ROOT / "rpm" / "magnolie-organizer.spec",
        "flatpak": ROOT / "flatpak" / "python3-dependencies.json",
        "appimage": ROOT / "werkzeuge" / "appimage_bauen.sh",
        "appimage-base": ROOT / "werkzeuge" / "appimage_jammy_bauen.sh",
        "fedora-base": ROOT / "werkzeuge" / "rpm_fedora_bauen.sh",
    }
    for package, path in files.items():
        assert "phonenumbers" in path.read_text(encoding="utf-8"), package

    appimage = files["appimage"].read_text(encoding="utf-8")
    assert '[ -e "$APPDIR/usr/lib/python3/dist-packages/phonenumbers" ] || {' in appimage
    assert "phonenumbers konnte nicht in das AppImage kopiert werden." in appimage


def test_distribution_check_gates_include_new_linux_regressions():
    expected = ("test_ersteinrichtung.py", "test_optionale_kontaktquellen.py",
                "test_phone_region.py")
    for gate in (ROOT / "debian" / "rules", ROOT / "rpm" / "magnolie-organizer.spec"):
        text = gate.read_text(encoding="utf-8")
        assert all(name in text for name in expected), gate
