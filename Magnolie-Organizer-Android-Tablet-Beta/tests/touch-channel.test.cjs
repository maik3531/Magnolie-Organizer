const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<button class="registerknopf" data-fokus="register:kalender">Calendar</button>',
  {url:'https://appassets.androidplatform.net/assets/web/index.html',runScripts:'outside-only'});
const w=dom.window, e=w.document.querySelector('button'), messages=[], frames=[];
w.requestAnimationFrame=callback=>{frames.push(callback);return frames.length;};
let section='notizen', x=0, animating=false;
e.getAnimations=()=>animating?[{playState:'running',effect:{getTiming:()=>({iterations:1})}}]:[];
Object.defineProperty(w.crypto,'randomUUID',{value:()=> 'fixture-document'});
w.OrganizerTest={zustand:()=>({sektion:section}),icsRuntime:{}};
w.visualViewport={scale:1,offsetLeft:0,offsetTop:0};
w.document.elementFromPoint=()=>e;
e.scrollIntoView=()=>{};
e.getBoundingClientRect=()=>({x,y:0,width:152,height:44});
for(const name of ['touch-proof.js','input-diagnostics.js'])
 w.eval(fs.readFileSync(require.resolve('../app/src/androidTest/assets/'+name),'utf8'));
w.NativeTouchProbe.connect('new-token','frozen-source');
const port={postMessage:text=>messages.push(JSON.parse(text))};
w.dispatchEvent(new w.MessageEvent('message',{data:'old-token',ports:[port]}));
assert.equal(messages.length,0);
w.dispatchEvent(new w.MessageEvent('message',{data:'new-token',ports:[port]}));
assert.equal(messages[0].kind,'ready');
assert.equal(messages[0].documentId,'fixture-document');
assert.equal(w.NativeTouchProbe.prepare(1,'Calendar','kalender').ready,false);
frames.shift()();
assert.equal(w.NativeTouchProbe.prepare(1,'Calendar','kalender').ready,false,'one frame must not arm a gesture');
frames.shift()();
x=8;
assert.equal(w.NativeTouchProbe.prepare(1,'Calendar','kalender').ready,false,'geometry change must restart frame verification');
frames.shift()();frames.shift()();
animating=true;
assert.equal(w.NativeTouchProbe.prepare(1,'Calendar','kalender').ready,false,'a running tab transition must not arm a gesture');
animating=false;
assert.equal(w.NativeTouchProbe.prepare(1,'Calendar','kalender').ready,false);
frames.shift()();frames.shift()();
const prepared=w.NativeTouchProbe.prepare(1,'Calendar','kalender');
assert.equal(prepared.ready,true);assert.equal(prepared.stableFrames,2);assert.equal(prepared.sourceHash,'frozen-source');
for(const type of ['pointerdown','pointerup','click']) {
 const event=new w.MouseEvent(type,{bubbles:true,button:0});
 Object.defineProperties(event,{pointerType:{value:'touch'},pointerId:{value:7}});
 e.dispatchEvent(event); // isTrusted remains false, as it must for DOM injection.
}
section='kalender'; // Expected readonly DOM/state alone must not trigger an ACK.
assert.equal(messages.length,1);
assert.ok(w.NativeTouchProbe.prepare(2,'Calendar','kalender').error);
assert.equal(w.__nativeDiagnosticSnapshot().written,4);
const diagnostic=w.NativeTouchProbe.failure();
assert.equal(diagnostic.activeStep,1);assert.equal(diagnostic.actualSection,'kalender');
assert.equal(diagnostic.events.length,4);
assert.deepEqual(Object.keys(diagnostic).sort(),['activeStep','expectedSection','actualSection','targetNode','rect','targetConnected','currentCenterHit','hidden','focused','pageScale','events'].sort());
dom.window.close();
console.log('1 functional channel/DOM false-positive case passed');


