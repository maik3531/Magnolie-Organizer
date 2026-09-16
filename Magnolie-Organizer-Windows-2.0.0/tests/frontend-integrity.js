"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true
  });
  const w = dom.window, d = w.document, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  d.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest;
  const clean = value => JSON.parse(JSON.stringify(value));
  const reset = () => w.App.init({ daten: {}, neu: false, regional: { language: "en" } });
  const input = (node, value) => { node.value = value; node.dispatchEvent(new w.Event("input", { bubbles: true })); };
  try {
    reset();
    const contact = { uid: "person-a", vorname: "", nachname: "Van Dame", anzeigename: "Dr Van Dame",
      weitereNamen: "", namensPraefix: "Dr", namensSuffix: "Jr", vcardN: "Van Dame;;;Dr;Jr",
      vcardRoundtrip: ["N:Van Dame;;;Dr;Jr", "TITLE:Nurse", "URL:https://example.test"],
      vcardParameter: { N: { LANGUAGE: "en" } }, email: "family@example.test", jubilaeum: "--02-29", geburtstag: "--06-07" };
    T.mergeKontakte([contact]);
    const saved = T.normalisiere(clean(T.daten())).kontakte[0];
    for (const key of ["vorname", "nachname", "anzeigename", "weitereNamen", "namensPraefix", "namensSuffix", "vcardN", "vcardRoundtrip", "vcardParameter", "jubilaeum"])
      assert.deepEqual(clean(saved[key]), contact[key], key);
    T.mergeKontakte([{ uid: "person-b", vorname: "Bob", nachname: "Other", email: "family@example.test" }]);
    assert.equal(T.daten().kontakte.length, 2, "F08: conflicting UIDs merged through email");
    T.mergeKontakte([{ uid: "person-a", anzeigename: "Van Dame", vcardRoundtrip: ["FN:Van Dame", "X-SAFE:keep"] }]);
    assert.equal(T.daten().kontakte[0].vorname, "", "F55: missing name invented");
    assert.ok(T.daten().kontakte[0].vcardRoundtrip.includes("X-SAFE:keep"));
    T.mergeKontakte([{ uid: "person-a", vorname: "", nachname: "", anzeigename: "Van Dame", geaendert: Date.now() + 1000,
      vcardRoundtrip: ["FN:Van Dame"] }]);
    assert.equal(T.daten().kontakte[0].nachname, "Van Dame", "FN-only update clears structured family name");
    T.daten().kontakte[0].baumKontakt = { freigabeId: "local:contact", version: 1, quelle: "local", geaendert: 1 };
    assert.equal(T.kontaktBaumInhalt(T.daten().kontakte[0]).kontakt.jubilaeum, "--02-29",
      "internal modern projection must preserve the anniversary");
    assert.throws(() => T.kontaktBaumInhalt(T.daten().kontakte[0], 1), /Not sent/,
      "extended contact must not be silently downgraded");
    w.App.baumStand({ an: true, moeglich: true, laeuft: true, kennung: "local", eingang: [], partner: [
      { kennung: "old-contact-peer", bestaetigt: true, vertraut: true },
      { kennung: "new-contact-peer", bestaetigt: true, vertraut: true,
        kontaktFaehigkeiten: { kontakt_sync: [1, 2], kontakt_import: [1, 2] } }
    ] });
    const legacyFields = ["vorname", "nachname", "firma", "notiz", "geburtstag", "telefone", "emailEintraege", "anschriften"];
    const wireContacts = since => messages.slice(since).filter(m => m.cmd === "baum_teilen" && m.art === "kontakt_sync");
    let beforeSend = messages.length;
    assert.equal(await T.synchronisiereKontakteMit("old-contact-peer"), false);
    assert.deepEqual(wireContacts(beforeSend), [], "v1 preflight must reject the entire lossy snapshot before sending contacts");
    beforeSend = messages.length;
    assert.equal(await T.synchronisiereKontakteMit("new-contact-peer"), true);
    const modernWire = wireContacts(beforeSend);
    assert.equal(modernWire.length, T.daten().kontakte.length);
    for (const m of modernWire) {
      assert.equal(m.kennung, "new-contact-peer");
      assert.equal(m.inhalt.fassung, 2);
      assert.deepEqual(Object.keys(m.inhalt.kontakt).sort(), [...legacyFields, "anzeigename", "jubilaeum", "vcardName"].sort());
    }
    assert.equal(modernWire[0].inhalt.kontakt.jubilaeum, "--02-29");
    T.daten().kontakte = T.normalisiere({ kontakte: [{ id: "legacy-contact", vorname: "Anna", nachname: "Example" }] }).kontakte;
    beforeSend = messages.length;
    assert.equal(await T.synchronisiereKontakteMit("old-contact-peer"), true);
    const legacyWire = wireContacts(beforeSend);
    assert.equal(legacyWire.length, 1);
    assert.equal(legacyWire[0].kennung, "old-contact-peer");
    assert.equal(legacyWire[0].inhalt.fassung, 1);
    assert.deepEqual(Object.keys(legacyWire[0].inhalt.kontakt).sort(), legacyFields.sort(),
      "actual v1 send must have exactly the shipped schema");

    reset();
    const task = { uid: "new-task", titel: "Start and due", startDatum: "2026-09-01", startZeit: "09:00",
      faellig: "2026-09-07", faelligZeit: "17:00", sync: true,
      syncKalenderUid: "calendar-two", syncQuellen: { "dav:calendar-two": { uid: "new-task", href: "task.ics" } } };
    const normalizedTask = T.normalisiere({ aufgaben: [task] }).aufgaben[0];
    for (const key of ["startDatum", "startZeit", "faelligZeit", "sync", "syncQuellen", "syncKalenderUid"])
      assert.deepEqual(clean(normalizedTask[key]), task[key], "F10/F15: " + key);
    w.App.importErgebnis({ aufgaben: [task] });
    assert.equal(T.daten().aufgaben[0].faelligZeit, "17:00");
    assert.equal(T.daten().aufgaben[0].startDatum, "2026-09-01");
    for (const key of ["sync", "syncQuellen", "syncKalenderUid"])
      assert.deepEqual(clean(T.daten().aufgaben[0][key]), task[key], "native import lost " + key);
    const event = { uid: "same-event", datum: "2026-09-07", zeit: "10:00", titel: "Meeting" };
    T.mergeTermine([{ ...event, icsQuelleId: "a", notiz: "a" }, { ...event, icsQuelleId: "b", notiz: "b" }]);
    assert.equal(T.normalisiere(clean(T.daten())).termine.length, 2, "F09: sources collapse on reload");
    reset();
    const largeImport = Array.from({ length: 1200 }, (_, i) => ({ ...event, uid: "batch-" + i }));
    const importing = w.App.importErgebnis({ termine: largeImport });
    assert.equal(T.daten().termine.length, 0, "F51: partial import published before preparation finished");
    T.mergeTermine([{ ...event, uid: "during-import", notiz: "local change during yield" }]);
    await importing;
    assert.equal(T.daten().termine.length, 1201);
    assert.equal(T.daten().termine.find(t => t.uid === "during-import").notiz, "local change during yield");
    await w.App.importErgebnis({ termine: largeImport });
    assert.equal(T.daten().termine.length, 1201, "batch reimport not idempotent");
    const obsoleteImport = w.App.importErgebnis({ termine: largeImport });
    reset();
    await obsoleteImport;
    assert.equal(T.daten().termine.length, 0, "stale import applied after replacing data");
    T.wechsel("notizen");
    const reportedImport = largeImport.map((t, i) => i ? t : { ...t, icsKomplex: true,
      icsRoundtrip: ["DTSTART:20260907T100000Z", "RRULE:FREQ=DAILY;COUNT=3"] });
    const pendingReport = w.App.importErgebnis({ termine: reportedImport, wiederholend: 1, bericht: "Native report." });
    assert.equal(T.daten().termine.length, 0);
    await pendingReport;
    assert.equal(T.daten().termine.length, 1200);
    assert.ok(d.querySelector("#zettel").textContent.includes("Imported: 1200 appointments"));
    assert.ok(d.querySelector("#zettel").textContent.includes("Some recurrence rules cannot be expanded. Their original calendar data was preserved."),
      "Native unresolved-rule count must not be reduced by unrelated supported complex rules");
    assert.ok(d.querySelector("#zettel").textContent.includes("Native report."));

    reset();
    const imported = { kontakte: [contact], geburtstage: [{ kontaktUid: contact.uid, name: "Dr Van Dame", datum: "--06-07" }],
      jahrestage: [{ kontaktUid: contact.uid, name: "Dr Van Dame", datum: "--02-29", typ: "anniversary" }] };
    w.App.importErgebnis(clean(imported)); w.App.importErgebnis(clean(imported));
    assert.equal(T.daten().jahrestage.length, 2, "F30: contact event copies imported twice");
    assert.ok(T.daten().jahrestage.every(j => j.kontaktId === T.daten().kontakte[0].id));

    reset();
    const notes = (id, page, count) => ({ id, page, type: "notes", items: Array.from({ length: count }, (_, i) =>
      ({ id: id + i, text: "Body " + i })) });
    const legacy = T.normalisiereCustomOrganizer({ modules: [notes("a", "left", 300), notes("b", "left", 300)] });
    assert.equal(legacy.modules.flatMap(m => m.items).length, 600, "F21: populated pages truncated");
    const longText = "x".repeat(60000), largeHtml = "<span>x</span>".repeat(10001);
    const longPages = T.normalisiereCustomOrganizer({ modules: [{ type: "notes", items: [
      { id: "long", text: longText }, { id: "large-dom", html: largeHtml, text: "original" }] }] });
    assert.equal(longPages.modules[0].items[0].text, longText);
    assert.equal(longPages.modules[0].items[1].html, largeHtml, "saved oversized HTML replaced by partial sanitization");
    T.daten().einstellungen.allgemein.customTab = { enabled: true, name: "Review" };
    T.daten().customOrganizer = T.normalisiereCustomOrganizer({ modules: [notes("left", "left", 2), notes("right", "right", 1),
      { id: "events", type: "appointments", page: "left", items: [{ id: "e", title: "Meeting", textItemId: "left1", date: "2026-09-07",
        wiederholung: { art: "monthly", bis: "2026-12-31", ordinal: 2, wochentag: "MO" } }] },
      { id: "tasks", type: "tasks", page: "right", items: [] }] });
    T.uebernehmeSetupAbsichten({ setupAuswahl: { customOrganizerChanged: true, customOrganizer: { modules: [
      { type: "appointments", page: "left" }, { type: "tasks", page: "left" }, { type: "notes", page: "right" }] } } });
    assert.equal(T.daten().customOrganizer.modules.length, 4);
    assert.ok(T.daten().customOrganizer.modules.some(m => m.items.some(i => i.id === "left1")));
    assert.equal(T.daten().customOrganizer.modules.find(m => m.type === "appointments").items[0].textItemId, "left1");
    for (const page of ["left", "right"]) assert.ok(T.daten().customOrganizer.modules.filter(m => m.page === page).length <= 2);
    T.wechsel("custom");
    T.suchTrefferFuer("custom", ["body 1"], 10)[0].oeffnen();
    assert.equal(d.querySelector(".custom-text-editor[data-custom-text-id='left1']")?.dataset.customTextId, "left1");
    assert.equal(d.querySelector("#custom-designer-schleier"), null);
    T.suchTrefferFuer("custom", ["meeting"], 10)[0].oeffnen();
    d.querySelector(".custom-eintrag-aktionen .haupt").click();
    assert.deepEqual(clean(T.daten().customOrganizer.modules.find(m => m.type === "appointments").items[0].wiederholung),
      { art: "monthly", bis: "2026-12-31", ordinal: 2, wochentag: "MO" });

    reset();
    for (const format of [2, 3]) {
      T.daten().notizen = [{ id: "note", titel: "Note " + format, text: "safe", html: "<p>safe</p>", angelegt: 1,
        symbol: "notiz", anhaenge: [], notizbuchId: T.daten().notizbuecher[0].id }];
      let records = await T.personalSyncSnapshot(["notes"], format, "peer");
      assert.deepEqual(clean(records.find(r => r.kind === "note").value.attachments), []);
      T.daten().notizen[0].anhaenge.push({ id: "attachment", name: "a.png", daten: "data:image/png;base64,AQID" });
      records = await T.personalSyncSnapshot(["notes"], format, "peer");
      const note = records.find(r => r.kind === "note");
      assert.equal(note.value.attachments.length, 1);
      assert.equal(await T.personalSyncHash(note.value), note.hash);
      const counter = T.daten().personalSync.counter;
      await T.personalSyncAnwenden(records, { [note.value.attachments[0].sha256]: "data:image/png;base64,AQID" }, format, "peer", ["notes"]);
      assert.equal(T.daten().personalSync.counter, counter, "F17: unchanged format projection increments revision");
    }
    T.daten().aufgaben = [normalizedTask];
    const tasks = await T.personalSyncSnapshot(["tasks"], 3, "peer");
    const counter = T.daten().personalSync.counter;
    await T.personalSyncAnwenden(tasks, {}, 3, "peer", ["tasks"]);
    assert.equal(T.daten().personalSync.counter, counter);
    const grants = { grants: { personal_tasks_sync: true } };
    w.App.telefonStand({ peers: [{ device_id: "peer", own_device: true, remote_own_device: true,
      local_grants: grants, grants, state: "offline" }] });
    w.App.personalSync({ kind: "personal_sync.batch", device_id: "peer", pending_message_id: "message", commit_token: "commit",
      body: { format: 3, run_id: "run", reply: false, requested_modules: ["tasks"], records: clean(tasks), attachment_data: {} } });
    const acknowledged = new Set();
    for (let attempt = 0; attempt < 100 && !messages.some(m => m.cmd === "personal_sync_lauf_senden"); attempt++) {
      for (const message of messages.slice()) if (message.cmd === "speichern" && !acknowledged.has(message.id)) {
        acknowledged.add(message.id); w.App.gespeichert({ id: message.id, ok: true });
      }
      await new Promise(resolve => setTimeout(resolve, 2));
    }
    const reply = messages.find(m => m.cmd === "personal_sync_lauf_senden");
    assert.ok(reply, "F17: reply not sent after successful persistence");
    assert.equal(reply.request.format, 3);
    assert.ok(reply.batches.every(b => b.format === 3 && b.records_hash.length === 64));
    assert.equal(reply.batches.flatMap(b => b.records).find(r => r.kind === "task").value.uid, normalizedTask.uid);
    assert.equal(reply.report.format, 3);

    reset();
    T.daten().gesundheit.vitalwerte = w.JSON.parse(JSON.stringify(Array.from({ length: 1000 }, (_, i) => ({ id: "v" + i, datum: "2026-09-07", seite: i, temperatur: "36.5" }))));
    T.zustand().gesundheit.ansicht = "vital";
    let sorts = 0;
    const sort = w.Array.prototype.sort;
    w.Array.prototype.sort = function (...args) { sorts++; return sort.apply(this, args); };
    assert.equal(T.suchTrefferFuer("gesundheit", ["not-present"], 100).length, 0);
    w.Array.prototype.sort = sort;
    assert.equal(sorts, 0, "F49: unsuccessful health search sorts history");
    T.daten().notizen = [{ id: "body", titel: "Old", text: "old", html: "<p>old</p>", anhaenge: [], notizbuchId: T.daten().notizbuecher[0].id }];
    T.zustand().notizen.auswahlId = "body";
    T.wechsel("notizen");
    const body = d.querySelector("#notiz-text");
    Object.defineProperty(body, "innerHTML", { configurable: true, get() { throw Error("title reparsed body"); } });
    input(d.querySelector("#notiz-titel"), "New title");
    assert.equal(T.daten().notizen[0].titel, "New title");
    delete body.innerHTML;
    body.innerHTML = "<p>first</p>"; body.dispatchEvent(new w.Event("input"));
    body.innerHTML = "<p>latest <b>safe</b><script>bad()</script></p>"; body.dispatchEvent(new w.Event("input"));
    assert.equal(T.daten().notizen[0].html, "<p>old</p>", "body work not coalesced");
    T.speichereJetzt();
    assert.equal(T.daten().notizen[0].html, "<p>latest <b>safe</b></p>");
    assert.equal(T.daten().notizen[0].text, "latest safe");
    console.log("FRONTEND INTEGRITY PASSED: " + web);
  } finally { dom.window.close(); }
}

const windows = path.resolve(__dirname, "../app/web");
const linux = path.resolve(__dirname, "../../magnolie-organizer-2.0.0/web");
(async () => {
  for (const web of process.env.MAGNOLIE_WEB ? [process.env.MAGNOLIE_WEB] : [linux, windows].filter(p => fs.existsSync(p))) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
