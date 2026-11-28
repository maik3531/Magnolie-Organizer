"use strict";
const fs = require("node:fs"), path = require("node:path");
function probe(appearanceSource,appSources){
 class Node{
   constructor(name){this.name=name;this.children=[];this.dataset={};this.style={};this.attrs={};this.parent=null;}
   append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
   prepend(n){n.parent=this;this.children.unshift(n);}
   remove(){if(this.parent){this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}}
   setAttribute(k,v){this.attrs[k]=String(v);}
   toggleAttribute(k,v){if(v)this.attrs[k]="";else delete this.attrs[k];}
   querySelector(q){return q==="#magnolie-saison"?this.children.find(n=>n.id==="magnolie-saison")||null:null;}
 }
 const desktop=new Node("main"),body=new Node("body"),draft=new Node("textarea");draft.value="unsaved";desktop.append(draft);
 const doc={body,querySelector:q=>q==="#schreibtisch"?desktop:null,querySelectorAll:()=>[],createElement:n=>new Node(n),createElementNS:(ns,n)=>new Node(n)};
 const w={};new Function("window","document",appearanceSource)(w,doc);
 const a=w.MagnolieAppearance, checks=[];
 const check=(label,actual,expected)=>checks.push({label,actual,expected,pass:actual===expected});
 for(const c of ["DE","AT","CH","LI","LU","BE","NL","PL","CZ"])check("winter "+c,a.season("2026-12-10",c),"crystals");
 for(const c of ["","ES","FR","IT","AU","CN","ZA","ZZ",null])check("no snow "+String(c),a.season("2026-12-10",c),"none");
 for(const [date,want] of [["2026-12-05","none"],["2026-12-06","crystals"],["2026-12-29","crystals"],["2026-12-30","stars"],["2026-12-31","stars"],["2027-01-01","stars"],["2027-01-02","none"],["2026-02-30","none"]])check("boundary "+date,a.season(date,"DE"),want);
 check("neutral stars ES",a.season("2026-12-30","ES"),"stars");
 const state=()=>desktop.querySelector("#magnolie-saison")?.dataset.season||"none";
 const update=(country,locked=false)=>a.update({today:"2026-12-10",country,developer:false,locked});
 update("DE");check("initial DE",state(),"crystals");const layer=desktop.querySelector("#magnolie-saison");
 check("unchanged 34 motifs",layer?.children.length,34);
 update("DE");check("no unnecessary redraw",desktop.querySelector("#magnolie-saison")===layer,true);
 update("ES");check("switch DE to ES",state(),"none");
 update("DE");check("switch ES to DE",state(),"crystals");
 update("DE",true);check("locked",state(),"none");
 update("");check("new unspecified book",state(),"none");
 check("unsaved editor retained",draft.value,"unsaved");
 for(const [platform,source] of appSources){
   const marker='    landWahl.addEventListener("change", () => {';
   const start=source.indexOf(marker),end=source.indexOf("\n    });",start);
   if(start<0||end<0)throw Error("missing event "+platform);
   const event=source.slice(start,end+8);
   const DATEN={einstellungen:{ort:{land:"DE"},allgemein:{entwicklermodus:false}}};
   let callback, saved=0, region=0, flag=0;
   const landWahl={value:"ES",addEventListener:(name,fn)=>{callback=fn;}};
   new Function("landWahl","landFlagge","aktualisiereLandFlagge","wendeOrtAuswahlDatenAn","planeSpeichern","regionenZeigen","window","isoHeute","DATEN","gesperrt",event)(landWahl,null,()=>flag++,x=>Object.assign(DATEN.einstellungen.ort,x),()=>saved++,()=>region++,w,()=>"2026-12-10",DATEN,false);
   update("DE");callback();check(platform+" country event redraw",state(),"none");
   check(platform+" event original actions",saved+":"+region+":"+flag+":"+DATEN.einstellungen.ort.land,"1:1:1:ES");
   landWahl.value="DE";callback();check(platform+" country event restores",state(),"crystals");
 }
 return checks;
}
const root=process.argv[2]||".";
const read=p=>fs.readFileSync(path.join(root,p),"utf8");
const appearance=read("magnolie-organizer/web/appearance.js");
if(appearance!==read("magnolie-organizer-windows/app/web/appearance.js"))throw Error("appearance parity");
const checks=probe(appearance,[["Linux",read("magnolie-organizer/web/anwendung.js")],["Windows",read("magnolie-organizer-windows/app/web/anwendung.js")]]);
console.log(JSON.stringify(checks,null,2));
console.log(checks.filter(x=>x.pass).length+"/"+checks.length);
if(checks.some(x=>!x.pass))process.exitCode=1;
