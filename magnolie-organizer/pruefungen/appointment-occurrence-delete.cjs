"use strict";
const fs=require("node:fs"), path=require("node:path"), Module=require("node:module"), assert=require("node:assert/strict");
const canonicalHarness=path.resolve(__dirname,"../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harnessPath=fs.existsSync(canonicalHarness)?canonicalHarness:path.resolve(__dirname,"../../../tests/desktop-state-regressions.js");
const harness=new Module(harnessPath,module);
harness.filename=harnessPath;harness.paths=Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath,"utf8").split("async function run(web)")[0]+"\nmodule.exports={boot,roots};",harnessPath);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const plain=value=>JSON.parse(JSON.stringify(value));
const dates=["2026-12-01","2026-12-08","2026-12-15"];
const local={id:"series",uid:"series-uid",datum:dates[0],zeit:"10:00",endZeit:"11:00",titel:"Synthetic weekly",wiederholung:{art:"weekly",bis:""}};
const cases=[
 ["local",local],
 ["date",{...local,zeit:"",endZeit:"",icsRoundtrip:["BEGIN:VEVENT","DTSTART;VALUE=DATE:20261201","RRULE:FREQ=WEEKLY;COUNT=5","END:VEVENT"]}],
 ["utc",{...local,icsRoundtrip:["BEGIN:VEVENT","DTSTART:20261201T100000Z","DTEND:20261201T110000Z","RRULE:FREQ=WEEKLY;COUNT=5","END:VEVENT"]}],
 ["tzid",{...local,icsRoundtrip:["BEGIN:VEVENT","DTSTART;TZID=Europe/Berlin:20261201T100000","DTEND;TZID=Europe/Berlin:20261201T110000","RRULE:FREQ=WEEKLY;COUNT=5","END:VEVENT"]}],
 ["floating",{...local,icsRoundtrip:["BEGIN:VEVENT","DTSTART:20261201T100000","DTEND:20261201T110000","RRULE:FREQ=WEEKLY;COUNT=5","END:VEVENT"]}],
 ["floating-foreign-display",{...local,icsAnzeigeZeitzone:"Europe/Berlin",icsRoundtrip:["BEGIN:VEVENT","DTSTART:20261201T100000","DTEND:20261201T110000","RRULE:FREQ=WEEKLY;COUNT=5","END:VEVENT"]}]
];
async function remove(b,day,accept=true){
 const occurrence=b.t.termineAm(day,true).find(value=>value.id==="series");assert.ok(occurrence,day);
 b.t.oeffneTerminBlatt(occurrence,day);
 const button=b.w.document.querySelector("#tb-vorkommen-loeschen");assert.ok(button,"Single-occurrence action missing");button.click();
 b.w.document.querySelector(accept?"#dialog-ja":"#dialog-nein").click();await tick();
}
(async()=>{
 let passed=0;
 for(const web of harness.exports.roots){
  for(const [name,entry] of cases){
   const b=await harness.exports.boot(web,{termine:[entry]});
   try{
    const before=plain(b.t.daten().termine[0]);
    await remove(b,dates[1],false);
    assert.deepEqual(plain(b.t.daten().termine[0]),before,"Cancel changed series");
    [...b.w.document.querySelectorAll("#termin-schleier .tb-fuss button")].find(button=>button.textContent==="Cancel").click();
    await remove(b,dates[1]);
    assert.equal(b.t.daten().termine.length,1,"Single deletion removed the master");
    assert.deepEqual(dates.map(day=>b.t.termineAm(day,true).some(value=>value.id==="series")),[true,false,true],name);
    assert.equal(b.t.daten().tombstones?.termine?.length||0,0,"Single deletion created a whole-series tombstone");
    const trash=b.t.daten().papierkorb[0];assert.ok(trash.appointment_occurrence);
    const missing=plain(trash);delete missing.appointment_occurrence;
    assert.equal(b.t.ausDemPapierkorb(missing),false,"Missing restore metadata duplicated the archived whole series");
    const reopened=b.t.normalisiere(plain(b.t.daten()));
    assert.ok(reopened.papierkorb[0].appointment_occurrence,"Save/reopen lost single-occurrence restore metadata");
    assert.equal(b.t.ausDemPapierkorb(reopened.papierkorb[0],reopened),false,"Private Notes restore must not mutate appointments");
    b.t.daten().termine[0].titel="Edited title must survive restore";
    assert.equal(b.t.ausDemPapierkorb(trash),true,"Restore refused unrelated title edit");
    assert.equal(b.t.daten().termine[0].titel,"Edited title must survive restore");
    assert.deepEqual(dates.map(day=>b.t.termineAm(day,true).some(value=>value.id==="series")),[true,true,true]);
    b.t.planeSpeichern();
    await remove(b,dates[0]);
    assert.deepEqual(dates.map(day=>b.t.termineAm(day,true).some(value=>value.id==="series")),[false,true,true],"Deleting first occurrence shortened series");
    passed++;
   }finally{b.close();}
  }
  {
   const b=await harness.exports.boot(web,{termine:[local]});
   try{
    await remove(b,dates[1]);await remove(b,dates[2]);
    assert.equal(b.t.ausDemPapierkorb(b.t.daten().papierkorb[0]),true);
    assert.deepEqual(dates.map(day=>b.t.termineAm(day,true).some(value=>value.id==="series")),[true,true,false],"Restoring one occurrence removed another exclusion");
    const trash=b.t.daten().papierkorb[0];b.t.daten().termine[0].wiederholung.art="daily";
    assert.equal(b.t.ausDemPapierkorb(trash),false,"Restore overwrote an altered series");passed++;
   }finally{b.close();}
  }
  {
   const b=await harness.exports.boot(web,{termine:[local]});
   try{
    const occurrence=b.t.termineAm(dates[1],true).find(value=>value.id==="series");b.t.oeffneTerminBlatt(occurrence,dates[1]);
    b.t.daten().termine[0].titel="Concurrent native change";
    b.w.document.querySelector("#tb-vorkommen-loeschen").click();b.w.document.querySelector("#dialog-ja").click();await tick();
    assert.equal(b.t.daten().papierkorb.length,0);assert.ok(b.t.termineAm(dates[1],true).some(value=>value.id==="series"));passed++;
   }finally{b.close();}
  }
  {
   const b=await harness.exports.boot(web,{termine:[local],einstellungen:{papierkorb:{an:false}}});
   try{
    b.w.eval(fs.readFileSync(path.join(web,"i18n/de.js"),"utf8"));b.w.MagnolieI18n.setLocale("de");
    const occurrence=b.t.termineAm(dates[1],true).find(value=>value.id==="series");b.t.oeffneTerminBlatt(occurrence,dates[1]);
    assert.equal(b.w.document.querySelector("#tb-vorkommen-loeschen").textContent,"Nur dieses Vorkommen löschen");
    assert.equal(b.w.document.querySelector("#tb-loeschen").textContent,"Terminserie löschen");
    b.w.document.querySelector("#tb-vorkommen-loeschen").click();
    assert.equal(b.w.document.querySelector("#dialog-text").textContent,"Papierkorb deaktiviert: Die ausgewählten Einträge endgültig löschen?");
    b.w.document.querySelector("#dialog-ja").click();await tick();
    assert.equal(b.t.daten().papierkorb.length,0);assert.equal(b.t.daten().termine.length,1);
    assert.deepEqual(dates.map(day=>b.t.termineAm(day,true).some(value=>value.id==="series")),[true,false,true]);passed++;
   }finally{b.close();}
  }
  {
   const b=await harness.exports.boot(web,{termine:[local]});
   try{
    await remove(b,dates[1]);const saved=plain(b.t.daten());
    const reopen=await harness.exports.boot(web,saved);
    try{
     assert.equal(reopen.t.ausDemPapierkorb(reopen.t.daten().papierkorb[0]),true,"Actual reopened archive failed to restore");
     assert.equal(reopen.t.daten().termine.length,1,"Restore duplicated the whole series");
     assert.ok(reopen.t.termineAm(dates[1],true).some(value=>value.id==="series"));passed++;
    }finally{reopen.close();}
   }finally{b.close();}
  }
  {
   const b=await harness.exports.boot(web,{termine:[{...local,icsReadOnly:true}]});
   try{
    b.t.oeffneTerminBlatt(b.t.termineAm(dates[1],true).find(value=>value.id==="series"),dates[1]);
    assert.equal(b.w.document.querySelector("#tb-vorkommen-loeschen"),null);
    assert.equal(b.w.document.querySelector("#tb-loeschen"),null);passed++;
   }finally{b.close();}
  }
  {
   const b=await harness.exports.boot(web,{termine:[local]});
   try{
    b.t.oeffneTerminBlatt(b.t.termineAm(dates[1],true).find(value=>value.id==="series"),dates[1]);
    b.w.document.querySelector("#tb-loeschen").click();assert.match(b.w.document.querySelector("#dialog-text").textContent,/every occurrence.*series/);
    b.w.document.querySelector("#dialog-ja").click();await tick();
    assert.equal(b.t.daten().termine.length,0);assert.equal(b.t.ausDemPapierkorb(b.t.daten().papierkorb[0]),true);
    assert.equal(b.t.daten().termine.length,1);passed++;
   }finally{b.close();}
  }
  {
   const entry={...cases.find(value=>value[0]==="utc")[1],icsRoundtrip:["BEGIN:VEVENT","DTSTART:20261201T100000Z","RRULE:FREQ=WEEKLY;COUNT=5","RDATE:20261208T150000Z","END:VEVENT"]};
   const b=await harness.exports.boot(web,{termine:[entry]});
   try{
    assert.equal(b.t.termineAm(dates[1],true).filter(value=>value.id==="series").length,2);
    await remove(b,dates[1]);
    const remaining=b.t.termineAm(dates[1],true).filter(value=>value.id==="series");
    assert.equal(remaining.length,1);assert.equal(remaining[0].zeit,"15:00","EXDATE removed another time on the same day");passed++;
   }finally{b.close();}
  }
 }
 console.log(`${passed} dual-desktop occurrence deletion cases PASS`);
})().catch(error=>{console.error(error);process.exitCode=1;});
