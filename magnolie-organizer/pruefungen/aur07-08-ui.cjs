"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict"), Module = require("node:module");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "../.."), work = process.argv[2], dotnet = process.argv[3];
const harnessPath = path.join(root, "magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath;
harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] +
  "\nmodule.exports = {boot, roots};", harnessPath);
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));
let checks = 0;

function native(platform, file, message) {
  const args = platform === "windows" ? [path.join(work, "bin/Debug/net8.0/Probe.dll"), file]
    : [path.join(__dirname, "aur07-08-verify.py"), file];
  const result = spawnSync(platform === "windows" ? dotnet : "python3", args,
    { input: JSON.stringify(message), encoding: "utf8", timeout: 30000 });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout);
}

function button(b, label, parent = b.w.document) {
  const found = [...parent.querySelectorAll("button")].find(node => node.textContent.trim() === label);
  assert.ok(found, "Missing button: " + label);
  return found;
}

async function imports(web) {
  const platform = web.includes("Windows") ? "windows" : "linux";
  const b = await harness.exports.boot(web, { kontakte: [
    { id: "existing", uid: "aur07-rich", vorname: "Ada", nachname: "Example", notiz: "Local history",
      importHerkunfte: ["synthetic-history"], importBindungen: ["urn:magnolie:import:android:" + "a".repeat(64)], geaendert: 1 },
    { id: "unrelated", uid: "unrelated", vorname: "Untouched", notiz: "Do not replace" }
  ], notizen: [{ id: "note", titel: "Keep", text: "Full snapshot", html: "Full snapshot" }] });
  try {
    const sourceHashes = new Map(["contacts.ldif", "contacts.ldi", "unexpected.txt", "contacts.zip", "invalid.ldif"]
      .map(name => [name, fs.readFileSync(path.join(work, name)).toString("base64")]));
    b.w.document.querySelector("#knopf-einstellungen").click();
    b.w.document.querySelector("#einst-tab-import").click();
    let cursor = b.messages.length, persisted, reports = [], snapshots = 0, imports = 0;
    const savedFile = path.join(work, platform + "-saved.json");
    const drain = (choice, snapshotOk = true) => {
      while (cursor < b.messages.length) {
        const message = b.messages[cursor++];
        if (message.cmd === "speichern") {
          persisted = native(platform, savedFile, { cmd: "persist", text: message.text });
          assert.equal(persisted.notizen[0].text, "Full snapshot");
          b.w.App.gespeichert({ id: message.id, ok: true });
        } else if (message.cmd === "mutations_snapshot") {
          assert.equal(message.reason, "pre-contact-import");
          assert.ok(persisted, "Snapshot requested before save completed");
          snapshots++;
          b.w.App.mutationsSnapshot({ token: message.token, ok: snapshotOk });
        } else if (message.cmd === "import") {
          assert.equal(message.art, "ldif", "Visible LDIF identity was replaced with Claws");
          imports++;
          const reply = native(platform, choice === "cancel" ? choice : path.join(work, choice), message);
          assert.ok(reply.dialog, "Native chooser did not open");
          assert.ok(reply.dialog.Disposed, "Native dialog was not disposed");
          assert.doesNotMatch(reply.dialog.Title, /Claws/i);
          const filter = reply.dialog.Filter || JSON.stringify(reply.dialog.Filters);
          for (const suffix of ["*.ldif", "*.ldi", "*.zip"]) assert.ok(filter.includes(suffix), suffix);
          assert.ok(filter.includes(platform === "windows" ? "*.*" : '"*"'));
          assert.doesNotMatch(filter, /Claws|\*\.xml/i);
          assert.equal(reply.replies.length, 1);
          assert.equal(reply.replies[0].callback, "App.importErgebnis");
          assert.equal(reply.replies[0].payload.art, "ldif");
          b.w.App.importErgebnis(reply.replies[0].payload);
          reports.push(b.w.document.querySelector("#zettel").textContent);
        }
      }
    };
    // Start through the actual settings button, with a dirty full snapshot.
    b.t.daten().notizen[0].text = "Full snapshot";
    b.t.daten().kontakte[0].notiz += " (edited)";
    const before = plain(b.t.daten());
    button(b, "LDIF address book (.ldif) \u2026").click();
    assert.ok(!b.messages.slice(cursor).some(m => m.cmd === "import"), "Import bypassed durable save/snapshot");
    drain("contacts.ldif");
    assert.equal(imports, 1); assert.equal(snapshots, 1);
    const data = b.t.daten(), rich = data.kontakte.find(k => k.uid === "aur07-rich");
    assert.equal(data.kontakte.length, 3);
    assert.equal(rich.id, "existing");
    assert.ok(rich.notiz.includes("Local history (edited)") && rich.notiz.includes("Imported note"));
    assert.deepEqual(plain(rich.importHerkunfte), ["synthetic-history"]);
    assert.ok(rich.importBindungen.includes("urn:magnolie:import:android:" + "a".repeat(64)));
    assert.equal(rich.geburtstag, "--02-29"); assert.equal(rich.jubilaeum, "2001-06-07");
    assert.equal(rich.geburtstagJahrUnbekannt, true);
    assert.equal(rich.emails.length, 2); assert.equal(rich.telefone.length, 2);
    assert.equal(rich.anschriften.length, 2);
    assert.equal(rich.anschriften[0].strasse, "Test Road 1");
    assert.equal(rich.foto, "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZ8AAAAASUVORK5CYII=");
    for (const raw of ["N:Example;Ada;Middle;Dr.;Jr.", "TITLE:Engineer", "X-AUR07:Preserve original"])
      assert.ok(rich.vcardRoundtrip.includes(raw), raw);
    assert.equal(data.jahrestage.filter(j => j.kontaktId === rich.id).length, 2);
    assert.deepEqual(plain(data.kontakte.find(k => k.id === "unrelated")), before.kontakte[1]);
    assert.match(reports.at(-1), /Imported:|existing entr/);
    b.t.speichereJetzt(); drain("cancel");
    assert.deepEqual(persisted, plain(data), "Safe save did not contain the full merged document");
    const first = plain(data);
    button(b, "LDIF address book (.ldif) \u2026").click(); drain("contacts.ldif");
    assert.deepEqual(plain(b.t.daten()), first, "First repeated plain-LDIF import changed the contract");
    // Reload the full safe-save document through the real modern normalizer.
    b.w.App.init({ daten: persisted, neu: false, regional: { language: "en", timeZone: "UTC" } });
    b.w.document.querySelector("#knopf-einstellungen").click();
    b.w.document.querySelector("#einst-tab-import").click();
    b.t.speichereJetzt(); drain("cancel");
    const after = plain(b.t.daten());
    for (const choice of ["contacts.ldif", "contacts.ldi", "unexpected.txt", "contacts.zip", "cancel", "cancel"]) {
      button(b, "LDIF address book (.ldif) \u2026").click(); drain(choice);
      b.t.speichereJetzt(); drain("cancel");
      assert.deepEqual(plain(b.t.daten()), after, "Repeated import/cancel mutated data: " + choice);
      assert.deepEqual(persisted, after);
    }
    const count = imports;
    button(b, "LDIF address book (.ldif) \u2026").click(); drain("contacts.ldif", false);
    assert.equal(imports, count, "Failed snapshot still opened import");
    assert.deepEqual(plain(b.t.daten()), after);
    button(b, "LDIF address book (.ldif) \u2026").click(); drain("invalid.ldif");
    assert.deepEqual(plain(b.t.daten()), after, "Invalid LDIF mutated data");
    button(b, "LDIF address book (.ldif) \u2026").click(); drain("missing.ldif");
    assert.deepEqual(plain(b.t.daten()), after, "Native read failure mutated data");
    assert.match(reports.at(-1), /Import failed:/);
    b.t.daten().kontakte[0].notiz += " unsaved edit";
    const start = b.messages.length;
    button(b, "LDIF address book (.ldif) \u2026").click();
    const failedSave = b.messages.slice(start).find(m => m.cmd === "speichern");
    assert.ok(failedSave, "Dirty import did not wait for a save");
    b.w.App.gespeichert({ id: failedSave.id, ok: false });
    assert.ok(!b.messages.slice(start).some(m => ["import", "mutations_snapshot"].includes(m.cmd)),
      "Failed prerequisite save reached import/snapshot");
    for (const [name, bytes] of sourceHashes) {
      assert.equal(fs.readFileSync(path.join(work, name)).toString("base64"), bytes);
      assert.equal(fs.statSync(path.join(work, name)).mode & 0o777, 0o400);
    }
    checks++;
    console.log(platform + ": LDIF actual button, save/snapshot gate, native chooser adapter, parser, merge, repeat/cancel, full atomic save passed");
  } finally { b.close(); }
}

