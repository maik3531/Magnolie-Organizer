import assert from 'node:assert/strict';
import fs from 'node:fs';
import { webcrypto } from 'node:crypto';
import { boot, tick } from './ui_harness.mjs';

const fixture = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
assert.equal(fixture.response.ok, true);
const payload = { ...fixture.response.result, art: 'lotus', abgebrochen: false, datei: fixture.response.name };
let checks = 0;
const equal = (actual, expected, label) => {
  const plain = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  assert.deepEqual(plain(actual), plain(expected), label); checks++;
};
async function environment() {
  const b = await boot(process.argv[2]);
  Object.defineProperty(b.w.crypto, 'subtle', { value: webcrypto.subtle });
  b.w.MacBeta.receive('init', { daten: {
    termine: [], aufgaben: [], kontakte: [], notizen: [],
    futureRoot: { preserve: ['unknown', { value: 17 }] },
    einstellungen: { allgemein: { handbuchHinweisGezeigt: true }, regional: { homeCountry: 'DE' } }
  }, neu: false, regional: { language: 'en', timeZone: 'Europe/Berlin' } });
  const seen = new Set(), clicked = new WeakSet();
  b.receiptErrors = [];
  b.pump = async ({ saves = true, saveOK = true, snapshots = true, apply = false } = {}) => {
    for (const message of [...b.messages]) {
      const key = message.cmd + ':' + (message.id ?? message.token ?? '');
      if (seen.has(key)) continue;
      if (message.cmd === 'speichern' && saves) {
        seen.add(key); b.w.MacBeta.receive('gespeichert', { id: message.id, ok: saveOK, fehler: saveOK ? '' : 'Synthetic failed write' });
      }
      if (message.cmd === 'mutations_snapshot' && snapshots) {
        seen.add(key);
        try { b.w.MacBeta.receive('mutationsSnapshot', { token: message.token, ok: true }); }
        catch (error) { b.receiptErrors.push(String(error?.message || error)); }
      }
    }
    if (apply) {
      const button = b.w.document.querySelector('[data-import-anwenden]');
      if (button && !button.disabled && button.closest('[aria-busy]')?.getAttribute('aria-busy') !== 'true' && !clicked.has(button)) {
        clicked.add(button); button.click();
      }
    }
    await tick();
  };
  b.until = async (condition, options = {}) => {
    for (let n = 0; n < 800; n++) { if (condition()) return; await b.pump(options); }
    throw new Error('Actual file import did not finish: ' + JSON.stringify({ receiptErrors: b.receiptErrors,
      dialog: b.w.document.querySelector('[data-import-anwenden]')?.closest('section')?.textContent.slice(0, 1600),
      messages: b.messages.slice(-4).map(m => ({ cmd: m.cmd, id: m.id, token: m.token })) }));
  };
  b.prepare = async () => {
    let result, error;
    b.w.App.macOSBetaPrepareFileImport('lotus').then(value => { result = value; }, value => { error = value; });
    await b.until(() => result || error);
    if (error) throw error;
    assert.equal(typeof result.token, 'string'); checks++;
    return result.token;
  };
  await b.pump(); await b.pump();
  return b;
}

