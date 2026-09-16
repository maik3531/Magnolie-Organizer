"use strict";

const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const windows = path.resolve(__dirname, "../app/web");
const linux = path.resolve(process.env.MAGNOLIE_LINUX_SOURCE || path.join(__dirname, "../../magnolie-organizer-2.0.0"), "web");
const roots = process.env.MAGNOLIE_WEB ? [process.env.MAGNOLIE_WEB] : [windows, linux].filter(root => fs.existsSync(root));
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function boot(web, data = {}, initialize = true) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://desktop-regression.invalid/index.html", pretendToBeVisual: true
  });
  const w = dom.window, messages = [], timers = [];
  w.setTimeout = (fn, delay) => { const timer = { fn, delay }; timers.push(timer); return timer; };
  w.clearTimeout = timer => { if (timer) timer.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w.crypto, "subtle", { value: webcrypto.subtle });
  w.__MAGNOLIE_BRUECKE__ = "regression";
  w.webkit = { messageHandlers: { regression: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  await tick();
  if (initialize) w.App.init({ daten: data, neu: false, regional: { language: "en", timeZone: "UTC" } });
  const t = w.OrganizerTest;
  return { w, t, messages, timers, close: () => dom.window.close(),
    saves: () => messages.filter(message => message.cmd === "speichern"),
    input(selector, value) { const field = w.document.querySelector(selector); assert.ok(field, selector);
      field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true })); return field; },
    answer(text) { const button = [...w.document.querySelectorAll("#aenderungen-schleier button")].find(button => button.textContent === text);
      assert.ok(button, text); button.click(); },
    ack(ok = true) { const save = messages.filter(message => message.cmd === "speichern").at(-1); assert.ok(save);
      w.App.gespeichert({ id: save.id, ok }); return save; }
  };
}

