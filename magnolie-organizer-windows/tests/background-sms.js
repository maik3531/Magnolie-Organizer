const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
for (const file of [path.join(__dirname, '../app/web/anwendung.js'),
  path.join(__dirname, '../../magnolie-organizer/web/anwendung.js')]) {
  if (!fs.existsSync(file) && file.includes('magnolie-organizer/web')) {
    console.log('SKIP Linux SMS target absent from standalone Windows source'); continue;
  }
  const source = fs.readFileSync(file, 'utf8');
  const extract = name => {
    const start = source.indexOf('  function ' + name + '(');
    assert(start >= 0); return source.slice(start, source.indexOf('\n  }', start) + 4);
  };
  const actions = [], sent = [];
  const sms = { id: 'fixture', nummer: '+49123', text: 'test', zeit: 1, status: 'planned' };
  const c = { DATEN: { smsPlanung: [sms], smsVerlauf: [], einstellungen: { adressen: { smsSchedulingEnabled: true } } },
    telefonStand: { kdeconnect: { available: true, device_id: 'fixture' } }, smsPlanFreigaben: new WeakSet(),
    Bruecke: { vorhanden: true, sende: x => { sent.push(x); return true; } },
    nachDauerhaftemSpeichern: f => actions.push(f), planeSpeichern() {},
    telefonSchluessel: x => x, adressLandCode: () => 'DE', telefonHeimatland: () => 'DE', _: x => x, smsPlanungsTimer: null,
    setTimeout() {}, clearTimeout() {}, gesperrt: false, initialisiert: true, antwortErhalten: true };
  vm.createContext(c);
  vm.runInContext(extract('pruefeSmsPlanung') + '\n' + extract('aktualisiereSmsPlanung'), c);
  c.pruefeSmsPlanung();
  assert.equal(sent.length, 0, 'SMS dispatched before durable save');
  assert.equal(actions.length, 1);
  actions.shift()(); assert.equal(sent.length, 1);
  c.aktualisiereSmsPlanung({ ok: true, state: 'submitted', client_ref: sms.clientRef });
  assert.equal(sms.status, 'submitted', 'Submission is not sent');
  sms.status = 'planned'; c.pruefeSmsPlanung(); c.DATEN.smsPlanung = [];
  actions.shift()(); assert.equal(sent.length, 1, 'Deleted/restored item dispatched');
  c.DATEN.smsPlanung = [sms]; sms.status = 'planned'; c.pruefeSmsPlanung();
  c.telefonStand.kdeconnect.available = false; actions.shift()();
  assert.equal(sent.length, 1, 'Unavailable phone dispatched');
  console.log('PASS durable scheduled SMS: ' + file);
}
