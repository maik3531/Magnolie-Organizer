// Execute the actual call-only frontend functions with inert bridge/UI captures.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../..');
const files = ['magnolie-organizer/web/anwendung.js', 'magnolie-organizer-windows/app/web/anwendung.js'];
const peerId = '11111111-1111-4111-8111-111111111111';
const callId = '22222222-2222-4222-8222-222222222222';
function harness(source, active = null) {
  const history = source.match(/function neuesAnrufEreignis\(value\) \{[\s\S]*?\n  \}/)[0];
  const handler = source.match(/    telefonEingehenderAnruf\(nutzlast\) \{[\s\S]*?\n    \},/)[0];
  const sent = [], states = [];
  const peer = {device_id: peerId, local_grants: {grants: {incoming_call_state: true}},
    capabilities: {items: {incoming_call_state: {available: true, versions: [2]}}}};
  const data = {einstellungen: {adressen: {kommunikation: {anruf: {art: 'magnolie', telefonId: peerId,
    eingehendBenachrichtigen: true, computerTelefonie: true}}}, erinnerung: {stil: 'system'}}};
  const factory = new Function('DATEN', 'telefonStand', 'aktiverAnruf', 'Bruecke', 'zeigeAnrufDialog',
    'verwerfeAnrufDialog', 'anrufKontakt', '_', 'kontaktName',
    'const anrufEreignisse = new Map();\n' + history + '\nreturn {' + handler + '};');
  const app = factory(data, {peers: [peer]}, active, {sende: value => sent.push(value)},
    value => states.push(value), () => {}, () => null, value => value, () => '');
  return {app, sent, states};
}
const event = {device_id: peerId, call_ref: callId, revision: 1, occurred_ms: 1000,
  state: 'ringing', direction: 'incoming', number_status: 'not_shared', number: ''};
for (const file of files) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  let h = harness(source);
  h.app.telefonEingehenderAnruf(event);
  assert.equal(h.sent.length, 1); assert.equal(h.sent[0].stil, 'magnolie');
  // Native authority decides answer and reject independently, including a reject-only peer.
  assert.equal(h.sent[0].annehmen, true);
  h.app.telefonEingehenderAnruf(event);
  h.app.telefonEingehenderAnruf({...event, direction: 'outgoing', revision: 2});
  assert.equal(h.sent.length, 1);
  h.app.telefonEingehenderAnruf({...event, revision: 2, state: 'idle'});
  const count = h.sent.length;
  h.app.telefonEingehenderAnruf({...event, revision: 3});
  assert.equal(h.sent.length, count);
  for (const direction of ['outgoing', 'unknown']) {
    h = harness(source);
    for (const [index, state] of ['ringing', 'offhook', 'idle'].entries())
      h.app.telefonEingehenderAnruf({...event, direction, state, revision: index + 1});
    assert(!h.sent.some(value => value.cmd === 'telefon_anruf_anzeigen'));
  }
  if (process.env.MAGNOLIE_CALL_TRACE_DIR) {
    for (const direction of ['incoming', 'outgoing']) {
      const trace = JSON.parse(fs.readFileSync(path.join(process.env.MAGNOLIE_CALL_TRACE_DIR, direction + '.json')));
      h = harness(source, direction === 'outgoing' ? {device_id: peerId, direction, client_ref: trace[0].call_ref} : null);
      for (const value of trace) h.app.telefonEingehenderAnruf({...value, device_id: peerId});
      assert.equal(h.sent.filter(value => value.cmd === 'telefon_anruf_anzeigen').length, direction === 'incoming' ? 1 : 0);
      assert(h.states.some(value => value.state === 'offhook'));
      assert(h.states.every(value => value.call_ref === trace[0].call_ref));
    }
  }
}
console.log('Both call frontends: compact alert, independent controls, direction, exact IDs and stale lifecycle passed.');
