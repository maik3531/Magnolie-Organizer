"use strict";
// Reuse the existing isolated desktop boot harness. Only the unchanged actual
// synchronous search entrypoint is measured: no native input or frame claim.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../open-audit-performance-tests');
const file=path.join(root,'magnolie-organizer-windows/tests/desktop-state-regressions.js');
const mod=new Module(file,module);mod.filename=file;mod.paths=Module._nodeModulePaths(path.dirname(file));
mod._compile(fs.readFileSync(file,'utf8').split('async function run(web)')[0]+'\nmodule.exports={boot,roots};',file);
(async()=>{
 const results=[];
 for(const web of mod.exports.roots){
  const b=await mod.exports.boot(web,{});
  try{
   for(const count of [10000,50000]){
    b.t.daten().kontakte=Array.from({length:count},(_,i)=>({id:'load-contact-'+i,nachname:'Contact '+i}));
    b.t.daten().termine=Array.from({length:count},(_,i)=>({id:'load-event-'+i,titel:i===count-1?'Needlecore':'Appointment '+i,datum:'2026-06-12',zeit:'09:00',endZeit:'10:00',kontaktId:'load-contact-'+i,wiederholung:{art:'none',bis:''}}));
    for(const [name,term,expected] of [['last-title','needlecore',1],['missing-text','nomatchingtitle',0],['missing-with-digits','nomatchingtitle2026',0],['date-first-101','2026-06-12',101]]){
     const elapsed=[];
     for(let rep=0;rep<3;rep++){
      const start=performance.now();const hits=b.t.suchTrefferFuer('kalender',[term],101);elapsed.push(performance.now()-start);assert.equal(hits.length,expected,name);
     }
     const row={edition:web.includes('windows')?'windows-source':'linux-source',records_per_domain:count,total_contact_plus_event_records:count*2,case:name,runs_ms:elapsed.map(v=>+v.toFixed(3)),hits:expected};results.push(row);console.log(JSON.stringify(row));
    }
   }
  }finally{b.close();}
 }
 fs.writeFileSync(path.join(__dirname,'core-search-results.json'),JSON.stringify({boundary:'Actual search function with existing boot harness. Timers and native bridge are fixture seams; no GUI frame, saved disk or long-run claim. No invented latency assertion.',results},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
