// Fixture generator/checker: actual generated common UI import -> native-save envelope.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {webcrypto,createHash}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..'),web=path.join(root,'app/build/generated/projection/assets/web');
const fixtureFile=path.join(root,'app/src/test/resources/calendar-export-normalized-ui.json');
const golden=JSON.parse(fs.readFileSync(fixtureFile));
const sourceInput=process.argv[2];
const input=sourceInput ? JSON.parse(fs.readFileSync(sourceInput)) : {source:golden.source,document:golden.importDocument};
const canonical=fs.readFileSync(path.join(root,'../magnolie-organizer/web/anwendung.js'),'utf8');
const released=require('node:child_process').execFileSync('git',['show','067c38934b539943d8e1720abafd8a80b401d797:magnolie-organizer/web/anwendung.js'],{cwd:root,maxBuffer:4*1024*1024}).toString();
const projected=fs.readFileSync(path.join(web,'anwendung.js'),'utf8');
const functionHash=(source,name)=>{
 const start=source.indexOf('  function '+name+'(');assert.ok(start>=0,name);
 const end=source.indexOf('\n  }',start)+4;assert.ok(end>start,name);
 return createHash('sha256').update(source.slice(start,end)).digest('hex');
};
const normalizerFunctionSHA256={};
for(const name of Object.keys(golden.normalizerFunctionSHA256)) {
 assert.equal(functionHash(released,name),golden.normalizerFunctionSHA256[name],name+' published reference changed');
 normalizerFunctionSHA256[name]=functionHash(canonical,name);
 assert.equal(functionHash(projected,name),normalizerFunctionSHA256[name],name+' diverged from current canonical sources');
}
const errors=[],virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',error=>errors.push(error));
const generated=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{runScripts:'outside-only',pretendToBeVisual:true,
  url:'https://appassets.androidplatform.net/assets/web/index.html',virtualConsole});
const w=generated.window; let disk=null,revision=webcrypto.randomUUID();const session=webcrypto.randomUUID();
w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w,'crypto',{value:webcrypto});
w.Element.prototype.getAnimations=()=>[];
w.TabletNative={postMessage(text){const m=JSON.parse(text);setTimeout(()=>{
  if(!w.document)return;
  if(m.cmd==='bereit')w.Tablet.receive({callback:'init',payload:{daten:null,session,revision}});
  if(m.cmd==='tablet_loaded')w.Tablet.receive({callback:'ready',payload:{session,revision}});
  if(m.cmd==='speichern'){
    assert.equal(m.session,session);assert.equal(m.revision,revision);disk=JSON.parse(m.text);
    revision=webcrypto.randomUUID();w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision:m.revision,revision}});
  }
},0)}};
for(const name of ['normative-timezones.js','beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','mcp-protocol.js','anwendung.js'])w.eval(fs.readFileSync(path.join(web,name),'utf8'));
const wait=()=>new Promise(resolve=>setTimeout(resolve,40));
(async()=>{
 await wait();await wait();
 await Promise.resolve(w.App.importErgebnis(input.document));w.Tablet.flush();await wait();await wait();
 const normalized=disk.termine.find(item=>item.uid==='normalized-valarm-event');assert.ok(normalized);
 assert.equal(normalized.alarme.length,2);assert.equal(normalized.kalenderQuelle.id,normalized.icsQuelleId);
 delete normalized.id;delete normalized.geaendert;delete normalized.angelegt;
 const fixture={source:input.source,importDocument:input.document,normalizedRecord:normalized,
  contractTag:'v2.0.30',contractCommit:'067c38934b539943d8e1720abafd8a80b401d797',normalizerFunctionSHA256,
  recordedUiSHA256:createHash('sha256').update(fs.readFileSync(path.join(root,'../magnolie-organizer/web/anwendung.js'))).digest('hex')};
 if(process.argv.includes('--record'))fs.writeFileSync(fixtureFile,JSON.stringify(fixture,null,2)+'\n');
 else {
  const expected=JSON.parse(fs.readFileSync(fixtureFile));
  for(const key of ['recordedUiSHA256','normalizerFunctionSHA256']) {delete expected[key];delete fixture[key];}
  assert.deepEqual(fixture,expected,'Saved shared UI calendar projection drifted; review its native export contract.');
 }
 assert.equal(errors.length,0,errors.map(String).join('\n'));
 process.stdout.write('Actual common App.importErgebnis and durable native-save envelope: two VALARMs and source display preserved.\n');
 generated.window.close();
})().catch(error=>{generated.window.close();console.error(error);process.exitCode=1;});
