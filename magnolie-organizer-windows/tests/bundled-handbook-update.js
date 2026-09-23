"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {webcrypto}=require("node:crypto"),{JSDOM}=require("jsdom");
const web=path.resolve(__dirname,"../app/web");
const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
async function check(installed){
 const dom=new JSDOM(fs.readFileSync(path.join(web,"index.html"),"utf8"),{runScripts:"outside-only",url:"https://app.magnolie.invalid/index.html",pretendToBeVisual:true});
 const w=dom.window,d=w.document,messages=[];
 Object.defineProperty(w,"crypto",{value:webcrypto});w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;
 w.__MAGNOLIE_BRUECKE__="test";
 w.webkit={messageHandlers:{test:{postMessage:raw=>{const m=JSON.parse(raw);messages.push(m);if(m.cmd==="speichern")queueMicrotask(()=>w.App.gespeichert({id:m.id,ok:true}));}}}};
 w.eval(fs.readFileSync(path.join(web,"i18n.js"),"utf8"));w.MagnolieI18n.setLocale("en");
 w.eval(fs.readFileSync(path.join(web,"anwendung.js"),"utf8"));d.dispatchEvent(new w.Event("DOMContentLoaded"));
 try{
  w.App.init({daten:{},neu:false,regional:{language:"en"},handbuchInstalliert:installed,handbuchVersion:installed?"2.0.21":""});
  assert.equal(w.OrganizerTest.zeigeHandbuchHinweis(),false,"Windows must not ask to download the bundled handbook at startup.");
  assert.ok(d.querySelector("#dialog-schleier").classList.contains("verborgen"));
  d.querySelector("#knopf-einstellungen").click();d.querySelector("#einst-tab-ueber").click();
  const url="https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Organizer-Windows-99.0.0-Setup-x64.exe";
  w.App.updateErgebnis({ok:true,aktuell:false,windows:true,version:"99.0.0",url,sha256:"a".repeat(64),
    handbuch:{version:"99.0.0",url,sha256:"a".repeat(64),platform:"windows"}});
  assert.equal(d.querySelectorAll("#update-herunterladen").length,1);
  assert.equal(d.querySelector("#handbuch-herunterladen"),null,"Same installer offered twice.");
  assert.ok(d.querySelector("#handbuch-stand").textContent.includes("The Windows installer includes the manual."));
  assert.equal(d.querySelector("#handbuch-oeffnen").disabled,!installed);
  if(installed){d.querySelector("#handbuch-oeffnen").click();assert.ok(messages.some(m=>m.cmd==="handbuch_oeffnen"));}
  d.querySelector("#update-herunterladen").click();d.querySelector("#dialog-ja").click();
  for(let i=0;i<100&&!messages.some(m=>m.cmd==="update_herunterladen");i++)await tick();
  assert.equal(messages.filter(m=>m.cmd==="update_herunterladen").length,1);
  assert.equal(messages.filter(m=>m.cmd==="handbuch_herunterladen").length,0);
  w.App.updateHeruntergeladen({ok:true,bereit:true});
  assert.equal(messages.filter(m=>m.cmd==="update_installieren").length,1);
  console.log("BUNDLED HANDBOOK UPDATE PASSED: installed="+installed);
 }finally{w.close();}
}
(async()=>{await check(true);await check(false);})().catch(error=>{console.error(error);process.exitCode=1;});
