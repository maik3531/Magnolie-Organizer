/* Normal yearly Planner: special-day marks, no ordinary appointment expansion.
   Trusted native clicks deliberately leave the Planner without waiting for it. */
"use strict";
(async () => {
  const options=window.plannerProbeOptions;
  const send=value=>window.webkit.messageHandlers.planner_probe.postMessage(JSON.stringify(value));
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const assert=(value,message)=>{if(!value)throw new Error(message);};
  const T=OrganizerTest, requests=[], samples=[], frames=[], ticks=[];
  let workers=0,maxPending=0;const inFlight=new Set();
  let lastFrame, lastTick=performance.now(), inputAt=0;
  const nativeFrame=requestAnimationFrame.bind(window);
  const frame=now=>{if(lastFrame!==undefined)frames.push(now-lastFrame);lastFrame=now;nativeFrame(frame);};
  nativeFrame(frame);
  setInterval(()=>{const now=performance.now();ticks.push(now-lastTick);lastTick=now;},10);
  document.addEventListener("click",event=>{if(event.isTrusted)inputAt=performance.now();},true);
  const NativeWorker=Worker;
  window.Worker=class extends NativeWorker {
    constructor(...args){super(...args);workers++;this.addEventListener("message",event=>inFlight.delete(event.data.key));}
    postMessage(data,...args){if(data.key){requests.push({key:data.key,id:data.mode==="base"?"ordinary-base":data.item?.id,mode:data.mode,
      recurrence:(data.item?.icsRoundtrip||[]).some(line=>/^(RRULE|RDATE|EXRULE)[;:]/i.test(line))});
      inFlight.add(data.key);maxPending=Math.max(maxPending,inFlight.size);}super.postMessage(data,...args);}
  };
  const status=()=>({requests:requests.length,ordinaryJobs:requests.filter(job=>job.id?.startsWith("ordinary-")).length,
    recurrenceJobs:requests.filter(job=>job.recurrence).length,
    duplicateJobs:requests.length-new Set(requests.map(job=>job.key)).size,
    pending:[...(T.icsRuntime?.state?.jobs.values()||[])].filter(job=>job.status==="pending").length,
    recurrenceError:T.icsRuntime?.lastError,workers,maxPending,cachedJobs:T.icsRuntime?.state?.jobs.size||0});
  const stats=values=>{const sorted=values.slice().sort((a,b)=>a-b);return{n:sorted.length,max:sorted.at(-1)||0,p95:sorted[Math.floor(sorted.length*.95)]||0};};
  const click=selector=>new Promise((resolve,reject)=>{
    const button=document.querySelector(selector);assert(button,"Missing "+selector);
    const rect=button.getBoundingClientRect(),x=rect.x+rect.width/2,y=rect.y+rect.height/2;
    assert(rect.width>0&&rect.height>0&&button.contains(document.elementFromPoint(x,y)),"Covered target "+selector);
    const timer=setTimeout(()=>{document.removeEventListener("click",done);reject(new Error("Native click timeout: "+selector));},3000);
    const done=event=>{if(!event.target.closest(selector))return;
      clearTimeout(timer);document.removeEventListener("click",done);
      if(!event.isTrusted){reject(new Error("Untrusted click"));return;}queueMicrotask(resolve);};
    document.addEventListener("click",done);send({probe:"native-click",selector,x,y});
  });
  const tab=async section=>{
    const started=performance.now();await click('[data-fokus="register:'+section+'"]');
    assert(T.zustand().sektion===section,"Tab did not activate: "+section);
    const responseMs=performance.now()-started,handlerMs=performance.now()-inputAt;
    send({probe:"tab-active",section,responseMs,handlerMs,...status()});
    if(!options.baseline){assert(responseMs<=options.tab_budget,"Tab activation exceeded "+options.tab_budget+" ms: "+section+" "+responseMs);
      assert(handlerMs<=100,"Click handler exceeded 100 ms: "+section);}
    return{section,responseMs,handlerMs};
  };
  const ready=async()=>{
    const deadline=performance.now()+12000;
    while(status().pending||T.icsRuntime?.state?.paint||document.querySelector('.planer-raster[aria-busy="true"]')){
      assert(performance.now()<deadline,"View did not complete in 12 seconds");await wait(20);
    }
  };
  const snapshot=name=>new Promise(resolve=>{window.plannerSnapshotDone=resolve;send({probe:"snapshot",name});});
  try {
    const count=options.scenario==="empty"?0:options.scenario==="large"?5000:80;
    const data={termine:[],notizen:[],kontakte:[],jahrestage:[],feiertage:[],urlaube:[],schichten:[],zyklusmarker:[],tagmarken:[],
      einstellungen:{ansicht:"week",allgemein:{handbuchHinweisGezeigt:true},kalender:{vergangeneTermine:false,
         schichtplanerAn:true,zykluskalenderAn:true,urlaubsplanerAn:true,muellkalenderAn:true}}};
    for(let i=0;i<count;i++){
      const date=new Date(Date.UTC(1998+i%29,i%12,1+i%27)).toISOString().slice(0,10);
      data.termine.push({id:"ordinary-history-"+i,uid:"ordinary-history-"+i,datum:date,zeit:"09:00",endZeit:"10:00",
        titel:"Ordinary history "+i,notiz:"Complete original history text\n"+i,standardErinnerung:true,sync:true,
        icsRoundtrip:["DTSTART:"+date.replaceAll("-","")+"T090000Z","DTEND:"+date.replaceAll("-","")+"T100000Z"]});
    }
    if(count){
      for(let i=0;i<17;i++)data.termine.push({id:"ordinary-fortnightly-"+i,uid:"ordinary-fortnightly-"+i,
        datum:"1998-01-01",zeit:"12:00",endZeit:"13:00",titel:"Ordinary fortnightly "+i,
        notiz:"Complete recurring text "+i,standardErinnerung:true,individuelleErinnerungTage:3,sync:true,
        icsRoundtrip:["DTSTART:19980101T120000Z","DURATION:PT1H","RRULE:FREQ=WEEKLY;INTERVAL=2"]});
      data.termine.push({id:"ordinary-dense",uid:"ordinary-dense",datum:"1998-01-01",zeit:"09:00",
        titel:"Ordinary dense counted history",notiz:"Must never be expanded by the normal Planner",standardErinnerung:true,sync:true,
        icsRoundtrip:["DTSTART;TZID=Europe/Berlin:19980101T090000","DURATION:PT1S","RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=400000"]});
      for(let i=0;i<20;i++){
        data.notizen.push({id:"note-"+i,titel:"Note "+i,text:"Complete note\n"+i});
        data.kontakte.push({id:"contact-"+i,vorname:"Synthetic",nachname:"Contact "+i});
      }
    }
    data.jahrestage=[{id:"birthday",name:"Birthday marker",datum:"1998-09-12",typ:"birthday"},
      {id:"unknown-year",name:"Unknown year birthday",datum:"--02-29",typ:"birthday"},
      {id:"anniversary",name:"Anniversary marker",datum:"2000-06-15",typ:"anniversary"}];
    data.feiertage=[{id:"public",von:"2026-01-01",bis:"2026-01-01",name:"Public holiday marker",art:"public-holiday"},
      {id:"school",von:"2026-07-01",bis:"2026-07-05",name:"School holiday marker",art:"school-holiday"}];
    data.urlaube=[{id:"vacation",von:"2026-08-01",bis:"2026-08-03",name:"Vacation marker",symbol:"palm"}];
    data.schichten=[{id:"shift",name:"Shift marker",von:"08:00",bis:"16:00",farbe:"#789abc"}];
    data.zyklusmarker=[{id:"cycle",name:"Cycle marker",symbol:"*",farbe:"#987abc"}];
    data.tagmarken=[{datum:"2026-09-15",schichtId:"shift",zyklusIds:["cycle"]}];
    data.muelltermine=[{id:"waste",von:"2026-09-05",name:"Waste <paper> & blue",intervallTage:14,farbe:"#3478ab",art:"custom"}];
    if(options.tier==="compatible"&&count){
      // Published 2.0.17 consumes native projections, not raw RFC recurrence rules.
      for(const record of data.termine.filter(record=>record.id.startsWith("ordinary-fortnightly-")))
        record.wiederholung={art:"weekly",intervall:2,bis:""};
      const dense=data.termine.find(record=>record.id==="ordinary-dense");
      const end=new Date(Date.UTC(1998,0,1)+399999*86400000).toISOString().slice(0,10);
      Object.assign(dense,{zeit:"09:00",endZeit:"09:01",wiederholung:{art:"daily",bis:end},
        icsRoundtrip:["DTSTART:19980101T090000Z","DURATION:PT1M","RRULE:FREQ=DAILY;COUNT=400000"]});
    }
    // A cold non-calendar entry profile isolates work started by the Planner itself.
    send({probe:"synthetic-profile",data});
    T.zustand().sektion="notizen";
    App.init({daten:data,neu:false,handbuchInstalliert:true,handbuchVersion:"2.0.18",regional:{language:"de",timeZone:"UTC"}});
    T.zustand().planer.jahr=2026;
    await click("#deckel");await wait(1600);
    assert(document.querySelector("#deckel").classList.contains("weg"),"Cover did not open");
    const content=()=>JSON.stringify(T.daten());
    const original=content();
    if(options.prints){await window.plannerPrintRegressions(data,{status,ready,send,wait,assert});return;}
    send({probe:"fixture",histories:count,fortnightly:count?17:0,dense:count?1:0,...status()});
    for(let cycle=0;cycle<Math.max(1,options.cycles);cycle++){
      for(const destination of ["notizen","adressen","aufgaben","jahrestage"]){
        frames.length=0;ticks.length=0;const start=performance.now();lastFrame=start;lastTick=start;
        const name="immediate-"+cycle+"-"+destination;send({probe:"start",name});
        const entered=await tab("planer");
        // Deliberately no settle, no RAF and no timeout between these two clicks.
        const left=await tab(destination);
        await wait(500);
        assert(T.zustand().sektion===destination,"Late render changed the active tab");
        assert(!document.querySelector(".planer-raster"),"Detached Planner work reappeared");
        const sample={probe:"sample",name,entered,left,inputDispatchMs:left.responseMs,
          elapsedMs:performance.now()-start,frames:stats(frames),heartbeat:stats(ticks),...status()};
        samples.push(sample);send(sample);
        if(!options.baseline)assert(status().requests===0,
          "Normal Planner queued ordinary appointment work");
      }
    }
    await tab("planer");await ready();
    assert(document.querySelectorAll('[data-fokus^="planer-tag:"]').length===365,"Incomplete year");
    const cell=date=>document.querySelector('[data-fokus="planer-tag:'+date+'"]');
    if(!options.baseline){
      assert(!document.querySelector(".mm-tag.hat"),"Ordinary appointment dots remain in yearly Planner");
      for(const [date,kind] of [["2026-09-12","jt"],["2026-02-28","jt"],["2026-06-15","jt"],
        ["2026-01-01","feiertag"],["2026-07-03","ferien"],["2026-08-02","urlaub"],
        ["2026-09-15","schicht"],["2026-09-15","zyklus"]])assert(cell(date).classList.contains(kind),"Missing "+kind+" "+date);
      assert(status().requests===0,"Final Planner started ordinary recurrence work");
    }
    assert(content()===original,"Navigation changed the stored synthetic payload");
    // Only the final evidence image waits for animation; the paired clicks above do not.
    await wait(500);
    await snapshot("normal-planner");
    send({probe:"normal-visible",days:document.querySelectorAll('[data-fokus^="planer-tag:"]').length,
      ordinaryDots:document.querySelectorAll('.mm-tag.hat').length,
      marks:[...document.querySelectorAll('[data-fokus^="planer-tag:"]')].filter(node=>
        /\b(jt|feiertag|ferien|urlaub|schicht|zyklus)\b/.test(node.className)).map(node=>({date:node.dataset.fokus,title:node.title,classes:node.className}))});
    const stutter=samples.filter(sample=>sample.frames.max>100||sample.heartbeat.max>100);
    send({probe:"done",ok:!options.gate||!stutter.length,samples:samples.length,stutter:stutter.map(sample=>sample.name),
      dataIdentity:true,
      maxTabActivationMs:Math.max(...samples.flatMap(sample=>[sample.entered.responseMs,sample.left.responseMs])),...status()});
  }catch(error){send({probe:"failure",error:String(error)+"\n"+String(error.stack||""),frames:stats(frames),heartbeat:stats(ticks),...status()});}
})();
