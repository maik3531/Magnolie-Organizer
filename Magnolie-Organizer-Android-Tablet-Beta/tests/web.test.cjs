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
  ok(Object.keys(beta).length===20 && Object.values(beta).every(x=>x.length===2 && x.every(Boolean)), '20 manual beta locales');
  const canonical=fs.readFileSync(path.join(root,'../magnolie-organizer-2.0.0/web/anwendung.js'),'utf8');
  const projected=read('anwendung.js');
  ok(projected.replace('  window.MagnolieTabletActions = { afterSave: action => navigiereMitGuard(() => nachDauerhaftemSpeichern(action)) };\n','')===canonical,
    'generated core differs only by explicit guarded-action API');
  const fontCss=read('desktop-fonts.css');
  assert.match(read('index.html'),/href="desktop-fonts\.css"/);
  for (const family of ['Noto Serif','DejaVu Sans','Noto Sans','DejaVu Sans Mono','Magnolie Handschrift'])
    assert.ok(fontCss.includes('font-family: "'+family+'"'),family+' must be bundled');
  for (const match of fontCss.matchAll(/url\("([^"]+)"\)/g)) {
    assert.deepEqual(fs.readFileSync(path.join(web,match[1])),
      fs.readFileSync(path.join(root,'../Magnolie-Organizer-Windows-2.0.0/app/web',match[1])));
  }
  for (const license of ['DejaVu-LIZENZ.txt','Noto-LIZENZ.txt','Z003-LIZENZ.txt'])
    assert.ok(read('schriften/'+license).length>100);
  ok(true,'desktop font families, faces and licenses use the live bundled Windows bytes');
  let disk=null, messages=[], failSave=false;
  const browserErrors=[];
  async function open() {
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
        if(m.cmd==='bereit') w.Tablet.receive({callback:'init',payload:{daten:disk,session,revision}});
        if(m.cmd==='tablet_loaded') w.Tablet.receive({callback:'ready',payload:{session,revision}});
        if(m.cmd==='speichern') {
          assert.equal(m.session,session); assert.equal(m.revision,revision);
          if(!failSave) disk=JSON.parse(m.text);
          if(!failSave) revision=webcrypto.randomUUID();
          w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:!failSave,session,expectedRevision:m.revision,revision}});
        }
      },0);
    }};
    for(const f of ['beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','anwendung.js']) w.eval(read(f));
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
  ok(w.document.querySelector('#einst-tab-sync').disabled && w.document.querySelector('#einst-tab-baum').disabled,
    'desktop system-account and sync tabs are disabled');
  w.document.querySelector('#einst-tab-ort').click(); await wait();
  ok(w.document.querySelector('#ort-abrufen').disabled && w.document.querySelector('#ort-jahre').disabled &&
    !w.document.querySelector('#ort-ferien').disabled && w.document.querySelector('#tablet-holiday-limit'),
    'network holiday retrieval disabled; local cached-holiday filter remains usable');
  assert.throws(()=>w.webkit.messageHandlers.bridge.postMessage('{"cmd":"invented_success"}'));
  for(const cmd of ['telefon_waehlen','kde_sms_senden','sms','feiertage']) {
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
  const priorExports=messages.filter(x=>x.cmd==='tablet_export').length;
  failSave=true; T.daten().notizen[0].text='unsaved change';
  w.Tablet.action('tablet_export'); await wait();
  ok(messages.filter(x=>x.cmd==='tablet_export').length===priorExports,'SAF export is gated by durable save failure');
  failSave=false; T.speichereJetzt(); await wait();
  const token='native-selected-import';
  w.Tablet.receive({callback:'importCandidate',payload:{token,text:JSON.stringify(disk)}});
  const confirm=messages.findLast(x=>x.cmd==='tablet_replace');
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
  dom.window.close();
  await wait();
  assert.equal(browserErrors.length,0,browserErrors.map(e=>String(e)).join('\n'));
  ok(true,'no uncaught browser errors, including teardown');
  // Read-only execution of the existing cross-platform shared contract vectors.
  execFileSync(process.execPath,[path.join(root,'../Magnolie-Organizer-Windows-2.0.0/tests/personal-custom-consent.js')],{stdio:'inherit'});
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
