/* #853 targeted source host, no native GUI. Run from repo root with node magnolie-organizer/pruefungen/appearance-national-de-at.cjs */
function run(source) {
  const nodes=[];
  class Node {
    constructor(name){this.name=name;this.attrs={};this.dataset={};this.children=[];this.style={};this.classList={add:()=>{}};}
    setAttribute(k,v){this.attrs[k]=String(v);}
    append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
    querySelectorAll(){return this.children.filter(n=>n.dataset.appearanceWatermark);}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
  }
  const document={createElementNS:(_ns,n)=>new Node(n),querySelector:()=>null,querySelectorAll:()=>nodes,body:{toggleAttribute:()=>{}}};
  const window={};
  new Function("window","document",source)(window,document);
  const a=window.MagnolieAppearance, results=[];
  function check(name,fn){let ok=false, error="";try{ok=!!fn();}catch(e){error=String(e);}results.push({name,ok,error});}
  for(const [date,land,want] of [
    ["1989-10-03","DE","none"],["1990-10-03","DE","unity-gate"],["2026-10-03","DE","unity-gate"],
    ["2026-10-02","DE","none"],["2026-10-04","DE","none"],["2026-10-03","AT","none"],["2026-10-03","FR","none"],
    ["1964-10-26","AT","none"],["1965-10-26","AT","neutrality-parliament"],["2026-10-26","AT","neutrality-parliament"],
    ["2026-10-25","AT","none"],["2026-10-27","AT","none"],["2026-10-26","DE","none"],["2026-10-26","CH","none"],
    ["2026-10-03","","none"],["2026-10-26","de","none"],["2026-10-03","AU","none"],["2026-02-30","DE","none"],
    ["2026-08-01","CH","swiss-lantern"],["2026-07-14","FR","french-rosette"],["2025-04-26","NL","kings-crown"],
    ["2025-04-27","NL","none"],["2026-12-06","DE","boots"],["2026-04-05","AT","eggs"],["2026-01-01","DE","glass"]
  ])check(date+" "+land+" => "+want,()=>a.holiday(date,land)===want);
  for(const [kind,parts] of [["unity-gate",3],["neutrality-parliament",4]]) {
    check(kind+" stamp shape",()=>{const s=a.stamp(kind);return s?.attrs.viewBox==="0 0 80 80"&&s.attrs["aria-hidden"]==="true"&&s.attrs.focusable==="false"&&s.children.length===parts;});
    check(kind+" inherits visual contract",()=>a.stamp(kind)?.children.every(n=>n.attrs.stroke==="currentColor"&&n.attrs["stroke-width"]==="2"&&n.attrs["stroke-linejoin"]==="round"&&n.attrs.d.length>0));
  }
  const day=new Node("div");nodes.push(day);const state={today:"2026-10-03",developer:false,locked:false};
  a.update({...state,country:"DE"});a.day(day,"2026-10-03");
  check("DE day",()=>day.children.length===1&&day.children[0].dataset.appearanceWatermark==="unity-gate");
  a.day(day,"2026-10-03");check("no duplicate",()=>day.children.length===1);
  a.update({...state,country:"AT"});check("country switch",()=>day.children.length===0);
  a.day(day,"2026-10-26");check("AT day",()=>day.children.length===1&&day.children[0].dataset.appearanceWatermark==="neutrality-parliament");
  a.update({...state,country:"AT",locked:true});check("locked",()=>day.children.length===0);
  return results;
}
if(typeof module!=="undefined"&&require.main===module) {
  const fs=require("fs");let failures=0;
  for(const p of ["magnolie-organizer/web/appearance.js","magnolie-organizer-windows/app/web/appearance.js"]) {
    const results=run(fs.readFileSync(p,"utf8"));console.log(JSON.stringify({path:p,results},null,2));failures+=results.filter(x=>!x.ok).length;
  } process.exitCode=failures?1:0;
}
