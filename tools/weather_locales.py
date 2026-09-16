"""Apply the explicitly authored weather fallback translations and generate catalogs."""
import importlib.util
import gettext
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / 'magnolie-organizer-2.0.0'
WINDOWS = ROOT / 'Magnolie-Organizer-Windows-2.0.0'
messages = json.loads(Path(__file__).with_suffix('.json').read_text())
assert len(messages) == 20 and all(messages.values())
spec = importlib.util.spec_from_file_location('editor_locale_helpers', ROOT / 'tools/editor_locales.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
native = []
for base, tools in ((LINUX, LINUX / 'werkzeuge'), (WINDOWS / 'app', WINDOWS / 'werkzeuge')):
    catalogs = sorted((base / 'po').glob('*.po'))
    assert {path.stem for path in catalogs} == messages.keys() - {'en'}
    for po in catalogs:
        value = messages[po.stem]
        assert value != messages['en']
        helpers.update_po(po, {messages['en']: value})
        subprocess.run([sys.executable, str(tools / 'po_zu_js.py'), po.stem, str(po),
                        str(base / 'web/i18n' / (po.stem + '.js'))], check=True)
        js = (base / 'web/i18n' / (po.stem + '.js')).read_text()
        payload = json.loads(js[js.index(', ') + 2:js.rindex(');')])
        assert payload['messages'][messages['en']] == value
        if base == LINUX:
            target = LINUX / 'locale' / po.stem / 'LC_MESSAGES/magnolie-organizer.mo'
            subprocess.run(['msgfmt', '--check', '--check-format', '-o', str(target), str(po)], check=True)
            with target.open('rb') as stream:
                assert gettext.GNUTranslations(stream).gettext(messages['en']) == value
        else:
            native.extend([po.stem, str(po)])
subprocess.run([sys.executable, str(WINDOWS / 'werkzeuge/po_zu_native.py'),
                str(WINDOWS / 'app/native-i18n.json'), *native], check=True)
compiled = json.loads((WINDOWS / 'app/native-i18n.json').read_text())['locales']
for locale in messages.keys() - {'en'}:
    assert compiled[locale][messages['en']] == messages[locale]
print('Weather fallback notice: all 20 languages generated.')
