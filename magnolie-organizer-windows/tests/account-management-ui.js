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
    for(const row of rows()) {
      const buttons=row.querySelectorAll("button");
      assert.equal(buttons.length,1,"existing accounts offer only the requested removal action");
      assert.equal(buttons[0].textContent,"×");
      assert.match(buttons[0].getAttribute("aria-label"),/^Remove · /);
      assert.equal(buttons[0].title,buttons[0].getAttribute("aria-label"));
    }
    rows()[1].querySelector("button").click();await tick();
    const before=messages.length;
    w.document.querySelector("#dialog-nein").click();await tick();
    assert.ok(!messages.slice(before).some(m=>m.cmd==="internet_konto_verwalten"));
    assert.equal(w.OrganizerTest.daten().kontakte[0].id,"keep");
    rows()[0].querySelector("button").click();await tick();
    w.document.querySelector("#dialog-ja").click();await tick();
    const request=messages.filter(m=>m.cmd==="internet_konto_verwalten").at(-1);
    assert.equal(request.anbieter,"google");assert.equal(request.konto,"first@example.invalid");assert.equal(request.aktion,"remove");
    assert.ok([...rows()].every(row=>row.querySelector("button").disabled));
    w.App.internetKontoVerwaltet({ok:true});w.App.internetKontenStatus({bereit:true,google:{accounts:[]},microsoft:status.microsoft});
    assert.equal(rows().length,1);assert.match(rows()[0].textContent,/Second/);
    assert.equal(w.OrganizerTest.daten().kontakte[0].id,"keep");
    assert.ok(messages.filter(m=>m.cmd==="internet_konto_verwalten").every(m=>m.aktion==="remove"));
    console.log("ACCOUNT MANAGEMENT UI PASSED: removal-only accessible cross, explicit identity, cancellation, transient status and retained local data");
  }finally{w.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
