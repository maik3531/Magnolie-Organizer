"""Focused native ASR01/06 preview/review layouts; synthetic capture-only bridge.

Reuses setup only, not the broad editor/designer test matrix. Both desktop source
trees run separately. Native XTest clicks activate actual localized controls.
"""
from pathlib import Path

helpers = Path('/home/source/harness.py').read_text().split('completed = False\n')[0]
helpers = helpers.replace('bindeSchreibTab, htmlZuText,',
    'oeffneSmsPlanung, pruefeSmsPlanung, smsTextAnpassen, setPhone: value => telefonStand = value, bindeSchreibTab, htmlZuText,')
exec(compile(helpers, 'native-editor-setup-only', 'exec'))


def unload(_, dialog):
    assert dialog.get_dialog_type() == WebKit2.ScriptDialogType.BEFORE_UNLOAD_CONFIRM
    dialog.ref(); dialog.confirm_set_confirmed(True)
    def done():
        dialog.close(); dialog.unref(); return False
    GLib.idle_add(done)
    return True


view.connect('script-dialog', unload)
manager = view.get_user_content_manager()
manager.remove_all_scripts()
manager.add_script(WebKit2.UserScript.new("""
window.__MAGNOLIE_SPRACHE__='en'; window.__MAGNOLIE_BRUECKE__='smsTest';
window.events=[]; window.commands=[]; window.saves=[]; window.pending=[];
window.webkit={messageHandlers:{smsTest:{postMessage(raw) {
 const m=JSON.parse(raw); commands.push(m);
 if(m.cmd==='speichern') {saves.push(JSON.parse(m.text)); pending.push(m.id);}
}}}};
window.ackAll=()=>{for(let i=0;i<20 && pending.length;i++)for(const id of pending.splice(0))App.gespeichert({id,ok:true});};
document.addEventListener('click',e=>events.push({kind:'click',trusted:e.isTrusted,text:e.target.textContent}),true);
""", WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))


def click(label, selector='.sms-planung-dialog'):
    point = js('''const root=document.querySelector(SELECTOR), text=MagnolieI18n.gettext(LABEL);
 const button=[...root.querySelectorAll('button')].find(b=>b.textContent===text || b.getAttribute('aria-label')===text);
 if(!button || button.disabled) throw new Error('Missing/enabled button: '+text);
 button.scrollIntoView({block:'center'}); const r=button.getBoundingClientRect();
 return {x:r.left+r.width/2,y:r.top+r.height/2};'''.replace('SELECTOR', json.dumps(selector)).replace('LABEL', json.dumps(label)))
    subprocess.run(['xdotool', 'mousemove', str(round(point['x'])), str(round(point['y'])), 'click', '1'], check=True, timeout=5)
    wait(200)
    assert js('return events.at(-1)?.trusted===true;')


def preview_ready():
    for _ in range(30):
        if js("return !!document.querySelector('.sms-plan-vorschau:not(.verborgen)');"): return
        wait(50)
    raise AssertionError('Actual preview did not appear')


def geometry(locale, width, kind):
    result = js('''const d=document.querySelector('.sms-planung-dialog'),r=d.getBoundingClientRect();
 const outside=[...d.querySelectorAll('input,select,textarea,button,pre')].filter(n=>{
   if(!n.getClientRects().length)return false;const b=n.getBoundingClientRect();return b.left<r.left-1||b.right>r.right+1;
 }).map(n=>n.outerHTML.slice(0,180));
 return {locale:MagnolieI18n.locale(),width:innerWidth,overflow:d.scrollWidth-d.clientWidth,
   outside,dialog:{left:r.left,right:r.right,top:r.top,bottom:r.bottom},height:innerHeight,
   preview:[...d.querySelectorAll('.sms-plan-vorschau:not(.verborgen) pre')].map(n=>n.textContent)};''')
    assert result['overflow'] <= 1 and not result['outside'], result
    assert result['dialog']['left'] >= -1 and result['dialog']['right'] <= result['width'] + 1, result
    assert result['dialog']['top'] >= -1 and result['dialog']['bottom'] <= result['height'] + 1, result
    results.append(dict(case=kind, locale=locale, width=width, geometry=result))
    if locale in ('en', 'de', 'ar', 'hi', 'fr', 'nl'): screen(f'{locale}-{width}-{kind}')


messages = [
 'Review the exact SMS text for every recipient before confirming.',
 'Enabling this plan allows its overdue SMS to be sent while scheduling is on.',
 'Enable this SMS plan', 'Confirm SMS plans', 'Paused — review required', 'Review and enable',
 'Restored pending plans stay paused until you review and enable each plan. Restoring contacts, calendar or notes does not change live SMS plans.']
