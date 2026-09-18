const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const {webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'..'), web=path.join(root,'app/build/generated/projection/assets/web');
const read=f=>fs.readFileSync(path.join(web,f),'utf8');
const tick=()=>new Promise(r=>setTimeout(r,30));
(async()=>{
  const errors=[], console=new VirtualConsole(); console.on('jsdomError',e=>errors.push(e));
  const dom=new JSDOM(read('index.html'),{url:'https://appassets.androidplatform.net/assets/web/index.html',
    runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
  const w=dom.window; w.TextEncoder=TextEncoder; w.TextDecoder=TextDecoder;
  Object.defineProperty(w,'crypto',{value:webcrypto}); w.Element.prototype.getAnimations=()=>[];
  const session=webcrypto.randomUUID(); let revision=webcrypto.randomUUID();
  w.TabletNative={postMessage(text){const m=JSON.parse(text); setTimeout(()=>{
    if(m.cmd==='bereit') w.Tablet.receive({callback:'init',payload:{daten:null,session,revision}});
    if(m.cmd==='tablet_loaded') w.Tablet.receive({callback:'ready',payload:{session,revision}});
    if(m.cmd==='speichern') {
      assert.equal(m.session,session); assert.equal(m.revision,revision); revision=webcrypto.randomUUID();
      w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision:m.revision,revision}});
    }
  },0);}};
  try {
    for(const f of ['beta-i18n.js','tablet.js','i18n.js','i18n-active.js','i18n-start.js','anwendung.js']) w.eval(read(f));
    await tick(); await tick();
    const T=w.OrganizerTest, d=w.document;
    T.daten().einstellungen.regional.timeZone='UTC';
    w.MagnolieI18n.setLocale('en'); await T.wechsel('aufgaben');
    const set=(selector,value)=>{const el=d.querySelector(selector); assert.ok(el,selector); el.value=value; el.dispatchEvent(new w.Event('input',{bubbles:true}));};
    set('#aufgabe-titel','A3 editor task');
    T.setzeDatumswert(d.querySelector('#aufgabe-faellig-zeile input'),'2030-05-10');
    d.querySelector('#aufgabe-faellig-zeile').dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
    const mode=[...d.querySelectorAll('#vorschlags-menue button')].find(b=>b.textContent==='Due on / Time');
    assert.ok(mode,'actual editor due-time mode'); mode.click();
    set('#aufgabe-faellig-zeit-zeile input','10:00');
    set('#aufgabe-individuelle-erinnerung','1 day before');
    d.querySelector('#aufgabe-erinnern').checked=false;
    const add=[...d.querySelectorAll('#inhalt-rechts button')].find(b=>b.textContent==='Add');
    assert.ok(add); add.click(); await tick();
    const task=T.daten().aufgaben.find(t=>t.titel==='A3 editor task');
    assert.ok(task); assert.equal(task.erinnern,false); assert.equal(task.individuelleErinnerungTage,1);
    global.console.log('Actual editor output:',JSON.stringify(task));
    const cases=[];
    const project=(name,record,zone,expected)=>{
      T.daten().aufgaben=[record]; T.daten().einstellungen.regional.timeZone=zone;
      const result=w.Tablet.alarms().filter(a=>a.section==='aufgaben');
      assert.deepEqual(result.map(a=>new Date(a.at).toISOString()),expected,name);
      assert.equal(new Set(result.map(a=>a.id)).size,result.length,name+' separate IDs');
      cases.push({name,task:JSON.parse(JSON.stringify(record)),zone,alarms:JSON.parse(JSON.stringify(result))});
      global.console.log('PASS '+name); return result;
    };
    const alarms=project('editor early-only UTC',task,'UTC',['2030-05-09T10:00:00.000Z']);
    assert.equal(alarms.length,1,'early-only editor task needs an alarm');
    assert.equal(alarms[0].at,Date.parse('2030-05-09T10:00:00Z'));
    // Edit the same actual source-generated record through the visible form, not a reduced fixture.
    async function edit(days,due) {
      const row=d.querySelector('#inhalt-links .zeilen-aktion'); assert.ok(row); row.click(); await tick();
      set('#aufgabe-individuelle-erinnerung',days ? '1 day before' : '');
      d.querySelector('#aufgabe-erinnern').checked=due;
      const save=[...d.querySelectorAll('#inhalt-rechts button')].find(b=>b.textContent==='Save changes');
      assert.ok(save); save.click(); await tick();
      return JSON.parse(JSON.stringify(T.daten().aufgaben.find(t=>t.id===task.id)));
    }
    const dueOnly=await edit(0,true);
    const dueResult=project('editor due-only UTC',dueOnly,'UTC',['2030-05-10T10:00:00.000Z']);
    assert.equal(dueResult[0].id,'aufgaben:'+dueOnly.id+':'+Date.parse('2030-05-10T10:00:00Z'),'existing due receipts remain valid');
    const combined=await edit(1,true);
    project('editor combined UTC',combined,'UTC',['2030-05-09T10:00:00.000Z','2030-05-10T10:00:00.000Z']);
    project('spring DST calendar day, not 24 hours',{...combined,faellig:'2026-03-29'},'Europe/Berlin',
      ['2026-03-28T09:00:00.000Z','2026-03-29T08:00:00.000Z']);
    project('autumn DST calendar day, not 24 hours',{...combined,faellig:'2026-10-25'},'Europe/Berlin',
      ['2026-10-24T08:00:00.000Z','2026-10-25T09:00:00.000Z']);
    project('source UTC wins over organizer timezone',{...combined,icsRoundtrip:['DUE:20300510T100000Z']},'Asia/Tokyo',
      ['2030-05-09T10:00:00.000Z','2030-05-10T10:00:00.000Z']);
    project('source TZID DST wins over organizer timezone',{...combined,faellig:'2026-03-29',
      icsRoundtrip:['DUE;TZID=Europe/Berlin:20260329T100000']},'America/New_York',
      ['2026-03-28T09:00:00.000Z','2026-03-29T08:00:00.000Z']);
    project('all-day default 08:00',{...combined,faelligZeit:''},'UTC',
      ['2030-05-09T08:00:00.000Z','2030-05-10T08:00:00.000Z']);
    project('done task',{...combined,erledigt:true},'UTC',[]);
    project('missing date',{...combined,faellig:''},'UTC',[]);
    project('invalid date',{...combined,faellig:'2030-02-30'},'UTC',[]);
    T.daten().einstellungen.erinnerung.an=false;
    project('global web opt-out',combined,'UTC',[]); T.daten().einstellungen.erinnerung.an=true;
    for(const [name,extra] of [
      ['structured recurrence',{wiederholung:{art:'weekly'}}],
      ['raw recurrence',{icsRoundtrip:['RRULE:FREQ=DAILY']}],
      ['malformed recurrence',{icsRoundtrip:['RRULE broken']}],
      ['EXRULE',{icsRoundtrip:['EXRULE:FREQ=DAILY']}],
      ['override',{icsRangeOverrides:[['RECURRENCE-ID:20300510T100000Z']]}],
      ['invalid DTSTART',{icsRoundtrip:['DTSTART:bad','DUE:20300510T100000Z']}],
      ['invalid DUE',{icsRoundtrip:['DUE:bad']}],
      ['unresolved timezone',{icsRoundtrip:['DUE;TZID=Not/AZone:20300510T100000']}],
      ['contradictory timezone',{icsRoundtrip:['DUE;TZID=Europe/Berlin:20300510T100000Z']}],
      ['DATE with time',{icsRoundtrip:['DUE;VALUE=DATE:20300510T100000']}],
      ['date with timezone',{icsRoundtrip:['DUE;TZID=Europe/Berlin;VALUE=DATE:20300510']}],
      ['duplicate DTSTART',{icsRoundtrip:['DTSTART:20300509T100000Z','DTSTART:20300509T110000Z','DUE:20300510T100000Z']}]
    ]) project('explicit unsupported '+name,{...combined,...extra},'UTC',[]);
    T.daten().aufgaben=[];
    const module={id:'custom-a3',type:'tasks',title:'Custom',reminders:false,
      items:[{id:'custom-item',title:'Custom task',due:'2030-05-10',time:'10:00',remind:true,done:false}]};
    T.daten().customOrganizer.modules=[module];
    assert.equal(w.Tablet.alarms().length,0,'custom module opt-out');
    module.reminders=true; const custom=w.Tablet.alarms(); assert.equal(custom.length,1); assert.ok(custom[0].custom);
    cases.push({name:'custom native consent fixture',alarms:JSON.parse(JSON.stringify(custom))});
    module.items[0].remind=false; assert.equal(w.Tablet.alarms().length,0,'custom item opt-out');
    const sourceHash=JSON.parse(fs.readFileSync(path.join(web,'../projection.json'))).sourceHash;
    fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
    fs.writeFileSync(path.join(root,'artifacts/a3-editor-vectors.json'),JSON.stringify({sourceHash,cases},null,2)+'\n');
    global.console.log('A3 actual-editor matrix passed: '+cases.length+' cases, plus module/item opt-out');
  } finally {dom.window.close(); await tick(); assert.equal(errors.length,0,errors.map(String).join('\n'));}
})().catch(e=>{console.error(e);process.exit(1);});
