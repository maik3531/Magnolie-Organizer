/* Test APK only. Drives the actual canonical editors in the real Android WebView. */
window.NativeScenario = (() => {
  const T=window.OrganizerTest, $=s=>document.querySelector(s), tick=()=>new Promise(r=>setTimeout(r,50));
  const set=(s,v)=>{const e=$(s); if(!e) throw Error('Missing '+s); e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));};
  const click=(s,text,scope=document)=>{const b=[...scope.querySelectorAll(s)].find(e=>e.textContent.trim()===text); if(!b) throw Error('Missing button '+text); b.click();};
  async function task(title,date,time,early=0,due=true) {
    const existing=new Set(T.daten().aufgaben.map(x=>x.id));
    await T.wechsel('aufgaben'); click('#kopf-links button','New task'); await tick();
    set('#aufgabe-titel',title); T.setzeDatumswert($('#aufgabe-faellig-zeile input'),date);
    $('#aufgabe-faellig-zeile').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
    click('#vorschlags-menue button','Due on / Time');
    set('#aufgabe-faellig-zeit-zeile input',time); set('#aufgabe-individuelle-erinnerung',early ? early+' day before' : '');
    $('#aufgabe-erinnern').checked=due; click('#inhalt-rechts button','Add'); await tick(); T.speichereJetzt();
    const record=T.daten().aufgaben.find(x=>!existing.has(x.id)&&x.titel===title); if(!record) throw Error('Task editor did not save a new record'); return record;
  }
  async function calendar() {
    const existing=new Set(T.daten().termine.map(x=>x.id));
    await T.wechsel('kalender'); T.oeffneTerminBlatt(null,'2030-05-10'); await tick();
    set('#tb-titel','Synthetic native calendar'); set('#tb-ort','Tablet test room');
    if($('#tb-ganztaegig').checked) $('#tb-ganztaegig').click();
    set('#tb-zeit','10:00'); set('#tb-endzeit','11:00'); $('#tb-fertig').click(); await tick(); T.speichereJetzt();
    const record=T.daten().termine.find(x=>!existing.has(x.id)&&x.titel==='Synthetic native calendar'); if(!record) throw Error('Calendar editor did not save a new record'); return record;
  }
  async function contact() {
    const existing=new Set(T.daten().kontakte.map(x=>x.id));
    await T.wechsel('adressen'); click('#kopf-links button','New'); await tick();
    set('#kontakt-vorname','Synthetic'); set('#kontakt-nachname','Tablet'); set('#kontakt-notiz','Native contact only');
    const b=$('#inhalt-rechts .form-knoepfe button'); if(!b) throw Error('Missing contact save'); b.click(); await tick(); T.speichereJetzt();
    const record=T.daten().kontakte.find(x=>!existing.has(x.id)&&x.nachname==='Tablet'); if(!record) throw Error('Contact editor did not save a new record'); return record;
  }
  async function note() {
    const existing=new Set(T.daten().notizen.map(x=>x.id));
    await T.wechsel('notizen'); click('#kopf-links button','New page'); await tick();
    const dialog=[...document.querySelectorAll('.eingabe-dialog')].find(e=>e.querySelector('h2')?.textContent==='New page');
    if(!dialog) throw Error('Missing new-page creation dialog');
    const title=dialog.querySelector('input[type=text]'); if(!title) throw Error('Missing new-page title');
    title.value='Synthetic native note'; title.dispatchEvent(new Event('input',{bubbles:true}));
    click('.dialog-knoepfe button','Create',dialog); await tick();
    if(dialog.isConnected) throw Error('New-page creation dialog did not close');
    set('#notiz-titel','Synthetic native note'); $('#notiz-text').textContent='Private synthetic note body';
    $('#notiz-text').dispatchEvent(new Event('input',{bubbles:true})); T.sichereNotizSnapshot(); T.speichereJetzt();
    const record=T.daten().notizen.find(x=>!existing.has(x.id)&&x.titel==='Synthetic native note');
    if(!record || record.text!=='Private synthetic note body') throw Error('Note editor did not save the new title and body'); return record;
  }
  async function custom(title='Synthetic custom appointment',date='2030-05-10',time='12:35') {
    T.daten().einstellungen.allgemein.customTab.enabled=true;
    T.daten().einstellungen.allgemein.customTab.name='Tablet custom';
    T.oeffneCustomDesigner(); await tick();
    set('.custom-designer-werkzeuge select','appointments');
    if(!T.daten().customOrganizer.modules.some(x=>x.type==='appointments')) click('.custom-designer-werkzeuge button','Add');
    set('.custom-editor-karte input[type=text]','Synthetic custom calendar');
    if(!$('.custom-editor-karte input[type=checkbox]').checked) $('.custom-editor-karte input[type=checkbox]').click();
    $('.custom-designer-kopf button').click(); await T.wechsel('custom'); await tick();
    $('.custom-modul-appointments .custom-modul-kopf-aktionen button').click(); await tick();
    set('.custom-titel-zeile input',title);
    T.setzeDatumswert($('.custom-eintrag-formular .datumsfeld') || $('.custom-eintrag-formular input[type=date]'),date);
    set('.custom-eintrag-formular .zeitfeld',time);
    click('.custom-eintrag-aktionen button','Add'); await tick(); T.speichereJetzt();
    const module=T.daten().customOrganizer.modules.find(x=>x.type==='appointments');
    if(!module.items.length || module.items[0].time!==time) throw Error('Custom editor did not preserve time'); return module;
  }
  function navigationFixture(seed=null) {
    const data=T.daten();
    if(seed) {
      for(const key of Object.keys(data)) delete data[key]; Object.assign(data,seed);
    } else {
      data.termine=data.termine.filter(x=>!String(x.id).startsWith('old-series-'));
      const base=data.termine[0]; if(!base) throw Error('Missing seeded calendar');
      for(let i=0;i<17;i++) data.termine.push({...base,id:'old-series-'+i,titel:'Old series '+i,
        datum:'2000-01-01',zeit:'10:00',endDatum:'2000-01-01',endZeit:'11:00',
        icsRoundtrip:['DTSTART:20000101T100000Z','DTEND:20000101T110000Z','RRULE:FREQ=DAILY;COUNT=20000'],
        wiederholung:{art:'daily'}});
    }
    // This is a real data mutation: notify the existing canonical index/save
    // path rather than merely serializing data behind an already cached index.
    T.planeSpeichern(); T.speichereJetzt();
    return {series:data.termine.filter(x=>String(x.id).startsWith('old-series-')).length};
  }
  function recurrenceProof() {
    const series=T.daten().termine.filter(x=>String(x.id).startsWith('old-series-'));
    const metadata=series.filter(x=>x.datum==='2000-01-01' && x.wiederholung?.art==='daily' &&
      x.icsRoundtrip.includes('RRULE:FREQ=DAILY;COUNT=20000') &&
      x.icsRoundtrip.includes('DTSTART:20000101T100000Z') && x.icsRoundtrip.includes('DTEND:20000101T110000Z')).length;
    const rows=T.termineAm('2030-05-10',true).filter(x=>String(x.id).startsWith('old-series-'));
    const projected=rows.filter(x=>x.datum==='2030-05-10' && x.zeit==='10:00' &&
      x.icsOccurrence && Number.isFinite(x.icsStartUtc) && Number.isFinite(x.icsEndUtc) && x.icsEndUtc>x.icsStartUtc);
    const state=T.icsRuntime.state, workerAvailable=typeof Worker==='function';
    const readySeries=new Set();
    for(const [key,job] of state?.jobs || []) {
      const query=JSON.parse(key);
      if(query[0]==='expand' && String(query[1]?.id).startsWith('old-series-') && job.status==='ready') readySeries.add(query[1].id);
    }
    return {series:series.length,validMetadata:metadata,occurrences:rows.length,
      uniqueOccurrences:new Set(rows.map(x=>x.id)).size,datedOccurrences:projected.length,
      workerAvailable,workerActive:!!state?.worker,workerSeriesReady:readySeries.size,
      active:series.length===17 && metadata===17 && rows.length===17 && projected.length===17 &&
        new Set(rows.map(x=>x.id)).size===17 && (!workerAvailable || !!state?.worker && readySeries.size===17)};
  }
  return {task,calendar,contact,note,custom,navigationFixture,recurrenceProof,set,click};
})();
