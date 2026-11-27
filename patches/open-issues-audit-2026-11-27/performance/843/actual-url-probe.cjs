"use strict";
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]),output=path.resolve(process.argv[3]),expectClean=process.argv.includes('--expect-clean');
const file=path.join(root,'magnolie-organizer-windows/tests/desktop-state-regressions.js');
const mod=new Module(file,module);mod.filename=file;mod.paths=Module._nodeModulePaths(path.dirname(file));
mod._compile(fs.readFileSync(file,'utf8').split('async function run(web)')[0]+'\nmodule.exports={boot,roots};',file);
(async()=>{
 const results=[];let failed=false;
 for(const web of mod.exports.roots)for(const mode of ['constructor','worker-error','provider-mismatch','successful-owner']){
  const b=await mod.exports.boot(web,{}),urls=new Map(),listeners=new Map();let created=0,revoked=0,constructed=0,terminated=0;
  const add=b.w.addEventListener.bind(b.w),remove=b.w.removeEventListener.bind(b.w);
  b.w.addEventListener=(type,fn,options)=>{if(type!=='unload')return add(type,fn,options);const wrapped=function(event){if(options?.once)listeners.delete(fn);return fn.call(this,event);};listeners.set(fn,wrapped);return add(type,wrapped,options);};
  b.w.removeEventListener=(type,fn,options)=>{const wrapped=type==='unload'?listeners.get(fn):null;if(type==='unload')listeners.delete(fn);return remove(type,wrapped||fn,options);};
  b.w.Blob=Blob;
  b.w.URL.createObjectURL=blob=>{const url=URL.createObjectURL(blob);urls.set(url,blob.size);created++;return url;};
  b.w.URL.revokeObjectURL=url=>{URL.revokeObjectURL(url);if(urls.delete(url))revoked++;};
  b.w.Worker=class{constructor(){constructed++;if(mode==='constructor')throw Error('synthetic startup failure');}postMessage(){}terminate(){terminated++;}};
  const sample=attempts=>({attempts,active_object_urls:urls.size,retained_blob_bytes:[...urls.values()].reduce((a,b)=>a+b,0),active_unload_listeners:listeners.size,created,revoked,constructed,terminated});
  try{
   const samples=[];
   for(let i=0;i<32;i++){
    const item={uid:'owned-url-probe-'+i,datum:'2026-06-12',zeit:'09:00',icsRoundtrip:['DTSTART:20260612T090000Z','DURATION:PT1H','RRULE:FREQ=DAILY;COUNT=2']};
    assert.equal(b.t.icsRuntime('expand',item,[Date.parse('2026-06-12'),Date.parse('2026-06-14')]),null);
    if(mode==='worker-error')b.t.icsRuntime.state.worker.onerror(Error('synthetic worker crash'));
    if(mode==='provider-mismatch')b.t.icsRuntime.state.worker.onmessage({data:{key:[...b.t.icsRuntime.state.jobs.keys()].at(-1),timeZoneIdentity:'wrong-provider'}});
    if([0,7,15,31].includes(i))samples.push(sample(i+1));
   }
   const beforeUnload=sample(32);b.w.dispatchEvent(new b.w.Event('unload'));const afterUnload=sample(32);
   const expectedLive=mode==='successful-owner'?1:0;
   if(expectClean&&(beforeUnload.active_object_urls!==expectedLive||beforeUnload.active_unload_listeners!==expectedLive||afterUnload.active_object_urls!==0||afterUnload.active_unload_listeners!==0))failed=true;
   if(mode==='successful-owner'){assert.equal(beforeUnload.active_object_urls,1);assert.equal(constructed,1);assert.equal(afterUnload.active_object_urls,0);}
   const row={edition:web.includes('windows')?'windows-source':'linux-source',scenario:mode,samples,before_unload:beforeUnload,after_unload:afterUnload};results.push(row);console.log(JSON.stringify(row));
  }finally{for(const url of urls.keys())URL.revokeObjectURL(url);b.close();}
 }
 fs.writeFileSync(output,JSON.stringify({root,expect_clean:expectClean,passed:!failed,boundary:'Actual unmodified or patched icsRuntime product function and real Node Blob object-URL registry; Worker is an explicitly controlled startup/crash/provider fault seam. URL bytes are registered blob data, not native browser heap. No native tray/month claim.',results},null,2)+'\n');
 if(failed)throw Error('URL/listener cleanup did not match expected lifecycle');
})().catch(error=>{console.error(error);process.exitCode=1;});
