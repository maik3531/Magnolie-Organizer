"""Transient #465 evidence around the unchanged current desktop ICS result."""
import hashlib
import io
import re
import zipfile


def with_calendar_evidence(result, raw, source_sha256, codec):
    response = dict(result)
    properties = []
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        stack = []
        for line in codec._entfalte_zeilen(codec._text_dekodieren(raw)):
            prop = codec._prop_zerlegen(line)
            if not prop:
                continue
            name, _parameters, value = prop
            if name == "BEGIN":
                stack.append(value.strip().upper())
            elif name == "END":
                if stack:
                    stack.pop()
            elif stack == ["VCALENDAR"]:
                properties.append(line)
    response["icsImportMetadata"] = {"version": 1, "sourceSHA256": source_sha256,
                                     "calendarProperties": properties}
    rows = result.get("termine", [])
    entries = []
    for index, row in enumerate(rows):
        lines = [line for line in row.get("icsRoundtrip", [])
                 if isinstance(line, str) and re.match(r"^RECURRENCE-ID[;:]", line, re.I)]
        if not lines:
            continue
        if len(lines) != 1:
            raise ValueError("Ambiguous calendar recurrence identity.")
        wire = row.get("icsSerienUid")
        source_id = row.get("icsQuelleId")
        if not isinstance(wire, str) or not wire or not isinstance(source_id, str) or not source_id:
            raise ValueError("The calendar recurrence source identity is missing.")
        # Reuse the parser's exact full parameter/value serialization. Source
        # identity and the original complete RID line stay separate witnesses.
        current = codec._termin_recurrence_id(row)
        canonical_uid = wire + "-magnolie-instanz-" + hashlib.sha256(current.encode("utf-8")).hexdigest()[:16]
        if row.get("uid") != canonical_uid:
            raise ValueError("Canonical calendar recurrence evidence differs.")
        legacy_uid = wire + "-magnolie-instanz-" + hashlib.sha256(current.replace("/", "\\/").encode("utf-8")).hexdigest()[:16]
        if canonical_uid != legacy_uid:
            entries.append({"appointmentIndex": index, "canonicalUID": canonical_uid,
                            "legacyUID": legacy_uid, "sourceID": source_id, "wireUID": wire,
                            "recurrenceLine": lines[0]})
    if entries:
        if len(rows) > 50000:
            raise ValueError("The calendar alias evidence exceeds the supported limits.")
        response["legacyAndroidAliases"] = {
            "version": 1, "algorithm": "android-jsonobject-quote-v1", "sourceSHA256": source_sha256,
            "appointmentCount": len(rows), "entries": entries,
        }
    return response
