"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = process.env.MAGNOLIE_TEST_WEB ? path.resolve(process.env.MAGNOLIE_TEST_WEB) : path.resolve(__dirname, "../app/web");
const sha = text => createHash("sha256").update(text).digest("hex");
const copy = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));
async function boot(options = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://original-source.test.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [], timers = [];
  w.setTimeout = (fn, delay) => { const t = { fn, delay }; timers.push(t); return t; };
  w.clearTimeout = t => { if (t) t.cancelled = true; }; w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: raw => {
    const value = JSON.parse(raw); messages.push(value); options.emit?.(value);
  } } } };
  for (const name of ["i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
  await tick();
  w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: options.data || {
    kontakte: [{ id: "local-person", uid: "canonical-person", vorname: "Alex", nachname: "Synthetic", sync: true, notiz: "Original",
      syncQuellen: { first: { id: "https://first.invalid/book/person.vcf", etag: '"first-v1"' },
        second: { id: "https://second.invalid/book/other.vcf", etag: '"second-v1"' } } }],
    notizen: [{ id: "synthetic-note", titel: "Keep", text: "Do not rewrite" }],
    einstellungen: { sync: { kontaktOriginalQuellen: ["first", "second"] } }
  } });
  const t = w.OrganizerTest;
  const commands = cmd => messages.filter(value => value.cmd === cmd);
  function ack(extra = {}) {
    const save = commands("speichern").at(-1); assert.ok(save);
    w.App.gespeichert({ id: save.id, ok: true, standSha256: sha(save.text), ...extra }); return save;
  }
  if (!options.wire) {
    t.speichereJetzt(); ack();
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    w.App.edsStatus({ verfuegbar: true, buchOk: true, windows: true, kalender: [], adressbuecher: [],
      originalKontaktUpdates: { verfuegbar: true, freigaben: 2 } });
  }
  const button = text => [...w.document.querySelectorAll("#sync-wahl button")].find(value => value.textContent === text);
  return { w, t, messages, commands, ack, button, close: () => w.close() };
}
async function start(b) {
  b.t.daten().kontakte[0].notiz = "Edited synthetic contact";
  b.button("Original contact sources").click();
  assert.equal(b.commands("kontakt_originalquellen_freigabe").length, 0, "Consent discovery preceded original SaveACK");
  assert.equal(b.commands("kontakt_originalquellen_update").length, 0);
  b.ack();
  const request = b.commands("kontakt_originalquellen_freigabe").at(-1); assert.ok(request);
  assert.deepEqual(Object.keys(request).sort(), ["cmd", "requestId"]);
  b.w.App.originalKontaktFreigabe({ requestId: request.requestId, ok: true, changed: true, freigaben: 2 });
  const update = b.commands("kontakt_originalquellen_update").at(-1); assert.ok(update);
  assert.deepEqual(Object.keys(update).sort(), ["cmd", "requestId", "standSha256"]);
  assert.equal(update.standSha256, sha(b.commands("speichern").at(-1).text));
  return update;
}
async function runWire() {
  const readline = require("node:readline");
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  const emit = value => process.stdout.write(JSON.stringify(value) + "\n");
  let b = null, step = 0, pendingComplete = null;
  const durableRestart = process.env.MAGNOLIE_TEST_DURABLE_RESTART === "1";
  const timeout = setTimeout(() => { console.error("Bounded native/frontend wire did not complete"); process.exit(1); }, 50000);
  try {
    for await (const line of lines) {
      const input = JSON.parse(line);
      if (input.type === "init") {
        b = await boot({ data: input.daten, wire: true, emit: value => emit({ type: "command", value }) });
        if (durableRestart) b.t.daten().kontakte[0].notiz = "Canonical note";
        b.t.speichereJetzt();
      } else {
        assert.ok(b && typeof b.w.App[input.callback] === "function", "Unknown native callback");
        b.w.App[input.callback](input.value);
        if (input.callback === "gespeichert") {
          assert.equal(input.value.ok, true, "Actual native SaveAsync rejected the wire candidate");
          if (step === 0) {
            step = 1;
            if (durableRestart) continue; // Wait for actual SaveACK-correlated native restoration, no new setup.
            b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click();
            b.w.App.edsStatus({ verfuegbar: true, buchOk: true, windows: true, kalender: [], adressbuecher: [],
              originalKontaktUpdates: { verfuegbar: true, freigaben: 0 } });
            b.t.daten().kontakte[0].notiz = "Canonical note";
            b.button("Original contact sources").click();
          } else if (input.value.kontaktOriginalGespeichert) {
            const save = b.commands("speichern").at(-1);
            assert.equal(input.value.kontaktOriginalGespeichert, save.kontaktOriginalLauf);
            assert.equal(b.commands("kontakt_originalquellen_update").length, Number(process.env.MAGNOLIE_TEST_EXPECT_ORIGINAL_RUNS || 1));
            if (input.value.kontaktQuellenDauerhaft === true) pendingComplete = save;
            else { emit({ type: "complete", text: save.text, token: save.kontaktOriginalLauf }); return; }
          }
        }
        if (input.callback === "originalKontaktDauerfreigabe" && pendingComplete && input.value.id === pendingComplete.id) {
          assert.equal(input.value.ok, true, "Durable result authority did not restore after its actual SaveACK");
          assert.equal(input.value.standSha256, sha(pendingComplete.text));
          assert.equal(b.commands("kontakt_originalquellen_update").length, Number(process.env.MAGNOLIE_TEST_EXPECT_ORIGINAL_RUNS || 1),
            "Result authority restoration caused another provider run");
          emit({ type: "complete", text: pendingComplete.text, token: pendingComplete.kontaktOriginalLauf }); return;
        }
      }
    }
    throw new Error("Native wire input closed before result SaveACK");
  } finally { clearTimeout(timeout); lines.close(); b?.close(); process.stdin.destroy(); }
}
async function runTests() {
  let cases = 0;
  for (const mode of ["success", "partial-source-error", "newer-edit", "pending-save", "wrong-hash", "wrong-identity", "wrong-token",
    "wrong-request", "revoked", "native-revoked", "status-revoked", "reloaded-book", "save-failed", "missing-native-commit"]) {
    const b = await boot();
    try {
      assert.equal(b.commands("kontakt_originalquellen_update").length, 0, "Imported mappings/status capability granted automatic IO");
      b.w.App.originalKontaktFreigabe({ ok: true, changed: true, freigaben: 2 });
      assert.equal(b.commands("kontakt_originalquellen_update").length, 0, "Unsolicited native reply granted automatic IO");
      const update = await start(b), before = copy(b.t.daten()), saveCount = b.commands("speichern").length;
      const contacts = copy(before.kontakte); contacts[0].syncQuellen.first.etag = '"first-v2"';
      const result = { requestId: update.requestId, ok: true, freigaben: 2, token: "a".repeat(64),
        originalSha256: update.standSha256, kontakte: contacts, fehlerQuellen: mode === "partial-source-error" ? 1 : 0 };
      if (mode === "newer-edit") b.t.daten().kontakte[0].notiz = "Newer local edit must survive";
      if (mode === "pending-save") { b.t.daten().kontakte[0].notiz = "Pending newer save"; b.t.speichereJetzt(); }
      if (mode === "wrong-hash") result.originalSha256 = "0".repeat(64);
      if (mode === "wrong-identity") result.kontakte[0].uid = "different-person";
      if (mode === "wrong-token") result.token = "not-a-native-token";
      if (mode === "wrong-request") result.requestId = "not-the-original-run";
      if (mode === "revoked") b.button("Revoke").click();
      if (mode === "native-revoked") b.w.App.originalKontaktFreigabe({ ok: true, changed: true, freigaben: 0 });
      if (mode === "status-revoked") b.w.App.edsStatus({ verfuegbar: true, buchOk: true, windows: true, kalender: [], adressbuecher: [],
        originalKontaktUpdates: { verfuegbar: true, freigaben: 0 } });
      if (mode === "reloaded-book") b.w.App.init({ neu: false, daten: { kontakte: [{ id: "new-book-person", uid: "new-book-native", notiz: "Keep new book" }] } });
      const current = copy(b.t.daten());
      b.w.App.originalKontaktErgebnis(result);
      if (["success", "partial-source-error", "save-failed", "missing-native-commit"].includes(mode)) {
        const save = b.commands("speichern").at(-1); assert.equal(b.commands("speichern").length, saveCount + 1);
        assert.equal(save.kontaktOriginalLauf, result.token, "Exact result was saved without native one-use proof");
        const saved = JSON.parse(save.text), expected = copy(before); expected.kontakte = contacts;
        assert.deepEqual(saved, expected, "Native result changed unrelated document domains");
        assert.equal(saved.kontakte[0].syncQuellen.second.etag, '"second-v1"', "Failed/pending second baseline was fabricated");
        assert.equal(b.commands("kontakt_originalquellen_update").length, 1, "Result was retried before native SaveACK");
        if (mode === "save-failed") b.ack({ ok: false });
        else b.ack(mode === "missing-native-commit" ? {} : { kontaktOriginalGespeichert: result.token });
        assert.equal(b.commands("kontakt_originalquellen_update").length, 1, "Result SaveACK caused an immediate provider retry");
        if (["save-failed", "missing-native-commit"].includes(mode)) {
          assert.equal(b.commands("kontakt_originalquellen_widerrufen").length, 1, "Unknown result save did not stop automatic session");
          b.t.daten().kontakte[0].notiz = "Later user edit"; b.t.speichereJetzt(); b.ack();
          assert.equal(b.commands("kontakt_originalquellen_update").length, 1, "Unknown outcome was blindly retried");
        } else {
          b.t.daten().kontakte[0].notiz = "Next user edit"; b.t.speichereJetzt();
          assert.equal(b.commands("kontakt_originalquellen_update").length, 1);
          b.ack(); assert.equal(b.commands("kontakt_originalquellen_update").length, 2, "New durable user edit was not automatically planned");
        }
      } else {
        assert.deepEqual(copy(b.t.daten()), current, "Stale/foreign/revoked result overwrote current book: " + mode);
        assert.equal(b.commands("speichern").length, saveCount + (mode === "pending-save" ? 1 : 0), "Held result caused a save: " + mode);
        if (["revoked", "native-revoked", "status-revoked"].includes(mode)) {
          b.t.daten().kontakte[0].notiz = "New user edit after native revocation"; b.t.speichereJetzt(); b.ack();
          assert.equal(b.commands("kontakt_originalquellen_update").length, 1, "Late result revived revoked scheduling");
        }
      }
      cases++; console.log("ORIGINAL CONTACT FRONTEND PASS", mode);
    } finally { b.close(); }
  }
  assert.equal(cases, 14);
}
(process.argv.includes("--wire") ? runWire() : runTests()).catch(error => { console.error(error); process.exitCode = 1; });
