/* Generated build projection only. No writes to canonical desktop/Notes sources. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createHash } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const parent = path.dirname(root);
const desktop = path.join(parent, 'magnolie-organizer/web');
const windowsWeb = path.join(parent, 'magnolie-organizer-windows/app/web');
const out = path.join(root, 'app/build/generated/projection');
const sha = b => createHash('sha256').update(b).digest('hex');
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).sort((a,b) => a.name.localeCompare(b.name, 'en'))
    .flatMap(e => { const p = path.join(dir, e.name);
      if (e.isSymbolicLink()) throw Error('Symlinks are forbidden in projection inputs: ' + p);
      return e.isDirectory() ? walk(p) : [p]; });
}
const inputs = [...walk(desktop), ...walk(path.join(windowsWeb,'schriften')), path.join(windowsWeb,'stil.css'), ...walk(path.join(root, 'web')),
  ...walk(path.join(parent,'port-adapters')),
  path.join(windowsWeb,'anwendung.js'), ...walk(path.join(windowsWeb,'i18n')),
  ...walk(path.join(root, 'app/src')), ...walk(path.join(root, 'tests')),
  ...walk(path.join(root, 'tools')), ...walk(path.join(parent, 'contracts')),
  path.join(parent,'magnolie-organizer-windows/tests/personal-custom-consent.js'),
  path.join(parent,'magnolie-organizer-windows/tests/setup-holidays.js'),
  path.join(parent,'magnolie-organizer-windows/app/native-i18n.json'),
  ...['gradlew','gradle/wrapper/gradle-wrapper.jar','gradle/wrapper/gradle-wrapper.properties']
    .map(f=>path.join(parent,'magnolie-notes',f)),
  ...['DatenDateiKrypto.kt','DateiDauerhaft.kt'].map(f => path.join(parent,
    'magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/daten', f)),
  ...['app/build.gradle.kts','build.gradle.kts','settings.gradle.kts','gradle.properties','package.json','bun.lock'].map(f => path.join(root,f))];
const buffers = new Map(inputs.map(p => [p, fs.readFileSync(p)]));
const hashes = Object.fromEntries([...buffers].map(([p,b]) => [path.relative(parent,p),sha(b)]).sort(([a],[b])=>a.localeCompare(b,'en')));
const sourceHash = sha(JSON.stringify(hashes));
function markCandidateStale(reason) {
  const file=path.join(root,'artifacts/candidate.json');
  if (!fs.existsSync(file)) return;
  const candidate=JSON.parse(fs.readFileSync(file));
  candidate.stale=true; candidate.currentSourceHash=sourceHash;
  candidate.status='STALE debug beta; not current-source readiness or production acceptance';
  candidate.staleReason=reason;
  fs.writeFileSync(file,JSON.stringify(candidate,null,2)+'\n');
}
if (process.argv.includes('--check')) {
  const manifest = JSON.parse(fs.readFileSync(path.join(out,'assets/projection.json')));
  if (sourceHash !== manifest.sourceHash) {
    const changed=Object.keys({...manifest.inputs,...hashes}).filter(p=>manifest.inputs[p]!==hashes[p]);
    markCandidateStale('Source inputs changed: '+changed.join(', '));
    throw Error('Sources changed. Rebuild the beta; do not publish stale assets.\n'+changed.join('\n'));
  }
  for (const [name, hash] of Object.entries(manifest.outputs)) {
    if (sha(fs.readFileSync(path.join(out,name))) !== hash) throw Error('Generated projection modified: '+name);
  }
  console.log('Projection matches current source: ' + sourceHash);
  const candidateFile=path.join(root,'artifacts/candidate.json');
  if(fs.existsSync(candidateFile) && JSON.parse(fs.readFileSync(candidateFile)).sourceHash!==sourceHash) {
    markCandidateStale('Existing APK uses an older projection');
    console.log('Existing debug APK is stale; this source check is not full readiness.');
  }
  process.exit(0);
}
markCandidateStale('Projection regeneration in progress; artifact verification pending');
const timezoneRoot=path.join(parent,'port-adapters/timezones');
const timezoneInput=name=>buffers.get(path.join(timezoneRoot,name));
const timezoneBuilder={module:{exports:{}},Buffer,require:name=>{
  if(name!=='node:crypto') throw Error('Unexpected timezone build dependency');
  return require(name);
}};
vm.runInNewContext(timezoneInput('projection-assets.cjs').toString(),timezoneBuilder,{filename:'shared-timezone-assets.cjs'});
const timezoneAssets=timezoneBuilder.module.exports(timezoneInput);
const generated = new Map();
for (const [p,b] of buffers) if (p.startsWith(desktop + path.sep)) generated.set('assets/web/'+path.relative(desktop,p),b);
// Finalized strokes share Undo/Redo/reopen/export rendering without changing
// the canonical Linux/Windows source or the live pointer-motion path.
const drawingPatch = JSON.parse(buffers.get(path.join(parent,'port-adapters/drawing-finish-patch.json')));
const drawingSource = generated.get('assets/web/zeichenblatt.js').toString();
if (drawingPatch.schema !== 1 || sha(drawingSource) !== drawingPatch.canonicalSHA256 ||
    drawingSource.split(drawingPatch.before).length !== 2 ||
    typeof drawingPatch.releaseBefore !== 'string' || typeof drawingPatch.releaseAfter !== 'string' ||
    drawingSource.split(drawingPatch.releaseBefore).length !== 2) throw Error('Canonical drawing finish anchor changed');
generated.set('assets/web/zeichenblatt.js',Buffer.from(drawingSource.replace(drawingPatch.before,drawingPatch.after).replace(drawingPatch.releaseBefore,drawingPatch.releaseAfter)));
// Android does not provide the desktop's Noto Serif / DejaVu families by name.
// Reuse live Windows @font-face definitions and bytes, never host font discovery.
const fontFaces = buffers.get(path.join(windowsWeb,'stil.css')).toString().match(/@font-face\s*\{[^}]+\}/g) || [];
if (!fontFaces.some(face=>face.includes('"Noto Serif"')) || !fontFaces.some(face=>face.includes('"DejaVu Sans"')))
  throw Error('Canonical desktop font definitions changed');
for (const [p,b] of buffers) if (p.startsWith(path.join(windowsWeb,'schriften')+path.sep)) {
  const name='assets/web/schriften/'+path.basename(p);
  if (generated.has(name) && !generated.get(name).equals(b)) throw Error('Desktop font variants disagree: '+name);
  generated.set(name,b);
}
for (const match of fontFaces.join('\n').matchAll(/url\(["']?([^"')]+)["']?\)/g)) {
  if (!match[1].startsWith('schriften/') || !generated.has('assets/web/'+match[1])) throw Error('Unbundled desktop font: '+match[1]);
}
generated.set('assets/web/desktop-fonts.css',Buffer.from(fontFaces.join('\n\n')+'\n'));
const timezonePatcher={module:{exports:{}},require:timezoneBuilder.require};
vm.runInNewContext(timezoneInput('projection-patches.cjs').toString(),timezonePatcher,{filename:'shared-timezone-patches.cjs'});
const occurrencePatcher={module:{exports:{}},require:timezoneBuilder.require};
vm.runInNewContext(buffers.get(path.join(parent,'port-adapters/occurrence-identity-projection.cjs')).toString(),occurrencePatcher,{filename:'shared-occurrence-identity-projection.cjs'});
const appSource = occurrencePatcher.module.exports(
  timezonePatcher.module.exports(buffers.get(path.join(desktop,'anwendung.js')).toString(),timezoneInput),
  name=>buffers.get(path.join(parent,'port-adapters',name)));
const regionalAnchor = '    { id: "ort", name: msgid("Country & holidays") },';
if (appSource.split(regionalAnchor).length !== 2) throw Error('Desktop regional settings anchor changed');
let regionalSource = appSource.replace(regionalAnchor,
  '    { id: "regional", name: msgid("Language and regional display") },\n'+regionalAnchor);
const alarmHelper = buffers.get(path.join(parent,'port-adapters/display-alarm-roundtrip.js')).toString();
const alarmHelperAnchor = '  function spiegeleTerminInIcs(termin, vorher = null) {';
const alarmRebuildAnchor = `    for (const alarm of saubereAlarme(termin.alarme).filter((a) => a.bearbeitbar && a.aktiviert)) {
      const trigger = alarm.offsetMinuten ? "-PT" + alarm.offsetMinuten + "M" : "-PT0M";
      neu.push("BEGIN:VALARM", "TRIGGER;RELATED=" + alarm.related + ":" + trigger,
        "ACTION:DISPLAY", "DESCRIPTION:" + icsSicher(termin.titel || "Termin"), "END:VALARM");
    }`;
for (const anchor of [alarmHelperAnchor,alarmRebuildAnchor])
  if (regionalSource.split(anchor).length !== 2) throw Error('Canonical DISPLAY alarm anchor changed');
regionalSource = regionalSource.replace(alarmHelperAnchor,
  '/*PORT_DISPLAY_ALARM_HELPER_BEGIN*/\n'+alarmHelper+'/*PORT_DISPLAY_ALARM_HELPER_END*/\n'+alarmHelperAnchor)
  .replace(alarmRebuildAnchor,'    neu.push(...portDisplayAlarmLines(termin, vorher, alt));');
