"""Pure exporters plus isolated LibreOffice rendering; no user data or app startup.

The rendered cross-platform gate is explicitly in letter_cross_platform.py.
PDFs, raster previews and build artifacts stay under /tmp/opencode/letter-layout-*.
"""
import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINUX = Path(__file__).resolve().parents[1]
SOURCE = LINUX / "bin/magnolie-organizer"
NS = {name: f"urn:oasis:names:tc:opendocument:xmlns:{value}:1.0" for name, value in
      [("office", "office"), ("style", "style"), ("text", "text"), ("draw", "drawing"),
       ("svg", "svg-compatible"), ("fo", "xsl-fo-compatible")]}


def exporter(culture="de-DE"):
    names = {"datum_kurz", "_xml_sicher", "anschrift_zeilen", "_fodt_brief_kompakt", "fodt_brief"}
    tree = ast.parse(SOURCE.read_text())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    from test_locale_completeness import _catalog
    language = culture.split("-")[0]
    messages = {} if language == "en" else {key[1]: value["values"][0]
        for key, value in _catalog(LINUX / "po" / (language + ".po")).items() if value["values"]}
    scope = {"datetime": datetime, "re": re, "_": lambda text: messages.get(text, text),
             "_REGIONAL": {"formatLocale": culture}, "os": SimpleNamespace(environ={}),
             "locale": SimpleNamespace(LC_TIME=2, getlocale=lambda _: (culture, "UTF-8"))}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope["fodt_brief"]


def frame(root):
    return root.find('.//draw:frame[@draw:name="Anschriftfeld"]', NS)


def test_default_explicit_and_legacy_geometry():
    generate = exporter()
    contact = {"anzeigename": "Recipient & <Family>", "strasse": "Testweg 1"}
    default = generate(contact, "Sender & <Co>")
    for layout, y in [(None, "4.5cm"), ("", "4.5cm"), ("din5008", "4.5cm"),
                      ("din5008-b", "4.5cm"), ("din5008-a", "2.7cm")]:
        xml = generate(contact, "Sender & <Co>", layout=layout) if layout is not None else default
        root = ET.fromstring(xml)
        address = frame(root)
        assert address is not None
        assert [address.get(f'{{{NS["svg"]}}}{key}') for key in ("x", "y", "width", "height")] == ["2cm", y, "8.5cm", "4.5cm"]
        sender = root.find('.//draw:frame[@draw:name="Absenderblock"]', NS)
        assert (sender is None) == (layout == "din5008-a")
        assert "Sender & <Co>" in "".join(address.itertext())
        assert "Recipient & <Family>" in "".join(address.itertext())
    assert generate(contact, layout="compact") == generate(contact, layout="kompakt")
    assert frame(ET.fromstring(generate(contact, layout="compact"))) is None
    assert generate(contact) == generate(dict(contact, geburtstag="--04-03"))
    assert "Testweg 1" in generate({"strasse": "Testweg 1"})
    for sender, recipient in [("W" * 1000, contact), ("Sender", {"anzeigename": "W" * 160})]:
        with pytest.raises(ValueError):
            generate(recipient, sender)
        assert generate(recipient, sender, layout="compact")


def test_complete_recipient_lines_and_capacity():
    generate = exporter()
    for item in json.loads((Path(__file__).parent / 'letter-layout/contacts.json').read_text()):
        root = ET.fromstring(generate(item['contact'], item['sender']))
        lines = frame(root).findall('.//text:p[@text:style-name="Anschrift"]', NS)
        assert [''.join(p.itertext()) for p in lines] == item['expected'], item['id']
        sender = root.find('.//draw:frame[@draw:name="Absenderblock"]', NS)
        assert (sender is None) == (not item['sender'])
        if sender is not None:
            assert [''.join(p.itertext()) for p in sender.findall('.//text:p', NS)] == item['sender'].splitlines()
        if item['id'] == 'long-six-lines':
            style = root.find('.//style:style[@style:name="Anschrift"]/style:text-properties', NS)
            assert style.get(f'{{{NS["fo"]}}}font-size') == '8pt'
    # Embedded newlines count against the six-line window capacity, not as XML whitespace.
    with pytest.raises(ValueError):
        generate({'firma': '\n'.join(['Organization'] * 7)})
    with pytest.raises(ValueError):
        generate({'firma': 'Recipient'}, '\n'.join(['Sender'] * 6))


