const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const assert = require('node:assert/strict');
const repo = path.resolve(__dirname, '../..');
const {JSDOM} = require(repo + '/Magnolie-Organizer-Windows-2.0.0/node_modules/jsdom');
const root = process.env.CONTACT_INTEROP_HOME;
assert.ok(root?.startsWith('/tmp/opencode/'));
const clone = x => JSON.parse(JSON.stringify(x));
let checks = 0;
const windowsToClose = [];
function check(ok, name) { assert.ok(ok, name); checks++; }
function peer(command, args) {
  const child = spawn(command, args, {env: {...process.env, CONTACT_REPO: repo}, stdio: ['pipe', 'pipe', 'inherit']});
  const pending = [];
  createInterface({input: child.stdout}).on('line', line => {
    const next = pending.shift(); if (next) next(JSON.parse(line));
  });
  child.on('exit', code => { while (pending.length) pending.shift()({error: 'adapter exited ' + code}); });
  const raw = request => new Promise(resolve => { pending.push(resolve); child.stdin.write(JSON.stringify(request) + '\n'); });
  return {raw, child, async call(op, data, text, extra = {}) {
    const r = await raw({op, data, text, ...extra}); assert.ok(!r.error, r.error); return r.value;
  }};
}
const linux = peer('/usr/bin/python3', [__dirname + '/linux.py']);
const windows = peer('/tmp/opencode/dotnet-8.0.408/dotnet', [process.env.CONTACT_WINDOWS_DLL]);
const android = peer('bash', [__dirname + '/android.sh']);
const peers = [linux, windows, android];
async function transfer(from, to, content, expected = 200) {
  const start = await from.call('start');
  const response = await to.call('request', start, '/magnolie/v2/sitzung');
  check(response.Status === 200, 'authenticated native FS1 session');
  const envelope = await from.call('message', response.Body, '', {content});
  const result = await to.call('request', envelope, '/magnolie/v2/nachricht');
  check(result.Status === expected, 'native receive status ' + expected + ': ' + JSON.stringify(result));
  if (expected === 200) check(await from.call('ack', result.Body), 'native authenticated ACK');
  return envelope;
}
function web(platform, bridge = false) {
  const dir = repo + (platform === 'Linux' ? '/magnolie-organizer-2.0.0/web' : '/Magnolie-Organizer-Windows-2.0.0/app/web');
  const dom = new JSDOM(fs.readFileSync(dir + '/index.html', 'utf8'), {runScripts: 'outside-only', url: 'https://contact-interop.invalid', pretendToBeVisual: true});
  const w = dom.window; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w.crypto, 'subtle', {value: require('node:crypto').webcrypto.subtle});
  const messages = [];
  if (bridge) w.webkit = {messageHandlers: {bridge: {postMessage: text => messages.push(JSON.parse(text))}}};
  windowsToClose.push(w);
  w.eval(fs.readFileSync(dir + '/i18n.js', 'utf8')); w.eval(fs.readFileSync(dir + '/anwendung.js', 'utf8'));
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  const t = w.OrganizerTest;
  const reset = () => { Object.assign(t.daten(), t.normalisiere({})); t.planeSpeichern(); };
  const save = () => {
    t.speichereJetzt();
    const stored = Object.keys(w.localStorage).map(k => { try { return JSON.parse(w.localStorage.getItem(k)); } catch { return null; } })
      .find(x => x && Array.isArray(x.kontakte) && Array.isArray(x.termine));
    assert.ok(stored, 'actual web save'); Object.assign(t.daten(), t.normalisiere(stored)); return clone(t.daten());
  };
  return {w, t, reset, save, messages, close: () => dom.window.close(), import: payload => w.App.importErgebnis(w.JSON.parse(JSON.stringify(payload)))};
}
const cases = [
  ['first', 'N:;Anna Maria;;;', 'FN:Anna Maria'],
  ['family', 'N:Van Dame;;;;', 'FN:Van Dame'],
  ['display', 'FN:The Club Contact'],
  ['emptyN', 'N:;;;;', 'FN:The Club Contact'],
  ['emptyFn', 'N:;Anna;;;', 'FN:'],
  ['missingFn', 'N:;Anna;;;'],
  ['distinct', 'N:Smith;Robert;;;', 'FN:Bob Smith'],
  ['all', 'N:de la Cruz;Maria;Elena;Dr.;Jr.', 'FN:Dr. Maria Elena de la Cruz Jr.'],
  ['commas', 'N:Smith,Jones;Anna,Maria;;;', 'FN:Anna Maria Smith Jones'],
  ['escaped', 'N:Smith\\,Jones;Anna\\,Maria;;;', 'FN:Anna\\,Maria Smith\\,Jones'],
  ['parameters', 'N;LANGUAGE=en;SORT-AS="Family:Given":Family;Given;Middle;Dr.;III', 'FN;LANGUAGE=en:Given Middle Family', 'FN;LANGUAGE=de:Alternative Name']
];
const card = fields => ['BEGIN:VCARD', 'VERSION:4.0', ...fields, 'END:VCARD', ''].join('\r\n');
const base = {art: 'kontakt_sync', fassung: 2, freigabeId: 'synthetic', version: 1, quelle: 'synthetic-source', geaendert: 1,
  kontakt: {vorname: '', nachname: 'Van Dame', firma: '', notiz: '', geburtstag: '--02-29', jubilaeum: '--06-07',
    anzeigename: 'Club contact', vcardName: ['N:Van Dame;;;;', 'FN:Club contact'], telefone: [], emailEintraege: [], anschriften: []}};
