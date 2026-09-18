/* Test APK only. Drives the actual canonical editors in the real Android WebView. */
window.NativeScenario = (() => {
  const T=window.OrganizerTest, $=s=>document.querySelector(s), tick=()=>new Promise(r=>setTimeout(r,50));
  const set=(s,v)=>{const e=$(s); if(!e) throw Error('Missing '+s); e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));};
  const click=(s,text)=>{const b=[...document.querySelectorAll(s)].find(e=>e.textContent.trim()===text); if(!b) throw Error('Missing button '+text); b.click();};
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
    await T.wechsel('notizen'); click('#kopf-links button','New page'); await tick();
    set('#notiz-titel','Synthetic native note'); $('#notiz-text').textContent='Private synthetic note body';
    $('#notiz-text').dispatchEvent(new Event('input',{bubbles:true})); T.sichereNotizSnapshot(); T.speichereJetzt();
    return T.daten().notizen.find(x=>x.titel==='Synthetic native note');
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
    set('.custom-eintrag-formular input[type=time]',time);
    click('.custom-eintrag-aktionen button','Add'); await tick(); T.speichereJetzt();
    const module=T.daten().customOrganizer.modules.find(x=>x.type==='appointments');
    if(!module.items.length || module.items[0].time!==time) throw Error('Custom editor did not preserve time'); return module;
  }
  return {task,calendar,contact,note,custom,set,click};
})();
