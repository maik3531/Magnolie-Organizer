/* Run through planner_webkit_probe.py --prints, on immutable assets in native WebKit. */
"use strict";
window.plannerPrintRegressions=async function(data,{status,send,wait,assert}){
  const T=OrganizerTest,options=window.plannerProbeOptions,passed=[];
  const equal=(a,b,message)=>assert(JSON.stringify(a)===JSON.stringify(b),message+": "+JSON.stringify(a));
  const keys=["feiertage","ferien","urlaub","termine","jahrestage","schichten","zyklus","muell"];
  const all=Object.fromEntries(keys.map(key=>[key,true]));
  const original=JSON.stringify(T.daten());
  const select=(id,value)=>{const node=document.querySelector(id);assert(node,"Missing "+id);
    node.value=String(value);node.dispatchEvent(new Event("change",{bubbles:true}));};
  const close=()=>document.querySelector(".planer-druck-blatt header button").click();
  const complete=async()=>{
    const deadline=performance.now()+90000;
    while(status().pending||T.icsRuntime?.state?.paint||document.querySelector('.planer-druck-vorschau[aria-busy="true"]')){
      assert(!status().recurrenceError,"Print recurrence error: "+status().recurrenceError);
      assert(performance.now()<deadline,"Print completion timeout");await wait(20);
    }
    assert(!status().recurrenceError,"Print recurrence error: "+status().recurrenceError);
  };
  const open=async(wahl,art="month",month=8)=>{
    T.oeffneDruckvorschau(null,"planer");select("#planer-druck-monat",month);select("#planer-druck-art",art);
    for(const [key,value] of Object.entries(wahl)){
      const node=document.querySelector('[data-druck-option="'+key+'"]');
      assert(node,"Missing optional print control "+key);
      if(node.checked!==value)node.click();
    }
    await complete();
    assert([...document.querySelectorAll(".druck-fuss button")].every(node=>!node.disabled),"Complete export remains disabled");
  };
  const bridge=selector=>new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(new Error("Print bridge timeout")),3000);
    window.plannerBridgeReply=value=>{clearTimeout(timeout);resolve(value);};
    document.querySelector(selector).click();
  });
  const color=value=>{const node=document.createElement("span");node.style.color=value;return node.style.color;};
  const checkMonth=(model,html,ods,preview)=>{
    assert(!model.icsIncomplete,"Incomplete model exported");
    equal([model.wochen.length,ods.zeilen.length,ods.spalten.length],[6,6,8],"Month dimensions");
    const documentHtml=new DOMParser().parseFromString(html,"text/html");
    const htmlCells=[...documentHtml.querySelectorAll("tbody td")],previewCells=[...preview.querySelectorAll("tbody td")];
    equal([htmlCells.length,previewCells.length],[42,42],"Rendered month dimensions");
    model.wochen.forEach((week,w)=>week.tage.forEach((day,d)=>{
      const visible=day.eintraege.slice(0,5),more=Math.max(0,day.eintraege.length-5);
      const cell=ods.inhalte[w][d+1],printed=htmlCells[w*7+d],shown=previewCells[w*7+d];
      equal(cell.eintraege,visible.map(e=>({text:e.text,farbe:e.farbe,art:e.art})),"ODS labels/groups/colors");
      equal(cell.mehr,more,"ODS overflow count");
      equal(cell.marker,day.zyklus.map(m=>({text:m.symbol,farbe:m.farbe})),"ODS cycle markers");
      equal(ods.zeilen[w][d+1],[day.imMonat?String(day.tag):"",...day.zyklus.map(m=>m.symbol+" "+m.name),
        ...day.eintraege.map(e=>e.text)].join("\n"),"ODS full text fieldset");
      for(const [node,selector,prefix] of [[printed,".eintrag:not(.mehr)",""],[shown,".pm-anlass:not(.pm-mehr)","pm-"]]){
        equal([...node.querySelectorAll(selector)].map(e=>({text:e.textContent,art:[...e.classList].find(c=>c!==prefix+(prefix?"anlass":"eintrag")).slice(prefix.length),
          farbe:color(prefix?e.style.getPropertyValue("--eintragfarbe"):e.style.borderLeftColor)})),
        visible.map(e=>({text:e.text,art:e.art,farbe:color(e.farbe)})),"HTML/preview labels/groups/colors");
        equal(node.querySelector("."+prefix+"mehr")?.textContent||"",more?"+"+more:"","HTML/preview overflow count");
        equal([...node.querySelectorAll("."+prefix+"zyklus")].map(e=>({text:e.textContent,farbe:color(e.style.color)})),
          day.zyklus.map(m=>({text:m.symbol,farbe:color(m.farbe)})),"HTML/preview cycle symbols/colors");
      }
    }));
  };
  T.zustand().planer.jahr=2026;T.zustand().kalender.monat=8;
  // The cold dialog must not export a partial worker result. Change selection before completion.
  T.oeffneDruckvorschau(null,"planer");select("#planer-druck-art","month");
  send({probe:"print-defaults",globalWaste:T.daten().einstellungen.kalender.muellkalenderAn,
    options:Object.fromEntries([...document.querySelectorAll('[data-druck-option]')].map(node=>[node.dataset.druckOption,node.checked]))});
  if(T.icsRuntime){
    assert(document.querySelector('.planer-druck-vorschau[aria-busy="true"]')&&
      document.querySelector(".ods-knopf").disabled,"Cold pending print looked complete");
    select("#planer-druck-art","year");close();await T.wechsel("notizen");await complete();
    assert(!document.querySelector("#druck-schleier")&&T.zustand().sektion==="notizen","Closed preview stole the tab");
    passed.push("closed-pending-preview-isolation");
  }else close();
  await open(all);
  const full=T.planerMonatsModell(2026,8,all);
  const entries=full.wochen.flatMap(w=>w.tage).flatMap(d=>d.eintraege);
  const fortnight=entries.filter(e=>e.art==="termin"&&e.text.includes("Ordinary fortnightly")).length;
  const dense=entries.filter(e=>e.art==="termin"&&e.text.includes("Ordinary dense")).length;
  T.termineAm("1998-01-02",true);await complete();
  const denseWitness=T.termineAm("1998-01-02",true).filter(t=>t.id==="ordinary-dense").length;
  const expectedWitness=options.tier==="compatible"?1:144;
  if(options.tier==="compatible"){
    const end=data.termine.find(t=>t.id==="ordinary-dense").wiederholung.bis;
    const after=new Date(Date.parse(end)+86400000).toISOString().slice(0,10);
    for(const [date,expected] of [[end,1],[after,0]]){
      T.termineAm(date,true);await complete();
      equal(T.termineAm(date,true).filter(t=>t.id==="ordinary-dense").length,expected,"Compatible COUNT boundary "+date);
    }
    passed.push("compatible-count-boundary");
  }
  const semanticCompatible=fortnight===34&&dense===(options.tier==="compatible"?30:0)&&denseWitness===expectedWitness;
  send({probe:"recurrence-compatibility",tier:options.tier,fortnight,expectedFortnight:34,dense,
    expectedDense:options.tier==="compatible"?30:0,ok:semanticCompatible,
    denseWitness,expectedWitness,minutelyCountSupported:!!T.icsRuntime});
  if(!options.baseline||options.tier==="compatible")assert(semanticCompatible,"Fixture recurrence semantics were lost");
  close();
  const variants=[["all",all],["none",Object.fromEntries(keys.map(key=>[key,false]))],
    ...keys.map(key=>["without-"+key,{...all,[key]:false}])];
  for(const [name,wahl] of variants){
    await open(wahl);
    const model=T.planerMonatsModell(2026,8,wahl),preview=document.querySelector(".planer-monatskalender").cloneNode(true);
    const printed=await bridge(".druck-fuss button:first-child");
    await open(wahl);const ods=await bridge(".ods-knopf");
    equal(printed.cmd,"drucken","Print bridge command");equal(ods,T.planerOdsNutzlast(model),"Actual ODS bridge payload");
    equal(printed.html,T.planerDruckSeite(model),"Actual print bridge HTML");checkMonth(model,printed.html,ods,preview);
    for(const key of keys){
      const art={feiertage:"feiertag",ferien:"ferien",urlaub:"urlaub",termine:"termin",jahrestage:"jahrestag",schichten:"schicht",muell:"muell"}[key];
      if(!wahl[key])assert(model.wochen.every(w=>w.tage.every(d=>key==="zyklus"?!d.zyklus.length:!d.eintraege.some(e=>e.art===art))),"Deselected field leaked: "+key);
    }
    if(name==="all"){
      equal(entries.filter(e=>e.art==="muell").map(e=>({text:e.text,farbe:e.farbe})),
        Array.from({length:2},()=>({text:"Waste <paper> & blue",farbe:"#3478ab"})),"Waste recurrence label/color/count");
      assert(entries.some(e=>e.art==="jahrestag")&&entries.some(e=>e.art==="schicht"),"Optional markers absent");
    }
    send({probe:"print-artifact",name:"month-"+name,html:printed.html,data:{model,ods},fieldset:wahl});
    passed.push("month-"+name);
  }
  // These categories occur in other months in the unchanged large fixture.
  for(const [key,month,art] of [["feiertage",0,"feiertag"],["ferien",6,"ferien"],["urlaub",7,"urlaub"]]){
    for(const enabled of [true,false]){
      const wahl={...all,[key]:enabled};await open(wahl,"month",month);
      const model=T.planerMonatsModell(2026,month,wahl);
      assert(model.wochen.some(w=>w.tage.some(d=>d.eintraege.some(e=>e.art===art)))===enabled,"Month optional "+key);
      checkMonth(model,T.planerDruckSeite(model),T.planerOdsNutzlast(model),document.querySelector(".planer-monatskalender"));close();
    }
    passed.push("month-toggle-"+key);
  }
  for(let mask=0;mask<8;mask++){
    const wahl=Object.fromEntries(["feiertage","ferien","urlaub"].map((key,i)=>[key,!!(mask&(1<<i))]));
    await open(wahl,"year");
    const model=T.planerKalenderModell(2026,wahl),ods=T.planerOdsNutzlast(model),html=T.planerDruckSeite(model);
    const doc=new DOMParser().parseFromString(html,"text/html");
    const shown=[...document.querySelectorAll(".planer-druck-kalender tbody td")],printed=[...doc.querySelectorAll("tbody td")];
    equal([shown.length,printed.length,ods.zeilen.length,ods.spalten.length],[372,372,31,12],"Year dimensions");
    model.zeilen.forEach((row,r)=>row.forEach((day,c)=>{
      const cell=ods.inhalte[r][c],index=r*12+c;
      equal([...shown[index].querySelectorAll(".pk-anlass")].map(e=>e.textContent),cell.eintraege.map(e=>e.text),"Year preview fields");
      equal([...printed[index].querySelectorAll(".anlass")].map(e=>e.textContent),cell.eintraege.map(e=>e.text),"Year print fields");
      if(day)for(const [key,field] of [["feiertage","feiertage"],["ferien","ferien"],["urlaub","urlaube"]])
        if(!wahl[key])assert(!day[field].length,"Year deselected field leaked");
    }));
    equal((await bridge(".druck-fuss button:first-child")).html,html,"Actual year print bridge HTML");
    await open(wahl,"year");equal(await bridge(".ods-knopf"),ods,"Actual year ODS bridge payload");
    send({probe:"print-artifact",name:"year-"+mask,html,data:{model,ods},fieldset:wahl});passed.push("year-"+mask);
  }
  equal(JSON.stringify(T.daten()),original,"Print selection changed stored data");
  // Global waste calendar defaults off, independently of the print option's enabled default.
  const defaults=T.normalisiere({muelltermine:data.muelltermine});
  assert(defaults.einstellungen.kalender.muellkalenderAn===false,"Global waste default changed");
  T.daten().einstellungen.kalender.muellkalenderAn=false;
  T.oeffneDruckvorschau(null,"planer");select("#planer-druck-art","month");await complete();
  assert(!document.querySelector('[data-druck-option="muell"]')&&!document.querySelector(".pm-muell"),"Disabled module leaked waste print fields");
  const disabled=T.planerMonatsModell(2026,8,all);
  checkMonth(disabled,T.planerDruckSeite(disabled),T.planerOdsNutzlast(disabled),document.querySelector(".planer-monatskalender"));close();
  T.daten().einstellungen.kalender.muellkalenderAn=true;
  passed.push("waste-default-off");
  await open(all);select("#planer-druck-monat",7);select("#planer-druck-monat",8);await complete();
  const final=T.planerMonatsModell(2026,8,all);
  checkMonth(final,T.planerDruckSeite(final),T.planerOdsNutzlast(final),document.querySelector(".planer-monatskalender"));close();
  passed.push("latest-month-no-stale-preview");
  equal(JSON.stringify(T.daten()),original,"Optional print tests changed data");
  assert(status().workers<=1&&status().maxPending<=1024&&status().cachedJobs<=1024&&status().duplicateJobs===0,
    "Global worker budget or duplicate work regression");
  passed.push("global-worker-budget");
  // August starts on Saturday and ends in the sixth row: neither edge may clip.
  const denseData={termine:[],jahrestage:[],feiertage:[],urlaube:[],muelltermine:[],tagmarken:[],
    schichten:[{id:"pdf-shift",name:"SHIFT Long shift label",von:"08:00",bis:"16:00",farbe:"#789abc"}],
    zyklusmarker:[{id:"pdf-cycle",name:"Cycle",symbol:"*",farbe:"#987abc"}],
    einstellungen:{allgemein:{handbuchHinweisGezeigt:true},kalender:{schichtplanerAn:true,zykluskalenderAn:true,urlaubsplanerAn:true,muellkalenderAn:true}}};
  for(const [date,suffix,count] of [["2026-08-01","FIRST",13],["2026-08-31","LAST",12]]){
    denseData.feiertage.push({id:"public-"+suffix,von:date,bis:date,name:"HOL-"+suffix+" Long holiday label ".repeat(10),art:"public-holiday"},
      {id:"school-"+suffix,von:date,bis:date,name:"SCH-"+suffix+" Long school label ".repeat(10),art:"school-holiday"});
    denseData.urlaube.push({id:"vacation-"+suffix,von:date,bis:date,symbol:"palm",darstellung:"symbol-text"});
    denseData.muelltermine.push({id:"waste-"+suffix,von:date,name:"WASTE-"+suffix+" Long collection label",intervallTage:0,farbe:"#3478ab",art:"custom"});
    denseData.jahrestage.push({id:"birthday-"+suffix,datum:date.replace("2026","1980"),name:"BDAY-"+suffix,typ:"birthday"});
    denseData.tagmarken.push({datum:date,schichtId:"pdf-shift",zyklusIds:["pdf-cycle"]});
    for(let i=0;i<count;i++)denseData.termine.push({id:"pdf-"+suffix+i,datum:date,titel:"APPT-"+i+" Long appointment label ".repeat(10)});
  }
  App.init({daten:denseData,neu:false,handbuchInstalliert:true,handbuchVersion:"2.0.18",regional:{language:"de",timeZone:"UTC"}});
  T.zustand().planer.jahr=2026;T.zustand().kalender.monat=7;
  const denseOriginal=JSON.stringify(T.daten());
  for(const [name,wahl] of [["all",all],["none",Object.fromEntries(keys.map(key=>[key,false]))],
    ["selected",Object.fromEntries(keys.map(key=>[key,["termine","jahrestage","muell"].includes(key)]))],
    ["without-muell",{...all,muell:false}]]){
    await open(wahl,"month",7);
    const model=T.planerMonatsModell(2026,7,wahl),preview=document.querySelector(".planer-monatskalender").cloneNode(true);
    const html=(await bridge(".druck-fuss button:first-child")).html;
    await open(wahl,"month",7);const ods=await bridge(".ods-knopf");checkMonth(model,html,ods,preview);
    if(name==="all")for(const [row,col,more] of [[0,5,14],[5,0,13]]){
      equal(model.wochen[row].tage[col].eintraege.slice(0,5).map(e=>e.art),["feiertag","ferien","urlaub","schicht","muell"],"Legacy group order, including fifth waste entry");
      equal(ods.inhalte[row][col+1].mehr,more,"Dense first/last row omitted count");
    }
    send({probe:"print-artifact",name:"month-dense-"+name,html,data:{model,ods},fieldset:wahl});passed.push("dense-print-"+name);
  }
  equal(JSON.stringify(T.daten()),denseOriginal,"Dense print selection changed data");
  send({probe:"done",ok:semanticCompatible,tests:passed.length,passed,semanticCompatible,...status()});
};
