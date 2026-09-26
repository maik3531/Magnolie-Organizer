"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const {spawnSync} = require("node:child_process"), {webcrypto} = require("node:crypto"), {JSDOM} = require("jsdom");
const root = path.resolve(__dirname, ".."), web = path.join(root, "app/web");
const source = "thunderbird-addressbook:managed:fixture:book";
const dotnet = process.env.DOTNET_HOST_PATH || "dotnet";
const runner = process.env.MAGNOLIE_CORE_TESTS || path.join(__dirname, "bin/Debug/net8.0/CoreTests.dll");
if (!process.env.MAGNOLIE_CORE_TESTS) {
  const build = spawnSync(dotnet, ["build", path.join(__dirname, "CoreTests.csproj"), "--no-restore", "-v", "quiet"], {encoding: "utf8"});
  assert.equal(build.status, 0, build.error?.message || build.stderr || build.stdout);
}
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
async function check(mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/", pretendToBeVisual: true});
  const w = dom.window, messages = [], writes = [];
  Object.defineProperty(w, "crypto", {value: webcrypto}); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = {messageHandlers: {test: {postMessage(text) {
    const message = JSON.parse(text); messages.push(message);
    if (message.cmd === "speichern") {
      writes.push(JSON.parse(message.text));
      let plan;
      if (message.kontaktePruefen) {
        const native = spawnSync(dotnet, [runner, "--contact-cleanup-fixture"], {input: message.text, encoding: "utf8"});
        assert.equal(native.status, 0, native.stderr);
        plan = JSON.parse(native.stdout);
        if (mode === "bad-proof") plan.fingerprint = "0".repeat(64);
      }
      queueMicrotask(() => w.App.gespeichert({id: message.id, ok: true, kontaktPruefung: plan}));
    }
    if (message.cmd === "mutations_snapshot") queueMicrotask(() => {
      if (mode === "stale") w.OrganizerTest.daten().kontakte[0].notiz = "Concurrent edit";
      w.App.mutationsSnapshot({token: message.token, ok: mode !== "snapshot-error"});
    });
  }}}};
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const card = {id: "tree", uid: "mag-tree@magnolie-organizer", vorname: "Mia", nachname: "Müller",
      telefone: [{wert: "+49305550123", typen: ["CELL", "VOICE"], label: "Mobile"}],
      baumKontakt: {freigabeId: "tree-share", version: 1, quelle: "peer", partner: ["peer"]},
      sync: true, syncQuellen: {[source]: {id: "redundant", etag: '"d1"', eigen: true}}};
    const copy = {...JSON.parse(JSON.stringify(card)), id: "provider", uid: "provider-original", baumKontakt: null,
      anzeigename: "Mia Müller", vcardRoundtrip: ["N:Müller;Mia;;;", "FN:Mia Müller"],
      telefone: [{wert: "+49305550123", typen: ["CELL", "VOICE", "PREF"], label: "", vcardParameter: []}],
      syncQuellen: {[source]: {id: "original", etag: '"o1"', eigen: true}}};
    w.App.init({neu: false, kontaktSyncPruefung: true, daten: {kontakte: [card, copy],
      aufgaben: [{id: "task", titel: "Linked", kontaktId: "provider"}],
      einstellungen: {sync: {adressbuchUid: source, automatisch: false}}}});
    await tick(); messages.length = 0; writes.length = 0;
    const T = w.OrganizerTest;
    T.starteSync(true);
    for (let i = 0; i < 150 && !messages.some(m => m.cmd === "sync") && !T.daten().syncStatus.letzterFehler; i++) await tick();
    if (mode === "success") {
      assert.equal(T.daten().kontakte.length, 1);
      assert.equal(T.daten().kontakte[0].id, "tree");
      assert.equal(T.daten().kontakte[0].syncQuellen[source].id, "original", "the original provider record must survive");
      assert.equal(T.daten().aufgaben[0].kontaktId, "tree");
      assert.equal(T.daten().papierkorb.filter(p => p.art === "duplicate").length, 1);
      const tombstone = T.daten().geloescht.kontakte[0];
      assert.equal(tombstone.syncQuellen[source].id, "redundant");
      assert.notEqual(tombstone.uid, T.daten().kontakte[0].uid);
      assert.equal(tombstone.kontaktDuplikat.keeperId, "original");
      const request = messages.find(m => m.cmd === "sync");
      assert.ok(request, "native synchronization must resume after consolidation");
      assert.equal(request.daten.kontakte.length, 1);
      assert.equal(request.daten.geloescht.kontakte[0].kontaktDuplikat.keeperId, "original");
      assert.equal(messages.filter(m => m.cmd === "mutations_snapshot").length, 1);
      assert.equal(writes[0].kontakte.length, 2, "the original contacts must be durable before the pre-change snapshot");
      assert.equal(writes.at(-1).kontakte.length, 1, "the consolidated state must be saved before sending sync");
      const archivedReference = JSON.parse(JSON.stringify(T.daten()));
      archivedReference.aufgaben[0].kontaktId = "provider";
      assert.equal(T.normalisiere(archivedReference).aufgaben[0].kontaktId, "tree", "old references must resolve after reload/restore");
      T.mergeKontakte([{...copy, id: "reimport", geaendert: Date.now()}]);
      assert.equal(T.daten().kontakte.length, 1, "a retired provider UID must not create another card on reimport");
    } else {
      assert.equal(T.daten().kontakte.length, 2, mode);
      assert.equal(T.daten().geloescht.kontakte.length, 0, mode);
      assert.equal(messages.filter(m => m.cmd === "sync").length, 0, "no provider operation after failed validation: " + mode);
    }
  } finally { w.close(); }
}
(async () => {
  for (const mode of ["success", "bad-proof", "snapshot-error", "stale"]) await check(mode);
  console.log("CONTACT SYNC CLEANUP PASSED: native planner, snapshot boundary, links, source identity, failed/stale guards");
})().catch(error => {console.error(error); process.exitCode = 1;});
