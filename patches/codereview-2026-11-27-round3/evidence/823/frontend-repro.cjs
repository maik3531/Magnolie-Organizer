"use strict";
const fs=require("node:fs"), path=require("node:path"), {webcrypto}=require("node:crypto");
const {JSDOM}=require("jsdom");
const root=path.resolve(process.argv[2]), output=path.resolve(process.argv[3]);
fs.mkdirSync(output,{recursive:true});
const tzRoot=path.join(root,"port-adapters/timezones");
const tz=require(path.join(tzRoot,"projection-assets.cjs"))(name=>fs.readFileSync(path.join(tzRoot,name)))["normative-timezones.js"].toString("utf8");
for(const edition of ["magnolie-organizer", "magnolie-organizer-windows"]){
 const web=path.join(root,edition,edition.endsWith("windows") ? "app/web" : "web");
 const dom=new JSDOM(fs.readFileSync(path.join(web,"index.html"),"utf8"),{url:"https://app.magnolie.invalid/",runScripts:"outside-only",pretendToBeVisual:true});
 const w=dom.window;
 Object.defineProperty(w,"crypto",{value:webcrypto});w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;
 w.__MAGNOLIE_BRUECKE__="test";w.webkit={messageHandlers:{test:{postMessage(){}}}};
 try{
  w.eval(fs.readFileSync(path.join(web,"i18n.js"),"utf8"));w.eval(tz);w.eval(fs.readFileSync(path.join(web,"anwendung.js"),"utf8"));
  w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T=w.OrganizerTest;
  w.App.init({neu:false,daten:{kontakte:[{id:"contact-local",uid:"",vorname:"Alex",nachname:"Person",email:"same@example.test",notiz:"Snapshot detail"}]}});
  const before=JSON.parse(JSON.stringify(T.daten()));
  T.mergeKontakte([{uid:"import-uid",vorname:"Alex",nachname:"Person",email:"same@example.test",firma:"Imported company"}]);
  const after=JSON.parse(JSON.stringify(T.daten()));
  fs.writeFileSync(path.join(output,`round3-storage-${edition}.json`),JSON.stringify({before,after}));
  console.log(JSON.stringify({edition,before:before.kontakte.map(x=>({id:x.id,uid:x.uid})),after:after.kontakte.map(x=>({id:x.id,uid:x.uid}))}));
 } finally {w.close();}
}
