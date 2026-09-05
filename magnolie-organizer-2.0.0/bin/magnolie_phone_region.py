#!/usr/bin/env python3
"""Conservative local phone-number normalization and origin metadata."""

import json
import locale
import os
import re


ISO_ALPHA2 = frozenset((
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI "
    "BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN "
    "CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK "
    "FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM "
    "HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN "
    "KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK "
    "ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP "
    "NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
    "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF "
    "TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI "
    "VN VU WF WS YE YT ZA ZM ZW").split())

try:
    import phonenumbers
    from phonenumbers import geocoder
except (ImportError, OSError):
    phonenumbers = geocoder = None


def home_country(value):
    """Validate ISO 3166-1 alpha-2; DE preserves pre-setting behavior."""
    candidate = str(value or "").strip().upper()
    return candidate if candidate in ISO_ALPHA2 else "DE"


def regional_context(path=None):
    config = path
    if config is None:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        config = os.path.join(base, "magnolie-organizer", "locale.json")
    try:
        with open(config, encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, TypeError, ValueError):
        value = {}
    language = str(value.get("language") or "system").replace("-", "_")
    if language == "system":
        language = (locale.getlocale()[0] or "en").replace("-", "_")
    language = language.split("_", 1)[0].lower()
    if not re.fullmatch(r"[a-z]{2,3}", language):
        language = "en"
    return home_country(value.get("homeCountry")), language


def analyze(number, number_status="available", country=None, language=None):
    """Return metadata only when libphonenumber establishes a unique ISO region."""
    origin = {"phone_origin_status": "unknown", "phone_e164": "",
              "phone_region": "", "phone_country_name": "",
              "phone_is_foreign": None, "phone_display_hint": ""}
    if number_status != "available" or not isinstance(number, str) or not number.strip():
        return origin
    selected_country, selected_language = regional_context()
    selected_country = home_country(country or selected_country)
    selected_language = str(language or selected_language).replace("-", "_").split("_", 1)[0].lower()
    if phonenumbers is None or geocoder is None or len(number) > 128:
        return origin
    try:
        parsed = phonenumbers.parse(number, selected_country)
        if not phonenumbers.is_valid_number(parsed):
            return origin
        region = phonenumbers.region_code_for_number(parsed)
        if not isinstance(region, str) or region not in ISO_ALPHA2:
            return origin
        country_name = (geocoder.country_name_for_number(parsed, selected_language) or
                        geocoder.country_name_for_number(parsed, "en"))
        if not country_name:
            return origin
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        foreign = region != selected_country
        hint = "%s (%s%s%s)" % (country_name, selected_country,
                                  " -> " if foreign else " = ", region)
        return {"phone_origin_status": "known", "phone_e164": e164,
                "phone_region": region, "phone_country_name": country_name,
                "phone_is_foreign": foreign, "phone_display_hint": hint}
    except Exception:
        return origin


def match_key(number, country=None):
    return analyze(number, "available", country, "en")["phone_e164"]


def enrich_call(payload, country=None, language=None):
    value = dict(payload or {})
    value.update(analyze(value.get("number"), value.get("number_status"),
                         country, language))
    return value
