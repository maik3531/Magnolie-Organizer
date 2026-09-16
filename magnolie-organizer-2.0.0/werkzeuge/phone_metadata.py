#!/usr/bin/env python3
"""Generate offline dialling metadata from our native dependency.

Source: Google libphonenumber metadata (Apache-2.0), via python-phonenumbers.
Only metadata is generated; frontend logic and unrelated sections are unchanged.
"""
import argparse
import json
from pathlib import Path

import phonenumbers

ROOT = Path(__file__).resolve().parents[1]
START = "  // BEGIN GENERATED PHONE METADATA\n"
END = "  // END GENERATED PHONE METADATA\n"


def metadata():
    result = {}
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        m = phonenumbers.PhoneMetadata.metadata_for_region(region)
        result[region] = [str(m.country_code), m.international_prefix,
            m.national_prefix_for_parsing or "", m.national_prefix_transform_rule or "",
            m.general_desc.national_number_pattern, list(m.general_desc.possible_length),
            m.national_prefix == "0"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = metadata()
    block = START + "  const TELEFON_REGIONEN = {\n" + ",\n".join(
        "    " + json.dumps(k) + ": " + json.dumps(v, separators=(",", ":"))
        for k, v in rows.items()) + "\n  };\n" + END
    paths = list(dict.fromkeys(path for path in (
        ROOT / "web/anwendung.js", ROOT / "app/web/anwendung.js",
        ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/app/web/anwendung.js") if path.is_file()))
    assert paths, "No desktop source found"
    for path in paths:
        source = path.read_text()
        start, end = source.index(START), source.index(END) + len(END)
        if args.write:
            path.write_text(source[:start] + block + source[end:])
        else:
            assert source[start:end] == block, str(path) + ": stale phone metadata"
    print("Phone metadata: %d regions, libphonenumber %s" % (len(rows), phonenumbers.__version__))


if __name__ == "__main__":
    main()
