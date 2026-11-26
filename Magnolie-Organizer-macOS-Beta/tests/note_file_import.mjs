import assert from 'node:assert/strict';
import { boot, tick } from './ui_harness.mjs';
let checks = 0;
const equal=(a,b,label)=>{assert.deepEqual(JSON.parse(JSON.stringify(a)),JSON.parse(JSON.stringify(b)),label); checks++;};
const b=await boot(process.argv[2]);const {w,t,messages}=b;
const original={termine:[],aufgaben:[],kontakte:[],notizen:[{id:'existing',titel:'same.pdf',text:'',future:{retain:17}}],futureRoot:{keep:'opaque'},einstellungen:{allgemein:{handbuchHinweisGezeigt:true}}};
w.MacBeta.receive('init',{daten:original,neu:false,regional:{language:'en',timeZone:'UTC'}});
const seen=new Set();
async function pump({snapshot=true,save=true,ackSaves=true}={}) {
  for(let n=0;n<8;n++) {
    for(const m of [...messages]) {
      const key=m.cmd+':'+(m.id??m.token??'');if(seen.has(key))continue;
      if(m.cmd==='speichern'&&ackSaves){seen.add(key);w.MacBeta.receive('gespeichert',{id:m.id,ok:save,fehler:save?'':'Synthetic save failure'});}
      if(m.cmd==='mutations_snapshot'){seen.add(key);w.MacBeta.receive('mutationsSnapshot',{token:m.token,ok:snapshot,fehler:snapshot?'':'Synthetic recovery failure'});}
    }
    await tick();
  }
}
function item(name,text='',bytes='one') {
 const fields={titel:name,text,anhaenge:[]};
 if(name.endsWith('.pdf'))fields.anhaenge=[{art:'pdf',daten:'data:application/pdf;base64,'+Buffer.from('%PDF-'+bytes).toString('base64'),id:crypto.randomUUID(),name}];
 return {fields,sourceName:name,sourceSHA256:'a'.repeat(64),sourceBytes:7,warnings:[]};
}
try {
 await pump();
 t.daten().einstellungen.futureImportSettings={opaque:['keep',{nested:17}]};
 t.daten().gesundheit.futureImportDomain={opaque:['health',true]};
 t.daten().customOrganizer.futureImportDomain={opaque:['custom',false]};
 const untouched=()=>JSON.stringify({settings:t.daten().einstellungen,health:t.daten().gesundheit,custom:t.daten().customOrganizer});
 const domainsBefore=untouched();
 const before=JSON.stringify(t.daten());
 const payload={items:[item('same.pdf','','first'),item('same.pdf','','second'),item('literal.md',' \n# Text <script>literal</script>\n ')]};
 let settled=false;
 const pending=w.App.macOSBetaImportNoteFiles(payload).then(value=>{settled=true;return value;});
 equal(JSON.stringify(t.daten()),before,'No mutation before recovery snapshot ACK');
 await pump();const result=await pending;
 equal(result.count,3,'Three additive notes despite identical titles and empty attachment-note text');
 equal(settled,true,'Success only after real canonical save ACK');
 equal(t.daten().notizen[0].future,{retain:17},'Existing note extension untouched');
 equal(untouched(),domainsBefore,'Shared note normalization does not mutate nested settings/domain objects');
 equal(t.daten().futureRoot,{keep:'opaque'},'Existing root extension untouched');
 equal(new Set(t.daten().notizen.map(n=>n.id)).size,4,'Fresh IDs preserve all preexisting notes');
 equal(t.daten().notizen.at(-1).text,payload.items[2].fields.text,'Literal Markdown whitespace and source retained');
 equal(t.daten().notizen.slice(1,3).map(n=>n.anhaenge[0].daten),payload.items.slice(0,2).map(i=>i.fields.anhaenge[0].daten),'Distinct original PDF bytes retained');
 assert.ok(!t.daten().notizen.at(-1).html.includes('<script>'));checks++;
 let stable=JSON.stringify(t.daten());
 const failed=w.App.macOSBetaImportNoteFiles({items:[item('reject.txt','not committed')]}).then(()=>null,e=>e.message);
 await pump({snapshot:false});assert.match(await failed,/recovery/i);checks++;
 equal(JSON.stringify(t.daten()),stable,'Failed recovery checkpoint preserves the entire book');
 const bad=item('bad.pdf');bad.fields.anhaenge[0].daten='invalid';
 await assert.rejects(w.App.macOSBetaImportNoteFiles({items:[bad]}),/Attachment/);checks++;
 equal(JSON.stringify(t.daten()),stable,'Invalid attachment has no partial mutation');
 for(const literal of ['<&'.repeat(524288),'line\n'.repeat(20000)]) {
   const large=item('large.txt',literal);large.sourceBytes=Buffer.byteLength(literal);
   const beforeLarge=JSON.stringify(t.daten());
   const outcome=w.App.macOSBetaImportNoteFiles({items:[item('all-or-nothing.txt','also rejected'),large]}).then(()=>null,e=>e.message);
   // Escaping a long text-node must remain exact; too many rendered elements
   // must fail the entire selection before checkpoint or mutation.
   if(literal.startsWith('line')) {
     assert.match(await outcome,/safe rendered-note limit/);checks++;
     equal(JSON.stringify(t.daten()),beforeLarge,'Rendered line limit rejects the whole selection before mutation');
   } else {
     await pump();await outcome;
     equal(t.daten().notizen.at(-1).text,literal,'1MiB escaped literal text stays complete');
     const surface=w.document.createElement('div');surface.innerHTML=t.daten().notizen.at(-1).html;
     equal(surface.textContent,literal,'1MiB escaped literal renders without truncation or interpretation');
   }
 }
 // #781: exercise the actual asynchronous checkpoint callback, not a copied helper.
 for (const [locale, prefix] of [['en', 'Note copies were added, but saving was not confirmed.'],
                                ['de', 'Notizkopien wurden hinzugefügt, ihre Speicherung wurde jedoch nicht bestätigt.']]) {
   w.MacBeta.receive('init',{daten:JSON.parse(JSON.stringify(t.daten())),neu:false,regional:{language:locale,timeZone:'UTC'}});
   await pump();
   const retained=JSON.stringify(t.daten().notizen), count=t.daten().notizen.length;
   const appearance=w.MagnolieAppearance;
   w.MagnolieAppearance={...appearance,update(){throw new Error('Synthetic renderer failure after file append');}};
   let settled=false;
   const failedRender=w.App.macOSBetaImportNoteFiles({items:[item('renderer-'+locale+'.txt','Exact file text <b>literal</b>')]}).then(
     value=>{settled=true;return {value};},error=>{settled=true;return {error:error.message};});
   try { await pump(); } finally { w.MagnolieAppearance=appearance; }
   equal(settled,true,'Async renderer failure settles original Promise: '+locale);
   const outcome=await failedRender;
   assert.ok(outcome.error?.startsWith(prefix),JSON.stringify(outcome));checks++;
   equal(t.daten().notizen.length,count+1,'Mutation stays visible after failure: '+locale);
   equal(JSON.stringify(t.daten().notizen.slice(0,count)),retained,'Existing notes unchanged: '+locale);
   equal(t.daten().notizen.at(-1).text,'Exact file text <b>literal</b>','Appended original content retained: '+locale);
   const id=t.daten().notizen.at(-1).id;
   t.speichereJetzt();await pump();
   const saved=JSON.parse(messages.filter(message=>message.cmd==='speichern').at(-1).text);
   equal(saved.notizen.filter(note=>note.id===id).length,1,'Retry saves exactly the existing copy: '+locale);
   w.MacBeta.receive('init',{daten:saved,neu:false,regional:{language:locale,timeZone:'UTC'}});await pump();
   equal(t.daten().notizen.filter(note=>note.id===id).length,1,'Reopen preserves exactly the saved copy: '+locale);
 }
 w.MacBeta.receive('init',{daten:JSON.parse(JSON.stringify(t.daten())),neu:false,regional:{language:'en',timeZone:'UTC'}});t.speichereJetzt();await pump();
 const beforeFailedWrite=t.daten().notizen.length;
 const failedWrite=w.App.macOSBetaImportNoteFiles({items:[item('pending.txt','retain unsaved import')]}).then(()=>null,e=>e.message);
 await pump({save:false});assert.match(await failedWrite,/unsaved/);checks++;
 equal(t.daten().notizen.length,beforeFailedWrite+1,'Failed final write leaves imported notes visible for save retry');
 t.speichereJetzt();await pump();
 // The final ACK belongs to a particular saved snapshot, not any current UI state.
 let ackSettled=false;
 const ackPending=w.App.macOSBetaImportNoteFiles({items:[item('ack-bound.txt','ACK-bound copy')]}).then(
   value=>{ackSettled=true;return {value};},error=>{ackSettled=true;return {error:error.message};});
 await pump({ackSaves:false});
 equal(ackSettled,false,'No import success before final Save-ACK');
 const waiting=messages.filter(message=>message.cmd==='speichern').at(-1);
 w.MacBeta.receive('gespeichert',{id:waiting.id+10000,ok:true});await tick();
 equal(ackSettled,false,'An unrelated ACK cannot complete this import');
 const removed=t.daten().notizen.pop();
 equal(removed.titel,'ack-bound.txt','Only the imported fixture is removed while save is pending');
 await pump();const ackOutcome=await ackPending;
 assert.match(ackOutcome.error||'',/document changed before the note-file import save completed/);checks++;
 t.speichereJetzt();await pump();
 stable=JSON.stringify(t.daten());
 w.App.macOSBetaStartNoteImport();await pump();
 equal(messages.filter(m=>m.cmd==='notiz_dateien_importieren').at(-1),{cmd:'notiz_dateien_importieren'},'Actual import action sends picker command without path or document body');
 w.MacBeta.validateRestore(JSON.stringify(original));
 await assert.rejects(w.App.macOSBetaImportNoteFiles({items:[item('fenced.txt','must not commit')]}),/not available/);checks++;
 equal(JSON.stringify(t.daten()),stable,'Replacement fence blocks note import');
 console.log(`Mac additive note files: ${checks} host checks; synthetic transport, not native picker evidence.`);
 process.exitCode=0;
} finally { b.close(); }