const automaticZoneAnchor = '  async function aktualisiereAutomatischeZeitzone() {';
if (regionalSource.split(automaticZoneAnchor).length !== 2) throw Error('Desktop automatic time-zone anchor changed');
// Android Beta has no native source-bound detection. Preserve imported settings
// while refusing to initiate the desktop-only background MCP transaction.
regionalSource = regionalSource.replace(automaticZoneAnchor, automaticZoneAnchor+' return;');
// The actual shared DAV form and source-selection renderer remain authoritative.
// Prefixes isolate Android account setup/discovery from desktop-only services.
const davPatch = (name, body) => '/*TABLET_DAV_'+name+'_BEGIN*/'+body+'/*TABLET_DAV_'+name+'_END*/';
function amendDav(before, after) {
  if (regionalSource.split(before).length !== 2) throw Error('Canonical DAV anchor changed: '+before.slice(0,90));
  regionalSource = regionalSource.replace(before,after);
}
const davSyncAnchor = '  function baueSeiteSync(wurzel) {';
amendDav(davSyncAnchor,davSyncAnchor+davPatch('PAGE',`{
    const section = abschnitt(_("DAV account"), "Account setup and read-only discovery. Calendar/contact synchronization is not implemented.");
    section.id = "tablet-dav-discovery";
    const status = el("p", "sync-status", _("Checking online accounts …")); status.id = "sync-status";
    const choices = el("div", "sync-wahl"); choices.id = "sync-wahl";
    const start = knopf(_("Synchronize now"), "", () => starteSync(false)); start.id = "sync-jetzt"; start.disabled = true;
    const limitation = el("p", "einst-hinweis", "Account setup and read-only discovery. Calendar/contact synchronization is not implemented."); limitation.id = "tablet-dav-limit";
    const systemAccess = el("div", ""); systemAccess.id = "tablet-system-access";
    section.append(status, systemAccess, choices, start, limitation); wurzel.append(section);
    if (letzterEdsStatus) fuelleEdsAuswahl(letzterEdsStatus);
    Bruecke.sende({ cmd: "eds_status" });
    baueNextcloudKonto(wurzel); window.TabletDav.accountRendered(briefkastenStand); return;
  }`));