function events() {
  const count = (Date.parse("2026-09-15") - Date.parse("1998-01-01")) / 86400000 + 1;
  const event = (id, datum, raw, title = id) => ({ id, uid: id, icsSerienUid: "daily", icsQuelleId: "test",
    datum, titel: title, icsRoundtrip: raw, sync: true });
  return [
    { id: "weekly", uid: "weekly", titel: "Weekly from August", datum: "2026-08-31",
      wiederholung: { art: "weekly", intervall: 1 }, sync: true },
    event("daily", "1998-01-01", ["UID:daily", "DTSTART;VALUE=DATE:19980101", "DTEND;VALUE=DATE:19980102",
      "RRULE:FREQ=DAILY;COUNT=" + count, "EXDATE;VALUE=DATE:20260903"], "Since 1998 <safe>"),
    event("moved", "2026-09-20", ["UID:daily", "RECURRENCE-ID;VALUE=DATE:20260904",
      "DTSTART;VALUE=DATE:20260920", "DTEND;VALUE=DATE:20260921"], "Moved beyond COUNT"),
    event("cancelled", "2026-09-05", ["UID:daily", "RECURRENCE-ID;VALUE=DATE:20260905",
      "DTSTART;VALUE=DATE:20260905", "STATUS:CANCELLED"], "Cancelled"),
    event("moved-out", "2026-10-01", ["UID:daily", "RECURRENCE-ID;VALUE=DATE:20260906",
      "DTSTART;VALUE=DATE:20261001", "DTEND;VALUE=DATE:20261002"], "Moved outside month"),
    { id: "multi", uid: "multi", titel: "Month overlap", datum: "2026-08-30", endDatum: "2026-09-02" },
    { id: "outside", uid: "outside", titel: "Outside", datum: "2026-10-11" }
  ];
}

