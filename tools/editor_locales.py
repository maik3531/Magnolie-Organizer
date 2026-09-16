#!/usr/bin/env python3
"""Manual editor translations -> canonical PO, MO, JS and native resources.

Run desktop_pot_merge.py first, then --apply. Default: read-only verification.
Only the explicit editor keys and Norwegian 'Select all' are authored here.
"""
import gettext
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / 'magnolie-organizer-2.0.0'
WINDOWS = ROOT / 'Magnolie-Organizer-Windows-2.0.0'
TEXT = json.loads(Path(__file__).with_suffix('.json').read_text())


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


parser = module(LINUX / 'werkzeuge/desktop_pot_merge.py')


def expected(locale, count):
    values = dict(zip(TEXT['en'][:count], TEXT[locale][:count]))
    if locale == 'nb':
        values['Select all'] = 'Merk alt'
    return values


def update_po(path, values):
    text = path.read_text()
    blocks = re.split(r'\n\s*\n', text)
    seen = set()
    for index, block in enumerate(blocks):
        if any(line.startswith('#~') for line in block.splitlines()):
            continue
        # Use the canonical parser, retaining every unrelated byte/block.
        match = re.search(r'^msgid (".*"(?:\n".*")*)\nmsgstr (".*"(?:\n".*")*)$', block, re.M)
        if not match:
            continue
        key = ''.join(json.loads(line) for line in match[1].splitlines())
        if key in values:
            assert '#, fuzzy' not in block, (path, key)
            blocks[index] = block[:match.start(2)] + json.dumps(values[key], ensure_ascii=False) + block[match.end(2):]
            seen.add(key)
    assert seen == values.keys(), (path, values.keys() - seen)
    path.write_text('\n\n'.join(blocks))


def main():
    apply = '--apply' in sys.argv
    assert len(TEXT) == 20 and all(len(row) == 8 for row in TEXT.values())
    for locale, row in TEXT.items():
        assert all(row) and (locale == 'en' or all(a != b for a, b in zip(TEXT['en'], row)))
        for key, value in zip(TEXT['en'], row):
            assert re.findall(r'%\([^)]+\)s', key) == re.findall(r'%\([^)]+\)s', value)
    native_args = []
    for base, tools, count in ((LINUX, LINUX / 'werkzeuge', 4), (WINDOWS / 'app', WINDOWS / 'werkzeuge', 7)):
        po_files = sorted((base / 'po').glob('*.po'))
        assert {p.stem for p in po_files} == TEXT.keys() - {'en'}
        template = {e['msgid'] for e in parser.catalog(base / 'po/magnolie-organizer.pot')}
        assert set(TEXT['en'][:count]) <= template
        for po in po_files:
            values = expected(po.stem, count)
            if apply:
                update_po(po, values)
            active = {e['msgid']: e for e in parser.catalog(po) if not e['obsolete']}
            assert template <= active.keys(), po
            assert all('fuzzy' not in e['flags'] and all(parser.values(e).values()) for e in active.values()), po
            for key, value in values.items():
                assert active[key]['msgstr'] == value, (po, key)
            js = base / 'web/i18n' / (po.stem + '.js')
            if apply:
                subprocess.run([sys.executable, str(tools / 'po_zu_js.py'), po.stem, str(po), str(js)], check=True)
            with tempfile.TemporaryDirectory(prefix='editor-mo-', dir='/tmp/opencode') as temp:
                # Windows ships JSON; its MO is an intermediate resource fixture.
                mo = (LINUX / 'locale' / po.stem / 'LC_MESSAGES/magnolie-organizer.mo'
                      if base == LINUX else Path(temp) / 'magnolie-organizer.mo')
                assert mo.parent.is_dir()
                if apply or base != LINUX:
                    subprocess.run(['msgfmt', '--check', '--check-format', '-o', str(mo), str(po)], check=True)
                with mo.open('rb') as stream:
                    compiled = gettext.GNUTranslations(stream)
            payload = json.loads(re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\("[^"]+", (.*)\);\s*', js.read_text(), re.S)[1])
            for key, value in values.items():
                assert compiled.gettext(key) == value and payload['messages'].get(key) == value, (po, key)
            if base == WINDOWS / 'app':
                native_args.extend([po.stem, str(po)])
    native_path = WINDOWS / 'app/native-i18n.json'
    if apply:
        subprocess.run([sys.executable, str(WINDOWS / 'werkzeuge/po_zu_native.py'), str(native_path), *native_args], check=True)
    native = json.loads(native_path.read_text())['locales']
    extra_path = ROOT / 'Magnolie-Organizer-macOS-Beta/Resources/native-extra-i18n.json'
    extras = json.loads(extra_path.read_text())
    for locale in TEXT.keys() - {'en'}:
        for key, value in expected(locale, 7).items():
            assert native[locale].get(key) == value, (locale, key)
        extra = extras[locale.replace('_', '-').lower()]
        # Existing aliases must agree with the canonical translations.
        assert all(extra.get(key) == value for key, value in zip(TEXT['en'][:2], TEXT[locale][:2]))
        if apply:
            extra[TEXT['en'][7]] = TEXT[locale][7]
        assert extra.get(TEXT['en'][7]) == TEXT[locale][7]
    if apply:
        extra_path.write_text(json.dumps(extras, ensure_ascii=False, indent=2) + '\n')
    if '--preservation-baseline' in sys.argv:
        baseline = json.loads(Path(sys.argv[sys.argv.index('--preservation-baseline') + 1]).read_text())
        preserved = 0
        for platform, base in (('linux', LINUX), ('windows', WINDOWS / 'app')):
            for name, previous in baseline[platform].items():
                if not name.endswith('.po'):
                    continue
                current = parser.catalog(base / 'po' / name)
                by_key = {}
                for entry in current:
                    by_key.setdefault(parser.key(entry), []).append(parser.values(entry))
                for old in previous:
                    if not any(parser.values(old).values()):
                        continue
                    if name == 'nb.po' and old['msgid'] == 'Select all':
                        continue  # Explicitly requested correction, checked above.
                    assert parser.values(old) in by_key.get(parser.key(old), []), (platform, name, old['msgid'])
                    preserved += 1
        print(f'PASS preservation: {preserved} pre-existing translated entries retained, including obsolete and OpenHolidays entries')
    print('PASS editor catalogs: 20 languages; Linux/Windows POT, PO, MO, JS; Windows native JSON; macOS clipboard aliases')


if __name__ == '__main__':
    main()
