"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
// Linux EDS/DAV stores deferred per-card provider reviews. Windows native
// conflict handling is exercised separately by contact-sync-conflicts.js.
const web = path.resolve(__dirname, "../../magnolie-organizer/web");
const tick = () => new Promise(r => setTimeout(r, 5));
async function check(mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const eds = mode.startsWith("eds-");
  const w = dom.window, messages = [], source = eds ? "eds:fixture" : "generic-dav-addressbook:fixture";
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => {
      if (mode === "stale") w.OrganizerTest.daten().kontakte[0].notiz = "Changed meanwhile";
      w.App.mutationsSnapshot({ token: m.token, ok: mode !== "snapshot-error" });
    });
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ neu: false, regional: { language: "en" }, daten: { kontakte: [
      { id: "local", uid: "same", vorname: "Local", nachname: "Person", sync: true,
        syncQuellen: { [source]: { id: "/person.vcf", etag: "v1", inhaltSha256: "old" } },
        kontaktProviderKonflikte: { [source]: { name: "Fixture", entfernt: mode.endsWith("deleted"), transport: eds ? "eds" : "dav", nurLesen: mode === "eds-deleted",
          kontakt: { uid: "same", vorname: "Remote", nachname: "Person", firma: "Source" },
          mapping: { id: eds ? "same" : "/person.vcf", etag: eds ? "" : "v2", transport: eds ? "eds" : "dav", inhaltFormat: "linux-1", inhaltSha256: "remote" } } } },
      { id: "other", uid: "same", vorname: "Other", nachname: "Person" }
    ] } });
    const T = w.OrganizerTest;
    if (mode.startsWith("batch-")) {
      const other = T.daten().kontakte[1]; other.uid = "other-uid";
      other.syncQuellen = { [source]: { id: "/other.vcf", etag: "v1" } };
      other.kontaktProviderKonflikte = { [source]: { transport: "dav", entfernt: false,
        kontakt: { uid: "other-uid", vorname: "RemoteOther", nachname: "Person" },
        mapping: { id: "/other.vcf", etag: "v2", inhaltFormat: "linux-1", inhaltSha256: "other-remote" } } };
    }
    T.zustand().adressen.buchstabe = "P"; T.zustand().adressen.auswahlId = "local";
    w.document.querySelector('.registerknopf[title="Contacts"]').click();
    const button = w.document.querySelector("[data-provider-konflikt]"); assert.ok(button, "pending provider conflict is not reachable from the contact card");
    button.click();
    if (mode.endsWith("deleted")) {
      [...w.document.querySelectorAll("button")].find(b => b.textContent === "Keep existing" && b.closest(".eingabe-schleier, #dialog-schleier")).click();
    } else {
      const choice = w.document.querySelector("[data-import-entscheidung]"); assert.ok(choice);
      assert.equal(choice.querySelector('option[value="new"]'), null);
      assert.equal(choice.querySelector('option[value="skip"]'), null);
      assert.equal(w.document.querySelector("[data-import-ziel]").disabled, true);
      if (mode.startsWith("batch-")) {
        const all = w.document.querySelector("[data-import-rest]");
        for (let n = 0; n < 200 && all.disabled; n++) await tick();
        assert.equal(all.disabled, false); all.checked = true; all.dispatchEvent(new w.Event("change"));
      }
      if (mode === "cancel") [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click();
      else { choice.value = mode.endsWith("keep") ? "keep" : mode === "merge" ? "merge" : "replace"; choice.dispatchEvent(new w.Event("change")); w.document.querySelector("[data-import-anwenden]").click(); }
    }
    for (let n = 0; n < 200 && !["cancel", "stale", "snapshot-error"].includes(mode) && T.daten().kontakte[0].kontaktProviderKonflikte; n++) await tick();
    await tick(); await tick();
    const local = T.daten().kontakte[0];
    assert.equal(T.daten().kontakte.length, 2); assert.equal(T.daten().kontakte[1].vorname, mode === "batch-replace" ? "RemoteOther" : "Other");
    if (mode.startsWith("batch-")) {
      assert.equal(T.daten().kontakte[1].kontaktProviderKonflikte, undefined);
      assert.equal(T.daten().kontakte[1].syncQuellen[source].etag, "v2");
    }
    assert.equal(local.id, "local"); assert.equal(local.uid, "same");
    if (["cancel", "stale", "snapshot-error"].includes(mode)) {
      assert.equal(local.vorname, "Local"); assert.ok(local.kontaktProviderKonflikte);
      assert.equal(local.syncQuellen[source].etag, "v1");
    } else {
      assert.equal(local.vorname, mode.endsWith("replace") ? "Remote" : "Local");
      assert.equal(local.kontaktProviderKonflikte, undefined);
      assert.equal(local.syncQuellen[source].etag, eds ? "" : "v2");
      assert.equal(local.syncQuellen[source].inhaltSha256, mode.endsWith("deleted") ? "" : "remote");
      if (eds) { assert.equal(local.syncQuellen[source].pruefungFreigegeben, true); assert.equal(local.davHref, undefined); }
      if (mode === "merge") assert.equal(local.firma, "Source");
    }
  } finally { w.close(); }
}
(async () => { for (const mode of ["replace", "merge", "keep", "cancel", "stale", "snapshot-error", "deleted", "eds-keep", "eds-replace", "eds-deleted", "batch-keep", "batch-replace"]) await check(mode);
  console.log("CONTACT PROVIDER REVIEW PASSED: explicit target, source baseline, cancellation, deletion restoration");
})().catch(error => { console.error(error); process.exitCode = 1; });
