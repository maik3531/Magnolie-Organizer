/* Archived pre-clarification fixture and expectations; not the normal Planner contract. */
"use strict";
(async () => {
  const options = window.plannerProbeOptions;
  if (options.grid_control) {
    const style = document.createElement("style");
    style.textContent = ".planer-raster { grid-template-columns:repeat(2,minmax(0,1fr)); grid-auto-rows:minmax(0,1fr); } .mm-raster {grid-template-columns:repeat(7,minmax(0,1fr));} .mini-monat {min-width:0;}";
    document.head.append(style);
  }
  if (options.paint_containment) {
    const style=document.createElement("style");
    style.textContent=options.paint_containment==="always" ? ".seite{contain:paint;}" :
      "#seiten.blaettern-vor .seite,#seiten.blaettern-zurueck .seite{contain:paint;}";
    document.head.append(style);
  }
  if (options.page_layers) {
    const style=document.createElement("style");
    style.textContent=".seite{will-change:transform,opacity;}";
    document.head.append(style);
  }
  const send = value => window.webkit.messageHandlers.planner_probe.postMessage(JSON.stringify(value));
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const assert = (value, text) => { if (!value) throw new Error(text); };
  const samples = [], frames = [], ticks = [], jobs = new Map();
  let inputTimes = [];
  let activity = [], timerIntervals = [];
  document.addEventListener("click", event => {
    if (event.isTrusted) { const time=performance.now(); inputTimes.push(time); activity.push({kind:"input",time}); }
  }, true);
  let expectedSection = null;
  let slowestFrameCallback = {ms:0, source:""};
  let slowestTaskCallback = {ms:0, source:""};
  // Acceptance runs sample the loop without wrapping application callbacks.
  for (const method of options.profile ? ["setTimeout","setInterval"] : []) {
    const native = window[method].bind(window);
    window[method] = (callback,delay,...args) => typeof callback !== "function" ? native(callback,delay,...args) :
      native(function(...values) {
        const start=performance.now();
        try { return callback.apply(this,values); } finally {
          const ms=performance.now()-start;
          if (ms>slowestTaskCallback.ms) slowestTaskCallback={ms,source:callback.toString().slice(0,240)};
        }
      },delay,...args);
  }
  const nativeFrame = window.requestAnimationFrame.bind(window);
  if (options.profile) window.requestAnimationFrame = callback => nativeFrame(timestamp => {
    const start = performance.now();
    try { return callback(timestamp); } finally {
      const ms = performance.now()-start;
      if (ms>slowestFrameCallback.ms) slowestFrameCallback = {ms,source:callback.toString().slice(0,240)};
    }
  });
  let posts = 0, replies = 0, cancelledJobs = 0, renders = 0, changed = performance.now();
  let lastTick = performance.now(), lastFrame;
  setInterval(() => { const now = performance.now(); ticks.push(now-lastTick);
    timerIntervals.push({start:lastTick,end:now}); activity.push({kind:"timer",time:now}); lastTick=now; },10);
  const frame = now => { if (lastFrame !== undefined) frames.push(now-lastFrame);
    activity.push({kind:"raf",time:performance.now()}); lastFrame=now; nativeFrame(frame); };
  nativeFrame(frame);
  const NativeWorker = Worker;
  window.Worker = class extends NativeWorker {
    constructor(...args) { super(...args); this.addEventListener("message", event => { if (!event.data.cancelled) replies++; }); }
    postMessage(data, ...args) {
      if (data.mode==="cancel-planner") cancelledJobs+=data.keys.length;
      else { posts++; jobs.set(data.key, (jobs.get(data.key) || 0) + 1); }
      super.postMessage(data,...args);
    }
  };
  new MutationObserver(() => { renders++; changed = performance.now(); })
    .observe(document.querySelector("#inhalt-links"), {childList:true});
  const stats = values => {
    const sorted = values.slice().sort((a,b) => a-b);
    return {n:sorted.length, p95:sorted[Math.floor(sorted.length*.95)] || 0,
      max:sorted[sorted.length-1] || 0, over50:sorted.filter(v => v>50).length};
  };
  const status = () => ({posts, replies, cancelledJobs, duplicatePosts:posts-jobs.size, renders,
    pending:[...(OrganizerTest.icsRuntime.state?.jobs.values() || [])].filter(v=>v.status==="pending").length,
    recurrenceError:OrganizerTest.icsRuntime.lastError, profile:window.plannerProfile,
    slowestFrameCallback,slowestTaskCallback});
  const settle = async () => {
    const start = performance.now();
    while (performance.now()-start < 12000) {
      await wait(50);
      if (!status().pending && !OrganizerTest.icsRuntime.state?.paint &&
        !document.querySelector('.planer-raster[aria-busy="true"],.kalender-uebersicht-laedt') && performance.now()-changed > 150) return;
    }
    throw new Error("Render did not settle in 12 seconds");
  };
  const measure = async (name, action) => {
    frames.length = 0; ticks.length = 0;
    slowestFrameCallback = {ms:0, source:""};
    slowestTaskCallback = {ms:0, source:""}; inputTimes=[];
    activity=[];timerIntervals=[];
    expectedSection = null;
    const before = status(), start = performance.now();
    lastFrame = start; lastTick = start;
    send({probe:"start", name});
    await action();
    const inputDispatchMs = performance.now()-start;
    let firstRafMs, secondRafMs;
    nativeFrame(() => { firstRafMs = performance.now()-start;
      nativeFrame(() => { secondRafMs = performance.now()-start; }); });
    await settle();
    await wait(200);
    while (document.getAnimations().some(a => a.playState === "running" &&
      a.effect.getTiming().iterations !== Infinity)) await wait(20);
    if (expectedSection) assert(OrganizerTest.zustand().sektion===expectedSection,"Navigation did not reach "+expectedSection);
    const end=performance.now(), times=[start,...activity.map(event=>event.time),end];
    const maxJsActivityGapMs=Math.max(...times.slice(1).map((time,index)=>time-times[index]));
    const longTimerGaps=timerIntervals.filter(gap=>gap.end-gap.start>100).map(gap=>({
      startMs:gap.start-start,endMs:gap.end-start,gapMs:gap.end-gap.start,
      callbacksInside:activity.filter(event=>event.kind!=="timer" && event.time>gap.start && event.time<gap.end)
        .map(event=>({kind:event.kind,atMs:event.time-start}))}));
    const sample = {probe:"sample", name, inputDispatchMs, firstRafMs, secondRafMs, elapsedMs:end-start,
      maxJsActivityGapMs,longTimerGaps,
      inputEventMs:inputTimes.map(time=>time-start),
      firstRafAfterInputMs:inputTimes.length ? firstRafMs-(inputTimes[0]-start) : null,
      paintUpperBoundAfterInputMs:inputTimes.length ? secondRafMs-(inputTimes[0]-start) : null,
      frames:stats(frames), heartbeat:stats(ticks), newPosts:posts-before.posts,
      newRenders:renders-before.renders, ...status()};
    samples.push(sample); send(sample);
  };
  const click = selector => {
    const button = document.querySelector(selector); assert(button, "Missing " + selector);
    const rect = button.getBoundingClientRect(), x = rect.x+rect.width/2, y = rect.y+rect.height/2;
    assert(rect.width>0 && rect.height>0 && button.contains(document.elementFromPoint(x,y)),
      "Click target is covered or outside the viewport: "+selector);
    expectedSection = button.dataset.fokus?.startsWith("register:") ? button.dataset.fokus.slice(9) : expectedSection;
    return new Promise((resolve,reject) => {
      const timer = setTimeout(() => { document.removeEventListener("click",clicked);
        reject(new Error("Native click did not arrive: "+selector)); },3000);
      const clicked = event => {
        if (!event.target.closest(selector)) return;
        clearTimeout(timer); document.removeEventListener("click",clicked);
        if (!event.isTrusted) { reject(new Error("Untrusted input event")); return; }
        queueMicrotask(resolve);
      };
      document.addEventListener("click",clicked);
      send({probe:"native-click",selector,x,y});
    });
  };
  const snapshot = name => new Promise(resolve => {
    window.plannerSnapshotDone = resolve; send({probe:"snapshot", name});
  });
  try {
    const count = options.scenario === "empty" ? 0 : options.scenario === "large" ? 5000 : 80;
    const data = {termine:[], aufgaben:[], notizen:[], kontakte:[], jahrestage:[],
      einstellungen:{ansicht:"week",allgemein:{handbuchHinweisGezeigt:true},kalender:{vergangeneTermine:false}}};
    for (let i=0; i<count; i++) {
      const date = new Date(Date.UTC(1998 + i%29, i%12, 1+i%27)).toISOString().slice(0,10);
      data.termine.push({id:"history-"+i, datum:date, zeit:"09:00", endZeit:"10:00", titel:"Synthetic history "+i,
        notiz:"Complete synthetic detail "+i, standardErinnerung:true});
      if (i<100 && i%2===0) data.termine[data.termine.length-1].icsRoundtrip = [
        "DTSTART:"+date.replaceAll("-","")+"T090000Z", "DTEND:"+date.replaceAll("-","")+"T100000Z"];
    }
    if (count) {
      for (let i=0; i<4; i++) data.termine.push({id:"series-"+i, uid:"series-"+i, datum:"1998-01-01",
        zeit:"12:00", endZeit:"13:00", titel:"Synthetic recurring "+i, notiz:"Full recurring text "+i,
        standardErinnerung:true, icsRoundtrip:["DTSTART:19980101T120000Z", "DTEND:19980101T130000Z",
          "RRULE:FREQ="+["DAILY", "WEEKLY", "MONTHLY", "YEARLY"][i]]});
      for (let i=0;i<20;i++) {
        data.aufgaben.push({id:"task-"+i, titel:"Synthetic task "+i, faellig:"2026-09-12", erinnern:true});
        data.notizen.push({id:"note-"+i, titel:"Synthetic note "+i, text:"Complete text "+i});
        data.kontakte.push({id:"contact-"+i,vorname:"Synthetic",nachname:"Contact "+i});
        data.jahrestage.push({id:"anniversary-"+i, name:"Synthetic anniversary "+i, datum:"1998-09-12"});
      }
    }
    App.init({daten:data,neu:false,handbuchInstalliert:true,handbuchVersion:"2.0.18",regional:{language:"de",timeZone:"UTC"}});
    const T = OrganizerTest, z = T.zustand();
    z.planer.jahr = 2026;
    Object.assign(z.kalender, {jahr:2026, monat:8, tag:"2026-09-12"});
    await settle();
    await click("#deckel");
    await wait(1600); await settle();
    assert(document.querySelector("#deckel").classList.contains("weg"),"Book cover is not open");
    await snapshot("opened-book");
    const content = () => JSON.stringify([T.daten().termine,T.daten().aufgaben,T.daten().notizen,
      T.daten().kontakte,T.daten().jahrestage]);
    const original = content();
    if (options.paint_benchmark) {
      const overlay = document.createElement("div"), rectangle = document.createElement("div");
      Object.assign(overlay.style,{position:"fixed",inset:"0",background:"white",zIndex:"999999"});
      Object.assign(rectangle.style,{position:"absolute",left:"50px",top:"50px",background:"#decfa5",transformOrigin:"left center"});
      overlay.append(rectangle); document.body.append(overlay);
      await wait(1600);
      for (const size of [100,400,800]) {
        rectangle.style.width = size+"px"; rectangle.style.height = Math.round(size*.65)+"px";
        for (const [kind,from] of [["opacity",{opacity:.2}],
          ["affine",{transform:"scaleX(.5) skewY(3deg)",opacity:.2}],
          ["perspective",{transform:"perspective(1500px) rotateY(-62deg)",opacity:.2}]]) {
          for (let i=0;i<3;i++) {
            await measure("benchmark-"+kind+"-"+size+"-"+i,()=>rectangle.animate([from,
              {transform:"none",opacity:1}],{duration:420,easing:"ease-out"}));
            await wait(300);
          }
        }
      }
      overlay.remove();
      send({probe:"done",ok:true,diagnosticOnly:true,samples:samples.length});
      return;
    }
    if (options.paint_controls) {
      await click('[data-fokus="kalender-ansicht:month"]');
      await settle();
      await wait(1600);
      const animate = () => {
        const pages = document.querySelector("#seiten");
        pages.classList.remove("blaettern-vor"); void pages.offsetWidth;
        pages.classList.add("blaettern-vor");
        setTimeout(() => pages.classList.remove("blaettern-vor"), 480);
      };
      await measure("control-idle", () => {});
      for (let i=0;i<3;i++) { await measure("control-animation-svg-"+i, animate); await wait(600); }
      await snapshot("original-textures");
      for (const [property,value] of [["willChange","transform"],["contain","layout paint"],["isolation","isolate"]]) {
        const pages = [...document.querySelectorAll(".seite")];
        for (const page of pages) page.style[property] = value;
        await wait(600);
        for (let i=0;i<3;i++) { await measure("control-"+property+"-"+i,animate); await wait(600); }
        for (const page of pages) page.style[property] = "";
      }
      const cached = new Map();
      for (const selector of [".seite", "#schreibtisch", "#einband", ".deckel-vorn", ".deckel-rueck"]) {
        for (const node of document.querySelectorAll(selector)) {
          const background = getComputedStyle(node).backgroundImage;
          const match = background.match(/^url\("(.*?)"\)/);
          if (!match || !match[1].includes("feTurbulence")) continue;
          if (!cached.has(match[1])) {
            const image = new Image(); image.src = match[1]; await image.decode();
            const canvas = document.createElement("canvas");
            canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
            const ctx = canvas.getContext("2d"); ctx.drawImage(image,0,0);
            cached.set(match[1],canvas.toDataURL("image/png"));
          }
          node.style.backgroundImage = background.replace(match[0],'url("'+cached.get(match[1])+'")');
        }
        await wait(600);
        for (let i=0;i<3;i++) { await measure("control-cached-"+selector+"-"+i,animate); await wait(600); }
      }
      await snapshot("cached-textures");
      send({probe:"done",ok:true,diagnosticOnly:true,textures:cached.size,samples:samples.length});
      return;
    }
    await measure("idle", () => {});
    await measure("planner-first", () => click('[data-fokus="register:planer"]'));
    assert(document.querySelectorAll('[data-fokus^="planer-tag:"]').length === 365, "Missing Planner days");
    if (count) assert(document.querySelectorAll('.mm-tag.hat').length === 365, "Daily recurrence markers missing");
    await snapshot("planner-first");
    for (const mode of ["day", "week", "month"]) {
      await measure("calendar-"+mode, async () => {
        z.kalender.ansicht=mode; await click('[data-fokus="register:kalender"]');
        const switcher = document.querySelector('[data-fokus="kalender-ansicht:'+mode+'"]');
        if (switcher && !switcher.classList.contains("aktiv")) await click('[data-fokus="kalender-ansicht:'+mode+'"]');
      });
      if (mode==="month") {
        let expected=0;
        for (let day=1;day<=30;day++) expected+=T.termineAm("2026-09-"+String(day).padStart(2,"0")).length;
        assert(document.querySelectorAll(".ue-termin").length===expected,"Incomplete appointment overview after deferred rendering");
      }
      await measure("planner-from-"+mode, () => click('[data-fokus="register:planer"]'));
    }
    for (let cycle=0; cycle<options.cycles; cycle++) {
      for (const section of ["notizen", "aufgaben", "adressen", "jahrestage", "kalender", "planer"]) {
        await measure("cycle-"+cycle+"-"+section, () => click('[data-fokus="register:'+section+'"]'));
      }
    }
    assert(content() === original, "Navigation altered complete text/recurrence/alarm data");
    assert(!status().recurrenceError && posts===jobs.size, "Recurrence errors or duplicate job/render loop");
    const stutter = samples.filter(s=>s.frames.max>100 || s.heartbeat.max>100);
    send({probe:"done", ok:!options.gate || !stutter.length, stutter:stutter.map(s=>s.name),
      frameGatePassed:samples.every(s=>s.frames.max<=100),
      activityGatePassed:samples.every(s=>s.maxJsActivityGapMs<=100),
      samples:samples.length, ...status()});
  } catch (error) { send({probe:"failure", error:String(error)+"\n"+String(error.stack || ""), ...status(), frames:stats(frames), heartbeat:stats(ticks)}); }
})();