const davStartAnchor = '  function starteSync(stumm) {';
amendDav(davStartAnchor,davStartAnchor+davPatch('SYNC',
  'if (!stumm) zettel("Calendar/contact synchronization is not implemented. DAV account setup and read-only discovery are available."); return;'));
amendDav('        kennwortLoeschen: !!kennwortLoeschen });',
  '        kennwortLoeschen: !!kennwortLoeschen'+davPatch('REVISION',', expectedRevision: briefkastenStand.revision')+' });');
amendDav('Bruecke.sende({ cmd: "baum_briefkasten_pruefen" })',
  'Bruecke.sende({ cmd: "baum_briefkasten_pruefen"'+davPatch('TEST_REVISION',', expectedRevision: briefkastenStand.revision')+' })');
const davSourceAnchor = '  function fuelleEdsAuswahl(nutzlast) {';
const sourceStart = regionalSource.indexOf(davSourceAnchor);
const sourceEnd = regionalSource.indexOf('  function starteImport(',sourceStart);
if (sourceStart<0 || sourceEnd<0 || regionalSource.split(davSourceAnchor).length!==2) throw Error('Canonical DAV source renderer changed');
let sourceRenderer = regionalSource.slice(sourceStart,sourceEnd);
const sourceClose = sourceRenderer.lastIndexOf('}');
sourceRenderer = sourceRenderer.slice(0,sourceClose)+davPatch('SOURCE_END',
  '} finally { window.TabletDav.sourcesRendered(nutzlast); }')+sourceRenderer.slice(sourceClose);
