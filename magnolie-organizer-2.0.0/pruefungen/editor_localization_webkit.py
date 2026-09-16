"""Actual WebKit menus, native XTest activation/history, captured clipboard only.

DOM selection setup and locale/system mocks are explicit fixtures. The complete
production MagnolieI18n core and generated catalogs resolve every displayed label.
"""
from pathlib import Path
import sys

menus_only = '--menus-only' in sys.argv
history_only = '--history-only' in sys.argv
assert menus_only != history_only, 'Choose --menus-only or --history-only to keep each invocation within four minutes.'
for flag in ('--menus-only', '--history-only'):
    if flag in sys.argv:
        sys.argv.remove(flag)

helpers = Path('/home/source/context.py').read_text().split('\nif probe:\n    for kind')[0]
helpers = helpers.replace('zeigeBearbeitenMenue, markierterText, ausAblage, bindeSchreibTab, htmlZuText,',
    'baueSeiteSchrift, AUSZEICHNUNGEN, zeigeBearbeitenMenue, markierterText, ausAblage, bindeSchreibTab, htmlZuText,')
exec(compile(helpers, 'context-edit-helpers', 'exec'))
authored = json.loads(Path('/home/source/editor_locales.json').read_text())


def load_locale(locale):
    if locale != 'en':
        js((web / 'i18n' / (locale + '.js')).read_text() + '; return true;')
    js('MagnolieI18n.setLocale(' + json.dumps(locale) + '); return true;')


def context_state():
    return js("""const m=document.querySelector('.bearbeiten-menue'), r=m.getBoundingClientRect();
return {buttons:[...m.querySelectorAll('button')].map(b=>({text:b.textContent,disabled:b.disabled})),
 undo:document.queryCommandEnabled('undo'),redo:document.queryCommandEnabled('redo'),
 outside:r.left<0||r.top<0||r.right>innerWidth||r.bottom>innerHeight,
 overflow:Math.max(m.scrollWidth-m.clientWidth,...[...m.querySelectorAll('button')].map(b=>b.scrollWidth-b.clientWidth))};""")


def open_menu():
    js('OrganizerTest.zeigeBearbeitenMenue(innerWidth-10,innerHeight-10,field,OrganizerTest.markierterText(field));return true;')
    return context_state()


