// Host-only checks of shared native domain inputs. Real canvas/trusted input is
// deliberately left to the native stage; no canvas shim pretends to prove ink.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module'),{webcrypto}=require('node:crypto');
const repository=path.resolve(__dirname,'../..');
const {JSDOM,VirtualConsole}=createRequire(path.join(repository,'Magnolie-Organizer-Android-Tablet-Beta/package.json'))('jsdom');
module.exports=async function run({web}) {
 let disk=null,revision=webcrypto.randomUUID();const session=webcrypto.randomUUID(),errors=[];
 const console=new VirtualConsole();console.on('jsdomError',error=>errors.push(error));
 async function open() {
  const dom=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{runScripts:'outside-only',pretendToBeVisual:true,
   url:'https://appassets.androidplatform.net/assets/web/index.html',virtualConsole:console});
  const w=dom.window;
  w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w,'crypto',{value:webcrypto});
  w.Element.prototype.getAnimations=()=>[];w.Element.prototype.scrollIntoView=()=>{};
  w.TabletNative={postMessage(text){const m=JSON.parse(text);setTimeout(()=>{
   if(!w.document)return;
   if(m.cmd==='bereit')w.Tablet.receive({callback:'init',payload:{daten:disk,session,revision}});
   if(m.cmd==='tablet_loaded')w.Tablet.receive({callback:'ready',payload:{session,revision}});
   if(m.cmd==='speichern') {assert.equal(m.session,session);assert.equal(m.revision,revision);disk=JSON.parse(m.text);revision=webcrypto.randomUUID();
    w.Tablet.receive({callback:'gespeichert',payload:{id:m.id,ok:true,session,expectedRevision:m.revision,revision}});}
  },0)}};
  for(const script of w.document.querySelectorAll('script[src]'))w.eval(fs.readFileSync(path.join(web,script.getAttribute('src')),'utf8'));
  await new Promise(resolve=>setTimeout(resolve,80));w.MagnolieI18n.setLocale('en');
  w.eval(fs.readFileSync(path.join(__dirname,'domain-scenarios.js'),'utf8'));return dom;
 }
 let dom=await open(),count=0;
 try {
  await dom.window.NativeDomains.prepare();count++;
  await dom.window.NativeDomains.health();count++;
  await dom.window.NativeDomains.custom();count++;
  const expected=JSON.parse(JSON.stringify(dom.window.NativeDomains.expectedAfterReopen(dom.window.NativeDomains.snapshot())));
  assert.equal(disk.gesundheit.vitalwerte[0].puls,73);assert.equal(disk.customOrganizer.modules.length,3);count++;
  const fullExpected=JSON.parse(JSON.stringify(dom.window.NativeDomains.expectedAfterReopen(dom.window.OrganizerTest.daten())));
  const savedOriginal=JSON.parse(JSON.stringify(dom.window.OrganizerTest.daten()));
  assert.deepEqual(disk,savedOriginal,'Native save ACK must preserve all original values, IDs and unknown fields');
  dom.window.close();dom=await open();
  assert.deepEqual(JSON.parse(JSON.stringify(dom.window.OrganizerTest.daten())),fullExpected);
  assert.deepEqual(JSON.parse(JSON.stringify(dom.window.NativeDomains.snapshot())),expected);count++;
  const goodDisk=JSON.stringify(disk);
  for(const mode of ['changed','lost']) {
    dom.window.close();disk=JSON.parse(goodDisk);
    if(mode==='changed')disk.gesundheit.vitalwerte[0].puls=74;
    else delete disk.gesundheit.vitalwerte[0].puls;
    dom=await open();
    assert.notDeepEqual(JSON.parse(JSON.stringify(dom.window.NativeDomains.snapshot())),expected,'Corrupt stored health '+mode+' values were not detected');count++;
  }
  assert.equal(errors.length,0,errors.map(String).join('\n'));count++;
  process.stdout.write(`Shared actual domain forms: ${count} host checks passed; native canvas/IME/device acceptance not claimed.\n`);
  return count;
 } finally {dom.window.close()}
};
if(require.main===module)module.exports({web:process.argv[2]}).catch(error=>{console.error(error);process.exitCode=1;});
