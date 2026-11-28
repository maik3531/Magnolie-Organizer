"""Refs #855: actual provider functions, bounded offline HTTP, no GTK/app startup.

Run with Python's standard-library unittest. MAGNOLIE_HOLIDAY_SOURCE can name
an immutable baseline copy to reproduce the missing-coverage assertions.
"""
import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
SOURCE = Path(os.environ.get("MAGNOLIE_HOLIDAY_SOURCE", ROOT / "bin/magnolie-organizer"))


def product_functions():
    source = ast.parse(SOURCE.read_text())
    names = {"_ist_iso", "kanonischer_text", "_feiertag_sprache", "_name_waehlen",
             "_openholidays_auswerten", "feiertage_abrufen"}
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    scope = dict(json=json, re=re, datetime=datetime, unicodedata=unicodedata,
                 _ISO_DATUM=re.compile(r"^\d{4}-\d{2}-\d{2}$"),
                 _=lambda text: text, ngettext=lambda one, many, count: one if count == 1 else many,
                 _REGIONAL={"language": "en"}, FEIERTAG_DIENST="https://openholidaysapi.org",
                 FEIERTAG_ABRUF_MAX=8 * 1024 * 1024,
                 GroessenFehler=type("GroessenFehler", (RuntimeError,), {}))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope


def row(**more):
    return {"startDate": "2026-06-01", "endDate": "2026-06-02", "name": "Synthetic holiday",
            "nationwide": False, **more}


def expected_scope(kind="public-holiday", region="DE-SN", year=2026, country="DE"):
    return (country, region, kind, f"{year}-01-01", f"{year}-12-31")


