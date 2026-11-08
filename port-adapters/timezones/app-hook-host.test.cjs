'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module'),{Worker}=require('node:worker_threads'),{webcrypto}=require('node:crypto');
const repo=path.resolve(__dirname,'../..'),tablet=path.join(repo,'Magnolie-Organizer-Android-Tablet-Beta'),deps=createRequire(path.join(tablet,'package.json')),{JSDOM,VirtualConsole}=deps('jsdom'),web=path.join(tablet,'app/build/generated/projection/assets/web');
const apply=require('./projection-patches.cjs'),read=name=>fs.readFileSync(path.join(__dirname,name)),canonical=fs.readFileSync(path.join(repo,'magnolie-organizer/web/anwendung.js'),'utf8'),patched=apply(canonical,read);
assert.equal(apply(patched,read,true,canonical),canonical,'Strict inverse retains every canonical byte');
assert.throws(()=>apply(canonical.replace('const ianaZonenPruefungen = new Map();','const ianaZonenPruefungen = new Map(); /*change*/').replace('let zone = String(value || "").trim();','let zone = String(value || "").trim(); /*change*/'),read),/canonical block changed/);
assert.throws(()=>apply(patched.replace('TZ_PORT:validate-zone:BEGIN','changed'),read,true,canonical),/projection match changed/);
// Both projectors must apply the very same reviewed transformations.
const cp=require('node:child_process');
const python=`import sys,pathlib,importlib.util
sys.dont_write_bytecode=True
r=pathlib.Path(sys.argv[1]);s=importlib.util.spec_from_file_location('p',r/'Magnolie-Organizer-macOS-Beta/tools/project_ui.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
p='port-adapters/timezones/';snap={p+f.name:f.read_bytes() for f in (r/p).iterdir() if f.is_file()}
source=(r/'magnolie-organizer/web/anwendung.js').read_text()
if len(sys.argv)>2:source=source.replace('let zone = String(value || \"\").trim();','let zone = String(value || \"\").trim(); /*change*/')
sys.stdout.buffer.write(m.apply_timezone_patches(source,snap).encode())
`;
assert.equal(cp.execFileSync('python3',['-c',python,repo],{maxBuffer:8*1024*1024}).toString(),patched);
const rejected=cp.spawnSync('python3',['-c',python,repo,'drift'],{encoding:'utf8',maxBuffer:8*1024*1024});
assert.notEqual(rejected.status,0);assert.match(rejected.stderr,/canonical block changed/);
// Replacement metacharacters are trusted source bytes, never replace() directives.
const dollarSource="ANCHOR $& $` $' $$ END",dollarReplacement="BODY $& $` $' $$";
const dollarManifest=[{id:'literal',start:'ANCHOR',end:' END',includeEnd:true,sha256:require('node:crypto').createHash('sha256').update(dollarSource).digest('hex'),replacement:dollarReplacement}];
const dollarRead=name=>Buffer.from(name==='projection-patches.json'?JSON.stringify(dollarManifest):'');
const dollarPatched=apply(dollarSource,dollarRead);
assert.equal(dollarPatched,'/*TZ_PORT:literal:BEGIN*/'+dollarReplacement+'/*TZ_PORT:literal:END*/');
assert.equal(apply(dollarPatched,dollarRead,true,dollarSource),dollarSource);
const tick=()=>new Promise(r=>setTimeout(r,35));
async function boot(initial=null) {
 const errors=[],console=new VirtualConsole();console.on('jsdomError',e=>errors.push(e));
 const dom=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{url:'https://appassets.androidplatform.net/assets/web/index.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console}),w=dom.window;
 w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w,'crypto',{value:webcrypto});w.Element.prototype.getAnimations=()=>[];
 const session=webcrypto.randomUUID();let revision=webcrypto.randomUUID(),disk=initial;const threads=[],sources=new Map();let workerSource='';
 w.Blob=class{constructor(parts){this.text=parts.join('')}};w.URL.createObjectURL=blob=>{const key='blob:host-'+sources.size;sources.set(key,blob.text);return key};w.URL.revokeObjectURL=()=>{};
 w.Worker=class {
  constructor(url){workerSource=sources.get(url);assert.ok(workerSource,'Actual generated worker source required');const prelude="const {parentPort}=require('node:worker_threads');global.self=globalThis;global.postMessage=data=>parentPort.postMessage(data);parentPort.on('message',data=>self.onmessage({data}));\n";
   this.thread=new Worker(prelude+workerSource,{eval:true});threads.push(this.thread);this.thread.on('message',data=>this.onmessage?.({data}));this.thread.on('error',error=>this.onerror?.(error));}
  postMessage(data){this.thread.postMessage(data)}terminate(){return this.thread.terminate()}
 };
 w.TabletNative={postMessage(text){const m=JSON.parse(text);setTimeout(()=>{if(!w.document)return;
  if(m.cmd==='bereit')w.Tablet.receive({callback:'init',payload:{daten:initial,session,revision}});
  if(m.cmd==='tablet_loaded')w.Tablet.receive({callback:'ready',payload:{session,revision}});
  if(m.cmd==='speichern'){disk=JSON.parse(m.text);const expectedRevision=revision;revision=webcrypto.randomUUID();w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision,revision}});}
 },0)}};
 for(const name of ['normative-timezones.js','beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','mcp-protocol.js','anwendung.js']) {
  let source=fs.readFileSync(path.join(web,name),'utf8');
  if(name==='anwendung.js') {assert.equal(source.split('window.OrganizerTest = {').length,2);
   // Existing test doorway: expose references only, never replace a calculator.
   source=source.replace('window.OrganizerTest = {','window.OrganizerTest = { eindeutigerOrtszeitpunkt, zeitOrtszeitpunkt, zeitLokaleMinute, zeitDatumTeile,');}
  w.eval(source);
 }
 await tick();await tick();w.MagnolieI18n.setLocale('en');
 return {w,errors,disk:()=>disk,source:()=>workerSource,close:async()=>{for(const t of threads)await t.terminate();dom.window.close();}};
}
(async()=>{
 const b=await boot();let checks=0;
 try{
  const w=b.w,T=w.OrganizerTest,D=T.daten();D.einstellungen.regional.timeZone='UTC';D.einstellungen.regional.hourCycle='h23';
  // The actual formatted clock must not acquire the OS Berlin spring-gap shift.
  const oldTZ=process.env.TZ;try{process.env.TZ='Europe/Berlin';assert.equal(T.zeitText('2026-03-29','02:30'),'02:30');assert.equal(T.zeitText('2026-03-29','02:30:45'),'02:30:45');checks+=2;}finally{if(oldTZ===undefined)delete process.env.TZ;else process.env.TZ=oldTZ;}
  const sourceZone=['BEGIN:VTIMEZONE','TZID:Europe/Berlin','BEGIN:STANDARD','DTSTART:19700101T000000','TZOFFSETFROM:+235959','TZOFFSETTO:+235959','END:STANDARD','END:VTIMEZONE'];
  const raw=['DTSTART;TZID=Europe/Berlin:20260328T100000','DURATION:PT0S'];const result=T.icsExpansion({icsTimezones:[sourceZone],icsRoundtrip:raw,icsDisplayTarget:'UTC'},-Infinity,Infinity)[0];
  assert.equal(result.icsStartUtc,Date.parse('2026-03-27T10:00:01Z'));assert.deepEqual(Array.from(result.icsRoundtrip),raw);checks+=2;
  const daily=T.icsExpansion({icsRoundtrip:['DTSTART;TZID=Europe/Berlin:20260328T023000','DURATION:PT0S','RRULE:FREQ=DAILY;COUNT=3'],icsDisplayTarget:'UTC'},-Infinity,Infinity);
  assert.deepEqual(Array.from(daily,r=>r.icsStartUtc),['2026-03-28T01:30Z','2026-03-30T00:30Z','2026-03-31T00:30Z'].map(Date.parse));checks++;
  const allday=T.icsExpansion({icsRoundtrip:['DTSTART;VALUE=DATE:20111230','DTEND;VALUE=DATE:20111231'],icsDisplayTarget:'Pacific/Apia'},-Infinity,Infinity)[0];assert.equal(allday.datum,'2011-12-30');checks++;
  const floating=['DTSTART:20261015T123000','DURATION:PT0S'];D.einstellungen.regional.timeZone='Africa/Casablanca';const f=T.icsExpansion({icsRoundtrip:floating},-Infinity,Infinity)[0];assert.equal(f.zeit,'12:30');assert.deepEqual(Array.from(f.icsRoundtrip),floating);checks+=2;
  // Actual lexical domain functions, using the same debug doorway as communication tests.
  assert.equal(T.zeitOrtszeitpunkt('1910-01-15','12:30:45','Europe/Paris'),Date.parse('1910-01-15T12:21:24Z'));checks++;
  const firstFold=Date.parse('2026-10-25T00:30:45Z'),lastFold=Date.parse('2026-10-25T01:30:45Z');
  assert.throws(()=>T.eindeutigerOrtszeitpunkt('2026-10-25','02:30:45','Europe/Berlin'),error=>error.code==='invalid_settings');
  assert.throws(()=>T.eindeutigerOrtszeitpunkt('2026-03-29','02:30:45','Europe/Berlin'),error=>error.code==='invalid_settings');
  assert.equal(T.eindeutigerOrtszeitpunkt('2026-10-25','02:30:45','Europe/Berlin','earlier'),firstFold);
  assert.equal(T.eindeutigerOrtszeitpunkt('2026-10-25','02:30:45','Europe/Berlin','later'),lastFold);
  assert.equal(T.eindeutigerOrtszeitpunkt('2026-10-25','02:30:45','Europe/Berlin','reject',lastFold),lastFold);checks+=5;
  const wall={year:2026,month:10,day:25,hour:2,minute:30};
  assert.equal(T.zeitLokaleMinute(wall,'Europe/Berlin'),Date.parse('2026-10-25T00:30Z')/60000);
  assert.equal(T.zeitLokaleMinute(wall,'Europe/Berlin',Date.parse('2026-10-25T01:30Z')/60000),Date.parse('2026-10-25T01:30Z')/60000);
  assert.throws(()=>T.zeitLokaleMinute({year:1971,month:1,day:15,hour:12,minute:0},'Africa/Monrovia'),error=>error.code==='unsupported-time-tracking-precision');
  assert.equal(T.zeitLokaleMinute({year:1971,month:1,day:15,hour:12,minute:0},'Africa/Monrovia',null,true),Math.floor(Date.parse('1971-01-15T12:44:30Z')/60000));checks+=4;
  const original={uid:'public-strict-domain',titel:'Public strict domain',datum:'2026-10-25',zeit:'01:30',endDatum:'2026-10-25',endZeit:'03:30',icsAnzeigeZeitzone:'Europe/Berlin',icsRoundtrip:['UID:public-strict-domain','DTSTART;TZID=Europe/Berlin:20261025T013000','DTEND;TZID=Europe/Berlin:20261025T033000']};
  const edit=JSON.parse(JSON.stringify(original));edit.zeit='02:30';const editBefore=JSON.stringify(edit);
  assert.throws(()=>T.spiegeleTerminInIcs(edit,original),error=>error.code==='invalid_settings');assert.equal(JSON.stringify(edit),editBefore);checks+=2;
  const prior={...original,datum:'2074-07-15',endDatum:'2074-07-15',zeit:'12:30:45',endZeit:'13:30:45',icsAnzeigeZeitzone:'Asia/Gaza',icsRoundtrip:['UID:public-seconds','DTSTART;TZID=Asia/Gaza:20740715T123045','DTEND;TZID=Asia/Gaza:20740715T133045']};
  const seconds={...prior,zeit:'12:31:45'};const secondsLines=T.spiegeleTerminInIcs(seconds,prior);assert.ok(secondsLines.includes('DTSTART:20740715T093145Z'));checks++;
  // Actual generated worker code runs in a real isolated Node thread; browser-native proof is separate.
  D.einstellungen.regional.timeZone='UTC';const workerItem={uid:'dynamic-test-item-not-code-7f3a',icsRoundtrip:['DTSTART;TZID=Asia/Gaza:20740715T123045','DURATION:PT1H','RRULE:FREQ=DAILY;COUNT=2']},args=[Date.parse('2074-07-14T00:00Z'),Date.parse('2074-07-17T00:00Z')];
  let rows=T.icsRuntime('expand',workerItem,args);for(let i=0;!Array.isArray(rows)&&i<100;i++){await tick();rows=T.icsRuntime('expand',workerItem,args);}
  assert.ok(Array.isArray(rows));assert.deepEqual(Array.from(rows,r=>r.icsStartUtc),['2074-07-15T09:30:45Z','2074-07-16T09:30:45Z'].map(Date.parse));assert.ok(!b.source().includes(workerItem.uid));assert.ok(T.icsRuntime.state.worker);checks+=4;
  // Exercise the actual regional selector, durable-save envelope and fresh binder.
  T.oeffneEinstellungen();await tick();w.document.querySelector('#einst-tab-regional').click();await tick();const select=w.document.querySelector('#regional-zeitzone');
  assert.ok(Array.from(select.options,o=>o.value).includes('US/Eastern'));assert.ok(Array.from(select.options,o=>o.value).includes('America/Coyhaique'));select.value='US/Eastern';w.document.querySelector('#regional-speichern').click();await tick();await tick();
  assert.equal(b.disk().einstellungen.regional.timeZone,'US/Eastern');assert.equal(+T.terminZeitpunkt({datum:'2026-10-15',zeit:'12:30'}),Date.parse('2026-10-15T16:30Z'));checks+=4;
  const saved=JSON.parse(JSON.stringify(b.disk()));const restarted=await boot(saved);try{assert.equal(restarted.w.OrganizerTest.daten().einstellungen.regional.timeZone,'US/Eastern');assert.equal(+restarted.w.OrganizerTest.terminZeitpunkt({datum:'2026-10-15',zeit:'12:30'}),Date.parse('2026-10-15T16:30Z'));checks+=2;}finally{await restarted.close();}
  const restored=JSON.parse(JSON.stringify(saved));restored.einstellungen.regional.timeZone='Australia/Lord_Howe';const restoredApp=await boot(restored);try{assert.equal(+restoredApp.w.OrganizerTest.terminZeitpunkt({datum:'2026-07-15',zeit:'12:30'}),Date.parse('2026-07-15T02:00Z'));checks++;}finally{await restoredApp.close();}
  assert.equal(b.errors.length,0,b.errors.map(String).join('\n'));
  console.log(JSON.stringify({actualProjectedAppChecks:checks,strictInverse:true,actualIsolatedNodeWorker:true,nativeBrowserWorker:false,aliasSaveRestartRestore:true,nativeDeviceProof:false}));
 }finally{await b.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
