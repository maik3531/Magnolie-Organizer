"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, ".."), clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
const ports = [path.join(root, "app/web")];
const linux = path.resolve(root, "../magnolie-organizer/web");
if (fs.existsSync(path.join(linux, "index.html"))) ports.unshift(linux);
const item = (id, source) => ({ id, uid: "shared@example.test", syncKalenderUid: source,
  titel: id, notiz: id + " original", datum: "2026-11-27", zeit: id === "a" ? "09:00" : "10:00",
  faellig: "2026-11-27", sync: true, syncQuellen: { [source]: { id: "/" + id, etag: '"observed"' } } });
const entries = () => [item("a", "calendar-a"), item("b", "calendar-b")];
const both = (data, field, edited = false) => {
  assert.deepEqual(Array.from(data[field], value => value.id), ["a", "b"]);
  assert.equal(data[field][0].notiz, "a original");
  assert.equal(data[field][1].notiz, edited ? "b edited during sync" : "b original");
};
const unchanged = (data, before, messages, conflict) => {
  for (const field of ["termine", "aufgaben", "kontakte", "geloescht"])
    assert.deepEqual(clone(data[field]), before[field], field + " changed after a rejected response");
  assert.ok(data.syncAbgleichBasis, "rejected response discarded its recovery baseline");
  assert.equal(messages.filter(message => ["sync_commit", "sync_bestaetigen"].includes(message.cmd)).length, 0);
  if (conflict) assert.match(data.syncStatus.letzterFehler, /Conflict/);
};
const addressbookOnly = { kalenderUid: "", kalenderUids: [], adressbuchUid: "synthetic-addressbook",
  automatisch: false, erfolgsmeldungen: false };
const unrelatedCalendars = () => ({
  termine: [...entries().map(value => ({ ...value, sync: false, syncKalenderUid: "",
    icsQuelleId: "offline-calendar", syncQuellen: {} })),
    { ...item("c", "unselected-calendar"), uid: "third@example.test" }],
  aufgaben: [{ ...item("task", "unselected-calendar"), uid: "task@example.test" }],
  syncMetadaten: { nextcloud: { kalender: { "offline-calendar": { etag: "keep-calendar-metadata" } } } }
});
const updateContact = (data, payload) => {
  payload.kontakte[0].notiz = "provider contact update";
  payload.syncMetadaten.nextcloud.adressbuecher["synthetic-addressbook"] = { etag: "new-contact-metadata" };
};
const verifyContactOnly = (data, before, messages) => {
  for (const field of ["termine", "aufgaben", "geloescht"])
    assert.deepEqual(clone(data[field]), before[field], "unselected " + field + " changed");
  assert.equal(data.kontakte[0].notiz, "provider contact update");
  assert.equal(data.syncMetadaten.nextcloud.adressbuecher["synthetic-addressbook"].etag, "new-contact-metadata");
  assert.deepEqual(clone(data.syncMetadaten.nextcloud.kalender), before.syncMetadaten.nextcloud.kalender);
  assert.equal(data.syncStatus.letzterFehler, "");
  assert.ok(!data.syncAbgleichBasis, "contact-only result was rejected");
  assert.ok(messages.some(message => ["sync_commit", "sync_bestaetigen"].includes(message.cmd)), "accepted contact result was not acknowledged");
};
const contactOnly = { field: "kontakte", settings: addressbookOnly, extra: unrelatedCalendars,
  initial: () => [{ id: "contact", uid: "contact@example.test", vorname: "Synthetic", notiz: "before", sync: true }] };
