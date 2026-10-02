"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {webcrypto}=require("node:crypto"),{JSDOM}=require("jsdom");
const web=path.resolve(__dirname,"../app/web"),tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function check(mode){
  const duplicate=mode.startsWith("duplicate"), mergedDuplicate=["duplicate","duplicate-tree"].includes(mode), blocked=duplicate&&!mergedDuplicate;
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
      if(mode==="duplicate-stale")w.OrganizerTest.daten().kontakte[1].notiz="Changed meanwhile";
      w.App.mutationsSnapshot({token:m.token,ok:!mode.endsWith("snapshot-error")});
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
    if(duplicate){
      const local=T.daten().kontakte[0];local.uid="mag-local@magnolie-organizer";delete local.syncKonflikte;
      local.syncQuellen[source].id="redundant";
      local.foto="data:image/png;base64,AQID";
      T.daten().kontakte.push({...JSON.parse(JSON.stringify(remote)),id:"duplicate",foto:"data:image/png;base64,BAUG",sync:true,syncQuellen:{[source]:mapping}});
      T.daten().aufgaben.push({id:"linked",titel:"Link",kontaktId:"duplicate"});
      const other=T.daten().kontakte[1];
      if(mode==="duplicate-conflict")other.syncKonflikte={[source]:{kontakt:remote,mapping}};
      if(mode==="duplicate-local-conflict")local.syncKonflikte={[source]:{kontakt:remote,mapping}};
      if(mode==="duplicate-etag")delete other.syncQuellen[source].etag;
      if(mode==="duplicate-tree"){
        local.baumKontakt={freigabeId:"one",version:3,partner:["first"]};other.baumKontakt={freigabeId:"two",version:7,partner:["second"]};
      }
    }
    const before=JSON.stringify(T.daten().kontakte);
    T.oeffneSyncKontaktKonflikt("local",source,duplicate?"duplicate":"");
    assert.ok(w.document.querySelector(".sync-kontakt-konflikt"));
    assert.equal(T.daten().kontakte.length,duplicate?2:1);
    if(mode==="cancel"||mode==="duplicate-cancel"){
      [...w.document.querySelectorAll(".sync-kontakt-konflikt button")].find(b=>b.textContent==="Cancel").click();
    }else{
      if(mode==="merge"||mergedDuplicate){
        const name=w.document.querySelector('[data-kontakt-feld="vorname"]');name.value="incoming";name.dispatchEvent(new w.Event("change"));
        const phone=w.document.querySelector('[data-kontakt-liste="telefone"][data-kontakt-index="0"]');
        phone.value="replace:0";phone.dispatchEvent(new w.Event("change"));
        if(mergedDuplicate){
          const photo=w.document.querySelector('[data-kontakt-feld="foto"]');
          assert.ok(photo,"different photos must be a visible decision");photo.value="incoming";photo.dispatchEvent(new w.Event("change"));
        }
      }
      w.document.querySelector('[data-sync-kontakt-entscheidung="'+(mode==="keep"?"keep":"merge")+'"]').click();
    }
    await tick();await tick();
    if(blocked){
      assert.equal(T.daten().kontakte.length,2);
      assert.equal(T.daten().geloescht.kontakte.length,0);
      assert.equal(T.daten().papierkorb.length,0);
      assert.equal(T.daten().aufgaben[0].kontaktId,"duplicate");
      if(mode!=="duplicate-stale")assert.equal(JSON.stringify(T.daten().kontakte),before);
      return;
    }
    const card=T.daten().kontakte[0];
    assert.equal(T.daten().kontakte.length,1);assert.equal(card.id,"local");assert.equal(card.uid,mergedDuplicate?"mag-local@magnolie-organizer":"stable-local");
    if(["cancel","snapshot-error","stale"].includes(mode)){
      assert.equal(card.vorname,"Local");assert.ok(card.syncKonflikte[source]);assert.equal(card.syncQuellen[source].etag,'"v1"');
      assert.equal(messages.filter(m=>m.cmd==="mutations_snapshot").length,mode==="cancel"?0:1);
    }else{
      assert.equal(card.vorname,mode==="keep"?"Local":"Remote");
      assert.equal(card.telefone[0].wert,mode==="keep"?"+49305550123":"+49305550124");
      assert.equal(card.syncQuellen[source].etag,'"v2"');assert.equal(card.syncKonflikte,undefined);
      assert.equal(messages.filter(m=>m.cmd==="mutations_snapshot").length,1);
      if(mergedDuplicate){
        if(mode==="duplicate-tree"){
          assert.equal(card.baumKontakt.freigabeId,"one");
          assert.equal(card.baumKontakt.weitere[0].freigabeId,"two");
          assert.equal(card.baumKontakt.weitere[0].version,7);
        }
        assert.equal(card.syncQuellen[source].id,"provider-record");
        assert.equal(T.daten().geloescht.kontakte[0].syncQuellen[source].id,"redundant");
        assert.notEqual(T.daten().geloescht.kontakte[0].uid,card.uid);
        assert.equal(T.daten().aufgaben[0].kontaktId,"local");
        assert.equal(T.daten().papierkorb[0].eintrag.uid,"provider");
        assert.equal(card.foto,"data:image/png;base64,BAUG","the chosen photo must be retained explicitly");
        const archive=T.daten().papierkorb[0];
        T.mergeKontakte([{...remote,id:"reimport",geaendert:Date.now()}]);
        assert.equal(T.daten().kontakte.length,1,"retired provider identity must resolve to the survivor");
        assert.equal(T.ausDemPapierkorb(archive),true);
        const restored=T.daten().kontakte[1];
        assert.notEqual(restored.id,"duplicate");assert.notEqual(restored.uid,"provider");
        assert.equal(restored.foto,"data:image/png;base64,BAUG");
        assert.equal(restored.sync,false);assert.equal(restored.syncQuellen,undefined);
        assert.equal(T.daten().kontakte[0].syncQuellen[source].id,"provider-record");
        assert.equal(T.daten().geloescht.kontakte[0].syncQuellen[source].id,"redundant");
      }
    }
  }finally{w.close();}
}
(async()=>{for(const mode of ["merge","keep","duplicate","duplicate-cancel","duplicate-snapshot-error","duplicate-stale","duplicate-tree","duplicate-etag","duplicate-conflict","duplicate-local-conflict","cancel","snapshot-error","stale"])await check(mode);
  console.log("CONTACT SYNC CONFLICTS PASSED: one person, field decisions, stable identity, cancellation and failure guards");
})().catch(error=>{console.error(error);process.exitCode=1;});
