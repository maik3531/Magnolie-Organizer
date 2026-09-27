"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {webcrypto}=require("node:crypto"),{JSDOM}=require("jsdom");
const web=path.resolve(__dirname,"../app/web"),tick=()=>new Promise(resolve=>setTimeout(resolve,10));
(async()=>{
  const dom=new JSDOM(fs.readFileSync(path.join(web,"index.html"),"utf8"),{
    runScripts:"outside-only",url:"https://app.magnolie.invalid/",pretendToBeVisual:true});
  const w=dom.window,messages=[];
  try{
    Object.defineProperty(w,"crypto",{value:webcrypto});w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;
    w.__MAGNOLIE_BRUECKE__="test";
    w.webkit={messageHandlers:{test:{postMessage(text){messages.push(JSON.parse(text));}}}};
    w.eval(fs.readFileSync(path.join(web,"i18n.js"),"utf8"));w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web,"anwendung.js"),"utf8"));w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({neu:false,daten:{kontakte:[{id:"keep",vorname:"Local person"}]}});
    w.OrganizerTest.oeffneEinstellungen();w.document.querySelector("#einst-tab-sync").click();
    const status={bereit:true,google:{accounts:["first@example.invalid"],details:[{id:"first@example.invalid",name:"First"}]},
      microsoft:{accounts:[{id:"a2",name:"Second",enabled:true}]}};
    w.App.internetKontenStatus(status);
    const rows=()=>w.document.querySelectorAll("#internet-konten-liste .knopfreihe");
    assert.equal(rows().length,2);
    w.App.internetKontenStatus({bereit:false,fehler:"Temporary failure"});
    assert.equal(rows().length,2,"a failed status query must not make existing accounts disappear");
    w.App.internetKontenStatus(status);
    [...rows()[0].querySelectorAll("button")].find(b=>b.textContent==="Edit · Name").click();await tick();
    w.document.querySelector("#eingabe-feld").value="Renamed";
    w.document.querySelector("#eingabe-schleier form").dispatchEvent(new w.Event("submit",{cancelable:true}));await tick();
    let request=messages.filter(m=>m.cmd==="internet_konto_verwalten").at(-1);
    assert.equal(request.konto,"first@example.invalid");assert.equal(request.aktion,"rename");assert.equal(request.name,"Renamed");
    w.App.internetKontoVerwaltet({ok:true});w.App.internetKontenStatus(status);
    [...rows()[1].querySelectorAll("button")].find(b=>b.textContent==="Remove").click();await tick();
    const before=messages.length;
    w.document.querySelector("#dialog-nein").click();await tick();
    assert.ok(!messages.slice(before).some(m=>m.cmd==="internet_konto_verwalten"));
    assert.equal(w.OrganizerTest.daten().kontakte[0].id,"keep");
    console.log("ACCOUNT MANAGEMENT UI PASSED: explicit identity, rename, cancelled removal, transient status failure and local data retention");
  }finally{w.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
