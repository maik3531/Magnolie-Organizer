const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto,createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {JSDOM,VirtualConsole} = require('jsdom');
const root = path.resolve(__dirname,'..');
const web = path.join(root,'app/build/generated/projection/assets/web');
const read = f => fs.readFileSync(path.join(web,f),'utf8');
const wait = () => new Promise(resolve=>setTimeout(resolve,30));
let passed=0;
const ok = (condition,label) => {assert.ok(condition,label); passed++; console.log('PASS '+label);};
(async()=>{
  const beta=JSON.parse(fs.readFileSync(path.join(root,'web/beta-i18n.json')));
  ok(Object.keys(beta).length===20 && Object.values(beta).every(x=>x.length===4 && x.every(Boolean)), '20 manual beta locales');
  const canonical=fs.readFileSync(path.join(root,'../magnolie-organizer/web/anwendung.js'),'utf8');
  const projected=read('anwendung.js');
  const reviewed=projected.replace(/\/\*TABLET_ICS_([A-Z_]+)_BEGIN\*\/[\s\S]*?\/\*TABLET_ICS_\1_END\*\//g,'').replace(/\/\*TABLET_DAV_([A-Z_]+)_BEGIN\*\/[\s\S]*?\/\*TABLET_DAV_\1_END\*\//g,'');
  ok(reviewed.replace('  window.MagnolieTabletActions = { afterSave: (action, failed) => navigiereMitGuard(() => nachDauerhaftemSpeichern(action, failed)), persist: (action, failed) => nachDauerhaftemSpeichern(action, failed), exportCalendar: art => starteExport(art) };\n','').replace('    { id: "regional", name: msgid("Language and regional display") },\n','').replace('  async function aktualisiereAutomatischeZeitzone() { return;', '  async function aktualisiereAutomatischeZeitzone() {')===canonical,
    'generated core differs only by reviewed guard, regional entry, DAV prefixes and native detection suppression');
  const fontCss=read('desktop-fonts.css');
  assert.match(read('index.html'),/href="desktop-fonts\.css"/);
  for (const family of ['Noto Serif','DejaVu Sans','Noto Sans','DejaVu Sans Mono','Magnolie Handschrift'])
    assert.ok(fontCss.includes('font-family: "'+family+'"'),family+' must be bundled');
  for (const match of fontCss.matchAll(/url\("([^"]+)"\)/g)) {
    assert.deepEqual(fs.readFileSync(path.join(web,match[1])),
      fs.readFileSync(path.join(root,'../magnolie-organizer-windows/app/web',match[1])));
  }
  for (const license of ['DejaVu-LIZENZ.txt','Noto-LIZENZ.txt','Z003-LIZENZ.txt'])
    assert.ok(read('schriften/'+license).length>100);
  ok(true,'desktop font families, faces and licenses use the live bundled Windows bytes');
  let disk=null, messages=[], failSave=false;
  let accountChanges=0, credential='', accountCounter=1, discoveryError='';
  let account={kontoArt:'nextcloud',davAktiv:false,briefkastenAktiv:false,url:'',benutzer:'',
    kennwortVorhanden:false,revision:accountCounter.toString(16).padStart(64,'0'),zustand:'disabled',fehler:''};
  const calendars=[{uid:'nextcloud-caldav:available',name:'Native DAV calendar',art:'nextcloud-caldav',supportsVtodo:false}];
  const addressBooks=[{uid:'nextcloud-carddav:available',name:'Native DAV contacts',art:'nextcloud-carddav'}];
  const sourceSnapshot=()=>({verfuegbar:!discoveryError,buchOk:true,kalender:calendars,adressbuecher:addressBooks,
    fehler:discoveryError,systemAccountSyncImplemented:false});
  const davCallbacks=['baumBriefkastenStatus','baumBriefkastenGespeichert','baumBriefkastenPruefung','baumDavPruefung','edsStatus'];
  function callbackForwarding(target,expected,label) {
    let forwarded=0;
    const originals=Object.fromEntries(davCallbacks.map(name=>[name,target.App[name]]));
    for(const name of davCallbacks) target.App[name]=()=>{forwarded++;};
    try { for(const name of davCallbacks) target.Tablet.receive({callback:name,payload:{revision:'a'.repeat(64)}}); }
    finally { for(const name of davCallbacks) target.App[name]=originals[name]; }
    ok(forwarded===expected,label);
  }
  const browserErrors=[];
  async function open({holdReady=false}={}) {
    const session=webcrypto.randomUUID(); let revision=webcrypto.randomUUID();
    const console=new VirtualConsole(); console.on('jsdomError',error=>browserErrors.push(error));
    const dom=new JSDOM(read('index.html'),{url:'https://appassets.androidplatform.net/assets/web/index.html',
      runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
    const w=dom.window;
    dom.authority=()=>({session,revision});
    w.TextEncoder=TextEncoder; w.TextDecoder=TextDecoder;
    Object.defineProperty(w,'crypto',{value:webcrypto});
    w.Element.prototype.getAnimations=()=>[];
    w.TabletNative={postMessage(text) {
      const m=JSON.parse(text); messages.push(m);
      setTimeout(()=>{
        if (!w.document) return;
        if(m.cmd==='bereit') w.Tablet.receive({callback:'init',payload:{daten:disk,session,revision}});
        if(['baum_briefkasten_status','baum_briefkasten_speichern','baum_briefkasten_pruefen','baum_dav_pruefen','eds_status'].includes(m.cmd)) {
          assert.equal(m.session,session); assert.equal(m.revision,revision);
          if(m.cmd==='baum_briefkasten_status') w.Tablet.receive({callback:'baumBriefkastenStatus',payload:{...account}});
          if(m.cmd==='eds_status') w.Tablet.receive({callback:'edsStatus',payload:sourceSnapshot()});
          if(m.cmd==='baum_briefkasten_speichern') {
            const conflict=m.expectedRevision!==account.revision;
            if(!conflict) {
              if(m.kennwortLoeschen) credential=''; else if(m.anwendungskennwort) credential=m.anwendungskennwort;
              account={...account,kontoArt:m.kontoArt,davAktiv:m.davAktiv,briefkastenAktiv:m.briefkastenAktiv,
                url:m.url,benutzer:m.benutzer,kennwortVorhanden:!!credential,fehler:'',
                revision:(++accountCounter).toString(16).padStart(64,'0')}; accountChanges++;
            }
            w.Tablet.receive({callback:'baumBriefkastenGespeichert',payload:{...account,ok:!conflict,
              persisted:!conflict,verified:!conflict,fehler:conflict?'Account changed; reload its current state.':''}});
          }
          if(m.cmd==='baum_briefkasten_pruefen') {
            assert.equal(m.expectedRevision,account.revision);
            w.Tablet.receive({callback:'baumBriefkastenPruefung',payload:{...account,fehler:discoveryError}});
          }
        }
        if(m.cmd==='tablet_loaded' && !holdReady) w.Tablet.receive({callback:'ready',payload:{session,revision}});
        if(m.cmd==='speichern') {
          assert.equal(m.session,session); assert.equal(m.revision,revision);
          if(!failSave) disk=JSON.parse(m.text);
          if(!failSave) revision=webcrypto.randomUUID();
          w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:!failSave,session,expectedRevision:m.revision,revision}});
        }
      },0);
    }};
    for(const f of ['beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','mcp-protocol.js','anwendung.js']) w.eval(read(f));
    await wait(); await wait();
    return dom;
  }
  let dom=await open(), w=dom.window, T=w.OrganizerTest;
  ok(!!disk && w.document.querySelector('#buch.offen'),'real binder initializes through JSON bridge and saves');
  ok(w.document.querySelector('#seite-links') && w.document.querySelector('#seite-rechts'),'both canonical binder pages present');
  T.daten().termine.push({id:'calendar-1',datum:'2030-05-10',zeit:'10:00',titel:'Calendar beta',wiederholung:{art:'none'}});
  T.daten().aufgaben.push({id:'task-1',faellig:'2030-05-10',faelligZeit:'11:00',titel:'Task beta',erinnern:true,erledigt:false});
  T.daten().kontakte.push({id:'contact-1',vorname:'Beta',nachname:'Tablet',emails:['local@example.test'],
    telefone:[{wert:'+12025550123',typen:['CELL']}],email:'local@example.test'});
  T.daten().notizen.push({id:'note-1',titel:'Beta note',text:'<b>Local</b>',notizbuchId:T.daten().notizbuecher[0].id,anhaenge:[]});
  T.daten().customOrganizer.modules.push({id:'module-1',type:'tasks',title:'Garden',reminders:true,
    items:[{id:'item-1',title:'Water',due:'2030-05-10',time:'12:00',remind:true,done:false}]});
  T.speichereJetzt(); await wait();
  ok(disk.termine.length===1 && disk.aufgaben.length===1 && disk.kontakte.length===1 && disk.notizen.length===1,
    'calendar/tasks/contacts/notes use canonical JSON persistence');
  let alarms=w.Tablet.alarms();
  ok(alarms.some(x=>x.section==='kalender') && alarms.some(x=>x.section==='aufgaben'&&!x.custom) && alarms.some(x=>x.custom),
    'calendar, tasks and consented custom alarm projections');
  T.daten().customOrganizer.modules[0].reminders=false;
  ok(!w.Tablet.alarms().some(x=>x.custom),'custom module revocation removes alarms');
  T.daten().termine[0].wiederholung={art:'weekly'};
  ok(!w.Tablet.alarms().some(x=>x.section==='kalender'),'unsupported recurrence is never scheduled as a false one-off');
  T.speichereJetzt(); await wait();
  const before=JSON.stringify(disk);
  w.Tablet.validateImport(before);
  dom.window.close(); dom=await open(); w=dom.window; T=w.OrganizerTest;
  ok(T.daten().termine[0].titel==='Calendar beta' && T.daten().customOrganizer.modules[0].items[0].title==='Water',
    'reload restores actual calendar and custom data');
  for(const section of ['kalender','aufgaben','adressen','notizen','planer','gesundheit']) {
    await T.wechsel(section); ok(w.document.querySelector('#inhalt-links').childElementCount>0,'canonical section renders: '+section);
  }
  T.zustand().adressen.auswahlId='contact-1'; T.zustand().adressen.modus='ansehen';
  await T.wechsel('adressen'); await wait();
  const sms=w.document.querySelector('.kontakt-sms'), call=w.document.querySelector('.kontakt-anruf');
  assert.ok(sms && call,'real contact communication controls must exist');
  const priorMessages=messages.length;
  sms.click(); call.click();
  sms.dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
  ok(sms.disabled && call.disabled && messages.length===priorMessages && !w.document.querySelector('#sms-plan-dialog'),
    'actual contact SMS/call actions and SMS context planning are disabled without sending');
  await T.wechsel('notizen'); await wait();
  const pdfButtons=[...w.document.querySelectorAll('.notiz-zusatz-knopf')].filter(b=>b.textContent==='PDF');
  ok(pdfButtons.length===1 && pdfButtons[0].disabled,
    'unsupported attachment picker is visibly disabled');
  const tabHelp='Tab: insert a tab stop. Shift+Tab: previous field. Ctrl+Tab: next field.';
  assert.ok(w.document.querySelector('.schreib-tab-hinweis'),'canonical context/Tab help rendered');
  for(const locale of Object.keys(beta)) {
    w.MagnolieI18n.setLocale(locale);
    for(const key of ['Undo','Redo',tabHelp,'School holidays are not available for this region.']) {
      const value=w.MagnolieI18n.gettext(key);
      assert.ok(value && (locale==='en' || value!==key),locale+' / '+key);
    }
  }
  w.MagnolieI18n.setLocale('en');
  ok(true,'current Undo/Redo, context Tab help and school-holiday keys resolve in all 20 locales');
  T.daten().einstellungen.erinnerung.an=false;
  w.Tablet.receive({callback:'notificationConsent',payload:{enabled:true,...dom.authority()}}); await wait();
  ok(T.daten().einstellungen.erinnerung.an && disk.einstellungen.erinnerung.an,
    'explicit native consent re-enables imported reminder projection and persists it');
  T.oeffneEinstellungen(); await wait();
  ok(!w.document.querySelector('#einst-tab-sync').disabled && w.document.querySelector('#einst-tab-baum').disabled,
    'DAV setup tab is available while desktop tree integration stays disabled');
  const originalSync=structuredClone(T.daten().einstellungen.sync);
  Object.assign(T.daten().einstellungen.sync,{kalenderUid:'imported-offline-calendar',kalenderUids:['imported-offline-calendar'],
    adressbuchUid:'imported-offline-book'});
  T.speichereJetzt(); await wait();
  const accountProfile=JSON.stringify(T.daten());
  w.document.querySelector('#einst-tab-sync').click(); await wait(); await wait();
  ok(!!w.document.querySelector('#nextcloud-konto') && !w.document.querySelector('#graph-konto') &&
    !w.document.querySelector('#nextcloud-briefkasten') && !w.document.querySelector('#telefon-kontakte-quelle') &&
    w.document.querySelector('#tablet-dav-limit').textContent.includes('read-only discovery'),
    'actual canonical DAV form is isolated from Linux, Graph, mailbox and phone configuration');
  const form=w.document.querySelector('#nextcloud-konto');
  ok(!form.querySelector('#nextcloud-dav-an').disabled && !form.querySelector('#briefkasten-url').disabled,
    'capability exceptions enable only actual native DAV account controls');
  const input=(id,value)=>{const field=w.document.getElementById(id);field.value=value;field.dispatchEvent(new w.Event('input',{bubbles:true}));};
  const namedButton=label=>[...w.document.querySelectorAll('#nextcloud-konto button')].find(button=>button.textContent===label);
  const serviceFailure={ok:false,fehler:'Native account service unavailable',fehlerCode:'native_account_unavailable'};
  w.Tablet.receive({callback:'baumBriefkastenStatus',payload:serviceFailure}); await wait();
  ok(namedButton('Save').disabled && w.document.getElementById('briefkasten-url').disabled &&
    !w.document.getElementById('tablet-dav-refresh').disabled &&
    Object.keys(serviceFailure).sort().join(',')==='fehler,fehlerCode,ok' &&
    JSON.stringify(T.daten())===accountProfile,
    'missing native account snapshot disables mutation without inventing account revision or changing profile');
  const beforeRefresh=messages.filter(m=>m.cmd==='baum_briefkasten_status').length;
  w.document.getElementById('tablet-dav-refresh').click(); await wait(); await wait();
  ok(messages.filter(m=>m.cmd==='baum_briefkasten_status').length===beforeRefresh+1 &&
    !namedButton('Save').disabled && !w.document.getElementById('briefkasten-url').disabled &&
    !w.document.getElementById('tablet-dav-refresh') && JSON.stringify(T.daten())===accountProfile &&
    JSON.stringify(disk)===accountProfile,
    'explicit read-only Refresh obtains real native status and recovers account controls without changing profile');
  input('briefkasten-url',' https://dav.example.test/remote.php/dav ');
  input('briefkasten-benutzer',' synthetic-dav-user ');
  input('briefkasten-kennwort','public-synthetic-app-password');
  const enable=w.document.getElementById('nextcloud-dav-an'); enable.checked=true;enable.dispatchEvent(new w.Event('change',{bubbles:true}));
  const firstRevision=account.revision;
  namedButton('Save').click(); await wait(); await wait();
  const accountSave=messages.filter(m=>m.cmd==='baum_briefkasten_speichern').at(-1);
  ok(accountSave?.expectedRevision===firstRevision && accountSave.kontoArt==='nextcloud' && accountSave.davAktiv &&
    accountSave.briefkastenAktiv===false && accountSave.url==='https://dav.example.test/remote.php/dav' &&
    accountSave.benutzer==='synthetic-dav-user' && accountSave.anwendungskennwort==='public-synthetic-app-password' &&
    accountChanges===1 && w.document.getElementById('briefkasten-kennwort').value==='',
    'actual DAV GUI save sends account revision and app password to the native account service only');
  T.speichereJetzt();await wait();
  ok(JSON.stringify(T.daten())===accountProfile && JSON.stringify(disk)===accountProfile &&
    !JSON.stringify(disk).includes('synthetic-dav-user') && !JSON.stringify(disk).includes('public-synthetic-app-password') &&
    !JSON.stringify(disk).includes('dav.example.test'),
    'account save and saved callback never insert credentials or account configuration into Organizer JSON');
  account={...account,revision:(++accountCounter).toString(16).padStart(64,'0')};
  const staleRevision=accountSave.expectedRevision;
  namedButton('Save').click(); await wait();await wait();
  const staleSave=messages.filter(m=>m.cmd==='baum_briefkasten_speichern').at(-1);
  ok(staleSave.expectedRevision!==account.revision && staleSave.expectedRevision!==staleRevision && accountChanges===1 &&
    w.document.getElementById('nextcloud-status').textContent.includes('Account changed'),
    'stale GUI revision is not silently replaced and native conflict cannot change account or book');
  discoveryError='Synthetic DAV discovery is unavailable';
  namedButton('Test connection').click();await wait();await wait();
  const connection=messages.filter(m=>m.cmd==='baum_briefkasten_pruefen').at(-1);
  ok(connection.expectedRevision===account.revision && w.document.getElementById('sync-status').textContent.includes(discoveryError) &&
    w.document.getElementById('sync-jetzt').disabled && JSON.stringify(T.daten())===accountProfile,
    'actual connection-test GUI uses current account revision; failed discovery preserves the full document');
  const retained=w.document.querySelector('#sync-wahl input[data-kalender-uid="imported-offline-calendar"]');
  const available=w.document.querySelector('#sync-wahl input[data-kalender-uid="nextcloud-caldav:available"]');
  const bookChoice=w.document.querySelector('#sync-wahl select');
  ok(retained?.checked && !!available && bookChoice?.value==='imported-offline-book' &&
    [...bookChoice.options].some(option=>option.value==='nextcloud-carddav:available'),
    'canonical source renderer retains unavailable imported UIDs alongside cached native DAV choices');
  available.checked=true;available.dispatchEvent(new w.Event('change',{bubbles:true}));
  bookChoice.value='nextcloud-carddav:available';bookChoice.dispatchEvent(new w.Event('change',{bubbles:true}));
  T.speichereJetzt();await wait();
  ok(disk.einstellungen.sync.kalenderUids.includes('imported-offline-calendar') &&
    disk.einstellungen.sync.kalenderUids.includes('nextcloud-caldav:available') &&
    disk.einstellungen.sync.adressbuchUid==='nextcloud-carddav:available',
    'actual cached-source controls persist through canonical UID selection handlers without dropping an offline calendar');
  const beforeUnsupportedSync=messages.length;
  T.starteSync(false); await wait();
  ok(messages.length===beforeUnsupportedSync && w.document.getElementById('sync-jetzt').disabled &&
    w.document.getElementById('zettel').textContent.includes('not implemented'),
    'synchronization stays explicitly unsupported even after account configuration and successful discovery');
  callbackForwarding(w,davCallbacks.length,'DAV callback router forwards all supported callbacks only in the loaded writable page');
  discoveryError=''; T.daten().einstellungen.sync=originalSync;T.speichereJetzt();await wait();
  Object.assign(T.daten().einstellungen.ort,{land:'DE',region:'DE-BE',ferien:true,alleRegionen:false});
  w.document.querySelector('#einst-tab-ort').click(); await wait();
  ok(!w.document.querySelector('#ort-abrufen').disabled && !w.document.querySelector('#ort-jahre').disabled &&
    !w.document.querySelector('#ort-ferien').disabled && !w.document.querySelector('#tablet-holiday-limit'),
    'native holiday retrieval and period controls are available');
  w.document.querySelector('#ort-abrufen').click(); await wait();
  const holidayRequest=messages.filter(m=>m.cmd==='feiertage').at(-1);
  ok(holidayRequest && holidayRequest.land==='DE' && holidayRequest.region==='DE-BE' &&
    holidayRequest.session===dom.authority().session && Array.isArray(holidayRequest.jahre),
    'canonical regional holiday request carries actual native document authority');
  const holidayYear=holidayRequest.jahre[0], holidayDate=holidayYear+'-12-25';
  w.Tablet.receive({callback:'feiertageErgebnis',payload:{jahre:[holidayYear],feiertage:[{
    von:holidayDate,bis:holidayDate,name:'Synthetic holiday',art:'public-holiday',country:'DE',nationwide:true,regions:[]}]}});
  await wait(); T.speichereJetzt(); await wait();
  ok(T.daten().feiertage.some(h=>h.name==='Synthetic holiday') && disk.feiertage.some(h=>h.name==='Synthetic holiday'),
    'native holiday result uses the canonical importer and durable save protocol');
  const holidayBefore=JSON.stringify(T.daten().feiertage);
  w.Tablet.receive({callback:'feiertageErgebnis',payload:{fehler:'Synthetic HTTP failure'}});
  ok(JSON.stringify(T.daten().feiertage)===holidayBefore,'failed retrieval preserves the complete existing holiday cache');
  ok(w.document.querySelector('#ort-zeitzonenmanagement').disabled,
    'native-only time-zone management cannot open an unsupported MCP transaction');
  w.document.querySelector('#einst-tab-regional').click(); await wait();
  w.document.querySelector('#regional-sprache').value='en';
  w.document.querySelector('#regional-formatgebiet').value='en-GB';
  w.document.querySelector('#regional-zeitzone').value='Europe/Berlin';
  const regionalCommands=messages.length;
  w.document.querySelector('#regional-speichern').click(); await wait(); await wait();
  ok(disk.einstellungen.regional.formatLocale==='en-GB' &&
    disk.einstellungen.regional.timeZone==='Europe/Berlin' &&
    w.document.querySelector('#tablet-status').textContent.includes('Regional settings saved.') &&
    !w.document.querySelector('#regional-speichern').disabled,
    'local regional form persists through native save ACK without desktop MCP');
  assert.ok(messages.slice(regionalCommands).every(m=>['speichern','erinnerung_einrichten'].includes(m.cmd)));
  disk.einstellungen.regional.timeZoneManagement='automatic';
  dom.window.close(); dom=await open(); w=dom.window; T=w.OrganizerTest;
  const nativeBeforeAutomatic=messages.length, rejectedBeforeAutomatic=Array.from(w.Tablet.rejected);
  w.dispatchEvent(new w.Event('focus')); await wait();
  assert.deepEqual(Array.from(w.Tablet.rejected),rejectedBeforeAutomatic);
  ok(T.daten().einstellungen.regional.timeZoneManagement==='automatic' && messages.length===nativeBeforeAutomatic,
    'imported automatic time-zone mode is preserved without unsupported native MCP polling');
  ok(T.daten().einstellungen.regional.formatLocale==='en-GB' &&
    T.daten().einstellungen.regional.timeZone==='Europe/Berlin',
    'regional choices survive a real binder reload from native document data');
  T.oeffneEinstellungen(); await wait();
  w.document.querySelector('#einst-tab-regional').click(); await wait();
  const savedRegional=JSON.stringify(disk.einstellungen.regional);
  failSave=true; T.daten().notizen[0].text='Unsaved regional guard boundary';
  w.document.querySelector('#regional-formatgebiet').value='en-US';
  w.document.querySelector('#regional-speichern').click(); await wait(); await wait();
  ok(JSON.stringify(disk.einstellungen.regional)===savedRegional &&
    JSON.stringify(T.daten().einstellungen.regional)===savedRegional &&
    w.document.querySelector('#tablet-status').textContent.includes('could not be saved') &&
    !w.document.querySelector('#regional-speichern').disabled,
    'failed pre-change save keeps regional preferences intact and makes retry available');
  failSave=false; T.speichereJetzt(); await wait();
  failSave=true;
  w.document.querySelector('#regional-speichern').click(); await wait(); await wait();
  ok(JSON.stringify(disk.einstellungen.regional)===savedRegional &&
    T.daten().einstellungen.regional.formatLocale==='en-US' &&
    w.document.querySelector('#tablet-status').textContent.includes('could not be saved') &&
    !w.document.querySelector('#regional-speichern').disabled,
    'failed regional write reports failure and retains the visible unsaved choice for retry');
  failSave=false;
  w.document.querySelector('#regional-speichern').click(); await wait(); await wait();
  ok(disk.einstellungen.regional.formatLocale==='en-US' &&
    w.document.querySelector('#tablet-status').textContent.includes('Regional settings saved.'),
    'retry after failed regional persistence commits the chosen preferences');
  assert.throws(()=>w.webkit.messageHandlers.bridge.postMessage('{"cmd":"invented_success"}'));
  for(const cmd of ['telefon_waehlen','kde_sms_senden','sms']) {
    assert.throws(()=>w.webkit.messageHandlers.bridge.postMessage(JSON.stringify({cmd})));
    assert.ok(!messages.some(x=>x.cmd===cmd));
  }
  ok(!messages.some(x=>x.cmd==='invented_success'),'unimplemented bridge calls reject instead of ACK');
  assert.throws(()=>w.Tablet.validateImport('{"version":6,"termine":[],"aufgaben":[],"kontakte":[]}'));
  assert.throws(()=>w.Tablet.validateImport(JSON.stringify({...disk,termine:[{id:'bad',datum:'invalid'}]})));
  const extension=JSON.stringify({...disk,unrecognizedScalar:'must not disappear'});
  const imported=w.Tablet.validateImport(extension);
  assert.equal(imported.unrecognizedScalar,'must not disappear');
  assert.ok(imported.kontakte[0].telefone[0].typen.includes('CELL'));
  assert.ok(imported.kontakte[0].telefone[0].typen.includes('VOICE'));
  const normalize=T.normalisiere;
  T.normalisiere=input=>{const value=normalize(input); value.kontakte[0].telefone[0].typen=[]; return value;};
  assert.throws(()=>w.Tablet.validateImport(extension)); T.normalisiere=normalize;
  ok(true,'saved mobile contact accepts canonical VOICE enrichment but rejects lost phone types');
  T.normalisiere=input=>{const value=normalize(input); delete value.unrecognizedScalar; return value;};
  assert.throws(()=>w.Tablet.validateImport(extension)); T.normalisiere=normalize;
  ok(w.Tablet.validateImport(before).kontakte.length===1,'shared normalizer validates JSON import, rejects dropped records');
  T.schliesseEinstellungen();
  w.eval(fs.readFileSync(path.join(root,'app/src/androidTest/assets/scenarios.js'),'utf8'));
  const createdCalendar=await w.NativeScenario.calendar(); await wait();
  ok(disk.termine.some(x=>x.id===createdCalendar.id && x.titel==='Synthetic native calendar'),
    'actual instrumentation calendar editor scenario persists its new record');
  const createdTask=await w.NativeScenario.task('Synthetic native task','2030-05-10','11:00',1,true); await wait();
  ok(disk.aufgaben.some(x=>x.id===createdTask.id && x.faelligZeit==='11:00' && x.individuelleErinnerungTage===1 && x.erinnern),
    'actual instrumentation task editor scenario preserves early and due reminders');
  const createdContact=await w.NativeScenario.contact(); await wait();
  ok(disk.kontakte.some(x=>x.id===createdContact.id && x.vorname==='Synthetic' && x.nachname==='Tablet'),
    'actual instrumentation contact editor scenario persists its new record');
  const createdNote=await w.NativeScenario.note(); await wait();
  ok(createdNote.titel==='Synthetic native note' && createdNote.text==='Private synthetic note body' &&
    disk.notizen.some(x=>x.id===createdNote.id && x.text===createdNote.text) &&
    !w.document.querySelector('.eingabe-dialog'),
    'actual instrumentation note scenario confirms the creation dialog and saves editor title/body');
  const createdModule=await w.NativeScenario.custom(); await wait();
  ok(disk.customOrganizer.modules.some(x=>x.id===createdModule.id &&
    x.items.some(item=>item.title==='Synthetic custom appointment' && item.time==='12:35')),
    'actual instrumentation custom designer and time editor scenario persists its new item');
  await T.wechsel('gesundheit'); await wait();
  // Prime the old index first: omitting canonical mutation notification must
  // not turn the native 17-series stress fixture into a zero-worker no-op.
  T.daten().einstellungen.regional.timeZone='UTC'; // Same explicit zone as native launch().
  T.termineAm('2030-05-10',true);
  w.NativeScenario.navigationFixture(); await wait();
  const recurrence=w.NativeScenario.recurrenceProof();
  ok(recurrence.active && recurrence.series===17 && recurrence.occurrences===17 &&
    recurrence.uniqueOccurrences===17 && recurrence.datedOccurrences===17,
    'actual native navigation fixture invalidates a primed index and projects all 17 old series');
  const diagnosticScript=fs.readFileSync(path.join(root,'app/src/androidTest/assets/startup-diagnostics.js'),'utf8');
  const priorStatus=w.document.getElementById('tablet-status').textContent;
  w.document.getElementById('tablet-status').textContent='Import failed. [load-validation]';
  const startup=w.eval(diagnosticScript);
  assert.equal(startup.origin,'https://appassets.androidplatform.net');
  assert.equal(startup.statusCode,'load-validation');
  assert.ok(startup.tabletPresent && startup.organizerPresent);
  assert.deepEqual(Object.keys(startup).sort(),['readyState','origin','tabletPresent','organizerPresent','storageBlocked','statusCode'].sort());
  assert.ok(!JSON.stringify(startup).includes('Synthetic'));
  w.document.getElementById('tablet-status').textContent=priorStatus;
  ok(true,'startup diagnostics expose fixed technical fields without document or status message content');
  // The production codec's release-oracle shape enters the real shared importer,
  // then records and source metadata must appear in the same native save envelope.
  const calendarOracle=JSON.parse(fs.readFileSync(path.join(root,'app/src/test/resources/calendar-import-v2.0.30.json'))).cases[0];
  const calendarPayload={...structuredClone(calendarOracle.importExpected),icsImportMetadata:{version:1,
    sourceSHA256:createHash('sha256').update(calendarOracle.importSource).digest('hex'),calendarProperties:['VERSION:2.0','X-WR-CALNAME:Synthetic import']}};
  const calendarReply=(request,data,extra={})=>({callback:'calendarImport',payload:{requestId:request.requestId,
    pickerToken:301,...dom.authority(),data,...extra}});
  async function calendarPicker() {
    const count=messages.filter(m=>m.cmd==='tablet_import').length;
    w.Tablet.action('tablet_import','ics'); await wait(); await wait();
    assert.equal(messages.filter(m=>m.cmd==='tablet_import').length,count+1);
    const request=messages.filter(m=>m.cmd==='tablet_import').at(-1);
    assert.equal(request.format,'ics'); return request;
  }
  let picker=await calendarPicker();
  const preCalendar=disk.termine.length;
  const preStaleCalendar=JSON.stringify(disk);
  w.Tablet.receive(calendarReply(picker,calendarPayload,{revision:'old-book-revision'})); await wait();
  ok(JSON.stringify(disk)===preStaleCalendar,'ICS result from an obsolete book revision cannot mutate the current page');
  w.Tablet.receive(calendarReply(picker,calendarPayload)); await wait(); await wait();
  const calendarSave=messages.filter(m=>m.cmd==='speichern' && JSON.parse(m.text).icsImportSources?.[calendarPayload.icsImportMetadata.sourceSHA256]).at(-1);
  ok(disk.termine.length===preCalendar+1 && !!calendarSave &&
    JSON.parse(calendarSave.text).termine.some(item=>item.uid==='monthly-ordinal') &&
    disk.icsImportSources[calendarPayload.icsImportMetadata.sourceSHA256].calendarProperties.includes('X-WR-CALNAME:Synthetic import'),
    'ICS merges through shared UI and saves its source metadata with records in one native book save');
  ok(messages.some(m=>m.cmd==='tablet_calendar_import_done' && m.requestId===picker.requestId),
    'ICS picker is consumed only after durable book-save acknowledgement');
  picker=await calendarPicker(); const priorDone=messages.filter(m=>m.cmd==='tablet_calendar_import_done').length;
  w.Tablet.receive(calendarReply(picker,calendarPayload)); await wait(); await wait();
  ok(disk.termine.length===preCalendar+1 && messages.filter(m=>m.cmd==='tablet_calendar_import_done').length===priorDone+1,
    'duplicate/no-op ICS import still finishes its one-shot picker without duplicating records');
  const taskTemplates=JSON.parse(fs.readFileSync(path.join(root,'app/src/test/resources/calendar-import-v2.0.30.json'))).cases.find(item=>item.name==='tasks').importExpected.aufgaben;
  const taskGraphPayload={termine:[],jahrestage:[],aufgaben:['source-A','source-B'].flatMap(source=>taskTemplates.map(item=>({...structuredClone(item),
    icsQuelleId:source,icsQuelleName:source,icsElternQuelleId:source,titel:source+' '+item.titel}))),
    icsImportMetadata:{version:1,sourceSHA256:'c'.repeat(64),calendarProperties:['VERSION:2.0']}};
  picker=await calendarPicker(); w.Tablet.receive(calendarReply(picker,taskGraphPayload)); await wait(); await wait();
  function taskGraphPreserved(book) {
    return ['source-A','source-B'].every(source=>{
      const tasks=book.aufgaben.filter(item=>item.icsQuelleId===source);
      const parent=tasks.find(item=>item.icsImportUid==='task-parent');
      const child=tasks.find(item=>item.icsImportUid==='task-child');
      return tasks.length===2 && parent && child && child.elternUid===parent.uid && child.icsElternQuelleId===source;
    }) && new Set(book.aufgaben.filter(item=>['source-A','source-B'].includes(item.icsQuelleId)).map(item=>item.uid)).size===4;
  }
  ok(taskGraphPreserved(disk),'common ICS merge preserves two source-qualified task graphs sharing external parent and child UIDs');
  const cancelledPicker=await calendarPicker();
  w.Tablet.receive({callback:'cancelled',payload:{requestId:cancelledPicker.requestId}});
  picker=await calendarPicker(); const unchanged=JSON.stringify(disk);
  w.Tablet.receive(calendarReply(cancelledPicker,calendarPayload)); await wait();
  ok(JSON.stringify(disk)===unchanged,'cancelled older ICS result cannot consume the new picker or mutate its book');
  w.Tablet.receive(calendarReply(picker,{...calendarPayload,icsImportMetadata:{version:1,sourceSHA256:'invalid',calendarProperties:[]}})); await wait();
  ok(JSON.stringify(disk)===unchanged,'invalid ICS source metadata rejects the whole candidate before the shared merge');
  picker=await calendarPicker();
  const failedPayload=structuredClone(calendarPayload); failedPayload.termine[0].uid='failed-import-unique';
  failedPayload.icsImportMetadata.sourceSHA256='b'.repeat(64);
  failSave=true; w.Tablet.receive(calendarReply(picker,failedPayload)); await wait(); await wait();
  ok(JSON.stringify(disk)===unchanged && w.document.getElementById('tablet-status').textContent.includes('could not be saved'),
    'failed atomic ICS save reports failure without writing records or metadata to the native book');
  failSave=false; T.speichereJetzt(); await wait(); await wait();
  ok(disk.termine.some(item=>item.uid==='failed-import-unique') && !!disk.icsImportSources['b'.repeat(64)],
    'retry commits the complete unsaved ICS merge with its metadata');
  dom.window.close(); dom=await open(); w=dom.window; T=w.OrganizerTest;
  ok(taskGraphPreserved(T.daten()),'reopened book retains both source-qualified task graphs without cross-linking parents');
  ok(T.daten().termine.some(item=>item.uid==='failed-import-unique') && !!T.daten().icsImportSources['b'.repeat(64)],
    'reopened native book retains the merged ICS records and source metadata');
  picker=await calendarPicker();
  w.Tablet.receive({callback:'calendarImport',payload:{requestId:picker.requestId,...dom.authority(),revision:'old-book-revision',fehler:'Import failed.'}});
  await wait(); const jsonCount=messages.filter(m=>m.cmd==='tablet_import').length;
  w.Tablet.action('tablet_import'); await wait(); await wait();
  ok(messages.filter(m=>m.cmd==='tablet_import').length===jsonCount+1 && messages.filter(m=>m.cmd==='tablet_import').at(-1).format==='json',
    'failed or obsolete-revision ICS read releases its picker and JSON backup import remains an explicit independent format');
  w.Tablet.receive({callback:'cancelled',payload:{}});
  w.MagnolieI18n.setLocale('de'); T.oeffneEinstellungen(); await wait();
  w.document.querySelector('#einst-tab-import').click(); await wait();
  ok(w.document.querySelector('#einst-seite-import').textContent.includes(beta.de[2]) &&
    !w.document.querySelector('#einst-seite-import').textContent.includes('ICS adds calendar items'),
    'German import flow explains ICS merge and confirmed JSON replacement without English implementation text');
  T.schliesseEinstellungen(); w.MagnolieI18n.setLocale('en');
  w.MagnolieI18n.setLocale('de'); T.oeffneEinstellungen(); await wait();
  w.document.querySelector('#einst-tab-export').click(); await wait();
  ok(w.document.querySelector('#einst-seite-export').textContent.includes(beta.de[3]),
    'ICS export explains its unencrypted format separately from complete encrypted JSON backup');
  for (const [kind,label] of [['ics-termine','Appointments (.ics)'],['ics-aufgaben','Tasks (.ics)'],['ics-jahrestage','Anniversaries (.ics)']]) {
    const priorPasswordExport=messages.filter(m=>m.cmd==='tablet_export').length;
    const control=[...w.document.querySelectorAll('#einst-seite-export button')].find(item=>item.textContent===w.MagnolieI18n.gettext(label));
    assert.ok(control); control.click(); await wait(); await wait();
    const request=messages.filter(m=>m.cmd==='tablet_export_ics').at(-1);
    assert.equal(request.art,kind); assert.equal(Object.hasOwn(request,'daten'),false);
    assert.equal(messages.filter(m=>m.cmd==='tablet_export').length,priorPasswordExport);
    w.Tablet.receive({callback:'exportErgebnis',payload:{requestId:'stale',session:dom.authority().session,ok:true}});
    w.Tablet.receive({callback:'exportErgebnis',payload:{requestId:request.requestId,session:dom.authority().session,ok:false}});
    ok(w.document.getElementById('tablet-status').textContent===w.MagnolieI18n.gettext('Export failed.'),
      kind+' uses a bounded native-authority request without a password dialog and reports write failure');
  }
  T.schliesseEinstellungen(); w.MagnolieI18n.setLocale('en');
  w.Tablet.exportCalendar('ics-termine'); await wait(); await wait();
  const completedExport=messages.filter(m=>m.cmd==='tablet_export_ics').at(-1);
  w.Tablet.receive({callback:'exportErgebnis',payload:{requestId:completedExport.requestId,session:'old-page',ok:true}});
  assert.notEqual(w.document.getElementById('tablet-status').textContent,'Saved.');
  w.Tablet.receive({callback:'exportErgebnis',payload:{requestId:completedExport.requestId,session:dom.authority().session,ok:true,anzahl:3}});
  ok(w.document.getElementById('tablet-status').textContent==='Saved.','ICS export completion requires its correlated current-session native result');
  const originalExportCount=messages.filter(m=>m.cmd==='tablet_export_ics').length;
  assert.throws(()=>w.Tablet.exportCalendar('csv-termine'));
  failSave=true; T.daten().notizen[0].text='unsaved ICS export guard';
  w.Tablet.exportCalendar('ics-termine'); await wait(); await wait();
  ok(messages.filter(m=>m.cmd==='tablet_export_ics').length===originalExportCount,
    'ICS picker is not requested when preceding durable book save fails');
  failSave=false; T.speichereJetzt(); await wait();
  w.Tablet.exportCalendar('ics-termine'); await wait(); await wait();
  const cancelledExport=messages.filter(m=>m.cmd==='tablet_export_ics').at(-1);
  w.Tablet.receive({callback:'cancelled',payload:{requestId:cancelledExport.requestId}});
  ok(w.document.getElementById('tablet-status').textContent==='Cancel','SAF ICS cancellation has no successful export acknowledgement');
  const priorExports=messages.filter(x=>x.cmd==='tablet_export').length;
  failSave=true; T.daten().notizen[0].text='unsaved change';
  w.Tablet.action('tablet_export'); await wait();
  ok(messages.filter(x=>x.cmd==='tablet_export').length===priorExports,'SAF export is gated by durable save failure');
  failSave=false; T.speichereJetzt(); await wait();
  const token='native-selected-import';
  w.Tablet.receive({callback:'importCandidate',payload:{token,text:JSON.stringify(disk)}});
  const confirm=messages.findLast(x=>x.cmd==='tablet_replace');
  callbackForwarding(w,0,'DAV callbacks cannot mutate account UI or source selections during replacement');
  ok(confirm?.token===token && !Object.hasOwn(confirm,'text'),'restore authorization submits no imported body or file-supplied authority');
  const count=messages.filter(x=>x.cmd==='speichern').length;
  w.Tablet.receive({callback:'restoreFailed',payload:{token,outcome:'uncertain',text:'Import failed.'}});
  w.Tablet.receive({callback:'cancelled',payload:{token}});
  w.Tablet.receive({callback:'error',payload:'late unrelated error'});
  w.Tablet.receive({callback:'ready',payload:{session:confirm.session,revision:confirm.revision}});
  T.daten().notizen[0].text='stale A'; w.Tablet.flush(); T.speichereJetzt();
  w.Tablet.action('tablet_export'); await wait();
  ok(w.document.getElementById('schreibtisch').inert && messages.filter(x=>x.cmd==='speichern').length===count,
    'uncertain restore stays fenced through late cancel/error/ready and explicit save/pause flush');
  callbackForwarding(w,0,'DAV callbacks stay fenced after storage becomes uncertain');
  dom.window.close();
  dom=await open({holdReady:true});
  callbackForwarding(dom.window,0,'DAV callbacks are ignored before native initialization is acknowledged');
  dom.window.close();
  await wait();
  assert.equal(browserErrors.length,0,browserErrors.map(e=>String(e)).join('\n'));
  ok(true,'no uncaught browser errors, including teardown');
  // Read-only execution of the existing cross-platform shared contract vectors.
  execFileSync(process.execPath,[path.join(root,'../magnolie-organizer-windows/tests/personal-custom-consent.js')],{stdio:'inherit'});
  passed++;
  const vectors=JSON.parse(fs.readFileSync(path.join(root,'../contracts/personal-custom-consent-v4-vectors.json')));
  const start=projected.indexOf('  function personalSyncKanonisch(');
  const end=projected.indexOf('  function personalSyncAutoEntscheidung(',start);
  const contract=vm.runInNewContext(projected.slice(start,end)+'\n({personalSyncCustomSourceId,personalSyncCustomAllowed});',
    {TextEncoder,crypto:webcrypto});
  for(const v of vectors.identities) assert.equal(await contract.personalSyncCustomSourceId(vectors.source_id,v.item_id),v.id);
  ok(!contract.personalSyncCustomAllowed(vectors.local,vectors.revoked,[4],[4],true,true,
    vectors.revoked.epoch,vectors.local.epoch,vectors.revoked.revision,vectors.local.revision),
    'projected core passes shared custom identity/revocation vectors');
  const manifest=JSON.parse(fs.readFileSync(path.join(web,'../projection.json')));
  fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  fs.writeFileSync(path.join(root,'artifacts/web-test-proof.json'),JSON.stringify({passed,
    sourceHash:manifest.sourceHash,emulator:false,scope:'jsdom + shared contract vectors; not Android runtime acceptance'},null,2)+'\n');
  console.log(`${passed} checks passed; no emulator run.`);
})().catch(error=>{console.error(error);process.exit(1);});
