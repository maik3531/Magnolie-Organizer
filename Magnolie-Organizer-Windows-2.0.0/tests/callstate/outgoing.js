// Real Windows dial, call dialog, note save, and callbacks; inert DOM/bridge, no WebView.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../../app/web/anwendung.js'), 'utf8');
const peerId = '11111111-1111-4111-8111-111111111111';
const callId = '22222222-2222-4222-8222-222222222222';
const endId = '33333333-3333-4333-8333-333333333333';
const trace = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function harness() {
  const nodes = new Set(), sent = []; let saves = 0, references = 0;
  // Match the production helper's three-argument contract. A variadic helper
  // would silently attach children that the real frontend actually discards.
  function el(tag, className, text) {
    const node = {tag, className, children: [], removed: false, value: '', textContent: '', listeners: {},
      append(...values) { this.children.push(...values); for (const child of values) if (child && typeof child === 'object') child.parent = this; }, setAttribute() {}, focus() {},
      addEventListener(name, fn) { this.listeners[name] = fn; },
      remove() { this.removed = true; for (const child of this.children) child?.remove?.(); }};
    if (text !== undefined && text !== null) node.textContent = String(text);
    nodes.add(node); return node;
  }
  const $ = selector => {
    const parts = selector.split(' '), match = node => !node.removed &&
      (parts.at(-1).startsWith('#') ? node.id === parts.at(-1).slice(1) : node.className?.split(' ').includes(parts.at(-1).slice(1)));
    return [...nodes].reverse().find(match) || null;
  };
  const peer = {device_id: peerId, display_name: 'Synthetic phone', state: 'online_wifi',
    capabilities: {items: {dial_request: {available: true, versions: [1, 2]},
      incoming_call_state: {available: true, versions: [2]}, end_call: {available: true, versions: [1, 2]}, answer_call: {available: false, versions: [1]}}},
    grants: {grants: {dial_request: true, incoming_call_state: false, end_call: false, answer_call: false}},
    local_grants: {grants: {dial_request: true, incoming_call_state: false, end_call: false, answer_call: false}}};
  const data = {einstellungen: {adressen: {kommunikation: {anruf: {art: 'magnolie', eingehendBenachrichtigen: false, computerTelefonie: false}}}},
    kontakte: [], notizen: [], notizbuecher: [{id: 'book'}]};
  const funcs = ['waehlFaehigeTelefone', 'rufeNummerAn', 'neuesAnrufEreignis', 'anrufDauer', 'speichereAnrufnotiz',
    'zeigeAnrufDialog', 'kannAnrufAuflegen', 'kannAnrufAnnehmen', 'verwerfeAnrufDialog', 'anrufAudioHinweis'];
  const callbacks = ['telefonEingehenderAnruf', 'telefonWaehlStatus', 'telefonAuflegeStatus'];
  const code = funcs.map(name => {
    const text = source.match(new RegExp('  function ' + name + '\\([\\s\\S]*?\\n  \\}'))[0];
    try { new Function(text); } catch (error) { throw new Error(name + ': ' + error.message); }
    return text;
  }).join('\n');
  const handlers = callbacks.map(name => source.match(new RegExp('    ' + name + '\\(nutzlast\\) \\{[\\s\\S]*?\\n    \\},'))[0]).join('\n');
  const deps = {DATEN: data, telefonStand: {peers: [peer], call_audio: {state: 'unsupported'}},
    Bruecke: {sende: value => { sent.push(value); return true; }}, el, $, document: {createElement: tag => el(tag), body: el('body')},
    knopf: (label, cls, fn) => Object.assign(el('button', cls, label), {click: fn}), _: text => text, zettel() {},
    anrufClientRef: () => references++ === 0 ? callId : endId, telefonHeimatland: () => 'US', anrufKontakt: () => null, anrufHerkunft: () => null,
    kontaktName: () => '', zustand: {notizen: {notizbuchId: 'book'}}, isoHeute: () => '2026-09-14',
    speichereJetzt: () => saves++, uebersetzt: text => text, setInterval: () => 1, clearInterval() {}};
  const api = new Function(...Object.keys(deps), `let aktiverAnruf = null, anrufUhr = 0;
    const anrufEreignisse = new Map(), anrufUuidV4 = /^[0-9a-f-]{36}$/;
    ${code}
    return {${handlers} dial: rufeNummerAn, active: () => aktiverAnruf, canEnd: () => kannAnrufAuflegen(aktiverAnruf, telefonStand.peers[0])};`)(...Object.values(deps));
  return {api, sent, data, peer, $, saves: () => saves};
}
const h = harness();
assert.equal(h.api.dial({wert: '+12025550123'}), true);
assert.equal(h.api.dial({wert: '+12025550124'}), false);
assert.equal(h.sent.filter(v => v.cmd === 'telefon_waehlen').length, 1);
assert.equal(h.sent[0].kennung, peerId);
assert.equal(h.api.canEnd(), false);
assert.equal(h.$('#anruf-notiz').parent?.tag, 'label', 'Call notes must be attached to the actual dialog label');
h.$('#anruf-notiz').value = 'Synthetic user note';
h.$('#anruf-notiz').listeners.input();
for (const direction of ['incoming', 'unknown']) h.api.telefonEingehenderAnruf({...trace[0], direction});
h.api.telefonEingehenderAnruf({...trace[0], device_id: 'other-peer'});
h.api.telefonEingehenderAnruf({...trace[0], call_ref: '33333333-3333-4333-8333-333333333333'});
assert.equal(h.api.active().revision, 0);
h.api.telefonEingehenderAnruf(trace[0]);
assert.equal(h.api.active().revision, 1); assert.equal(h.api.canEnd(), false);
h.api.telefonEingehenderAnruf(trace[1]);
assert.equal(h.api.active().state, 'offhook'); assert.equal(h.api.canEnd(), true);
assert.equal(h.api.active().number, '+12025550123');
assert.equal(h.$('#anruf-notiz').value, 'Synthetic user note');
h.$('.anruf-auflegen').click(); h.$('.anruf-auflegen').click();
assert.equal(h.sent.filter(v => v.cmd === 'telefon_auflegen').length, 1);
assert.equal(h.sent.find(v => v.cmd === 'telefon_auflegen').revision, 2);
assert.equal(h.sent.find(v => v.cmd === 'telefon_auflegen').commandRef, endId);
h.api.telefonAuflegeStatus({device_id: 'wrong', call_ref: callId, command_ref: callId, state: 'failed'});
assert.equal(h.api.active().endPending, true);
h.$('.anruf-minimieren').click(); assert(h.$('#anruf-chip')); assert.equal(h.api.active().hidden, true);
h.api.telefonEingehenderAnruf(trace[2]);
h.api.telefonWaehlStatus({device_id: peerId, client_ref: callId, state: 'submitted'});
h.api.telefonEingehenderAnruf(trace[2]); h.api.telefonEingehenderAnruf(trace[1]);
assert.equal(h.api.active(), null); assert.equal(h.saves(), 1); assert.equal(h.data.notizen.length, 1);
assert.match(h.data.notizen[0].text, /Synthetic user note/); assert.match(h.data.notizen[0].text, /Outgoing/);
assert.equal(h.sent.filter(v => v.cmd === 'telefon_anruf_anzeigen').length, 0);
assert.equal(h.sent.filter(v => v.cmd === 'telefon_freigabe' || v.cmd === 'telefon_annehmen').length, 0);
assert.equal(h.peer.local_grants.grants.incoming_call_state, false);
const pending = harness(); pending.api.dial({wert: '+12025550123'});
pending.api.telefonWaehlStatus({device_id: 'wrong', client_ref: callId, state: 'failed'}); assert(pending.api.active());
pending.api.telefonWaehlStatus({device_id: peerId, client_ref: callId, state: 'failed'}); assert.equal(pending.api.active(), null);
for (const value of trace) pending.api.telefonEingehenderAnruf(value);
assert.equal(pending.api.active(), null);
for (const name of ['scoped-timeout', 'scoped-incoming-collision']) {
  const fixture = path.join(path.dirname(process.argv[2]), 'host-' + name + '.json');
  assert(fs.existsSync(fixture), 'Missing native boundary fixture: ' + name);
  const ended = harness(); ended.api.dial({wert: '+12025550123'});
  ended.$('#anruf-notiz').value = 'Synthetic boundary note'; ended.$('#anruf-notiz').listeners.input();
  for (const value of JSON.parse(fs.readFileSync(fixture))) ended.api.telefonEingehenderAnruf(value);
  assert.equal(ended.api.active(), null); assert.equal(ended.saves(), 1);
  assert.equal(ended.sent.filter(v => v.cmd === 'telefon_anruf_anzeigen' || v.cmd === 'telefon_auflegen').length, 0);
}
console.log(JSON.stringify({states: ['local-dial', 'ringing', 'offhook', 'idle'], dials: 1, hangups: 1,
  savedNotes: h.data.notizen.length, saveCalls: h.saves(), incomingNotifications: 0, globalGrantChanges: 0,
  pendingFailureAndReorderedTerminal: 'passed', hardware: false}));
