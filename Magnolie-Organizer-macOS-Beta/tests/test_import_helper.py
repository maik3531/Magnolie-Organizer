#!/usr/bin/env python3
"""Actual isolated helper, canonical desktop oracle and original OR6 fixtures (#785).

The full desktop module is loaded only as a test oracle, never by the bundle.
Prepare the explicit dependency cache before running; tests do not download.
"""
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zoneinfo


BETA = Path(__file__).resolve().parents[1]
REPO = BETA.parent
sys.path.insert(0, str(BETA / "tools"))
import project_import_helper as projector


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def native_files():
    for path in sorted((REPO / "contracts").glob("or6-native-*.json")):
        contract = json.loads(path.read_text())
        files = contract.get("files", {})
        if "file" in contract:
            files = {contract["file"]["name"]: contract["file"]}
        for name, proof in files.items():
            data = gzip.decompress(base64.b64decode(proof["gzip_base64"], validate=True))
            if len(data) != proof["bytes"] or hashlib.sha256(data).hexdigest() != proof["sha256"]:
                raise AssertionError("Native OR6 fixture identity differs")
            yield path.name, name, data, contract


class ImportHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        cls.helper_python = os.environ.get("MACOS_BETA_IMPORT_PYTHON", sys.executable)
        cls.temporary = tempfile.TemporaryDirectory(prefix="magnolie-import-helper-test-")
        cls.directory = projector.canonical_temporary_root(cls.temporary.name)
        cls.bundle = cls.directory / "ImportHelper"
        cls.snapshot = projector.input_snapshot(REPO)
        with mock.patch.object(projector.urllib.request, "urlopen", side_effect=AssertionError("Projection must remain offline")):
            cls.manifest = projector.project_snapshot(cls.snapshot, cls.bundle)
        cls.manifest_sha = hashlib.sha256((cls.bundle / "manifest.json").read_bytes()).hexdigest()
        cls.helper_module = load_module("mac_import_protocol_under_test", BETA / "ImportHelper/helper.py")
        cls.old_tzpath = zoneinfo.TZPATH
        zoneinfo.reset_tzpath([str(cls.bundle / "zones")])
        zoneinfo.ZoneInfo.clear_cache()
        cls.old_path = list(sys.path)
        sys.path[:0] = [str(REPO / "magnolie-organizer/bin"), str(cls.bundle / "vendor")]
        cls.old_config = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(cls.directory / "isolated-config")
        cls.oracle = load_module("mac_import_current_desktop_oracle", REPO / projector.MONOLITH)
        cls.oracle._ = lambda message: message
        cls.oracle._zeitzonenname = lambda: "Europe/Berlin"
        cls.oracle._organizer_zeitzone = lambda: zoneinfo.ZoneInfo("Europe/Berlin")
        import magnolie_phone_region
        magnolie_phone_region.regional_context = lambda: ("DE", "en")
        cls.or6 = load_module("mac_import_current_or6_oracle", REPO / projector.OR6)
        cls.tzif = load_module("mac_import_existing_tzif_reader", REPO / "port-adapters/timezones/build-tzif.py")

    @classmethod
    def tearDownClass(cls):
        sys.dont_write_bytecode = cls.old_bytecode
        sys.path[:] = cls.old_path
        zoneinfo.reset_tzpath(cls.old_tzpath)
        zoneinfo.ZoneInfo.clear_cache()
        if cls.old_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = cls.old_config
        cls.temporary.cleanup()

    def header(self, data, art="lotus", name="known-values.or6", **updates):
        value = {"schema": 1, "format": art, "name": name, "language": "en", "timeZone": "Europe/Berlin",
                 "homeCountry": "DE", "byteLength": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        value.update(updates)
        return value

    def request(self, data, art="lotus", name="known-values.or6", header=None, line=None, **updates):
        value = self.header(data, art, name, **updates) if header is None else header
        line = json.dumps(value, ensure_ascii=False).encode() + b"\n" if line is None else line
        process = subprocess.run([self.helper_python, "-I", "-S", "-B", str(self.bundle / "helper.py")],
            input=line + data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
            cwd=self.directory, env=dict(os.environ, PYTHONPATH="/not-a-grant", PYTHONHOME="/not-a-runtime", PYTHONTZPATH="/not-a-zone-grant"))
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors="replace"))
        self.assertEqual(process.stderr, b"")
        self.assertTrue(process.stdout.endswith(b"\n"))
        self.assertLessEqual(len(process.stdout), 96 * 1024 * 1024)
        answer = json.loads(process.stdout)
        self.assertEqual(answer["schema"], 1)
        return answer

    def parsed(self, data, art, name, **updates):
        answer = self.request(data, art, name, **updates)
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["sourceSHA256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(answer["parserManifestSHA256"], self.manifest_sha)
        self.assertEqual(answer["format"], art)
        self.assertEqual(answer["name"], name)
        return answer["result"]

    def same_as_desktop(self, data, art, name):
        actual = self.parsed(data, art, name)
        expected = (self.oracle.muell_import_lesen(data, name) if art == "muell"
                    else self.oracle.import_rohdaten_lesen("claws" if art == "ldif" else art, data, name))
        if art == "ics":
            actual = {key: value for key, value in actual.items() if key not in {"legacyAndroidAliases", "icsImportMetadata"}}
        self.assertEqual(actual, expected)
        return expected

    def test_all_original_program_or6_fixtures_through_isolated_stdio(self):
        rows = list(native_files())
        self.assertEqual(len(rows), 27)
        for source, name, data, contract in rows:
            with self.subTest(source=source, file=name):
                result = self.parsed(data, "lotus", name)
                self.assertEqual(result, self.or6.read_or6(data))
                if name == "known-values.or6":
                    for kind, field in (("contact", "kontakte"), ("appointment", "termine"), ("task", "aufgaben"), ("note", "notizen")):
                        self.assertEqual(len(result[field]), 1)
                        for key, expected in contract["expected"][kind].items():
                            self.assertEqual(result[field][0][key], expected)

    def test_desktop_calendar_vcard_ldif_and_lotus_golden_files(self):
        directory = REPO / "magnolie-organizer/pruefungen/fixtures"
        for name, art in (("golden-komplex.ics", "ics"), ("caldav-series-resource.ics", "ics"),
                          ("icalendar-all-components.ics", "ics"), ("muster-organizer-lotus.ics", "ics"),
                          ("muster-jahrestage-thunderbird.ics", "ics"), ("golden-kontakt.vcf", "vcf"),
                          ("provider-vcards.vcf", "vcf"), ("nextcloud-anniversaries.vcf", "vcf"),
                          ("golden-kontakt.ldif", "ldif"), ("muster-organizer-lotus.csv", "lotus")):
            with self.subTest(name=name):
                self.same_as_desktop((directory / name).read_bytes(), art, name)

    def test_vcs_lcs_csv_contact_alias_and_claws_routes(self):
        directory = REPO / "magnolie-organizer/pruefungen/fixtures"
        calendar = (directory / "golden-komplex.ics").read_bytes()
        for suffix in ("vcs", "lcs"):
            with self.subTest(suffix=suffix):
                self.same_as_desktop(calendar, "ics", "calendar." + suffix)
        self.same_as_desktop((directory / "muster-organizer-lotus.csv").read_bytes(), "vcf", "source.csv")
        claws = b'<?xml version="1.0"?><address-book><person uid="a" first-name="Ada" last-name="Example"><address-list><address email="ada@example.test"/></address-list></person></address-book>'
        result = self.same_as_desktop(claws, "claws", "address-book.xml")
        self.assertEqual(result["kontakte"][0]["vorname"], "Ada")
        self.same_as_desktop((directory / "golden-kontakt.ldif").read_bytes(), "claws", "source.ldi")

    def test_utf16_csv_bom_and_decoded_null_through_isolated_helper(self):
        text = 'ANFANGSDATUMZEIT,BESCHREIBUNG\r\n"27.11.2026 09:30","Prüfung 👩‍💻"\r\n'
        for encoding, bom in (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")):
            for art in ("lotus", "vcf"):
                with self.subTest(encoding=encoding, art=art):
                    result = self.same_as_desktop(bom + text.encode(encoding), art, "selected.csv")
                    self.assertEqual(result["termine"][0]["titel"], "Prüfung 👩‍💻")
                    self.assertEqual(result["termine"][0]["zeit"], "09:30")
                    rejected = self.request(bom + text.replace("Prüfung", "Prü\0fung").encode(encoding), art, "selected.csv")
                    self.assertFalse(rejected["ok"])

    def test_absolute_task_alarm_keeps_explicit_classification(self):
        for classification in ("PUBLIC", "PRIVATE", "CONFIDENTIAL"):
            with self.subTest(classification=classification):
                lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VTODO", "UID:absolute-task",
                         "SUMMARY:Classified task", "CLASS:" + classification,
                         "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER;VALUE=DATE-TIME:20261127T103017Z",
                         "END:VALARM", "END:VTODO", "END:VCALENDAR", ""]
                result = self.same_as_desktop("\r\n".join(lines).encode(), "ics", "absolute.ics")
                self.assertIn("CLASS:" + classification, result["aufgaben"][0]["icsRoundtrip"])
                self.assertIn(lines[8], result["aufgaben"][0]["icsRoundtrip"])

    def test_projected_calendar_keeps_nextcloud_leap_birthday_and_colours(self):
        rule = "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1"
        properties = ["X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1",
                      "COLOR:turquoise", "X-TEST-PROVIDER:retained"]
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "COLOR:gold", "BEGIN:VEVENT", "UID:provider-birthday",
                 "SUMMARY:Example", "DTSTART;VALUE=DATE:19720229", "DTEND;VALUE=DATE:19720301", rule,
                 *properties, "END:VEVENT", "BEGIN:VEVENT", "UID:calendar-colour", "SUMMARY:Ordinary event",
                 "DTSTART;VALUE=DATE:20261128", "END:VEVENT", "END:VCALENDAR", ""]
        result = self.same_as_desktop("\r\n".join(lines).encode(), "ics", "birthdays.ics")
        birthday, = result["jahrestage"]
        self.assertEqual((birthday["uid"], birthday["typ"], birthday["datum"], birthday["akzentFarbe"]),
                         ("provider-birthday", "birthday", "--02-29", "#40e0d0"))
        self.assertEqual(birthday["icsCalendarColor"], "COLOR:gold")
        for line in [rule, *properties]:
            self.assertIn(line, birthday["icsRoundtrip"])
        appointment, = result["termine"]
        self.assertEqual((appointment["uid"], appointment["akzentFarbe"]), ("calendar-colour", "#ffd700"))

    def test_zip_routes_use_the_same_bounded_desktop_dispatcher(self):
        directory = REPO / "magnolie-organizer/pruefungen/fixtures"
        source_or6 = next(data for _source, name, data, _proof in native_files() if name == "known-values.or6")
        for art, name, data in (("ics", "calendar.ics", (directory / "golden-komplex.ics").read_bytes()),
                                ("lotus", "native.or6", source_or6),
                                ("vcf", "address.vcf", (directory / "golden-kontakt.vcf").read_bytes()),
                                ("ldif", "address.ldif", (directory / "golden-kontakt.ldif").read_bytes())):
            with self.subTest(art=art):
                memory = io.BytesIO()
                with zipfile.ZipFile(memory, "w", zipfile.ZIP_STORED) as archive:
                    archive.writestr("folder/" + name, data)
                    archive.writestr("ignored.exe", b"not executable")
                self.same_as_desktop(memory.getvalue(), art, "selected.zip")

    def test_waste_preview_contract_and_limits(self):
        source = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Waste\r\nBEGIN:VEVENT\r\nUID:waste-1\r\nDTSTART;VALUE=DATE:20261127\r\nSUMMARY:Paper\r\nLOCATION:Road\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        result = self.same_as_desktop(source, "muell", "waste.ics")
        self.assertEqual(result["muellFormat"], "ics")
        self.assertEqual(result["termine"][0]["ort"], "Road")
        result = self.same_as_desktop(b'Date;Type\n2026-11-27;Paper\n', "muell", "waste.csv")
        self.assertEqual(result["muellFormat"], "csv")
        self.assertEqual(len(result["zeilen"]), 2)
        rejected = self.request(b'a,b\n' + b'1,2\n' * 10002, "muell", "waste.csv")
        self.assertFalse(rejected["ok"])
        self.assertNotIn("result", rejected)

    def test_legacy_android_sidecar_is_exact_and_transient(self):
        data = (REPO / "magnolie-organizer/pruefungen/fixtures/caldav-series-resource.ics").read_bytes()
        result = self.parsed(data, "ics", "caldav-series-resource.ics")
        proof = result["legacyAndroidAliases"]
        self.assertEqual(proof["sourceSHA256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(proof["appointmentCount"], len(result["termine"]))
        self.assertEqual(proof["algorithm"], "android-jsonobject-quote-v1")
        self.assertTrue(proof["entries"])
        self.assertEqual(proof["entries"][0]["legacyUID"], "caldav-series-1-magnolie-instanz-7f5e24178d89f683")
        for entry in proof["entries"]:
            row = result["termine"][entry["appointmentIndex"]]
            self.assertEqual(row["uid"], entry["canonicalUID"])
            self.assertEqual(row["icsQuelleId"], entry["sourceID"])
            self.assertIn(entry["recurrenceLine"], row["icsRoundtrip"])
            self.assertNotEqual(entry["canonicalUID"], entry["legacyUID"])
            self.assertNotIn("legacyAndroidAliases", row)
        self.assertNotIn("legacyAndroidAliases", result["icsImportMetadata"])
        self.assertIn("X-WR-CALNAME:Team Calendar", result["icsImportMetadata"]["calendarProperties"])
        bare = b"BEGIN:VEVENT\nUID:bare\nDTSTART;VALUE=DATE:20261127\nSUMMARY:Bare\nEND:VEVENT\n"
        self.assertEqual(self.parsed(bare, "ics", "bare.ics")["icsImportMetadata"]["calendarProperties"], [])

    def test_normative_tzif_roundtrip_and_original_point_oracle(self):
        packet = json.loads(self.snapshot[projector.TZ_PREFIX + "tzdb-2026egtz.json"])
        for index, row in enumerate(packet["rules"]):
            with self.subTest(rule=index):
                self.assertEqual(self.tzif.parse_tzif(projector.encode_tzif(row)), row)
        self.assertEqual(len(self.manifest["timezones"]), 597)
        for name in self.manifest["timezones"]:
            self.assertEqual(zoneinfo.ZoneInfo(name).key, name)
        oracle = json.loads((REPO / "port-adapters/tests/timezone-interop-oracle.json").read_text())
        for clock in oracle["clocks"]:
            with self.subTest(clock=clock):
                value = datetime.fromtimestamp(clock["epochMs"] / 1000, timezone.utc).astimezone(zoneinfo.ZoneInfo(clock["identifier"]))
                self.assertEqual(value.strftime("%Y-%m-%dT%H:%M"), clock["wall"])
                self.assertEqual(int(value.utcoffset().total_seconds()), clock["offsetSeconds"])

    def test_selected_language_and_country_are_explicit_context(self):
        data = next(data for _source, name, data, _proof in native_files() if name == "known-values.or6")
        translated = self.parsed(data, "lotus", "source.or6", language="de")
        self.assertNotEqual(translated["bericht"], self.or6.read_or6(data)["bericht"])
        regional = self.parsed(data, "lotus", "source.or6", language="de-DE")
        self.assertEqual(regional["bericht"], translated["bericht"])
        english = self.parsed(data, "lotus", "source.or6", language="en-us")
        self.assertEqual(english["bericht"], self.or6.read_or6(data)["bericht"])
        chinese = self.parsed(data, "lotus", "source.or6", language="zh-cn")
        script = self.parsed(data, "lotus", "source.or6", language="zh-hant-de")
        self.assertEqual(script["bericht"], chinese["bericht"])
        self.assertNotEqual(chinese["bericht"], english["bericht"])
        self.parsed(data, "lotus", "source.or6", timeZone="US/Eastern")
        vcard = b'BEGIN:VCARD\nVERSION:3.0\nFN:Contact\nN:Contact;;;;\nTEL:0305550123\nTEL:+49305550123\nEND:VCARD\n'
        german = self.parsed(vcard, "vcf", "contact.vcf", homeCountry="DE")
        british = self.parsed(vcard, "vcf", "contact.vcf", homeCountry="GB")
        self.assertEqual(len(german["kontakte"][0]["telefone"]), 1)
        self.assertEqual(len(british["kontakte"][0]["telefone"]), 2)

    def test_file_and_network_photo_references_do_not_grant_access(self):
        sentinel = self.directory / "never-read.jpg"
        sentinel.write_bytes(b"\xff\xd8\xffprivate-secret")
        for reference in (sentinel.as_uri(), "https://example.invalid/private.jpg"):
            with self.subTest(reference=reference):
                text = "BEGIN:VCARD\nVERSION:3.0\nFN:A\nN:A;;;;\nPHOTO;VALUE=URI:" + reference + "\nEND:VCARD\n"
                result = self.parsed(text.encode(), "vcf", "photo.vcf")
                self.assertFalse(result["kontakte"][0].get("foto"))
                self.assertNotIn("private-secret", json.dumps(result))

    def test_malformed_headers_lengths_hashes_and_extra_authority_fail_closed(self):
        source = b"test"
        for change, expected in (({"schema": True}, "invalid_header"), ({"format": "import_lokal"}, "unsupported_format"),
                                 ({"path": "/tmp/source"}, "invalid_header"), ({"name": "../source"}, "invalid_header"),
                                 ({"homeCountry": "ZZ"}, "invalid_header"), ({"timeZone": "../../etc/passwd"}, "invalid_timezone"),
                                 ({"byteLength": 32 * 1024 * 1024 + 1}, "input_too_large"),
                                 ({"byteLength": 3}, "input_length"), ({"byteLength": 5}, "input_length"),
                                 ({"sha256": "0" * 64}, "input_identity")):
            with self.subTest(change=change):
                result = self.request(source, header=self.header(source, **change))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], expected)
                self.assertNotIn("result", result)
        for line in (b"{}", b" " * 8192 + b"\n", b'{"schema":1,"schema":1}\n', b'{"schema":NaN}\n'):
            with self.subTest(lineLength=len(line)):
                self.assertEqual(self.request(source, line=line)["error"]["code"], "invalid_header")

    def test_corrupt_or6_zip_bombs_and_xml_entities_have_no_partial_result(self):
        source = next(data for _source, name, data, _proof in native_files() if name == "known-values.or6")
        cases = [("lotus", "bad.or6", source[:-4]), ("lotus", "bad.or6", b"NOPE" + source[4:]),
                 ("claws", "bad.xml", b'<?xml version="1.0"?><!DOCTYPE address-book [<!ENTITY x SYSTEM "file:///etc/passwd">]><address-book>&x;</address-book>')]
        for many in (False, True):
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
                for index in range(129 if many else 1):
                    archive.writestr(str(index) + ".vcf", b"0" * (1 if many else 1024 * 1024))
            cases.append(("vcf", "bad.zip", memory.getvalue()))
        for art, name, raw in cases:
            with self.subTest(art=art, bytes=len(raw)):
                result = self.request(raw, art, name)
                self.assertFalse(result["ok"])
                self.assertNotIn("result", result)

    def test_output_bound_is_applied_before_a_complete_response_is_written(self):
        with self.assertRaises(self.helper_module.RequestError) as error:
            self.helper_module.encode_response({"result": "x" * 1000}, limit=64)
        self.assertEqual(error.exception.code, "output_too_large")

    def test_source_closure_and_dependency_tampering_are_rejected(self):
        source = self.snapshot[projector.MONOLITH].decode()
        for insertion in ("    unknown_import_authority()\n", "    import socket\n", "    exec('pass')\n"):
            with self.subTest(insertion=insertion):
                changed = dict(self.snapshot)
                changed[projector.MONOLITH] = source.replace('def import_rohdaten_lesen(art, roh, dateiname=""):\n',
                    'def import_rohdaten_lesen(art, roh, dateiname=""):\n' + insertion, 1).encode()
                with self.assertRaises(ValueError):
                    projector.build(changed)
        for name in (projector.PHONE_SNAPSHOT, projector.TZ_PREFIX + "tzdb-2026egtz.json"):
            with self.subTest(name=name):
                changed = dict(self.snapshot)
                changed[name] = b"not the reviewed dependency"
                with self.assertRaises(ValueError):
                    projector.build(changed)

    def test_generated_bytes_manifest_and_copy_identity_are_verified(self):
        projector.project_snapshot(self.snapshot, self.bundle, verify=True)
        self.assertEqual((self.bundle / "magnolie_or6.py").read_bytes(), self.snapshot[projector.OR6])
        self.assertNotIn("magnolie_telefon.py", self.manifest["generated"])
        self.assertNotIn("PhoneService", (self.bundle / "magnolie_phone_region.py").read_text())
        module = self.bundle / "desktop_imports.py"
        before = module.read_bytes()
        try:
            module.write_bytes(before + b"\n# changed\n")
            self.assertEqual(self.request(b"test")["error"]["code"], "bundle_invalid")
        finally:
            module.write_bytes(before)


