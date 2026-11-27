"use strict";
// Fault-injection seam around the actual production icsRuntime() and real Node
// Blob object-URL allocation. This is not a running native browser Worker test.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../open-audit-performance-tests');
const file=path.join(root,'magnolie-organizer-windows/tests/desktop-state-regressions.js');
const mod=new Module(file,module);mod.filename=file;mod.paths=Module._nodeModulePaths(path.dirname(file));
mod._compile(fs.readFileSync(file,'utf8').split('async function run(web)')[0]+'\nmodule.exports={boot,roots};',file);
(async()=>{
 const results=[];
 for(const web of mod.exports.roots){
  const b=await mod.exports.boot(web,{});const urls=new Map();let created=0,revoked=0,unloadAdded=0;
  const add=b.w.addEventListener.bind(b.w);b.w.addEventListener=(type,listener,options)=>{if(type==='unload')unloadAdded++;return add(type,listener,options);};
  b.w.Blob=Blob;
  b.w.URL.createObjectURL=blob=>{const url=URL.createObjectURL(blob);urls.set(url,blob.size);created++;return url;};
  b.w.URL.revokeObjectURL=url=>{URL.revokeObjectURL(url);if(urls.delete(url))revoked++;};
  b.w.Worker=class{constructor(){throw Error('synthetic Worker startup failure');}};
  try{
   const samples=[];
   for(let i=0;i<32;i++){
    const item={uid:'owned-failed-worker-'+i,datum:'2026-06-12',zeit:'09:00',icsRoundtrip:['DTSTART:20260612T090000Z','DURATION:PT1H','RRULE:FREQ=DAILY;COUNT=2']};
    assert.equal(b.t.icsRuntime('expand',item,[Date.parse('2026-06-12'),Date.parse('2026-06-14')]),null);
    if([0,7,15,31].includes(i))samples.push({attempts:i+1,active_object_urls:urls.size,retained_blob_bytes:[...urls.values()].reduce((a,b)=>a+b,0),unload_listeners_added:unloadAdded,created,revoked});
   }
   const beforeUnload={active_object_urls:urls.size,retained_blob_bytes:[...urls.values()].reduce((a,b)=>a+b,0)};
   b.w.dispatchEvent(new b.w.Event('unload'));
   const row={edition:web.includes('windows')?'windows-source':'linux-source',samples,before_unload:beforeUnload,after_unload:{active_object_urls:urls.size,revoked},seam:'Actual production failed Worker-constructor path, real Blob URL store. Constructor deliberately fails; no running browser Worker or native tray.'};results.push(row);console.log(JSON.stringify(row));
  }finally{for(const url of urls.keys())URL.revokeObjectURL(url);b.close();}
 }
 fs.writeFileSync(path.join(__dirname,'worker-url-lifecycle-results.json'),JSON.stringify({results},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
