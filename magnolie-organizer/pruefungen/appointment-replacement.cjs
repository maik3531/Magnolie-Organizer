"use strict";
const fs=require("node:fs"),path=require("node:path"),Module=require("node:module"),assert=require("node:assert/strict");
const harnessPath=path.resolve(__dirname,"../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness=new Module(harnessPath,module);harness.filename=harnessPath;harness.paths=Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath,"utf8").split("async function run(web)")[0]+"\nmodule.exports={boot,roots};",harnessPath);
const plain=value=>JSON.parse(JSON.stringify(value));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const base={id:"series",uid:"master-uid",titel:"Synthetic fixture",datum:"2026-12-01",zeit:"10:00",endZeit:"11:00",ort:"Fixture location",notiz:"Preserve",wiederholung:{art:"weekly",bis:""}};
function choose(b,day="2026-12-08",date="2026-12-09"){
 const occurrence=b.t.termineAm(day,true).find(value=>value.id==="series");assert.ok(occurrence);
 b.t.oeffneTerminBlatt(occurrence,day);b.w.document.querySelector("#tb-vorkommen-loeschen").click();
 const toggle=b.w.document.querySelector("#tb-ersatz-an");assert.ok(toggle&&!toggle.checked);
 assert.ok(b.w.document.querySelector("#tb-ersatz-datum").disabled);
 toggle.checked=true;toggle.dispatchEvent(new b.w.Event("change",{bubbles:true}));
 b.t.setzeDatumswert(b.w.document.querySelector("#tb-ersatz-datum"),date);
 const time=b.w.document.querySelector("#tb-ersatz-zeit"), initial=time?.value;if(time)time.value="14:30";
 return initial;
}
(async()=>{
 let count=0;
 for(const web of harness.exports.roots){
  for(const kind of ["local","utc","tzid","seconds","all-day","cancel","invalid","stale","edited-restore","provider-restore","reopen","german","dst-gap","dst-duration"]){
   if(process.env.MAGNOLIE_REPLACEMENT_CASE&&!kind.startsWith(process.env.MAGNOLIE_REPLACEMENT_CASE))continue;
   const entry={...base};
   if(kind==="all-day")Object.assign(entry,{zeit:"",endZeit:"",endDatum:"2026-12-03"});
   if(kind==="dst-duration")entry.endZeit="14:00";
   if(kind==="utc")Object.assign(entry,{icsRoundtrip:["BEGIN:VEVENT","DTSTART:20261201T100000Z","DTEND:20261201T110000Z","RRULE:FREQ=WEEKLY;COUNT=4","END:VEVENT"],sync:true,syncQuellen:{fixture:{remote_id:"master-only"}},providerMetadaten:{secretBinding:"must-not-copy"}});
   if(kind==="tzid")Object.assign(entry,{icsAnzeigeZeitzone:"Europe/Berlin",icsRoundtrip:["BEGIN:VEVENT","DTSTART;TZID=Europe/Berlin:20261201T100000","DTEND;TZID=Europe/Berlin:20261201T110000","RRULE:FREQ=WEEKLY;COUNT=4","END:VEVENT"]});
   if(kind==="seconds")Object.assign(entry,{icsRoundtrip:["BEGIN:VEVENT","DTSTART:20261201T100020Z","DTEND:20261201T110050Z","RRULE:FREQ=WEEKLY;COUNT=4","END:VEVENT"]});
   const b=await harness.exports.boot(web,{termine:[entry]});
   try{
    if(kind.startsWith("dst-"))b.w.App.init({daten:{termine:[entry]},neu:false,regional:{language:"en",timeZone:"Europe/Berlin"}});
    if(kind==="german"){b.w.eval(fs.readFileSync(path.join(web,"i18n/de.js"),"utf8"));b.w.MagnolieI18n.setLocale("de");}
    const before=JSON.stringify(b.t.daten()), initial=choose(b);
    if(kind==="tzid"){assert.equal(initial,"09:00");assert.ok(b.w.document.querySelector("#dialog-hinweis").textContent.includes("Time zone"));}
    if(kind.startsWith("dst-")){
     b.t.setzeDatumswert(b.w.document.querySelector("#tb-ersatz-datum"),"2027-03-28");
     b.w.document.querySelector("#tb-ersatz-zeit").value=kind==="dst-gap"?"02:30":"00:30";
    }
    if(kind==="german")assert.ok(b.w.document.querySelector("#dialog-hinweis").textContent.includes("Ersatztermin anlegen"));
    if(kind==="invalid")b.t.setzeDatumswert(b.w.document.querySelector("#tb-ersatz-datum"),"");
    if(kind==="stale")b.t.daten().termine[0].titel="Concurrent title";
    b.w.document.querySelector(kind==="cancel"?"#dialog-nein":"#dialog-ja").click();await tick();
    if(kind==="cancel"||kind==="invalid"||kind==="dst-gap"){assert.equal(JSON.stringify(b.t.daten()),before,kind);count++;continue;}
    if(kind==="stale"){assert.equal(b.t.daten().termine.length,1);assert.equal(b.t.daten().papierkorb.length,0);count++;continue;}
    const replacement=b.t.daten().termine.find(value=>value.id!=="series");assert.ok(replacement,kind);
    assert.notEqual(replacement.uid,b.t.daten().termine[0].uid);assert.equal(replacement.wiederholung.art,"none");
    assert.equal(replacement.datum,kind==="dst-duration"?"2027-03-28":"2026-12-09");assert.equal(replacement.notiz,"Preserve");assert.equal(replacement.ort,"Fixture location");
    assert.equal(replacement.sync,false);assert.equal(Object.keys(replacement.syncQuellen||{}).length,0);
    if(kind==="seconds")assert.ok(replacement.icsRoundtrip.includes("DTEND:20261209T153030Z"),"Replacement lost sub-minute source duration");
    assert.equal(replacement.providerMetadaten?.secretBinding,undefined);
    if(kind==="all-day"){assert.equal(replacement.zeit,"");assert.equal(replacement.endDatum,"2026-12-11");}
    else if(kind==="dst-duration"){assert.equal(replacement.zeit,"00:30");assert.equal(replacement.endZeit,"05:30");}
    else{assert.equal(replacement.zeit,"14:30");assert.equal(replacement.endZeit,"15:30");}
    assert.equal(b.t.termineAm("2026-12-08",true).some(value=>value.id==="series"),false);
    assert.equal(b.t.termineAm("2026-12-15",true).some(value=>value.id==="series"),true);
    assert.equal(b.t.termineAm(replacement.datum,true).filter(value=>value.id===replacement.id).length,1);
    const trash=b.t.daten().papierkorb[0];assert.ok(trash.appointment_occurrence.replacement);
    if(kind==="edited-restore"||kind==="provider-restore"){
     if(kind==="edited-restore")replacement.titel="Replacement edited";
     else replacement.syncKalenderUid="synthetic-provider";
     assert.equal(b.t.ausDemPapierkorb(trash),false);assert.equal(b.t.daten().termine.length,2);
     assert.equal(b.t.termineAm("2026-12-08",true).some(value=>value.id==="series"),false);
    }else if(kind==="reopen"){
     const reopen=await harness.exports.boot(web,plain(b.t.daten()));
     try{assert.equal(reopen.t.ausDemPapierkorb(reopen.t.daten().papierkorb[0]),true);assert.equal(reopen.t.daten().termine.length,1);}
     finally{reopen.close();}
    }else{
     assert.equal(b.t.ausDemPapierkorb(trash),true);assert.equal(b.t.daten().termine.length,1);
     assert.equal(b.t.termineAm("2026-12-08",true).some(value=>value.id==="series"),true);
    }
    count++;
   }finally{b.close();}
  }
 }
 console.log(`${count} dual-desktop replacement appointment cases PASS`);
})().catch(error=>{console.error(error);process.exitCode=1;});
