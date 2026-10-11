"""Local own-profile fallback; never an ordinary address-book contact."""

FIELDS = {"givenname": "vorname", "sn": "nachname", "o": "firma", "street": "strasse", "postalcode": "plz",
          "l": "ort", "c": "land", "st": "region", "mail": "email", "telephonenumber": "telefon", "homephone": "mobil"}


def resolve(office, profile, purpose="address"):
    if not isinstance(profile, dict) or profile.get("version") != 1 or profile.get("kind") != "own_profile" or not isinstance(profile.get("data"), dict):
        return office
    original = dict(office or {})
    existing = dict(original.get("felder") or {})
    own = {field: str(profile["data"].get(key) or "").strip() for field, key in FIELDS.items()}
    fields = dict(existing)
    address = ("givenname", "sn", "o", "street", "postalcode", "l", "c", "st")
    take = bool(own["l"]) and (not existing.get("l") if purpose == "location" else
                              bool(own["street"]) and not (existing.get("street") and existing.get("l")))
    if take:
        for field in address:
            fields[field] = own[field]
    for field in ("mail", "telephonenumber", "homephone"):
        if not fields.get(field): fields[field] = own[field]
    lines = [" ".join(filter(None, (fields.get("givenname"), fields.get("sn")))), fields.get("o", ""), fields.get("street", ""),
             " ".join(filter(None, (fields.get("postalcode"), fields.get("l")))), fields.get("c", "")]
    sender = "\n".join(line for line in lines if line)
    return dict(original, felder=fields, absender=sender, ok=bool(sender), fehler="" if sender else original.get("fehler", ""),
                quelle="own_profile" if take else original.get("quelle", "libreoffice"))
