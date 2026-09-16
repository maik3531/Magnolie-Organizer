"""Source parity, manual catalog completeness and current disposable macOS projection."""
import json
from pathlib import Path
import re
import tempfile

from editor_locales import ROOT, LINUX, WINDOWS, TEXT, main, module


def function(source, name):
    start = source.index('  function ' + name + '(')
    end = re.search(r'^  (?:function |/\*|const |let |for \()', source[start + 3:], re.M)
    assert end, name
    return source[start:start + 3 + end.start()].rstrip()


def test_desktop_editor_parity():
    linux = (LINUX / 'web/anwendung.js').read_text()
    windows = (WINDOWS / 'app/web/anwendung.js').read_text()
    names = ('bindeSchreibTab', 'erfasseBearbeitungsAuswahl', 'stelleBearbeitungsAuswahlHer',
             'bearbeitungsAuswahlGueltig', 'nativeTextBearbeitung', 'nativeHistorieMoeglich',
             'zeigeBearbeitenMenue', 'ausAblage')
    for name in names:
        assert function(linux, name) == function(windows, name), name
    assert (LINUX / 'web/i18n.js').read_bytes() == (WINDOWS / 'app/web/i18n.js').read_bytes()
    assert 'texte[window.MagnolieI18n' not in linux + windows
    assert '_("As usual (print)")' not in linux + windows
    assert 'sudo apt' not in function(windows, 'baueSeiteSchrift')


def test_manual_catalogs():
    main()


def test_current_disposable_macos_projection():
    projector = module(ROOT / 'Magnolie-Organizer-macOS-Beta/tools/project_ui.py')
    snapshot = projector.inputs()
    with tempfile.TemporaryDirectory(prefix='editor-beta-', dir='/tmp/opencode') as temp:
        target = Path(temp) / 'UI'
        projector.project(snapshot, target)
        native = json.loads((target / 'native-i18n.json').read_text())
        for locale, words in TEXT.items():
            if locale == 'en':
                continue  # English is the source-language branch of the native runtime.
            row = native[locale.replace('_', '-').lower()]
            for index in (0, 1, 2, 3, 7):
                assert row.get(TEXT['en'][index]) == words[index], (locale, index)
            assert (target / 'web/i18n' / (locale + '.js')).read_bytes() == (LINUX / 'web/i18n' / (locale + '.js')).read_bytes()
        source = (LINUX / 'web/anwendung.js').read_text()
        projected = (target / 'web/anwendung.js').read_text()
        for name in ('zeigeBearbeitenMenue', 'nativeTextBearbeitung', 'nativeHistorieMoeglich', 'bindeSchreibTab'):
            assert function(source, name) == function(projected, name)
        assert not (target / 'ProjectionManifest.json').exists()
    assert projector.inventory(snapshot) == projector.inventory(projector.inputs())
