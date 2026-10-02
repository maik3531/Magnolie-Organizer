"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const testPath = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(testPath, module);
harness.filename = testPath;
harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(testPath, "utf8").split("async function run(web)")[0]
  .replace('w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
    'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kontaktFormular, testeFotoLesen: callback => { kontaktFotoLesen = callback; }, starteSync: starteSync, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports = { boot, roots };", testPath);
const plain = value => JSON.parse(JSON.stringify(value));

(async () => {
  let count = 0;
  for (const web of harness.exports.roots) {
    for (const action of ["newer-selection", "remove"]) {
      const b = await harness.exports.boot(web, { kontakte: [{ id: "photo", uid: "photo-source",
        vorname: "Photo", nachname: "Fixture", foto: "data:image/png;base64,AQID" }] });
      try {
        const reads = [];
        b.t.testeFotoLesen((file, done) => reads.push(done));
        const form = b.t.kontaktFormular(b.t.daten().kontakte[0]);
        b.w.document.body.append(form);
        const picker = form.querySelector("#kontakt-foto-datei");
        Object.defineProperty(picker, "files", { value: [{ name: "fixture.png" }] });
        picker.dispatchEvent(new b.w.Event("change"));
        if (action === "remove") form.querySelector("#kontakt-foto-knopf").click();
        else {
          picker.dispatchEvent(new b.w.Event("change"));
          reads[1]("data:image/png;base64,BAUG");
        }
        reads[0]("data:image/png;base64,BwgJ");
        form.querySelector(".kontakt-form-knoepfe button").click();
        assert.equal(b.t.daten().kontakte[0].foto, action === "remove" ? "" : "data:image/png;base64,BAUG",
          "late photo decoding must not reverse a newer selection or removal");
        assert.equal(b.t.daten().kontakte[0].fotoManuell, true, "real photo controls persist manual priority");
        count++;
      } finally { b.close(); }
    }
    for (const manualPhoto of ["data:image/png;base64,AQID", ""]) {
      const b = await harness.exports.boot(web, { kontakte: [{ id: "photo", uid: "photo-source",
        vorname: "Photo", nachname: "Fixture", foto: manualPhoto, fotoManuell: true, geaendert: 1 }] });
      try {
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          const message = JSON.parse(text); b.messages.push(message);
          if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
          if (message.cmd === "mutations_snapshot") queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: true }));
        };
        const importing = b.w.App.importErgebnis({ kontakte: [{ uid: "photo-source", vorname: "Photo", nachname: "Fixture",
          foto: "data:image/png;base64,BAUG", geaendert: 200 }] });
        const choice = b.w.document.querySelector('[data-import-entscheidung="0"]');
        choice.value = "merge"; choice.dispatchEvent(new b.w.Event("change"));
        b.w.document.querySelector("[data-import-anwenden]").click();
        await importing;
        assert.equal(b.t.daten().kontakte[0].foto, manualPhoto, "newer imports must respect a manual photo or explicit removal");
        b.t.speichereJetzt();
        assert.equal(JSON.parse(b.messages.filter(m => m.cmd === "speichern").at(-1).text).kontakte[0].fotoManuell, true);
        await new Promise(resolve => setImmediate(resolve));
        count++;
      } finally { b.close(); }
    }
    for (const mutation of ["edit-add-delete", "import", "personal", "retry"]) {
      const b = await harness.exports.boot(web, {
        syncNachRestore: { additiv: true, loeschungsfrei: true },
        einstellungen: { sync: { adressbuchUid: "windows-contacts" } },
        aufgaben: [{ id: "one", uid: "one", titel: "Before", geaendert: 1 },
          { id: "remove", uid: "remove", titel: "Delete me", geaendert: 1 }]
      });
      try {
        b.t.starteSync(false); b.ack();
        const request = b.messages.find(message => message.cmd === "sync");
        assert.ok(request);
        assert.equal(request.daten.syncNachRestore.additiv, true);
        const response = plain(request.daten);
        response.transactionId = request.transactionId;
        response.syncNachRestore = null;
        response.aufgaben[0].notiz = "Remote note";
        response.aufgaben[1].sync = true;
        response.aufgaben[1].syncQuellen = { source: { id: "created-in-flight", etag: "created" } };
        if (mutation === "retry") b.w.App.syncFehler("synthetic failure");
        if (mutation === "import") b.w.App.importErgebnis({ aufgaben: [{ uid: "import", titel: "Imported" }] });
        else if (mutation === "personal") b.t.personalSyncSetze({ kind: "task", value: {
          title: "Personal", note: "", due: "2026-09-11", priority: 2, completed: false,
          remind: false, modified_ms: 200 } }, "one", false);
        else {
          b.t.daten().aufgaben[0].titel = "Edited";
          b.t.daten().aufgaben.push({ id: "new", uid: "new", titel: "Added" });
          b.t.daten().aufgaben = b.t.daten().aufgaben.filter(item => item.id !== "remove");
          b.t.daten().geloescht.aufgaben.push({ uid: "remove", zeit: 200,
            syncQuellen: mutation === "retry" ? { source: { id: "created-in-flight", etag: "observed" } } : {} });
        }
        b.t.speichereJetzt(); b.ack();
        if (mutation === "retry" && web.includes("Windows")) {
          b.t.starteSync(false); b.ack();
          assert.equal(b.messages.filter(message => message.cmd === "sync").at(-1).transactionId, request.transactionId);
        }
        b.w.App.syncFertig(response);
        const tasks = b.t.daten().aufgaben;
        if (mutation === "import") assert.ok(tasks.some(item => item.titel === "Imported"));
        else if (mutation === "personal") assert.equal(tasks.find(item => item.id === "one").titel, "Personal");
        else {
          assert.equal(tasks.find(item => item.id === "one").titel, "Edited");
          assert.ok(tasks.some(item => item.id === "new"));
          assert.ok(!tasks.some(item => item.id === "remove"));
          assert.ok(b.t.daten().geloescht.aufgaben.some(item => item.uid === "remove"));
          assert.equal(b.t.daten().geloescht.aufgaben.find(item => item.uid === "remove").syncQuellen.source.etag,
            mutation === "retry" ? "observed" : "created");
        }
        assert.equal(tasks.find(item => item.id === "one").notiz, "Remote note");
        assert.ok(b.t.daten().syncAbgleichNachweis);
        count++;
      } finally { b.close(); }
    }
    for (const [collection, field] of [["termine", "titel"], ["kontakte", "vorname"], ["jahrestage", "name"]]) {
      const b = await harness.exports.boot(web, {
        einstellungen: { sync: { adressbuchUid: "windows-contacts" } },
        [collection]: [{ id: "one", uid: "one", [field]: "Before", datum: "2026-09-11" },
          { id: "remove", uid: "remove", [field]: "Remove", datum: "2026-09-12" }]
      });
      try {
        b.t.starteSync(false); b.ack();
        const request = b.messages.find(message => message.cmd === "sync");
        const response = plain(request.daten);
        response.transactionId = request.transactionId;
        response.requestId = request.requestId;
        response[collection][1].sync = true;
        response[collection][1].syncQuellen = { source: { id: "created-in-flight", etag: "created" } };
        b.t.daten()[collection][0][field] = "Edited";
        b.t.daten()[collection].splice(1, 1, { id: "new", uid: "new", [field]: "Added", datum: "2026-09-13" });
        b.t.speichereJetzt(); b.ack();
        b.w.App.syncFertig(response);
        assert.equal(b.t.daten()[collection].find(item => item.id === "one")[field], "Edited");
        assert.ok(b.t.daten()[collection].some(item => item.id === "new"));
        assert.ok(!b.t.daten()[collection].some(item => item.id === "remove"));
        if (collection !== "jahrestage") assert.equal(b.t.daten().geloescht[collection]
          .find(item => item.uid === "remove").syncQuellen.source.etag, "created");
        count++;
      } finally { b.close(); }
    }
    const b = await harness.exports.boot(web, {
      syncNachRestore: { additiv: true }, syncMetadaten: { ersteSyncLoeschungsfrei: true },
      einstellungen: { sync: { adressbuchUid: "windows-contacts" } }
    });
    try {
      b.t.starteSync(false); b.ack();
      const request = b.messages.find(message => message.cmd === "sync");
      const response = plain(request.daten);
      response.transactionId = request.transactionId || "b".repeat(64);
      response.requestId = request.requestId;
      response.syncNachRestore = null;
      response.syncMetadaten.ersteSyncLoeschungsfrei = false;
      response.syncMetadaten.nextcloud.pendingCommitId = response.transactionId;
      b.w.App.syncFertig(response);
      const commits = () => b.messages.filter(message => ["sync_commit", "sync_bestaetigen"].includes(message.cmd));
      assert.equal(commits().length, 0, "Completion acknowledged before durable save ACK");
      b.ack();
      assert.equal(commits().length, 1);
      const persisted = JSON.parse(b.saves().at(-1).text);
      assert.equal(persisted.syncMetadaten.ersteSyncLoeschungsfrei, false);
      if (web.includes("Windows")) assert.equal(persisted.syncNachRestore, null);
      b.t.daten().aufgaben.push({ id: "after", uid: "after", titel: "After completion" });
      b.w.App.syncFertig(response);
      assert.ok(b.t.daten().aufgaben.some(item => item.id === "after"), "Duplicate completion discarded a later edit");
      b.t.starteSync(false); b.ack();
      const sent = b.messages.filter(message => message.cmd === "sync").length;
      b.w.App.syncFertig(response);
      b.t.starteSync(false); b.ack();
      assert.equal(b.messages.filter(message => message.cmd === "sync").length, sent,
        "Stale completion unlocked a newer sync run");
      count++;
    } finally { b.close(); }
  }
  console.log(`${count} desktop data reconciliation regressions passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
