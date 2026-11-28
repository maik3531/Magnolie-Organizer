"use strict";
function extract(source,name){const start=source.indexOf("  function "+name+"("),end=source.indexOf("\n  }\n",start);if(start<0||end<0)throw Error(name);return source.slice(start,end+5);}
async function checkSource(source,expect) {
 const start=source.indexOf("  const LAENDER = ["),end=source.indexOf("\n  ];",start)+5;
 const body=source.slice(start,end)+"\n"+["feiertagRegionen","feiertagLand","feiertagPasstZurAuswahl","wendeOrtAuswahlDatenAn","starteFeiertage","wendeFeiertageDatenAn","mcpFeiertagWerkzeuge","ortStandText","ortStandAktualisieren","baueSeiteOrt"].map(n=>extract(source,n)).join("\n");
 const build=new Function("env",`const msgid=x=>x, _=x=>x, S=x=>String(x??""), kopie=x=>JSON.parse(JSON.stringify(x));
 let DATEN={einstellungen:{ort:{land:"FR",landName:"France",region:"",regionName:"",alleRegionen:false,ferien:true,feiertage:true,jahre:[],abgerufen:0,setupFerienAbruf:false}},feiertage:[]};let feiertageLaufen=false,feiertageAnfrage=null;let counter=0;
 const gueltigesISO=x=>typeof x==="string"&&/^\\d{4}-\\d{2}-\\d{2}$/.test(x)&&!Number.isNaN(Date.parse(x));
 const uid=()=>"id"+(++counter),enumWert=(x,options,fallback)=>options[x]??fallback;
 const $=()=>null, zettel=x=>env.messages.push(x),Bruecke={vorhanden:true,sende:x=>env.requests.push(x)};
 const mcpEditorPruefen=()=>{},personalSyncHash=async()=>"revision",mcpSchreiben=async(signal,fn)=>fn();
 const mcpNativeAufruf=async(cmd,args)=>{env.requests.push({cmd,...args});return {feiertage:[],jahre:args.jahre,abrufbereiche:[]};};
 const MagnolieMcp={ToolError:class extends Error{constructor(code,message){super(message);this.code=code;}}};
 const uebersetzt=(s,v)=>s.replace(/%\\((\\w+)\\)s/g,(_,key)=>String(v[key]??""));
 const uebersetztMehrzahl=(a,b,n)=>uebersetzt(n===1?a:b,{count:n});
 const organizerDatumzeitTeile=()=>({jahr:2026}),datumText=()=>"",planeSpeichern=()=>{},zeichneAlles=()=>{},aktualisiereLandFlagge=()=>{},oeffneZeitzonenManagement=()=>{},frage=async()=>false,baueEinstellungen=()=>{};
 const document=env.document, el=env.el,abschnitt=env.abschnitt,auswahlFeld=env.auswahlFeld,formZeile=env.formZeile,knopf=env.knopf;
 ${body}
 return {LAENDER,DATEN,change:wendeOrtAuswahlDatenAn,fetch:starteFeiertage,reset:()=>{feiertageLaufen=false;feiertageAnfrage=null;},match:feiertagPasstZurAuswahl,apply:wendeFeiertageDatenAn,mcp:mcpFeiertagWerkzeuge,status:ortStandText,ui:baueSeiteOrt};`);
 class N {constructor(tag="",text=""){this.tag=tag;this.children=[];this.textContent=text;this.events={};this.value="";} append(...n){this.children.push(...n);} addEventListener(event,fn){this.events[event]=fn;}}
 const env={requests:[],messages:[],document:{createElement:t=>new N(t),createTextNode:t=>new N("#text",t)},el:(t,c,s)=>new N(t,s),abschnitt:(t,s)=>{let n=new N("section",t);n.append(new N("p",s));return n;},auswahlFeld:(opts,value)=>{let n=new N("select");n.options=opts;n.value=value;return n;},formZeile:(label,field)=>{let n=new N("label",label);n.append(field);return n;},knopf:(label,c,fn)=>{let n=new N("button",label);n.events.click=fn;return n;}};
 const t=build(env),ort=t.DATEN.einstellungen.ort,fr=t.LAENDER.find(x=>x.code==="FR"),results=[];
 async function check(name,fn){try{results.push({name,pass:!!(await fn())});}catch(e){results.push({name,pass:false,error:String(e)});}}
 const reset=()=>{t.reset();env.requests.length=0;env.messages.length=0;Object.assign(ort,{land:"FR",region:"",alleRegionen:false,ferien:true,feiertage:true});};
 const row=(id,regions,nationwide=false,country="FR",art="school-holiday")=>({id,country,regions,region:regions.join(","),regionName:"",nationwide,art,von:"2026-02-08",bis:"2026-02-22",name:id});
 function find(root,id){if(root.id===id)return root;for(const c of root.children??[]){const n=find(c,id);if(n)return n;}return null;}
 await check("all 12 verified provider codes, no invented codes",()=>JSON.stringify(fr.regionen.map(x=>x[0]))===JSON.stringify(expect));
 for(const code of expect)await check("selected subdivision "+code,()=>{reset();if(!t.change({region:code}))return false;t.fetch([2026]);const p=env.requests[0];return p?.land==="FR"&&p.region===code&&p.ferien===true&&p.regionen.length===0&&p.regionErforderlich===false;});
 await check("country-wide legacy request remains one request with schools",()=>{reset();t.fetch([2026]);const p=env.requests[0];return p?.region===""&&p.regionen.length===0&&p.ferien&&p.regionErforderlich===false;});
 await check("FR all_regions bool remains unsupported; use empty direct scope",()=>{reset();return !t.change({alleRegionen:true})&&!ort.alleRegionen;});
 await check("foreign and fabricated codes rejected",()=>{reset();return !t.change({region:"BE-FR"})&&!t.change({region:"FR-ZD"})&&ort.region==="";});
 await check("country switch resets region and preserves data",()=>{reset();t.change({region:"FR-ZA"});t.DATEN.feiertage=[row("keep",["FR-ZA"])];return t.change({land:"DE"})&&ort.region===""&&!ort.alleRegionen&&t.DATEN.feiertage.length===1;});
 await check("DE region-required behavior unchanged",()=>{reset();t.change({land:"DE"});t.fetch([2026]);return env.requests[0]?.regionErforderlich===true;});
 await check("school opt-out still sent",()=>{reset();if(!t.change({region:"FR-ZC",ferien:false}))return false;t.fetch([2026]);return env.requests[0]?.ferien===false;});
 await check("zone A includes explicit zone plus administrative aliases, not zone B or overseas",()=>{reset();if(!t.change({region:"FR-ZA"}))return false;return t.match(row("a",["FR-ZA","FR-AR","FR-BF","FR-NA"]))&&!t.match(row("b",["FR-ZB","FR-BT"]))&&!t.match(row("ru",["FR-RU"]));});
 await check("Réunion Southern summer does not leak to Zone C",()=>{reset();if(!t.change({region:"FR-RU"}))return false;return t.match(row("south",["FR-RU"]))&&!t.match(row("mainland",["FR-ZC","FR-IF"]));});
 await check("national public holiday stays visible in selected zone, foreign does not",()=>{reset();if(!t.change({region:"FR-ZB"}))return false;return t.match(row("national",[],true,"FR","public-holiday"))&&!t.match(row("foreign",[],true,"BE","public-holiday"));});
 await check("status counts selected cached rows only",()=>{reset();if(!t.change({region:"FR-ZC"}))return false;t.DATEN.feiertage=[row("C",["FR-ZC"]),row("B",["FR-ZB"]),row("national",[],true,"FR","public-holiday")];const s=t.status();return s.includes("1 holiday period")&&s.includes("1 public holiday")&&!s.includes("2 holiday periods");});
 await check("actual settings page has Region, All blank choice, 12 options, no state checkbox",()=>{reset();let root=new N("root");t.ui(root);const region=find(root,"ort-region");if(!region||!region.options)return false;return region.options[0][0]===""&&region.options[0][1]==="All"&&region.options.length===expect.length+1&&!find(root,"ort-alle-regionen");});
 await check("actual settings change handler selects Zone B",()=>{reset();let root=new N("root");t.ui(root);const region=find(root,"ort-region");if(!region?.events.change)return false;region.value="FR-ZB";region.events.change();return ort.region==="FR-ZB"&&ort.regionName==="Zone B";});
 await check("MCP exposes same regions",async()=>{reset();const r=await t.mcp()[0].call({});return r.countries.find(x=>x.code==="FR").regionen.length===expect.length;});
 await check("MCP retrieval selected code and no fake state requirement",async()=>{reset();if(!t.change({region:"FR-ZA"}))return false;const m=t.mcp().find(x=>x.name==="organizer_holidays_retrieve");await m.call({expected_revision:"revision",years:[2026]},{aborted:false});return env.requests[0]?.region==="FR-ZA"&&env.requests[0]?.regionErforderlich===false;});
 await check("MCP country-wide retrieval unchanged",async()=>{reset();const m=t.mcp().find(x=>x.name==="organizer_holidays_retrieve");await m.call({expected_revision:"revision",years:[2026]},{aborted:false});return env.requests[0]?.region===""&&env.requests[0]?.regionErforderlich===false;});
 await check("scope refresh Zone A preserves Zone B and overseas rows",()=>{reset();if(!t.change({region:"FR-ZA"}))return false;t.DATEN.feiertage=[row("old-A",["FR-ZA"]),row("keep-B",["FR-ZB"]),row("keep-RU",["FR-RU"])];t.apply({jahre:[2026],feiertage:[],abrufbereiche:[{country:"FR",region:"FR-ZA",art:"school-holiday",von:"2026-01-01",bis:"2026-12-31"}]},{...ort,jahre:[2026]});return t.DATEN.feiertage.map(r=>r.id).join(",")==="keep-B,keep-RU";});
 await check("legacy country-wide valid coverage still recognized",()=>{reset();t.DATEN.feiertage=[row("old-FR",["FR-ZA"]),row("keep-DE",["DE-BY"],false,"DE")];t.apply({jahre:[2026],feiertage:[],abrufbereiche:[{country:"FR",region:"",art:"school-holiday",von:"2026-01-01",bis:"2026-12-31"}]},{...ort,jahre:[2026]});return t.DATEN.feiertage.map(r=>r.id).join(",")==="keep-DE";});
 await check("unconfirmed region refresh preserves cached school dates",()=>{reset();if(!t.change({region:"FR-ZA"}))return false;t.DATEN.feiertage=[row("keep-old",["FR-ZA"])];t.apply({jahre:[2026],feiertage:[],abrufbereiche:[]},{...ort,jahre:[2026]});return t.DATEN.feiertage.length===1;});
 return results;
}
const fs=require("node:fs"),path=require("node:path");
const paths=["magnolie-organizer/web/anwendung.js","magnolie-organizer-windows/app/web/anwendung.js"],expected=["FR-ZA","FR-ZB","FR-ZC","FR-CO","FR-GP","FR-GY","FR-MQ","FR-YT","FR-RU","FR-BL","FR-MF","FR-SP"];
(async()=>{for(const p of paths){const source=fs.readFileSync(path.join(process.argv[2]||process.cwd(),p),"utf8");new Function(source);const cases=await checkSource(source,expected);console.log(JSON.stringify({path:p,cases},null,2));if(cases.some(x=>!x.pass))process.exitCode=1;}})().catch(e=>{console.error(e);process.exitCode=1;});
