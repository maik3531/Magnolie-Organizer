"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {webcrypto}=require("node:crypto"),{JSDOM}=require("jsdom");
const web=path.resolve(__dirname,"../app/web"),tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function check(mode){
  const dom=new JSDOM(fs.readFileSync(path.join(web,"index.html"),"utf8"),{
    runScripts:"outside-only",url:"https://app.magnolie.invalid/",pretendToBeVisual:true});
  const w=dom.window,messages=[];
  Object.defineProperty(w,"crypto",{value:webcrypto});w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;
  w.__MAGNOLIE_BRUECKE__="test";
  w.webkit={messageHandlers:{test:{postMessage(text){
    const m=JSON.parse(text);messages.push(m);
    if(m.cmd==="speichern")queueMicrotask(()=>w.App.gespeichert({id:m.id,ok:true}));
    if(m.cmd==="mutations_snapshot")queueMicrotask(()=>{
      if(mode==="stale")w.OrganizerTest.daten().kontakte[0].notiz="Changed meanwhile";
      w.App.mutationsSnapshot({token:m.token,ok:mode!=="snapshot-error"});
    });
  }}}};
  try{
    w.eval(fs.readFileSync(path.join(web,"i18n.js"),"utf8"));w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web,"anwendung.js"),"utf8"));w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const source="thunderbird-addressbook:managed:fixture:book";
    const remote={id:"remote",uid:"provider",vorname:"Remote",nachname:"Person",
      telefone:[{wert:"+49305550124",typen:["CELL"]}]};
    const mapping={id:"provider-record",etag:'"v2"',inhaltFormat:"windows-contact-2",inhaltSha256:"a".repeat(64)};
    w.App.init({neu:false,daten:{kontakte:[{id:"local",uid:"stable-local",vorname:"Local",nachname:"Person",
      telefone:[{wert:"+49305550123",typen:["CELL"]}],sync:true,
      syncQuellen:{[source]:{...mapping,etag:'"v1"'}},syncKonflikte:{[source]:{kontakt:remote,mapping}}}]}});
    await tick();messages.length=0;
    const T=w.OrganizerTest;
    T.oeffneSyncKontaktKonflikt("local",source);
    assert.ok(w.document.querySelector(".sync-kontakt-konflikt"));
    assert.equal(T.daten().kontakte.length,1);
    if(mode==="cancel"){
      [...w.document.querySelectorAll(".sync-kontakt-konflikt button")].find(b=>b.textContent==="Cancel").click();
    }else{
      if(mode==="merge"){
        const name=w.document.querySelector('[data-kontakt-feld="vorname"]');name.value="incoming";name.dispatchEvent(new w.Event("change"));
        const phone=w.document.querySelector('[data-kontakt-liste="telefone"][data-kontakt-index="0"]');
        phone.value="replace:0";phone.dispatchEvent(new w.Event("change"));
      }
      w.document.querySelector('[data-sync-kontakt-entscheidung="'+(mode==="keep"?"keep":"merge")+'"]').click();
    }
    await tick();await tick();
    const card=T.daten().kontakte[0];
    assert.equal(T.daten().kontakte.length,1);assert.equal(card.id,"local");assert.equal(card.uid,"stable-local");
    if(["cancel","snapshot-error","stale"].includes(mode)){
      assert.equal(card.vorname,"Local");assert.ok(card.syncKonflikte[source]);assert.equal(card.syncQuellen[source].etag,'"v1"');
      assert.equal(messages.filter(m=>m.cmd==="mutations_snapshot").length,mode==="cancel"?0:1);
    }else{
      assert.equal(card.vorname,mode==="merge"?"Remote":"Local");
      assert.equal(card.telefone[0].wert,mode==="merge"?"+49305550124":"+49305550123");
      assert.equal(card.syncQuellen[source].etag,'"v2"');assert.equal(card.syncKonflikte,undefined);
      assert.equal(messages.filter(m=>m.cmd==="mutations_snapshot").length,1);
    }
  }finally{w.close();}
}
(async()=>{for(const mode of ["merge","keep","cancel","snapshot-error","stale"])await check(mode);
  console.log("CONTACT SYNC CONFLICTS PASSED: one person, field decisions, stable identity, cancellation and failure guards");
})().catch(error=>{console.error(error);process.exitCode=1;});
