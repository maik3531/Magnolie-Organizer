import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { boot, tick } from './ui_harness.mjs';
const fixture = JSON.parse(fs.readFileSync(new URL('../Tests/BetaCoreTests/Fixtures/dav-book-restore.json', import.meta.url), 'utf8'));
const { expected } = fixture;
const host = await boot(process.argv[2]);
try {
  host.w.MacBeta.receive('init', { daten: expected, neu: false, regional: { language: 'en', timeZone: 'UTC' } });
  const normalized = JSON.parse(JSON.stringify(host.t.daten()));
  assert.deepEqual(normalized.syncMetadaten.quarantinedDeletes, expected.syncMetadaten.quarantinedDeletes);
  assert.equal(normalized.syncEpoch, fixture.newEpoch);
  assert.equal(normalized.syncMetadaten.syncEpoch, fixture.newEpoch);
  assert.equal(normalized.syncMetadaten.ersteSyncLoeschungsfrei, true);
  assert.equal(normalized.einstellungen.sync.syncEpoch, fixture.newEpoch, 'Mac opaque-field preservation retains optional settings copy');
  // Exercise the unchanged canonical desktop normalizer, disabling only the port's outer
  // unknown-field preservation for this call. No normalizer implementation is copied.
  const adapter = host.w.MacBeta;
  let canonical;
  try {
    host.w.MacBeta = { ...adapter, preserve: (_source, result) => result };
    canonical = host.t.normalisiere(expected);
  } finally { host.w.MacBeta = adapter; }
  assert.equal(canonical.einstellungen.sync.syncEpoch, fixture.newEpoch, 'canonical bewahreUnbekannteFelder retains present optional settings copy');
  assert.equal(canonical.syncEpoch, fixture.newEpoch);
  assert.equal(canonical.syncMetadaten.syncEpoch, fixture.newEpoch);
  assert.deepEqual(JSON.parse(JSON.stringify(canonical.syncMetadaten.quarantinedDeletes)), expected.syncMetadaten.quarantinedDeletes);
  assert.deepEqual(normalized.geloescht, { termine: [], aufgaben: [], kontakte: [] });
  assert.equal(normalized.syncMetadaten.nextcloud.pendingCommitId, undefined);
  assert.equal(normalized.syncMetadaten.nextcloud.ausstehendeTransaktion, undefined);
  assert.deepEqual(normalized.syncMetadaten.nextcloud.transaktionen, {});
  const absent = structuredClone(expected);
  delete absent.einstellungen.sync.syncEpoch;
  const legacy = host.t.normalisiere(absent);
  assert.equal(legacy.einstellungen.sync.syncEpoch, undefined);
  assert.equal(legacy.syncEpoch, fixture.newEpoch);
  assert.equal(legacy.syncMetadaten.syncEpoch, fixture.newEpoch);
  host.t.speichereJetzt();
  const save = host.messages.filter(message => message.cmd === 'speichern').at(-1);
  assert.ok(save, 'actual canonical save serializer executed');
  const saved = JSON.parse(save.text);
  assert.deepEqual(saved.syncMetadaten.quarantinedDeletes, expected.syncMetadaten.quarantinedDeletes);
  assert.equal(saved.einstellungen.sync.syncEpoch, fixture.newEpoch);
  if (process.argv[3]) {
    fs.writeFileSync(process.argv[3], JSON.stringify({ version: 1, issue: 454, canonicalSourceSHA256: createHash('sha256').update(fs.readFileSync(new URL('../../magnolie-organizer/web/anwendung.js', import.meta.url))).digest('hex'), description: 'Extracted proof fields from actual canonical normalizer+save serializer, including bewahreUnbekannteFelder.', savedBinding: {
      syncEpoch: saved.syncEpoch, syncMetadaten: { syncEpoch: saved.syncMetadaten.syncEpoch, quarantinedDeletes: saved.syncMetadaten.quarantinedDeletes },
      einstellungen: { sync: { syncEpoch: saved.einstellungen.sync.syncEpoch } }
    } }, null, 2) + '\n');
  }
  console.log('DAV restore shared fixture: actual projected canonical normalizer retains quarantine and epoch; synthetic native transport, no GUI/disk-sync claim.');
} finally { await tick(); host.close(); }