// Browser-side preparation must use the same private port identity and complete
// real frame/readiness checks without a sequence of native evaluateJavascript RPCs.
function channelFixture() {
  const test=new JSDOM('<button class="registerknopf" data-fokus="register:kalender">Calendar</button>',
    {url:'https://appassets.androidplatform.net/assets/web/index.html',runScripts:'outside-only'});
  const w=test.window, queue=[], sent=[], target=w.document.querySelector('button'); let now=0;
  Object.defineProperty(w.performance,'now',{value:()=>now});
  Object.defineProperty(w.crypto,'randomUUID',{value:()=> 'current-renderer'});
  w.requestAnimationFrame=fn=>{queue.push(fn);return queue.length;};
  w.OrganizerTest={zustand:()=>({sektion:'notizen'}),icsRuntime:{}};
  w.visualViewport={scale:1,offsetLeft:0,offsetTop:0};
  function configure(e) {e.scrollIntoView=()=>{};e.getBoundingClientRect=()=>({x:0,y:0,width:152,height:44});e.getAnimations=()=>[];}
  configure(target);w.document.elementFromPoint=()=>w.document.querySelector('button');
  for(const name of ['touch-proof.js','input-diagnostics.js']) w.eval(fs.readFileSync(require.resolve('../app/src/androidTest/assets/'+name),'utf8'));
  const port={postMessage:text=>sent.push(JSON.parse(text)),close(){this.closed=true;}};
  w.NativeTouchProbe.connect('current-token','current-source');
  w.dispatchEvent(new w.MessageEvent('message',{data:'current-token',ports:[port]}));
  const request={kind:'prepare',step:1,label:'Calendar',section:'kalender',token:'current-token',documentId:'current-renderer',sourceHash:'current-source',budgetMs:5000};
  return {w,target,port,sent,request,configure,frame(){now+=16;for(const fn of queue.splice(0))fn(now);},advance(value){now=value;},close(){test.window.close();}};
}
let protocolCases=0;
for(const change of [{token:'old-token'},{documentId:'old-renderer'},{sourceHash:'old-source'},{budgetMs:5001},{budgetMs:0}]) {
  const t=channelFixture();t.port.onmessage({data:JSON.stringify({...t.request,...change})});
  t.frame();t.frame();assert.equal(t.sent.length,1);assert.equal(t.w.NativeTouchProbe.failure().activeStep,0);t.close();protocolCases++;
}
{
  const t=channelFixture();t.port.onmessage({data:JSON.stringify(t.request)});
  assert.equal(t.sent.length,1);t.frame();assert.equal(t.sent.length,1);t.frame();
  assert.equal(t.sent.length,2);assert.equal(t.sent[1].kind,'prepared');assert.equal(t.sent[1].stableFrames,2);
  assert.equal(t.sent[1].token,t.request.token);assert.equal(t.sent[1].documentId,t.request.documentId);
  assert.equal(t.sent[1].sourceHash,t.request.sourceHash);assert.equal(t.sent[1].step,1);
  assert.ok(!t.sent.some(message=>message.kind==='ack'),'preparation cannot invent a trusted click');
  t.close();protocolCases++;
}
{
  const t=channelFixture();t.port.onmessage({data:JSON.stringify(t.request)});t.frame();
  const replacement=t.target.cloneNode(true);t.configure(replacement);t.target.replaceWith(replacement);
  t.frame();assert.equal(t.sent.length,1,'a detached target must restart stable-frame preparation');t.frame();t.frame();
  assert.equal(t.sent[1].kind,'prepared');assert.equal(t.w.NativeTouchProbe.failure().targetConnected,true);t.close();protocolCases++;
}
{
  const t=channelFixture();t.port.onmessage({data:JSON.stringify(t.request)});t.advance(5001);t.frame();
  assert.equal(t.sent[1].kind,'prepareError');assert.equal(t.w.NativeTouchProbe.failure().activeStep,0);t.close();protocolCases++;
}
{
  const t=channelFixture();t.port.onmessage({data:JSON.stringify(t.request)});t.w.dispatchEvent(new t.w.Event('pagehide'));
  t.frame();t.frame();assert.equal(t.sent.length,1);assert.equal(t.port.closed,true);t.close();protocolCases++;
}
console.log(`${protocolCases} bounded identity/readiness/liveness preparation cases passed`);
