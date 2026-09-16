/* Archived pre-clarification ordinary-appointment Planner expectations. */
"use strict";
(async () => {
  const send = value => window.webkit.messageHandlers.planner_probe.postMessage(JSON.stringify(value));
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const assert = (value, text) => { if (!value) throw new Error(text); };
  const equal = (a,b,text) => assert(JSON.stringify(a)===JSON.stringify(b), text+": "+JSON.stringify(a));
  let tests = 0, ticks = 0, lastTick = performance.now();
  const tickGaps = [], workerMeasurements = [];
  setInterval(()=>{ const now=performance.now(); tickGaps.push(now-lastTick); lastTick=now; ticks++; },10);
  try {
    App.init({daten:{einstellungen:{allgemein:{handbuchHinweisGezeigt:true}}},neu:false,
      handbuchInstalliert:true,handbuchVersion:"2.0.18",regional:{language:"de",timeZone:"Europe/Berlin"}});
    const T = OrganizerTest;
    document.querySelector("#deckel").click(); await wait(1600);
    assert(document.querySelector("#deckel").classList.contains("weg"),"Book did not open");
    await T.wechsel("notizen");
    await wait(600);
    const query = async (item, year) => {
      const saved = JSON.stringify(item), before = ticks, started = performance.now();
      tickGaps.length=0; lastTick=started;
      T.icsRuntime("planner",item,[year]);
      assert(T.icsRuntime.state.progress && !T.icsRuntime.state.progress.hidden,"Missing visible worker progress");
      const deadline = performance.now()+60000;
      while ([...T.icsRuntime.state.jobs.values()].some(v=>v.status==="pending")) {
        assert(performance.now()<deadline,"Worker deadline"); await wait(20);
      }
      const result = T.icsRuntime("planner",item,[year]);
      assert(result, "Planner worker failed: "+T.icsRuntime.lastError);
      assert(ticks>before, "Main-loop heartbeat stopped while worker was running");
      const maxHeartbeatMs = Math.max(0,...tickGaps);
      workerMeasurements.push({id:item.id,year,elapsedMs:performance.now()-started,maxHeartbeatMs});
      if (item.id==="dense") assert(maxHeartbeatMs<=100,"Dense recurrence blocked the main loop: "+maxHeartbeatMs);
      equal(JSON.stringify(item),saved,"Worker changed source text/alarms");
      tests++;
      return result.map(v=>v.datum);
    };
    const item = (id, lines, extra={}) => ({id,uid:id,datum:"1998-01-01",titel:id,
      notiz:"Full original text\nSecond line",standardErinnerung:true,individuelleErinnerungTage:3,
      icsRoundtrip:lines,...extra});
    equal(await query(item("year-boundary",["DTSTART;VALUE=DATE:20251231","DTEND;VALUE=DATE:20260103",
      "RRULE:FREQ=YEARLY;COUNT=1"]),2026),["2026-01-01","2026-01-02"],"Exclusive all-day end/year overlap");
    equal(await query(item("midnight",["DTSTART;TZID=Europe/Berlin:20260101T230000",
      "DTEND;TZID=Europe/Berlin:20260102T000000","RRULE:FREQ=YEARLY;COUNT=1"]),2026),["2026-01-01"],"Midnight does not mark next day");
    equal(await query(item("dst",["DTSTART;TZID=Europe/Berlin:20260328T230000","DURATION:PT3H",
      "RRULE:FREQ=DAILY;COUNT=3","EXDATE;TZID=Europe/Berlin:20260329T230000"]),2026),
      ["2026-03-28","2026-03-29","2026-03-30","2026-03-31"],"DST overlap/exclusion");
    equal(await query(item("period",["DTSTART:20260101T120000Z","DURATION:PT1H",
      "RDATE;VALUE=PERIOD:20260831T210000Z/PT4H","EXDATE:20260101T120000Z"]),2026),
      ["2026-08-31","2026-09-01"],"RDATE period overlap");
    const daily = item("old-daily",["DTSTART:19980101T120000Z","DURATION:PT1H","RRULE:FREQ=DAILY"]);
    const leap = await query(daily,2024);
    assert(leap.length===366 && leap.includes("2024-02-29"),"Leap year incomplete");
    const history = await query(daily,1998);
    assert(history.length===365 && history[0]==="1998-01-01", "Old history omitted");
    const dense = item("dense",["DTSTART:19980101T120000Z","DURATION:PT1S","RRULE:FREQ=MINUTELY;INTERVAL=5"]);
    const denseDays = await query(dense,2026);
    assert(denseDays.length===365,"Day-bounded dense series was truncated by a year-sized output limit");
    const counted = item("counted-history",["DTSTART;TZID=Europe/Berlin:20210301T090000",
      "DURATION:PT1S","RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=400000"]);
    const interval = [Date.parse("2026-09-07T07:00:00Z"),Date.parse("2026-09-07T07:20:00Z")];
    const countedStart=performance.now();tickGaps.length=0;lastTick=countedStart;
    T.icsRuntime("expand",counted,interval);
    while ([...T.icsRuntime.state.jobs.values()].some(v=>v.status==="pending")) {
      assert(performance.now()-countedStart<90000,"Counted recurrence deadline");await wait(20);
    }
    equal(T.icsRuntime("expand",counted,interval)?.map(v=>new Date(v.icsStartUtc).toISOString()),
      ["2026-09-07T07:00:00.000Z","2026-09-07T07:10:00.000Z","2026-09-07T07:20:00.000Z"],
      "Counted historical recurrence changed");
    const countedHeartbeat=Math.max(0,...tickGaps);
    assert(countedHeartbeat<=100,"Counted recurrence blocked main loop: "+countedHeartbeat);
    workerMeasurements.push({id:counted.id,elapsedMs:performance.now()-countedStart,maxHeartbeatMs:countedHeartbeat});
    tests++;

    const markerDays = () => [...document.querySelectorAll('.mm-tag.hat')].map(v=>v.dataset.fokus.split(":")[1]).sort();
    const settle = async () => {
      const deadline=performance.now()+20000;
      do {
        await wait(100);
        assert(performance.now()<deadline,"UI did not settle");
      } while ([...T.icsRuntime.state.jobs.values()].some(v=>v.status==="pending") || T.icsRuntime.state.paint ||
        document.querySelector('.planer-raster[aria-busy="true"],.kalender-uebersicht-laedt'));
    };
    const show = async (termine, year, hide=false) => {
      App.init({daten:{termine,einstellungen:{allgemein:{handbuchHinweisGezeigt:true},kalender:{vergangeneTermine:hide}}},neu:false,
        regional:{language:"de",timeZone:"Europe/Berlin"}});
      T.zustand().planer.jahr=year;
      await T.wechsel("notizen");
      document.querySelector('[data-fokus="register:planer"]').click();
      await settle(); tests++;
      return markerDays();
    };
    const holiday = item("holiday",["DTSTART;VALUE=DATE:20260701","DTEND;VALUE=DATE:20260703",
      "RRULE:FREQ=YEARLY"],{sync:true,titel:"Sommerferien NRW"});
    equal(await show([holiday],2026),[],"Synced school holiday became an appointment marker");
    const changedHoliday = {...holiday,icsRangeOverrides:[["RECURRENCE-ID;VALUE=DATE;RANGE=THISANDFUTURE:20260701",
      "DTSTART;VALUE=DATE:20260701","DTEND;VALUE=DATE:20260703","SUMMARY:Full replacement meeting"]]};
    equal(await show([changedHoliday],2026),["2026-07-01","2026-07-02"],"Override title/filter semantics lost");
    await show([item("oneoff-holiday",["DTSTART;VALUE=DATE:20260101","DTEND;VALUE=DATE:20260102"],
      {datum:"2026-01-01",sync:true,titel:"Neujahr",kategorien:"Public"})],2026);
    const holidayCell = document.querySelector('[data-fokus="planer-tag:2026-01-01"]');
    assert(holidayCell.classList.contains("feiertag") && holidayCell.title.includes("Neujahr"),
      "Pending imported holiday did not refresh color and tooltip");
    const mixed = [item("local",[],{datum:"2026-06-01",endDatum:"2026-06-03"}),
      item("local-repeat",[],{datum:"2026-01-01",wiederholung:{art:"custom",daten:["2026-06-10"]}})];
    equal(await show(mixed,2026),["2026-01-01","2026-06-01","2026-06-02","2026-06-03","2026-06-10"],"Local recurrence/multi-day markers changed");
    equal(await show([daily],1998,true),[],"Past filter ignored");
    assert((await show([daily],1998,false)).length===365,"Past data lost when filter toggled");

    const before = JSON.stringify(T.daten().termine);
    T.zustand().planer.jahr=2027;
    await T.wechsel("kalender");
    document.querySelector('[data-fokus="register:planer"]').click();
    await T.wechsel("notizen");
    await settle();
    assert(T.zustand().sektion==="notizen" && !document.querySelector('.planer-raster'),"Late worker result reopened Planner");
    equal(JSON.stringify(T.daten().termine),before,"Navigation changed full source data");
    tests++;
    await T.wechsel("planer"); await settle();
    assert(markerDays().length===365 && document.querySelectorAll(".mini-monat").length===12,
      "Cancelled half-year did not render on return");
    await T.wechsel("notizen"); T.zustand().planer.jahr=2028;
    await T.wechsel("planer");
    document.querySelector('[data-fokus="planer:jahr-vor"]').click();
    await settle();
    assert(T.zustand().planer.jahr===2029 && markerDays().length===365 &&
      [...document.querySelectorAll('[data-fokus^="planer-tag:"]')].every(v=>v.dataset.fokus.startsWith("planer-tag:2029-")),
      "Stale half-year survived a year change");
    tests++;
    const lastDay = document.querySelector('[data-fokus="planer-tag:2029-12-31"]');
    lastDay.focus(); lastDay.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true,cancelable:true}));
    await settle();
    assert(document.activeElement.dataset.fokus==="planer-tag:2030-01-01" &&
      document.querySelectorAll('[data-fokus^="planer-tag:"][tabindex="0"]').length===1,
      "Asynchronous year change lost the roving keyboard focus");
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{key:"PageDown",shiftKey:true,bubbles:true,cancelable:true}));
    const yearButton = document.querySelector('[data-fokus="planer:jahr-waehlen"]'); yearButton.focus();
    await settle();
    assert(document.activeElement===yearButton,"Delayed rendering stole focus from another control");
    tests++;
    const singles = [item("pending-one",["DTSTART:20260912T100000Z","DTEND:20260912T110000Z"]),
      item("pending-two",["DTSTART:20260913T100000Z","DTEND:20260913T110000Z"])];
    App.init({daten:{termine:singles,einstellungen:{allgemein:{handbuchHinweisGezeigt:true}}},neu:false,
      regional:{language:"de",timeZone:"Europe/Berlin"}});
    let readyIds = [];
    document.addEventListener("magnolie-recurrence-ready", () => {
      readyIds = [...T.termineAm("2026-09-12",true),...T.termineAm("2026-09-13",true)].map(v=>v.id);
    },{once:true});
    T.termineAm("2026-09-12",true); T.termineAm("2026-09-13",true);
    await settle();
    assert(readyIds.includes("pending-one") && readyIds.includes("pending-two"),
      "Ready-event readers observed a stale pending index before the repaint");
    assert(T.termineAm("2026-09-12",true).some(v=>v.id==="pending-one"),"Pending index lost first imported one-off");
    assert(T.termineAm("2026-09-13",true).some(v=>v.id==="pending-two"),"Pending index lost second imported one-off");
    T.daten().termine.find(v=>v.id==="pending-two").icsRoundtrip = ["DTSTART:20260914T100000Z","DTEND:20260914T110000Z"];
    T.planeSpeichern(); T.termineAm("2026-09-14",true);
    await settle();
    assert(!T.termineAm("2026-09-13",true).some(v=>v.id==="pending-two") &&
      T.termineAm("2026-09-14",true).some(v=>v.id==="pending-two"),"Worker reply did not refresh invalidated index");
    tests++;
    await T.wechsel("notizen"); await wait(600);
    const zoned = item("interleaved-zones",["DTSTART:20251231T233000Z","DURATION:PT15M","RRULE:FREQ=YEARLY;COUNT=1"]);
    T.icsRuntime("planner",zoned,[2026]);
    T.daten().einstellungen.regional.timeZone="UTC";
    T.icsRuntime("planner",zoned,[2026]);
    await settle();
    equal(T.icsRuntime("planner",zoned,[2026]).map(v=>v.datum),[],"UTC job used another job's timezone");
    T.daten().einstellungen.regional.timeZone="Europe/Berlin";
    equal(T.icsRuntime("planner",zoned,[2026]).map(v=>v.datum),["2026-01-01"],"Yielding job lost its timezone");
    tests++;
    send({probe:"done",ok:true,tests,ticks,workerMeasurements});
  } catch(error) { send({probe:"failure",error:String(error)+"\n"+String(error.stack || ""),tests,ticks}); }
})();
