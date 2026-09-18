/* Test APK only: no activation, state assignment, perpetual observer or style reads in event callbacks. */
(() => {
  const ids = new WeakMap(); let next = 0, active = null, port = null;
  const documentId = crypto.randomUUID();
  const id = e => { if (!e) return 0; if (!ids.has(e)) ids.set(e, ++next); return ids.get(e); };
  const ring = new Array(256); let written = 0;
  const record = row => {ring[written++ % ring.length] = row;};
  const snapshot = () => ({documentId,written,capacity:ring.length,
    events:Array.from({length:Math.min(written,ring.length)},(_,i)=>ring[(Math.max(0,written-ring.length)+i)%ring.length])});
  window.__nativeDiagnosticSnapshot = snapshot;
  window.__nativeProbeTarget = id; // Generic field/picker preparation uses the same identity allocator.
  window.NativeTouchProbe = {
    connect(token, sourceHash) {
      const receive = e => {
        if (e.data !== token || e.ports.length !== 1) return;
        window.removeEventListener('message', receive);
        port = e.ports[0];
        port.postMessage(JSON.stringify({kind:'ready',token,sourceHash,documentId}));
      };
      window.addEventListener('message', receive);
      this.token = token; this.sourceHash = sourceHash;
      return true;
    },
    prepare(step, label, section) {
      try {
        const started=performance.now();
        if (!port) throw Error('Test-only message port not connected');
        if (active) throw Error('Previous gesture has not acknowledged');
        const matches = [...document.querySelectorAll('.registerknopf')].filter(b=>b.textContent.trim()===label);
        if (matches.length !== 1) throw Error('Expected exactly one register: '+label);
        const e = matches[0]; e.scrollIntoView({block:'nearest',behavior:'instant'});
        const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
        if (!hit || !(hit===e || e.contains(hit)) || e.disabled || !e.isConnected) return {ready:false};
        if (e.dataset.fokus !== 'register:'+section) throw Error('Label/section identity mismatch');
        const before=OrganizerTest.zustand().sektion;
        if (before===section) throw Error('No transition: expected section is already active');
        const armedAt=performance.now(),node=id(e);
        active={e,step,label,section,deadline:armedAt+10000,
          proof:NativeTouchProof.create({documentId,step,target:e,node,label,section,before,armedAt,token:this.token,sourceHash:this.sourceHash})};
        record([step,0,node,armedAt,x,y]);
        return {ready:true,step,documentId,node,label,section,before,armedAt,sourceHash:this.sourceHash,
          x,y,width:r.width,height:r.height,dpr:devicePixelRatio,pageScale:visualViewport.scale,
          viewportX:visualViewport.offsetLeft,viewportY:visualViewport.offsetTop,touchAction:getComputedStyle(e).touchAction,
          jsPrepareMs:performance.now()-started};
      } catch(e) {return {error:String(e)};}
    }
  };
  function acknowledge(a) {
    if (active!==a || performance.now()>a.deadline) return;
    const section=OrganizerTest.zustand().sektion;
    const pendingJobs=section==='planer' ? [...(OrganizerTest.icsRuntime.state?.jobs.values()||[])].filter(j=>j.status==='pending').length : null;
    if (section==='planer' && section===a.section && pendingJobs!==0) {
      port.postMessage(JSON.stringify({kind:'error',step:a.step,documentId,token:NativeTouchProbe.token,error:'Planner has pending jobs'}));
      active=null; return;
    }
    const proof=a.proof.finish(section,a.e.isConnected,a.e.textContent.trim(),a.e.dataset.fokus,pendingJobs);
    if (proof) {
      record([a.step,6,id(a.e),performance.now()]);
      active=null;
      port.postMessage(JSON.stringify({...proof,kind:'ack',token:NativeTouchProbe.token,ackAt:performance.now()}));
    } else {
      // Only while a genuine matching click is awaiting an async application guard;
      // no RPC polling, DOM mutation or repeated geometry/style reads.
      setTimeout(()=>acknowledge(a),25);
    }
  }
  ['pointerdown','pointerup','click','pointercancel','contextmenu'].forEach((type,index)=>{
    document.addEventListener(type,e=>{
      const a=active; if (!a) return;
      const target=e.target.closest?.('.registerknopf');
      const at=performance.now();
      record([a.step,index+1,id(target),e.timeStamp,at,e.pointerId||0,e.isTrusted?1:0,target?.isConnected?1:0]);
      if (a.proof.observe({type,target,trusted:e.isTrusted,documentId,token:NativeTouchProbe.token,
          step:a.step,node:id(target),connected:target?.isConnected===true,
          stamp:e.timeStamp,at,pointerId:e.pointerId,pointerType:e.pointerType,button:e.button})) {
        setTimeout(()=>acknowledge(a),0); // After downstream application click handlers.
      }
    },{capture:true,passive:true});
  });
})();