function workerQueue(b) {
  const queue = [], sources = new Map(); let sequence = 0, worker;
  b.w.Blob = class { constructor(parts) { this.source = parts.join(""); } };
  b.w.URL.createObjectURL = blob => { const id = "blob:test-" + ++sequence; sources.set(id, blob.source); return id; };
  b.w.URL.revokeObjectURL = () => {};
  b.w.Worker = class {
    constructor(url) {
      worker = this;
      this.context = vm.createContext({ performance, Intl, console, setTimeout: fn => queue.push(fn),
        self: { postMessage: data => this.onmessage({ data }) } });
      vm.runInContext(sources.get(url), this.context);
    }
    postMessage(data) { queue.push(() => { if (!this.stopped) this.context.self.onmessage({ data: plain(data) }); }); }
    terminate() { this.stopped = true; }
  };
  return { queue, fail: () => worker.onerror(), flush() {
    let turns = 0;
    while (queue.length) { assert.ok(++turns < 4096, "Unbounded worker loop"); queue.shift()(); }
  } };
}

async function printing(web, mode) {
  const b = await harness.exports.boot(web, { termine: events(), einstellungen: { allgemein: { tray: { aktiv: false } } } });
  try {
    const T = b.t, w = b.w;
    T.zustand().kalender.jahr = 2026; T.zustand().kalender.monat = 8;
    // The worker executes the actual generated worker code, manually, one queued job at a time.
    const workers = mode === "sync" ? null : workerQueue(b);
    const original = plain(T.daten());
    await T.wechsel("kalender");
    w.document.querySelector("#knopf-drucken").click();
    const dialog = w.document.querySelector("#druck-schleier"); assert.ok(dialog);
    const print = button(b, "Print now", dialog), none = button(b, "None", dialog);
    if (workers) {
      assert.ok(print.disabled, "Pending expansion was printable");
      assert.ok(button(b, "Delete selection", dialog).disabled);
      assert.equal(dialog.querySelector(".druck-vorschau").getAttribute("aria-busy"), "true");
      const sent = b.messages.length; print.click(); assert.equal(b.messages.length, sent);
      none.click();
      if (mode === "worker-error") {
        workers.fail(); workers.flush();
        assert.ok(print.disabled);
        assert.match(dialog.textContent, /Some recurrence rules cannot be expanded/);
        assert.deepEqual(plain(T.daten()), original);
        checks++; return;
      }
      if (mode === "close-pending") {
        button(b, "Cancel", dialog).click(); workers.flush();
        assert.ok(!w.document.querySelector("#druck-schleier"));
        assert.deepEqual(plain(T.daten()), original); checks++; return;
      }
      // The open preview retains its own month while pending work completes.
      T.zustand().kalender.monat = 9;
      workers.flush();
      assert.ok(!print.disabled);
      assert.ok([...dialog.querySelectorAll(".druck-auswahl input")].every(input => !input.checked), "None was lost on worker completion");
      T.zustand().kalender.monat = 8;
    }
    const stoff = T.druckStoff("kalender");
    assert.ok(!stoff.icsIncomplete);
    assert.equal(stoff.liste.filter(e => e._druckQuelleId === "weekly").length, 4);
    const daily = stoff.liste.filter(e => e._druckQuelleId === "daily");
    assert.equal(daily.length, 11); // Sep 1..15, excluding EXDATE, moved, cancelled and moved-out.
    assert.deepEqual(plain(daily.map(e => e.datum)), [1,2,7,8,9,10,11,12,13,14,15].map(d => "2026-09-" + String(d).padStart(2,"0")));
    assert.equal(stoff.liste.filter(e => e._druckQuelleId === "multi").length, 1);
    assert.equal(stoff.liste.filter(e => e._druckQuelleId === "moved")[0].datum, "2026-09-20");
    assert.ok(!stoff.liste.some(e => ["cancelled", "outside", "moved-out"].includes(e._druckQuelleId)));
    assert.equal(new Set(stoff.liste.map(e => e.id)).size, stoff.liste.length);
    const projection = new Set();
    // Independent per-day display queries must agree with the shared-window print projection.
    for (let d = 1; d <= 30; d++) T.termineAm("2026-09-" + String(d).padStart(2, "0"), true);
    workers?.flush();
    for (let d = 1; d <= 30; d++) for (const e of T.termineAm("2026-09-" + String(d).padStart(2, "0"), true))
      projection.add(JSON.stringify([e.id,e.icsOccurrence ?? null,e.datum,e.zeit || "",e.endDatum || "",e.endZeit || ""]));
    assert.deepEqual(new Set(stoff.liste.map(e => e.id)), projection);
    none.click(); const before = b.messages.length; print.click();
    assert.equal(b.messages.length, before, "Print None reached the bridge");
    assert.deepEqual(plain(T.daten()), original);
    button(b, "All", dialog).click(); print.click();
    const printed = b.messages.filter(m => m.cmd === "drucken").at(-1);
    assert.ok(printed); assert.ok(printed.html.includes("&lt;safe&gt;"));
    assert.equal((printed.html.match(/class="karte"/g) || []).length, stoff.liste.length);
    assert.deepEqual(plain(T.daten()), original, "Print mutated source series");
    const year = T.planerKalenderModell(2026);
    assert.ok(!T.planerDruckSeite(year).includes("Since 1998"), "Normal planner scope widened");
    let month = T.planerMonatsModell(2026, 8);
    workers?.flush(); month = T.planerMonatsModell(2026, 8);
    assert.ok(!month.icsIncomplete);
    assert.equal(month.wochen.flatMap(row => row.tage).flatMap(day => day.eintraege)
      .filter(e => e.art === "termin" && e.text.includes("Since 1998")).length, 11);
    w.document.querySelector("#knopf-drucken").click();
    const single = w.document.querySelector("#druck-schleier");
    button(b, "None", single).click();
    [...single.querySelectorAll(".druck-zeile")].find(row => row.textContent.includes("Since 1998"))
      .querySelector("input").click();
    button(b, "Print now", single).click();
    assert.equal((b.messages.filter(m => m.cmd === "drucken").at(-1).html.match(/class="karte"/g) || []).length, 1,
      "Selecting one occurrence printed the entire series");
    assert.deepEqual(plain(T.daten()), original);
    // Source deletion is independent: two printed instances delete one original once.
    w.document.querySelector("#knopf-drucken").click();
    const deletion = w.document.querySelector("#druck-schleier");
    button(b, "None", deletion).click();
    const rows = [...deletion.querySelectorAll(".druck-zeile")].filter(row => row.textContent.includes("Since 1998"));
    rows[0].querySelector("input").click(); rows[1].querySelector("input").click();
    button(b, "Delete selection", deletion).click();
    assert.match(w.document.querySelector("#dialog-text").textContent, /1 selected entry/);
    w.document.querySelector("#dialog-ja").click(); await tick();
    assert.deepEqual(plain(T.daten().termine.map(e => e.id)), original.termine.filter(e => e.id !== "daily").map(e => e.id));
    assert.equal(T.daten().geloescht.termine.filter(e => e.uid === "daily").length, 1);
    assert.equal(T.daten().papierkorb.filter(e => e.art === "appointment").length, 1);
    assert.deepEqual(plain(T.daten().papierkorb.find(e => e.art === "appointment").eintrag),
      original.termine.find(e => e.id === "daily"), "Wastebasket stored a projected occurrence instead of the original");
    assert.ok(![...deletion.querySelectorAll(".druck-zeile")].some(row => row.textContent.includes("Since 1998")));
    checks++;
  } finally { b.close(); }
}

