/* Normal Planner scope and independent calendar/month-export recurrence checks. */
"use strict";
(async()=>{
  const send=value=>window.webkit.messageHandlers.planner_probe.postMessage(JSON.stringify(value));
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const assert=(value,message)=>{if(!value)throw new Error(message);};
  const equal=(a,b,message)=>assert(JSON.stringify(a)===JSON.stringify(b),message+": "+JSON.stringify(a));
  const T=OrganizerTest,requests=[],passed=[];
  let ticks=0,last=performance.now(),gaps=[];
  setInterval(()=>{const now=performance.now();gaps.push(now-last);last=now;ticks++;},10);
  const NativeWorker=Worker;
  window.Worker=class extends NativeWorker{postMessage(data,...args){requests.push({id:data.item?.id,mode:data.mode,key:data.key});super.postMessage(data,...args);}};
  const pending=()=>[...(T.icsRuntime.state?.jobs.values()||[])].some(job=>job.status==="pending");
  const settle=async()=>{const deadline=performance.now()+90000;
    while(pending()||T.icsRuntime.state?.paint||document.querySelector('.planer-raster[aria-busy="true"],.kalender-uebersicht-laedt')){
      assert(performance.now()<deadline,"Completion deadline");await wait(20);
    }};
  const load=data=>{T.zustand().sektion="notizen";App.init({daten:{...data,einstellungen:{...data.einstellungen,
    allgemein:{handbuchHinweisGezeigt:true,...data.einstellungen?.allgemein}}},neu:false,
    handbuchInstalliert:true,handbuchVersion:"2.0.18",regional:{language:"de",timeZone:"Europe/Berlin"}});};
  const item=(id,lines,extra={})=>({id,uid:id,datum:"2026-01-01",titel:id,notiz:"Complete original text\nSecond line",
    standardErinnerung:true,individuelleErinnerungTage:3,icsRoundtrip:lines,...extra});
  const show=async(data,year=2026)=>{load(data);T.zustand().planer.jahr=year;await T.wechsel("planer");await settle();};
  const cell=date=>document.querySelector('[data-fokus="planer-tag:'+date+'"]');
  const query=async(record,from,through)=>{
    const before=JSON.stringify(record),start=performance.now();gaps=[];last=start;
    T.icsRuntime("expand",record,[Date.parse(from),Date.parse(through),false,true]);
    assert(pending()&&!T.icsRuntime.state.progress.hidden,"Missing pending/progress state");
    await settle();
    const result=T.icsRuntime("expand",record,[Date.parse(from),Date.parse(through),false,true]);
    assert(result,"Calendar expansion failed: "+T.icsRuntime.lastError);
    equal(JSON.stringify(record),before,"Worker changed recurrence/alarm data");
    send({probe:"worker",id:record.id,elapsedMs:performance.now()-start,maxHeartbeatMs:Math.max(0,...gaps)});
    return result;
  };
  try{
    load({});document.querySelector("#deckel").click();await wait(1600);
    const ordinary=[item("ordinary-single",["DTSTART:20260912T090000Z","DTEND:20260912T100000Z"],{datum:"2026-09-12",zeit:"09:00"}),
      item("ordinary-fortnight",["DTSTART:19980101T120000Z","DURATION:PT1H","RRULE:FREQ=WEEKLY;INTERVAL=2"],{datum:"1998-01-01",zeit:"12:00"}),
      item("ordinary-dense",["DTSTART;TZID=Europe/Berlin:19980101T090000","DURATION:PT1S","RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=400000"],{datum:"1998-01-01",zeit:"09:00"})];
    const special={termine:ordinary,jahrestage:[{id:"birthday",name:"Birthday search marker",datum:"1998-09-12",typ:"birthday"},
      {id:"leap-birthday",name:"Unknown year birthday",datum:"--02-29",typ:"birthday"}],
      feiertage:[{id:"public",von:"2026-01-01",bis:"2026-01-01",name:"Public holiday search marker",art:"public-holiday"},
        {id:"school",von:"2026-07-01",bis:"2026-07-03",name:"School holiday search marker",art:"school-holiday"}]};
    let before=requests.length;await show(special);
    assert(!document.querySelector(".mm-tag.hat")&&document.querySelectorAll(".mini-monat").length===12,"Normal year is not appointment-free/complete");
    assert(cell("2026-09-12").classList.contains("jt")&&cell("2026-02-28").classList.contains("jt"),"Birthday markers missing");
    assert(cell("2026-01-01").classList.contains("feiertag")&&cell("2026-07-02").classList.contains("ferien"),"Holiday markers missing");
    equal(requests.length,before,"Normal year queued ordinary ICS work");passed.push("normal-scope-and-special-marks");
    const normalized=JSON.stringify(T.daten());
    assert(T.suchTrefferFuer("planer",["ordinary"]).length===0,"Planner search includes ordinary appointments");
    assert(T.suchTrefferFuer("planer",["birthday"]).length>0&&T.suchTrefferFuer("planer",["holiday"]).length>0,"Planner search lost special days");
    T.planerKalenderModell(2026);equal(requests.length,before,"Planner search/year export queued ordinary work");
    equal(JSON.stringify(T.daten()),normalized,"Normal Planner changed stored data");passed.push("search-and-year-export-scope");
    T.daten().einstellungen.allgemein.tray.aktiv=true;T.daten().einstellungen.allgemein.tray.zaehler=true;
    document.querySelector('[data-fokus="planer:jahr-vor"]').click();await settle();
    equal(requests.length,before,"Planner redraw indirectly expanded ordinary data through tray counters");passed.push("tray-render-boundary");
    const imported=[item("holiday-newyear",["DTSTART;VALUE=DATE:20260101","DTEND;VALUE=DATE:20260102"],{sync:true,titel:"Neujahr",kategorien:"Public"}),
      item("holiday-school",["DTSTART;VALUE=DATE:20260701","DTEND;VALUE=DATE:20260704"],{sync:true,titel:"Sommerferien NRW",datum:"2026-07-01",endDatum:"2026-07-03"}),
      item("holiday-cancelled",["DTSTART;VALUE=DATE:20261225","DTEND;VALUE=DATE:20261226","STATUS:CANCELLED"],{sync:true,titel:"1. Weihnachtsfeiertag",kategorien:"Public",datum:"2026-12-25"})];
    before=requests.length;load({termine:[...ordinary,...imported]});
    assert(T.planerKalenderModell(2026).icsIncomplete,"Pending holiday year export looked complete");
    await T.wechsel("planer");await settle();
    assert(!T.planerKalenderModell(2026).icsIncomplete,"Completed holiday year export stayed pending");
    passed.push("holiday-year-export-pending");
    assert(requests.slice(before).every(job=>job.id.startsWith("holiday-")),"Holiday path expanded an ordinary appointment");
    assert(cell("2026-01-01").classList.contains("feiertag")&&cell("2026-01-01").title.includes("Neujahr"),"Imported holiday missing");
    for(const date of ["2026-07-01","2026-07-02","2026-07-03"])assert(cell(date).classList.contains("ferien"),"Imported school holiday span missing");
    assert(!cell("2026-07-04").classList.contains("ferien")&&!cell("2026-12-25").classList.contains("feiertag"),"Exclusive end/cancellation changed");
    passed.push("filtered-imported-holidays");
    const schoolSeries=item("holiday-series",["DTSTART;VALUE=DATE:19980701","DTEND;VALUE=DATE:19980704","RRULE:FREQ=YEARLY"],
      {sync:true,titel:"Sommerferien NRW",datum:"1998-07-01",endDatum:"1998-07-03"});
    before=requests.length;await show({termine:[...ordinary,schoolSeries]});
    assert(cell("2026-07-02").classList.contains("ferien"),"Actual recurring school holiday was lost");
    assert(requests.slice(before).every(job=>job.id==="holiday-series"),"Holiday recurrence expanded ordinary series");passed.push("holiday-recurrence-only");
    const publicSeries=item("holiday-public-series",["DTSTART;VALUE=DATE:19980101","DTEND;VALUE=DATE:19980102","RRULE:FREQ=YEARLY"],
      {sync:true,titel:"Neujahr",kategorien:"Public",datum:"1998-01-01"});
    before=requests.length;await show({termine:[...ordinary,publicSeries]});
    assert(cell("2026-01-01").classList.contains("feiertag")&&!document.querySelector(".mm-tag.hat"),"Imported recurring public holiday missing");
    assert(requests.slice(before).every(job=>job.id==="holiday-public-series"),"Public holiday path expanded ordinary data");passed.push("public-holiday-recurrence");
    const replacement={...schoolSeries,icsRangeOverrides:[["RECURRENCE-ID;VALUE=DATE;RANGE=THISANDFUTURE:20260701",
      "DTSTART;VALUE=DATE:20260701","DTEND;VALUE=DATE:20260704","SUMMARY:Ordinary replacement meeting"]]};
    await show({termine:[...ordinary,replacement]});
    assert(!cell("2026-07-02").classList.contains("ferien")&&!document.querySelector(".mm-tag.hat"),
      "Ordinary replacement of a holiday appeared in the normal Planner");passed.push("holiday-override-classification");
    const leaf=cell("2026-07-02");
    await query(ordinary[0],"2026-09-12T00:00:00Z","2026-09-12T23:59:59Z");
    assert(cell("2026-07-02")===leaf,"Unrelated ordinary reply rebuilt the normal Planner");passed.push("unrelated-reply-isolation");
    await show(special,2024);assert(cell("2024-02-29").classList.contains("jt"),"Leap birthday missing");
    const edge=cell("2024-12-31");edge.focus();edge.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true,cancelable:true}));
    await settle();assert(document.activeElement.dataset.fokus==="planer-tag:2025-01-01","Year-crossing focus lost");
    await T.wechsel("notizen");await T.wechsel("planer");await T.wechsel("adressen");await wait(200);
    assert(T.zustand().sektion==="adressen"&&!document.querySelector(".planer-raster"),"Late half-year stole navigation");passed.push("focus-and-cancelled-render");
    // Calendar and explicitly chosen monthly export retain ordinary appointments.
    const daily=item("calendar-daily",["DTSTART:20260901T100000Z","DURATION:PT1H","RRULE:FREQ=DAILY;COUNT=3"],{datum:"2026-09-01",zeit:"10:00"});
    load({termine:[daily]});
    T.termineAm("2026-09-02",true);await settle();
    assert(T.termineAm("2026-09-02",true).some(value=>value.id===daily.id),"Calendar lost an ordinary recurrence");
    T.planerMonatsModell(2026,8);await settle();
    const monthly=T.planerMonatsModell(2026,8);
    equal(monthly.wochen.flatMap(week=>week.tage).flatMap(day=>day.eintraege).filter(entry=>entry.art==="termin").length,3,"Explicit month export lost ordinary appointments");
    assert(!monthly.icsIncomplete,"Completed monthly export is still pending");passed.push("calendar-and-month-export");
    await T.wechsel("planer");await settle();cell("2026-09-02").click();await settle();
    assert(T.zustand().sektion==="kalender"&&T.zustand().kalender.tag==="2026-09-02","Planner day click no longer opens the calendar date");passed.push("day-click-calendar");
    load({termine:[item("calendar-index",["DTSTART:20260912T100000Z","DURATION:PT1H"])]});
    let readyIds=[];document.addEventListener("magnolie-recurrence-ready",()=>{readyIds=T.termineAm("2026-09-12",true).map(value=>value.id);},{once:true});
    T.termineAm("2026-09-12",true);await settle();
    assert(readyIds.includes("calendar-index"),"Ready-event reader saw a stale pending base index");passed.push("index-ready-event");
    const counted=item("calendar-counted",["DTSTART;TZID=Europe/Berlin:20210301T090000","DURATION:PT1S","RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=400000"]);
    const values=await query(counted,"2026-09-07T07:00:00Z","2026-09-07T07:20:00Z");
    equal(values.map(value=>new Date(value.icsStartUtc).toISOString()),["2026-09-07T07:00:00.000Z","2026-09-07T07:10:00.000Z","2026-09-07T07:20:00.000Z"],"Counted calendar recurrence changed");
    assert(Math.max(0,...gaps)<=100,"Dense calendar work blocked JS heartbeat");passed.push("dense-calendar-worker");
    load({termine:[item("holiday-last-year",[],{datum:"9999-12-31",endDatum:"9999-12-31",sync:true,titel:"Neujahr",kategorien:"Public"})]});
    assert(T.planerKalenderModell(9999).zeilen[30][11].feiertage.length===1,"Holiday indexing did not stop at the requested year boundary");
    passed.push("bounded-holiday-year-index");
    const boundary=[
      item("batch-utc",["DTSTART:20260831T233000Z","DTEND:20260901T003000Z"]),
      item("batch-cancelled",["DTSTART:20260901T090000Z","DURATION:PT1H","STATUS:CANCELLED"]),
      item("batch-excluded",["DTSTART:20260901T100000Z","DURATION:PT1H","EXDATE:20260901T100000Z"]),
      item("month-midnight",["DTSTART;TZID=Europe/Berlin:20260831T230000","DTEND;TZID=Europe/Berlin:20260901T000000","RRULE:FREQ=DAILY;COUNT=3"]),
      item("month-span",["DTSTART;VALUE=DATE:20260831","DTEND;VALUE=DATE:20260903","RRULE:FREQ=WEEKLY;COUNT=2"]),
      item("month-zero",["DTSTART:20260901T000000Z","DTEND:20260901T000000Z","RRULE:FREQ=DAILY;COUNT=2"])
    ];
    load({termine:boundary});T.planerMonatsModell(2026,8);await settle();
    const bounded=T.planerMonatsModell(2026,8);
    for(const date of ["2026-09-01","2026-09-02","2026-09-03","2026-09-08"]){
      T.termineAm(date,true);await settle();
      const day=bounded.wochen.flatMap(w=>w.tage).find(d=>d.iso===date);
      equal(day.eintraege.filter(e=>e.art==="termin").map(e=>e.text.split(" ").at(-1)).sort(),
        T.termineAm(date,true).map(t=>t.titel).sort(),"Month range differs from calendar overlap/exclusive end: "+date);
    }
    const first=bounded.wochen.flatMap(w=>w.tage).find(d=>d.iso==="2026-09-01").eintraege;
    assert(first.some(e=>e.text.includes("batch-utc"))&&!first.some(e=>/batch-(cancelled|excluded)/.test(e.text)),
      "Batched base index lost timezone/cancellation/EXDATE semantics");
    passed.push("batched-base-and-month-boundaries");
    load({termine:[boundary[0],item("batch-invalid-zone",["DTSTART;TZID=Unresolvable/Fixture:20260901T090000","DURATION:PT1H"])]});
    T.termineAm("2026-09-01",true);await settle();
    assert(T.termineAm("2026-09-01",true).some(t=>t.id==="batch-utc"),"One invalid source hid valid base appointments");
    assert(T.planerMonatsModell(2026,8).icsIncomplete,"Invalid base source allowed a complete-looking export");
    passed.push("batch-error-isolation");
    const savedWorker=window.Worker;
    try{
      window.Worker=undefined;
      load({termine:[{...boundary[0],id:"fallback-valid"},item("fallback-invalid",["DTSTART;TZID=Unresolvable/Fixture:20260901T090000","DURATION:PT1H"])]});
      assert(T.termineAm("2026-09-01",true).some(t=>t.id==="fallback-valid"),"Workerless batch hid a valid appointment");
      assert(T.planerMonatsModell(2026,8).icsIncomplete,"Workerless invalid batch looked complete");
    }finally{window.Worker=savedWorker;}
    passed.push("workerless-batch-error-isolation");
    send({probe:"done",ok:true,tests:passed.length,passed,ticks,requests:requests.length});
  }catch(error){send({probe:"failure",error:String(error)+"\n"+String(error.stack||""),passed,ticks});}
})();