locales = ['en'] + sorted(p.stem for p in (web / 'i18n').glob('*.js'))
assert len(locales) == 20
completed = False
try:
    for locale in locales:
        for width in (1100, 390):
            window.resize(width, 850); wait(200); load()
            if locale != 'en': js((web / 'i18n' / (locale + '.js')).read_text() + '\nreturn true;')
            js('MagnolieI18n.setLocale(' + json.dumps(locale) + ''');
 const d=OrganizerTest.daten(); d.einstellungen.adressen.smsSchedulingEnabled=true;
 d.einstellungen.regional.homeCountry='GB';
 OrganizerTest.setPhone({peers:[],kdeconnect:{available:true,device_id:'a'.repeat(32),device_fingerprint:'1'.repeat(64)}});
 OrganizerTest.speichereJetzt(); ackAll();
 window.contact={id:'synthetic',vorname:'Synthetic',nachname:'Only',telefone:[{wert:'07700900123',typen:['CELL']},{wert:'07700900124',typen:['CELL']}]};
 OrganizerTest.oeffneSmsPlanung(contact,'07700900123','Привет — 你好'); return true;''')
            translations = js('return ' + json.dumps(messages) + '.map(text=>MagnolieI18n.gettext(text));')
            assert all(translations) and (locale == 'en' or all(a != b for a, b in zip(messages, translations)))
            click('Add another SMS')
            js("const row=document.querySelectorAll('.sms-planung-zeile')[1]; row._werte.text.value='GSM ÄÖÜ €'; row._werte.nummer.selectedIndex=1; return true;")
            click('Schedule SMS'); preview_ready()
            assert js("return [...document.querySelectorAll('.sms-plan-vorschau:not(.verborgen) pre')].map(n=>n.textContent);") == ['?????? - ??', 'GSM ÄÖÜ €']
            assert js('return OrganizerTest.daten().smsPlanung.length;') == 0
            geometry(locale, width, 'batch-preview')
            click('Cancel', '.sms-plan-vorschau:not(.verborgen)')
            assert js("return document.querySelector('.sms-planung-zeile')._werte.text.value;") == 'Привет — 你好'
            click('Schedule SMS'); preview_ready()
            if locale == 'en' and width == 1100:
                click('Confirm SMS plans', '.sms-plan-vorschau:not(.verborgen)')
                assert js("return !!document.querySelector('.sms-planung-dialog') && OrganizerTest.daten().smsPlanung.length===2;")
                assert js("return !commands.some(m=>m.cmd==='kde_sms_senden');")
                js('ackAll(); return true;'); wait(100)
                assert js("return !document.querySelector('.sms-planung-dialog');")
            else:
                click('Cancel', '.sms-plan-vorschau:not(.verborgen)'); click('Close')
            js('''const data=JSON.parse(JSON.stringify(OrganizerTest.daten()));
 data.smsPlanung=['paused-a','paused-b'].map(id=>({id,status:'paused',zeit:1,nummer:'+447700900123',land:'GB',text:'?????? - ??',originalText:'Привет — 你好',clientRef:'',fehler:''}));
 App.gesamtarchivImportiert({ok:true,daten:data}); ackAll(); OrganizerTest.pruefeSmsPlanung(); ackAll();
 OrganizerTest.oeffneSmsPlanung(null); return true;''')
            assert js("return !commands.some(m=>m.cmd==='kde_sms_senden');")
            click('Review and enable'); preview_ready()
            geometry(locale, width, 'restored-plan-review')
            assert js("return document.querySelector('.sms-plan-vorschau:not(.verborgen) pre').textContent;") == '?????? - ??'
            if locale == 'en' and width == 1100:
                click('Enable this SMS plan', '.sms-plan-vorschau:not(.verborgen)')
                assert js("return !commands.some(m=>m.cmd==='kde_sms_senden');")
                js('ackAll(); OrganizerTest.pruefeSmsPlanung(); ackAll(); return true;'); wait(100)
                assert js("return commands.filter(m=>m.cmd==='kde_sms_senden').map(m=>m.clientRef);") == ['plan:paused-a']
                assert js("return OrganizerTest.daten().smsPlanung[1].status;") == 'paused'
            else:
                click('Cancel', '.sms-plan-vorschau:not(.verborgen)')
                assert js("return OrganizerTest.daten().smsPlanung.every(p=>p.status==='paused');")
            print('PASS', args.web, locale, width, 'preview/review/cancel', flush=True)
    completed = True
finally:
    report = dict(completed=completed, web=args.web, seconds=round(time.monotonic()-started, 3), results=results,
        screenshots=screens, sourceSha256={name:hashlib.sha256((web/name).read_bytes()).hexdigest() for name in ('anwendung.js','stil.css')},
        engine=f'WebKitGTK {WebKit2.MAJOR_VERSION}.{WebKit2.MINOR_VERSION}.{WebKit2.MICRO_VERSION}',
        bridge='synthetic capture only; no native backend or phone', cpuAffinity=sorted(os.sched_getaffinity(0)))
    (output/'sms-review-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    window.destroy()
