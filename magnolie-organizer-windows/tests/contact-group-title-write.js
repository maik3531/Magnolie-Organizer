"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const source = { deviceId: "notes:22222222-2222-4222-8222-222222222222", fingerprint: "a".repeat(64), uid: "native-lookup" };
const account = { name: "synthetic", type: "provider", data_set: "" }, token = "33333333-3333-4333-8333-333333333333";
const titles = { old_title: "Work", new_title: "Arbeit" }, plain = value => JSON.parse(JSON.stringify(value));
function boot(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage(value) {
    messages.push(typeof value === "string" ? JSON.parse(value) : plain(value));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  w.App.init({ daten: {}, neu: false });
  return { w, t: w.OrganizerTest, messages, last: () => messages.filter(value => value.cmd === "telefon_kontaktgruppentitel").at(-1) };
}
function response(message) {
  return { ok: true, requestId: message.requestId, device_id: message.device_id, fingerprint: message.fingerprint,
    version: 20, request_id: message.requestId, action: message.action, uid: message.uid,
    old_title: message.old_title, new_title: message.new_title, group_id: message.group_id || "42", account: plain(message.account || account),
    group_identity: "b".repeat(64), state: message.action === "inspect" ? "current" : message.action === "prepare" ? "prepared" : "saved",
    ...(message.action === "inspect" ? { current_title: "Arbeit" } : { token: message.token || token }) };
}
async function prepare(b) {
  const pending = b.t.kontaktGruppenTitelAbfragen(source, "prepare", titles), report = response(b.last());
  b.w.App.kontaktGruppenTitelErgebnis(report); return pending;
}
async function roundtrip(web) {
  const b = boot(web);
  try {
    const prepared = await prepare(b), extra = { ...titles, token, prepared };
    const pending = b.t.kontaktGruppenTitelAbfragen(source, "apply", extra), report = response(b.last());
    extra.prepared.account.name = "changed after dispatch";
    b.w.App.kontaktGruppenTitelErgebnis(report);
    assert.equal((await pending).group_id, "42");
    const inspectExtra = { ...titles, group_id: "42", account: plain(account) };
    const inspection = b.t.kontaktGruppenTitelAbfragen(source, "inspect", inspectExtra), current = response(b.last());
    inspectExtra.account.name = "changed after dispatch";
    b.w.App.kontaktGruppenTitelErgebnis(current);
    assert.equal((await inspection).current_title, "Arbeit");
    assert.ok(!("token" in b.last()), "Readonly inspection sent a mutation ticket");
  } finally { b.w.close(); }
}
async function wrongReport(web, field) {
  const b = boot(web);
  try {
    const prepared = await prepare(b);
    const pending = b.t.kontaktGruppenTitelAbfragen(source, "apply", { ...titles, token, prepared });
    const rejected = assert.rejects(pending), report = response(b.last());
    if (field === "account") report.account.name = "another";
    else if (field === "group_id") report.group_id = "43";
    else if (field === "group_identity") report.group_identity = "c".repeat(64);
    else if (field === "extra") report.unrequested = true;
    else if (field === "boolean") report.new_title = true;
    else if (field === "state") report.state = "prepared";
    else if (field === "version") report.version = 19;
    else if (field === "uid") report.uid = "another-lookup";
    else if (field === "fingerprint") report.fingerprint = "d".repeat(64);
    else if (field === "device_id") report.device_id = "notes:44444444-4444-4444-8444-444444444444";
    else if (field === "request_id" || field === "token") report[field] = "44444444-4444-4444-8444-444444444444";
    else if (field === "old_title") report.old_title = "Another";
    else if (field === "new_title") report.new_title = "Another";
    else if (field === "book") b.w.App.init({ daten: {}, neu: false });
    b.w.App.kontaktGruppenTitelErgebnis(report); await rejected;
  } finally { b.w.close(); }
}
async function invalidAndBounded(web) {
  const b = boot(web);
  try {
    for (const extra of [{ ...titles, new_title: "Work" }, { ...titles, new_title: "Cafe\u0301" },
      { ...titles, new_title: "x".repeat(257) }, { ...titles, new_title: "\uD800" }, { ...titles, token }, { ...titles, fields: {} }])
      await assert.rejects(b.t.kontaktGruppenTitelAbfragen(source, "prepare", extra));
    await assert.rejects(b.t.kontaktGruppenTitelAbfragen({ ...source, deviceId: "kde:foreign" }, "prepare", titles));
    await assert.rejects(b.t.kontaktGruppenTitelAbfragen(source, "apply", { ...titles, token }));
    for (const group_id of ["0", "+1", "01", "9223372036854775808"])
      await assert.rejects(b.t.kontaktGruppenTitelAbfragen(source, "inspect", { ...titles, group_id, account }));
    assert.equal(b.messages.filter(value => value.cmd === "telefon_kontaktgruppentitel").length, 0);
    const requests = Array.from({ length: 8 }, () => b.t.kontaktGruppenTitelAbfragen(source, "prepare", titles));
    await assert.rejects(b.t.kontaktGruppenTitelAbfragen(source, "prepare", titles));
    for (const message of b.messages.filter(value => value.cmd === "telefon_kontaktgruppentitel")) b.w.App.kontaktGruppenTitelErgebnis(response(message));
    await Promise.all(requests);
    const pending = b.t.kontaktGruppenTitelAbfragen(source, "inspect", { ...titles, group_id: "42", account });
    const rejected = assert.rejects(pending), report = response(b.last()); report.token = token;
    b.w.App.kontaktGruppenTitelErgebnis(report); await rejected;
  } finally { b.w.close(); }
}
async function durableJob(web, mode) {
  const b = boot(web);
  try {
    const contact = { id: "title-contact", uid: "local-contact", vorname: "Synthetic", nachname: "", firma: "", foto: "",
      vcardRoundtrip: ["CATEGORIES:Work"], telefonGruppenStand: { ...plain(source), groups: ["Work"] } };
    b.t.daten().kontakte.push(contact);
    b.t.daten().kontaktFotoCache = { version: 4, deviceId: source.deviceId, fingerprint: source.fingerprint,
      entries: [{ uid: source.uid, modified_ms: 1 }, { uid: "unbound-native-contact", modified_ms: 1 }] };
    const epoch = String(b.t.daten().syncEpoch || "");
    const proof = { uid: source.uid, ...titles, group_id: "42", account: plain(account), group_identity: "b".repeat(64) };
    const resume = ["resume", "converged", "remote", "rebound", "restore", "before-prepare"].includes(mode);
    if (resume) contact.telefonGruppenTitelAenderung = b.t.normalisiereTelefonGruppenTitelAenderung({ version: 1,
      id: "55555555-5555-4555-8555-555555555555", source, proof, wish: "Arbeit", baseTitle: "Work", epoch: mode === "restore" ? epoch + "-old" : epoch, state: "pending" });
    b.w.App.telefonStand({ peers: [{ device_id: source.deviceId.slice(6), own_device: true, remote_own_device: true,
      state: "online_wifi", contact_group_titles_write_available: true, contacts_fingerprint: source.fingerprint }] });
    let done = false, failure = null, edited = false, retried = false, applyCount = 0, mutations = 0, saves = 0, durableClear = false;
    let nativeTitle = mode === "converged" ? "Arbeit" : mode === "remote" ? "Phone change" : "Work";
    const track = promise => promise.then(() => { done = true; }, error => { failure = error; done = true; });
    if (mode === "ui") {
      const card = b.t.kontaktKarte(contact); b.w.document.body.append(card);
      const select = card.querySelector(".kontakt-gruppentitel-auswahl select"); assert.equal(select.value, "Work");
      assert.ok(card.querySelector("[data-gruppentitel-umbenennen]"));
      const action = b.t.oeffneTelefonGruppenTitelDialog(contact, select.value);
      const dialog = b.w.document.querySelector("#eingabe-schleier form");
      assert.ok(dialog.textContent.includes("Memberships are preserved"));
      dialog.querySelector("input").value = "Arbeit";
      dialog.dispatchEvent(new b.w.Event("submit", { bubbles: true, cancelable: true }));
      track(action);
    } else track(resume ? b.t.sendeTelefonKontaktGruppenTitel(contact) : b.t.starteTelefonGruppenTitelAenderung(contact, "Work", "Arbeit"));
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      const message = b.messages.shift();
      if (!message) {
        if (done && ["lost", "bad-saved"].includes(mode) && !retried) {
          retried = true; done = false; track(b.t.sendeTelefonKontaktGruppenTitel(contact)); continue;
        }
        if (mode === "save-failed" && failure || ["restore", "key-switch", "book-switch"].includes(mode) && done ||
            done && ["remote", "rebound"].includes(mode) && contact.telefonGruppenTitelAenderung?.state === "conflict" ||
            done && !contact.telefonGruppenTitelAenderung && durableClear) break;
        await new Promise(resolve => setTimeout(resolve, 5)); continue;
      }
      if (message.cmd === "speichern") {
        const payload = JSON.parse(message.text), marker = payload.kontakte.find(value => value.id === contact.id).telefonGruppenTitelAenderung;
        if (marker) {
          assert.ok(marker.proof.group_identity && marker.proof.group_id && marker.proof.account);
          assert.ok(!("token" in marker.proof), "An ephemeral native ticket was persisted instead of just its group identity");
        } else durableClear = true;
        b.w.App.gespeichert({ id: message.id, ok: mode !== "save-failed" }); saves++; continue;
      }
      if (message.cmd !== "telefon_kontaktgruppentitel") continue;
      const report = response(message);
      if (message.action === "inspect") {
        report.current_title = nativeTitle;
        if (mode === "rebound") report.group_identity = "c".repeat(64);
      } else if (message.action === "prepare") {
        assert.equal(message.old_title, nativeTitle, "A different native title was silently overwritten");
        report.token = message.requestId;
        if (mode === "before-prepare" && !edited) { edited = true; b.t.setzeTelefonGruppenTitelWunsch(contact, "Other").catch(() => {}); }
      } else {
        assert.ok(saves > 0, "Native title apply preceded durable local SaveACK");
        applyCount++; nativeTitle = message.new_title; mutations++;
        if (mode === "cancel") {
          const card = b.t.kontaktKarte(contact); b.w.document.body.append(card);
          card.querySelector("[data-gruppentitel-stop]").click();
        }
        if (mode === "key-switch") b.w.App.telefonStand({ peers: [{ device_id: source.deviceId.slice(6), own_device: true, remote_own_device: true,
          state: "online_wifi", contact_group_titles_write_available: true, contacts_fingerprint: "c".repeat(64) }] });
        if (mode === "book-switch") b.w.App.init({ daten: { kontakte: [{ id: "replacement", vorname: "New book" }], syncEpoch: "replacement-epoch" }, neu: false });
        if (["late-edit", "late-undo"].includes(mode) && !edited) {
          edited = true; b.t.setzeTelefonGruppenTitelWunsch(contact, mode === "late-undo" ? "Work" : "Other").catch(() => {});
        }
        if (mode === "lost" && !retried) {
          b.w.App.kontaktGruppenTitelErgebnis({ ok: false, requestId: message.requestId, code: "contact_group_title_timeout" }); continue;
        }
        if (mode === "bad-saved" && !retried) report.group_id = "43";
      }
      b.w.App.kontaktGruppenTitelErgebnis(report);
    }
    if (["remote", "rebound"].includes(mode)) {
      assert.equal(mutations, 0); assert.equal(contact.telefonGruppenTitelAenderung.state, "conflict");
    } else if (mode === "restore") {
      assert.equal(mutations, 0); assert.ok(contact.telefonGruppenTitelAenderung);
      assert.ok(!b.messages.some(value => value.cmd === "telefon_kontaktgruppentitel"));
    } else if (["key-switch", "book-switch"].includes(mode)) {
      assert.equal(mutations, 1); assert.ok(contact.telefonGruppenTitelAenderung, "A stale source/book callback cleared the previous wish");
      if (mode === "book-switch") assert.equal(b.t.daten().kontakte[0].id, "replacement");
    } else if (mode === "save-failed") {
      assert.ok(failure); assert.equal(mutations, 0); assert.ok(contact.telefonGruppenTitelAenderung);
    } else {
      assert.equal(failure, null); assert.equal(contact.telefonGruppenTitelAenderung, null, mode + ": native proof left a pending title wish");
      assert.equal(nativeTitle, mode === "late-undo" ? "Work" : ["late-edit", "before-prepare"].includes(mode) ? "Other" : "Arbeit");
      assert.equal(applyCount, mode === "converged" ? 0 : ["late-edit", "late-undo"].includes(mode) ? 2 : 1);
      assert.ok(durableClear);
      assert.deepEqual(plain(b.t.daten().kontaktFotoCache.entries).map(value => value.uid), ["unbound-native-contact"], "Stale known-UID group cards were not invalidated selectively");
    }
  } finally { b.w.close(); }
}
(async () => {
  const windows = path.resolve(__dirname, "../app/web"), linux = path.resolve(__dirname, "../../magnolie-organizer/web");
  assert.ok(fs.existsSync(path.join(windows, "index.html")), "The packaged Windows frontend is missing");
  for (const web of [windows, ...(fs.existsSync(path.join(linux, "index.html")) ? [linux] : [])]) {
    await roundtrip(web);
    for (const field of ["account", "group_id", "group_identity", "extra", "boolean", "state", "version", "uid", "fingerprint", "device_id", "request_id", "token", "old_title", "new_title", "book"])
      await wrongReport(web, field);
    await invalidAndBounded(web);
    for (const mode of ["success", "ui", "cancel", "resume", "converged", "lost", "bad-saved", "late-edit", "late-undo", "before-prepare", "remote", "rebound", "restore", "key-switch", "book-switch", "save-failed"])
      await durableJob(web, mode);
    console.log("PASS contact group title broker and 16 durable/UI jobs: native identity, SaveACKs, lost results, late edits/undo, source/book/restore and selective refresh " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
