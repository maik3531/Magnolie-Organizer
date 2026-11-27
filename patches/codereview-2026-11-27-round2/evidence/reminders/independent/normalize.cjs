'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {JSDOM}=require('$REVIEW_TOOLS/node_modules/jsdom');
const web='$REVIEW_SOURCE/magnolie-organizer-windows/app/web';
const dom=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{runScripts:'outside-only',url:'https://owned-reminder.test/',pretendToBeVisual:true});
const w=dom.window;
w.HTMLElement.prototype.scrollIntoView=()=>{};
w.webkit={messageHandlers:{bridge:{postMessage:()=>{}}}};
for(const f of ['i18n.js','normative-timezones.js','anwendung.js'])w.eval(fs.readFileSync(f==='normative-timezones.js'?'$EARLIER_REVIEW/review-integrated/magnolie-organizer-windows/app/web/normative-timezones.js':path.join(web,f),'utf8'));
w.document.dispatchEvent(new w.Event('DOMContentLoaded',{bubbles:true}));
w.App.init({daten:{},neu:false,regional:{language:'en',timeZone:'UTC'}});
let checks=0;
const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const out=cases.map(test=>{
 const normalized=JSON.parse(JSON.stringify(w.OrganizerTest.normalisiere(test.data)));
 for(const key of ['termine','aufgaben'])for(const item of normalized[key]||[]){
   if(!Array.isArray(item.alarme)){console.log(JSON.stringify({name:test.name,key,id:item.id,alarms:'absent',roundtrip:item.icsRoundtrip}));continue;}
   assert.ok(item.alarme.filter(a=>a.bearbeitbar===false).length>=2,test.name+': readonly alarms retained');checks++;
   const display=item.alarme.filter(a=>a.aktion==='display'&&a.bearbeitbar===false);
   assert.equal(display.length,2,test.name+': two absolute display times');checks++;
   assert.deepEqual(display.map(a=>a.triggerRaw).sort(),['20261127T103015Z','20261127T103030Z']);checks++;
 }
 return {...test,data:normalized};
});
fs.writeFileSync(process.argv[3],JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify({uiNormalization:'actual windows application',cases:out.length,checks}));
w.close();
