"""Chromium acceptance for real cycle UI; synthetic books only (Refs #803).

Usage: python3 tests/cycle-forecast-browser.py --browser /path/to/chromium --output /tmp/cycle-proof
Requires Playwright and generated normative timezone assets / runtime catalogs.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--browser', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)


def profile(days, view='month'):
    return {'zyklusmarker': [{'id': 'blood', 'art': 'bleeding-light', 'name': 'Blutung · leicht', 'symbol': '💧', 'farbe': '#bd5a67'},
                            {'id': 'medium', 'art': 'bleeding-medium', 'name': 'Blutung · mittel', 'symbol': '💧💧', 'farbe': '#ad3f50'}],
            'tagmarken': [{'datum': day, 'zyklusIds': ['blood']} for day in days],
            'einstellungen': {'ansicht': view, 'regional': {'language': 'de', 'timeZone': 'UTC'},
                'kalender': {'zykluskalenderAn': True, 'zyklusErinnerungen': {'anzeige': True, 'abweichung': True, 'abweichungTage': 7}},
                'allgemein': {'wetter': False}}}

results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=args.browser, headless=True, args=['--no-sandbox'])
    for edition, web in [('linux', ROOT/'magnolie-organizer/web'), ('windows', ROOT/'magnolie-organizer-windows/app/web')]:
        page=browser.new_page(viewport={'width':1280,'height':800})
        errors=[]
        page.on('pageerror',lambda error: errors.append(str(error)))
        def respond(route):
            rel=route.request.url.split('cycle.test/',1)[-1].split('?',1)[0]
            target=(web/(rel or 'index.html')).resolve()
            if target.is_relative_to(web.resolve()) and target.is_file(): route.fulfill(path=str(target))
            else: route.fulfill(status=404,body='')
        page.route('**/*',respond)
        page.add_init_script("""window.__MAGNOLIE_BRUECKE__='test';window.webkit={messageHandlers:{test:{postMessage(){}}}};
        window.cycleTestNow='2026-03-26T12:00:00Z';const BaseDate=Date;
        Date=class extends BaseDate{constructor(...args){super(...(args.length?args:[window.cycleTestNow]));}static now(){return BaseDate.parse(window.cycleTestNow);}};""")
        page.goto('https://cycle.test/',wait_until='load')
        # Explicitly load the generated German catalog to test translated tooltips.
        page.add_script_tag(url='https://cycle.test/i18n/de.js')
        page.evaluate('(data)=>App.init({neu:false,daten:data,regional:{language:"de",timeZone:"UTC"}})',profile(['2026-01-01','2026-01-29','2026-02-26']))
        page.evaluate('OrganizerTest.oeffneBuch()')
        page.locator('#deckel').wait_for(state='hidden')
        page.locator('[data-cycle-confirm="2026-03-26"]').wait_for(state='visible')
        page.screenshot(path=str(args.output/f'{edition}-forecast.png'),full_page=True)
        ghost=page.locator('[data-cycle-confirm="2026-03-26"]')
        assert ghost.locator('path').get_attribute('stroke-dasharray') is None
        assert '2026' in ghost.get_attribute('title') and 'geschätzt' in ghost.get_attribute('title').lower()
        before=page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')
        # Keyboard activation must reach the same guarded confirmation as a mouse.
        ghost.focus();page.keyboard.press('Enter')
        page.locator('#zyklus-bestaetigung').wait_for(state='visible')
        assert page.locator('#zyklus-bestaetigung-speichern').is_disabled()
        page.screenshot(path=str(args.output/f'{edition}-confirmation.png'),full_page=True)
        page.keyboard.press('Escape')
        assert page.locator('#zyklus-bestaetigung').count()==0
        assert page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')==before
        ghost.click()
        page.locator('#zyklus-bestaetigung').wait_for(state='visible')
        page.keyboard.press('Escape')
        assert page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')==before
        # Expired ghosts become only an explanatory dashed hint, never data.
        page.evaluate("window.cycleTestNow='2026-03-29T12:00:00Z'; OrganizerTest.aendereTagmarkenBereich('2020-01-01','2020-01-01',null,null)")
        assert page.locator('[data-cycle-estimate]').count()==0
        hint=page.locator('[data-cycle-hint="2026-03-26"]')
        assert hint.locator('path').get_attribute('stroke-dasharray')=='2 2'
        assert hint.get_attribute('title')==hint.get_attribute('aria-label')
        page.screenshot(path=str(args.output/f'{edition}-expired-hint.png'),full_page=True)
        assert page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')==before
        results.append({'edition':edition,'scenario':'forecast-confirm-cancel-expiry','passed':True,'hintTooltip':hint.get_attribute('title')})
        # A hint opens an explicit, editable pause; no cause is inferred.
        hint.click()
        page.locator('#zyklus-pause').wait_for(state='visible')
        assert page.locator('#zyklus-pause-speichern').is_disabled()
        page.locator('#zyklus-pause-grund').select_option('pregnancy')
        page.screenshot(path=str(args.output/f'{edition}-pregnancy-pause-dialog.png'),full_page=True)
        page.locator('#zyklus-pause-speichern').click()
        assert page.evaluate('OrganizerTest.zyklusStatistik().pauseUntil')=='2026-12-29'
        assert page.evaluate('OrganizerTest.zyklusStatistik().paused') is True
        assert page.locator('[data-cycle-hint], [data-cycle-estimate]').count()==0
        assert 'Schwangerschaft' in page.locator('.zyklus-prognose-kasten').inner_text()
        assert page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')==before
        page.screenshot(path=str(args.output/f'{edition}-pregnancy-paused.png'),full_page=True)
        page.evaluate("window.cycleTestNow='2026-03-30T12:00:00Z'; OrganizerTest.aendereTagmarkenBereich('2026-03-30','2026-03-30',null,['blood'])")
        page.locator('#zyklus-wiederaufnahme').wait_for(state='visible')
        assert 'ärztlich' in page.locator('#zyklus-wiederaufnahme').inner_text()
        page.screenshot(path=str(args.output/f'{edition}-new-period-confirmation.png'),full_page=True)
        page.locator('#zyklus-wiederaufnahme-behalten').click()
        assert page.evaluate('OrganizerTest.zyklusStatistik().paused') is True
        page.evaluate("OrganizerTest.aendereTagmarkenBereich('2026-03-30','2026-03-30',null,[]); OrganizerTest.aendereTagmarkenBereich('2026-03-30','2026-03-30',null,['blood'])")
        page.locator('#zyklus-wiederaufnahme-bestaetigen').click()
        assert page.evaluate('OrganizerTest.zyklusStatistik().resumedOn')=='2026-03-30'
        assert page.evaluate('OrganizerTest.zyklusStatistik().starts')==['2026-03-30']
        results.append({'edition':edition,'scenario':'self-reported-pause-and-explicit-new-period','passed':True})
        # Menopause/medication can be indefinite, and end without inventing data.
        for reason in ['menopause','medication']:
            page.locator('#zyklus-pause-oeffnen').click()
            page.locator('#zyklus-pause-grund').select_option(reason)
            assert page.locator('#zyklus-pause-unbefristet').is_checked()
            page.locator('#zyklus-pause-speichern').click()
            assert page.evaluate('OrganizerTest.zyklusStatistik().pauseUntil') is None
            assert page.evaluate('OrganizerTest.zyklusStatistik().pauseReason')==reason
        page.screenshot(path=str(args.output/f'{edition}-medication-paused.png'),full_page=True)
        current_marks=page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')
        page.locator('#zyklus-pause-oeffnen').click()
        page.locator('#zyklus-pause-beenden').click()
        assert page.evaluate('OrganizerTest.zyklusStatistik().paused') is False
        assert page.evaluate('JSON.stringify(OrganizerTest.daten().tagmarken)')==current_marks
        results.append({'edition':edition,'scenario':'indefinite-menopause-medication-pause','passed':True})
        # Many details cannot push the day grids off screen.
        days=['2026-01-01','2026-01-29','2026-02-26']+[f'2026-04-{i:02}' for i in range(9,18)]
        page.evaluate("window.cycleTestNow='2026-04-18T12:00:00Z'")
        page.evaluate('(data)=>App.init({neu:false,daten:data,regional:{language:"de",timeZone:"UTC"}})',profile(days,'day'))
        page.evaluate('OrganizerTest.oeffneBuch()')
        page.locator('#deckel').wait_for(state='hidden')
        for width,height in [(1280,800),(1024,768)]:
            page.set_viewport_size({'width':width,'height':height})
            page.locator('.zyklus-prognose-details').evaluate('(element)=>element.open=true')
            page.wait_for_timeout(150)
            metrics=page.evaluate("""()=>{const selectors=['#inhalt-links .stunden-raster','#inhalt-rechts .stunden-raster','.zyklus-prognose-kasten'];return Object.fromEntries(selectors.map(s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return[s,{height:e.clientHeight,top:r.top,bottom:r.bottom,scrollHeight:e.scrollHeight}]}))}""")
            assert metrics['#inhalt-links .stunden-raster']['height']>=60,metrics
            assert metrics['#inhalt-rechts .stunden-raster']['height']>=60,metrics
            assert abs(metrics['#inhalt-links .stunden-raster']['top']-metrics['#inhalt-rechts .stunden-raster']['top'])<=1,metrics
            results.append({'edition':edition,'scenario':'day-layout','viewport':[width,height],'passed':True,'metrics':metrics})
            page.screenshot(path=str(args.output/f'{edition}-day-{width}.png'),full_page=True)
        assert not errors,errors
        page.close()
    browser.close()
(args.output/'browser-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(f'PASS: {len(results)} Chromium scenarios, both real desktop frontends; zero page errors.')
