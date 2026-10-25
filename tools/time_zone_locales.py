#!/usr/bin/env python3
"""Author and verify #152 translations with the existing desktop catalog tools."""
import argparse
import gettext
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from editor_locales import ROOT, LINUX, WINDOWS, parser, update_po

TEXT = json.loads(Path(__file__).with_suffix('.json').read_text())


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--apply', action='store_true')
    arguments.add_argument('--preservation-baseline', type=Path)
    args = arguments.parse_args()
    assert len(TEXT) == 20 and len(TEXT['en']) == 22
    assert all(len(row) == len(TEXT['en']) and all(row) for row in TEXT.values())
    native_args = []
    for base, tools in ((LINUX, LINUX / 'werkzeuge'), (WINDOWS / 'app', WINDOWS / 'werkzeuge')):
        catalogs = sorted((base / 'po').glob('*.po'))
        assert {path.stem for path in catalogs} == TEXT.keys() - {'en'}
        template = {entry['msgid'] for entry in parser.catalog(base / 'po/magnolie-organizer.pot')}
        assert set(TEXT['en']) <= template
        for po in catalogs:
            wanted = dict(zip(TEXT['en'], TEXT[po.stem]))
            if args.apply:
                update_po(po, wanted)
            active = {entry['msgid']: entry for entry in parser.catalog(po) if not entry['obsolete']}
            assert template <= active.keys(), po
            assert all('fuzzy' not in entry['flags'] and all(parser.values(entry).values()) for entry in active.values()), po
            assert all(active[key]['msgstr'] == value for key, value in wanted.items()), po
            js = base / 'web/i18n' / (po.stem + '.js')
            if args.apply:
                subprocess.run([sys.executable, str(tools / 'po_zu_js.py'), po.stem, str(po), str(js)], check=True)
            with tempfile.TemporaryDirectory(prefix='magnolie-timezone-mo-', dir='/tmp/opencode') as temporary:
                mo = LINUX / 'locale' / po.stem / 'LC_MESSAGES/magnolie-organizer.mo' if base == LINUX else Path(temporary) / 'magnolie-organizer.mo'
                if args.apply or base != LINUX:
                    subprocess.run(['msgfmt', '--check', '--check-format', '-o', str(mo), str(po)], check=True)
                with mo.open('rb') as stream:
                    compiled = gettext.GNUTranslations(stream)
            payload = json.loads(re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\("[^"]+", (.*)\);\s*', js.read_text(), re.S)[1])
            for key, value in wanted.items():
                assert compiled.gettext(key) == value and payload['messages'].get(key) == value, (po, key)
            if base == WINDOWS / 'app':
                native_args.extend([po.stem, str(po)])
    native_path = WINDOWS / 'app/native-i18n.json'
    if args.apply:
        subprocess.run([sys.executable, str(WINDOWS / 'werkzeuge/po_zu_native.py'), str(native_path), *native_args], check=True)
    native = json.loads(native_path.read_text())['locales']
    for locale in TEXT.keys() - {'en'}:
        for key, value in zip(TEXT['en'], TEXT[locale]):
            assert native[locale].get(key) == value, (locale, key)
    if args.preservation_baseline:
        baseline = json.loads(args.preservation_baseline.read_text())
        count = 0
        for platform, base in (('linux', LINUX), ('windows', WINDOWS / 'app')):
            for name, previous in baseline[platform].items():
                if not name.endswith('.po'):
                    continue
                current = {}
                for entry in parser.catalog(base / 'po' / name):
                    current.setdefault(parser.key(entry), []).append(parser.values(entry))
                for old in previous:
                    if any(parser.values(old).values()):
                        assert parser.values(old) in current.get(parser.key(old), []), (platform, name, old['msgid'])
                        count += 1
        print(f'PASS preservation: {count} existing translations retained')
    print('PASS time-zone catalogs: 22 messages, 20 languages, both desktops, MO/JS/native resources')


if __name__ == '__main__':
    main()
