/* Shared native-test-only scenarios. Every feature mutation goes through the
 * actual current Organizer settings/forms/editor bindings, never a seeded model.
 * Platform hosts own durable-save ACKs, reload and trusted canvas input. */
window.NativeDomains = (() => {
  const T=window.OrganizerTest, $=selector=>document.querySelector(selector);
  const tr=text=>window.MagnolieI18n.gettext(text), tick=()=>new Promise(resolve=>setTimeout(resolve,30));
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const set=(target,value)=>{
    const field=typeof target==='string'?$(target):target;assert(field,'Missing domain form field');
    field.value=String(value);field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));return field;
  };
  const click=(selector,label)=>{const button=[...document.querySelectorAll(selector)].find(node=>node.textContent.trim()===tr(label));assert(button,'Missing domain action: '+label);button.click();};
  const aria=(selector,label)=>{const button=[...document.querySelectorAll(selector)].find(node=>node.getAttribute('aria-label')===tr(label));assert(button,'Missing domain control: '+label);button.click();};
  const date=(field,value)=>{T.setzeDatumswert(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));};
  const clone=value=>JSON.parse(JSON.stringify(value));
  const save=async()=>{T.speichereJetzt();await tick();};
  let coverReceipt=null;
  function coverTarget() {
    const book=$('#buch'),cover=$('#deckel');assert(book&&cover,'Missing actual book cover');
    assert(!book.classList.contains('offen'),'Domain opening must start with the actual closed cover');
    const rect=cover.getBoundingClientRect(),left=Math.max(0,rect.left),right=Math.min(innerWidth,rect.right),
      top=Math.max(0,rect.top),bottom=Math.min(innerHeight,rect.bottom);
    assert(right-left>40&&bottom-top>40,'Book cover is not visibly clickable');
    const x=(left+right)/2,y=(top+bottom)/2,hit=document.elementFromPoint(x,y);
    assert(hit&&cover.contains(hit),'Book cover target is covered');
    cover.addEventListener('click',event=>{coverReceipt={trusted:event.isTrusted,tag:event.target?.tagName||'',className:String(event.target?.className||'').slice(0,160)};},{capture:true,once:true});
    return {x,y};
  }
  async function opened() {
    const deadline=performance.now()+3000;let stable=0;
    while(performance.now()<deadline) {
      await new Promise(resolve=>requestAnimationFrame(resolve));
      assert(!coverReceipt||coverReceipt.trusted,'Book must open through trusted native input');
      const book=$('#buch'),cover=$('#deckel');
      const ready=coverReceipt?.trusted&&book?.classList.contains('offen')&&cover&&getComputedStyle(cover).display==='none'&&
        (!cover.getAnimations||cover.getAnimations().every(animation=>!['running','pending'].includes(animation.playState)));
      stable=ready?stable+1:0;
      if(stable>=2)return {trustedCoverClick:true,coverRemoved:true,stableFrames:stable,receipt:coverReceipt};
    }
    throw Error('Actual native book opening/animation did not complete within3seconds');
  }
  function drawingTargetReady(target) {
    const canvas=$('.custom-zeichenblatt');assert(canvas,'Missing actual drawing canvas');
    const points=[];
    for(let index=0;index<=8;index++) {
      const fraction=index/8,x=target.x1+(target.x2-target.x1)*fraction;
      for(const y of [target.y,target.y+Math.sin(fraction*Math.PI)*8]) {
        const hit=document.elementFromPoint(x,y);
        assert(hit===canvas,'Native drawing target missed canvas: '+JSON.stringify({x,y,tag:hit?.tagName||'',className:String(hit?.className||'').slice(0,160)}));
        points.push({x,y});
      }
    }
    return {canvasHit:true,checkedPoints:points.length};
  }
  async function drawingInputReady() {
    const deadline=performance.now()+3000;let previous='',stableSince=0,frames=0,last=null;
    while(performance.now()<deadline) {
      await new Promise(resolve=>requestAnimationFrame(resolve));
      const canvas=$('.custom-zeichenblatt');assert(canvas,'Missing actual drawing canvas');
      const rect=canvas.getBoundingClientRect(),module=T.daten().customOrganizer.modules.find(item=>item.type==='drawing');
      const sample={left:rect.left,top:rect.top,width:rect.width,height:rect.height,
        bitmapWidth:canvas.width,bitmapHeight:canvas.height,modelWidth:module?.drawing?.width,modelHeight:module?.drawing?.height,
        fonts:document.fonts?.status||'unsupported'};
      const key=JSON.stringify(sample),now=performance.now();last=sample;
      if(key!==previous||sample.fonts==='loading'){previous=key;stableSince=now;frames=0;}else frames++;
      if(frames<4||now-stableSince<150)continue;
      assert(window.MagnolieZeichnen.valid(module?.drawing)&&module.drawing.strokes.length===0,'Input preparation requires an empty valid drawing');
      assert(window.__domainPointers.down===0&&window.__domainPointers.move===0&&window.__domainPointers.up===0,'Input baseline must precede native pointers');
      const top=Math.max(rect.top,0),bottom=Math.min(rect.bottom,innerHeight);
      assert(rect.width>100&&bottom-top>80,'Drawing canvas is not visible enough for a native stroke');
      const target={x1:rect.left+rect.width*.2,x2:rect.left+rect.width*.75,y:top+(bottom-top)*.45};
      const hit=drawingTargetReady(target);
      window.__domainCanvasBefore=canvas.toDataURL('image/png');
      return {target,readiness:{...hit,geometry:sample,stableFrames:frames,stableMilliseconds:now-stableSince}};
    }
    throw Error('Drawing geometry/bitmap/fonts did not settle within 3 seconds: '+JSON.stringify(last));
  }
  async function prepare() {
    assert(T.daten().customOrganizer.modules.length===0,'Domain acceptance requires an unused disposable custom organizer');
    assert(['vitalwerte','blutzucker','medikamente'].every(key=>T.daten().gesundheit[key].length===0),'Domain acceptance requires unused disposable health tables');
    T.oeffneEinstellungen();await tick();
    for(const id of ['allgemein-register-gesundheit','allgemein-register-custom']) {const box=$('#'+id);assert(box,'Missing optional tab setting');if(!box.checked)box.click();await tick();}
    set('#allgemein-custom-name','Synthetic domains');
    $('#einst-tab-kalender').click();await tick();
    for(const [kind,value] of [['temperatur','celsius'],['gewicht','kg'],['groesse','cm'],['blutzucker','mmol/L']]) {
      set('#kalender-gesundheit-einheit-'+kind,value);await tick();
    }
    T.schliesseEinstellungen();await save();return {settingsThroughUi:true};
  }
  async function health() {
    await T.wechsel('gesundheit');await tick();aria('.gesundheit-kopfwahl button','Vital signs');await tick();
    let row=$('.vitalwert-tabelle tbody tr');assert(row,'Missing vital table');
    let inputs=[...row.querySelectorAll('input')];assert(inputs.length===8,'Unexpected vital table contract');
    date(inputs[0],'2030-05-13');set(inputs[1],'08:10');
    [72,118,78,999,68.4,172].forEach((value,index)=>set(inputs[index+2],value));
    click('.gesundheit-tabellenaktionen button','Save');await tick();
    assert(T.daten().gesundheit.vitalwerte.length===0,'Invalid health value was committed');
    set(inputs[5],36.6);click('.gesundheit-tabellenaktionen button','Save');await tick();await save();
    const vital=T.daten().gesundheit.vitalwerte[0];assert(vital&&vital.puls===72&&vital.systolisch===118&&vital.temperatur===36.6,'Vital UI values lost');
    aria('.gesundheit-kopfwahl button','Blood glucose table');await tick();
    row=$('.blutzucker-tabelle tbody tr');inputs=[...row.querySelectorAll('input')];assert(inputs.length===5,'Unexpected glucose table contract');
    date(inputs[0],'2030-05-13');set(inputs[1],'08:15');set(inputs[2],5.6);set(inputs[3],0);set(inputs[4],'Synthetic test context');
    click('.gesundheit-tabellenaktionen button','Save');await tick();await save();
    assert(T.daten().gesundheit.blutzucker[0]?.wert===5.6,'Glucose UI value lost');
    aria('.gesundheit-kopfwahl button','Medication plan');await tick();
    const left=$('.medikament-links tbody tr'),right=$('.medikament-rechts tbody tr');
    inputs=[...left.querySelectorAll('input')];set(inputs[0],'Synthetic fixture — not medication');set(inputs[1],'Test only');
    const form=left.querySelector('select');set(form,[...form.options].find(option=>option.value)?.value||form.options[0].value);
    inputs=[...right.querySelectorAll('input')];assert(inputs.length===8,'Unexpected medication table contract');
    ['1','','','','1','fixture unit','Software test','No clinical use'].forEach((value,index)=>set(inputs[index],value));
    click('.gesundheit-tabellenaktionen button','Save');await tick();await save();
    assert(T.daten().gesundheit.medikamente[0]?.name==='Synthetic fixture — not medication','Medication UI row lost');
    const retained=JSON.stringify(T.daten().gesundheit);
    set('.medikament-links tbody tr input','Discarded synthetic change');click('.gesundheit-tabellenaktionen button','Discard');await tick();
    assert(JSON.stringify(T.daten().gesundheit)===retained,'Discard changed persisted health records');
    aria('.gesundheit-kopfwahl button','Vital signs');await tick();
    set($('.vitalwert-tabelle tbody tr').querySelectorAll('input')[2],73);click('.gesundheit-tabellenaktionen button','Save');await tick();await save();
    assert(T.daten().gesundheit.vitalwerte.length===1&&T.daten().gesundheit.vitalwerte[0].puls===73,'Vital edit duplicated or lost record');
    return {vitalRows:1,glucoseRows:1,medicationRows:1,invalidValueRejected:true,discardPreserved:true,editPreserved:true};
  }
  async function addModule(type,title) {
    const before=new Set(T.daten().customOrganizer.modules.map(module=>module.id));
    T.oeffneCustomDesigner();await tick();set('.custom-designer-werkzeuge select',type);click('.custom-designer-werkzeuge button','Add');await tick();
    const module=T.daten().customOrganizer.modules.find(item=>!before.has(item.id));assert(module,'Designer did not create module');
    const card=[...document.querySelectorAll('.custom-editor-karte')].find(item=>item.dataset.moduleId===module.id);set(card.querySelector('input[type=text]'),title);
    $('.custom-designer-kopf button').click();await tick();return module.id;
  }
  async function custom() {
    await T.wechsel('custom');await tick();
    await addModule('appointments','Synthetic appointment block');await T.wechsel('custom');await tick();
    $('.custom-modul-appointments .custom-modul-kopf-aktionen button').click();await tick();
    set('.custom-titel-zeile input','Synthetic domain appointment');date($('.custom-eintrag-formular .datumsfeld'),'2030-05-14');
    set('.custom-eintrag-formular .zeitfeld','12:35');set('.custom-notiz-zeile textarea','Synthetic retained appointment note');click('.custom-eintrag-aktionen button','Add');await tick();
    $('.custom-modul-appointments .custom-modul-eintrag').click();await tick();set('.custom-eintrag-formular .zeitfeld','13:05');
    click('.custom-eintrag-aktionen button','Save changes');await tick();
    await addModule('tasks','Synthetic task block');await T.wechsel('custom');await tick();
    $('.custom-modul-tasks .custom-modul-kopf-aktionen button').click();await tick();
    set('.custom-titel-zeile input','Synthetic domain task');date($('.custom-eintrag-formular .datumsfeld'),'2030-05-15');
    set('.custom-eintrag-formular .zeitfeld','13:40');click('.custom-eintrag-aktionen button','Add');await tick();
    $('.custom-modul-tasks input[type=checkbox]').click();await tick();
    await addModule('notes','Synthetic text block');await T.wechsel('custom');await tick();
    const plus=[...document.querySelectorAll('.custom-modul-notes .custom-modul-kopf-aktionen button')].find(button=>button.textContent==='+');assert(plus,'Missing custom text add');plus.click();await tick();
    const editor=$('.custom-modul-notes .custom-text-editor');assert(editor&&editor.isContentEditable!==false,'Missing custom text editor');
    editor.textContent='Synthetic domain text — preserved';editor.dispatchEvent(new Event('input',{bubbles:true}));await save();
    const modules=T.daten().customOrganizer.modules;
    assert(modules.find(module=>module.type==='appointments')?.items[0]?.time==='13:05','Custom appointment edit lost');
    assert(modules.find(module=>module.type==='tasks')?.items[0]?.time==='13:40'&&modules.find(module=>module.type==='tasks').items[0].done,'Custom task completion lost');
    assert(modules.find(module=>module.type==='notes')?.items.some(item=>item.text.includes('Synthetic domain text')),'Custom text lost');
    return {moduleTypes:['appointments','tasks','notes'],uiDesigner:true};
  }
  async function drawing() {
    await addModule('drawing','Synthetic drawing sheet');await T.wechsel('custom');await tick();
    const canvas=$('.custom-zeichenblatt');assert(canvas,'Missing actual drawing canvas');
    canvas.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});await tick();
    window.__domainPointers={down:0,move:0,up:0,untrusted:0};
    for(const [type,key] of [['pointerdown','down'],['pointermove','move'],['pointerup','up']]) canvas.addEventListener(type,event=>{
      if(event.isTrusted)window.__domainPointers[key]++;else window.__domainPointers.untrusted++;
    });
    return (await drawingInputReady()).target;
  }
  async function drawingProof() {
    const module=T.daten().customOrganizer.modules.find(item=>item.type==='drawing');
    assert(module&&window.MagnolieZeichnen.valid(module.drawing)&&module.drawing.strokes.length===1,'Native input did not create one valid stroke');
    const canvas=$('.custom-zeichenblatt'),after=canvas.toDataURL('image/png');
    assert(after!==window.__domainCanvasBefore,'Native stroke changed no rendered pixels');
    const pointer=window.__domainPointers;assert(pointer.down>0&&pointer.move>0&&pointer.up>0&&pointer.untrusted===0,'Native stroke lacked trusted pointer events');
    aria('.zeichen-werkzeuge button','Undo');await tick();assert(module.drawing.strokes.length===0,'Drawing Undo did not remove stroke');
    aria('.zeichen-werkzeuge button','Redo');await tick();assert(module.drawing.strokes.length===1,'Drawing Redo did not restore stroke');
    assert(canvas.toDataURL('image/png')===after,'Drawing Redo did not restore rendered pixels');await save();
    return {strokeCount:1,pointCount:module.drawing.strokes[0].points.length,pixelChange:true,undoRedo:true,pointer};
  }
  const snapshot=()=>clone({health:T.daten().gesundheit,custom:T.daten().customOrganizer,tab:T.daten().einstellungen.allgemein.customTab,units:T.daten().einstellungen.kalender.gesundheitEinheiten});
  // The canonical health normalizer adds only this absent optional zero field
  // to freshly created vital rows. Preserve every existing value and every other
  // field; this clone is an expected-result policy, never a product-model write.
  const expectedAfterReopen=value=>{
    const expected=clone(value),health=expected.health||expected.gesundheit;
    for(const row of health?.vitalwerte||[]) if(!Object.hasOwn(row,'sauerstoff')) row.sauerstoff=0;
    return expected;
  };
  return {coverTarget,opened,drawingTargetReady,drawingInputReady,prepare,health,custom,drawing,drawingProof,snapshot,expectedAfterReopen};
})();
