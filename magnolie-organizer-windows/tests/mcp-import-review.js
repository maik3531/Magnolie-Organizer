"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(test) { for (let index = 0; index < 1000; index++) { if (test()) return; await tick(); } throw new Error("Import review fixture timed out"); }
const watchdog = setTimeout(() => { console.error("MCP import review timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [{ id: "local", uid: "stable", vorname: "Local", nachname: "Existing", notiz: "Owned local note",
      strasse: "Old Street", plz: "10115", ort: "Owned town", sync: true, syncQuellen: { owned: { marker: "preserve" } } }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const owner = "a".repeat(48), other = "b".repeat(48), sourceRevision = "e".repeat(64), noteText = "🌸".repeat(40000);
      let sequence = 0, holdSave = false, holdSnapshot = false, snapshotFailure = false, sourceChanged = false, onImport;
      let localFailure = "", localScopeMismatch = false, onLocalImport;
      const snapshots = [], nativeImports = [], nativeLocalImports = [];
      const payload = { kontakte: [{ uid: "stable", vorname: "Remote", nachname: "Existing", notiz: "Owned incoming note", strasse: "New Street", plz: "10115", ort: "Owned town" },
        { uid: "created", vorname: "Created", nachname: "Contact", geburtstag: "--02-29", geburtstagJahrUnbekannt: true, sync: true,
          syncQuellen: { injected: {} }, baumKontakt: { freigabeId: "injected" }, kontaktZeit: { hash: "injected", zeit: Date.now() }, fotoAlternativen: ["injected"] }],
        geburtstage: [{ name: "Created Contact", datum: "--02-29", jahrUnbekannt: true, kontaktIndex: 1 }],
        termine: [{ uid: "owned-review-event", titel: "Owned review appointment", datum: "2030-01-02", zeit: "09:00", icsQuelleId: "owned-import" }],
        aufgaben: [{ uid: "owned-review-task", titel: "Owned review task", faellig: "2030-01-02", icsQuelleId: "owned-import" }],
        notizen: [{ titel: "Owned review note", text: noteText, html: "<p>" + noteText + "</p>" }] };
      const replyImport = message => b.w.App.importErgebnis(sourceChanged || message.expectedRevision && message.expectedRevision !== sourceRevision
        ? { requestId: message.requestId, art: message.art, ok: false, code: "conflict", fehler: "Owned source changed" }
        : { ...JSON.parse(JSON.stringify(payload)), requestId: message.requestId, art: message.art, pfad: message.pfad, ok: true,
          bytes: 200000, sha256: "f".repeat(64), revision: sourceRevision, kontaktQuelle: "datei:" + "d".repeat(64), uebersprungen: 0, wiederholend: 0 });
      const replyLocal = message => b.w.App.importErgebnis(localFailure
        ? { requestId: message.requestId, art: "lokal", ok: false, code: localFailure, fehler: "Owned private local scan failure" }
        : { requestId: message.requestId, art: "lokal", ok: true, source: message.quelle,
          scope: localScopeMismatch ? "wrong-scope" : message.bereich === "kontakte" ? "contacts" : "all", revision: "c".repeat(64), uebersprungen: 0, wiederholend: 0,
          kontakte: [{ id: "owned-external-source-id", uid: "owned-local-contact", vorname: "Owned native", nachname: "Local import", geburtstag: "--03-04", sync: true, syncQuellen: { injected: {} } }],
          termine: message.bereich === "kontakte" ? [] : [{ uid: "owned-local-event", datum: "2030-03-04", titel: "Owned scanned appointment", icsQuelleId: "owned-local-source" }],
          aufgaben: message.bereich === "kontakte" ? [] : [{ uid: "owned-local-task", titel: "Owned scanned task", faellig: "2030-03-04" }], geburtstage: [], jahrestage: [] });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern" && !holdSave) queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
        if (message.cmd === "import" && message.requestId) { nativeImports.push(message); if (onImport) onImport(message); else queueMicrotask(() => replyImport(message)); }
        if (message.cmd === "import_lokal" && message.requestId) { nativeLocalImports.push(message); if (onLocalImport) onLocalImport(message); else queueMicrotask(() => replyLocal(message)); }
        if (message.cmd === "mutations_snapshot") { snapshots.push(message); if (!holdSnapshot) queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: !snapshotFailure })); }
      };
      const firstNotebook = b.t.daten().notizbuecher[0];
      b.t.daten().notizbuecher.push({ ...JSON.parse(JSON.stringify(firstNotebook)), id: "owned-review-notebook", name: "Owned review notebook" });
      b.t.speichereJetzt(); await tick();
      async function rpc(method, params, actualOwner = owner, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0"), id = explicitId ?? sequence;
        await b.w.App.mcpRequest({ session: actualOwner, invocation, message: { jsonrpc: "2.0", ...(method.startsWith("notifications/") ? {} : { id }), method, ...(params === undefined ? {} : { params }) } });
        const response = b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation);
        assert.ok(response, "Every accepted review invocation must settle"); return response.response;
      }
      async function tool(name, args, actualOwner = owner, explicitId) {
        const response = await rpc("tools/call", { name, ...(args === undefined ? {} : { arguments: args }) }, actualOwner, explicitId);
        assert.ok(!response.error, JSON.stringify(response)); return response.result;
      }
      const success = result => { assert.equal(result.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const error = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      for (const session of [owner, other]) {
        await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-review-fixture", version: "1" } }, session);
        await rpc("notifications/initialized", undefined, session);
      }
      const revision = async () => success(await tool("organizer_book_revision_read")).revision;
      const begin = async (session = owner) => success(await tool("organizer_import_review_begin", { format: "vcf", path: "/owned-fixture/mixed.vcf",
        expected_revision: sourceRevision, expected_book_revision: await revision(), notebook_id: "owned-review-notebook" }, session));
      const cancelRpc = async id => { await rpc("notifications/cancelled", { requestId: id }); };
      const skipContacts = async review => success(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: review.selection_revision,
        decisions: [{ index: 0, action: "skip" }, { index: 1, action: "skip" }] }));
      const applyArgs = review => ({ token: review.token, expected_book_revision: review.book_revision, expected_selection_revision: review.selection_revision });
      const before = JSON.stringify(b.t.daten()), savesBefore = b.saves().length, clockRuntime = b.t.daten().zeiterfassung;
      const review = await begin();
      assert.equal(review.contacts_total, 2); assert.equal(review.unresolved_contacts, 1);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, savesBefore);
      assert.equal(b.w.document.querySelector(".kontakt-datei-pruefung"), null);
      error(await tool("organizer_import_review_read", { token: review.token }, other), "not_found");
      const page = success(await tool("organizer_import_review_read", { token: review.token, limit: 1, candidate_limit: 1 }));
      assert.equal(page.plans[0].index, 0); assert.equal(page.plans[0].action, null); assert.equal(page.plans[0].candidates[0].id, "local"); assert.equal(page.next_offset, 1);
      const importsBeforeContent = nativeImports.length;
      const card = success(await tool("organizer_import_review_content_read", { token: review.token, section: "kontakte", index: 1 }));
      const incoming = JSON.parse(Buffer.from(card.data, "base64").toString("utf8"));
      assert.equal(incoming.sync, undefined); assert.equal(incoming.baumKontakt, undefined); assert.equal(incoming.kontaktZeit, undefined); assert.equal(incoming.fotoAlternativen, undefined);
      const chunk = success(await tool("organizer_import_review_content_read", { token: review.token, section: "notizen", index: 0, content_path: ["text"], limit: 5 }));
      assert.equal(chunk.representation, "string"); assert.equal(chunk.revision, createHash("sha256").update(noteText).digest("hex"));
      assert.deepEqual(Buffer.from(chunk.data, "base64"), Buffer.from(noteText).subarray(0, 5));
      const chunk2 = success(await tool("organizer_import_review_content_read", { token: review.token, section: "notizen", index: 0, content_path: ["text"], offset: 5, limit: 5, expected_revision: chunk.revision }));
      assert.deepEqual(Buffer.from(chunk2.data, "base64"), Buffer.from(noteText).subarray(5, 10));
      const candidate = success(await tool("organizer_import_review_content_read", { token: review.token, section: "kontakte", index: 0, side: "candidate", candidate_id: "local", list_field: "anschriften" }));
      assert.equal(JSON.parse(Buffer.from(candidate.data, "base64").toString())[0].strasse, "Old Street");
      assert.equal(nativeImports.length, importsBeforeContent, "Cached content reads must not parse the source again");
      error(await tool("organizer_import_review_apply", applyArgs(review)), "decision_required");
      assert.equal(snapshots.length, 0); assert.equal(JSON.stringify(b.t.daten()), before);
      error(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: 0, decisions: [{ index: 0, action: "replace" }, { index: 999, action: "new" }] }), "invalid_selection");
      assert.equal(success(await tool("organizer_import_review_read", { token: review.token })).selection_revision, 0);
      error(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: 0, decisions: [{ index: 0, action: "newer" }] }), "invalid_selection");
      error(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: 0, decisions: [{ index: 0, action: "replace", target_id: "not-offered" }] }), "invalid_selection");
      error(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: 0, decisions: [{ index: 0, action: "merge", lists: [{ field: "anschriften", incoming_index: 0, choice: "replace", existing_index: 999 }] }] }), "invalid_selection");
      const decided = success(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: 0, decisions: [{ index: 0, action: "merge", target_id: "local",
        fields: [{ field: "vorname", choice: "incoming" }, { field: "notiz", choice: "merge" }], lists: [{ field: "anschriften", incoming_index: 0, choice: "replace", existing_index: 0 }] }] }));
      assert.equal(decided.selection_revision, 1); assert.equal(decided.unresolved_contacts, 0); assert.equal(JSON.stringify(b.t.daten()), before);
      error(await tool("organizer_import_review_decide", { token: review.token, expected_selection_revision: 0, decisions: [{ index: 0, action: "skip" }] }), "conflict");
      holdSave = holdSnapshot = true; let complete = false;
      const operation = tool("organizer_import_review_apply", applyArgs(decided)).then(value => { complete = true; return value; });
      await until(() => snapshots.length === 1); assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(complete, false);
      b.w.App.mutationsSnapshot({ token: snapshots.at(-1).token, ok: true });
      await until(() => b.saves().length > savesBefore); assert.equal(complete, false);
      const saved = b.saves().at(-1), document = JSON.parse(saved.text);
      assert.equal(document.kontakte.length, 2); assert.equal(document.kontakte.find(contact => contact.id === "local").vorname, "Remote");
      assert.equal(document.kontakte.find(contact => contact.id === "local").strasse, "New Street");
      assert.equal(document.kontakte.find(contact => contact.id === "local").syncQuellen.owned.marker, "preserve");
      const created = document.kontakte.find(contact => contact.uid === "created"); assert.equal(created.sync, false); assert.ok(!created.baumKontakt && !created.kontaktZeit);
      assert.equal(document.jahrestage.length, 1); assert.equal(document.jahrestage[0].kontaktId, created.id);
      assert.equal(document.notizen[0].notizbuchId, "owned-review-notebook"); assert.equal(b.t.daten().zeiterfassung, clockRuntime);
      b.w.App.gespeichert({ id: saved.id, ok: true });
      const applied = success(await operation); assert.equal(applied.persisted, true); assert.equal(applied.counts.contacts, 2); assert.equal(applied.counts.notes, 1);
      error(await tool("organizer_import_review_apply", applyArgs(decided)), "not_found");
      holdSave = holdSnapshot = false;
      payload.notizen.push({ titel: "Owned oversized review note", text: "Owned oversized", html: "<span>x</span>".repeat(10001) });
      const oversized = await skipContacts(await begin()), toastBeforeOversize = b.w.document.querySelector("#zettel").textContent;
      const omitted = success(await tool("organizer_import_review_apply", applyArgs(oversized)));
      assert.equal(omitted.counts.notes_skipped, 1); assert.ok(!b.t.daten().notizen.some(note => note.titel === "Owned oversized review note"));
      assert.equal(b.w.document.querySelector("#zettel").textContent, toastBeforeOversize);
      payload.notizen.pop();
      const a = await begin(), c = await begin(other);
      error(await tool("organizer_import_review_begin", { format: "vcf", path: "/owned-fixture/mixed.vcf", expected_book_revision: await revision() }), "review_limit");
      error(await tool("organizer_import_review_cancel", { token: a.token }, other), "not_found");
      b.w.App.mcpClose(other);
      const released = await begin();
      success(await tool("organizer_import_review_cancel", { token: a.token })); success(await tool("organizer_import_review_cancel", { token: released.token }));
      assert.ok(c.token);
      const staleBook = await begin(), local = b.t.daten().kontakte[0], note = local.notiz;
      local.notiz += "\nOwned concurrent edit"; error(await tool("organizer_import_review_read", { token: staleBook.token }), "conflict"); local.notiz = note;
      const expired = await begin(); b.timers.filter(timer => timer.delay === 300000 && !timer.cancelled).at(-1).fn();
      error(await tool("organizer_import_review_read", { token: expired.token }), "not_found");
      const source = await skipContacts(await begin()), current = JSON.stringify(b.t.daten()), checkpointCount = snapshots.length;
      sourceChanged = true; error(await tool("organizer_import_review_apply", applyArgs(source)), "conflict"); sourceChanged = false;
      assert.equal(JSON.stringify(b.t.daten()), current); assert.equal(snapshots.length, checkpointCount); success(await tool("organizer_import_review_cancel", { token: source.token }));
      const modal = await skipContacts(await begin()); b.t.oeffneEinstellungen();
      error(await tool("organizer_import_review_apply", applyArgs(modal)), "dialog_busy"); b.w.document.querySelector("#einstellungen-zu").click();
      success(await tool("organizer_import_review_cancel", { token: modal.token }));
      const snapshot = await skipContacts(await begin()); snapshotFailure = true;
      error(await tool("organizer_import_review_apply", applyArgs(snapshot)), "snapshot_failed"); snapshotFailure = false;
      assert.equal(JSON.stringify(b.t.daten()), current); success(await tool("organizer_import_review_cancel", { token: snapshot.token }));
      const cancelledReview = await skipContacts(await begin()); let native;
      const nativeStarted = new Promise(resolve => { onImport = message => { native = message; resolve(); }; });
      const cancelled = tool("organizer_import_review_apply", applyArgs(cancelledReview), owner, 9000);
      await nativeStarted; await cancelRpc(9000); error(await cancelled, "cancelled");
      const toast = b.w.document.querySelector("#zettel").textContent; replyImport(native); onImport = null; await tick();
      assert.equal(JSON.stringify(b.t.daten()), current); assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
      assert.equal(b.w.document.querySelector(".kontakt-datei-pruefung"), null);
      success(await tool("organizer_import_review_cancel", { token: cancelledReview.token }));
      const preparingStarted = new Promise(resolve => { onImport = message => { native = message; resolve(); }; });
      const pendingBegin = tool("organizer_import_review_begin", { format: "vcf", path: "/owned-fixture/mixed.vcf", expected_book_revision: await revision() }, owner, 9001);
      await preparingStarted; await cancelRpc(9001); error(await pendingBegin, "cancelled"); replyImport(native); onImport = null; await tick();
      const free1 = await begin(), free2 = await begin();
      success(await tool("organizer_import_review_cancel", { token: free1.token })); success(await tool("organizer_import_review_cancel", { token: free2.token }));
      const localArgs = async (extra = {}) => ({ local_source: "thunderbird", local_scope: "contacts", expected_book_revision: await revision(), ...extra });
      const localBook = JSON.stringify(b.t.daten()), localCheckpointCount = snapshots.length;
      error(await tool("organizer_import_review_begin", await localArgs({ format: "vcf", path: "/owned-fixture/mixed.vcf" })), "invalid_settings");
      assert.equal(nativeLocalImports.length, 0);
      localScopeMismatch = true; error(await tool("organizer_import_review_begin", await localArgs()), "invalid_result"); localScopeMismatch = false;
      localFailure = "unsupported_feature";
      const unavailable = await tool("organizer_import_review_begin", await localArgs()); error(unavailable, "unsupported_feature");
      assert.ok(!JSON.stringify(unavailable).includes("Owned private local scan failure")); localFailure = "";
      const localReview = success(await tool("organizer_import_review_begin", await localArgs()));
      assert.equal(localReview.contacts_total, 1); assert.equal(localReview.counts.appointments, 0);
      assert.equal(localReview.source_revision, "c".repeat(64)); assert.equal(JSON.stringify(b.t.daten()), localBook);
      assert.equal(nativeLocalImports.at(-1).quelle, "thunderbird"); assert.equal(nativeLocalImports.at(-1).bereich, "kontakte");
      assert.equal(nativeLocalImports.at(-1).pfad, undefined);
      localFailure = "conflict"; error(await tool("organizer_import_review_apply", applyArgs(localReview)), "conflict"); localFailure = "";
      assert.equal(JSON.stringify(b.t.daten()), localBook); assert.equal(snapshots.length, localCheckpointCount);
      const localSaved = success(await tool("organizer_import_review_apply", applyArgs(localReview)));
      assert.equal(localSaved.persisted, true); assert.equal(localSaved.counts.contacts, 1);
      assert.equal(nativeLocalImports.at(-1).expectedRevision, "c".repeat(64));
      const scannedContact = b.t.daten().kontakte.find(contact => contact.uid === "owned-local-contact");
      assert.equal(scannedContact.sync, false); assert.equal(Object.keys(scannedContact.syncQuellen || {}).length, 0);
      assert.equal(b.t.daten().jahrestage.filter(entry => entry.kontaktId === scannedContact.id).length, 1);
      const localAll = success(await tool("organizer_import_review_begin", await localArgs({ local_scope: "all" })));
      assert.equal(localAll.counts.appointments, 1); assert.equal(localAll.counts.tasks, 1);
      const localDecided = success(await tool("organizer_import_review_decide", { token: localAll.token, expected_selection_revision: localAll.selection_revision, decisions: [{ index: 0, action: "skip" }] }));
      success(await tool("organizer_import_review_apply", applyArgs(localDecided)));
      assert.ok(b.t.daten().termine.some(event => event.uid === "owned-local-event"));
      assert.ok(b.t.daten().aufgaben.some(task => task.uid === "owned-local-task"));
      const beforeCancelledLocal = JSON.stringify(b.t.daten());
      const localStarted = new Promise(resolve => { onLocalImport = message => { native = message; resolve(); }; });
      const cancelledLocal = tool("organizer_import_review_begin", await localArgs(), owner, 9100);
      await localStarted; await cancelRpc(9100); error(await cancelledLocal, "cancelled"); replyLocal(native); onLocalImport = null; await tick();
      assert.equal(JSON.stringify(b.t.daten()), beforeCancelledLocal); assert.equal(b.w.document.querySelector(".kontakt-datei-pruefung"), null);
      payload.kontakte = []; payload.geburtstage = []; payload.aufgaben = []; payload.notizen = [];
      payload.termine = Array.from({ length: 1501 }, (_, index) => ({ uid: "owned-bulk-review-" + index, titel: "Owned bulk appointment " + index,
        datum: "2030-02-03", zeit: "09:00", icsQuelleId: "owned-bulk-source" }));
      const timerStart = b.timers.length, checkpointsBeforeBulk = snapshots.length;
      let bulkReady = false, bulkReview, bulkError;
      const bulk = begin().then(value => { bulkReview = value; bulkReady = true; }, error => { bulkError = error; bulkReady = true; });
      await until(() => {
        for (const timer of b.timers.slice(timerStart).filter(timer => timer.delay === 0 && !timer.cancelled && !timer.ran)) { timer.ran = true; timer.fn(); }
        return bulkReady;
      });
      await bulk; if (bulkError) throw bulkError;
      assert.equal(bulkReview.contacts_total, 0); assert.equal(bulkReview.counts.appointments, 1501);
      const bulkApplied = success(await tool("organizer_import_review_apply", applyArgs(bulkReview)));
      assert.equal(bulkApplied.counts.appointments, 1501); assert.equal(snapshots.length, checkpointsBeforeBulk);
      assert.equal(b.t.daten().zeiterfassung, clockRuntime);
      console.log("MCP IMPORT REVIEW PASS: staged choices/content/owner/CAS/snapshot/save/expiry/cancel/one-use " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