def test_existing_parser_letter_block():
    # Execute only the pure letter assertions, never the application/parser suite startup.
    source = (Path(__file__).parent / 'test_parser.py').read_text()
    start = source.index('kontakt_probe = {"vorname": "Hans"')
    end = source.index('adressen_gettext_alt, adressen_ngettext_alt', start)
    generate = exporter()
    def check(condition, message):
        assert condition, message
    scope = {'m': SimpleNamespace(fodt_brief=generate,
                                 anschrift_zeilen=generate.__globals__['anschrift_zeilen']),
             'pruefe': check}
    exec(compile(source[start:end], 'test_parser.py:letter', 'exec'), scope)


def cross_platform_pdf_geometry():
    dotnet = os.environ.get("LETTER_DOTNET") or shutil.which("dotnet")
    if not dotnet or not shutil.which("libreoffice"):
        raise RuntimeError("Explicit rendered gate requires LETTER_DOTNET/.NET and LibreOffice")
    for tool in ("pdftotext", "pdftoppm"):
        if not shutil.which(tool):
            raise RuntimeError("Explicit rendered gate requires " + tool)
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="letter-layout-", dir="/tmp/opencode"))
    print(f"Letter PDF evidence: {work}", flush=True)
    home = work / 'home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
           'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_CACHE_HOME': str(home / '.cache'),
           'DOTNET_CLI_HOME': str(home), 'DOTNET_PROCESSOR_COUNT': '1',
           'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE': '1',
           'NODE_PATH': str(ROOT / 'magnolie-organizer-windows/node_modules')}
    cases = []
    for culture, name, sender in [
        ("de-DE", "Alexandra Katharina von Beispiel & Partner",
         "Dr. Maximilian Alexander von Musterhausen\nBeispielweg 123\n12345 Musterstadt"),
        ("fr-FR", "Marie-Charlotte de la Fontaine & Associés",
         "Jean-Baptiste Alexandre de la Roche\n123 rue des Fleurs\n75001 Paris")]:
        for layout in [None, "din5008-b", "din5008-a", "din5008", "compact", "kompakt"]:
            item = {"id": culture + "-" + (layout or "default"), "culture": culture,
                    "contact": {"anzeigename": name, "firma": "Example <Test>", "strasse": "Testweg 123", "plz": "12345", "ort": "Teststadt", "geburtstag": "--04-03"},
                    "sender": sender}
            if layout is not None:
                item["layout"] = layout
            cases.append(item)
        cases.append({"id": culture + "-missing", "culture": culture,
                      "contact": {"strasse": "Testweg 123", "ort": "Teststadt"}, "sender": ""})
        cases.append({"id": culture + "-long-recipient", "culture": culture,
                      "contact": {"anzeigename": name + " International Family Administration Service",
                                  "firma": "Example <Test>", "strasse": "Testweg 123", "ort": "Teststadt"},
                       "sender": sender})
    cases.extend(json.loads((Path(__file__).parent / 'letter-layout/contacts.json').read_text()))
    (work / "cases.json").write_text(json.dumps(cases))
    javascript = shutil.which('bun') or shutil.which('node')
    if not javascript:
        raise RuntimeError('Explicit rendered gate requires Bun/Node and jsdom')
    subprocess.run([javascript, str(Path(__file__).parent / 'letter-layout/web.js'),
                    str(work / 'cases.json'), str(work / 'bridge-cases.json')], env=env, check=True, timeout=90)
    bridge = json.loads((work / 'bridge-cases.json').read_text())
    (work / 'windows-cases.json').write_text(json.dumps(bridge['windows']))
    project = Path(__file__).parent / "letter-layout/LetterProbe.csproj"
    subprocess.run([dotnet, "build", str(project), "--nologo", "-o", str(work / "bin"),
                    f"-p:BaseIntermediateOutputPath={work}/obj/", '-m:1', '-p:UseSharedCompilation=false'],
                   env=env, check=True, text=True, timeout=120)
    # Raw imported cards and actual web bridge payloads must both export correctly.
    raw = work / 'raw'
    raw.mkdir()
    subprocess.run([dotnet, str(work / "bin/LetterProbe.dll"), str(work / "cases.json"), str(raw)], env=env, check=True)
    for item in cases:
        if 'expected' in item:
            with zipfile.ZipFile(raw / (item['id'] + '-windows.odt')) as odt:
                paragraphs = frame(ET.fromstring(odt.read('content.xml'))).findall('.//text:p[@text:style-name="Anschrift"]', NS)
                assert [''.join(p.itertext()) for p in paragraphs] == item['expected'], item['id']
    subprocess.run([dotnet, str(work / "bin/LetterProbe.dll"), str(work / "windows-cases.json"), str(work)], env=env, check=True)
    for item in bridge['linux']:
        kwargs = {"layout": item["layout"]} if "layout" in item else {}
        generate = exporter(item['culture'])
        # Exercise the real Linux open route; intercept only process launch.
        names = {'brief_oeffnen', '_private_ausgabe_schreiben'}
        nodes = [node for node in ast.parse(SOURCE.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
        scope = {**generate.__globals__, 'os': os, 'shutil': shutil,
                 'fehler_deutsch': lambda error, context: str(error)}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), scope)
        route = work / ('route-' + item['id'])
        route.mkdir()
        calls = []
        result = scope['brief_oeffnen'](item['contact'], item['sender'], starter=calls.append, ordner=str(route), **kwargs)
        assert result['ok'] and len(calls) == 1, (item['id'], result)
        xml = Path(result['pfad']).read_text()
        (work / (item["id"] + "-linux.fodt")).write_text(xml)
        if item.get("layout") not in ("compact", "kompakt"):
            with zipfile.ZipFile(work / (item["id"] + "-windows.odt")) as odt:
                windows = ET.fromstring(odt.read("content.xml"))
                assert frame(windows).attrib == frame(ET.fromstring(xml)).attrib
                assert "".join(frame(windows).itertext()) == "".join(frame(ET.fromstring(xml)).itertext())
                if 'expected' in item:
                    assert [''.join(p.itertext()) for p in frame(windows).findall('.//text:p[@text:style-name="Anschrift"]', NS)] == item['expected']
    odts = work / 'odt'
    odts.mkdir()
    conversion = subprocess.run(["libreoffice", f"-env:UserInstallation={work.as_uri()}/lo-profile", "--headless",
                    "--convert-to", "odt:writer8", "--outdir", str(odts),
                    *map(str, sorted(work.glob("*.fodt"))), *map(str, sorted(work.glob("*.odt")))],
                   env=env, check=True, capture_output=True, text=True, timeout=120)
    (work / 'libreoffice-odt.log').write_text(conversion.stdout + conversion.stderr)
    assert len(list(odts.glob('*.odt'))) == len(cases) * 2
    conversion = subprocess.run(["libreoffice", f"-env:UserInstallation={work.as_uri()}/lo-profile", "--headless",
                    "--convert-to", "pdf", "--outdir", str(work), *map(str, sorted(odts.glob('*.odt')))],
                   env=env, check=True, capture_output=True, text=True, timeout=120)
    (work / 'libreoffice-pdf.log').write_text(conversion.stdout + conversion.stderr)
    measurements = {}
    rendered_words = {}
    for item in cases:
        for platform in ("linux", "windows"):
            stem = item["id"] + "-" + platform
            pdf = work / (stem + ".pdf")
            bbox = subprocess.check_output(["pdftotext", "-bbox", str(pdf), "-"], text=True)
            root = ET.fromstring(bbox)
            assert len(root.findall('.//{*}page')) == 1, stem
            words = root.findall('.//{*}word')
            if item.get("layout") in ("compact", "kompakt"):
                continue
            rendered_words[stem] = [(word.text, [float(word.get(key)) for key in ("xMin", "yMin", "xMax", "yMax")]) for word in words]
            address = next(word for word in words if word.text in ("Testweg", "Pr\u00fcfweg", "Postfach"))
            x, y = float(address.get("xMin")) * 25.4 / 72, float(address.get("yMin")) * 25.4 / 72
            top = 27 if item.get("layout") == "din5008-a" else 45
            assert 19.8 <= x <= 20.2, (stem, x, y)
            assert top + 17.7 <= y < top + 45, (stem, x, y)
            last = next(word for word in words if word.text == "Teststadt")
            assert float(last.get("yMax")) * 25.4 / 72 <= top + 45, stem
            for word in words:
                if top <= float(word.get("yMin")) * 25.4 / 72 < top + 45:
                    assert float(word.get("xMax")) * 25.4 / 72 <= 105, stem
            measurements[stem] = {'address_xy_mm': [x, y]}
            if item["sender"]:
                # Return text remains a single line; the B header is separate and multiline.
                address_words = [word for word in words if top <= float(word.get('yMin')) * 25.4 / 72 < top + 17.7]
                first = item["sender"].split()[0]
                start = next(word for word in address_words if word.text == first)
                end = next(word for word in address_words if word.text == item["sender"].split()[-1])
                assert abs(float(start.get("yMin")) - float(end.get("yMin"))) < 0.1, stem
                assert float(end.get("xMax")) * 25.4 / 72 <= 105, stem
                assert 19.8 <= float(start.get("xMin")) * 25.4 / 72 <= 20.2
                assert top <= float(start.get("yMin")) * 25.4 / 72 < top + 17.7
                recipient_words = [word for word in words if top + 17.7 <= float(word.get('yMin')) * 25.4 / 72 < top + 45]
                recipient_start = recipient_words[0]
                assert top + 17.7 <= float(recipient_start.get("yMin")) * 25.4 / 72 < top + 20, stem
                if top == 45:
                    header = [word for word in words if float(word.get('xMin')) * 25.4 / 72 < 105 and float(word.get('yMin')) * 25.4 / 72 < 45]
                    assert [word.text for word in header] == item['sender'].split(), stem
                    assert len({round(float(word.get('yMin')), 1) for word in header}) >= len(item['sender'].splitlines()), stem
                    assert 19.8 <= float(header[0].get('xMin')) * 25.4 / 72 <= 20.2
                    assert 20 <= float(header[0].get('yMin')) * 25.4 / 72 < 22
                    assert max(float(word.get('yMax')) for word in header) * 25.4 / 72 < 45
                    date = [word for word in words if float(word.get('xMin')) * 25.4 / 72 >= 125 and float(word.get('yMin')) * 25.4 / 72 < 45]
                    assert date and max(float(word.get('xMax')) for word in date) * 25.4 / 72 <= 190.2
                    assert abs(float(date[0].get('yMin')) - float(header[0].get('yMin'))) < 2
            if 'expected' in item:
                recipient_words = [word for word in words if top + 17.7 <= float(word.get('yMin')) * 25.4 / 72 < top + 45]
                assert [word.text for word in recipient_words] == ' '.join(item['expected']).split(), stem
                line_y = sorted({round(float(word.get('yMin')) * 25.4 / 72, 2) for word in recipient_words})
                assert len(line_y) >= len(item['expected']), (stem, line_y)
                assert len(line_y) <= 6 and all(4.4 < b - a < 4.7 for a, b in zip(line_y, line_y[1:])), (stem, line_y)
                measurements[stem]['recipient_line_y_mm'] = line_y
            subprocess.run(["pdftoppm", "-scale-to", "1100", "-singlefile", "-png", str(pdf), str(work / stem)],
                           check=True, capture_output=True)
        if item.get("layout") not in ("compact", "kompakt"):
            assert all(abs(a - b) < 0.2 for a, b in zip(measurements[item["id"] + "-linux"]['address_xy_mm'], measurements[item["id"] + "-windows"]['address_xy_mm']))
            linux_words = rendered_words[item["id"] + "-linux"]
            windows_words = rendered_words[item["id"] + "-windows"]
            assert [word[0] for word in linux_words] == [word[0] for word in windows_words]
            differences = [(left, right) for left, right in zip(linux_words, windows_words)
                           if any(abs(a - b) >= 0.2 for a, b in zip(left[1], right[1]))]
            assert not differences, (item["id"], differences)
    (work / "coordinates.json").write_text(json.dumps(measurements, indent=2))
    (work / "word-boxes.json").write_text(json.dumps(rendered_words, indent=2))
    print(f"Letter PDF evidence: {work}")


def test_linux_open_route_defaults_and_capacity_error(tmp_path):
    generate = exporter()
    node = next(node for node in ast.parse(SOURCE.read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name == "brief_oeffnen")
    calls = []
    scope = {**generate.__globals__, "os": os, "shutil": SimpleNamespace(which=lambda _: "/fake/libreoffice"),
             "_private_ausgabe_schreiben": lambda path, text: Path(path).write_text(text),
             "fehler_deutsch": lambda error, context: str(error)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), scope)
    work = str(tmp_path)
    result = scope["brief_oeffnen"]({"strasse": "Testweg 123"}, starter=calls.append, ordner=work)
    assert result["ok"] and len(calls) == 1
    assert frame(ET.fromstring(Path(result["pfad"]).read_text())).get(f'{{{NS["svg"]}}}y') == "4.5cm"
    result = scope["brief_oeffnen"]({"strasse": "Testweg 123"}, "W" * 1000, starter=calls.append, ordner=work)
    assert not result["ok"] and len(calls) == 1
    assert "too long" in result["fehler"] or "zu lang" in result["fehler"]
