"use strict";
// #447: actual canonical application, no projected replacement or Intl override.
const fs=require("node:fs"),path=require("node:path"),Module=require("node:module"),assert=require("node:assert/strict");
const {Worker}=require("node:worker_threads");
const os=require("node:os");
const file=path.join(__dirname,"desktop-state-regressions.js"),host=new Module(file,module);
host.filename=file;host.paths=Module._nodeModulePaths(__dirname);
host._compile(fs.readFileSync(file,"utf8").split("async function run(web)")[0]+"\nmodule.exports={boot,roots};",file);
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
// Independent UTC reference clocks, not calculated by the provider under test.
const clocks=[
 ["Africa/Casablanca","2026-10-15","12:30","2026-10-15T12:30:00Z"],
 ["Asia/Almaty","2026-01-15","12:30","2026-01-15T07:30:00Z"],
 ["Asia/Almaty","2400-07-15","12:30","2400-07-15T07:30:00Z"],
 ["Europe/Berlin","2400-07-15","12:30","2400-07-15T10:30:00Z"],
 ["Asia/Gaza","2074-07-15","12:30:45","2074-07-15T09:30:45Z"],
 ["Europe/Paris","1910-01-15","12:30:45","1910-01-15T12:21:24Z"]
];
const watchdog=setTimeout(()=>{console.error("Canonical timezone regression timed out");process.exit(1);},60000);
(async()=>{
 let checks=0;const failures=[];
 for(const web of host.exports.roots) {
  const b=await host.exports.boot(web),threads=[],sources=new Map();let workerSource="",poisonNextRequest=false,workerFolder=null;
  const check=(name,actual,expected)=>{checks++;if(actual!==expected)failures.push({web,name,actual,expected});};
  try {
   const w=b.w,T=b.t,D=T.daten(),before=JSON.stringify(D);
   const scripts=Array.from(w.document.querySelectorAll("script[src]"),node=>node.getAttribute("src"));
   assert.equal(scripts.filter(name=>name==="normative-timezones.js").length,1);
   assert.ok(scripts.indexOf("normative-timezones.js")<scripts.indexOf("anwendung.js"));checks+=2;
   assert.equal(w.MagnolieTime.identity.tzdbVersion,"2026egtz");
   assert.equal(w.MagnolieTime.identity.payloadSHA256,"2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c");checks+=2;
   const saved=D.einstellungen.regional.timeZone;
   try {
    for(const [zone,datum,zeit,utc]of clocks) {
     D.einstellungen.regional.timeZone=zone;
     // This appointment helper explicitly takes five civil minute fields.
     // Second-preserving ICS paths are checked below, not inferred from it.
     if(zeit.length===5)check(zone+" appointment "+datum,+T.terminZeitpunkt({datum,zeit}),Date.parse(utc));
     const stamp=datum.replace(/-/g,"")+"T"+zeit.replace(/:/g,"")+(zeit.length===5?"00":"");
     const rows=T.icsExpansion({icsRoundtrip:["DUE;TZID="+zone+":"+stamp]},-Infinity,Infinity,true);
     check(zone+" task count",rows.length,1);check(zone+" task UTC",rows[0]?.icsStartUtc,Date.parse(utc));
    }
    // A source VTIMEZONE overrides even an identically named normative zone.
    const source=["BEGIN:VTIMEZONE","TZID:Europe/Berlin","BEGIN:STANDARD","DTSTART:19700101T000000","TZOFFSETFROM:+235959","TZOFFSETTO:+235959","END:STANDARD","END:VTIMEZONE"];
    const raw=["DTSTART;TZID=Europe/Berlin:20260328T100000","DURATION:PT0S"];
    const custom=T.icsExpansion({icsTimezones:[source],icsRoundtrip:raw,icsDisplayTarget:"UTC"},-Infinity,Infinity);
    check("source timezone seconds",custom[0]?.icsStartUtc,Date.parse("2026-03-27T10:00:01Z"));
    assert.deepEqual(Array.from(custom[0].icsRoundtrip),raw);checks++;
    const gap=T.icsExpansion({icsRoundtrip:["DTSTART;TZID=Europe/Berlin:20260328T023000","DURATION:PT0S","RRULE:FREQ=DAILY;COUNT=3"],icsDisplayTarget:"UTC"},-Infinity,Infinity);
    assert.deepEqual(Array.from(gap,row=>row.icsStartUtc),["2026-03-28T01:30:00Z","2026-03-30T00:30:00Z","2026-03-31T00:30:00Z"].map(Date.parse));checks++;
    const fold=T.icsExpansion({icsRoundtrip:["DTSTART;TZID=Europe/Berlin:20261024T023045","DURATION:PT0S","RRULE:FREQ=DAILY;COUNT=3"],icsDisplayTarget:"UTC"},-Infinity,Infinity);
    assert.deepEqual(Array.from(fold,row=>row.icsStartUtc),["2026-10-24T00:30:45Z","2026-10-25T00:30:45Z","2026-10-26T01:30:45Z"].map(Date.parse));checks++;
    D.einstellungen.regional.timeZone="UTC";
    w.Blob=class{constructor(parts){this.text=parts.join("");}};
    w.URL.createObjectURL=blob=>{const url="blob:timezone-test-"+sources.size;sources.set(url,blob.text);return url;};w.URL.revokeObjectURL=()=>{};
    workerFolder=fs.mkdtempSync(path.join(os.tmpdir(),"magnolie-timezone-worker-"));
    w.Worker=class {
     constructor(url){workerSource=sources.get(url);assert.ok(workerSource);
      const prelude="const {parentPort}=require('node:worker_threads');global.self=globalThis;global.postMessage=data=>parentPort.postMessage(data);parentPort.on('message',data=>self.onmessage({data}));\n";
      // A real absolute worker file avoids Bun/Windows' crashing eval-worker
      // path without changing any of the generated product worker bytes.
      const workerFile=path.join(workerFolder,"worker-"+threads.length+".cjs");
      fs.writeFileSync(workerFile,prelude+workerSource,{flag:"wx"});
      assert.equal(fs.readFileSync(workerFile,"utf8"),prelude+workerSource);
      this.thread=new Worker(workerFile);threads.push(this.thread);
      this.thread.on("message",data=>this.onmessage?.({data}));this.thread.on("error",error=>this.onerror?.(error));}
     postMessage(data){if(poisonNextRequest){data={...data,timeZoneIdentity:"0".repeat(64)};poisonNextRequest=false;}this.thread.postMessage(data);}terminate(){return this.thread.terminate();}
    };
    const item={uid:"fixture-data-not-executable-447",icsRoundtrip:["DTSTART;TZID=Asia/Gaza:20740715T123045","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=2"]};
    const args=[Date.parse("2074-07-14T00:00Z"),Date.parse("2074-07-17T00:00Z")];
    let rows=T.icsRuntime("expand",item,args);
    for(let turn=0;!Array.isArray(rows)&&turn<150;turn++){await tick();rows=T.icsRuntime("expand",item,args);}
    assert.ok(Array.isArray(rows),T.icsRuntime.lastError);assert.ok(T.icsRuntime.state.worker);checks+=2;
    check("worker seconds first",rows[0]?.icsStartUtc,Date.parse("2074-07-15T09:30:45Z"));
    check("worker seconds next",rows[1]?.icsStartUtc,Date.parse("2074-07-16T09:30:45Z"));
    assert.ok(!workerSource.includes(item.uid));checks++;
    assert.ok(Array.from(T.icsRuntime.state.jobs.keys()).every(key=>JSON.parse(key)[0]===w.MagnolieTime.identity.payloadSHA256));checks++;
    // Actual isolated worker receives a deliberately wrong request identity.
    poisonNextRequest=true;
    const rejected={...item,uid:"wrong-request-identity-447"};
    T.icsRuntime("expand",rejected,args);
    let job=Array.from(T.icsRuntime.state.jobs.values()).at(-1);
    for(let turn=0;job.status==="pending"&&turn<150;turn++)await tick();
    assert.equal(job.status,"error");assert.equal(job.error,"timezone-provider-identity");assert.ok(!job.result);checks+=3;
    // Separately exercise the Main receiver's malformed-response countercase.
    T.icsRuntime("expand",{...item,uid:"wrong-response-identity-447"},args);
    const key=Array.from(T.icsRuntime.state.jobs.keys()).at(-1);job=T.icsRuntime.state.jobs.get(key);
    assert.equal(job.status,"pending");
    T.icsRuntime.state.worker.onmessage({data:{key,timeZoneIdentity:"0".repeat(64),result:[{icsStartUtc:0}]}});
    assert.equal(job.status,"error");assert.equal(job.error,"timezone-provider-identity");assert.equal(job.result,null);
    assert.equal(T.icsRuntime.state.worker,null);checks+=4;
   } finally {D.einstellungen.regional.timeZone=saved;}
   assert.equal(JSON.stringify(D),before);checks++;
  } finally {for(const thread of threads)await thread.terminate();b.close();if(workerFolder)fs.rmSync(workerFolder,{recursive:true});}
 }
 assert.deepEqual(failures,[]);
 console.log(JSON.stringify({canonicalTimezoneChecks:checks,bothGUIs:host.exports.roots.length===2,
   runtime:process.versions.bun?"Bun "+process.versions.bun:"Node "+process.version,
   isolatedWorkerThreads:true,nativeBrowserAcceptance:false}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>clearTimeout(watchdog));
