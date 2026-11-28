#!/usr/bin/env python3
"""Refs #855: real public HTTP through exact Linux product functions.

Only environment/gettext and response recording are supplied by this host.
The product's Request, urlopen, bounded reader, decoder, parser and fetcher run.
No application startup, persisted user data, or native GUI is involved.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", action="append", help="Optional exact scenario names; default runs initial four scenes")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.root / "magnolie-organizer/bin/magnolie-organizer"
    raw_source = source.read_bytes()
    tree = ast.parse(raw_source)
    functions = {"_ist_iso", "kanonischer_text", "_feiertag_sprache", "_name_waehlen",
                 "_openholidays_auswerten", "feiertage_abrufen", "_url_holen",
                 "antwort_begrenzt_lesen", "_text_dekodieren"}
    optional_helpers = {"_openholidays_region_code"}
    constants = {"PROGRAMM_FASSUNG", "FEIERTAG_DIENST", "FEIERTAG_ANTWORT_MAX",
                 "FEIERTAG_ABRUF_MAX", "_ISO_DATUM"}
    nodes = []
    found = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in functions | optional_helpers | {"GroessenFehler"}:
            nodes.append(n)
            found.add(n.name)
        elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets):
            nodes.append(n)
            found.update(t.id for t in n.targets if isinstance(t, ast.Name))
    assert functions | constants | {"GroessenFehler"} <= found, found
    scope = dict(json=json, re=re, datetime=datetime, unicodedata=unicodedata,
                 _=lambda text: text, ngettext=lambda one, many, count: one if count == 1 else many,
                 _REGIONAL={"language": "en"})
    sys.path.insert(0, str(source.parent))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    fragments = {getattr(n, "name", "constant-" + str(n.lineno)):
                 ast.get_source_segment(raw_source.decode(), n) for n in nodes}
    (out / "extracted-source.json").write_text(json.dumps(fragments, indent=2) + "\n")
    original_urlopen = urllib.request.urlopen
    requests = []

    class RecordedResponse:
        def __init__(self, response, entry):
            self.response, self.entry, self.chunks = response, entry, []
            self.headers = response.headers

        def read(self, count=-1):
            data = self.response.read(count)
            self.chunks.append(data)
            return data

        def __enter__(self):
            self.response.__enter__()
            return self

        def __exit__(self, *args):
            body = b"".join(self.chunks)
            name = f"response-{len(requests):02d}.json"
            (out / name).write_bytes(body)
            self.entry.update(file=name, bytes=len(body), sha256=sha(body),
                              finished_at_utc=datetime.now(timezone.utc).isoformat())
            return self.response.__exit__(*args)

    def recording_urlopen(request, *positional, **kwargs):
        entry = {"url": request.full_url, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                 "request_headers": dict(request.header_items()), "timeout_seconds": kwargs.get("timeout")}
        requests.append(entry)
        try:
            response = original_urlopen(request, *positional, **kwargs)
        except urllib.error.HTTPError as error:
            body = error.read(scope["FEIERTAG_ANTWORT_MAX"] + 1)
            name = f"response-{len(requests):02d}-error.txt"
            (out / name).write_bytes(body)
            entry.update(status=error.code, file=name, bytes=len(body), sha256=sha(body),
                         error_type=type(error).__name__, error=str(error),
                         finished_at_utc=datetime.now(timezone.utc).isoformat())
            raise
        except Exception as error:
            entry.update(error_type=type(error).__name__, error=str(error),
                         finished_at_utc=datetime.now(timezone.utc).isoformat())
            raise
        entry.update(status=response.status, final_url=response.geturl(),
                     response_headers={k: v for k, v in response.headers.items()
                                       if k.lower() in {"content-type", "content-length", "date", "etag", "last-modified", "cache-control"}})
        return RecordedResponse(response, entry)

    scenes = [
        ("de-sn-2026", "DE", "DE-SN", [2026]),
        ("at-9-2026", "AT", "AT-9", [2026]),
        ("ch-zh-2026", "CH", "CH-ZH", [2026]),
        ("de-sn-2027", "DE", "DE-SN", [2027]),
    ]
    if args.scene:
        scenes += [("at-2-2026", "AT", "AT-2", [2026]), ("at-3-2026", "AT", "AT-3", [2026])]
        assert set(args.scene) <= {s[0] for s in scenes}
        scenes = [s for s in scenes if s[0] in args.scene]
    results = []
    urllib.request.urlopen = recording_urlopen
    try:
        for name, country, region, years in scenes:
            first = len(requests)
            result = {"scene": name, "settings": {"land": country, "region": region, "jahre": years, "ferien": True}}
            start = time.monotonic()
            try:
                value = scope["feiertage_abrufen"](country, region, years, ferien=True)
                result["response"] = value
                rows = value["feiertage"]
                result["checks"] = {
                    "exactly_two_real_http_requests": len(requests) - first == 2,
                    "both_requests_http_200": all(r.get("status") == 200 for r in requests[first:]),
                    "nonempty_public_holidays": any(r["art"] == "public-holiday" for r in rows),
                    "nonempty_school_holidays": any(r["art"] == "school-holiday" for r in rows),
                    "returned_country_matches": all(r["country"] == country for r in rows),
                    "returned_request_region_matches": all(r["region"] == region for r in rows),
                    "both_successful_kinds_have_coverage": {r["art"] for r in value["abrufbereiche"]} == {"public-holiday", "school-holiday"},
                    "coverage_bound_to_requested_scope": all(r["country"] == country and r["region"] == region and r["von"] == f"{years[0]}-01-01" and r["bis"] == f"{years[0]}-12-31" for r in value["abrufbereiche"]),
                }
                result["counts"] = {kind: sum(r["art"] == kind for r in rows) for kind in ("public-holiday", "school-holiday")}
                result["full_cross_year_periods"] = [r for r in rows if r["von"][:4] != r["bis"][:4]]
            except Exception as error:
                result.update(error_type=type(error).__name__, error=str(error))
            result.update(request_indices=list(range(first + 1, len(requests) + 1)), seconds=round(time.monotonic() - start, 3))
            results.append(result)
            print(json.dumps({k: v for k, v in result.items() if k != "response"}, ensure_ascii=False), flush=True)
    finally:
        urllib.request.urlopen = original_urlopen
    report = {
        "source_base": "1749c92eb42801c38eaba31b272d8c0e27be9164",
        "candidate_tree": None if "_openholidays_region_code" in found else "f4f94a2c2cf73a064448d3208f31d471e150dbe4",
        "parent_candidate_tree": "f4f94a2c2cf73a064448d3208f31d471e150dbe4",
        "runtime": sys.version,
        "source_sha256": sha(raw_source),
        "setup_source_sha256": sha((source.parent / "magnolie_setup_ui.py").read_bytes()),
        "functions": sorted(functions | (found & optional_helpers)),
        "network_mode": "Live verified-TLS urllib.request through actual product _url_holen; recording wrapper only",
        "requests": requests, "scenes": results,
        "limits": ["No native GUI or package acceptance", "Provider content observed at capture time only", "No Nager call: this product path uses OpenHolidays"]
    }
    (out / "live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if all(all(r.get("checks", {"error": False}).values()) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
