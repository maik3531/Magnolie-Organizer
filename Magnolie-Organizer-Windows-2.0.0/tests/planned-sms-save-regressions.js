"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const harnessPath = path.join(__dirname, "save-custom-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath;
harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(harnessPath, "utf8").split("const cases = [")[0].replace(
  "nachDauerhaftemSpeichern, personalCustomSenden,",
  "pruefeSmsPlanung, aktualisiereSmsPlanung, setPhone: value => telefonStand = value, " +
  "setReady: value => antwortErhalten = value, setBridgePresent: value => Bruecke.vorhanden = value, " +
  "setSnapshot: value => ausstehenderNotizSnapshot = value, " +
  "saveState: () => ({ timer: speicherAntwortTimer, debounce: speicherTimer, running: laufenderSpeicher?.id, waiters: wartendeSpeicherAktionen.length }), " +
  "nachDauerhaftemSpeichern, personalCustomSenden,");
harness._compile(source + "\nmodule.exports = { boot };", harnessPath);

const cases = [];
const sms = b => b.messages.filter(message => message.cmd === "kde_sms_senden");
function configure(b) {
  b.t.daten().einstellungen.adressen.smsSchedulingEnabled = true;
  b.t.daten().einstellungen.regional.homeCountry = "GB";
  b.t.daten().smsPlanung = ["first", "second"].map((id, index) => ({ id, kontaktId: "synthetic",
    nummer: "+447700900123", land: "GB", text: "Synthetic " + id, zeit: index + 1,
    status: "planned", clientRef: "", fehler: "" }));
  b.t.setPhone({ peers: [], kdeconnect: { available: true, device_id: "a".repeat(32), device_fingerprint: "1".repeat(64) } });
  b.t.speichereJetzt(); b.ack();
}
function clearSave(b) {
  assert.equal(b.t.saveState().waiters, 0, "no abandoned save waiters");
  assert.equal(b.t.saveState().timer, null, "settled save must release its ACK timer handle");
  assert.equal(b.t.saveState().running, undefined);
}

for (const mode of ["async", "local", "timeout", "serialization", "snapshot"]) cases.push([mode + " pre-dispatch failure and retry", async b => {
  configure(b);
  if (mode === "local") b.rejectSave(true);
  if (mode === "serialization") b.t.daten().cycle = b.t.daten();
  if (mode === "snapshot") b.t.setSnapshot(() => { throw new Error("synthetic editor snapshot failure"); });
  assert.doesNotThrow(() => b.t.pruefeSmsPlanung());
  assert.equal(sms(b).length, 0);
  if (mode === "async") b.ack(undefined, false);
  if (mode === "timeout") {
    const timer = b.t.saveState().timer; assert.ok(timer);
    timer.cancelled = true; timer.fn();
  }
  const first = b.t.daten().smsPlanung[0];
  assert.equal(first.status, "planned", "known non-dispatch must be retryable, not submitting/uncertain");
  assert.ok(first.fehler);
  assert.equal(b.t.daten().smsVerlauf[0].status, "failed");
  clearSave(b);
  assert.equal(sms(b).length, 0);
  const old = b.saves().at(-1);
  b.rejectSave(false); delete b.t.daten().cycle;
  b.t.pruefeSmsPlanung();
  assert.equal(sms(b).length, 0, "retry must wait for its own durable ACK");
  b.ack(old); assert.equal(sms(b).length, 0, "old ACK must not dispatch retry");
  b.ack();
  assert.equal(sms(b).length, 1); assert.equal(sms(b)[0].clientRef, "plan:first");
  if (b.windows) {
    assert.equal(sms(b)[0].device_id, "a".repeat(32));
    assert.equal(sms(b)[0].device_fingerprint, "1".repeat(64));
  }
  assert.equal(first.status, "queued", "accepted handoff must no longer block other plans");
  assert.equal(b.t.daten().smsVerlauf.filter(row => row.clientRef === first.clientRef).length, 1);
  b.t.pruefeSmsPlanung(); b.ack();
  assert.deepEqual(sms(b).map(row => row.clientRef), ["plan:first", "plan:second"]);
  // Failure of the later status save cannot turn an already handed-off plan into a retry.
  b.t.speichereJetzt(); b.ack(undefined, false); b.t.pruefeSmsPlanung();
  assert.equal(sms(b).length, 2); assert.equal(first.status, "queued");
  b.w.App.kdeSmsStatus({ ok: false, state: "uncertain", client_ref: first.clientRef });
  b.t.pruefeSmsPlanung(); assert.equal(first.status, "uncertain"); assert.equal(sms(b).length, 2);
  clearSave(b);
}]);

for (const mode of ["disabled", "offline", "device-change", "local-sms-rejection", "synchronous-status"]) cases.push([mode + " after durable save", async b => {
  configure(b); b.t.daten().smsPlanung.length = 1;
  const bridge = b.w.webkit.messageHandlers.test, send = bridge.postMessage;
  bridge.postMessage = raw => {
    const message = JSON.parse(raw);
    if (message.cmd === "kde_sms_senden" && mode === "local-sms-rejection") throw new Error("synthetic local non-acceptance");
    send(raw);
    if (message.cmd === "kde_sms_senden" && mode === "synchronous-status")
      b.w.App.kdeSmsStatus({ ok: true, state: "submitted", client_ref: message.clientRef });
  };
  b.t.pruefeSmsPlanung();
  if (mode === "disabled") b.t.daten().einstellungen.adressen.smsSchedulingEnabled = false;
  if (mode === "offline") b.t.setPhone({ peers: [], kdeconnect: { available: false } });
  if (mode === "device-change") b.t.setPhone({ peers: [], kdeconnect: { available: true, device_id: "b".repeat(32), device_fingerprint: "2".repeat(64) } });
  b.ack();
  const item = b.t.daten().smsPlanung[0];
  assert.equal(item.status, mode === "synchronous-status" ? "submitted" : "planned");
  assert.equal(sms(b).length, mode === "synchronous-status" ? 1 : 0);
  b.t.speichereJetzt(); b.ack(); clearSave(b);
}]);

