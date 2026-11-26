'use strict';
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const web='/workspace/scratch/acde70e8594b/Magnolie-Organizer/Magnolie-Organizer-Android-Tablet-Beta/app/build/generated/projection/assets/web';
const out='/workspace/scratch/acde70e8594b/tablet-system-conflict-visibility';
fs.mkdirSync(out,{recursive:true});
const contactSource='android-contacts:'+'a'.repeat(64),eventSource='android-events:'+'b'.repeat(64);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/workspace/scratch/acde70e8594b/tablet-browser-tooling/root/usr/lib/chromium/chromium-headless-shell'});
 const results=[];
 try{
 for(const spec of [{name:'split',width:600,height:960},{name:'keyboard',width:600,height:360}]){
  const context=await browser.newContext({viewport:{width:spec.width,height:spec.height},hasTouch:true,locale:'de-DE',reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(4000);const errors=[];
  page.on('pageerror',err=>errors.push(err.message));
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());if(url.origin!=='https://tablet-layout.test')return route.abort();
   const file=path.resolve(web,decodeURIComponent(url.pathname).replace(/^\/+/, '')||'index.html');
   if(!file.startsWith(web+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:'missing'});
   const types={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json','.png':'image/png','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf'};
   return route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
  });
  await page.addInitScript(({contactSource,eventSource})=>{
   const session=crypto.randomUUID();let revision=crypto.randomUUID(),disk=null;
   window.__messages=[];window.__snapshot={verfuegbar:true,buchOk:true,permissions:{contacts:'authorized',events:'authorized'},
    systemImportImplemented:{contacts:true,events:'instances-window'},kalender:[{uid:eventSource,name:'Privatkalender',art:'android-events'}],
    adressbuecher:[{uid:contactSource,name:'Lokale Kontakte',art:'android-contacts'}]};
   window.__reply=(callback,payload)=>window.Tablet.receive({callback,payload});
   window.__finishImport=()=>{const r=window.__messages.filter(m=>m.cmd==='android_systemimport').at(-1);
    window.__reply('androidSystemImport',{...r,kind:r.art,ok:true,complete:true,scope:r.art==='contacts'?'source-contacts':'calendar-instances-window',records:[]});};
   window.TabletNative={postMessage(text){const m=JSON.parse(text);window.__messages.push(m);setTimeout(()=>{
    if(m.cmd==='bereit')window.__reply('init',{daten:disk,session,revision});
    if(m.cmd==='tablet_loaded')window.__reply('ready',{session,revision});
    if(m.cmd==='speichern'){disk=JSON.parse(m.text);const expectedRevision=revision;revision=crypto.randomUUID();window.__reply('gespeichert',{id:m.id,ok:true,session,expectedRevision,revision});}
    if(m.cmd==='eds_status')window.__reply('edsStatus',{...window.__snapshot,requestId:m.requestId});
    if(m.cmd==='baum_briefkasten_status')window.__reply('baumBriefkastenStatus',{kontoArt:'nextcloud',davAktiv:false,briefkastenAktiv:false,url:'',benutzer:'',kennwortVorhanden:false,revision:'f'.repeat(64),zustand:'disabled',fehler:''});
   },0);}};
  },{contactSource,eventSource});
  await page.goto('https://tablet-layout.test/index.html');
  await page.waitForFunction(()=>!!window.OrganizerTest&&document.querySelector('#buch.offen'));
  await page.locator('#knopf-einstellungen').tap();
  await page.waitForFunction(()=>document.activeElement?.id==='einstellungen-zu');
  const openFocus=await page.evaluate(()=>document.activeElement.id);
  await page.locator('#einst-tab-sync').tap();
  await page.waitForFunction(()=>document.querySelector('#tablet-system-source-contacts')?.options.length===2);
  await page.locator('#tablet-system-source-contacts').selectOption(contactSource);
  await page.locator('#tablet-system-source-events').selectOption(eventSource);
  await page.locator('#tablet-system-from').fill('2026-11-26');
  await page.locator('#tablet-system-to').fill('2026-12-10');
  await page.locator('#tablet-system-to').press('Tab');
  const measure=()=>page.evaluate(()=>{
   const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
   const page=document.querySelector('.einst-seite');const root=document.querySelector('#tablet-system-access');
   return {active:document.activeElement?.id||document.activeElement?.tagName,inside:document.getElementById('einstellungen-blatt').contains(document.activeElement),
    content:{...rect(page),clientWidth:page.clientWidth,scrollWidth:page.scrollWidth,scrollHeight:page.scrollHeight,scrollTop:page.scrollTop,scrollLeft:page.scrollLeft},
    root:rect(root),controls:[...root.querySelectorAll('button,select,input')].map(el=>({id:el.id,text:el.textContent,...rect(el),disabled:el.disabled,
      centerHit:el.contains(document.elementFromPoint(...(()=>{const r=el.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()))}))};
  });
  await page.locator('#tablet-system-import-contacts').tap();
  await page.waitForFunction(()=>window.__messages.some(m=>m.cmd==='android_systemimport'&&m.art==='contacts'));
  await page.evaluate(()=>{
   const request=window.__messages.filter(m=>m.cmd==='android_systemimport').at(-1);
   const records=['e','f'].map(letter=>{const recordId='android-contact:'+letter.repeat(64);return {
    recordId,identityKind:'source-id',rowBinding:'android-contact-row:'+'c'.repeat(64),
    data:{uid:recordId,anzeigename:'Synthetic conflict',sync:false}};});
   window.__reply('androidSystemImport',{...request,kind:'contacts',ok:true,complete:true,identitySchema:2,scope:'source-contacts',records});
  });
  await page.waitForFunction(()=>document.getElementById('tablet-status').textContent===window.Tablet.systemText('identityConflict'));
  const result=await page.evaluate(()=>{
   const el=document.getElementById('tablet-status'),r=el.getBoundingClientRect(),dialog=document.getElementById('einstellungen-blatt');
   const atCenter=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
   return {message:el.textContent,rect:{x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom},
    settingsOpen:!document.getElementById('einstellungen-schleier').classList.contains('verborgen'),
    messageInsideDialog:dialog.contains(el),statusCenterReceivesHit:el.contains(atCenter),
    centerCoveredBy:atCenter?.id||atCenter?.className||atCenter?.tagName,
    dialogCoversCenter:dialog.contains(atCenter),contacts:OrganizerTest.daten().kontakte.length};
  });
  await page.screenshot({path:path.join(out,spec.name+'-identity-conflict.png')});
  results.push({...spec,...result,errors});console.log(JSON.stringify({...spec,...result,errors}));
  await context.close();
 }
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({browser:browser.version(),scope:'Host Chromium review only, synthetic provider and SaveACK',results},null,2)+'\n');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
