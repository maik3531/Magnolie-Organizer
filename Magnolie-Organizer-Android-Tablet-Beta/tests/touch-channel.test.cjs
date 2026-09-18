const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<button class="registerknopf" data-fokus="register:kalender">Calendar</button>',
  {url:'https://appassets.androidplatform.net/assets/web/index.html',runScripts:'outside-only'});
const w=dom.window, e=w.document.querySelector('button'), messages=[];
let section='notizen';
Object.defineProperty(w.crypto,'randomUUID',{value:()=> 'fixture-document'});
w.OrganizerTest={zustand:()=>({sektion:section}),icsRuntime:{}};
w.visualViewport={scale:1,offsetLeft:0,offsetTop:0};
w.document.elementFromPoint=()=>e;
e.scrollIntoView=()=>{};
e.getBoundingClientRect=()=>({x:0,y:0,width:152,height:44});
for(const name of ['touch-proof.js','input-diagnostics.js'])
 w.eval(fs.readFileSync(require.resolve('../app/src/androidTest/assets/'+name),'utf8'));
w.NativeTouchProbe.connect('new-token','frozen-source');
const port={postMessage:text=>messages.push(JSON.parse(text))};
w.dispatchEvent(new w.MessageEvent('message',{data:'old-token',ports:[port]}));
assert.equal(messages.length,0);
w.dispatchEvent(new w.MessageEvent('message',{data:'new-token',ports:[port]}));
assert.equal(messages[0].kind,'ready');
assert.equal(messages[0].documentId,'fixture-document');
const prepared=w.NativeTouchProbe.prepare(1,'Calendar','kalender');
assert.equal(prepared.ready,true);assert.equal(prepared.sourceHash,'frozen-source');
for(const type of ['pointerdown','pointerup','click']) {
 const event=new w.MouseEvent(type,{bubbles:true,button:0});
 Object.defineProperties(event,{pointerType:{value:'touch'},pointerId:{value:7}});
 e.dispatchEvent(event); // isTrusted remains false, as it must for DOM injection.
}
section='kalender'; // Expected readonly DOM/state alone must not trigger an ACK.
assert.equal(messages.length,1);
assert.ok(w.NativeTouchProbe.prepare(2,'Calendar','kalender').error);
assert.equal(w.__nativeDiagnosticSnapshot().written,4);
dom.window.close();
console.log('1 functional channel/DOM false-positive case passed');