const b = await environment();
try {
  const before = JSON.stringify(b.t.daten());
  const token = await b.prepare();
  equal(JSON.stringify(b.t.daten()), before, 'Preparing the native import changes no book content');
  let outcome, error;
  b.w.App.macOSBetaCommitFileImport(structuredClone(payload), token).then(value => { outcome = value; }, value => { error = value; });
  await b.until(() => b.w.document.querySelector('[data-import-anwenden]') || error, { saves: false });
  assert.ifError(error); checks++;
  equal(JSON.stringify(b.t.daten()), before, 'Actual OR6 contact preview precedes every collection mutation');
  await b.until(() => b.messages.some(m => m.cmd === 'speichern' && JSON.parse(m.text).notizen?.length === 1) || error,
    { saves: false, apply: true });
  assert.ifError(error); checks++;
  equal(outcome, undefined, 'No successful file-import receipt before the final save ACK');
  const pending = b.messages.filter(m => m.cmd === 'speichern').at(-1);
  b.w.MacBeta.receive('gespeichert', { id: pending.id + 10000, ok: true }); await tick();
  equal(outcome, undefined, 'An unrelated save ACK does not complete the import');
  await b.until(() => outcome || error, { apply: true });
  assert.ifError(error); checks++;
  equal(outcome, { ok: true, changed: true, saveConfirmed: true }, 'Success follows the canonical durable-save callback');
  equal(b.t.daten().futureRoot, { preserve: ['unknown', { value: 17 }] }, 'Unrelated root values remain intact');
  for (const [kind, field] of [['contact', 'kontakte'], ['appointment', 'termine'], ['task', 'aufgaben'], ['note', 'notizen']]) {
    equal(b.t.daten()[field].length, 1, 'Exactly one original OR6 ' + kind);
    for (const [key, value] of Object.entries(fixture.expected[kind])) {
      // The original native fixture intentionally uses example.invalid. The
      // shared desktop UI rejects that domain; a second real OR6 source below
      // proves that accepted .test addresses remain intact through persistence.
      const expected = kind === 'contact' && key === 'email' ? '' : value;
      equal(b.t.daten()[field][0][key], expected, 'Original fixture with shared validation ' + kind + '.' + key);
    }
  }
  const saved = JSON.parse(b.messages.filter(m => m.cmd === 'speichern').at(-1).text);
  for (const field of ['termine', 'aufgaben', 'kontakte', 'notizen']) equal(saved[field], b.t.daten()[field], 'Save payload retains complete ' + field);
  b.w.MacBeta.receive('init', { daten: saved, neu: false, regional: { language: 'en', timeZone: 'Europe/Berlin' } });
  await b.pump();
  for (const field of ['termine', 'aufgaben', 'kontakte', 'notizen']) {
    equal(b.t.daten()[field].length, saved[field].length, 'Reopened book retains the ' + field + ' count');
    for (const row of saved[field]) {
      const reopened = b.t.daten()[field].find(item => item.id === row.id);
      assert.ok(reopened); checks++;
      equal(Object.fromEntries(Object.keys(row).map(key => [key, reopened[key]])), row,
        'Reopen preserves every saved ' + field + ' value while allowing shared default fields');
    }
  }
  const secondToken = await b.prepare();
  outcome = error = undefined;
  b.w.App.macOSBetaCommitFileImport(structuredClone(payload), secondToken).then(value => { outcome = value; }, value => { error = value; });
  await b.until(() => outcome || error, { apply: true });
  assert.ifError(error); checks++;
  for (const field of ['termine', 'aufgaben', 'kontakte', 'notizen']) equal(b.t.daten()[field].length, 1, 'Reimport does not duplicate ' + field);
  const staleToken = await b.prepare();
  b.t.daten().futureRoot.changedDuringPicker = true;
  await assert.rejects(b.w.App.macOSBetaCommitFileImport(structuredClone(payload), staleToken), /Conflict/); checks++;
  b.w.App.macOSBetaCancelFileImport(staleToken);
  const validSource = fixture.validContactResponse;
  assert.equal(validSource.ok, true); checks++;
  const validToken = await b.prepare();
  outcome = error = undefined;
  b.w.App.macOSBetaCommitFileImport({ ...structuredClone(validSource.result), art: 'lotus', abgebrochen: false, datei: validSource.name }, validToken)
    .then(value => { outcome = value; }, value => { error = value; });
  await b.until(() => outcome || error, { apply: true });
  assert.ifError(error); checks++;
  const grace = b.t.daten().kontakte.find(contact => contact.vorname === 'Grace' && contact.firma === 'OR6-222');
  assert.ok(grace); checks++;
  equal(grace.email, 'grace.or6@example.test', 'Actual OR6 .test email survives preview, apply and save');
  equal(JSON.parse(b.messages.filter(m => m.cmd === 'speichern').at(-1).text).kontakte.find(contact => contact.id === grace.id).email,
    'grace.or6@example.test', 'Confirmed save contains the original accepted OR6 address');
} finally { b.close(); }

for (const mode of ['save-rejected', 'renderer-threw']) {
  const b = await environment();
  try {
    const token = await b.prepare();
    let outcome, error;
    const appearance = b.w.MagnolieAppearance;
    if (mode === 'renderer-threw') b.w.MagnolieAppearance = { ...appearance, update() { throw new Error('Synthetic renderer failure after OR6 append'); } };
    b.w.App.macOSBetaCommitFileImport(structuredClone(payload), token).then(value => { outcome = value; }, value => { error = value; });
    await b.until(() => outcome || error, { apply: true, saveOK: mode !== 'save-rejected' });
    b.w.MagnolieAppearance = appearance;
    assert.ok(error, mode + ' must not return a successful receipt'); checks++;
    assert.match(String(error.message), /saving was not confirmed|Synthetic/i); checks++;
    equal(outcome, undefined, mode + ' does not report success');
    for (const field of ['termine', 'aufgaben', 'kontakte', 'notizen']) equal(b.t.daten()[field].length, 1, mode + ' retains the appended ' + field);
    b.t.speichereJetzt();
    for (let n = 0; n < 12; n++) await b.pump();
    const saved = JSON.parse(b.messages.filter(m => m.cmd === 'speichern').at(-1).text);
    for (const field of ['termine', 'aufgaben', 'kontakte', 'notizen']) equal(saved[field].length, 1, mode + ' retry saves exactly the retained ' + field);
  } finally { b.close(); }
}
console.log(`Actual OR6 helper → projected Mac UI: ${checks} checks; explicit WebCrypto, real contact preview and shared Save-ACK path; synthetic transport, no native persistence claim.`);