const cases = [
  { ...contactOnly, name: "contact-only sync retains unchanged unrelated ambiguous calendar entries",
    change: updateContact, verify: verifyContactOnly },
  { ...contactOnly, name: "contact-only sync retains late calendar edits, additions and deletion metadata",
    change: (data, payload, T) => {
      updateContact(data, payload); data.termine[1].notiz = "late unrelated edit";
      const deleted = data.termine.find(value => value.id === "c");
      T.merkeGeloescht("termine", deleted); data.termine = data.termine.filter(value => value !== deleted);
      const task = data.aufgaben[0]; T.merkeGeloescht("aufgaben", task); T.entferneAufgabe(task);
      data.termine.push(T.normalisiere({ termine: [{ ...item("new", ""), uid: "new@example.test", sync: false }] }).termine[0]);
    }, verify: verifyContactOnly },
  { ...contactOnly, name: "contact-only request selection is frozen before its save acknowledgement",
    beforeDispatch: data => { data.einstellungen.sync.kalenderUid = "late-calendar";
      data.einstellungen.sync.kalenderUids = ["late-calendar"]; },
    inspectRequest: request => { assert.equal(request.wahl.kalenderUid, ""); assert.deepEqual(request.wahl.kalenderUids, []); },
    change: updateContact, verify: verifyContactOnly },
  { ...contactOnly, name: "contact-only response may omit unrelated calendar collections",
    change: (data, payload) => {
      updateContact(data, payload); delete payload.termine; delete payload.aufgaben;
      delete payload.geloescht.termine; delete payload.geloescht.aufgaben;
    }, verify: verifyContactOnly },
  { ...contactOnly, name: "pending Windows transaction keeps its original source selection on retry",
    afterDispatch: async (T, w, messages, original) => {
      if (!original.transactionId) return original; // Linux uses fresh request IDs, not this journal path.
      const unexpected = { ...clone(original.daten), transactionId: original.transactionId, ok: true };
      unexpected.termine[0].notiz = "unrequested calendar change";
      w.App.syncFertig(unexpected); await tick();
      assert.match(T.daten().syncStatus.letzterFehler, /Conflict/);
      assert.equal(messages.filter(message => ["sync_commit", "sync_bestaetigen"].includes(message.cmd)).length, 0);
      T.daten().einstellungen.sync.kalenderUid = "retry-calendar";
      T.daten().einstellungen.sync.kalenderUids = ["retry-calendar"];
      T.starteSync(true);
      for (let i = 0; i < 100 && messages.filter(message => message.cmd === "sync").length < 2; i++) await tick();
      const attempts = messages.filter(message => message.cmd === "sync"), retry = attempts[1];
      assert.ok(retry, "pending transaction did not retry");
      assert.equal(retry.transactionId, original.transactionId);
      assert.deepEqual(retry.wahl, original.wahl, "retry changed the selection of a pending transaction");
      return retry;
    }, change: updateContact, verify: verifyContactOnly },
  ...["termine", "aufgaben", "deleted-termine", "deleted-aufgaben"].map(field => ({
    ...contactOnly, name: "contact-only response cannot modify unselected " + field,
    change: (data, payload) => {
      updateContact(data, payload);
      if (field.startsWith("deleted-")) payload.geloescht[field.slice(8)].push({ uid: "injected", zeit: 1, syncKalenderUid: "unselected-calendar" });
      else payload[field][0].notiz = "unexpected provider edit";
    }, verify: (data, before, messages) => unchanged(data, before, messages, true)
  })),
  { ...contactOnly, name: "a legacy baseline without a bound selection cannot bypass ambiguity checks",
    change: (data, payload) => { updateContact(data, payload); delete data.syncAbgleichBasis.wahl; },
    verify: (data, before, messages) => unchanged(data, before, messages, true) },
  { name: "unchanged events in different calendars", field: "termine", verify: data => both(data, "termine") },
  ...["termine", "aufgaben"].map(field => ({ name: field + " late edit stays in its calendar", field,
    change: data => { data[field][1].notiz = "b edited during sync"; }, verify: data => both(data, field, true) })),
  ...["termine", "aufgaben"].map(field => ({ name: field + " late deletion preserves the other calendar", field,
    change: (data, payload) => {
      const deleted = data[field].find(value => value.id === "b");
      data[field] = data[field].filter(value => value.id !== "b");
      data.geloescht[field].push({ uid: deleted.uid, zeit: 10, syncKalenderUid: "calendar-b",
        syncQuellen: { "calendar-b": { id: "/b", etag: '"observed"' } } });
      payload[field][1].syncQuellen["calendar-b"].etag = '"new-server-revision"';
    }, verify: data => {
      assert.deepEqual(Array.from(data[field], value => value.id), ["a"]);
      assert.equal(data[field][0].notiz, "a original");
      assert.equal(data.geloescht[field].length, 1);
      assert.equal(data.geloescht[field][0].syncKalenderUid, "calendar-b");
      assert.equal(data.geloescht[field][0].syncQuellen["calendar-b"].etag, '"observed"');
    } })),
  ...["icsQuelleId", "kalenderQuelle"].map(source => ({ name: source + " fallback keeps imported calendars", field: "termine",
    initial: () => entries().map((value, index) => ({ ...value, syncKalenderUid: "", syncQuellen: {},
      [source]: source === "kalenderQuelle" ? { id: "import-" + index } : "import-" + index })),
    verify: data => both(data, "termine") })),
  { name: "unqualified legacy UID is separate from another local record", field: "termine",
    initial: () => [ { ...item("a", ""), syncQuellen: {} }, item("b", "calendar-b") ],
    verify: data => both(data, "termine") },
  { name: "UID and local ID are separate namespaces", field: "termine",
    initial: () => [ { ...item("a", ""), uid: "b", syncQuellen: {} }, { ...item("b", ""), uid: "", syncQuellen: {} } ],
    verify: data => both(data, "termine") },
  { name: "same qualified UID still merges a changed remote local ID", field: "termine", initial: () => [item("a", "calendar-a")],
    change: (data, payload) => { data.termine[0].notiz = "local edit"; payload.termine[0].id = "remote-id"; },
    verify: data => { assert.equal(data.termine.length, 1); assert.equal(data.termine[0].notiz, "local edit"); } },
  ...[false, true].flatMap(imported => [false, true].map(deleted => ({
    name: (imported ? "imported" : "new") + " entry binds to its first provider after a late " + (deleted ? "deletion" : "edit"), field: "termine",
    initial: () => [{ ...item("a", ""), sync: false, syncQuellen: {}, ...(imported ? { icsQuelleId: "original-import" } : {}) }],
    change: (data, payload) => {
      payload.termine[0].sync = true; payload.termine[0].syncKalenderUid = "calendar-a";
      payload.termine[0].syncQuellen = { "calendar-a": { id: "/created", etag: '"created"' } };
      if (deleted) { data.termine = []; data.geloescht.termine.push({ uid: "shared@example.test", zeit: 10, syncKalenderUid: "", syncQuellen: {} }); }
      else data.termine[0].notiz = "local edit";
    }, verify: data => {
      if (deleted) {
        assert.equal(data.termine.length, 0, "late provider create resurrected a deleted entry");
        assert.equal(data.geloescht.termine.length, 1);
        assert.equal(data.geloescht.termine[0].syncKalenderUid, "calendar-a");
        assert.equal(data.geloescht.termine[0].syncQuellen["calendar-a"].etag, '"created"');
      } else {
        assert.equal(data.termine.length, 1); assert.equal(data.termine[0].notiz, "local edit");
        assert.equal(data.termine[0].syncKalenderUid, "calendar-a");
      }
    }
  }))),
  { name: "ambiguous provider identity holds before modifying data", field: "termine",
    initial: () => [item("a", "calendar-a"), item("b", "calendar-a")],
    change: data => { data.termine[1].notiz = "local edit"; },
    verify: (data, before, messages) => unchanged(data, before, messages, true) },
  { name: "contact UID merge retains its existing semantics", field: "kontakte",
    initial: () => [{ id: "contact", uid: "shared@example.test", vorname: "Synthetic", notiz: "original", sync: true }],
    change: (data, payload) => { data.kontakte[0].notiz = "local contact edit"; payload.kontakte[0].id = "remote-contact"; },
    verify: data => { assert.equal(data.kontakte.length, 1); assert.equal(data.kontakte[0].notiz, "local contact edit"); } },
  ...["request", "epoch"].map(kind => ({ name: "stale " + kind + " remains rejected", field: "termine",
    change: (data, payload) => {
      if (kind === "epoch") data.syncEpoch = "new-epoch";
      else if (payload.requestId) payload.requestId = "stale";
      else payload.transactionId = "stale";
    },
    verify: (data, before, messages) => unchanged(data, before, messages, false) }))
];

