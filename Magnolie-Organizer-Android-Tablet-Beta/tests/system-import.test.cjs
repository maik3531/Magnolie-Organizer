'use strict';
// Real generated organizer + synthetic Android provider/SaveACK. Refs #791/#682.
// This exercises the actual UI and core; it is not Android permission/provider proof.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..'),web=path.join(root,'app/build/generated/projection/assets/web');
const read=name=>fs.readFileSync(path.join(web,name),'utf8');
const wait=()=>new Promise(resolve=>setTimeout(resolve,40));
const contactsSource='android-contacts:'+'a'.repeat(64),eventsSource='android-events:'+'b'.repeat(64);
let checks=0;
function check(value,label){assert.ok(value,label);checks++;console.log('PASS '+label);}
(async()=>{
  const errors=[],vc=new VirtualConsole();vc.on('jsdomError',error=>errors.push(String(error)));
  const dom=new JSDOM(read('index.html'),{url:'https://appassets.androidplatform.net/assets/web/index.html',
    runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window,session=webcrypto.randomUUID();let revision=webcrypto.randomUUID(),disk=null,failSave=false,holdSave=false;
  const messages=[],saves=[];let permissions={contacts:'authorized',events:'authorized'};
  w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w,'crypto',{value:webcrypto});
  w.Element.prototype.getAnimations=()=>[];
  const reply=(callback,payload)=>w.Tablet.receive({callback,payload});
  function acknowledge(m,ok=true){
    if(ok){disk=JSON.parse(m.text);revision=webcrypto.randomUUID();}
    reply('gespeichert',{id:m.id,ok,session,expectedRevision:m.revision,revision});
  }
  function sources(extra={}){return {...extra,verfuegbar:true,buchOk:true,permissions:{...permissions},
    systemImportImplemented:{contacts:true,events:'instances-window'},
    kalender:[{uid:eventsSource,name:'Local calendar',art:'android-events'}],
    adressbuecher:[{uid:contactsSource,name:'Local contacts',art:'android-contacts'}]};}
  w.TabletNative={postMessage(text){const m=JSON.parse(text);messages.push(m);setTimeout(()=>{
    if(!w.document)return;
    if(m.cmd==='bereit')reply('init',{daten:disk,session,revision});
    if(m.cmd==='tablet_loaded')reply('ready',{session,revision});
    if(m.cmd==='speichern'){assert.equal(m.session,session);assert.equal(m.revision,revision);
      if(holdSave)saves.push(m);else acknowledge(m,!failSave);}
    if(m.cmd==='eds_status')reply('edsStatus',sources({requestId:m.requestId}));
    if(m.cmd==='baum_briefkasten_status')reply('baumBriefkastenStatus',{kontoArt:'nextcloud',davAktiv:false,briefkastenAktiv:false,
      url:'',benutzer:'',kennwortVorhanden:false,revision:'f'.repeat(64),zustand:'disabled',fehler:''});
  },0);}};
  for(const name of ['normative-timezones.js','beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js',
    'mcp-protocol.js',...(fs.existsSync(path.join(web,'appearance.js'))?['appearance.js']:[]),'anwendung.js'])w.eval(read(name));
  await wait();await wait();const T=w.OrganizerTest;
  try {
    check(!!disk,'generated UI initialization and first synthetic native SaveACK complete');
    T.daten().einstellungen.regional.timeZone='Europe/Berlin';
    T.daten().notizen.push({id:'kept-note',titel:'Keep',text:'Unrelated text',notizbuchId:T.daten().notizbuecher[0].id,anhaenge:[]});
    T.speichereJetzt();await wait();
    T.oeffneEinstellungen();await wait();w.document.getElementById('einst-tab-sync').click();await wait();await wait();
    check(w.document.getElementById('einst-tab-baum').hidden,'tablet setup omits Notes/KDE pairing tab');
    check(messages.every(m=>m.cmd!=='android_systemzugriff' && m.cmd!=='android_systemimport'),'startup and discovery do not read record bodies or prompt for permission');
    function select(kind){const el=w.document.getElementById('tablet-system-source-'+kind);el.value=kind==='contacts'?contactsSource:eventsSource;
      el.dispatchEvent(new w.Event('change',{bubbles:true}));}
    async function start(kind='contacts'){
      select(kind);const count=messages.filter(m=>m.cmd==='android_systemimport').length;
      w.document.getElementById('tablet-system-import-'+kind).click();await wait();await wait();
      const requests=messages.filter(m=>m.cmd==='android_systemimport');assert.equal(requests.length,count+1);
      return requests.at(-1);
    }
    function contact(letter='c',name='Ada') {const recordId='android-contact:'+letter.repeat(64);return {recordId,data:{uid:recordId,
      anzeigename:name,vorname:name,nachname:'Example',firma:'',notiz:'Preserved note',sync:false,
      telefone:[{wert:'+4930123456',typen:['WORK']}],emailEintraege:[{wert:'ada@example.test',typen:['WORK']}],
      anschriften:[],geburtstag:'--02-29'}};}
    function result(request,records,extra={}) {return {...request,kind:request.art,ok:true,complete:true,
      scope:request.art==='contacts'?'source-contacts':'calendar-instances-window',records,...extra};}
    let request=await start(),before=JSON.stringify(disk),c=contact();
    holdSave=true;reply('androidSystemImport',result(request,[c]));await wait();await wait();
    check(JSON.stringify(disk)===before && saves.length===1,'provider completion does not claim durable success before native SaveACK');
    check(!w.document.getElementById('tablet-status').textContent.startsWith('Imported:'),'no import success while SaveACK is pending');
    acknowledge(saves.shift());holdSave=false;await wait();
    check(disk.kontakte.length===1 && disk.kontakte[0].vorname==='Ada' && disk.kontakte[0].geburtstag==='--02-29','contact content and unknown birthday year survive canonical normalization and save');
    check(disk.kontakte[0].sync===false && Object.keys(disk.kontakte[0].syncQuellen).length===0,'import grants no provider-write or sync authority');
    check(disk.notizen[0].text==='Unrelated text','unrelated notes remain unchanged');
    const reopened=w.Tablet.validateImport(JSON.stringify(disk));
    check(reopened.kontakte[0].uid===c.recordId && reopened.kontakte[0].androidSystemImport.recordId===c.recordId,'copy identity survives validated book reopen');
    check(reopened.jahrestage.length===1 && reopened.jahrestage[0].kontaktId===c.recordId &&
      T.normalisiere(reopened).jahrestage.length===1,'derived contact birthday remains stable across consecutive reopens');
    const api={empty:T.leereDaten,normalize:T.normalisiere,projectEvent:w.MagnolieTabletActions.systemEvent};
    const pureRequest={cmd:'android_systemimport',art:'contacts',sourceUid:contactsSource,requestId:'pure',session,revision};
    const countryBook=T.leereDaten();countryBook.einstellungen.regional.homeCountry='US';
    const twoPhones=contact('a','Distinct numbers');twoPhones.data.telefone=[{wert:'2025550100',typen:['HOME']},{wert:'+492025550100',typen:['HOME']}];
    const phonePlan=w.TabletSystemImport.prepare(result(pureRequest,[twoPhones]),pureRequest,countryBook,api);
    check(phonePlan.rows[0].telefone.length===2,'new contact normalization uses the existing home country instead of a default');
    const conflictBook=T.leereDaten();conflictBook.jahrestage.push({id:'manual-birthday',uid:'',name:'Ada Example',datum:'--12-01',kontaktId:'',typ:'birthday'});
    const conflictBefore=JSON.stringify(conflictBook);
    assert.throws(()=>w.TabletSystemImport.prepare(result(pureRequest,[c]),pureRequest,conflictBook,api),/existing_record_conflict|unstable_reopen/);
    check(JSON.stringify(conflictBook)===conflictBefore,'ambiguous existing birthday is rejected without linking or folding old entries');
    T.daten().kontakte[0].notiz='Locally edited';T.speichereJetzt();await wait();
    request=await start();reply('androidSystemImport',result(request,[contact('c','Changed remotely')]));await wait();await wait();
    check(disk.kontakte.length===1 && disk.kontakte[0].vorname==='Ada' && disk.kontakte[0].notiz==='Locally edited','repeated import skips existing identities and preserves local edits');
    for(const [label,change] of [
      ['partial result',{complete:false}],['wrong source',{sourceUid:eventsSource}],['duplicate record',{records:[contact('d'),contact('d')]}],
      ['provider failure',{ok:false,errorCode:'permission_required'}],['invalid sync grant',{records:[{...contact('d'),data:{...contact('d').data,sync:true}}]}]
    ]){
      request=await start();before=JSON.stringify(disk);reply('androidSystemImport',result(request,[contact('d')],change));await wait();await wait();
      check(JSON.stringify(disk)===before,label+' changes no saved data');
    }
    request=await start();before=JSON.stringify(disk);
    reply('androidSystemImport',result(request,[contact('d')],{requestId:'unrelated'}));await wait();
    check(JSON.stringify(disk)===before,'unrelated request callback is ignored');
    T.daten().notizen[0].text='Concurrent edit';T.speichereJetzt();await wait();before=JSON.stringify(disk);
    reply('androidSystemImport',result(request,[contact('d')]));await wait();await wait();
    check(JSON.stringify(disk)===before,'old native revision cannot overwrite a newer book');
    request=await start();const cancel=[...w.document.querySelectorAll('#tablet-system-access button')].find(b=>b.textContent==='Cancel');
    assert.ok(cancel);cancel.click();before=JSON.stringify(disk);reply('androidSystemImport',result(request,[contact('d')]));await wait();
    check(JSON.stringify(disk)===before,'cancelled provider result cannot be applied later');
    permissions.contacts='not_granted';reply('edsStatus',sources());await wait();
    check(w.document.getElementById('tablet-system-import-contacts').disabled,'revoked contact permission disables the import control');
    permissions.contacts='authorized';reply('edsStatus',sources());await wait();
    w.document.getElementById('tablet-system-from').value='2030-03-31';w.document.getElementById('tablet-system-from').dispatchEvent(new w.Event('change'));
    w.document.getElementById('tablet-system-to').value='2030-03-31';w.document.getElementById('tablet-system-to').dispatchEvent(new w.Event('change'));
    request=await start('events');
    check(request.to-request.from===23*3600000,'calendar date window follows the book time zone across DST');
    const eventId='android-event:'+'e'.repeat(64),event={recordId:eventId,data:{uid:eventId,titel:'Android event',notiz:'Exact instant',ort:'',
      datum:'2030-03-31',zeit:'09:00',endDatum:'',endZeit:'10:00',icsAnzeigeZeitzone:'UTC',
      icsRoundtrip:['DTSTART:20300331T090000Z','DTEND:20300331T100000Z'],wiederholung:{art:'none',bis:''},
      sync:false,standardErinnerung:false,icsEndeFehlt:false,icsNullDauer:false}};
    reply('androidSystemImport',result(request,[event]));await wait();await wait();
    check(disk.termine.length===1 && disk.termine[0].zeit==='11:00' && disk.termine[0].icsAnzeigeZeitzone==='Europe/Berlin','UTC provider instant displays in the organizer time zone');
    check(disk.termine[0].icsRoundtrip.includes('DTSTART:20300331T090000Z') && disk.termine[0].wiederholung.art==='none','original instant survives without invented recurrence rules');
    request=await start('contacts');before=JSON.stringify(disk);failSave=true;
    reply('androidSystemImport',result(request,[contact('d')]));await wait();await wait();
    check(JSON.stringify(disk)===before && !w.document.getElementById('tablet-status').textContent.startsWith('Imported:'),'failed native save never reports import success');
    failSave=false;T.speichereJetzt();await wait();
    check(disk.kontakte.length===2,'unsaved complete copy remains available for an explicit save retry');
    const social={cmd:'sozial',dienst:'custom',wert:'https://example.test/file%20name.pdf',aktionArt:'url',
      aktionZiel:'https://example.test/file%20name.pdf',land:'DE'};
    w.webkit.messageHandlers.bridge.postMessage(JSON.stringify(social));await wait();await wait();
    const launch=messages.findLast(m=>m.cmd==='sozial');
    check(launch && launch.wert===social.wert && launch.session===session && launch.revision===revision,'explicit attachment action reaches native unchanged after a durable save guard');
    reply('externalAttachmentResult',{requestId:launch.requestId,session,revision,ok:false,reason:'attachment_not_saved'});await wait();
    check(w.document.getElementById('tablet-status').textContent==='Unavailable','native rejection of an unsaved attachment stays visible');
    assert.throws(()=>w.webkit.messageHandlers.bridge.postMessage(JSON.stringify({...social,dienst:'email'})));
    check(!messages.some(m=>m.cmd==='sozial'&&m.dienst==='email'),'attachment path does not enable other communication commands');
    check(errors.length===0,'no uncaught generated-UI errors');
    console.log(checks+' Android copy/attachment integration checks passed; synthetic provider and storage, no Android runtime.');
  } finally {dom.window.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
