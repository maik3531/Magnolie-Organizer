// Actual desktop functions, no WebView, radio, microphone, or host audio server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
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
  assert.equal(migrate({}, false).computerTelefonie, false);
  assert.equal(migrate({}, false).eingehendBenachrichtigen, false);
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
    assert.deepEqual(sent, []);
    options.preferPcAudio = true;
    sync(peer, true);
    assert.deepEqual(sent, [{cmd: 'telefon_anruf_audio_einstellung', kennung: 'own-phone', preferPc: true}]);
    sync(peer); // A pending explicit re-enable is not undone by an older status response.
    assert.equal(options.preferPcAudio, true);
  }
}
const native = fs.readFileSync(path.join(root, 'WindowsBluetoothRadio.cs'), 'utf8');
assert.match(native, /IsApiContractPresent\("Windows.ApplicationModel.Calls.CallsPhoneContract", 6\)/);
assert.match(native, /IsTypePresent\("Windows.ApplicationModel.Calls.PhoneLineTransportDevice"\)/);
assert.match(native, /GetCurrentPackageFullName/);
assert.match(native, /\["approved_capability"\] = false/);
assert.match(native, /\["state"\] = "unsupported"/);
assert.doesNotMatch(native, /RequestAccessAsync|RegisterApp|RegisterForTransport|FromIdAsync/);
console.log(`${frontends.length} desktop migrations, routing snapshots, and guarded Windows capability passed.`);