async function unknownRule(web) {
  const b = await harness.exports.boot(web, { termine: [{ id:"bad", uid:"bad", titel:"Unexpandable", datum:"1998-01-01",
    icsRoundtrip:["UID:bad", "DTSTART;VALUE=DATE:19980101", "RRULE:FREQ=DAILY;BYUNKNOWN=1"] }, ...events()] });
  try {
    b.t.zustand().kalender.jahr=2026; b.t.zustand().kalender.monat=8;
    const before=plain(b.t.daten());
    b.t.oeffneDruckvorschau(null,"kalender");
    assert.ok(button(b,"Print now",b.w.document.querySelector("#druck-schleier")).disabled);
    assert.ok(b.t.druckStoff("kalender").icsIncomplete);
    assert.deepEqual(plain(b.t.daten()),before); checks++;
  } finally { b.close(); }
}

(async () => {
  for (const web of harness.exports.roots) {
    await imports(web);
    for (const mode of ["sync", "worker", "worker-error", "close-pending"]) await printing(web, mode);
    await unknownRule(web);
    console.log(web + ": selection recurrence, COUNT, exceptions, pending/failure, None and source deletion passed");
  }
  console.log("AUR07/AUR08: " + checks + " scenario suites passed, sequential, two-CPU bound");
})().catch(error => { console.error(error); process.exitCode = 1; });
