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
 for(const [kind,label] of [["unity-gate","Germany"],["neutrality-parliament","Austria"],["swiss-lantern","Switzerland"],["french-rosette","France"],["kings-crown","Netherlands"],["italian-ballot","Italy"],["polish-banner","Poland"]]){
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
 ["1948-06-02","IT","none"],["1949-06-02","IT","italian-ballot"],["1976-06-02","IT","italian-ballot"],
 ["1977-06-02","IT","none"],["1977-06-05","IT","italian-ballot"],["1977-06-06","IT","none"],
 ["1985-06-02","IT","italian-ballot"],["2000-06-04","IT","italian-ballot"],["2000-06-02","IT","none"],
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
 return results;
}
const root=process.argv[2]||".";
let failed=0;
for(const name of ["magnolie-organizer/web/appearance.js","magnolie-organizer-windows/app/web/appearance.js"]){const result=probe(fs.readFileSync(path.join(root,name),"utf8"));console.log(name,JSON.stringify(result));failed+=result.filter(x=>!x.pass).length;}
process.exitCode=failed?1:0;