completed = False
try:
    # All 20 actual menu labels, real action clicks and native undo enablement.
    for locale, words in (() if history_only else authored.items()):
        setup('note', 'abcd')
        load_locale(locale)
        assert all(b['disabled'] for b in open_menu()['buttons'][:2]), (locale, 'empty native history')
        js("document.querySelector('.bearbeiten-menue').remove();return true;")
        key('e')
        # Logical offsets, rather than visual arrow direction in the Arabic UI.
        select(4, 4)
        select(5, 5)
        key('Tab')
        assert summary()['text'] == 'abcde\t', summary()
        select(1, 3)
        before = summary()
        actual = open_menu()
        payload = {} if locale == 'en' else json.loads((web / 'i18n' / (locale + '.js')).read_text().split(', ', 1)[1].rsplit(');', 1)[0])['messages']
        labels = ['Undo', 'Redo', 'Cut', 'Copy', 'Paste', 'Select all']
        expected = [words[0], words[1]] + [payload.get(k, k) for k in labels[2:]]
        expected += [payload.get(symbol, symbol) + payload.get(name, name) for symbol, name in
                     [('B','Bold'),('I','Italic'),('U','Underline'),('S','Strikethrough')]]
        assert [b['text'] for b in actual['buttons']] == expected, (locale, actual, expected)
        assert actual['buttons'][0]['disabled'] == (not actual['undo'])
        assert actual['buttons'][1]['disabled'] == (not actual['redo'])
        assert not actual['outside'] and actual['overflow'] <= 1, (locale, actual)
        assert summary()['selection'] == before['selection'] and summary()['focus'], locale
        hint = js('return OrganizerTest.bindeSchreibTab(document.createElement("textarea")).textContent;')
        assert hint == words[3], (locale, hint)
        settings = js("""const p=document.createElement('div');OrganizerTest.baueSeiteSchrift(p);
return {options:[...p.querySelectorAll('option')].map(o=>o.textContent),text:p.textContent};""")
        assert words[2] in settings['options'], (locale, settings)
        if args.web == 'windows':
            assert words[6] in settings['text'] and 'sudo apt' not in settings['text'], locale
        js("events=[];return true;")
        assert not menu(words[0])['disabled']
        assert summary()['text'] == 'abcde' and summary()['focus'], summary()
        assert len(summary()['inputs']) == 1 and summary()['inputs'][0]['trusted'], summary()
        assert not menu(words[1])['disabled']
        assert summary()['text'] == 'abcde\t', summary()
        key('ctrl+z')
        assert summary()['text'] == 'abcde'
        key('ctrl+shift+z')
        assert summary()['text'] == 'abcde\t'
        # Invoke every common action by its displayed, localized label.
        select(1, 3)
        inputs = len(summary()['inputs'])
        menu(expected[3])
        assert summary()['clipboard'] == 'bc' and len(summary()['inputs']) == inputs
        js("fixtureClipboard='XY';return true;")
        menu(expected[4]); reply()
        assert summary()['text'] == 'aXYde\t', (locale, summary())
        select(1, 3)
        menu(expected[2]); reply()
        assert summary()['text'] == 'ade\t' and summary()['clipboard'] == 'XY', (locale, summary())
        menu(words[0]); menu(words[0])
        assert summary()['text'] == 'abcde\t', (locale, summary())
        menu(expected[5])
        assert summary()['selection'] == 'abcde\t', (locale, summary())
        # All four formatting entries invoke their actual click handlers.
        for index, tag in enumerate(['b', 'i', 'u', 's']):
            select(1, 3)
            open_menu()
            js(f"document.querySelectorAll('.bearbeiten-menue button')[{index + 6}].click();return true;")
            assert js(f"return [...field.querySelectorAll('{tag}')].some(n=>n.textContent==='bc');"), (locale, tag, summary())
        results.append({'kind':locale,'case':'all-ten-menu-clicks-labels-hint-typeface-native-menu-keyboard-history','menu':actual})
    # Real core, regional and mocked system locale; no fake gettext resolver.
    for regional, base in ([] if history_only else [('ja-JP','ja'),('de-AT','de'),('nb-NO','nb'),('zh_CN','zh_CN'),('zh-CN','zh_CN'),('zhCN','en')]):
        load_locale(base)
        for system in (False, True):
            result = js("""Object.defineProperty(navigator,'languages',{configurable:true,get:()=>[REGIONAL]});
MagnolieI18n.setLocale(LOCALE);
return OrganizerTest.bindeSchreibTab(document.createElement('textarea')).textContent;"""
                .replace('REGIONAL', json.dumps(regional)).replace('LOCALE', json.dumps('system' if system else regional)))
            assert result == authored[base][3], (regional, system, result)
        results.append({'kind':regional,'case':'real-i18n-regional-and-system-fallback','base':base})
    for kind in (() if menus_only else ('note','custom','diary')):
        setup(kind, 'abcd')
        key('e', 'Left', 'Right', 'Tab')
        select(1, 3)
        menu('Einfügen'); reply()
        select(1, 3)
        menu('Ausschneiden'); reply()
        assert summary()['text'] == 'ade\t'
        history = []
        for action in ['Rückgängig'] * 4 + ['Wiederholen'] * 4:
            assert not menu(action)['disabled']
            history.append(summary()['text'])
        assert history == ['aXYde\t','abcde\t','abcde','abcd','abcde','abcde\t','aXYde\t','ade\t'], history
        results.append({'kind':kind,'case':'contiguous-native-context-paste-cut-menu-history','history':history})
        # A pending captured clipboard reply may never be applied after history
        # changes, even after redo recreates byte-identical editor content.
        for pending in ('Einfügen','Ausschneiden'):
            select(1, 2)
            menu(pending)
            menu('Rückgängig'); menu('Wiederholen')
            before = summary()
            reply()
            after = summary()
            assert after['text'] == before['text'] and len(after['inputs']) == len(before['inputs']), (kind, pending, after)
        # Disabled/readonly, stale selection and focused-menu keyboard activation.
        select(1, 2)
        open_menu()
        js("field.setAttribute('aria-readonly','true');document.querySelector('.bearbeiten-menue button').click();return true;")
        assert summary()['text'] == 'ade\t'
        js("field.removeAttribute('aria-readonly');return true;")
        for guard in ('readonly','composition','inert'):
            select(1, 2)
            js("""if(G==='readonly')field.setAttribute('aria-readonly','true');
else if(G==='inert')field.setAttribute('inert','');
else field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));return true;""".replace('G===',json.dumps(guard)+'==='))
            states = open_menu()['buttons'][:2]
            assert all(b['disabled'] for b in states), (kind, guard, states)
            js("field.removeAttribute('aria-readonly');field.removeAttribute('inert');field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));return true;")
        if kind != 'diary':
            select(1, 2)
            open_menu()
            js("document.querySelector('.bearbeiten-menue button').focus();return true;")
            key('Return')
            assert summary()['text'] == 'aXYde\t' and summary()['focus'], summary()
        results.append({'kind':kind,'case':'pending-cut-paste-history-invalidation-readonly-composition-inert-keyboard-menu'})
    if not menus_only:
        # A title input has its own captured target and no writing-sheet shortcut
        # adapter. Menu history must follow native focus, never a prior rich range.
        setup('note', 'abcd')
        key('e')
        js("window.original=field;field=document.querySelector('#notiz-titel');field.value='TITLE';field.focus();field.setSelectionRange(5,5);events=[];return true;")
        key('x')
        menu('Rückgängig')
        assert summary()['text'] == 'TITLE' and js("return original.textContent;") == 'abcde', summary()
        menu('Wiederholen')
        assert summary()['text'] == 'TITLEx' and js("return original.textContent;") == 'abcde', summary()
        js("events=[];field.addEventListener('beforeinput',e=>e.preventDefault(),{once:true});return true;")
        menu('Rückgängig')
        assert summary()['text'] == 'TITLEx' and not summary()['inputs'], summary()
        select(1, 3)
        before = summary()['selection']
        open_menu()
        assert summary()['selection'] == before
        js("window.staleUndo=document.querySelector('.bearbeiten-menue button');window.title=field;field=original;field.focus();return true;")
        key('q')
        current = summary()['text']
        js("staleUndo.click();return true;")
        assert summary()['text'] == current and js("return title.value;") == 'TITLEx', summary()
        results.append({'kind':'title-input','case':'native-history-target-cancelled-beforeinput-stale-focus-rejected'})
    completed = True
finally:
    report = {'completed':completed,'web':args.web,'seconds':round(time.monotonic()-started,2),
        'engine':f'WebKitGTK {WebKit2.MAJOR_VERSION}.{WebKit2.MINOR_VERSION}.{WebKit2.MICRO_VERSION}',
        'sourceSha256':hashlib.sha256((web/'anwendung.js').read_bytes()).hexdigest(),
        'peakIsolatedRssKiB':peak_rss_kib,'results':results}
    suite = 'menus' if menus_only else 'history'
    report['suite'] = suite
    (output / ('editor-localization-' + suite + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'results'}), flush=True)
    window.destroy()
