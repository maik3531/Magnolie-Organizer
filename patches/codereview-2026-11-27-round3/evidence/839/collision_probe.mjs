import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';

const repo=path.resolve(process.argv[2]), require=createRequire(import.meta.url);
const {JSDOM,VirtualConsole}=require(process.env.MACOS_BETA_JSDOM);
const raw=['DTSTART:20300510T103000Z','DTEND:20300510T113000Z',
  'BEGIN:VALARM','ACTION:DISPLAY','TRIGGER;VALUE=DATE-TIME:20300510T103000Z','END:VALARM'];
const record=process.argv[3] ? {...JSON.parse(fs.readFileSync(process.argv[3],'utf8')),id:'coincident-event'} :
  {id:'coincident-event',uid:'coincident-event',titel:'Coincident event',datum:'2030-05-10',zeit:'10:30',endZeit:'11:30',
  icsAnzeigeZeitzone:'UTC',icsRoundtrip:raw,standardErinnerung:true};
const reports=[];
const {boot,tick}=await import(pathToFileURL(path.join(repo,'Magnolie-Organizer-macOS-Beta/tests/ui_harness.mjs')));
{
  const b=await boot(path.join(repo,'Magnolie-Organizer-macOS-Beta/Generated'),Date.parse('2030-05-10T10:29:59Z'));
  try {
    b.w.MacBeta.receive('init',{daten:{termine:[record],einstellungen:{allgemein:{handbuchHinweisGezeigt:true},regional:{timeZone:'UTC'},erinnerung:{an:true,vorlauf:0}}},neu:false,regional:{language:'en',timeZone:'UTC'}});
    await tick();
    const notifications=()=>b.messages.filter(m=>m.cmd==='erinnerung_zeigen');
    b.t.pruefeErinnerungen(); const early=notifications().length;
    b.at('2030-05-10T10:30:00Z'); b.t.pruefeErinnerungen(); const due=notifications().slice(early);
    b.t.pruefeErinnerungen(); const repeated=notifications().length-early-due.length;
    reports.push({platform:'macOS projected UI to real notification bridge',expected:1,actual:due.length,early,repeated,messages:due});
  } finally {b.close();}
}
{
  const web=path.join(repo,'Magnolie-Organizer-Android-Tablet-Beta/app/build/generated/projection/assets/web');
  const read=f=>fs.readFileSync(path.join(web,f),'utf8');
  const errors=[],console=new VirtualConsole();console.on('jsdomError',e=>errors.push(String(e)));
  const dom=new JSDOM(read('index.html'),{url:'https://appassets.androidplatform.net/assets/web/index.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
  const w=dom.window;w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w,'crypto',{value:webcrypto});w.Element.prototype.getAnimations=()=>[];
  const session=webcrypto.randomUUID();let revision=webcrypto.randomUUID(),savedAlarms;
  w.TabletNative={postMessage(text){const m=JSON.parse(text);setTimeout(()=>{
    if(m.cmd==='bereit')w.Tablet.receive({callback:'init',payload:{daten:null,session,revision}});
    if(m.cmd==='tablet_loaded')w.Tablet.receive({callback:'ready',payload:{session,revision}});
    if(m.cmd==='speichern'){savedAlarms=m.alarms;revision=webcrypto.randomUUID();w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision:m.revision,revision}});}
  },0);}};
  try {
    for(const f of ['normative-timezones.js','beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','anwendung.js'])w.eval(read(f));
    await new Promise(r=>setTimeout(r,70));
    const t=w.OrganizerTest,book=t.daten();book.einstellungen.regional.timeZone='UTC';book.einstellungen.erinnerung.an=true;book.einstellungen.erinnerung.vorlauf=0;
    book.termine=t.normalisiere({termine:[record]}).termine;book.aufgaben=[];
    const alarms=JSON.parse(JSON.stringify(w.Tablet.alarms()));
    await new Promise((resolve,reject)=>w.MagnolieTabletActions.persist(resolve,reject));
    reports.push({platform:'Android Tablet projected UI and durable save message',expected:1,actual:alarms.length,alarms,savedAlarms,errors});
  }finally{dom.window.close();}
}
console.log(JSON.stringify(reports,null,2));
if(reports.some(r=>r.actual!==r.expected))process.exitCode=1;
