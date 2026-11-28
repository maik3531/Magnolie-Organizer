"use strict";
const fs=require("node:fs"),path=require("node:path");
function probe(source){
 const results=[];
 const check=(name,fn)=>{try{results.push({name,pass:!!fn()});}catch(e){results.push({name,pass:false,error:String(e)});}};
 class N{
 constructor(tag=""){this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.events={};this.style={};this.classList={add(){}};this.value="";this.textContent="";this.parent=null;}
 get isConnected(){return this.tag==="body"||!!this.parent?.isConnected;}
 append(...items){for(const n of items){n.parent=this;this.children.push(n);}}
 prepend(n){n.parent=this;this.children.unshift(n);}
 remove(){if(this.parent){this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}}
 replaceChildren(...items){for(const n of this.children)n.parent=null;this.children=[];this.append(...items);}
 setAttribute(k,v){this.attrs[k]=v;}
 toggleAttribute(k,v){if(v)this.attrs[k]="";else delete this.attrs[k];}
 addEventListener(k,f){this.events[k]=f;}
 querySelectorAll(s){const match=n=>s==="[data-appearance-test]"?n.dataset.appearanceTest!==undefined:s===":scope > [data-appearance-watermark]"?n.dataset.appearanceWatermark!==undefined:s==="#magnolie-test-hinweis"?n.id==="magnolie-test-hinweis":s==="#schreibtisch"?n.id==="schreibtisch":s==="#magnolie-saison"?n.id==="magnolie-saison":s===".wo-tag[data-appearance-date]"?n.dataset.appearanceDate!==undefined:false;const all=n=>n.children.flatMap(c=>[c,...all(c)]);return (s.startsWith(":scope")?this.children:all(this)).filter(match);}
 querySelector(s){return this.querySelectorAll(s)[0]??null;}
 }
 const body=new N("body"),doc={body,createElement:t=>new N(t),createElementNS:(ns,t)=>new N(t),createTextNode:t=>Object.assign(new N("#text"),{textContent:t}),querySelector:s=>body.querySelector(s),querySelectorAll:s=>body.querySelectorAll(s)};
 const window={};
 new Function("document","window",source)(doc,window);
 window.MagnolieAppearance.update({today:"2026-08-01",country:"CH",developer:true,locked:false});
 window.MagnolieAppearance.mountDeveloper(body,x=>x);
 check("default panel remains disabled",()=>body.children.length===0);
 new Function("document","window",source.replace("const SHOW_DEVELOPER_PREVIEW = false;","const SHOW_DEVELOPER_PREVIEW = true;"))(doc,window);
 const a=window.MagnolieAppearance,calls=[],tr=x=>"T:"+x;
 a.update({today:"2026-08-01",country:"CH",developer:false,locked:false});a.mountDeveloper(body,tr, x=>calls.push(x));
 check("nondeveloper blocked",()=>body.children.length===0);
 a.update({today:"2026-08-01",country:"CH",developer:true,locked:true});a.mountDeveloper(body,tr,x=>calls.push(x));
 check("locked blocked",()=>body.children.length===0);
 a.update({today:"2026-08-01",country:"CH",developer:true,locked:false});a.mountDeveloper(body,tr,x=>calls.push(x));
 const section=body.children.find(n=>n.id==="entwickler-darstellung");
 const all=n=>n.children.flatMap(c=>[c,...all(c)]);
 const select=all(section).find(n=>n.dataset.appearanceTest==="holiday");
 const sample=all(section).find(n=>n.dataset.appearanceSample==="watermark");
 const reset=all(section).find(n=>n.textContent==="T:Reset preview");
 const choose=value=>{select.value=value;select.events.change();};
 const motif=()=>sample.children[0]?.dataset.appearanceWatermark;
 check("automatic country motif",()=>motif()==="swiss-lantern");
 for(const [kind,label] of [["unity-gate","Germany"],["neutrality-parliament","Austria"],["swiss-lantern","Switzerland"],["french-rosette","France"],["kings-crown","Netherlands"],["italian-ballot","Italy"],["polish-banner","Poland"],["liechtenstein-lights","Liechtenstein"]]){
 check("option "+kind,()=>select.children.some(n=>n.value===kind&&n.textContent==="T:"+label));
 check("explicit "+kind,()=>{choose("none");choose(kind);return motif()===kind&&sample.children[0].attrs["aria-hidden"]==="true"&&sample.children[0].attrs.focusable==="false";});
 }
 check("all previous options retained",()=>["auto","none","boots","santa","rocket","glass","eggs"].every(x=>select.children.some(n=>n.value===x)));
 check("invalid choice cannot change preview",()=>{choose("boots");choose("invalid");return motif()==="boots";});
 check("reset to automatic",()=>{reset.events.click();return motif()==="swiss-lantern"&&select.value==="auto";});
 check("country change automatic",()=>{a.update({today:"2026-07-14",country:"FR",developer:true,locked:false});return motif()==="french-rosette";});
 check("none clears image",()=>{choose("none");return !motif();});
 check("legacy override works",()=>{choose("eggs");return motif()==="eggs";});
 check("ordinary changes no native calls",()=>calls.length===0);
 check("lock resets and stale event has no effect",()=>{a.update({today:"2026-07-14",country:"FR",developer:true,locked:true});choose("rocket");section.remove();a.update({today:"2026-07-14",country:"FR",developer:true,locked:false});a.mountDeveloper(body,tr,x=>calls.push(x));const fresh=all(body).find(n=>n.dataset.appearanceSample==="watermark");return fresh.children[0]?.dataset.appearanceWatermark==="french-rosette"&&calls.length===0;});

 for(const [iso,country,want] of [
 ["1948-06-02","IT","italian-ballot"],["1949-06-02","IT","italian-ballot"],["1976-06-02","IT","italian-ballot"],
 ["1977-06-02","IT","none"],["1977-06-05","IT","italian-ballot"],["1977-06-06","IT","none"],
 ["1985-06-02","IT","italian-ballot"],["1986-06-01","IT","none"],["1986-06-02","IT","italian-ballot"],["1947-06-02","IT","italian-ballot"],["2000-06-04","IT","italian-ballot"],["2000-06-02","IT","none"],
 ["2001-06-02","IT","italian-ballot"],["2001-06-03","IT","none"],["2026-06-02","IT","italian-ballot"],
 ["2026-06-01","IT","none"],["2026-06-03","IT","none"],["2024-06-02","IT","italian-ballot"],
 ["1936-11-11","PL","none"],["1937-11-11","PL","polish-banner"],["1938-11-11","PL","polish-banner"],
 ["1939-11-11","PL","none"],["1945-11-11","PL","none"],["1988-11-11","PL","none"],
 ["1989-11-11","PL","polish-banner"],["2026-11-11","PL","polish-banner"],
 ["2026-11-10","PL","none"],["2026-11-12","PL","none"],["2026-06-02","PL","none"],["2026-11-11","IT","none"],
 ["2026-06-02","","none"],["2026-11-11","XX","none"],["2026-02-30","IT","none"],
 ["2026-10-03","DE","unity-gate"],["2025-04-26","NL","kings-crown"],["2026-04-05","IT","eggs"],
 ["2026-12-31","PL","rocket"]]){
 check(iso+" "+country+" "+want,()=>a.holiday(iso,country)===want);
 }
 for(const [kind,parts] of [["italian-ballot",["ballot-box","ballot-paper","festive-rays"]],["polish-banner",["flag","horizontal-bands","flagpole","festive-rays"]]]){
 check("SVG attributes "+kind,()=>{const s=a.stamp(kind);return s?.attrs.viewBox==="0 0 80 80"&&s.attrs["aria-hidden"]==="true"&&s.attrs.focusable==="false"&&parts.every(p=>s.children.some(n=>n.attrs["data-motif-part"]===p))&&s.children.every(n=>n.tag==="path"&&n.attrs.stroke==="currentColor"&&n.attrs["stroke-width"]==="2"&&n.attrs["stroke-linecap"]==="round"&&n.attrs.d.length>0);});
 }
 const cell=new N("div");body.append(cell);
 a.update({today:"2026-06-02",country:"IT",developer:false,locked:false});a.day(cell,"2026-06-02");
 check("calendar Italian motif",()=>cell.children[0]?.dataset.appearanceWatermark==="italian-ballot");
 a.day(cell,"2026-06-02");
 check("calendar no duplicate",()=>cell.children.length===1&&cell.children[0]?.dataset.appearanceWatermark==="italian-ballot");
 a.update({today:"2026-06-02",country:"PL",developer:false,locked:false});
 check("calendar country refresh removes Italian",()=>cell.children.length===0);
 a.day(cell,"2026-11-11");
 check("calendar Polish motif",()=>cell.children[0]?.dataset.appearanceWatermark==="polish-banner");
 a.update({today:"2026-11-11",country:"PL",developer:false,locked:true});
 check("calendar locked clears motif",()=>cell.children.length===0);

 for(const [iso,country,want] of [
 ["1939-08-15","LI","none"],["1940-08-15","LI","liechtenstein-lights"],["1989-08-15","LI","liechtenstein-lights"],["1990-08-15","LI","liechtenstein-lights"],["2026-08-15","LI","liechtenstein-lights"],["2027-08-15","LI","liechtenstein-lights"],["2026-08-14","LI","none"],["2026-08-16","LI","none"],["2026-01-23","LI","none"],["2026-08-15","DE","none"],["2026-08-15","CH","none"],["2026-08-15","AT","none"],["2026-08-15","","none"],["2026-08-15","XX","none"],["2026-08-32","LI","none"],["2026-12-24","LI","santa"],["2026-07-21","BE","belgian-banner"],["2026-06-23","LU","luxembourg-concert"]]) check(iso+" "+country+" "+want,()=>a.holiday(iso,country)===want);
 check("LI SVG attributes",()=>{const s=a.stamp("liechtenstein-lights");return s?.attrs.viewBox==="0 0 80 80"&&s.attrs["aria-hidden"]==="true"&&s.attrs.focusable==="false"&&["mountain-ridge","illuminated-crown","mountain-fires","festive-rays"].every(p=>s.children.some(n=>n.attrs["data-motif-part"]===p))&&s.children.every(n=>n.tag==="path"&&n.attrs.stroke==="currentColor"&&n.attrs["stroke-width"]==="2"&&n.attrs["stroke-linecap"]==="round"&&n.attrs.d.length>0);});
 const liCell=new N("div");body.append(liCell);
 a.update({today:"2026-08-15",country:"LI",developer:false,locked:false});a.day(liCell,"2026-08-15");
 check("LI calendar cell",()=>liCell.children[0]?.dataset.appearanceWatermark==="liechtenstein-lights");
 a.day(liCell,"2026-08-15");check("LI cell idempotent",()=>liCell.children.length===1);
 a.update({today:"2026-08-15",country:"CH",developer:false,locked:false});check("LI country switch clears",()=>liCell.children.length===0);
 a.update({today:"2026-08-15",country:"LI",developer:false,locked:false});a.day(liCell,"2026-08-15");a.day(liCell,"2026-08-16");check("LI date switch clears",()=>liCell.children.length===0);
 a.day(liCell,"2026-08-15");a.update({today:"2026-08-15",country:"LI",developer:false,locked:true});check("LI locked clears",()=>liCell.children.length===0);


 for(const [iso,country,want] of [
 ["1992-10-28","CZ","none"],["1993-10-28","CZ","czech-proclamation"],["2000-10-28","CZ","czech-proclamation"],
 ["2026-10-27","CZ","none"],["2026-10-28","CZ","czech-proclamation"],["2026-10-29","CZ","none"],
 ["2027-10-28","CZ","czech-proclamation"],["2026-10-28","SK","none"],["2026-10-28","ES","none"],
 ["2026-10-28","","none"],["2026-10-28","XX","none"],["2026-10-32","CZ","none"],
 ["1981-10-12","ES","none"],["1982-10-12","ES","spanish-ribbon"],["1986-10-12","ES","spanish-ribbon"],
 ["1987-10-12","ES","spanish-ribbon"],["2025-10-12","ES","spanish-ribbon"],["2025-10-13","ES","none"],
 ["2026-10-11","ES","none"],["2026-10-12","ES","spanish-ribbon"],["2026-10-13","ES","none"],
 ["2026-10-12","CZ","none"],["2026-10-12","","none"],["2026-10-12","MX","none"],["2026-10-00","ES","none"],
 ["2026-12-24","CZ","santa"],["2026-12-31","ES","rocket"],["2026-04-05","ES","eggs"]])
 check(iso+" "+country+" "+want,()=>a.holiday(iso,country)===want);
 for(const [kind,label,parts,country,date] of [
 ["czech-proclamation","Czech Republic",["proclamation","document-lines","flag","flag-wedge","festive-rays"],"CZ","2026-10-28"],
 ["spanish-ribbon","Spain",["banner","horizontal-bands","ribbon","festive-rays"],"ES","2026-10-12"]]) {
  check("SVG attributes "+kind,()=>{const s=a.stamp(kind);return s?.attrs.viewBox==="0 0 80 80"&&s.attrs["aria-hidden"]==="true"&&s.attrs.focusable==="false"&&parts.every(p=>s.children.some(n=>n.attrs["data-motif-part"]===p))&&s.children.every(n=>n.tag==="path"&&n.attrs.stroke==="currentColor"&&n.attrs["stroke-width"]==="2"&&n.attrs["stroke-linecap"]==="round"&&n.attrs.d.length>0);});
  for(const old of body.children.filter(n=>n.id==="entwickler-darstellung"))old.remove();
  a.update({today:date,country,developer:true,locked:false});a.mountDeveloper(body,tr,x=>calls.push(x));
  const section=body.children.find(n=>n.id==="entwickler-darstellung");
  const s=all(section).find(n=>n.dataset.appearanceTest==="holiday"), sm=all(section).find(n=>n.dataset.appearanceSample==="watermark");
  check("preview choice "+kind,()=>s.children.some(n=>n.value===kind&&n.textContent==="T:"+label));
  check("automatic preview "+kind,()=>sm.children[0]?.dataset.appearanceWatermark===kind);
  s.value="none";s.events.change();s.value=kind;s.events.change();
  check("explicit preview "+kind,()=>sm.children[0]?.dataset.appearanceWatermark===kind);
  a.update({today:date,country,developer:false,locked:false});const c=new N("div");body.append(c);
  a.day(c,date);check("calendar "+kind,()=>c.children[0]?.dataset.appearanceWatermark===kind);
  a.day(c,date);check("idempotence "+kind,()=>c.children.length===1);
  a.update({today:date,country:"DE",developer:false,locked:false});check("country change clears "+kind,()=>c.children.length===0);
  a.update({today:date,country,developer:false,locked:false});a.day(c,date);a.day(c,date.slice(0,-2)+"01");check("date change clears "+kind,()=>c.children.length===0);
  a.day(c,date);a.update({today:date,country,developer:false,locked:true});check("lock clears "+kind,()=>c.children.length===0);
 }
 check("no native calls during additional previews",()=>calls.length===0);
 check("CZ and ES winter rules unchanged",()=>a.season("2026-12-10","CZ")==="crystals"&&a.season("2026-12-10","ES")==="none");


 for (const [country,kind,label,min,parts] of [
 ["ES","three-kings","Spain",1984,["first-crown","middle-crown","third-crown","star","gifts"]],
 ["IT","befana-stocking","Italy",1986,["stocking","broom-handle","broom-bristles","sweets-and-star"]]]) {
   const want=kind;
   for(const y of [min,2024,2025,2026,2027,2028]) check(country+" Jan6 "+y,()=>a.holiday(y+"-01-06",country)===want);
   for(const d of [(min-1)+"-01-06","2026-01-05","2026-01-07","2026-06-01","2026-01-32"]) check(country+" negative "+d,()=>a.holiday(d,country)!==want);
   check(country+" SVG",()=>{const s=a.stamp(kind);return s?.attrs.viewBox==="0 0 80 80"&&s.attrs["aria-hidden"]==="true"&&s.attrs.focusable==="false"&&parts.every(p=>s.children.some(n=>n.attrs["data-motif-part"]===p))&&s.children.every(n=>n.tag==="path"&&n.attrs.stroke==="currentColor"&&n.attrs["stroke-width"]==="2"&&n.attrs.d.length>0);});
   for(const old of body.children.filter(n=>n.id==="entwickler-darstellung"))old.remove();
   a.update({today:"2026-01-06",country,developer:true,locked:false});a.mountDeveloper(body,tr,x=>calls.push(x));
   const p=all(body).find(n=>n.id==="entwickler-darstellung");
   const sel=all(p).find(n=>n.dataset.appearanceTest==="holiday"), sm=all(p).find(n=>n.dataset.appearanceSample==="watermark");
   check(country+" localized country preview label",()=>sel.children.some(n=>n.value===kind&&n.textContent==="T:"+label+" · 01-06"));
   check(country+" automatic preview",()=>sm.children[0]?.dataset.appearanceWatermark===kind);
   sel.value="none";sel.events.change();sel.value=kind;sel.events.change();
   check(country+" manual preview",()=>sm.children[0]?.dataset.appearanceWatermark===kind);
   a.update({today:"2026-01-06",country,developer:false,locked:false});const c=new N("div");body.append(c);
   a.day(c,"2026-01-06");check(country+" calendar",()=>c.children[0]?.dataset.appearanceWatermark===kind);
   a.day(c,"2026-01-06");check(country+" idempotence",()=>c.children.length===1);
   a.update({today:"2026-01-06",country:country==="ES"?"IT":"ES",developer:false,locked:false});
   check(country+" other region motif",()=>c.children[0]?.dataset.appearanceWatermark===(country==="ES"?"befana-stocking":"three-kings"));
   a.day(c,"2026-01-07");check(country+" day changed",()=>c.children.length===0);
   a.update({today:"2026-01-06",country,developer:false,locked:false});a.day(c,"2026-01-06");
   a.update({today:"2026-01-06",country,developer:false,locked:true});check(country+" lock clears",()=>c.children.length===0);
 }
 for(const c of ["DE","AT","CH","LI","LU","BE","NL","FR","PL","CZ","MX","","XX","es","it"]) check("no unverified January identity "+c,()=>a.holiday("2026-01-06",c)==="none");
 check("no native calls during cultural preview",()=>calls.length===0);

 return results;
}
const root=process.argv[2]||".";
let failed=0;
for(const name of ["magnolie-organizer/web/appearance.js","magnolie-organizer-windows/app/web/appearance.js"]){const result=probe(fs.readFileSync(path.join(root,name),"utf8"));console.log(name,JSON.stringify(result));failed+=result.filter(x=>!x.pass).length;}
process.exitCode=failed?1:0;