class ProjectionPathTests(unittest.TestCase):
    def test_owned_temporary_parent_alias_is_normalized_before_projection(self):
        """#793: reproduce a macOS-shaped parent alias with real filesystem links."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            real_parent = root / "private"; real_parent.mkdir()
            alias = root / "var"; alias.symlink_to(real_parent, target_is_directory=True)
            with tempfile.TemporaryDirectory(dir=alias) as owned:
                with self.assertRaisesRegex(ValueError, "Symlinked projection path"):
                    projector.safe_path(Path(owned) / "ImportHelper", "nested/fixture.txt")
                canonical = projector.canonical_temporary_root(owned)
                self.assertEqual(canonical, real_parent / Path(owned).name)
                output = canonical / "ImportHelper"
                payload = {"nested/fixture.txt": b"reviewed fixture bytes"}
                # Isolate the path boundary; reads/writes, links and verification are real.
                with mock.patch.object(projector, "build", return_value=(payload, {"fixture": True})):
                    projector.project_snapshot({}, output)
                    projector.project_snapshot({}, output, verify=True)
                self.assertEqual((output / "nested/fixture.txt").read_bytes(), payload["nested/fixture.txt"])

    def test_temporary_root_itself_cannot_be_a_link_or_a_missing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            real = root / "real"; real.mkdir()
            link = root / "link"; link.symlink_to(real, target_is_directory=True)
            broken = root / "broken"; broken.symlink_to(root / "absent", target_is_directory=True)
            file = root / "file"; file.write_bytes(b"file")
            for invalid in (link, broken, root / "missing", file):
                with self.subTest(path=invalid.name), self.assertRaisesRegex(ValueError, "real directory"):
                    projector.canonical_temporary_root(invalid)

    def test_canonical_temporary_parent_does_not_authorize_projection_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = projector.canonical_temporary_root(directory)
            outside = root / "outside"; outside.mkdir()
            (outside / "fixture.txt").write_bytes(b"preserved")
            for case in ("root", "directory", "file", "broken"):
                with self.subTest(case=case):
                    output = root / ("output-" + case)
                    if case == "root":
                        output.symlink_to(outside, target_is_directory=True)
                    else:
                        output.mkdir()
                        if case == "directory":
                            (output / "nested").symlink_to(outside, target_is_directory=True)
                        else:
                            (output / "nested").mkdir()
                            target = outside / ("absent" if case == "broken" else "fixture.txt")
                            (output / "nested/fixture.txt").symlink_to(target)
                    with self.assertRaisesRegex(ValueError, "Symlinked projection path"):
                        projector.safe_path(output, "nested/fixture.txt")
            self.assertEqual((outside / "fixture.txt").read_bytes(), b"preserved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
