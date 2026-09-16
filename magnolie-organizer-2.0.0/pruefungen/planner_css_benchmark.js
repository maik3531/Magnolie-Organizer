/* Diagnostic only: original book CSS, static synthetic DOM, no App or workers. */
"use strict";
(async () => {
  const send = value => window.webkit.messageHandlers.planner_probe.postMessage(JSON.stringify(value));
  const wait = ms => new Promise(resolve => setTimeout(resolve,ms));
  if (window.App || window.OrganizerTest) throw new Error("Application code must not be loaded in the CSS benchmark");
  const book = document.querySelector("#buch"), pages = document.querySelector("#seiten");
  book.className="offen"; book.dataset.registerAnzahl="7";
  document.querySelector("#deckel").classList.add("weg");
  document.querySelector("#kopf-links").innerHTML="<h2>September 2026</h2>";
  document.querySelector("#kopf-rechts").innerHTML="<h2>Appointment overview</h2>";
  const left = document.querySelector("#inhalt-links"), right = document.querySelector("#inhalt-rechts");
  left.classList.add("randlos");
  left.innerHTML='<div class="kal-huelle"><div class="kal-wochentage">'+
    ["M","D","M","D","F","S","S"].map(day=>'<span class="kal-wt">'+day+'</span>').join("")+
    '</div><div class="monatsraster">'+Array.from({length:42},(_,index)=>
      '<div class="kal-tag"><div class="kal-tag-kopf"><span class="nr">'+(index%31+1)+
      '</span></div><button class="mini mini-termin"><b>12:00</b> Synthetic complete appointment</button></div>').join("")+'</div></div>';
  right.innerHTML='<div class="termin-uebersicht">'+Array.from({length:30},(_,index)=>
    '<div class="ue-tag"><button class="ue-datum"><span class="ue-zahl">'+(index+1)+
    '</span><span class="ue-wt">Monday</span><span class="ue-monat">September</span></button>'+
    '<button class="ue-termin"><span class="ue-zeit">12:00-13:00</span><span class="ue-titel">Synthetic complete appointment</span></button></div>').join("")+'</div>';
  const width = book.getBoundingClientRect().width;
  const frames=[], ticks=[], samples=[];
  let lastFrame=performance.now(), lastTick=performance.now();
  const frame=now=>{frames.push(now-lastFrame);lastFrame=now;requestAnimationFrame(frame);};
  requestAnimationFrame(frame);
  setInterval(()=>{const now=performance.now();ticks.push(now-lastTick);lastTick=now;},10);
  const stats=values=>{ const sorted=values.slice().sort((a,b)=>a-b); return {
    n:sorted.length,max:sorted.at(-1)||0,p95:sorted[Math.floor(sorted.length*.95)]||0}; };
  await wait(1200);
  for (const mode of ["animation-only","layout-only","layout-and-animation"]) {
    for (let cycle=0;cycle<5;cycle++) {
      pages.classList.remove("blaettern-vor"); await wait(300);
      frames.length=0;ticks.length=0;
      const start=performance.now();lastFrame=start;lastTick=start;
      const name="css-"+mode+"-"+cycle;
      send({probe:"start",name});
      if (mode!=="animation-only") book.style.width=(width-(cycle%2))+"px";
      const layoutStart=performance.now();void pages.offsetWidth;
      const layoutMs=performance.now()-layoutStart;
      if (mode!=="layout-only") pages.classList.add("blaettern-vor");
      const inputDispatchMs=performance.now()-start;
      let firstRafMs,secondRafMs;
      requestAnimationFrame(()=>{firstRafMs=performance.now()-start;
        requestAnimationFrame(()=>secondRafMs=performance.now()-start);});
      await wait(700);
      const sample={probe:"sample",name,layoutMs,inputDispatchMs,firstRafMs,secondRafMs,
        elapsedMs:performance.now()-start,frames:stats(frames),heartbeat:stats(ticks),
        applicationLoaded:false,workers:0};
      samples.push(sample);send(sample);
    }
  }
  send({probe:"done",ok:true,diagnosticOnly:true,samples:samples.length,
    stutter:samples.filter(s=>s.frames.max>100||s.heartbeat.max>100).map(s=>s.name)});
})();
