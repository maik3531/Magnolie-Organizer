// Evaluate the actual Settings list expressions without starting either application.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const { webcrypto } = require('node:crypto');
const files = [path.join(__dirname, '../app/web/anwendung.js')];
const linuxRoot = process.env.MAGNOLIE_LINUX_SOURCE || path.join(__dirname, '../../magnolie-organizer');
if (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linuxRoot)) {
  files.push(path.join(linuxRoot, 'web/anwendung.js'));
}
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  const peers = source.match(/const telefone = (\(telefonStand\.peers[\s\S]*?);/)[1];
  const devices = source.match(/const btGeraete = (\(telefonStand\.bluetooth[\s\S]*?);/)[1];
  const phoneList = new Function('telefonStand', `return ${peers};`);
  const bluetoothList = new Function('telefonStand', `return ${devices};`);
  assert.deepEqual(phoneList({ peers: [
    { device_id: 'trusted-a', display_name: 'Friendly phone' },
    { device_id: 'trusted-a', display_name: 'Product model' },
    { device_id: 'trusted-b', display_name: 'Friendly phone' }
  ] }).map(p => p.device_id), ['trusted-a', 'trusted-b']);
  assert.deepEqual(bluetoothList({ bluetooth: { devices: [
    { address: 'AA:BB:CC:DD:EE:01', name: 'Friendly phone' },
    { address: 'aa:bb:cc:dd:ee:01', name: 'Product model' },
    { address: 'AA:BB:CC:DD:EE:02', name: 'Friendly phone' }
  ] } }).map(p => p.address), ['AA:BB:CC:DD:EE:01', 'AA:BB:CC:DD:EE:02']);
  assert.equal(phoneList({ peers: [{ display_name: 'Unknown' }, { display_name: 'Unknown' }] }).length, 2);
  const start = source.indexOf('  function telefonStandardsAnwenden() {');
  const end = source.indexOf('  function zeichneGeraeteKennungen()', start);
  assert.ok(start >= 0 && end > start);
  const runDefaults = new Function('telefonStand', 'Bruecke', 'telefonStandardAnfragen', 'performance', 'DATEN',
    source.slice(start, end) + '\ntelefonStandardsAnwenden();');
  const defaults = (...args) => runDefaults(...args, { einstellungen: { adressen: { kommunikation: { anruf: { art: 'system' } } } } });
  const messages = [], waiting = new Map(), bridge = { sende(message) { messages.push(message); return true; } };
  const peer = { device_id: 'phone', fingerprint: 'pin', state: 'offline', own_device: false,
    auto_wifi: false, local_grants: { grants: {} } };
  defaults({ peers: [{ ...peer, state: 'pair_commit_pending' }] }, bridge, waiting, { now: () => 1 });
  assert.equal(messages.length, 0, 'defaults must wait for confirmed pairing');
  defaults({ peers: [peer] }, bridge, waiting, { now: () => 1 });
  for (const name of ['personal_notes_sync', 'personal_tasks_sync', 'selected_notifications_readonly'])
    assert.ok(messages.some(m => m.cmd === 'telefon_freigabe' && m.name === name && m.an === true));
  assert.ok(messages.some(m => m.cmd === 'personal_sync_einstellungen' && m.eigen === true && m.autoWlan === true));
  const count = messages.length;
  defaults({ peers: [peer] }, bridge, waiting, { now: () => 2 });
  assert.equal(messages.length, count, 'waiting for acknowledgment must not flood the bridge');
  messages.length = 0;
  const configured = { ...peer, own_device: true, local_grants: { grants: {
    personal_notes_sync: false, personal_tasks_sync: false, selected_notifications_readonly: false } } };
  defaults({ peers: [configured] }, bridge, waiting, { now: () => 20000 });
  assert.equal(messages.length, 0, 'later note/task/automatic-sync opt-outs must remain disabled');
  defaults({ peers: [peer, { ...peer, device_id: 'other' }] }, bridge, waiting, { now: () => 20000 });
  defaults({ peers: [peer], binding_conflict: true }, bridge, waiting, { now: () => 20000 });
  assert.equal(messages.length, 0, 'ambiguous phone bindings must not receive defaults');
  if (file === files[0]) {
    runDefaults({ peers: [configured] }, bridge, new Map(), { now: () => 20000 }, {
      einstellungen: { adressen: { kommunikation: { anruf: { art: 'magnolie' } } } } });
    assert.deepEqual(messages.filter(m => m.cmd === 'telefon_freigabe').map(m => [m.name, m.an]),
      [['incoming_call_state', true], ['incoming_call_number', true], ['answer_call', true], ['end_call', true]],
      'the selected Notes call route must include all call controls');
    messages.length = 0;
  }
  const readyStart = source.indexOf('  function personalSyncBereit(peer) {');
  const ready = new Function('peer', source.slice(readyStart, end) + '\nreturn personalSyncBereit(peer);');
  assert.equal(ready(null), false);
  assert.equal(ready({ ...configured, remote_own_device: false }), false);
  assert.equal(ready({ ...configured, remote_own_device: true }), false);
  const commonNotes = { ...configured, remote_own_device: true, local_grants: { grants: { personal_notes_sync: true } },
    grants: { grants: { personal_notes_sync: true } } };
  assert.equal(ready(commonNotes), true);
  assert.equal(ready({ ...commonNotes, grants: { grants: { personal_tasks_sync: true } } }), false);
  assert.equal(ready({ ...configured, remote_own_device: true, custom_sync: { local: { enabled: true }, remote: { enabled: true } },
    capabilities: { items: { personal_tasks_sync: { available: true, versions: [4] } } } }), true);

  const web = path.dirname(file);
  const dom = new JSDOM(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), {
    runScripts: 'outside-only', url: 'https://app.magnolie.invalid/index.html', pretendToBeVisual: true });
  const w = dom.window;
  try {
    Object.defineProperty(w, 'crypto', { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.__MAGNOLIE_BRUECKE__ = 'test'; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
    w.eval(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8')); w.MagnolieI18n.setLocale('en');
    w.eval(source); w.document.dispatchEvent(new w.Event('DOMContentLoaded')); w.App.init({ daten: {}, neu: false });
    w.App.telefonStand({ peers: [configured] });
    w.OrganizerTest.oeffneGeraeteDialog({ kennung: configured.device_id, name: 'Fixture' });
    const noteCheckbox = w.document.querySelector('[data-personal-grant-name="personal_notes_sync"]');
    const autoCheckbox = w.document.querySelector('[data-personal-auto-peer]');
    const action = w.document.querySelector('[data-personal-sync-action]');
    assert.ok(noteCheckbox && autoCheckbox && action);
    assert.equal(noteCheckbox.checked, false); assert.equal(autoCheckbox.checked, false); assert.equal(action.disabled, true);
    w.App.telefonStand({ peers: [{ ...commonNotes, auto_wifi: true }] });
    assert.equal(noteCheckbox.checked, true); assert.equal(autoCheckbox.checked, true); assert.equal(action.disabled, false);
    w.App.telefonStand({ peers: [{ ...configured, remote_own_device: true }] });
    assert.equal(noteCheckbox.checked, false); assert.equal(autoCheckbox.checked, false); assert.equal(action.disabled, true);
  } finally { w.close(); }
}
console.log(`Phone Settings: identity deduplication and pairing defaults passed for ${files.length} source tree(s)`);