async function run(web) {
  if (web === windows) assert.match(fs.readFileSync(path.resolve(web, "../../ExchangeCodec.cs"), "utf8"),
    /InstanceUid\(string uid, IcsProperty recurrenceId\) => uid \+ "#" \+ recurrenceId.Value/,
    "Update frontend instance identities together with the native decoder contract");
  let cases = 0;
  async function test(name, fn, data = {}, initialize = true) {
    const b = await boot(web, data, initialize);
    let timeout;
    if (process.env.MAGNOLIE_TEST_TRACE) console.log(web + ": " + name);
    try {
      await Promise.race([fn(b), new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error("Test timed out")), 10000);
      })]);
      cases++;
    }
    catch (error) { error.message = path.basename(path.dirname(web)) + ": " + name + ": " + error.message; throw error; }
    finally { clearTimeout(timeout); b.close(); }
  }

  await test("unconfirmed startup cannot save", async b => {
    assert.equal(b.w.document.querySelector("#schreibtisch").hasAttribute("inert"), true);
    for (const timer of b.timers.filter(timer => timer.delay === 2500)) timer.fn();
    b.t.speichereJetzt(); assert.equal(b.saves().length, 0);
    b.w.App.vorBeenden(); await tick();
    assert.equal(b.saves().length, 0);
    b.w.App.init({ daten: { notizen: [{ id: "existing", titel: "Existing", text: "Keep", html: "Keep" }] }, neu: false });
    assert.equal(b.w.document.querySelector("#schreibtisch").hasAttribute("inert"), false);
    b.t.speichereJetzt(); assert.equal(JSON.parse(b.saves().at(-1).text).notizen[0].id, "existing");
  }, {}, false);

  await test("search ASCII fast path preserves Turkish I and non-ASCII folding", async b => {
    b.t.daten().termine = [{ id: "ascii", titel: "I", datum: "2026-09-08" },
      { id: "unicode", titel: "ÉCOLE", datum: "2026-09-08" }];
    assert.equal(b.t.suchTrefferFuer("kalender", ["i"], 101).length, 1);
    assert.equal(b.t.suchTrefferFuer("kalender", ["école"], 101).length, 1);
    b.w.eval(fs.readFileSync(path.join(web, "i18n/tr.js"), "utf8"));
    b.w.MagnolieI18n.setLocale("tr");
    assert.equal(b.t.suchTrefferFuer("kalender", ["ı"], 101).length, 1);
    assert.equal(b.t.suchTrefferFuer("kalender", ["i"], 101).length, 0);
    assert.equal(b.t.suchTrefferFuer("kalender", ["école"], 101).length, 1);
    b.t.daten().einstellungen.regional.formatLocale = "system";
    const systemI = "I".toLocaleLowerCase(new b.w.Intl.DateTimeFormat().resolvedOptions().locale);
    assert.equal(b.t.suchTrefferFuer("kalender", [systemI], 101).length, 1);
  });

  await test("filtered completed deletion", async b => {
    b.t.zustand().aufgaben.filter.person = "p1"; await b.t.wechsel("aufgaben");
    b.w.document.querySelector(".zwischentitel button").click();
    assert.match(b.w.document.querySelector("#dialog-text").textContent, /1 completed task/);
    b.w.document.querySelector("#dialog-ja").click(); await tick();
    assert.deepEqual(plain(b.t.daten().aufgaben.map(a => a.id)), ["hidden"]);
    assert.deepEqual(plain(b.t.daten().geloescht.aufgaben.map(a => a.uid)), ["visible-uid"]);
  }, { personen: [{ id: "p1", name: "One" }, { id: "p2", name: "Two" }], aufgaben: [
    { id: "visible", uid: "visible-uid", titel: "Visible", erledigt: true, personen: ["p1"], sync: true },
    { id: "hidden", uid: "hidden-uid", titel: "Hidden", erledigt: true, personen: ["p2"], sync: true }] });

  await test("task navigation save and cancel", async b => {
    await b.t.wechsel("aufgaben"); b.input("#aufgabe-titel", "Draft task");
    const cancelled = b.t.wechsel("notizen"); b.answer("Cancel"); await cancelled;
    assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Draft task");
    const saved = b.t.wechsel("notizen"); b.answer("Save"); await saved;
    assert.equal(b.t.daten().aufgaben[0].titel, "Draft task"); assert.equal(b.t.zustand().sektion, "notizen");
  });

  await test("task filter and cancelled delete retain editor registration", async b => {
    await b.t.wechsel("aufgaben");
    b.w.document.querySelector(".loesch-x").click();
    b.w.document.querySelector("#dialog-nein").click(); await tick();
    b.input("#aufgabe-titel", "Still guarded");
    const filter = b.w.document.querySelector("#filter-person");
    filter.value = "person"; filter.dispatchEvent(new b.w.Event("change"));
    b.answer("Cancel"); await tick();
    assert.equal(filter.value, ""); assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Still guarded");
    const navigation = b.t.wechsel("notizen"); b.answer("Discard"); await navigation;
    assert.equal(b.t.daten().aufgaben.length, 1);
  }, { personen: [{ id: "person", name: "Person" }], aufgaben: [{ id: "existing", uid: "existing", titel: "Existing" }] });

  await test("native quit preserves modal appointment", async b => {
    b.t.oeffneTerminBlatt(null, "2026-09-10"); b.input("#tb-titel", "Draft appointment");
    b.w.App.vorBeenden(); b.answer("Cancel"); await tick();
    assert.ok(b.messages.some(message => message.cmd === "beenden_abgebrochen"));
    assert.equal(b.w.document.querySelector("#tb-titel").value, "Draft appointment");
    b.w.App.vorBeenden(); b.answer("Save"); await tick();
    assert.equal(b.t.daten().termine[0].titel, "Draft appointment");
    assert.ok(!b.messages.some(message => message.cmd === "beenden_bereit"));
    b.ack(); assert.ok(b.messages.some(message => message.cmd === "beenden_bereit"));
  });

  await test("grid time is initialized before the dirty snapshot and time-wheel baseline", async b => {
    await b.t.wechsel("aufgaben");
    b.t.zustand().kalender.ansicht = "day";
    await b.t.wechsel("kalender");
    const hour = () => b.w.document.querySelector('#inhalt-links .stunden-reihe[data-stunde="9"] .stunden-feld');
    assert.ok(hour()); hour().click();
    assert.equal(b.w.document.querySelector("#tb-zeit").value, "09:00");
    const cancel = () => [...b.w.document.querySelectorAll("#termin-schleier button")].find(button => button.textContent === "Cancel").click();
    cancel();
    assert.ok(!b.w.document.querySelector("#termin-schleier"));
    assert.ok(!b.w.document.querySelector("#aenderungen-schleier"));
    hour().click();
    const time = b.input("#tb-zeit", "10:00"); time.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(b.w.document.querySelector("#tb-endzeit").value, "11:00");
    cancel(); assert.ok(b.w.document.querySelector("#aenderungen-schleier"));
    b.answer("Discard"); await tick();
    assert.equal(b.t.daten().termine.length, 0);
  });

  await test("late calendar worker does not rebuild contact", async b => {
    let worker, frame;
    b.w.Worker = class { constructor() { worker = this; } postMessage(job) { this.job = job; } };
    b.w.URL.createObjectURL = () => "blob:regression"; b.w.URL.revokeObjectURL = () => {};
    b.w.requestAnimationFrame = fn => { frame = fn; return 1; };
    b.t.icsRuntime("expand", { icsRoundtrip: ["DTSTART:20260908T120000Z", "RRULE:FREQ=DAILY"] }, [0, 1]);
    await b.t.wechsel("adressen");
    [...b.w.document.querySelectorAll("#kopf-links button")].find(button => button.textContent === "New").click();
    const field = b.input("#kontakt-nachname", "Keep draft"); field.focus();
    worker.onmessage({ data: { key: worker.job.key, result: [] } }); frame();
    assert.equal(field.isConnected, true); assert.equal(field.value, "Keep draft");
    assert.equal(b.w.document.activeElement, field);
  });

  await test("custom text recycle bin survives reload with links", async b => {
    const d = b.t.daten(); d.einstellungen.allgemein.customTab.enabled = true;
    d.customOrganizer = { version: 3, modules: [
      { id: "text", type: "notes", page: "left", order: 0, items: [{ id: "stable", title: "Text", text: "Keep", html: "<b>Keep</b>" }] },
      { id: "tasks", type: "tasks", page: "right", order: 0, items: [{ id: "task", title: "Task", textItemId: "stable" }] }] };
    await b.t.wechsel("custom"); b.w.document.querySelector(".custom-modul-notes .rot").click();
    assert.equal(d.customOrganizer.modules[0].items.length, 1);
    b.w.document.querySelector("#dialog-ja").click(); await tick();
    assert.equal(d.customOrganizer.modules[0].items.length, 0);
    assert.equal(d.customOrganizer.modules[1].items[0].textItemId, "");
    b.w.App.init({ daten: plain(d), neu: false });
    assert.equal(b.t.daten().papierkorb.length, 1);
    assert.equal(b.t.ausDemPapierkorb(b.t.daten().papierkorb[0]), true);
    const modules = b.t.daten().customOrganizer.modules;
    assert.equal(modules.find(m => m.type === "notes").items[0].html, "<b>Keep</b>");
    assert.equal(modules.find(m => m.type === "tasks").items[0].textItemId, "stable");
  });

  await test("custom modal participates in native quit guard", async b => {
    b.t.daten().einstellungen.allgemein.customTab.enabled = true;
    b.t.daten().customOrganizer = { version: 3, modules: [{ id: "module", type: "tasks", page: "left", items: [] }] };
    await b.t.wechsel("custom"); b.w.document.querySelector(".custom-modul-kopf-aktionen button").click();
    b.input(".custom-eintrag-formular input[type=text]", "Custom draft");
    b.w.App.vorBeenden(); b.answer("Save"); await tick();
    assert.equal(b.t.daten().customOrganizer.modules[0].items[0].title, "Custom draft");
    b.ack(); assert.ok(b.messages.some(m => m.cmd === "beenden_bereit"));
  });

  await test("note snapshot survives asynchronous sync handoff", async b => {
    await b.t.wechsel("notizen");
    const field = b.w.document.querySelector("#notiz-text");
    field.innerHTML = "Latest pending text"; field.dispatchEvent(new b.w.Event("input", { bubbles: true }));
    b.w.App.syncFertig({ termine: [], aufgaben: [], kontakte: [], jahrestage: [] });
    assert.equal(b.t.daten().notizen[0].text, "Latest pending text");
    await b.t.wechsel("adressen"); b.t.speichereJetzt();
    assert.equal(JSON.parse(b.saves().at(-1).text).notizen[0].text, "Latest pending text");
  }, { notizen: [{ id: "note", titel: "Note", text: "Old", html: "Old" }] });

  await test("two imported profiles retain their own task parents", async b => {
    for (const source of ["profile-a", "profile-b"]) b.t.mergeAufgaben([
      { uid: "parent", titel: "Parent", icsQuelleId: source, geaendert: 1 },
      { uid: "child", elternUid: "parent", titel: "Child", icsQuelleId: source, geaendert: 1 }]);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    b.t.mergeAufgaben([{ uid: "child", elternUid: "parent", titel: "Updated", icsQuelleId: "profile-b", geaendert: 2 }]);
    const tasks = b.t.daten().aufgaben; assert.equal(tasks.length, 4);
    for (const source of ["profile-a", "profile-b"]) {
      const own = tasks.filter(a => a.icsQuelleId === source);
      const parent = own.find(a => a.icsImportUid === "parent"), child = own.find(a => a.icsImportUid === "child");
      assert.equal(child.elternUid, parent.uid);
    }
    assert.equal(tasks.find(a => a.icsQuelleId === "profile-a" && a.icsImportUid === "child").titel, "Child");
  });

  await test("calendar and anniversary metadata roundtrip", async b => {
    const metadata = { icsTimezones: [["BEGIN:VTIMEZONE", "TZID:Private", "END:VTIMEZONE"]],
      icsAnzeigeZeitzone: "Europe/Berlin", icsRangeOverrides: [["RECURRENCE-ID:20260908T120000Z"]],
      icsAusnahmeTermine: [{ datum: "2026-09-08", zeit: "12:00:01" }], icsRoundtrip: ["X-LONG:" + "x".repeat(5000)] };
    b.t.mergeTermine([{ uid: "event", datum: "2026-09-08", titel: "Event", ...metadata }]);
    b.t.mergeJahrestage([{ uid: "anniversary", datum: "2026-09-08", name: "Anniversary", ...metadata }]);
    const normalized = b.t.normalisiere(plain(b.t.daten()));
    for (const field of Object.keys(metadata)) {
      assert.deepEqual(plain(normalized.termine[0][field]), metadata[field], field);
      assert.deepEqual(plain(normalized.jahrestage[0][field]), metadata[field], field);
    }
  });

  await test("older imported task parents stay linked on reimport", async b => {
    b.t.mergeAufgaben([{ uid: "child", elternUid: "parent", titel: "Updated", icsQuelleId: "old-profile", geaendert: 20 }]);
    const task = b.t.daten().aufgaben.find(a => a.id === "child");
    assert.equal(task.elternUid, "parent"); assert.equal(task.titel, "Updated");
  }, { aufgaben: [{ id: "parent", uid: "parent", titel: "Parent", icsQuelleId: "old-profile", geaendert: 10 },
    { id: "child", uid: "child", elternUid: "parent", titel: "Child", icsQuelleId: "old-profile", geaendert: 10 }] });

  await test("source-qualified detached task IDs match native identities", async b => {
    const value = "20260909T120000Z";
    const suffix = web === windows ? "#" + value : "-magnolie-instanz-" + (await b.t.personalSyncHash([{}, value])).slice(0, 16);
    for (const source of ["a", "b"]) b.t.mergeAufgaben([
      { uid: "same", titel: "Master", icsQuelleId: source, geaendert: 1 },
      { uid: "same" + suffix, icsSerienUid: "same", titel: "Instance", icsQuelleId: source,
        icsRoundtrip: ["RECURRENCE-ID:" + value], geaendert: 1 }]);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    for (const source of ["a", "b"]) {
      const own = b.t.daten().aufgaben.filter(item => item.icsQuelleId === source);
      const master = own.find(item => item.icsImportUid === "same");
      const instance = own.find(item => item.icsImportUid === "same" + suffix);
      assert.equal(instance.uid, master.uid + suffix); assert.equal(instance.icsSerienUid, "same");
    }
    assert.equal(b.t.daten().aufgaben.length, 4);
  });

  await test("task series migration requires original identity proof", async b => {
    const source = "proof", suffixes = ["#20260911", "-magnolie-instanz-8e04acb78995f24b"];
    b.t.mergeAufgaben([{ uid: "family", titel: "Master", icsQuelleId: source }]);
    const local = b.t.daten().aufgaben[0].uid;
    const tasks = [{ id: "master", uid: local, icsImportUid: "family", icsSerienUid: local, icsQuelleId: source, titel: "Master" }];
    suffixes.forEach((suffix, i) => tasks.push({ id: "instance" + i, uid: local + suffix,
      icsImportUid: "family" + suffix, icsSerienUid: local, icsQuelleId: source, titel: "Instance",
      icsRoundtrip: ["RECURRENCE-ID;VALUE=DATE:20260911"] }));
    tasks.push({ id: "legitimate", uid: "mag-task-legitimate", titel: "Legitimate", icsSerienUid: "mag-task-legitimate" });
    b.w.App.init({ daten: { aufgaben: tasks }, neu: false });
    for (const task of b.t.daten().aufgaben) assert.equal(task.icsSerienUid,
      task.id === "legitimate" ? "mag-task-legitimate" : "family");
    assert.equal(b.t.daten().aufgaben.find(a => a.id === "master").uid, local);
  });

  await test("both native instance spellings merge by external family and recurrence ID", async b => {
    const source = "same-source";
    b.t.mergeAufgaben([{ uid: "family", titel: "Master", icsQuelleId: source },
      { uid: "family-magnolie-instanz-8e04acb78995f24b", icsSerienUid: "family", icsQuelleId: source,
        titel: "Moved", icsRoundtrip: ["RECURRENCE-ID;VALUE=DATE:20260911"] }]);
    const ids = b.t.daten().aufgaben.map(a => a.id);
    b.t.mergeAufgaben([{ uid: "family#20260911", icsSerienUid: "family", icsQuelleId: source,
      titel: "Moved", icsRoundtrip: ["RECURRENCE-ID;VALUE=DATE:20260911"] }]);
    assert.deepEqual(b.t.daten().aufgaben.map(a => a.id), ids);
    assert.equal(b.t.daten().aufgaben[1].icsSerienUid, "family");
  });

  await test("task draft saves into current objects after metadata sync", async b => {
    b.t.zustand().aufgaben.bearbeiteId = "task"; await b.t.wechsel("aufgaben");
    b.input("#aufgabe-titel", "Local draft");
    const tasks = plain(b.t.daten().aufgaben); tasks[0].geaendert = 200;
    b.w.App.syncFertig({ aufgaben: tasks });
    assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Local draft");
    b.w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    assert.equal(b.t.daten().aufgaben[0].titel, "Local draft");
  }, { aufgaben: [{ id: "task", uid: "task", titel: "Original", geaendert: 100 }] });

  await test("contact draft saves into current objects after metadata sync", async b => {
    b.t.zustand().adressen.auswahlId = "contact"; b.t.zustand().adressen.modus = "bearbeiten";
    await b.t.wechsel("adressen"); b.input("#kontakt-nachname", "Local draft");
    const contacts = plain(b.t.daten().kontakte); contacts[0].geaendert = 200;
    b.w.App.syncFertig({ kontakte: contacts });
    b.w.document.querySelector(".kontakt-form-knoepfe button").click();
    assert.equal(b.t.daten().kontakte[0].nachname, "Local draft");
  }, { kontakte: [{ id: "contact", uid: "contact", nachname: "Original", geaendert: 100 }] });

  await test("conflicting appointment response cannot silently overwrite either draft", async b => {
    b.t.oeffneTerminBlatt(b.t.daten().termine[0], "2026-09-08"); b.input("#tb-titel", "Local title");
    const appointments = plain(b.t.daten().termine); appointments[0].titel = "Remote title";
    b.w.App.syncFertig({ termine: appointments });
    b.w.document.querySelector("#tb-fertig").click();
    assert.equal(b.t.daten().termine[0].titel, "Remote title");
    assert.equal(b.w.document.querySelector("#tb-titel").value, "Local title");
    assert.match(b.w.document.querySelector("#zettel").textContent, /Conflict/);
  }, { termine: [{ id: "appointment", uid: "appointment", datum: "2026-09-08", titel: "Original" }] });

  await test("title-only appointment editor keeps DTSTART and RRULE", async b => {
    const appointment = b.t.daten().termine[0];
    b.t.oeffneTerminBlatt(appointment, "2026-09-08"); b.input("#tb-titel", "Renamed");
    b.w.document.querySelector("#tb-fertig").click();
    assert.equal(appointment.titel, "Renamed");
    assert.ok(appointment.icsRoundtrip.includes("DTSTART:20260908T120000Z"));
    assert.ok(appointment.icsRoundtrip.includes("RRULE:FREQ=DAILY"));
  }, { termine: [{ id: "appointment", uid: "appointment", datum: "2026-09-08", zeit: "12:00", endZeit: "13:00", titel: "Original",
    wiederholung: { art: "daily", bis: "" }, icsRoundtrip: ["DTSTART:20260908T120000Z", "DTEND:20260908T130000Z", "RRULE:FREQ=DAILY"] }] });

  for (const [art, intervall, ordinal] of [["daily", 3, false], ["weekly", 2, false],
    ["monthly", 2, false], ["yearly", 2, false], ["monthly", 2, true]]) {
    const recurrence = { art, bis: "", intervall,
      ...(ordinal ? { ordinal: 2, wochentag: "MO" } : {}) };
    const rule = `RRULE:FREQ=${art.toUpperCase()};INTERVAL=${intervall}` + (ordinal ? ";BYDAY=2MO" : "");
    await test(`title-only edit preserves ${rule}`, async b => {
      const appointment = b.t.daten().termine[0];
      b.t.oeffneTerminBlatt(appointment, "2026-01-12"); b.input("#tb-titel", "Renamed interval");
      b.w.document.querySelector("#tb-fertig").click();
      assert.equal(appointment.titel, "Renamed interval");
      assert.deepEqual(plain(appointment.wiederholung), recurrence);
      assert.ok(appointment.icsRoundtrip.includes(rule));
    }, { termine: [{ id: "interval", uid: "interval", datum: "2026-01-12", zeit: "", titel: "Original",
      wiederholung: recurrence, icsRoundtrip: ["DTSTART;VALUE=DATE:20260112", rule] }] });
  }

  await test("imported interval can explicitly change to the ordinary daily option", async b => {
    const appointment = b.t.daten().termine[0];
    b.t.oeffneTerminBlatt(appointment, "2026-01-12");
    const frequency = b.w.document.querySelector("#tb-wiederholung");
    assert.equal(frequency.value, "daily-3");
    frequency.value = "daily"; frequency.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    b.w.document.querySelector("#tb-fertig").click();
    assert.deepEqual(plain(appointment.wiederholung), { art: "daily", bis: "" });
    assert.ok(appointment.icsRoundtrip.includes("RRULE:FREQ=DAILY"));
    assert.ok(!appointment.icsRoundtrip.some(line => line.includes("INTERVAL=3")));
  }, { termine: [{ id: "interval", uid: "interval", datum: "2026-01-12", zeit: "", titel: "Original",
    wiederholung: { art: "daily", bis: "", intervall: 3 },
    icsRoundtrip: ["DTSTART;VALUE=DATE:20260112", "RRULE:FREQ=DAILY;INTERVAL=3"] }] });

  await test("start-only recurring task keeps its schedule when its title changes", async b => {
    b.t.zustand().aufgaben.bearbeiteId = "start-only"; await b.t.wechsel("aufgaben");
    b.input("#aufgabe-titel", "Renamed start-only");
    b.w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    const task = b.t.daten().aufgaben[0];
    assert.equal(task.titel, "Renamed start-only");
    assert.deepEqual([task.startDatum, task.startZeit, task.faellig, task.faelligZeit],
      ["2026-09-10", "09:00", "", ""]);
    assert.ok(task.icsRoundtrip.includes("DTSTART:20260910T090000Z"));
    assert.ok(task.icsRoundtrip.includes("RRULE:FREQ=DAILY"));
  }, { aufgaben: [{ id: "start-only", uid: "start-only", titel: "Original", startDatum: "2026-09-10",
    startZeit: "09:00", faellig: "", faelligZeit: "",
    icsRoundtrip: ["DTSTART:20260910T090000Z", "RRULE:FREQ=DAILY"] }] });

  await test("overnight task title edit", async b => {
    b.t.zustand().aufgaben.bearbeiteId = "overnight"; await b.t.wechsel("aufgaben");
    assert.match(b.w.document.querySelector("#aufgabe-startdatum").getAttribute("aria-label"), /Date/);
    b.input("#aufgabe-titel", "Updated overnight");
    b.w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    const task = b.t.daten().aufgaben[0];
    assert.equal(task.titel, "Updated overnight"); assert.equal(task.startDatum, "2026-09-07");
    assert.equal(task.faellig, "2026-09-08"); assert.equal(task.startZeit, "23:00"); assert.equal(task.faelligZeit, "02:00");
  }, { aufgaben: [{ id: "overnight", uid: "overnight", titel: "Overnight", startDatum: "2026-09-07", faellig: "2026-09-08", startZeit: "23:00", faelligZeit: "02:00" }] });

  await test("recurring checkbox completes only the displayed occurrence", async b => {
    await b.t.wechsel("aufgaben");
    for (let i = 0; i < 1000 && b.w.document.querySelector(".check").disabled; i++) await tick();
    assert.equal(b.w.document.querySelector(".check").disabled, false);
    b.w.document.querySelector(".check").click(); await tick();
    const master = b.t.daten().aufgaben.find(a => a.id === "series");
    assert.equal(master.erledigt, false);
    assert.equal(b.t.daten().aufgaben.filter(a => a.erledigt).length, 1);
    const done = b.t.daten().aufgaben.find(a => a.erledigt);
    const rid = done.icsRoundtrip.find(line => line.startsWith("RECURRENCE-ID"));
    const value = rid.slice(rid.lastIndexOf(":") + 1);
    const suffix = web === windows ? "#" + value : "-magnolie-instanz-" + (await b.t.personalSyncHash([{}, value])).slice(0, 16);
    assert.equal(done.uid, master.uid + suffix, "Native decoder instance identity must roundtrip");
    assert.ok(master.icsRoundtrip.some(line => line.startsWith("EXDATE:")));
    const next = b.t.icsNaechsteAufgabe(master, b.t.isoHeute());
    assert.ok(next && next.icsOccurrence > b.t.daten().aufgaben.find(a => a.erledigt).icsOccurrence);
  }, { aufgaben: [{ id: "series", uid: "series", titel: "Series", startDatum: "2026-01-01", faellig: "2026-01-01", startZeit: "12:00", faelligZeit: "13:00",
    icsRoundtrip: ["BEGIN:VTODO", "UID:series", "DTSTART:20260101T120000Z", "DUE:20260101T130000Z", "RRULE:FREQ=DAILY", "END:VTODO"] }] });

  await test("cached calendar error keeps second print incomplete", async b => {
    const first = b.t.planerMonatsModell(2026, 8), second = b.t.planerMonatsModell(2026, 8);
    assert.equal(first.icsIncomplete, true); assert.equal(second.icsIncomplete, true);
  }, { termine: [{ id: "bad", uid: "bad", datum: "2026-09-08", titel: "Bad zone", icsRoundtrip: ["DTSTART;TZID=Invalid/Zone:20260908T120000", "DURATION:PT1H"] }] });

  await test("all-day instance identity includes native VALUE=DATE parameters", async b => {
    await b.t.wechsel("aufgaben");
    for (let i = 0; i < 1000 && b.w.document.querySelector(".check").disabled; i++) await tick();
    assert.equal(b.w.document.querySelector(".check").disabled, false);
    b.w.document.querySelector(".check").click(); await tick();
    const done = b.t.daten().aufgaben.find(item => item.erledigt);
    const rid = done.icsRoundtrip.find(line => line.startsWith("RECURRENCE-ID;VALUE=DATE:"));
    assert.ok(rid);
    const value = rid.slice(rid.lastIndexOf(":") + 1);
    const suffix = web === windows ? "#" + value : "-magnolie-instanz-" + (await b.t.personalSyncHash([{ VALUE: "DATE" }, value])).slice(0, 16);
    assert.equal(done.uid, "all-day" + suffix);
  }, { aufgaben: [{ id: "all-day", uid: "all-day", titel: "All day", startDatum: "2026-01-01", faellig: "2026-01-02",
    icsRoundtrip: ["DTSTART;VALUE=DATE:20260101", "DUE;VALUE=DATE:20260102", "RRULE:FREQ=DAILY"] }] });

  await test("Personal Sync dirty timestamp preserves DAV baseline despite clock rollback", async b => {
    const old = b.t.daten().aufgaben[0]; b.w.Date.now = () => 100;
    const baseline = plain(old.syncQuellen);
    b.t.personalSyncSetze({ kind: "task", value: { title: "Incoming", note: "", due: "2026-09-09", priority: 2, completed: false, remind: false, modified_ms: 200 } }, "dav", false);
    const task = b.t.daten().aufgaben[0];
    assert.ok(task.geaendert > 10000); assert.deepEqual(plain(task.syncQuellen), baseline);
  }, { aufgaben: [{ id: "dav", uid: "dav", titel: "Original", geaendert: 10000, syncQuellen: { calendar: { id: "href", etag: "baseline" } } }] });

  await test("sync journal ACK requires matching durable save", async b => {
    const transactionId = "a".repeat(64), cmd = web === windows ? "sync_commit" : "sync_bestaetigen";
    b.w.App.syncFertig({ transactionId, termine: [], aufgaben: [], kontakte: [], jahrestage: [] });
    assert.ok(!b.messages.some(message => message.cmd === cmd));
    assert.ok(b.saves().length > 0);
    b.w.App.gespeichert({ id: b.saves().at(-1).id + 20, ok: true });
    assert.ok(!b.messages.some(message => message.cmd === cmd));
    b.ack(false); assert.ok(!b.messages.some(message => message.cmd === cmd));
    b.w.App.syncFertig({ transactionId, termine: [], aufgaben: [], kontakte: [], jahrestage: [] });
    b.ack(); assert.equal(b.messages.filter(message => message.cmd === cmd).length, 1);
  });

  await test("duplicate pending Personal Sync joins save and retries failure", async b => {
    b.w.App.telefonStand({ peers: [{ device_id: "peer", display_name: "Synthetic" }] });
    b.t.daten().personalSync.applied_batches.push("pending-token");
    b.t.speichereJetzt();
    const message = { device_id: "peer", kind: "personal_sync.batch", commit_token: "pending-token", pending_message_id: "message",
      body: { format: 1, run_id: "run", requested_modules: ["tasks"], records: [], reply: true } };
    b.w.App.personalSync(message);
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit").length, 0);
    b.w.App.gespeichert({ ok: true });
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit").length, 0);
    b.ack(false);
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit").length, 0);
    b.w.App.personalSync(message); b.ack();
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit" && m.erfolgreich).length, 1);
  });

  await test("batch hash fault cannot partly update data or clocks", async b => {
    const value = { title: "Valid first record", note: "", due: "2026-09-09", priority: 2, completed: false,
      remind: false, lead_days: 0, reminder_minute: 480, created_ms: 1, modified_ms: 2 };
    const good = { kind: "task", id: "incoming", value, hash: await b.t.personalSyncHash(value),
      modified_ms: 2, clock: [{ actor_id: "00000000-0000-4000-8000-000000000001", counter: 1 }] };
    const before = plain(b.t.daten());
    await assert.rejects(b.t.personalSyncAnwenden([good, { ...good, id: "bad", hash: "0".repeat(64) }], {}, 1, "peer", ["tasks"]));
    assert.deepEqual(plain(b.t.daten().aufgaben), before.aufgaben);
    assert.deepEqual(plain(b.t.daten().personalSync), before.personalSync);
  });

  await test("worker continuation yields beyond sixteen attempts", async b => {
    let source;
    b.w.Blob = class { constructor(parts) { source = parts.join(""); } };
    b.w.URL.createObjectURL = () => "blob:scheduler";
    b.w.URL.revokeObjectURL = () => {};
    b.w.Worker = class { postMessage() {} };
    b.t.icsRuntime("expand", { icsRoundtrip: ["DTSTART:20260908T120000Z"] }, [0, 1]);
    const turns = [], results = [], sandbox = { self: { postMessage: value => results.push(value) }, setTimeout: fn => turns.push(fn), Date, performance };
    vm.createContext(sandbox);
    vm.runInContext(source + '\nlet probes = 0; icsExpansion = () => { if (++probes <= 20) { const error = new Error("continue"); error.retryable = true; error.code = "recurrence-work-limit"; throw error; } return [probes]; };', sandbox);
    sandbox.self.onmessage({ data: { key: "job", zone: "UTC", mode: "expand", item: {}, args: [] } });
    assert.equal(results.length, 0); assert.equal(turns.length, 1);
    let count = 0;
    while (turns.length) { assert.ok(++count < 30); turns.shift()(); }
    assert.equal(count, 20); assert.deepEqual(plain(results), [{ key: "job", result: [21] }]);
  });

  await test("disabled reminder remains disabled after native response", async b => {
    b.t.oeffneEinstellungen();
    [...b.w.document.querySelectorAll(".einst-reiter-knopf")].find(button => button.textContent === "Notifications").click();
    const toggle = b.w.document.querySelector("#erinnerung-an");
    toggle.checked = false; toggle.dispatchEvent(new b.w.Event("change"));
    b.w.App.erinnerungStand({ ok: true });
    assert.equal(b.t.daten().einstellungen.erinnerung.an, false);
    assert.match(b.w.document.querySelector("#erinnerung-stand").textContent, /not currently reminding/);
  });

  await test("custom bulk removal restores links in either order", async b => {
    b.t.daten().customOrganizer = { version: 3, modules: [
      { id: "note", type: "notes", page: "left", items: [{ id: "text", text: "Keep", html: "Keep" }] },
      { id: "task", type: "tasks", page: "right", items: [{ id: "linked", title: "Linked", textItemId: "text" }] }] };
    const stoff = b.t.druckStoff("custom"); stoff.entfernen(stoff.liste);
    assert.equal(b.t.daten().papierkorb.length, 2);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    const taskTrash = b.t.daten().papierkorb.find(s => s.eintrag.type === "tasks");
    assert.equal(b.t.ausDemPapierkorb(taskTrash), true);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    assert.equal(b.t.ausDemPapierkorb(b.t.daten().papierkorb[0]), true);
    assert.equal(b.t.daten().customOrganizer.modules.find(m => m.type === "tasks").items[0].textItemId, "text");
  });
  console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": " + cases + " desktop state regressions passed");
}

(async () => { for (const root of roots) await run(root); })().catch(error => { console.error(error); process.exitCode = 1; });
