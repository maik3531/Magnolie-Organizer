const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const consent = JSON.parse(fs.readFileSync(path.join(root, 'contracts/personal-custom-consent-v4-vectors.json'), 'utf8'));

(async () => {
  const outputs = [];
  for (const file of ['magnolie-organizer-2.0.0/web/anwendung.js', 'Magnolie-Organizer-Windows-2.0.0/app/web/anwendung.js']) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    new vm.Script(source, { filename: file });
    const helpers = source.slice(source.indexOf('  function personalSyncKanonisch('), source.indexOf('  function personalSyncAutoEntscheidung('));
    const sender = source.slice(source.indexOf('  let personalCustomKette ='), source.indexOf('  async function personalSyncSenden('));
    const sent = [], errors = []; let saves = 0;
    const data = { personalSync: { actor_id: consent.source_id }, einstellungen: { regional: { timeZone: 'America/New_York' }, erinnerung: { vorlauf: 15 } },
      customOrganizer: { modules: [
        { id: 'module-1', type: 'appointments', title: 'Garden', reminders: true, items: [
          { id: 'custom-item-1', title: 'Water plants', note: 'Own item note only', date: '2028-01-31', time: '09:00',
            textItemId: 'private-text', remind: true, wiederholung: { art: 'monthly' } }] },
        { id: 'module-2', type: 'tasks', title: 'Tasks', reminders: false, items: [
          { id: 'x'.repeat(160), title: 'Finished', due: '2028-02-01', done: true, remind: false }] },
        { id: 'module-text', type: 'notes', items: [{ id: 'private-text', text: 'DO NOT TRANSMIT', html: '<b>PRIVATE</b>' }] }
      ] } };
    const ctx = vm.createContext({ TextEncoder, crypto: webcrypto, DATEN: data, gesperrt: false, initialisiert: true,
      antwortErhalten: true, _: x => x, leseWiederholung: x => x || { art: 'none' },
      App: { personalSyncFehler: x => errors.push(x) },
      Bruecke: { sende: x => { assert(saves > 0); sent.push(JSON.parse(JSON.stringify(x))); } },
      nachDauerhaftemSpeichern: action => { saves++; action(); } });
    const zone = source.slice(source.indexOf('  function organizerZeitzone('), source.indexOf('  const ZEITZONEN_FORMATIERER'));
    ctx.personalCustomSenden = vm.runInContext(helpers + zone + sender + '\npersonalCustomSenden;', ctx);
    const acknowledge = vm.runInContext('personalCustomBestaetigt', ctx);
    const canonical = vm.runInContext('personalSyncKanonisch', ctx);
    assert.equal(canonical(JSON.parse('{"n":-0,"ordinal":-1}')), '{"n":0,"ordinal":-1}');
    assert.throws(() => canonical(JSON.parse('"\\ud800"')));
    assert.throws(() => canonical(JSON.parse('{"\\udfff":1}')));
    assert.equal(canonical(JSON.parse('"\\ud83d\\ude00"')), '"\ud83d\ude00"');
    const peer = { device_id: consent.other_source_id, own_device: true, remote_own_device: true, transport: 'wifi', auto_wifi: true,
      capabilities: { items: { personal_tasks_sync: { available: true, versions: [1, 2, 3, 4] } } },
      custom_sync: { local: consent.remote, remote: consent.local } };
    assert.equal(await ctx.personalCustomSenden({ ...peer, custom_sync: {} }, 'manual'), false);
    assert.equal(sent.length, 0);
    assert.equal(await ctx.personalCustomSenden(peer, 'manual'), true);
    const first = sent.at(-1).inhalt;
    assert.equal(first.upserts[0].value.timezone, 'America/New_York');
    assert.equal(first.upserts.length, 2);
    assert(!JSON.stringify(first).includes('DO NOT TRANSMIT'));
    assert(!JSON.stringify(first).includes('textItemId'));
    assert.equal(first.upserts[1].value.completed, true);
    assert.equal(first.upserts[1].value.module_reminders, false);
    const id = first.upserts[0].id;
    // Rename, module move and a serialized restart preserve the source-qualified identity.
    data.customOrganizer.modules[0].id = 'moved-module'; data.customOrganizer.modules[0].title = 'Renamed';
    data.personalSync = JSON.parse(JSON.stringify(data.personalSync));
    await ctx.personalCustomSenden(peer, 'manual');
    assert.equal(sent.at(-1).inhalt.upserts[0].id, id);
    assert.equal(sent.at(-1).inhalt.deletions.length, 0);
    const count = sent.length;
    await ctx.personalCustomSenden({ ...peer, custom_sync: { ...peer.custom_sync, local: consent.revoked } }, 'manual');
    assert.equal(sent.length, count);
    data.customOrganizer.modules[0].items = [];
    await ctx.personalCustomSenden(peer, 'manual');
    assert.equal(sent.at(-1).inhalt.deletions[0].id, id);
    assert.equal(sent.at(-1).inhalt.upserts.length, 1);
    outputs.push({ first, deletion: sent.at(-1).inhalt });
    data.einstellungen.regional.timeZone = 'system';
    await ctx.personalCustomSenden(peer, 'manual');
    assert.equal(sent.at(-1).inhalt.upserts[0].value.timezone, Intl.DateTimeFormat().resolvedOptions().timeZone);
    assert.equal(sent.at(-1).inhalt.upserts[0].value.default_minute, 480);
    // Change settings during the first asynchronous identity hash, not before capture.
    data.einstellungen.regional.timeZone = 'America/New_York';
    data.customOrganizer.modules[0].items = [{ id: 'async-item', date: '2026-09-15', time: '09:00' }];
    data.einstellungen.erinnerung.vorlauf = 15;
    let changed = false;
    ctx.crypto = { randomUUID: () => webcrypto.randomUUID(), subtle: { digest: (...args) => {
      if (!changed) { changed = true; data.einstellungen.regional.timeZone = 'Asia/Tokyo'; data.einstellungen.erinnerung.vorlauf = 90; }
      return webcrypto.subtle.digest(...args);
    } } };
    await ctx.personalCustomSenden(peer, 'manual');
    assert.equal(sent.at(-1).inhalt.upserts[0].value.timezone, 'America/New_York');
    assert.equal(sent.at(-1).inhalt.upserts[0].value.lead_minutes, 15);
    for (const invalid of ['Unknown/Shape', 'W. Europe Standard Time', '+01:00', 'GMT+01:00']) {
      data.einstellungen.regional.timeZone = invalid;
      const before = sent.length, saved = saves;
      await assert.rejects(ctx.personalCustomSenden(peer, 'auto_wifi'));
      assert.equal(sent.length, before); assert.equal(saves, saved);
      assert(errors.at(-1).fehler.includes(invalid));
    }
    data.einstellungen.regional.timeZone = 'Europe/Berlin';
    data.customOrganizer.modules = [{ id: 'mass', type: 'tasks', items: Array.from({ length: 201 }, (_, i) => ({ id: 'mass-' + i })) }];
    await ctx.personalCustomSenden(peer, 'manual');
    const offline = { ...peer, device_id: 'offline-peer' };
    await ctx.personalCustomSenden(offline, 'manual');
    data.customOrganizer.modules[0].items.length = 1;
    let start = sent.length;
    await ctx.personalCustomSenden(peer, 'manual');
    const deleted = sent.slice(start).map(x => x.inhalt);
    assert.equal(deleted.flatMap(x => x.deletions).filter(x => x.item_id.startsWith('mass-')).length, 200);
    const durableBeforeReceipt = JSON.stringify(data.personalSync);
    const saveNormally = ctx.nachDauerhaftemSpeichern;
    let finishSave;
    ctx.nachDauerhaftemSpeichern = action => { finishSave = action; };
    const receiptBeforeCrash = acknowledge({ device_id: peer.device_id, body: deleted[0] });
    await Promise.resolve(); await Promise.resolve();
    assert.equal(typeof finishSave, 'function');
    // Restart from the last durable snapshot, not from the ACK-mutated JS object.
    data.personalSync = JSON.parse(durableBeforeReceipt);
    finishSave(); await receiptBeforeCrash;
    ctx.nachDauerhaftemSpeichern = saveNormally;
    // Lost ACK + serialized restart: never age out source deletions.
    data.personalSync = JSON.parse(JSON.stringify(data.personalSync));
    start = sent.length;
    await ctx.personalCustomSenden(peer, 'manual');
    assert.equal(sent.slice(start).flatMap(x => x.inhalt.deletions).length, deleted.flatMap(x => x.deletions).length);
    for (const body of deleted) await acknowledge({ device_id: peer.device_id, body });
    assert.equal(Object.values(data.personalSync.custom_entities).filter(x => x.deleted_revision && x.item_id.startsWith('mass-')).length, 200);
    start = sent.length;
    await ctx.personalCustomSenden(offline, 'manual');
    for (const { inhalt: body } of sent.slice(start)) await acknowledge({ device_id: offline.device_id, body });
    // Remaining legacy deletions only belonged to the first peer and were ACKed above.
    assert.equal(Object.keys(data.personalSync.custom_entities).length, 1);
    for (let repeat = 0; repeat < 3; repeat++) {
      start = sent.length;
      await ctx.personalCustomSenden(peer, 'manual');
      assert.equal(sent.length - start, 1);
      assert.equal(sent.at(-1).inhalt.deletions.length, 0);
    }
    // A delayed receipt for an earlier deletion cannot retire a new same-hash deletion.
    data.customOrganizer.modules[0].items.push({ id: 'mass-1' });
    await ctx.personalCustomSenden(peer, 'manual');
    data.customOrganizer.modules[0].items.pop();
    await ctx.personalCustomSenden(peer, 'manual');
    for (const body of deleted) await acknowledge({ device_id: peer.device_id, body });
    assert.equal(Object.keys(data.personalSync.custom_entities).length, 2);
  }
  assert.deepEqual(outputs[0], outputs[1]);
  if (process.argv.includes('--emit')) console.log(JSON.stringify(outputs[0]));
  else console.log('Custom snapshots: both trees; 200 deletions, lost ACK/save, offline peer, retirement, stale receipt, invalid-zone error, canonical edges and snapshot identity passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
