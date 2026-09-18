// Run the actual rendering functions against synthetic nodes, never a user profile.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const frontends = ['../app/web/anwendung.js'];
if (fs.existsSync(path.join(__dirname, '../../magnolie-organizer/web/anwendung.js')))
  frontends.push('../../magnolie-organizer/web/anwendung.js');
for (const relative of frontends) {
  const request = "geraeteKennungenAnfragen.set(offenesGeraet, { id: 'new-request', deadline: performance.now() + 60000 });";
  const source = fs.readFileSync(path.join(__dirname, relative), 'utf8');
  const start = source.indexOf('  const geraeteKennungen = new Map();');
  const end = source.indexOf('  function personalCustomBeschriftung()', start);
  assert(start > 0 && end > start);
  const fields = Object.fromEntries(['phone_number', 'serial', 'imei'].map(key => [key, { textContent: '', previousElementSibling: {} }]));
  const peer = { device_id: 'fixture', fingerprint: 'fixture-key', own_device: true, remote_own_device: true, state: 'online_wifi',
    capabilities: { revision: 1, items: { device_status: { versions: [1, 2, 3, 4] } } },
    grants: { grants: { device_status: true } }, local_grants: { grants: { device_status: true } } };
  const context = vm.createContext({ Date, Map, Number, String, Math, performance, offenesGeraet: 'fixture', telefonStand: { peers: [peer] },
    _: text => text, geraeteZeit: () => '', geraeteDauer: () => '', setTimeout: () => {},
    $: () => ({ querySelectorAll: () => [], querySelector: selector => fields[selector.match(/data-identifier="([^"]+)"/)?.[1]] || null }) });
  vm.runInContext(source.slice(start, end), context);
  const report = { request_id: 'new-request', identifiers_expires_ms: Date.now() + 60000, identifiers_peer_fingerprint: 'fixture-key', identifiers: {
    phone_number: { status: 'permission_missing', value: '' }, serial: { status: 'os_restricted', value: '' },
    imei: { status: 'available', value: '000000000000001' } } };
  context.report = report;
  vm.runInContext('zeichneGeraeteStatus(report)', context);
  assert(!fields.imei.textContent.startsWith('0'), 'Unrequested rendering');
  vm.runInContext(request + 'zeichneGeraeteStatus(report)', context);
  assert(fields.imei.textContent.startsWith('0'), 'Lost string leading zero');
  assert.equal(fields.serial.textContent, '');
  assert(fields.serial.hidden && fields.serial.previousElementSibling.hidden, 'Unavailable identifier row must be hidden');
  assert(!fields.imei.hidden && !fields.imei.previousElementSibling.hidden, 'Available identifier row must remain visible');
  peer.fingerprint = 'changed-key';
  vm.runInContext('zeichneGeraeteKennungen();' + request + 'zeichneGeraeteStatus(report)', context);
  assert(!fields.imei.textContent.startsWith('0'), 'Changed peer rendered stale identifiers');
  peer.fingerprint = 'fixture-key';
  peer.own_device = false;
  vm.runInContext('zeichneGeraeteKennungen()', context);
  assert(fields.imei.hidden && fields.imei.previousElementSibling.hidden, 'Ownership did not hide fields');
  peer.own_device = true;
  vm.runInContext('zeichneGeraeteStatus(report)', context);
  assert(!fields.imei.textContent.startsWith('0'), 'Consent-off request revived');
  vm.runInContext(request + 'zeichneGeraeteStatus(report)', context);
  peer.capabilities.revision++;
  vm.runInContext('zeichneGeraeteKennungen()', context);
  assert(!fields.imei.textContent.startsWith('0'), 'Capability revision failed to purge');
  report.identifiers_expires_ms = Date.now() - 1;
  vm.runInContext(request + 'zeichneGeraeteStatus(report)', context);
  assert(!fields.imei.textContent.startsWith('0'), 'Expired identifier displayed');
  peer.state = 'offline';
  vm.runInContext('zeichneGeraeteKennungen()', context);
  assert.equal(vm.runInContext('geraeteKennungenAnfragen.size + geraeteKennungen.size', context), 0);
  {
    peer.state = 'online_wifi'; report.identifiers_expires_ms = Date.now() + 60000;
    report.request_id = 'old-request';
    vm.runInContext(request + 'zeichneGeraeteStatus(report)', context);
    assert(!fields.imei.textContent.startsWith('0'), 'Reopened dialog accepted old native request');
  }
}
console.log(`Identifier rendering: ${frontends.length} desktop frontends passed consent, expiry and leading-zero checks.`);