cases.push(["missing, false and non-boolean preferences pause without altering plans", async b => {
  configure(b);
  for (const value of [undefined, false, "true", 1]) {
    b.t.daten().einstellungen.adressen.smsSchedulingEnabled = value;
    const before = JSON.stringify(b.t.daten().smsPlanung);
    b.t.pruefeSmsPlanung();
    assert.equal(JSON.stringify(b.t.daten().smsPlanung), before);
    assert.equal(sms(b).length, 0);
    const normalized = b.t.normalisiere(b.t.daten());
    assert.equal(normalized.einstellungen.adressen.smsSchedulingEnabled, false);
    assert.equal(normalized.smsPlanung.length, 2);
  }
  assert.ok(b.w.document.querySelector("#zettel").textContent.includes("Pending plans are paused"),
    "Old pending plans need a visible migration reminder, not silent pausing");
  b.t.daten().einstellungen.adressen.smsSchedulingEnabled = true;
  assert.equal(b.t.normalisiere(b.t.daten()).einstellungen.adressen.smsSchedulingEnabled, true);
  b.t.pruefeSmsPlanung(); b.ack();
  assert.equal(sms(b).length, 1, "explicit enable resumes the overdue plan after durable save");
  b.t.daten().einstellungen.adressen.smsSchedulingEnabled = false;
  b.t.pruefeSmsPlanung();
  assert.equal(b.t.daten().smsPlanung[0].status, "queued", "disable cannot recall a handoff");
  b.w.App.kdeSmsStatus({ ok: true, state: "submitted", client_ref: "plan:first" });
  assert.equal(b.t.daten().smsPlanung[0].status, "submitted", "native status still updates while disabled");
  assert.equal(sms(b).length, 1);
}]);

for (const mode of ["restore", "lock"]) cases.push([mode + " cancels waiting planned SMS", async b => {
  configure(b); b.t.pruefeSmsPlanung(); const old = b.saves().at(-1);
  if (mode === "restore") b.restore(); else b.w.App.init({ gesperrt: true });
  b.ack(old); assert.equal(sms(b).length, 0); clearSave(b);
  assert.equal(b.t.saveState().debounce, null);
}]);

cases.push(["all waiter completion paths and repeated ACK timer cleanup", async b => {
  let completed = 0, errors = 0;
  for (let i = 0; i < 50; i++) {
    b.t.daten().notizen[0].text = "cycle " + i;
    b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
    b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
    const timer = b.t.saveState().timer; assert.ok(timer);
    b.ack(undefined, i % 2 === 0);
    assert.equal(timer.cancelled, true); clearSave(b);
  }
  assert.equal(completed, 50); assert.equal(errors, 50);
  b.w.App.init({ gesperrt: true });
  b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
  assert.equal(errors, 51); clearSave(b);
}]);

cases.push(["unconfirmed startup, browser storage and callback exception settlement", async b => {
  let completed = 0, errors = 0;
  b.t.setReady(false);
  b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
  assert.equal(errors, 1); clearSave(b);
  b.t.setReady(true); b.t.setBridgePresent(false);
  const write = b.w.Storage.prototype.setItem;
  b.w.Storage.prototype.setItem = () => { throw new Error("synthetic browser quota failure"); };
  b.t.daten().notizen[0].text = "browser retry";
  b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
  assert.equal(errors, 2); assert.equal(completed, 0); clearSave(b);
  b.w.Storage.prototype.setItem = write;
  b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
  assert.equal(completed, 1); clearSave(b);
  b.t.setBridgePresent(true);
  b.t.daten().notizen[0].text = "callback retry";
  b.t.nachDauerhaftemSpeichern(() => { throw new Error("synthetic UI callback failure"); }, () => errors++);
  b.t.nachDauerhaftemSpeichern(() => completed++, () => errors++);
  b.ack(); assert.equal(completed, 2); assert.equal(errors, 2); clearSave(b);
}]);

(async () => {
  let failed = 0, total = 0;
  const roots = [path.resolve(__dirname, "../app/web")];
  const linux = path.resolve(__dirname, "../../magnolie-organizer-2.0.0/web");
  if (fs.existsSync(linux)) roots.push(linux);
  for (const web of roots) {
    for (const [name, test] of cases) {
      const b = await harness.exports.boot(web); b.windows = web === roots[0]; total++;
      try { await test(b); console.log("PASS " + path.relative(path.resolve(__dirname, "../.."), web) + ": " + name); }
      catch (error) { failed++; console.error("FAIL " + web + ": " + name + ": " + error.message); }
      finally { b.close(); }
    }
  }
  console.log(`${total - failed}/${total} planned SMS/save lifecycle cases passed`);
  process.exitCode = failed ? 1 : 0;
})().catch(error => { console.error(error); process.exitCode = 1; });
