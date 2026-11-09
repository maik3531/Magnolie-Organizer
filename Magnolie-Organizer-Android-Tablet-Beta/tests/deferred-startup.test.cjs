'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole,ResourceLoader}=require('jsdom');
module.exports=async function({web}) {
  const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
  const names=[...html.matchAll(/<script src="([^"]+)" defer><\/script>/g)].map(x=>x[1]);
  assert.equal(names.length,12);assert.equal((html.match(/<script\b/g)||[]).length,12);
  const errors=[],requested=[],pending=[],messages=[];
  let releaseReady,dom,timeout;
  const session=webcrypto.randomUUID(),revision=webcrypto.randomUUID();
  class Resources extends ResourceLoader {
    fetch(url) {
      const name=new URL(url).pathname.replace('/assets/web/','');
      assert(!name.includes('..') && !path.isAbsolute(name));
      const bytes=fs.readFileSync(path.join(web,name));
      if(!name.endsWith('.js'))return Promise.resolve(bytes);
      assert(names.includes(name));requested.push(name);
      return new Promise(resolve=>{
        pending.push({name,resolve,bytes});
        if(pending.length===names.length) {
          // Every request must start while the first response is still held.
          // Reverse completion must not reverse classic defer execution order.
          for(const item of [...pending].reverse()) item.resolve(Buffer.concat([
            Buffer.from('window.__startupOrder.push('+JSON.stringify(item.name)+');\n'),item.bytes]));
        }
      });
    }
  }
  const virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',error=>errors.push(error));
  try {
    const ready=new Promise((resolve,reject)=>{
      releaseReady=resolve;
      timeout=setTimeout(()=>reject(Error('Deferred real HTML startup did not complete; requested '+requested.length+' scripts')),5000);
    });
    dom=new JSDOM(html,{url:'https://appassets.androidplatform.net/assets/web/index.html',
      runScripts:'dangerously',resources:new Resources(),pretendToBeVisual:true,virtualConsole,
      beforeParse(w) {
        w.__startupOrder=[];w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;
        Object.defineProperty(w,'crypto',{value:webcrypto});w.Element.prototype.getAnimations=()=>[];
        w.document.addEventListener('DOMContentLoaded',()=>{w.__startupDCL=true;});
        w.TabletNative={postMessage(text) {
          const message=JSON.parse(text);messages.push(message.cmd);
          if(message.cmd==='bereit') {
            assert.equal(w.__startupDCL,true);assert(w.document.getElementById('tablet-bar'));
            assert.deepEqual(Array.from(w.__startupOrder),names);
            queueMicrotask(()=>w.Tablet.receive({callback:'init',payload:{daten:null,session,revision}}));
          }
          if(message.cmd==='tablet_loaded') {
            // Withhold the real native ready callback: no speculative admission.
            releaseReady();
          }
        }};
      }});
    await ready;
    assert.deepEqual(requested,names);assert.deepEqual(Array.from(dom.window.__startupOrder),names);
    assert.equal(messages.filter(x=>x==='bereit').length,1);
    assert.equal(messages.filter(x=>x==='tablet_loaded').length,1);
    assert(dom.window.OrganizerTest && dom.window.Tablet);
    assert(!messages.includes('speichern'),'No save before the withheld native ready callback');
    assert.equal(dom.window.document.querySelectorAll('#tablet-bar').length,1);
    assert.equal(errors.length,0,errors.map(x=>String(x)).join('\n'));
    globalThis.console.log('PASS deferred startup: actual 12-script HTML, all requests before first response, reverse response order, DCL/adapter/native bootstrap ordering');
    return 1;
  } finally {
    clearTimeout(timeout);
    dom?.window.close();
  }
};
