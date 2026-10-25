#!/usr/bin/env python3
"""#220: compile QR dialog messages with existing PO/MO/JS/native tools."""
import gettext
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from editor_locales import ROOT, LINUX, WINDOWS, parser, update_po, module

TEXT = json.loads(Path(__file__).with_suffix('.json').read_text())
READ_ERRORS = {
    'de': 'Der Inhalt ist nicht lesbar.', 'fr': 'Le contenu est illisible.',
    'es': 'El contenido no se puede leer.', 'it': 'Il contenuto non è leggibile.',
    'nl': 'De inhoud is onleesbaar.', 'pt': 'O conteúdo não pode ser lido.',
    'da': 'Indholdet kan ikke læses.', 'nb': 'Innholdet kan ikke leses.',
    'pl': 'Nie można odczytać zawartości.', 'cs': 'Obsah nelze přečíst.',
    'hsb': 'Wobsah njeje čitajomny.', 'ru': 'Содержимое невозможно прочитать.',
    'uk': 'Вміст неможливо прочитати.', 'be': 'Змесціва немагчыма прачытаць.',
    'tr': 'İçerik okunamıyor.', 'hi': 'सामग्री पढ़ी नहीं जा सकती।',
    'ja': '内容を読み取れません。', 'zh_CN': '内容无法读取。', 'ar': 'لا يمكن قراءة المحتوى.'
}
SCAN_HINTS = {
    'de': 'Scannen oder klicken', 'fr': 'Scanner ou cliquer',
    'es': 'Escanear o hacer clic', 'it': 'Scansiona o fai clic',
    'nl': 'Scannen of klikken', 'pt': 'Digitalizar ou clicar',
    'da': 'Scan eller klik', 'nb': 'Skann eller klikk',
    'pl': 'Zeskanuj lub kliknij', 'cs': 'Naskenovat nebo kliknout',
    'hsb': 'Skenować abo kliknyć', 'ru': 'Сканировать или нажать',
    'uk': 'Сканувати або натиснути', 'be': 'Сканаваць або націснуць',
    'tr': 'Tara veya tıkla', 'hi': 'स्कैन करें या क्लिक करें',
    'ja': 'スキャンまたはクリック', 'zh_CN': '扫描或点击', 'ar': 'امسح الرمز أو انقر'
}


def main():
    apply = '--apply' in sys.argv
    assert len(TEXT) == 20 and all(len(row) == 4 and all(row) for row in TEXT.values())
    handbook = ROOT / 'magnolie-handbuch'
    hand_tools = handbook / 'werkzeuge'
    if apply:
        subprocess.run([sys.executable, str(hand_tools / 'pot_erzeugen.py')], check=True)
    hand_data = module(hand_tools / 'pot_erzeugen.py').handbook_data()
    localized = {}
    for page in hand_data['pages']:
        values = page.get('inhaltAnhang')
        if values and 'en' in values:
            localized[values['en']] = values
    for variant in hand_data['variants'].values():
        localized[variant['en']] = variant
    native_args = []
    count = 0
    for base, tools, template_name, domain in ((LINUX, LINUX / 'werkzeuge', 'magnolie-organizer.pot', 'magnolie-organizer'),
        (WINDOWS / 'app', WINDOWS / 'werkzeuge', 'magnolie-organizer.pot', 'magnolie-organizer'),
        (handbook, hand_tools, 'magnolie-handbuch.pot', 'magnolie-handbuch')):
        template = base / 'po' / template_name
        for po in sorted((base / 'po').glob('*.po')):
            before = parser.catalog(po)
            if apply:
                subprocess.run(['msgmerge', '--no-fuzzy', '--update', '--backup=none', str(po), str(template)], check=True, capture_output=True)
            active = {entry['msgid']: entry for entry in parser.catalog(po) if not entry['obsolete']}
            wanted = {}
            for key, value in [*zip(TEXT['en'], TEXT[po.stem]), ('The content is unreadable.', READ_ERRORS[po.stem]), ('Scan or click', SCAN_HINTS[po.stem])]:
                assert key in active, (po, key)
                wanted[key] = value if key == TEXT['en'][3] else active[key].get('msgstr') or value
            if base == handbook:
                for key, entry in active.items():
                    if not entry.get('msgstr') and key in localized:
                        wanted[key] = localized[key][po.stem.replace('_', '-').lower()]
            if apply:
                update_po(po, wanted)
            after = parser.catalog(po)
            by_key = {}
            for entry in after:
                by_key.setdefault(parser.key(entry), []).append(parser.values(entry))
            for previous in before:
                if any(parser.values(previous).values()):
                    assert parser.values(previous) in by_key.get(parser.key(previous), []), (po, previous['msgid'])
                    count += 1
            with tempfile.TemporaryDirectory(prefix='magnolie-qr-locale-', dir='/tmp/opencode') as temporary:
                mo = base / 'locale' / po.stem / 'LC_MESSAGES' / (domain + '.mo') if base != WINDOWS / 'app' else Path(temporary) / 'catalog.mo'
                if apply or base == WINDOWS / 'app':
                    mo.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(['msgfmt', '--check', '--check-format', '-o', str(mo), str(po)], check=True)
                with mo.open('rb') as stream:
                    catalog = gettext.GNUTranslations(stream)
                for key, value in wanted.items():
                    assert catalog.gettext(key) == value, (po, key)
            if apply:
                subprocess.run([sys.executable, str(tools / 'po_zu_js.py'), po.stem, str(po), str(base / 'web/i18n' / (po.stem + '.js'))], check=True)
            if base == WINDOWS / 'app':
                native_args.extend([po.stem, str(po)])
    if apply:
        subprocess.run([sys.executable, str(WINDOWS / 'werkzeuge/po_zu_native.py'), str(WINDOWS / 'app/native-i18n.json'), *native_args], check=True)
    print(f'QR LOCALES PASS: both desktops and handbook, 20 languages; {count} prior translations retained')


if __name__ == '__main__':
    main()
