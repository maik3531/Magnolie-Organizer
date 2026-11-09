/* Actual projected canonical appointment form; synthetic bridge, never native UI evidence. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const {createRequire}=require('node:module');
const tabletRequire=createRequire(path.resolve(__dirname,'../../Magnolie-Organizer-Android-Tablet-Beta/package.json'));
const {JSDOM,VirtualConsole}=process.env.MACOS_BETA_JSDOM?require(process.env.MACOS_BETA_JSDOM):tabletRequire('jsdom');
const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,
  '../../Magnolie-Organizer-Android-Tablet-Beta/app/src/test/resources/calendar-export-normalized-ui.json')));
const clone=value=>JSON.parse(JSON.stringify(value));
const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
function alarmBlocks(lines) {
  const result=[];let block=null;
  for(const line of lines) {
    if(line==='BEGIN:VALARM')block=[line];
    else if(block){block.push(line);if(line==='END:VALARM'){result.push(block);block=null;}}
  }
  return result;
}
function opaqueRecord(duplicate=false) {
  const record=clone(fixture.importDocument.termine[0]);
  const lines=record.icsRoundtrip;
  const trigger=lines.indexOf('TRIGGER:-PT15M');assert.ok(trigger>=0);
  lines[trigger]='TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma":-PT15M';
  lines.splice(trigger+1,0,'X-OPAQUE-ALARM:keep');
  if(duplicate){const block=alarmBlocks(lines)[0].map(line=>line==='X-OPAQUE-ALARM:keep'?'X-OPAQUE-ALARM:other':line);lines.push(...block);}
  return record;
}
async function boot(web,platform,record) {
  const errors=[],messages=[],vc=new VirtualConsole();vc.on('jsdomError',error=>errors.push(error));
  const dom=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{
    url:platform==='tablet'?'https://appassets.androidplatform.net/assets/web/index.html':'https://macos-alarm-host.invalid/',
    runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;let disk=null,revision=webcrypto.randomUUID();const session=webcrypto.randomUUID();
  w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;w.structuredClone=structuredClone;
  Object.defineProperty(w,'crypto',{value:webcrypto});
  w.HTMLElement.prototype.scrollIntoView=()=>{};w.Element.prototype.getAnimations=()=>[];
  w.setTimeout=()=>0;w.clearTimeout=()=>{};w.setInterval=()=>0;w.requestAnimationFrame=()=>0;w.cancelAnimationFrame=()=>{};
  function profile(){const data=w.OrganizerTest.leereDaten();data.termine=record?[clone(record)]:[];
    data.einstellungen.allgemein.handbuchHinweisGezeigt=true;data.einstellungen.regional.language='en';
    data.einstellungen.regional.timeZone='UTC';return data;}
  if(platform==='tablet')w.TabletNative={postMessage(raw){const message=JSON.parse(raw);messages.push(message);
    setTimeout(()=>{
      if(!w.document)return;
      if(message.cmd==='bereit')w.Tablet.receive({callback:'init',payload:{daten:profile(),session,revision}});
      if(message.cmd==='tablet_loaded')w.Tablet.receive({callback:'ready',payload:{session,revision}});
      if(message.cmd==='speichern'){assert.equal(message.session,session);assert.equal(message.revision,revision);
        disk=JSON.parse(message.text);revision=webcrypto.randomUUID();
        w.Tablet.receive({callback:'gespeichert',payload:{id:message.id,ok:true,session,expectedRevision:message.revision,revision}});}
    },0);
  }};
  else {
    w.__MAGNOLIE_BRUECKE__='alarmTest';
    w.webkit={messageHandlers:{alarmTest:{postMessage(raw){const message=JSON.parse(raw);messages.push(message);
      if(message.cmd==='speichern')setTimeout(()=>{if(w.document){disk=JSON.parse(message.text);w.MacBeta.receive('gespeichert',{id:message.id,ok:true});}},0);
    }}}};
  }
  for(const script of w.document.querySelectorAll('script[src]'))w.eval(fs.readFileSync(path.join(web,script.getAttribute('src')),'utf8'));
  await tick();await tick();
  if(platform==='macos')w.MacBeta.receive('init',{daten:profile(),neu:false,regional:{language:'en',timeZone:'UTC'}});
  await tick();
  assert.ok(w.OrganizerTest);assert.equal(errors.length,0,errors.map(String).join('\n'));
  if(record)assert.equal(w.OrganizerTest.daten().termine.length,1);
  return {w,t:w.OrganizerTest,messages,errors,disk:()=>disk,close:()=>dom.window.close()};
}
async function run({web,platform}) {
  assert.ok(['macos','tablet'].includes(platform));let checks=0;
  const first=await boot(web,platform,opaqueRecord());
  try {
    const {w,t}=first,record=t.daten().termine[0];const audio=alarmBlocks(record.icsRoundtrip).find(block=>block.includes('ACTION:AUDIO'));
    const edit=(value)=>{const editor=t.oeffneTerminBlatt(record,record.datum),input=editor.querySelector('.tb-alarm-zahl');
      assert.ok(input);input.value=String(value);input.dispatchEvent(new w.Event('input',{bubbles:true}));editor.querySelector('#tb-fertig').click();
      assert.equal(w.document.querySelector('#tb-fertig'),null);};
    for(const value of [30,45]) {
      edit(value);
      const blocks=alarmBlocks(record.icsRoundtrip),display=blocks.find(block=>block.includes('ACTION:DISPLAY'));
      assert.ok(display.includes('X-OPAQUE-ALARM:keep'));
      assert.ok(display.includes('TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma":-PT'+value+'M'));
      assert.ok(display.includes('DESCRIPTION:Synthetic reminder'));
      assert.deepEqual(blocks.find(block=>block.includes('ACTION:AUDIO')),audio);
      assert.equal(record.alarme.find(alarm=>alarm.bearbeitbar).offsetMinuten,value);checks++;
    }
    const cloneInput=clone(record),beforeClone=JSON.stringify(cloneInput);
    assert.deepEqual(alarmBlocks(t.spiegeleTerminInIcs(cloneInput)),alarmBlocks(record.icsRoundtrip));
    assert.equal(JSON.stringify(cloneInput),beforeClone);checks++;
    const staleClone=clone(record);staleClone.alarme.find(alarm=>alarm.bearbeitbar).offsetMinuten=46;
    assert.throws(()=>t.spiegeleTerminInIcs(staleClone),error=>error.code==='ambiguous-alarm');checks++;
    const relatedEdit=clone(record);relatedEdit.alarme.find(alarm=>alarm.bearbeitbar).related='END';
    const relatedRaw=t.spiegeleTerminInIcs(relatedEdit,clone(record));
    assert.ok(relatedRaw.includes('TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma";RELATED=END:-PT45M'));
    assert.ok(relatedRaw.includes('X-OPAQUE-ALARM:keep'));checks++;
    let editor=t.oeffneTerminBlatt(record,record.datum);
    assert.equal(editor.querySelectorAll('#tb-alarme input[type="checkbox"]').length,0);
    editor.querySelector('.tb-alarm-zahl').closest('.tb-alarm-zeile').querySelector('button').click();
    editor.querySelector('#tb-fertig').click();
    assert.deepEqual(alarmBlocks(record.icsRoundtrip),[audio]);checks++;
    editor=t.oeffneTerminBlatt(record,record.datum);
    [...editor.querySelectorAll('#tb-alarme button')].find(button=>button.textContent==='Add reminder').click();
    const input=editor.querySelector('.tb-alarm-zahl');input.value='20';input.dispatchEvent(new w.Event('input',{bubbles:true}));
    editor.querySelector('#tb-fertig').click();
    const blocks=alarmBlocks(record.icsRoundtrip);assert.equal(blocks.length,2);
    assert.deepEqual(blocks.find(block=>block.includes('ACTION:AUDIO')),audio);
    assert.ok(blocks.find(block=>block.includes('ACTION:DISPLAY')).includes('TRIGGER;RELATED=START:-PT20M'));
    assert.ok(!record.icsRoundtrip.includes('X-OPAQUE-ALARM:keep'));checks++;
    t.speichereJetzt();await tick();await tick();
    assert.deepEqual(first.disk().termine[0].icsRoundtrip,clone(record.icsRoundtrip));checks++;
    assert.equal(first.errors.length,0,first.errors.map(String).join('\n'));
  } finally {first.close();}
  const fresh=await boot(web,platform,null);
  try {
    const {w,t}=fresh,editor=t.oeffneTerminBlatt(null,'2030-05-10');
    editor.querySelector('#tb-titel').value='New appointment with new alarm';
    [...editor.querySelectorAll('#tb-alarme button')].find(button=>button.textContent==='Add reminder').click();
    editor.querySelector('#tb-fertig').click();
    assert.equal(w.document.querySelector('#tb-fertig'),null);
    assert.equal(t.daten().termine.length,1);
    assert.ok(alarmBlocks(t.daten().termine[0].icsRoundtrip)[0].includes('TRIGGER;RELATED=START:-PT15M'));checks++;
    t.speichereJetzt();await tick();await tick();assert.equal(fresh.disk().termine.length,1);checks++;
  } finally {fresh.close();}
  const ambiguous=await boot(web,platform,opaqueRecord(true));
  try {
    const {w,t,messages}=ambiguous,record=t.daten().termine[0];
    const before=JSON.stringify(t.daten()),saves=messages.filter(message=>message.cmd==='speichern').length;
    const editor=t.oeffneTerminBlatt(record,record.datum),input=editor.querySelector('.tb-alarm-zahl');
    input.value='30';input.dispatchEvent(new w.Event('input',{bubbles:true}));editor.querySelector('#tb-fertig').click();
    assert.ok(w.document.querySelector('#tb-fertig'),'Ambiguous edit must remain open');
    assert.equal(JSON.stringify(t.daten()),before,'Ambiguous edit must not mutate any book data');
    assert.equal(messages.filter(message=>message.cmd==='speichern').length,saves,'Ambiguous edit must not save');
    assert.ok(w.document.querySelector('#zettel').textContent.includes('Unsupported alarm'));checks++;
  } finally {ambiguous.close();}
  return checks;
}
module.exports=run;
if(require.main===module)run({platform:process.argv[2],web:path.resolve(process.argv[3])})
  .then(checks=>console.log('Shared DISPLAY alarm form: '+checks+' '+process.argv[2]+' checks; host JS only.'))
  .catch(error=>{console.error(error);process.exitCode=1;});