sourceRenderer = sourceRenderer.replace(davSourceAnchor,davSourceAnchor+davPatch('SOURCE_START',
  'nutzlast = window.TabletDav.sourceView(nutzlast, DATEN.einstellungen.sync); try {'));
regionalSource = regionalSource.slice(0,sourceStart)+sourceRenderer+regionalSource.slice(sourceEnd);
// Preserve calendar-level source properties in the very same canonical book save as its records.
const calendarMergeAnchor = '      const { teile, doppelt, changed } = wendeDateiImportDatenAn(nutzlast, termineNormalisiert, kontaktPruefung);\n      if (changed) {';
if (regionalSource.split(calendarMergeAnchor).length !== 2) throw Error('Canonical calendar merge anchor changed');
regionalSource = regionalSource.replace(calendarMergeAnchor,
  '/*TABLET_ICS_MERGE_BEGIN*/      const calendarMetadata = window.Tablet.calendarMetadata(DATEN, nutzlast, false);\n/*TABLET_ICS_MERGE_END*/' +
  '      const { teile, doppelt, changed } = wendeDateiImportDatenAn(nutzlast, termineNormalisiert, kontaktPruefung);\n' +
  '      if (changed/*TABLET_ICS_SAVE_BEGIN*/ || calendarMetadata/*TABLET_ICS_SAVE_END*/) {/*TABLET_ICS_COMMIT_BEGIN*/\n' +
  '        if (calendarMetadata) window.Tablet.calendarMetadata(DATEN, nutzlast, true);/*TABLET_ICS_COMMIT_END*/');
const calendarExportAnchor = '  function starteExport(art) {';
if (regionalSource.split(calendarExportAnchor).length !== 2) throw Error('Canonical ICS export action anchor changed');
regionalSource=regionalSource.replace(calendarExportAnchor,calendarExportAnchor+
  '/*TABLET_ICS_EXPORT_BEGIN*/\n    if (["ics-termine","ics-aufgaben","ics-jahrestage"].includes(art)) return window.Tablet.exportCalendar(art);/*TABLET_ICS_EXPORT_END*/');
const anchor = '  window.App = App;';
if (appSource.split(anchor).length !== 2) throw Error('Desktop adapter anchor changed');
generated.set('assets/web/anwendung.js', Buffer.from(regionalSource.replace(anchor,
  '  window.MagnolieTabletActions = { afterSave: (action, failed) => navigiereMitGuard(() => nachDauerhaftemSpeichern(action, failed)), persist: (action, failed) => nachDauerhaftemSpeichern(action, failed), exportCalendar: art => starteExport(art) };\n'+anchor)));
let html = buffers.get(path.join(desktop,'index.html')).toString();
if (!html.includes('<script src="anwendung.js"></script>')) throw Error('Desktop entry point changed');
html = html.replace('<title>Magnolie Organizer</title>', '<title>Magnolie Organizer Android Tablet Beta 2.0.30Beta</title>')
  .replace('</head>', '<link rel="stylesheet" href="desktop-fonts.css">\n<link rel="stylesheet" href="tablet.css">\n<script src="tablet.js"></script>\n</head>');
if(html.split('<script src="tablet.js"></script>').length!==2) throw Error('Tablet bootstrap ordering anchor changed');
html=html.replace('<script src="tablet.js"></script>','<script src="normative-timezones.js"></script>\n<script src="tablet.js"></script>');
for(const [name,bytes] of Object.entries(timezoneAssets)) generated.set('assets/web/'+name,bytes);
generated.set('assets/web/index.html',Buffer.from(html));
for (const f of ['tablet.js','tablet.css']) generated.set('assets/web/'+f,buffers.get(path.join(root,'web',f)));
generated.set('assets/web/tablet.css',Buffer.concat([generated.get('assets/web/tablet.css'),
  Buffer.from('\n'),buffers.get(path.join(parent,'port-adapters/legacy-display.css'))]));
