// Actual desktop functions, no WebView, radio, microphone, or host audio server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const frontends = [path.join(root, 'app/web/anwendung.js')];
const linux = path.join(root, '../magnolie-organizer/web/anwendung.js');
if (fs.existsSync(linux)) frontends.push(linux);
for (const file of frontends) {
  const source = fs.readFileSync(file, 'utf8');
  const migration = source.match(/const kommunikationsWeg = [\s\S]*?return ergebnis;\s*\};/)[0];
  const migrate = new Function('S', migration + '; return kommunikationsWeg;')((value) => String(value || ''));
  assert.equal(migrate({}, false).preferPcAudio, true);
  assert.equal(migrate({computerTelefonie: false}, false).preferPcAudio, true);
  assert.equal(migrate({hfpAdresse: ''}, false).preferPcAudio, false);
  assert.equal(migrate({hfpAdresse: 'AA:BB:CC:DD:EE:FF'}, false).preferPcAudio, true);
  assert.equal(migrate({hfpAdresse: 'arbitrary-friendly-name'}, false).preferPcAudio, false);
  assert.equal(migrate({preferPcAudio: false, hfpAdresse: 'AA:BB:CC:DD:EE:FF'}, false).preferPcAudio, false);
  assert.equal(migrate({preferPcAudio: true, hfpAdresse: ''}, false).preferPcAudio, true);
  assert.equal(migrate({}, false).computerTelefonie, true);
  assert.equal(migrate({}, false).eingehendBenachrichtigen, true);
  assert.equal(migrate({art: 'magnolie', computerTelefonie: false, eingehendBenachrichtigen: false}, false).computerTelefonie, true);
  assert.equal(migrate({art: 'system'}, false).computerTelefonie, false);
  assert.equal(migrate({art: 'program', programm: 'dialer'}, false).eingehendBenachrichtigen, false);
  assert.equal(migrate({}, true).preferPcAudio, undefined);
  const hintSource = source.match(/function anrufAudioHinweis\([\s\S]*?\n  \}/)[0];
  const hint = new Function('_', hintSource + '; return anrufAudioHinweis;')((text) => text);
  assert.match(hint({bluetooth: {available: true}}), /unavailable/);
  assert.match(hint({state: 'unsupported'}), /Package identity.*phoneLineTransportManagement/);
  assert.match(hint({available: true, route: {active: false}}, {state: 'offhook'}), /Keep the call on the phone/);
  const call = {device_id: 'own-phone', call_ref: 'current-call', revision: 5, state: 'offhook'};
  const capability = {available: true, route: {...call, active: true}};
  assert.match(hint(capability, call), /Connected/);
  assert.doesNotMatch(hint(capability, {...call, revision: 6}), /Connected/);
  assert.doesNotMatch(hint(capability, {...call, device_id: 'other-phone'}), /Connected/);
  assert.doesNotMatch(hint(capability, {...call, state: 'ringing'}), /Connected/);
  assert.doesNotMatch(source, /cmd: "telefon_anruf_bluetooth"/);
  assert.match(source, /pcAudio\.disabled = audioCapability/);
  if (file === linux) {
    const syncSource = source.match(/function synchronisiereAnrufFreigaben\([\s\S]*?\n  \}/)[0];
    const options = {art: 'magnolie', telefonId: 'own-phone', preferPcAudio: true};
    const data = {einstellungen: {adressen: {kommunikation: {anruf: options}}}};
    const peer = {device_id: 'own-phone', call_audio: {prefer_pc: false}, local_grants: {grants: {
      incoming_call_state: false, incoming_call_number: false, answer_call: false, end_call: false}}};
    const sent = [];
    const sync = new Function('DATEN', 'telefonStand', 'aktiverAnruf', 'anrufFreigabenAusstehend',
      'Bruecke', 'planeSpeichern', syncSource + '; return synchronisiereAnrufFreigaben;')(
        data, {peers: [peer]}, null, new Map(), {sende: message => sent.push(message) && true}, () => {});
    sync(peer);
    assert.equal(options.preferPcAudio, false);
    assert.deepEqual(sent.map(m => [m.name, m.an]), [['incoming_call_state', true], ['incoming_call_number', true], ['answer_call', true], ['end_call', true]]);
    assert.equal(options.eingehendBenachrichtigen, true); assert.equal(options.computerTelefonie, true);
    sent.length = 0;
    options.preferPcAudio = true;
    sync(peer, true);
    assert.deepEqual(sent, [{cmd: 'telefon_anruf_audio_einstellung', kennung: 'own-phone', preferPc: true}]);
    sync(peer); // A pending explicit re-enable is not undone by an older status response.
    assert.equal(options.preferPcAudio, true);
  }
  const web = path.dirname(file);
  const dom = new JSDOM(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), {
    runScripts: 'outside-only', url: 'https://app.magnolie.invalid/index.html', pretendToBeVisual: true });
  const w = dom.window;
  try {
    Object.defineProperty(w, 'crypto', { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    const sent = [];
    w.__MAGNOLIE_BRUECKE__ = 'test'; w.webkit = { messageHandlers: { test: { postMessage(m) { sent.push(JSON.parse(m)); } } } };
    w.eval(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8')); w.MagnolieI18n.setLocale('en');
    w.eval(source.replace('  function oeffneKommunikationsBelegung(typ) {',
      '  window.openCallSettings = oeffneKommunikationsBelegung; window.callOptions = () => DATEN.einstellungen.adressen.kommunikation.anruf;\n  function oeffneKommunikationsBelegung(typ) {'));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded')); w.App.init({ daten: {}, neu: false });
    const peer = { device_id: 'own-phone', fingerprint: 'pin', own_device: true, bluetooth_enabled: false,
      local_grants: { grants: {} } };
    const show = capability => {
      Object.assign(w.callOptions(), {art: 'magnolie', preferPcAudio: true, klingeltonLeiser: false, telefonId: peer.device_id});
      w.App.telefonStand({ peers: [peer], call_audio: capability });
      w.openCallSettings('anruf');
      const dialog = w.document.querySelector('.kommunikation-belegung-dialog');
      const checkbox = text => [...dialog.querySelectorAll('label')].find(label => label.textContent.includes(text)).querySelector('input');
      const button = text => [...dialog.querySelectorAll('button')].find(button => button.textContent === text);
      return {dialog, pc: checkbox('Prefer PC speakers'), lower: checkbox('Lower other sounds'), button};
    };
    let ui = show({state: 'unsupported', available: false});
    assert.equal(ui.pc.checked, false); assert.equal(ui.pc.disabled, true); assert.equal(ui.lower.checked, true);
    ui.button('Restore defaults').click();
    assert.equal(ui.pc.checked, false); assert.equal(ui.lower.checked, true);
    ui.button('Save').click();
    assert.equal(w.callOptions().preferPcAudio, false); assert.equal(w.callOptions().klingeltonLeiser, true);
    if (file === linux) {
      ui = show({state: 'setup_required', reason: 'pairing_required', devices: []});
      assert.equal(ui.pc.disabled, false); assert.equal(ui.pc.checked, true); assert.equal(ui.lower.checked, false);
      ui.button('Pair your phone in the OS Bluetooth settings first.').click();
      assert.ok(sent.some(message => message.cmd === 'telefon_bluetooth_einstellungen'));
      ui.button('Save').click();
      assert.ok(ui.dialog.isConnected, 'An unpaired phone must not be accepted as a ready HFP route');
      ui.button('Cancel').click();
      ui = show({state: 'setup_required', reason: 'binding_required', devices: [
        {address: 'AA:BB:CC:DD:EE:FF', name: 'Fixture phone', trusted: true}]});
      const select = ui.dialog.querySelector('select');
      assert.equal(select.value, '', 'A system bond is never silently assigned to a Notes peer');
      select.value = 'AA:BB:CC:DD:EE:FF';
      ui.button('Save').click();
      assert.ok(sent.some(message => message.cmd === 'telefon_bluetooth_schalten' &&
        message.adresse === select.value && message.an === false));
      assert.equal(ui.dialog.isConnected, false);
    }
  } finally { w.close(); }
}
const native = fs.readFileSync(path.join(root, 'WindowsBluetoothRadio.cs'), 'utf8');
assert.match(native, /IsApiContractPresent\("Windows.ApplicationModel.Calls.CallsPhoneContract", 6\)/);
assert.match(native, /IsTypePresent\("Windows.ApplicationModel.Calls.PhoneLineTransportDevice"\)/);
assert.match(native, /GetCurrentPackageFullName/);
assert.match(native, /\["approved_capability"\] = false/);
assert.match(native, /\["state"\] = "unsupported"/);
assert.doesNotMatch(native, /RequestAccessAsync|RegisterApp|RegisterForTransport|FromIdAsync/);
console.log(`${frontends.length} desktop migrations, routing snapshots, and guarded Windows capability passed.`);