(async () => {
  const schema = JSON.parse(fs.readFileSync(repo + '/contracts/kontakt-v2.schema.json', 'utf8'));
  check(JSON.stringify([...schema.$defs.contact.required].sort()) === JSON.stringify(Object.keys(base.kontakt).sort()), 'shared schema exact v2 field set');
  const locales = JSON.parse(fs.readFileSync(repo + '/Magnolie-Organizer-Windows-2.0.0/app/native-i18n.json', 'utf8')).locales;
  for (const [language, messages] of Object.entries(locales)) for (const id of [
    'Not sent.', 'The data is invalid.', 'Conflict'])
    check(typeof messages[id] === 'string' && messages[id].length > 0, 'existing translated error ' + language + ': ' + id);
  const identities = await Promise.all([linux.call('init'), windows.call('init')]);
  await linux.call('pair', identities[1]); await windows.call('pair', identities[0]);
  const caps = await linux.call('capabilities');
  const forged = {...await linux.call('start'), mac: Buffer.alloc(32).toString('base64')};
  check((await windows.call('request', forged, '/magnolie/v2/sitzung')).Status === 403, 'forged session rejected');
  const oldPeer = {bestaetigt: true};
  for (const p of [linux, windows]) check(!(await p.call('status')).partner[0].kontaktFaehigkeiten, 'no discovery capability');
  const replay = await transfer(linux, windows, caps);
  check(!(await linux.call('status')).partner[0].kontaktFaehigkeiten, 'ACK does not imply capability');
  check((await windows.call('request', replay, '/magnolie/v2/nachricht')).Status === 403, 'replay cannot reapply capabilities');
  const replies = await windows.call('outbox');
  check(replies.length === 1 && replies[0].inhalt.antwort === true, 'receiver durably queues one response');
  await transfer(windows, linux, replies[0].inhalt);
  check((await linux.call('outbox')).length === 0, 'capability response does not loop');
  for (const p of [linux, windows]) {
    const partner = await p.call('restart');
    check(partner.kontaktFaehigkeiten.kontakt_sync.includes(2) && !partner.vertraut && !partner.kontakte, 'authenticated capabilities persist without granting consent');
    check((await p.call('for-peer', base, '', {peer: partner})).fassung === 2, 'new peer gets v2');
    check(!!(await p.raw({op: 'for-peer', data: base, peer: oldPeer})).error, 'legacy rejects loss, not partial stripping');
  }
  for (const p of peers) {
    check(await p.call('validate', base), 'strict v2 accepted');
    for (const field of ['jubilaeum', 'anzeigename', 'vcardName']) {
      const bad = clone(base); delete bad.kontakt[field];
      const r = await p.raw({op: 'validate', data: bad}); check(!!r.error || r.value === false, 'required field ' + field);
    }
    for (const value of [1, true, '2', 2.5, 3]) {
      const r = await p.raw({op: 'validate', data: {...base, fassung: value}}); check(!!r.error || r.value === false, 'strict version ' + value);
    }
    for (const patch of [{version: '1'}, {freigabeId: 123}, {geaendert: '0'},
      {kontakt: {...base.kontakt, telefone: [{art: 'home', wert: 123}]}},
      {kontakt: {...base.kontakt, vcardName: ['UID:not-a-name']}},
      {kontakt: {...base.kontakt, vcardName: ['FN:one\nN:two'] }},
      {kontakt: {...base.kontakt, jubilaeum: '--02-30'}},
      {kontakt: {...base.kontakt, jubilaeum: '0000-02-29'}},
      {kontakt: {...base.kontakt, unknown: 'field'}}]) {
      const r = await p.raw({op: 'validate', data: {...base, ...patch}}); check(!!r.error || r.value === false, 'strict v2 value types and dates');
    }
    for (const patch of [{antwort: 'false'}, {adresse: '192.0.2.1'}, {kontakt_sync: [true, 2]}, {kontakt_sync: [2, 1]}]) {
      const r = await p.raw({op: 'validate', data: {...caps, ...patch}}); check(!!r.error || r.value === false, 'strict capabilities');
    }
  }
  const legacy = clone(base); legacy.fassung = 1;
  for (const field of ['jubilaeum', 'anzeigename', 'vcardName']) delete legacy.kontakt[field];
  for (const p of peers) check(await p.call('validate', legacy), 'v1 unchanged');
  const representable = clone(base); Object.assign(representable.kontakt, {jubilaeum: '', anzeigename: 'Van Dame', vcardName: ['N:Van Dame;;;;', 'FN:Van Dame']});
  for (const p of [linux, windows]) check((await p.call('for-peer', representable, '', {peer: oldPeer})).fassung === 1, 'representable legacy fallback');
  const androidCaps = await android.call('capabilities');
  check(androidCaps.kontakt_import.length === 0, 'Android only receives contact sync');
  await transfer(linux, windows, {...caps, kontakt_sync: [1], kontakt_import: [1]});
  check((await windows.call('restart')).kontaktFaehigkeiten.kontakt_sync.length === 1, 'authenticated downgrade persisted');
  await transfer(linux, windows, caps);
  const badCaps = {...caps, antwort: 1};
  await transfer(windows, linux, badCaps, 403);
  check((await linux.call('status')).partner[0].kontaktFaehigkeiten.kontakt_sync.includes(2), 'malformed capability did not overwrite');
  const evidence = [];
  const externalCards = [];
  const emittedVCard = (text, format) => format === 'vcf' ? text : Buffer.from(
    text.replace(/\r?\n /g, '').match(/^magnolieVCard:: ([^\r\n]+)$/mi)[1], 'base64').toString('utf8');
  for (const [platform, native, other] of [['Linux', linux, windows], ['Windows', windows, linux]]) {
    const ui = web(platform);
    for (const [value, parameter, expected] of [['--0229', '', '--02-29'], ['--0607', '', '--06-07'],
      ['1604-02-29', ';X-APPLE-OMIT-YEAR=1604', '--02-29'], ['1604-02-29', '', '1604-02-29']]) {
      const parsed = await native.call('vcf', null, card(['UID:date-fixture', 'N:Van Dame;;;;', 'FN:Club contact',
        'BDAY' + parameter + ':' + value, 'ANNIVERSARY' + parameter + ':' + value]));
      ui.reset(); ui.import(parsed); const saved = ui.save();
      for (const format of ['vcf', 'ldif']) {
        const exported = await native.call('write-' + format, saved.kontakte);
        externalCards.push({platform, format, id: 'date', text: emittedVCard(exported, format), expected: clone(saved.kontakte[0])});
        const returned = await other.call(format, null, exported);
        check(returned.kontakte[0].geburtstag === expected && returned.kontakte[0].jubilaeum === expected,
          'yearless/leap/explicit omit-year/real 1604 cross-platform ' + format);
      }
    }
    for (const [id, ...names] of cases) {
      const text = card(['UID:urn:synthetic:' + id, ...names, 'ORG:Example;Division', 'BDAY:--02-29', 'ANNIVERSARY:--06-07',
        'EMAIL;TYPE=HOME;PREF=1:a@example.test', 'EMAIL;TYPE=WORK;PREF=2:work@example.test',
        'TEL;TYPE=CELL:+4912345678', 'TEL;TYPE=WORK:+49301234567',
        'ADR;TYPE=WORK:PO42;Suite 7;Main Street;Town;Region;12345;Country', 'X-SYNTHETIC:opaque',
        'PHOTO:data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ9kAAAAASUVORK5CYII=']);
      const parsed = await native.call('vcf', null, text); ui.reset(); ui.import(parsed);
      const saved = ui.save(); check(saved.kontakte.length === 1 && saved.jahrestage.length === 2, platform + ' F30 linked occasions only ' + id);
      const original = saved.kontakte[0];
      check(original.emailEintraege.length === 2 && original.telefone.length === 2, 'communication fixtures must not be filtered into empty expectations');
      for (const format of ['vcf', 'ldif']) {
        const exported = await native.call('write-' + format, saved.kontakte);
        externalCards.push({platform, format, id, text: emittedVCard(exported, format), expected: clone(original)});
        if (format === 'ldif') check(/magnolieVCard::/i.test(exported) && !/magnolieVCardN:/i.test(exported), 'canonical LDIF extension');
        const reparsed = await other.call(format, null, exported);
        const k = reparsed.kontakte[0];
        for (const field of ['uid', 'vorname', 'nachname', 'anzeigename', 'firma', 'geburtstag', 'jubilaeum'])
          check(k[field] === original[field], platform + ' -> other ' + format + ' ' + id + ' ' + field);
        check(k.anschriften[0].postfach === 'PO42' && k.anschriften[0].zusatz === 'Suite 7', 'full ADR retained');
        check(k.vcardRoundtrip.some(s => s === 'X-SYNTHETIC:opaque'), 'opaque property retained');
        const back = await other.call('write-vcf', reparsed.kontakte);
        for (const line of names) check(back.includes(line), 'all N/FN syntax retained: ' + line);
        ui.import(reparsed); ui.import(reparsed);
        const repeated = ui.save();
        check(repeated.kontakte.length === 1 && repeated.jahrestage.length === 2, 'second/third import stays unique');
      }
      if (id === 'all') {
        const newer = {...original, geaendert: Date.now() + 10000, anzeigename: original.anzeigename.replace('Dr.', 'Prof.'),
          vcardRoundtrip: original.vcardRoundtrip.map(s => s.replace('Dr.', 'Prof.'))};
        ui.import({art: 'vcf', kontakte: [newer]});
        const result = await other.call('vcf', null, await native.call('write-vcf', ui.save().kontakte));
        check(result.kontakte[0].vcardRoundtrip.filter(s => /^N[;:]/.test(s)).length === 1 &&
          result.kontakte[0].vcardRoundtrip.some(s => /^N[;:]/.test(s) && s.includes('Prof.')), 'newer UID revision replaces primary N instead of accumulating stale name variants');
      }
      const payload = clone(ui.t.kontaktBaumInhalt({...original, baumKontakt: {freigabeId: id, version: 1, quelle: 'source', geaendert: 1}}));
      const androidWire = await android.call('roundtrip', payload);
      for (const p of [native, other]) check(await p.call('validate', androidWire), 'Android generated DTO -> native v2');
      ui.reset();
      check(ui.t.uebernehmeBaumAngebot({von: 'peer', inhalt: ui.w.JSON.parse(JSON.stringify(androidWire))}), 'native web contact acceptance');
      const received = ui.save().kontakte[0];
      check(received.anzeigename === original.anzeigename && received.jubilaeum === '--06-07', 'v2 web save retains names and anniversary');
      check(ui.t.uebernehmeBaumAngebot({von: 'peer', inhalt: ui.w.JSON.parse(JSON.stringify(androidWire))}), 'sync repeated idempotently');
      check(ui.save().kontakte.length === 1 && ui.save().jahrestage.length === 2, 'sync does not duplicate occasions');
      const updated = clone(androidWire); updated.version++; updated.kontakt.jubilaeum = '--06-08';
      check(await android.call('hash', updated) !== await android.call('hash', androidWire), 'anniversary changes Android hash');
      check(ui.t.uebernehmeBaumAngebot({von: 'peer', inhalt: ui.w.JSON.parse(JSON.stringify(updated))}), 'bound anniversary-only revision accepted');
      check(ui.save().kontakte[0].jubilaeum === '--06-08', 'anniversary-only revision persisted');
      const birthdayUpdate = clone(updated); birthdayUpdate.version++; birthdayUpdate.kontakt.geburtstag = '--04-01';
      check(ui.t.uebernehmeBaumAngebot({von: 'peer', inhalt: ui.w.JSON.parse(JSON.stringify(birthdayUpdate))}), 'birthday-only bound revision accepted');
      check(ui.save().kontakte[0].geburtstag === '--04-01' && ui.save().kontakte[0].jubilaeum === '--06-08', 'birthday and anniversary revisions stay independent');
      ui.t.daten().kontakte[0].jubilaeum = '--12-31';
      const beforeConflict = clone(ui.t.daten().kontakte[0]);
      const conflict = clone(birthdayUpdate); conflict.version++; conflict.kontakt.jubilaeum = '--06-10'; conflict.kontakt.firma = 'Must not partially apply';
      check(!ui.t.uebernehmeBaumAngebot({von: 'peer', inhalt: ui.w.JSON.parse(JSON.stringify(conflict))}), 'concurrent anniversary values are a contact-group conflict');
      check(JSON.stringify(clone(ui.t.daten().kontakte[0])) === JSON.stringify(beforeConflict), 'conflict leaves the entire local contact untouched');
      const binding = 'urn:magnolie:import:android:' + 'a'.repeat(64);
      const origin = {kontoTyp: 'synthetic', kontoName: 'test', dataSet: ''};
      const importCard = {art: 'kontakt_import_karte', fassung: 2, importId: 'import', bindung: binding, herkuenfte: [origin], kontakt: androidWire.kontakt};
      for (const p of [linux, windows]) check(await p.call('validate', importCard), 'strict v2 import card');
      ui.reset();
      for (let i = 0; i < 3; i++) ui.import({kontakte: [ui.t.androidImportKontakt(ui.w.JSON.parse(JSON.stringify(importCard)))], art: 'vcf'});
      check(ui.save().kontakte.length === 1, 'one-time binding prevents second/third duplicates');
      if (id === 'first') {
        const manifest = {art: 'kontakt_import_manifest', fassung: 2, importId: 'preview', anzahl: 1, herkuenfte: [{...origin, anzahl: 1}]};
        const previewCard = {...importCard, importId: 'preview'};
        for (const p of [linux, windows]) check(await p.call('validate', manifest), 'strict import manifest');
        const inbox = [{id: 'manifest', von: 'peer', inhalt: manifest}, {id: 'card', von: 'peer', inhalt: previewCard}];
        ui.t.zeigeKontaktImportAngebot(clone([{...inbox[0]}, {...inbox[1], inhalt: {...previewCard, fassung: 1}}]));
        check(!ui.w.document.querySelector('.kontakt-import-schleier'), 'mismatched manifest/card versions do not preview');
        ui.reset(); ui.t.zeigeKontaktImportAngebot(clone(inbox));
        check(!!ui.w.document.querySelector('.kontakt-import-schleier') && ui.t.daten().kontakte.length === 0, 'preview does not import before consent');
        ui.w.document.querySelector('.kontakt-import-schleier .hauptknopf').click();
        check(ui.save().kontakte.length === 1 && ui.save().kontakte[0].jubilaeum === '--06-07', 'confirmed v2 preview uses real web save');
      }
      evidence.push({platform, id, payload, androidWire, contact: ui.save().kontakte[0]});
    }
    ui.reset();
    ui.import({art: 'ics', jahrestage: [{name: 'Standalone birthday', datum: '--02-29', typ: 'birthday'}]});
    check(ui.save().jahrestage.length === 1 && ui.save().kontakte.length === 0, 'standalone birthday is not suppressed');
    ui.close();
    const legacyContact = {uid: 'urn:synthetic:legacy-full', vorname: 'Legacy', nachname: 'Full', anzeigename: 'Legacy Full',
      geburtstag: '1980-02-29', foto: 'data:image/jpeg;base64,/9j/2Q=='};
    for (const format of ['vcf', 'ldif']) {
      const text = emittedVCard(await native.call('write-' + format, [legacyContact]), format);
      check(text.includes('VERSION:3.0\r\n') && text.includes('BDAY:1980-02-29\r\n'), 'representable full birthday retains legal v3 output');
      externalCards.push({platform, format, id: 'legacy-full', text, expected: legacyContact});
    }
    const sender = web(platform, true);
    const setPeer = version => sender.w.App.baumStand({an: true, kennung: 'self', partner: [{kennung: 'peer', bestaetigt: true,
      kontaktFaehigkeiten: version === 2 ? caps : undefined}], eingang: []});
    setPeer(2); Object.assign(sender.t.daten(), sender.t.normalisiere({kontakte: [{...base.kontakt, vcardRoundtrip: base.kontakt.vcardName}]}));
    check(await sender.t.synchronisiereKontakteMit('peer'), 'frontend starts negotiated contact operation');
    const sent = () => sender.messages.filter(m => m.cmd === 'baum_teilen' && m.art === 'kontakt_sync');
    const firstRevision = sent()[0].inhalt.version;
    check(/^[0-9a-f]{64}$/.test(sender.t.daten().kontakte[0].baumKontakt.hash), 'desktop revision stores SHA-256, not duplicated photo content');
    check(sent()[0].inhalt.fassung === 2 && sent()[0].inhalt.kontakt.jubilaeum === '--06-07', 'actual native bridge payload uses v2');
    Object.assign(sender.t.daten(), sender.t.normalisiere(clone(sender.t.daten())));
    await sender.t.synchronisiereKontakteMit('peer');
    check(sent().at(-1).inhalt.version === firstRevision, 'unchanged projection survives normalizer/reload without revision churn');
    sender.t.daten().kontakte[0].jubilaeum = '--06-09'; await sender.t.synchronisiereKontakteMit('peer');
    check(sent().at(-1).inhalt.version === firstRevision + 1, 'anniversary-only edit advances desktop revision');
    sender.t.daten().kontakte[0].anzeigename = 'Name-only edit'; await sender.t.synchronisiereKontakteMit('peer');
    check(sent().at(-1).inhalt.version === firstRevision + 2, 'name-only edit advances desktop revision');
    const beforeLegacy = sent().length; setPeer(1);
    sender.t.daten().kontakte.unshift(sender.t.normalisiere({kontakte: [{vorname: 'Legacy safe'}]}).kontakte[0]);
    check(!await sender.t.synchronisiereKontakteMit('peer') && sent().length === beforeLegacy, 'legacy preflight blocks entire snapshot before its first safe contact');
    check(sender.messages.some(m => m.art === 'kontakt_faehigkeiten'), 'legacy operation sends a capability probe, not partial contact content');
    sender.close();
  }
  await transfer(linux, windows, base);
  check((await windows.call('status')).eingang.some(x => x.inhalt.fassung === 2 && x.inhalt.kontakt.jubilaeum === '--06-07'), 'native authenticated sync -> persisted inbox');
  const androidIdentity = await android.call('init');
  for (const native of [linux, windows]) {
    const identity = await native.call('init'); await native.call('pair', androidIdentity); await android.call('pair', identity);
    await transfer(android, native, androidCaps);
    const partner = (await native.call('status')).partner[0];
    check(partner.kontaktFaehigkeiten.kontakt_import.length === 0, 'authenticated Android capability records receiving direction');
    await transfer(native, android, (await native.call('outbox')).at(-1).inhalt);
    await transfer(native, android, await native.call('for-peer', base, '', {peer: partner}));
    check((await android.call('received')).at(-1).kontakt.anzeigename === base.kontakt.anzeigename, 'desktop -> Android actual FS1 and v2 codec');
    const imports = await android.call('import', base);
    for (const message of imports) { check(await native.call('validate', message), 'actual Android import codec'); await transfer(android, native, message); }
    const ui = web(native === linux ? 'Linux' : 'Windows');
    ui.w.App.baumStand(await native.call('status'));
    check(!!ui.w.document.querySelector('.kontakt-import-schleier'), 'Android native import -> authenticated desktop inbox -> web preview');
    ui.w.document.querySelector('.kontakt-import-schleier .hauptknopf').click();
    check(ui.save().kontakte[0].anzeigename === base.kontakt.anzeigename, 'Android authenticated import consent saves independent name');
    ui.close();
    const reverseImport = await native.raw({op: 'for-peer', peer: partner, data: {...imports[0], fassung: 1}});
    check(!!reverseImport.error, 'advertised import [] is not treated as v1 receiving support');
  }
  for (const native of [linux, windows]) {
    const accepted = await native.call('queue-compat', legacy, 'reject-probe');
    check(accepted.observed.includes('kontakt_sync') && accepted.report.zugestellt === 1, 'an old peer rejecting probes still receives representable v1 contact in the same operation');
    const refused = await native.call('queue-compat', legacy, 'reject-contact');
    check(refused.report.zugestellt === 0 && refused.outbox.some(x => x.art === 'kontakt_sync'), 'a capability ACK cannot masquerade as contact delivery');
  }
  check(await windows.call('core-contacts'), 'existing Windows contact contract tests');
  const external = await require('./thunderbird-check.js').run(externalCards);
  check(external.import.imported.length === externalCards.length, 'Thunderbird imported every emitted card');
  const dateParts = value => !value ? ['', '', ''] : value.startsWith('--')
    ? ['', String(Number(value.slice(2, 4))), String(Number(value.slice(5, 7)))]
    : [String(Number(value.slice(0, 4))), String(Number(value.slice(5, 7))), String(Number(value.slice(8, 10)))];
  async function checkThunderbird(actual, sample) {
    const expected = sample.expected;
    check(actual.uid === expected.uid && actual.first === expected.vorname && actual.last === expected.nachname &&
      actual.display === expected.anzeigename, 'Thunderbird preserves independent N/FN and original UID');
    check(JSON.stringify(actual.birthday) === JSON.stringify(dateParts(expected.geburtstag)) &&
      JSON.stringify(actual.anniversary) === JSON.stringify(dateParts(expected.jubilaeum)), 'Thunderbird stores real month/day and an absent year, not a guessed year');
    for (const native of [linux, windows]) {
      const returned = (await native.call('vcf', null, actual.vcard)).kontakte[0];
      for (const field of ['uid', 'vorname', 'nachname', 'anzeigename', 'geburtstag', 'jubilaeum', 'foto', 'firma'])
        check((returned[field] || '') === (expected[field] || ''), sample.platform + '/' + sample.format + '/' + sample.id + ': Thunderbird re-export -> desktop preserves ' + field);
      if (sample.id !== 'date' && sample.id !== 'legacy-full') {
        for (const field of ['telefone', 'emailEintraege'])
          check(JSON.stringify(returned[field].map(item => item.wert)) === JSON.stringify(expected[field].map(item => item.wert)),
            'Thunderbird preserves every phone/email value and its order');
        check(returned.anschriften[0].postfach === 'PO42' && returned.anschriften[0].zusatz === 'Suite 7' &&
          returned.anschriften[0].region === 'Region', 'Thunderbird preserves full address components');
        check(returned.vcardRoundtrip.includes('X-SYNTHETIC:opaque'), 'Thunderbird preserves opaque extensions');
      }
    }
    if (sample.id === 'all' || sample.id === 'parameters') {
      const n = actual.entries.find(entry => entry.name === 'n').value;
      check(JSON.stringify(n.slice(2)) === JSON.stringify(sample.id === 'all' ? ['Elena', 'Dr.', 'Jr.'] : ['Middle', 'Dr.', 'III']),
        'Thunderbird retains additional names, prefix and suffix');
    }
  }
  for (let index = 0; index < externalCards.length; index++) await checkThunderbird(external.import.imported[index], externalCards[index]);
  const latest = new Map(externalCards.map(card => [card.expected.uid, card]));
  check(external.reload.saved.length === latest.size, 'Thunderbird SQLite restart retains the complete unique contact set');
  for (const stored of external.reload.saved) await checkThunderbird(stored, latest.get(stored.uid));
  console.log('PASS Thunderbird ' + externalCards.length + ' emitted cards and ' + latest.size + ' unique contacts after SQLite/process restart');
  fs.writeFileSync(root + '/evidence.json', JSON.stringify({checks, evidence, externalCards}, null, 2));
  console.log('PASS ' + checks + ' contact interop assertions; evidence: ' + root + '/evidence.json');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
  windowsToClose.forEach(w => w.close()); peers.forEach(p => p.child.kill());
});
