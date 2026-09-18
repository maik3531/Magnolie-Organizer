// Execute the actual contract functions from both desktop entry points.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { webcrypto } = require('node:crypto');
const vm = require('node:vm');
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname,
  '../../contracts/personal-custom-consent-v4-vectors.json'), 'utf8'));

(async () => {
  for (const file of ['../app/web/anwendung.js', '../../magnolie-organizer/web/anwendung.js']) {
    const source = fs.readFileSync(path.join(__dirname, file), 'utf8');
    const start = source.indexOf('  function personalSyncKanonisch(');
    const end = source.indexOf('  function personalSyncAutoEntscheidung(', start);
    assert(start > 0 && end > start);
    const ctx = vm.createContext({ TextEncoder, crypto: webcrypto });
    const contract = vm.runInContext(source.slice(start, end) +
      '\n({ personalSyncCustomSourceId, personalSyncCustomSettings, personalSyncCustomAllowed, personalSyncAcceptCustomSettings });', ctx);
    for (const v of vectors.identities) {
      assert.equal(await contract.personalSyncCustomSourceId(vectors.source_id, v.item_id), v.id);
      assert.notEqual(await contract.personalSyncCustomSourceId(vectors.other_source_id, v.item_id), v.id);
    }
    const long = vectors.long_identity;
    assert.equal(await contract.personalSyncCustomSourceId(vectors.source_id, long.character.repeat(long.repeat)), long.id);
    for (const id of ['', 'a'.repeat(641), '\ud800', 'a\0b', 'a\nb', 'a\x7fb', '\u{1f331}'.repeat(161)]) {
      await assert.rejects(contract.personalSyncCustomSourceId(vectors.source_id, id));
    }
    assert.equal(await contract.personalSyncCustomSourceId(vectors.source_id, '\u{1f331}'.repeat(160)), vectors.unicode_identity.id);
    for (const body of vectors.invalid_settings) assert.throws(() => contract.personalSyncCustomSettings(body));
    const local = vectors.local, remote = vectors.remote, versions = [1, 2, 3, 4];
    const allowed = (l = local, r = remote, lv = versions, rv = versions, own = true, otherOwn = true,
      se = remote.epoch, re = local.epoch, sr = remote.revision, rr = local.revision) =>
      contract.personalSyncCustomAllowed(l, r, lv, rv, own, otherOwn, se, re, sr, rr);
    assert.equal(allowed(), true);
    for (const args of [[null], [local, null], [vectors.revoked], [local, vectors.revoked],
      [local, remote, [1, 2, 3]], [local, remote, versions, [1, 2, 3]],
      [local, remote, versions, versions, false], [local, remote, versions, versions, true, false],
      [local, vectors.reenabled], [local, { ...remote, revision: 3 }]]) assert.equal(allowed(...args), false);
    assert.equal(allowed(local, vectors.reenabled, versions, versions, true, true, vectors.reenabled.epoch, local.epoch, 3), true);
    let current = contract.personalSyncAcceptCustomSettings(null, remote);
    for (const next of [remote, vectors.revoked, vectors.reenabled]) {
      current = JSON.parse(JSON.stringify(contract.personalSyncAcceptCustomSettings(current, next)));
    }
    for (const stale of [remote, vectors.revoked, { ...current, enabled: false }, { ...current, revision: 4 }]) {
      assert.throws(() => ctx.personalSyncAcceptCustomSettings(current, stale));
    }
  }
  console.log('Custom consent/identity contract: both desktop sources passed (not runtime integration).');
})().catch(error => { console.error(error); process.exitCode = 1; });
