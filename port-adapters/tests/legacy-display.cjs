/* Source-bound CSS cascade/feature-profile checks; not legacy-engine layout evidence. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const local=createRequire(path.resolve(__dirname,'../../Magnolie-Organizer-Android-Tablet-Beta/package.json'));
const jsdom=process.env.MACOS_BETA_JSDOM||local.resolve('jsdom');
const {JSDOM}=require(jsdom),{parse}=createRequire(jsdom)('rrweb-cssom');
function run({web,platform}) {
  let checks=0;
  const shared=fs.readFileSync(path.resolve(__dirname,'../legacy-display.css'),'utf8');
  const file=platform==='tablet'?'tablet.css':'macos-beta.css';
  const css=fs.readFileSync(path.join(web,file),'utf8');
  assert.ok(css.endsWith(shared),'Both projections must append the exact shared CSS input');checks++;
  const rules=parse(shared).cssRules;
  const fallback=rules.find(rule=>rule.conditionText==='not (background: color-mix(in srgb, red, white))');
  assert.ok(fallback);assert.equal(fallback.cssRules.length,2);checks++;
  const dom=new JSDOM('<button class="zyklus-schnellknopf"></button><button class="zyklus-schnellknopf aktiv"></button>'+
    '<span class="schicht-marke"></span><span class="muell-marke"></span><div class="pm-anlass"></div>'+
    '<div class="pm-anlass pm-feiertag"></div><div class="pm-anlass pm-ferien"></div><div class="pm-anlass pm-urlaub"></div>'+
    '<button class="registerknopf"></button><div class="personal-note-conflict"><pre>selectable</pre></div><input class="feld">');
  try {
    const document=dom.window.document;
    const marker=fallback.cssRules[0],planner=fallback.cssRules[1];
    assert.equal(marker.style.background,'var(--papier)');
    assert.equal(document.querySelectorAll(marker.selectorText).length,3);checks++;
    assert.equal(planner.style.background,'white');
    assert.equal(document.querySelectorAll(planner.selectorText).length,1,'Holiday/vacation backgrounds must survive the fallback');checks++;
    const none=rules.find(rule=>rule.style?.getPropertyValue('-webkit-user-select')==='none');
    const text=rules.find(rule=>rule.style?.getPropertyValue('-webkit-user-select')==='text');
    assert.ok(document.querySelector('.registerknopf').matches(none.selectorText));
    assert.ok(document.querySelector('.personal-note-conflict pre').matches(text.selectorText));
    assert.ok(!document.querySelector('input').matches(none.selectorText));checks++;
  } finally {dom.window.close();}
  if(platform==='tablet') {
    // Profile Chrome106's rejection of dvh declarations and inspect the parsed
    // surviving rules, including units inside clamp()/calc(). Refs #792 bounds
    // page heights and every dialog while retaining the older engine fallback.
    const legacyCss=css.replace(/\b(?:max-height|height):[^;{}]*dvh[^;{}]*;/g,'');
    assert.notEqual(legacyCss,css,'The legacy feature profile must remove actual dynamic viewport declarations');
    assert.doesNotMatch(legacyCss,/\d(?:\.\d+)?dvh\b/);checks++;
    const legacy=parse(legacyCss);
    const modern=parse(css);
    const all=sheet=>Array.from(sheet.cssRules).flatMap(rule=>rule.cssRules?Array.from(rule.cssRules):[rule]);
    const style=(sheet,selector)=>all(sheet).find(rule=>rule.selectorText===selector).style;
    assert.equal(style(legacy,'#seiten > .seite').height,'clamp(340px, 72vh, 860px)');
    assert.equal(style(modern,'#seiten > .seite').height,'clamp(340px, 72dvh, 860px)');checks++;
    for(const selector of ['body [role=dialog]','#einstellungen-blatt']) {
      assert.equal(style(legacy,selector).getPropertyValue('max-height'),'calc(100vh - 16px)');
      assert.equal(style(modern,selector).getPropertyValue('max-height'),'calc(100dvh - 16px)');
    }
    assert.equal(style(legacy,'#einstellungen-blatt').height,'min(820px, calc(100vh - 16px))');
    assert.equal(style(modern,'#einstellungen-blatt').height,'min(820px, calc(100dvh - 16px))');checks++;
  }
  return checks;
}
module.exports=run;
if(require.main===module)try {console.log('Legacy CSS '+process.argv[2]+': '+run({platform:process.argv[2],web:path.resolve(process.argv[3])})+' source/AST checks; no native layout claim.');}
catch(error){console.error(error);process.exitCode=1;}
