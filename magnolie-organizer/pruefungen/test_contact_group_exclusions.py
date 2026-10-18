"""Identity-bound person-group reminder decisions and privacy projection (#160)."""
import copy
import datetime
import json
from pathlib import Path

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def product(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "gi", None)
    return quellmodul_laden("contact_groups_probe", Path(__file__).resolve().parents[1] / "bin/magnolie-organizer")


def owned_book():
    return {"kontakte": [
        {"id": "patient", "kontaktAliase": {"ids": ["old-patient"]}, "vcardRoundtrip": ["CATEGORIES:Work,PATIENTEN", "X-OWNED:preserved"]},
        {"id": "colleague", "vcardRoundtrip": ["CATEGORIES:Colleagues"]}],
        "jahrestage": [
            {"id": "patient-birthday", "uid": "patient-source", "kontaktId": "patient", "name": "Owned Patient", "datum": "1980-10-18", "typ": "birthday"},
            {"id": "old-patient-birthday", "uid": "other-source", "kontaktId": "old-patient", "name": "Owned Patient", "datum": "1980-10-18", "typ": "birthday"},
            {"id": "patient-wedding", "kontaktId": "patient", "name": "Owned Patient", "datum": "2000-10-18", "typ": "wedding-anniversary"},
            {"id": "colleague-birthday", "kontaktId": "colleague", "name": "Owned Colleague", "datum": "1981-10-18", "typ": "birthday"},
            {"id": "unlinked-birthday", "name": "Owned Patient", "datum": "1980-10-18", "typ": "birthday"}],
        "einstellungen": {"adressen": {"gruppenAusschluss": {"enabled": True,
            "notifications": {"scope": "birthdays", "groups": ["Patients"]}}},
            "sicherheit": {"erinnernTrotzKennwort": True}, "erinnerung": {"an": True, "jahrestage": {"an": True}}}}


def test_native_rules_scopes_identity_aliases_and_disabled_retained_choices(product):
    book = owned_book()
    before = json.dumps(book, sort_keys=True)
    excluded = product.gruppen_ausschluss_pruefer(book)
    assert [item["id"] for item in book["jahrestage"] if excluded(item)] == ["patient-birthday", "old-patient-birthday"]
    assert json.dumps(book, sort_keys=True) == before
    book["einstellungen"]["adressen"]["gruppenAusschluss"]["notifications"]["scope"] = "anniversaries"
    assert product.gruppen_ausschluss_pruefer(book)(book["jahrestage"][2])
    policy = book["einstellungen"]["adressen"]["gruppenAusschluss"]
    policy["enabled"] = False
    assert not any(product.gruppen_ausschluss_pruefer(book)(item) for item in book["jahrestage"])
    assert policy["notifications"]["groups"] == ["Patients"]


def test_native_reminder_and_privacy_projection_filter_before_contact_redaction(product):
    book = owned_book()
    records_before = copy.deepcopy((book["kontakte"], book["jahrestage"]))
    result = product.faellige_jahrestage(book, datetime.datetime(2026, 10, 18, 8, 1))
    ids = [item["id"] for item in result["faellig"]]
    assert not any("patient-birthday" in identity for identity in ids)
    assert any("colleague-birthday" in identity for identity in ids)
    assert any("patient-wedding" in identity for identity in ids)
    projected = product.erinnerungsdaten_auswaehlen(book)
    assert "kontakte" not in projected
    assert not any(item["id"] in ("patient-birthday", "old-patient-birthday") for item in projected["jahrestage"])
    assert "kontaktId" not in json.dumps(projected) and "gruppenAusschluss" not in json.dumps(projected)
    assert (book["kontakte"], book["jahrestage"]) == records_before


@pytest.mark.parametrize("settings", [None, [], "invalid", {"adressen": "invalid"}, {"adressen": {"gruppenAusschluss": "invalid"}},
    {"adressen": {"gruppenAusschluss": {"enabled": True, "notifications": {"groups": "Patients"}}}}])
def test_invalid_policy_shapes_do_not_invent_exclusions_or_crash_reminders(product, settings):
    assert product.gruppen_ausschluss_pruefer({"einstellungen": settings})({"typ": "birthday", "kontaktId": "owned"}) is False


def test_merged_provider_membership_uses_explicit_regional_phone_identity(product):
    book = owned_book()
    book["einstellungen"]["regional"] = {"homeCountry": "US"}
    book["einstellungen"]["adressen"]["landCode"] = "DE"
    book["kontakte"][0]["telefone"] = [{"wert": "+12025550123"}]
    book["kontakte"].append({"id": "other-provider", "telefone": [{"wert": "2025550123"}], "vcardRoundtrip": []})
    item = {"id": "other-provider-birthday", "kontaktId": "other-provider", "name": "Owned merged person", "datum": "1980-10-18", "typ": "birthday"}
    book["jahrestage"].append(item)
    assert product.gruppen_ausschluss_pruefer(book)(item)
