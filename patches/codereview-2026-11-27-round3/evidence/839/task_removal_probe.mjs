import path from 'node:path';
import {pathToFileURL} from 'node:url';
const repo=path.resolve(process.argv[2]);
const {boot,tick}=await import(pathToFileURL(path.join(repo,'Magnolie-Organizer-macOS-Beta/tests/ui_harness.mjs')));
const reports=[];
for(const lead of [0,1]) {
  const date=lead?'2026-11-27':'2026-11-28';
  const b=await boot(path.resolve(process.argv[3]),Date.parse(date+'T10:29:59Z'));
  try {
    const task={id:'task-collision-'+lead,titel:'Coincident task',faellig:'2026-11-28',faelligZeit:'10:30',
      erinnern:!lead,individuelleErinnerungTage:lead,icsAnzeigeZeitzone:'UTC',
      icsRoundtrip:['CLASS:PUBLIC','DUE:20261128T103000Z','BEGIN:VALARM','ACTION:DISPLAY',
        'TRIGGER;VALUE=DATE-TIME:'+date.replaceAll('-','')+'T103000Z','END:VALARM']};
    b.w.MacBeta.receive('init',{daten:{aufgaben:[task],einstellungen:{allgemein:{handbuchHinweisGezeigt:true},
      regional:{timeZone:'UTC'},erinnerung:{an:true,vorlauf:0}}},neu:false,regional:{language:'en',timeZone:'UTC'}});
    await tick();const notifications=()=>b.messages.filter(m=>m.cmd==='erinnerung_zeigen');
    b.at(date+'T10:30:00Z');b.t.pruefeErinnerungen();const initial=notifications().length;
    b.t.daten().aufgaben[0].icsRoundtrip=task.icsRoundtrip.slice(0,2);b.t.pruefeErinnerungen();
    reports.push({lead,initial,afterSourceRemoval:notifications().length,expectedAfterRemoval:1,messages:notifications()});
  }finally{b.close();}
}
console.log(JSON.stringify(reports,null,2));
if(reports.some(r=>r.initial!==1||r.afterSourceRemoval!==1))process.exitCode=1;
