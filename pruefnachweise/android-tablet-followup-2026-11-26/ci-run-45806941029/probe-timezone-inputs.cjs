'use strict';
// Verification-only read injection: no repository file is created or changed.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = process.cwd(), mode = process.env.MAGNOLIE_SETUP_PROBE;
const caches = new Set(['magnolie-organizer/web/normative-timezones.js',
  'magnolie-organizer-windows/app/web/normative-timezones.js'].map(file => path.join(root, file)));
const payload = path.join(root, 'port-adapters/timezones/tzdb-2026egtz.json');
const read = fs.readFileSync, exists = fs.existsSync;
let cacheReads = 0, mutations = 0;
fs.existsSync = function (file) { return caches.has(String(file)) || exists.apply(this, arguments); };
fs.readFileSync = function (file, options) {
  if (caches.has(String(file))) {
    cacheReads++;
    const text = 'throw new Error("stale desktop timezone cache executed");';
    return typeof options === 'string' || options?.encoding ? text : Buffer.from(text);
  }
  const value = read.apply(this, arguments);
  if (mode === 'corrupt-tzdb' && String(file) === payload) {
    mutations++;
    const damaged = Buffer.from(value); damaged[0] ^= 1;
    return typeof value === 'string' ? damaged.toString() : damaged;
  }
  return value;
};
process.on('exit', () => {
  assert.equal(cacheReads, 0, 'Desktop generated caches must never replace current validated inputs');
  assert.equal(mutations, mode === 'corrupt-tzdb' ? 1 : 0);
  console.log(`Timezone input probe: ${mode}; desktop cache reads=${cacheReads}; mutated payload reads=${mutations}.`);
});