generated.set('assets/web/beta-i18n.js',Buffer.from('window.TabletStrings = '+buffers.get(path.join(root,'web/beta-i18n.json'))+';'));
const catalogs = {};
let active = '/* Generated from the live canonical catalogs. */\n';
for (const [p,b] of buffers) if (p.startsWith(desktop+'/i18n/')) {
  active += b.toString()+'\n';
  vm.runInNewContext(b.toString(),{window:{MagnolieI18n:{registerCatalog:(code,c)=>{catalogs[code.replace('_','-').toLowerCase()]=c.messages;}}}});
}
generated.set('assets/web/i18n-active.js',Buffer.from(active));
generated.set('assets/web/index.html',Buffer.from(html.replace('<script src="tablet.js">', '<script src="beta-i18n.js"></script>\n<script src="tablet.js">')));
const labels = {cancel:'Cancel', close:'Close', import_label:'Import', export_label:'Export',
  restore:'Restore', password:'Backup password', saved:'Saved.', failed:'Failed',
  save_failed:'Warning: The data could not be saved.', import_failed:'Import failed.',
  notifications:'Notifications', custom:'Custom', about:'About',
  replacement:'The current data will be backed up first and then completely replaced with this file:\n%(path)s'};
const beta = JSON.parse(buffers.get(path.join(root,'web/beta-i18n.json')));
const nativeStartup = JSON.parse(buffers.get(path.join(root,'web/native-startup-i18n.json')));
const nativeStartupKeys = ['webview_title','webview_body','webview_update','webview_settings','webview_retry','webview_no_update','webview_unknown_provider'];
if (Object.keys(nativeStartup).sort().join() !== Object.keys(beta).sort().join()) throw Error('All 20 native startup locales are required');
for (const [locale,strings] of Object.entries(nativeStartup)) {
  if (Object.keys(strings).sort().join() !== [...nativeStartupKeys].sort().join() || nativeStartupKeys.some(key=>typeof strings[key]!=='string' || !strings[key].trim()))
    throw Error('Incomplete native startup translation: '+locale);
}
if (Object.keys(beta).length !== 20) throw Error('All 20 beta locales are required');
const xml = s => '"'+s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','\\"').replaceAll("'","\\'").replaceAll('\n','\\n')+'"';
for (const [locale,strings] of Object.entries(beta)) {
  const catalog = catalogs[locale==='zh_CN'?'zh-cn':locale] || {};
  const values = {...Object.fromEntries(Object.entries(labels).map(([k,id])=> {
    if (locale !== 'en' && !catalog[id]) throw Error('Missing reused translation: '+locale+' / '+id);
    return [k,catalog[id] || id];
  })), unavailable:strings[0], limits:strings[1], ...nativeStartup[locale]};
  const qualifier = locale==='en' ? 'values' : locale==='zh_CN' ? 'values-zh-rCN' : 'values-'+locale;
  generated.set('res/'+qualifier+'/strings.xml',Buffer.from('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'+
    Object.entries(values).map(([k,v])=>'  <string name="'+k+'" formatted="false">'+xml(v)+'</string>').join('\n')+'\n</resources>\n'));
}
// Detect mid-projection edits before replacing the previous generated projection.
for (const [p,b] of buffers) if (!b.equals(fs.readFileSync(p))) throw Error('Source changed while projecting: '+p);
fs.mkdirSync(out,{recursive:true});
fs.rmSync(out,{recursive:true});
for (const [p,b] of generated) { const dest = path.join(out,p); fs.mkdirSync(path.dirname(dest),{recursive:true}); fs.writeFileSync(dest,b); }
const manifest = {format:1, kind:'debug-beta-generated-build-projection', sourceHash, inputs:hashes,
  transformations:['index: beta title, adapter and responsive stylesheet',
    'timezones: verified common normative data/resolver/runtime/license loaded synchronously before the adapter and app with hash-checked shared app/worker time-path adapters',
    'alarms: shared port-adapters helper preserves opaque DISPLAY properties/parameters and blocks ambiguous edits',
    'fonts: live Windows font-face rules, bundled font bytes and licenses (no Android system-font substitution)',
    'anwendung: expose existing editor guard + durable action queue; reuse canonical DAV account/selection renderers for native setup and read-only discovery with revision fences; keep synchronization unsupported; expose regional form and suppress unsupported native automatic time-zone polling',
    'i18n-active: concatenate canonical catalogs', 'native resources: reuse catalogs + 20 manual beta translations'],
  outputs:Object.fromEntries([...generated].map(([p,b])=>[p,sha(b)]))};
fs.writeFileSync(path.join(out,'assets/projection.json'),JSON.stringify(manifest,null,2)+'\n');
console.log('Generated desktop projection: '+sourceHash);
