// Refs #121. Runs canonical UI functions in memory; no native launches.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const dependencies=createRequire(path.resolve(__dirname,'../../Magnolie-Organizer-Android-Tablet-Beta/package.json'));
const {JSDOM,VirtualConsole}=process.env.MACOS_BETA_JSDOM?require(process.env.MACOS_BETA_JSDOM):dependencies('jsdom');
const phoneMode=process.argv.includes('--phone-projection');
const canonicalWeb=path.resolve(__dirname,'../../magnolie-organizer/web');
const webArgument=process.argv[2],rawCheckout=webArgument===undefined && !phoneMode;
const web=path.resolve(webArgument===undefined?canonicalWeb:webArgument),messages=[];const dom=new JSDOM(fs.readFileSync(path.join(web,'index.html'),'utf8'),{url:'https://launcher-probe.invalid/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
const w=dom.window;w.setTimeout=()=>0;w.setInterval=()=>0;w.requestAnimationFrame=()=>0;w.HTMLElement.prototype.scrollIntoView=()=>{};w.Element.prototype.getAnimations=()=>[];
w.__MAGNOLIE_BRUECKE__='probe';w.webkit={messageHandlers:{probe:{postMessage(raw){messages.push(JSON.parse(raw))}}}};
const declaredScripts=[...w.document.querySelectorAll('script[src]')].map(script=>script.getAttribute('src'));
const scripts=phoneMode?declaredScripts:declaredScripts.filter(name=>['i18n.js','normative-timezones.js','anwendung.js'].includes(name));
for(const name of ['i18n.js','anwendung.js'])assert.equal(scripts.filter(value=>value===name).length,1,'Required canonical script: '+name);
if(scripts.includes('normative-timezones.js')) {
  assert.equal(scripts.filter(value=>value==='normative-timezones.js').length,1);
  assert.ok(scripts.indexOf('normative-timezones.js')<scripts.indexOf('anwendung.js'),'Canonical timezone bootstrap must precede its UI hooks');
}
for(const f of scripts) {
  // #796: the default raw checkout carries inputs, not a generated bootstrap.
  // Use the same real provider recipe as the ports; supplied projections must
  // contain their own bootstrap and never fall back to this checkout.
  let source=f==='normative-timezones.js' && rawCheckout
    ?require('../timezones/projection-assets.cjs')(name=>fs.readFileSync(path.resolve(__dirname,'../timezones',name)))[f].toString('utf8')
    :fs.readFileSync(path.join(web,f),'utf8');
  if(f==='anwendung.js') {
    assert.equal(source.split('window.OrganizerTest = {').length,2);
    source=source.replace('window.OrganizerTest = {','window.OrganizerTest = { schreibePost, zeigeKarte, oeffneSozial, oeffneKalenderAnhang,');
  }
  w.eval(source);
}
const initialize=phoneMode?payload=>w.MacBeta.receive('init',payload):payload=>w.App.init(payload);
initialize({daten:{einstellungen:{allgemein:{handbuchHinweisGezeigt:true}}},neu:false,regional:{language:'en',timeZone:'UTC'}});
const T=w.OrganizerTest,D=T.daten(),k={vorname:'Ada',nachname:'Example',strasse:'Musterweg 12',plz:'10115',ort:'Berlin',land:'Deutschland'};
if(phoneMode) {
  const golden=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../Magnolie-Organizer-macOS-Beta/Tests/BetaCoreTests/Fixtures/communication-phone-payloads.json')));
  for(const row of golden) {
    D.einstellungen.regional.homeCountry=row.country;messages.length=0;
    const request=row.request;assert.equal(T.oeffneSozial({dienst:request.dienst,wert:request.wert,aktionArt:request.aktionArt,aktionZiel:request.aktionZiel}),true);
    assert.deepEqual(messages,[request],row.country+' canonical national/extension normalization');
    assert.equal(request.nummer,row.expectedE164);
  }
  console.log('PASS '+golden.length+' actual projected phone payloads (canonical country metadata; no external application opened)');
} else {
messages.length=0;assert.equal(T.schreibePost(k,'ada@example.org'),true);assert.equal(T.schreibePost(k,'ada@bücher.example'),true);
for(const dienst of ['auto','gnome-maps','openstreetmap','google']){D.einstellungen.adressen.karten=dienst;D.einstellungen.adressen.route=false;assert.equal(T.zeigeKarte(k),true);D.einstellungen.adressen.route=true;D.einstellungen.adressen.absender='Alex Example\nStartweg 5\n10117 Berlin';assert.equal(T.zeigeKarte(k),true);}
for(const entry of [{dienst:'custom',wert:'https://example.org/calendar/item'},{dienst:'custom',wert:'https://bücher.example:8443/calendar'}, {dienst:'custom',wert:'Ada & Bob',aktionArt:'website',aktionZiel:'https://example.org/search?q={wert}'},{dienst:'telegram',wert:'@example'},{dienst:'custom',wert:'Ada',aktionArt:'program',aktionZiel:'arbitrary-command {wert}'}])assert.equal(T.oeffneSozial(entry),true);
assert.equal(messages.length,15);
const golden=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../Magnolie-Organizer-macOS-Beta/Tests/BetaCoreTests/Fixtures/communication-ui-payloads.json')));
assert.deepEqual(messages,golden,'Actual canonical functions must retain the published payload contract');
process.stdout.write('PASS 15 canonical communication payloads (host only; no external application opened)\n');
}
setImmediate(()=>dom.window.close());