async function check(web, test) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text); messages.push(message);
    if (message.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: message.id, ok: true }));
  } } } };
  try {
    for (const script of ["i18n.js", "normative-timezones.js", "anwendung.js"])
      w.eval(fs.readFileSync(path.join(web, script), "utf8"));
    w.MagnolieI18n.setLocale("en"); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const initial = (test.initial || entries)();
    w.App.init({ neu: false, daten: { [test.field]: initial, ...(test.extra?.() || {}),
      einstellungen: { sync: test.settings || { kalenderUid: "calendar-a", kalenderUids: ["calendar-a", "calendar-b"],
        adressbuchUid: "synthetic-addressbook", automatisch: false, erfolgsmeldungen: false } } } });
    await tick();
    const T = w.OrganizerTest;
    assert.equal(T.daten()[test.field].length, initial.length, "fixture changed during initialization");
    T.starteSync(true);
    test.beforeDispatch?.(T.daten());
    for (let i = 0; i < 100 && !messages.some(message => message.cmd === "sync"); i++) await tick();
    let request = messages.find(message => message.cmd === "sync");
    assert.ok(request, "actual native synchronization request was not dispatched");
    if (test.afterDispatch) request = await test.afterDispatch(T, w, messages, request);
    test.inspectRequest?.(request);
    const payload = { ...clone(request.daten), requestId: request.requestId,
      transactionId: request.transactionId || "f".repeat(64), ok: true };
    test.change?.(T.daten(), payload, T);
    const before = clone(T.daten());
    w.App.syncFertig(payload);
    await tick();
    test.verify(T.daten(), before, messages);
  } finally { w.close(); }
}

(async () => {
  let failed = 0;
  for (const web of ports) for (const test of cases) {
    const name = path.relative(path.dirname(root), web) + ": " + test.name;
    try { await check(web, test); console.log("PASS " + name); }
    catch (error) { failed++; console.error("FAIL " + name + "\n" + error.stack); }
  }
  console.log(`Calendar synchronization identity: ${ports.length * cases.length - failed}/${ports.length * cases.length} cases passed`);
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