class HolidayCoverageTests(unittest.TestCase):
    def setUp(self):
        self.product = product_functions()
        self.requests = []

    def fetch(self, response=None, **options):
        def http(url):
            uri = urlsplit(url)
            fields = {key: value[0] for key, value in parse_qs(uri.query).items()}
            self.requests.append((uri.path, fields))
            value = response(uri.path, fields) if response else []
            if isinstance(value, Exception):
                raise value
            return value if isinstance(value, str) else json.dumps(value)
        settings = dict(land="DE", region="DE-SN", jahre=[2026], ferien=True, holer=http)
        settings.update(options)
        return self.product["feiertage_abrufen"](**settings)

    def scopes(self, result):
        return {(item["country"], item["region"], item["art"], item["von"], item["bis"])
                for item in result.get("abrufbereiche", [])}

    def test_successful_empty_pages_certify_both_requested_kinds(self):
        result = self.fetch()
        self.assertEqual(self.scopes(result), {expected_scope(), expected_scope("school-holiday")})
        self.assertEqual(result["feiertage"], [])
        self.assertEqual(len(self.requests), 2)

    def test_opt_out_certifies_only_public_holidays(self):
        result = self.fetch(ferien=False)
        self.assertEqual(self.scopes(result), {expected_scope()})
        self.assertEqual(len(self.requests), 1)

    def test_missing_required_region_does_not_certify_school(self):
        result = self.fetch(region="", region_erforderlich=True)
        self.assertEqual(self.scopes(result), {expected_scope(region="")})
        self.assertEqual(len(self.requests), 1)

    def test_country_query_remains_distinct_from_a_subdivision(self):
        result = self.fetch(land="FR", region="", ferien=False)
        self.assertEqual(self.scopes(result), {expected_scope(country="FR", region="")})
        self.assertNotIn("subdivisionCode", self.requests[0][1])

    def test_each_year_region_and_kind_has_its_own_success_scope(self):
        result = self.fetch(region="", jahre=[2027, 2026, 2026],
                            regionen=[("DE-SN", "Saxony"), ("DE-BY", "Bavaria")])
        self.assertEqual(self.scopes(result), {expected_scope(kind, region, year)
            for kind in ("public-holiday", "school-holiday")
            for region in ("DE-SN", "DE-BY") for year in (2026, 2027)})
        self.assertEqual(len(result["abrufbereiche"]), 8)

    def test_one_failed_school_region_does_not_certify_that_region(self):
        def reply(path, fields):
            if path == "/SchoolHolidays" and fields.get("subdivisionCode") == "DE-BY":
                return RuntimeError("Synthetic school service unavailable")
            return []
        result = self.fetch(reply, region="", regionen=[("DE-SN", "Saxony"), ("DE-BY", "Bavaria")])
        self.assertEqual(self.scopes(result), {expected_scope(region="DE-SN"),
            expected_scope(region="DE-BY"), expected_scope("school-holiday", "DE-SN")})

    def test_failed_later_school_year_preserves_successful_other_years(self):
        def reply(path, fields):
            if path == "/SchoolHolidays" and fields["validFrom"].startswith("2027"):
                return RuntimeError("Synthetic later-year failure")
            return []
        result = self.fetch(reply, jahre=[2026, 2027])
        self.assertEqual(self.scopes(result), {expected_scope(year=2026), expected_scope(year=2027),
                                             expected_scope("school-holiday", year=2026)})

    def test_unreadable_school_payload_is_not_a_successful_empty_page(self):
        result = self.fetch(lambda path, _: "not-json" if path == "/SchoolHolidays" else [])
        self.assertEqual(self.scopes(result), {expected_scope()})

    def test_wrong_json_shapes_never_authorize_cache_removal(self):
        for payload in ({}, {"data": {}}, {"data": None}, None, "42", '"wrong"'):
            with self.subTest(payload=payload):
                result = self.fetch(lambda *_: payload, ferien=False)
                self.assertEqual(self.scopes(result), set())
                self.assertEqual(result["feiertage"], [])

    def test_valid_wrapper_retains_authoritative_empty_array(self):
        result = self.fetch(lambda *_: {"data": []}, ferien=False)
        self.assertEqual(self.scopes(result), {expected_scope()})

    def test_skipped_invalid_row_keeps_valid_rows_without_coverage(self):
        bad = {"startDate": "invalid", "name": "Malformed row"}
        result = self.fetch(lambda *_: [row(), bad], ferien=False)
        self.assertEqual(len(result["feiertage"]), 1)
        self.assertEqual(self.scopes(result), set())

    def test_invalid_end_correction_does_not_certify_coverage(self):
        for end in ("2026-05-31", "2026-06-99", "", None):
            with self.subTest(end=end):
                value = row(); value["endDate"] = end
                result = self.fetch(lambda *_: [value], ferien=False)
                self.assertEqual(len(result["feiertage"]), 1)
                self.assertEqual(result["feiertage"][0]["bis"], "2026-06-01")
                self.assertEqual(self.scopes(result), set())

    def test_missing_required_end_keeps_point_fallback_without_coverage(self):
        value = row(); del value["endDate"]
        result = self.fetch(lambda *_: [value], ferien=False)
        self.assertEqual(result["feiertage"][0]["bis"], "2026-06-01")
        self.assertEqual(self.scopes(result), set())

    def test_missing_required_nationwide_keeps_row_without_coverage(self):
        value = row(); del value["nationwide"]
        result = self.fetch(lambda *_: [value], ferien=False)
        self.assertEqual(len(result["feiertage"]), 1)
        self.assertEqual(self.scopes(result), set())

    def test_unscoped_regional_row_cannot_certify_countrywide_response(self):
        result = self.fetch(lambda *_: [row()], region="", ferien=False)
        self.assertEqual(len(result["feiertage"]), 1)
        self.assertEqual(self.scopes(result), set())

    def test_tolerated_bad_scope_metadata_does_not_certify_coverage(self):
        for extra in ({"subdivisions": None}, {"subdivisions": "DE-SN"},
                      {"subdivisions": [{"code": "../bad"}]},
                      {"subdivisions": [{"code": "DE-SN"}, 17]},
                      {"nationwide": "true"}, {"nationwide": None}):
            with self.subTest(extra=extra):
                result = self.fetch(lambda *_: [row(**extra)], ferien=False)
                self.assertEqual(len(result["feiertage"]), 1)
                self.assertEqual(self.scopes(result), set())

    def test_blank_or_partly_malformed_names_do_not_certify_coverage(self):
        for name in ("   ", [{"language": "EN", "text": "Synthetic"}, 17], []):
            with self.subTest(name=name):
                value = row(); value["name"] = name
                result = self.fetch(lambda *_: [value], ferien=False)
                self.assertEqual(self.scopes(result), set())

    def test_cross_year_full_dates_survive_inclusive_query(self):
        value = row(); value.update(startDate="2025-12-20", endDate="2026-01-05")
        result = self.fetch(lambda *_: [value], ferien=False)
        self.assertEqual(self.scopes(result), {expected_scope()})
        self.assertEqual((result["feiertage"][0]["von"], result["feiertage"][0]["bis"]),
                         ("2025-12-20", "2026-01-05"))

    def test_rows_outside_requested_year_do_not_certify_it(self):
        for start, end in (("2025-01-01", "2025-12-31"), ("2027-01-01", "2027-01-02")):
            with self.subTest(start=start):
                value = row(); value.update(startDate=start, endDate=end)
                result = self.fetch(lambda *_: [value], ferien=False)
                self.assertEqual(self.scopes(result), set())
                self.assertEqual(len(result["feiertage"]), 1)

    def test_wrong_country_or_unrelated_region_does_not_certify_query(self):
        for code in ("AT-9", "DE-BY"):
            with self.subTest(code=code):
                result = self.fetch(lambda *_: [row(subdivisions=[{"code": code}])], ferien=False)
                self.assertEqual(self.scopes(result), set())
                self.assertEqual(len(result["feiertage"]), 1)

    def test_parent_child_and_short_region_codes_are_related(self):
        for code in ("DE", "DE-SN", "DE-SN-TEST", "SN"):
            with self.subTest(code=code):
                result = self.fetch(lambda *_: [row(subdivisions=[{"code": code}])], ferien=False)
                self.assertEqual(self.scopes(result), {expected_scope()})

    def test_nationwide_row_can_be_returned_by_subdivision_query(self):
        result = self.fetch(lambda *_: [row(nationwide=True)], ferien=False)
        self.assertTrue(result["feiertage"][0]["nationwide"])
        self.assertEqual(self.scopes(result), {expected_scope()})

    def test_invalid_requested_subdivision_fails_before_http(self):
        with self.assertRaisesRegex(RuntimeError, "not available"):
            self.fetch(region="AT-9")
        self.assertEqual(self.requests, [])

    def test_public_failure_keeps_existing_whole_operation_error(self):
        with self.assertRaisesRegex(RuntimeError, "Synthetic public failure"):
            self.fetch(lambda *_: RuntimeError("Synthetic public failure"))

    def test_byte_limit_failure_is_not_downgraded_to_school_absence(self):
        self.product["FEIERTAG_ABRUF_MAX"] = 4
        with self.assertRaises(self.product["GroessenFehler"]):
            self.fetch(lambda path, _: [] if path == "/PublicHolidays" else [row()])

    def test_original_parser_list_call_remains_supported(self):
        result = self.product["_openholidays_auswerten"](json.dumps([row()]), "school-holiday")
        self.assertIsInstance(result, list)
        self.assertEqual((result[0]["von"], result[0]["bis"]), ("2026-06-01", "2026-06-02"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
