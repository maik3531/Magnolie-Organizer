const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const {webcrypto,createHash}=require('node:crypto');
const root=path.resolve(__dirname,'..'), web=path.join(root,'app/build/generated/projection/assets/web');
const read=f=>fs.readFileSync(path.join(web,f),'utf8');
const tick=()=>new Promise(r=>setTimeout(r,30));
(async()=>{
  const errors=[], console=new VirtualConsole(); console.on('jsdomError',e=>errors.push(e));
  const dom=new JSDOM(read('index.html'),{url:'https://appassets.androidplatform.net/assets/web/index.html',
    runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
  const w=dom.window; w.TextEncoder=TextEncoder; w.TextDecoder=TextDecoder;
  Object.defineProperty(w,'crypto',{value:webcrypto}); w.Element.prototype.getAnimations=()=>[];
  const session=webcrypto.randomUUID(); let revision=webcrypto.randomUUID();
  w.TabletNative={postMessage(text){const m=JSON.parse(text); setTimeout(()=>{
    if(m.cmd==='bereit') w.Tablet.receive({callback:'init',payload:{daten:null,session,revision}});
    if(m.cmd==='tablet_loaded') w.Tablet.receive({callback:'ready',payload:{session,revision}});
    if(m.cmd==='speichern') {
      assert.equal(m.session,session); assert.equal(m.revision,revision); revision=webcrypto.randomUUID();
      w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision:m.revision,revision}});
    }
  },0);}};
  let coreSHA256='';
  try {
    for(const f of ['beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','anwendung.js']) {
      const source=f==='anwendung.js' && process.env.TIMEZONE_INTEROP_PUBLISHED==='1'
        ? require('node:child_process').execFileSync('git',['show','v2.0.30:magnolie-organizer/web/anwendung.js'],{cwd:path.join(root,'..'),encoding:'utf8',maxBuffer:4*1024*1024}) : read(f);
      if(f==='anwendung.js') coreSHA256=createHash('sha256').update(source).digest('hex');
      w.eval(source);
    }
    await tick(); await tick();
    w.eval(fs.readFileSync(path.join(root,'../port-adapters/tests/timezone-interop.js'),'utf8'));
    const fixture=JSON.parse(fs.readFileSync(path.join(root,'../port-adapters/tests/timezone-interop-oracle.json'),'utf8'));
    const result=w.NativeTimezoneInterop.run(fixture);
    assert.equal(result.clocks,37); assert.equal(result.checks,148); assert.equal(result.bookUnchanged,true);
    // The installed host Intl can predate Morocco's normative 2026-09-20 change.
    // Keep this visible; the actual native acceptance stage rejects all differences.
    assert.equal(result.failures.length,process.versions.tz==='2026b'?9:0);
    for (const failure of result.failures) {
      assert.equal(failure.identifier,'Africa/Casablanca'); assert.ok((failure.wall.startsWith('2400-') || failure.wall==='2026-10-15T12:30'));
      assert.ok(['shared-appointment-reminder','shared-task-source-reminder','webview-intl-wall'].includes(failure.path));
      if(failure.path==='webview-intl-wall') assert.equal(failure.actual,failure.wall.replace('12:30','13:30'));
      else assert.equal(failure.actual,failure.expected-3600000);
    }
    assert.equal(errors.length,0);
    global.console.log(JSON.stringify({hostAudit:true,node:process.version,icu:process.versions.icu,tzdb:process.versions.tz,coreSHA256,core:process.env.TIMEZONE_INTEROP_PUBLISHED==='1'?'published-v2.0.30':'current-projection',clocks:result.clocks,checks:result.checks,differences:result.failures,nativeAndroidProof:false}));
  } finally {dom.window.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
