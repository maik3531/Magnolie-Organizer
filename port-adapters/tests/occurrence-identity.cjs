'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {webcrypto,createHash}=require('node:crypto'),{createRequire}=require('node:module');
const repo=path.resolve(__dirname,'../..'),deps=createRequire(path.join(repo,'Magnolie-Organizer-Android-Tablet-Beta/package.json'));
const {JSDOM,VirtualConsole}=process.env.MACOS_BETA_JSDOM?require(process.env.MACOS_BETA_JSDOM):deps('jsdom');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/distinct-rid-same-slot.json')));
const clone=x=>JSON.parse(JSON.stringify(x)),tick=()=>new Promise(resolve=>setTimeout(resolve,20));
const read=name=>fs.readFileSync(path.join(repo,'port-adapters',name));
const apply=require('../occurrence-identity-projection.cjs');
function inverseChecks() {
  const cp=require('node:child_process'),canonical=fs.readFileSync(path.join(repo,'magnolie-organizer/web/anwendung.js'),'utf8');
  const published=cp.execFileSync('git',['show','067c38934b539943d8e1720abafd8a80b401d797:magnolie-organizer/web/anwendung.js'],{cwd:repo,maxBuffer:4*1024*1024}).toString();
  const tz=require('../timezones/projection-patches.cjs'),tzRead=name=>read('timezones/'+name);
  assert.equal(JSON.parse(tzRead('projection-patches.json')).length,51,'all reviewed timezone anchors retained');
  const python=`import importlib.util,pathlib,sys\nr=pathlib.Path(sys.argv[1]);s=importlib.util.spec_from_file_location('p',r/'Magnolie-Organizer-macOS-Beta/tools/project_ui.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nsnap={'port-adapters/'+n:(r/'port-adapters'/n).read_bytes() for n in ['occurrence-identity-patch.json','occurrence-identity.js']}\nsys.stdout.write(m.apply_occurrence_identity(sys.stdin.read(),snap))`;
  for(const source of [canonical,published]) {
    const patched=apply(tz(source,tzRead),read);
    assert.equal(tz(apply(patched,read,true),tzRead,true,source),source,'all timezone and identity changes invert byte-exactly');
    const py=cp.execFileSync('python3',['-c',python,repo],{input:source,maxBuffer:4*1024*1024}).toString();
    assert.equal(py,apply(source,read),'Mac and Tablet consume identical helper/patch bytes');
  }
  const patch=JSON.parse(read('occurrence-identity-patch.json'));
  for(const changed of [{...patch,schema:2},{...patch,sha256:'0'.repeat(64)},{...patch,mainSHA256:'0'.repeat(64)},{...patch,after:patch.after.replace('/*PORT_OCCURRENCE_HELPER*/','changed')}])
    assert.throws(()=>apply(canonical,n=>n==='occurrence-identity-patch.json'?Buffer.from(JSON.stringify(changed)):read(n)),/manifest changed/);
  assert.throws(()=>apply(canonical.replace(patch.before,patch.before+' changed').replace('function termineStarkIdentisch','function driftedTermine'),read),/anchor changed/);
  assert.throws(()=>apply(apply(canonical,read).replace('PORT_OCCURRENCE_IDENTITY_BEGIN','changed'),read,true),/anchor changed/);
}
async function boot(web,platform,initial=null) {
  const errors=[],messages=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e));
  const dom=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{url:platform==='tablet'?'https://appassets.androidplatform.net/assets/web/index.html':'https://macos-identity.invalid/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;let disk=null,revision=webcrypto.randomUUID();const session=webcrypto.randomUUID();
  w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;w.structuredClone=structuredClone;Object.defineProperty(w,'crypto',{value:webcrypto});
  w.Element.prototype.getAnimations=()=>[];w.HTMLElement.prototype.scrollIntoView=()=>{};
  const profile=()=>{if(initial)return clone(initial);const b=w.OrganizerTest.leereDaten();b.einstellungen.allgemein.handbuchHinweisGezeigt=true;b.einstellungen.regional.language='en';b.einstellungen.regional.timeZone='UTC';return b;};
  if(platform==='tablet')w.TabletNative={postMessage(raw){const m=JSON.parse(raw);messages.push(m);setTimeout(()=>{
    if(!w.document)return;
    if(m.cmd==='bereit')w.Tablet.receive({callback:'init',payload:{daten:profile(),session,revision}});
    if(m.cmd==='tablet_loaded')w.Tablet.receive({callback:'ready',payload:{session,revision}});
    if(m.cmd==='speichern'){assert.equal(m.session,session);assert.equal(m.revision,revision);disk=JSON.parse(m.text);revision=webcrypto.randomUUID();w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision:m.revision,revision}});}
  },0);}};
  else {w.__MAGNOLIE_BRUECKE__='identityTest';w.webkit={messageHandlers:{identityTest:{postMessage(raw){const m=JSON.parse(raw);messages.push(m);if(m.cmd==='speichern')setTimeout(()=>{if(w.document){disk=JSON.parse(m.text);w.MacBeta.receive('gespeichert',{id:m.id,ok:true});}},0);}}}};}
  for(const script of w.document.querySelectorAll('script[src]'))w.eval(fs.readFileSync(path.join(web,script.getAttribute('src')),'utf8'));
  await tick();await tick();if(platform==='macos')w.MacBeta.receive('init',{daten:profile(),neu:false,regional:{language:'en',timeZone:'UTC'}});await tick();
  assert.equal(errors.length,0,errors.map(String).join('\n'));
  return {w,t:w.OrganizerTest,errors,messages,close:()=>dom.window.close(),save(){w.OrganizerTest.planeSpeichern();return new Promise((resolve,reject)=>{w.OrganizerTest.nachDauerhaftemSpeichern(()=>{assert.ok(disk,'real native-save envelope required');resolve(clone(disk));},reject);w.Tablet?.flush();});}};
}
function view(book){return clone(book.termine.map(t=>({id:t.id,uid:t.uid,source:t.icsQuelleId,wire:t.icsSerienUid,raw:t.icsRoundtrip,links:t.aufgaben,future:t.futureIdentity})));}
async function run({web,platform}) {
  inverseChecks();let checks=0;
  assert.equal(fixture.canonicalCommit,'067c38934b539943d8e1720abafd8a80b401d797');
  for(const entry of fixture.cases) {
    const b=await boot(web,platform);
    try {
      await Promise.resolve(b.w.App.importErgebnis(clone(entry.document)));
      await Promise.resolve(b.w.App.importErgebnis({aufgaben:[{uid:'retained-linked-task',titel:'Retained linked task',faellig:'2030-05-10',prio:2}]}));await tick();
      const data=b.t.daten();assert.equal(data.termine.length,entry.document.termine.length);
      assert.equal(data.aufgaben.length,1);const task=clone(data.aufgaben[0]);
      data.termine.forEach((t,i)=>{t.futureIdentity={marker:'retained-'+i};t.aufgaben=[task.uid];});
      const saved=await b.save(),before=view(saved),normalized=clone(b.t.normalisiere(saved));
      assert.equal(saved.termine.length,entry.document.termine.length,'latest durable save contains every imported row');
      assert.deepEqual(view(normalized),before,'distinct original identities, local IDs, references and unknowns survive normalization');
      assert.equal(normalized.aufgaben[0].uid,task.uid);assert.equal(normalized.aufgaben[0].id,task.id);
      for(let i=0;i<saved.termine.length;i++)assert.equal(saved.termine[i].uid,entry.document.termine[i].uid,'producer UID unchanged');
      const reopened=await boot(web,platform,saved);
      try {
        assert.deepEqual(view(reopened.t.daten()),before,'actual fresh init preserves each component');
        assert.equal(reopened.t.daten().aufgaben[0].uid,task.uid);assert.equal(reopened.t.daten().aufgaben[0].id,task.id);
        if(platform==='tablet')assert.ok(reopened.messages.some(m=>m.cmd==='tablet_loaded'),'strict load validation reached native acknowledgement');
        const day=entry.name==='distinct-rids'?'2030-05-10':'2030-05-06';
        const rows=reopened.t.termineAm(day,true);assert.equal(rows.length,2,'both explicitly coincident occurrences remain visible: '+entry.name);
        assert.equal(new Set(Array.from(rows,t=>t.id)).size,2);
        assert.equal(reopened.errors.length,0);
      } finally {reopened.close();}
      checks++;
    } finally {b.close();}
  }
  const b=await boot(web,platform);
  try {
    const a=clone(fixture.cases[0].document.termine[1]);a.id='first-local';
    const pair=(left,right,expected,label)=>{
      const book=b.t.leereDaten();book.termine=[{...clone(left),id:'pair-local-a'},{...clone(right),id:'pair-local-b'}];const prior=JSON.stringify(book);
      if(expected===1&&platform==='macos')assert.throws(()=>b.t.normalisiere(book),/refused lossy normalization/,
        label+': existing Mac lossless wrapper still rejects the unchanged core duplicate fold');
      else {const out=b.t.normalisiere(book);assert.equal(out.termine.length,expected,label);if(expected===2)assert.deepEqual(Array.from(out.termine,t=>t.id),['pair-local-a','pair-local-b']);}
      assert.equal(JSON.stringify(book),prior,label+' input immutable');checks++;
    };
    const same=clone(a);same.id='second-local';pair(a,same,1,'true qualified ICS duplicate still folds');
    const mutable=clone(same);pair(a,mutable,1,'first pass recognizes a true duplicate');mutable.icsRoundtrip[0]='RECURRENCE-ID:20300508T100000Z';pair(a,mutable,2,'later pass reparses mutated raw identity rather than reusing stale cached data');
    const rawUID=clone(a);rawUID.icsRoundtrip.unshift('UID:'+a.icsSerienUid);pair(rawUID,clone(rawUID),1,'matching raw wire UID still folds');
    const local={id:'local-a',uid:'ordinary-local',datum:'2030-05-10',zeit:'12:00',titel:'Ordinary local'};
    pair(local,{...local,id:'local-b'},1,'ordinary non-ICS true duplicate unchanged');
    pair(local,{...local,id:'local-b',uid:'other-local'},2,'ordinary independent local appointment unchanged');
    const withRID=(line)=>{const copy=clone(a);copy.id='other-local';copy.icsRoundtrip=copy.icsRoundtrip.map(x=>x.startsWith('RECURRENCE-ID')?line:x);return copy;};
    pair(a,{...same,icsQuelleId:'other-source'},2,'different qualified source');
    pair(a,{...same,icsSerienUid:'other-wire-UID'},2,'different original wire UID');
    pair({...a,icsSerienUid:'wire-caf\u00e9'},{...same,icsSerienUid:'wire-cafe\u0301'},2,'NFC/NFD wire UID bytes remain distinct');
    const missingRID=clone(a);missingRID.icsRoundtrip=missingRID.icsRoundtrip.filter(x=>!x.startsWith('RECURRENCE-ID'));
    pair(missingRID,clone(missingRID),2,'local detached alias without raw RID is ambiguous, never a guessed master');
    pair(a,withRID('RECURRENCE-ID:20300508T100000Z'),2,'different original RID');
    pair(a,withRID('RECURRENCE-ID;VALUE=DATE:20300507'),2,'different original VALUE type');
    pair(withRID('RECURRENCE-ID;TZID=Europe/Berlin:20300507T100000'),withRID('RECURRENCE-ID;TZID=Europe/Paris:20300507T100000'),2,'different opaque TZID');
    pair(a,withRID('RECURRENCE-ID;RANGE=THISANDFUTURE:20300507T100000Z'),2,'different RANGE role');
    pair(withRID('RECURRENCE-ID;VALUE=DATE-TIME;RANGE=THISANDFUTURE:20300507T100000Z'),withRID('RECURRENCE-ID;RANGE=THISANDFUTURE;VALUE=DATE-TIME:20300507T100000Z'),2,'equivalent differently spelled raw RID lines cannot be unioned into duplicate properties');
    pair(withRID('RECURRENCE-ID;TZID=Custom/caf\u00e9:20300507T100000'),withRID('RECURRENCE-ID;TZID=Custom/cafe\u0301:20300507T100000'),2,'NFC/NFD TZID bytes remain distinct');
    for(const [label,change] of [
      ['multiple RID',r=>r.icsRoundtrip.push('RECURRENCE-ID:20300508T100000Z')],
      ['duplicate parameter',r=>{r.icsRoundtrip=withRID('RECURRENCE-ID;VALUE=DATE-TIME;VALUE=DATE-TIME:20300507T100000Z').icsRoundtrip;}],
      ['unbalanced raw block',r=>r.icsRoundtrip.push('BEGIN:VALARM')],
      ['wrapped ambiguous component',r=>{r.icsRoundtrip=['BEGIN:VEVENT',...r.icsRoundtrip,'END:VEVENT'];}],
      ['nested RID in alarm',r=>r.icsRoundtrip.push('BEGIN:VALARM','RECURRENCE-ID:20300508T100000Z','END:VALARM')],
      ['raw UID contradicts metadata',r=>r.icsRoundtrip.unshift('UID:other-wire')],
      ['empty raw UID',r=>r.icsRoundtrip.unshift('UID:')],
      ['missing detached wire UID',r=>{r.icsSerienUid='';}],
      ['missing source identity',r=>{r.icsQuelleId='';}],
      ['malformed RID',r=>{r.icsRoundtrip=withRID('RECURRENCE-ID;VALUE=DATE:20300507T100000Z').icsRoundtrip;}]
    ]) {const changed=clone(same);change(changed);pair(a,changed,2,label+' conservatively stays separate');}
    await Promise.resolve(b.w.App.importErgebnis({termine:[clone(a),clone(a)]}));
    assert.equal(b.t.daten().termine.length,1,'actual App import still deduplicates an identical qualified record');
    await Promise.resolve(b.w.App.importErgebnis({termine:[clone(a)]}));
    assert.equal(b.t.daten().termine.length,1,'actual repeated import remains stable');checks++;
    assert.equal(b.errors.length,0);
  } finally {b.close();}
  console.log('Shared occurrence identity: '+checks+' '+platform+' checks; actual App/normalizer/save/reopen, host JS only.');return checks;
}
module.exports=run;
if(require.main===module)run({platform:process.argv[2],web:path.resolve(process.argv[3])}).catch(e=>{console.error(e);process.exitCode=1;});
