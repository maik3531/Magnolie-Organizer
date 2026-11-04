#!/usr/bin/env python3
"""Scoped, manually authored occurrence-deletion catalogs (Refs #379).

Only append the four new keys; preserve unrelated catalog bytes. Use each
desktop's existing po_zu_js generator rather than maintaining runtime copies.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEXT = json.loads(Path(__file__).with_suffix('.json').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('occurrence_catalog', ROOT / 'magnolie-organizer/werkzeuge/desktop_pot_merge.py')
    catalogs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalogs)
    assert len(TEXT) == 20 and all(len(row) == 4 and all(row) for row in TEXT.values())
    for base, tools in ((ROOT / 'magnolie-organizer', ROOT / 'magnolie-organizer/werkzeuge'),
                        (ROOT / 'magnolie-organizer-windows/app', ROOT / 'magnolie-organizer-windows/werkzeuge')):
        assert {p.stem for p in (base / 'po').glob('*.po')} == TEXT.keys() - {'en'}
        for locale in ['en', *sorted(TEXT.keys() - {'en'})]:
            target = base / 'po' / ('magnolie-organizer.pot' if locale == 'en' else locale + '.po')
            existing = {entry['msgid']: entry for entry in catalogs.catalog(target) if not entry['obsolete']}
            missing = []
            for key, value in zip(TEXT['en'], TEXT[locale]):
                if key in existing:
                    assert existing[key]['msgstr'] == ('' if locale == 'en' else value), (target, key)
                else:
                    missing.append('\n\n#. Single recurring appointment deletion (Refs #379).\nmsgid ' + json.dumps(key, ensure_ascii=False) +
                                   '\nmsgstr ' + json.dumps('' if locale == 'en' else value, ensure_ascii=False) + '\n')
            if args.apply and missing:
                with target.open('a', encoding='utf-8') as stream:
                    stream.write(''.join(missing))
            elif missing:
                raise AssertionError((target, 'Missing occurrence deletion keys'))
            if locale != 'en':
                subprocess.run(['msgfmt', '--check', '--check-format', '-o', '/dev/null', str(target)], check=True)
                if args.apply:
                    subprocess.run([sys.executable, str(tools / 'po_zu_js.py'), locale, str(target), str(base / 'web/i18n' / (locale + '.js'))], check=True)
    print('PASS: occurrence deletion catalogs, both desktops, all 19 translations')


if __name__ == '__main__':
    main()
