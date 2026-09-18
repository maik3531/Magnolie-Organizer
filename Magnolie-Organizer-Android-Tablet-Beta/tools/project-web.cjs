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
const generated = new Map();
for (const [p,b] of buffers) if (p.startsWith(desktop + path.sep)) generated.set('assets/web/'+path.relative(desktop,p),b);
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
const appSource = buffers.get(path.join(desktop,'anwendung.js')).toString();
const anchor = '  window.App = App;';
if (appSource.split(anchor).length !== 2) throw Error('Desktop adapter anchor changed');
generated.set('assets/web/anwendung.js', Buffer.from(appSource.replace(anchor,
  '  window.MagnolieTabletActions = { afterSave: action => navigiereMitGuard(() => nachDauerhaftemSpeichern(action)) };\n'+anchor)));
let html = buffers.get(path.join(desktop,'index.html')).toString();
if (!html.includes('<script src="anwendung.js"></script>')) throw Error('Desktop entry point changed');
html = html.replace('<title>Magnolie Organizer</title>', '<title>Magnolie Organizer Android Tablet Beta 2.0.18Beta</title>')
  .replace('</head>', '<link rel="stylesheet" href="desktop-fonts.css">\n<link rel="stylesheet" href="tablet.css">\n<script src="tablet.js"></script>\n</head>');
generated.set('assets/web/index.html',Buffer.from(html));
for (const f of ['tablet.js','tablet.css']) generated.set('assets/web/'+f,buffers.get(path.join(root,'web',f)));
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
if (Object.keys(beta).length !== 20) throw Error('All 20 beta locales are required');
const xml = s => '"'+s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','\\"').replaceAll("'","\\'").replaceAll('\n','\\n')+'"';
for (const [locale,strings] of Object.entries(beta)) {
  const catalog = catalogs[locale==='zh_CN'?'zh-cn':locale] || {};
  const values = {...Object.fromEntries(Object.entries(labels).map(([k,id])=> {
    if (locale !== 'en' && !catalog[id]) throw Error('Missing reused translation: '+locale+' / '+id);
    return [k,catalog[id] || id];
  })), unavailable:strings[0], limits:strings[1]};
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
    'fonts: live Windows font-face rules, bundled font bytes and licenses (no Android system-font substitution)',
    'anwendung: expose existing editor guard + durable action queue without changing either implementation',
    'i18n-active: concatenate canonical catalogs', 'native resources: reuse catalogs + 20 manual beta translations'],
  outputs:Object.fromEntries([...generated].map(([p,b])=>[p,sha(b)]))};
fs.writeFileSync(path.join(out,'assets/projection.json'),JSON.stringify(manifest,null,2)+'\n');
console.log('Generated desktop projection: '+sourceHash);
