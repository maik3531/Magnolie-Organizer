import assert from "node:assert/strict";
import { boot } from "./ui_harness.mjs";

const b = await boot(process.argv[2], Date.parse("2026-05-01T12:00:00Z"));
const { w, t, messages } = b;
const clone = value => JSON.parse(JSON.stringify(value));
const cases = [];
let checks = 0;
const equal = (a, expected, label) => { assert.deepEqual(clone(a), clone(expected), label); checks++; };
function field(selector, value) {
  const input = w.document.querySelector(selector);
  assert.ok(input, selector);
  if (input.type === "checkbox") input.checked = value;
  else if (input.dataset.iso !== undefined || input.type === "date") t.setzeDatumswert(input, value);
  else input.value = value;
  input.dispatchEvent(new w.Event("input", { bubbles: true }));
  input.dispatchEvent(new w.Event("change", { bubbles: true }));
}
function checkAt(instant, count, label) {
  b.at(instant);
  const before = messages.filter(m => m.cmd === "erinnerung_zeigen").length;
  t.pruefeErinnerungen();
  equal(messages.filter(m => m.cmd === "erinnerung_zeigen").length - before, count, label);
}
try {
  w.MacBeta.receive("init", { daten: { termine: [], aufgaben: [], kontakte: [], notizen: [],
    einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } }, neu: false,
    regional: { language: "en", timeZone: "UTC" } });
  for (const [name, location] of [["location", "Office"], ["escaped-location", "Room A, West; Floor 2 \\ Annex"]]) {
    t.oeffneTerminBlatt(null, "2026-05-10");
    field("#tb-titel", name); field("#tb-ganztaegig", false);
    field("#tb-zeit", "10:00"); field("#tb-endzeit", "11:00"); field("#tb-ort", location);
    w.document.querySelector("#tb-fertig").click();
    const created = t.daten().termine.at(-1);
    equal(created.ort, location, "actual LOCATION editor value");
    assert.ok(created.icsRoundtrip.some(line => line.startsWith("LOCATION:")));
    cases.push({ name, record: clone(created), location, start: "DTSTART:20260510T100000", end: "DTEND:20260510T110000" });
    t.oeffneTerminBlatt(created, "2026-05-10");
    field("#tb-zeit", "12:00"); field("#tb-endzeit", "13:00");
    w.document.querySelector("#tb-fertig").click();
    const edited = t.daten().termine.at(-1);
    assert.ok(edited.icsRoundtrip.includes("DTSTART;TZID=UTC:20260510T120000"));
    cases.push({ name: name + "-time-edit", record: clone(edited), location,
      start: "DTSTART;TZID=UTC:20260510T120000", end: "DTEND;TZID=UTC:20260510T130000" });
  }
  for (const zone of ["Europe/Berlin", "America/New_York", "system"]) {
    t.daten().einstellungen.regional.timeZone = zone;
    t.oeffneTerminBlatt(null, "2026-03-29");
    field("#tb-titel", "zone-edit"); field("#tb-ganztaegig", false);
    field("#tb-zeit", "10:00"); field("#tb-endzeit", "11:00"); field("#tb-ort", "Office");
    w.document.querySelector("#tb-fertig").click();
    t.oeffneTerminBlatt(t.daten().termine.at(-1), "2026-03-29");
    field("#tb-zeit", "12:00"); field("#tb-endzeit", "13:00");
    w.document.querySelector("#tb-fertig").click();
    const qualifier = zone === "system" ? "" : ";TZID=" + zone;
    cases.push({ name: zone, record: clone(t.daten().termine.at(-1)), location: "Office",
      start: "DTSTART" + qualifier + ":20260329T120000", end: "DTEND" + qualifier + ":20260329T130000" });
  }
  t.daten().einstellungen.regional.timeZone = "UTC";
  t.oeffneTerminBlatt(null, "2026-05-10");
  field("#tb-titel", "all-day"); field("#tb-ganztaegig", true); field("#tb-ort", "Office");
  w.document.querySelector("#tb-fertig").click();
  t.oeffneTerminBlatt(t.daten().termine.at(-1), "2026-05-10");
  field("#tb-datum-von", "2026-05-11"); field("#tb-datum-bis", "2026-05-12");
  w.document.querySelector("#tb-fertig").click();
  cases.push({ name: "all-day-edit", record: clone(t.daten().termine.at(-1)), location: "Office",
    start: "DTSTART;VALUE=DATE:20260511", end: "DTEND;VALUE=DATE:20260513" });
  t.oeffneTerminBlatt(t.daten().termine.at(-1), "2026-05-11");
  field("#tb-datum-von", "2026-03-28"); field("#tb-datum-bis", "2026-03-29");
  w.document.querySelector("#tb-fertig").click();
  cases.push({ name: "all-day-dst-edit", record: clone(t.daten().termine.at(-1)), location: "Office",
    start: "DTSTART;VALUE=DATE:20260328", end: "DTEND;VALUE=DATE:20260330" });
  t.daten().termine = [];
  const tasks = [];
  await t.wechsel("aufgaben");
  for (const [name, due, early] of [["early-only", false, 1], ["due-only", true, 0], ["combined", true, 1]]) {
    field("#aufgabe-titel", name);
    field("#aufgabe-faellig-zeile input", "2026-05-10");
    w.document.querySelector("#aufgabe-faellig-zeile").dispatchEvent(new w.MouseEvent("contextmenu", { bubbles: true }));
    w.document.querySelector("#vorschlags-menue button").click();
    field("#aufgabe-faellig-zeit-zeile input", "10:00");
    field("#aufgabe-erinnern", due);
    field("#aufgabe-individuelle-erinnerung", early ? "1 day before" : "");
    w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    const task = t.daten().aufgaben.at(-1);
    equal([task.titel, task.faellig, task.faelligZeit, task.erinnern, task.individuelleErinnerungTage],
      [name, "2026-05-10", "10:00", due, early], "actual task editor record");
    tasks.push(clone(task));
  }
  t.daten().einstellungen.erinnerung.an = true;
  if (process.argv.includes("--probe")) {
    t.daten().aufgaben = [tasks[0]]; b.at("2026-05-09T10:00:00Z"); t.pruefeErinnerungen();
    console.log(JSON.stringify({ cases, tasks, earlyOnlyCallbacks: messages.filter(m => m.cmd === "erinnerung_zeigen").length }));
  } else {
    t.daten().aufgaben = tasks;
    checkAt("2026-05-09T09:59:59Z", 0, "not early yet");
    checkAt("2026-05-09T10:00:00Z", 2, "early-only and combined, regardless of due checkbox");
    checkAt("2026-05-09T10:01:00Z", 0, "early IDs deduplicate polling");
    checkAt("2026-05-10T10:00:00Z", 2, "due-only and combined independently");
    checkAt("2026-05-10T10:01:00Z", 0, "due IDs deduplicate polling");
    const single = { ...clone(tasks[2]), id: "consent-task" };
    t.daten().aufgaben = [single];
    t.daten().einstellungen.erinnerung.an = false;
    checkAt("2026-05-09T10:00:00Z", 0, "global opt-out blocks early notification");
    t.daten().einstellungen.erinnerung.an = true;
    single.erledigt = true;
    checkAt("2026-05-09T10:00:00Z", 0, "completed task has no notifications");
    single.erledigt = false; single.faellig = "";
    checkAt("2026-05-09T10:00:00Z", 0, "missing due date has no notification");
    single.faellig = "2026-05-10";
    checkAt("2026-05-09T10:00:00Z", 1, "opt-out did not consume an alarm ID");
    single.titel = "renamed";
    checkAt("2026-05-09T10:01:00Z", 0, "title edit keeps stable identity");
    single.faelligZeit = "11:00";
    checkAt("2026-05-09T11:00:00Z", 1, "changed due instant gets new alarm identity");
    const base = clone(tasks[2]);
    const alarms = (patch, zone = "UTC") => w.MacBeta.taskAlarms({ ...base, ...patch }, zone);
    equal(alarms({ faelligZeit: "", individuelleErinnerungTage: 0 }).map(a => new Date(a.at).toISOString()),
      ["2026-05-10T08:00:00.000Z"], "date-only task default 08:00");
    equal(alarms({ erinnern: false, individuelleErinnerungTage: 0 }).length, 0, "no per-task consent");
    equal(alarms({ erledigt: true }).length, 0, "done helper gate");
    equal(alarms({ faellig: "" }).length, 0, "missing date helper gate");
    for (const raw of [["RRULE:FREQ=DAILY"], ["BEGIN:VALARM"], ["RECURRENCE-ID:20260510T100000Z"]]) {
      equal(alarms({ icsRoundtrip: raw }).length, 0, "no added recurrence/VALARM scheduler");
    }
    for (const [day, early, due] of [["2026-03-29", "2026-03-28T09:00:00.000Z", "2026-03-29T08:00:00.000Z"],
      ["2026-10-25", "2026-10-24T08:00:00.000Z", "2026-10-25T09:00:00.000Z"]]) {
      const list = alarms({ faellig: day }, "Europe/Berlin");
      equal(list.map(a => new Date(a.at).toISOString()), [due, early], "calendar day offsets across DST");
    }
    const source = { faellig: "2026-03-29", faelligZeit: "16:00", icsAnzeigeZeitzone: "Europe/Berlin",
      icsRoundtrip: ["DUE;TZID=America/New_York:20260329T100000"] };
    const sourceAlarms = alarms(source);
    equal(sourceAlarms.map(a => new Date(a.at).toISOString()),
      ["2026-03-29T14:00:00.000Z", "2026-03-28T14:00:00.000Z"], "source-zone calendar day, not display-zone day");
    const equivalent = alarms({ ...source, faelligZeit: "14:00", icsAnzeigeZeitzone: "UTC" });
    equal(clone(equivalent), clone(sourceAlarms), "same UTC occurrence has stable IDs after display-zone change");
    const utcRaw = alarms({ ...source, icsRoundtrip: ["DUE:20260329T140000Z"] });
    equal(clone(utcRaw), clone(sourceAlarms), "equivalent UTC raw DUE retains alarm identity");
    const dateOnly = alarms({ faelligZeit: "", icsRoundtrip: ["DUE;VALUE=DATE:20260510"] });
    equal(dateOnly.map(a => new Date(a.at).toISOString()), ["2026-05-10T08:00:00.000Z", "2026-05-09T08:00:00.000Z"], "raw DATE default time");
    equal(alarms({ faellig: "2026-03-29", faelligZeit: "02:30" }, "Europe/Berlin").length, 0, "DST gap is not silently shifted");
    equal(alarms({ faellig: "2026-10-25", faelligZeit: "02:30", individuelleErinnerungTage: 0 }, "Europe/Berlin")
      .map(a => new Date(a.at).toISOString()), ["2026-10-25T00:30:00.000Z"], "deterministic first fold occurrence");
    equal(alarms({ faellig: "2026-10-25", faelligZeit: "02:30", individuelleErinnerungTage: 0,
      icsAnzeigeZeitzone: "Europe/Berlin", icsRoundtrip: ["DUE:20261025T013000Z"] })
      .map(a => new Date(a.at).toISOString()), ["2026-10-25T01:30:00.000Z"], "explicit UTC resolves the second fold occurrence safely");
    equal(alarms({ faellig: "2026-03-30", faelligZeit: "02:30" }, "Europe/Berlin")
      .map(a => new Date(a.at).toISOString()), ["2026-03-30T00:30:00.000Z"], "nonexistent early wall time does not suppress a valid due notification");
    for (const patch of [{ ...source, faelligZeit: "15:00" }, { icsRoundtrip: ["DUE;TZID=Invalid/Zone:20260510T100000"] },
      { faellig: "2026-02-30" }, { faelligZeit: "25:00" }, { icsRoundtrip: ["DUE:20260510T100000Z", "DUE:20260510T110000Z"] }]) {
      assert.throws(() => alarms(patch)); checks++;
    }
    t.daten().aufgaben = [{ ...base, ...source, id: "source-callback" }];
    checkAt("2026-03-28T14:00:00Z", 1, "actual source-zone early callback");
    checkAt("2026-03-29T14:00:00Z", 1, "actual source-zone due callback");
    equal(messages.filter(m => m.cmd === "erinnerung_zeigen").at(-1).rumpf.includes(t.zeitText("2026-03-29", "14:00")),
      true, "callback shows the actual instant in the current organizer zone, not stale imported display time");
    t.daten().aufgaben = [];
    t.daten().customOrganizer = t.normalisiereCustomOrganizer({ modules: [{ id: "module", type: "tasks", title: "Custom",
      reminders: false, items: [{ id: "item", title: "Custom task", due: "2026-05-10", time: "10:00", remind: true }] }] });
    const module = t.daten().customOrganizer.modules[0];
    checkAt("2026-05-10T10:00:00Z", 0, "Custom module consent off");
    module.reminders = true; module.items[0].remind = false;
    checkAt("2026-05-10T10:00:00Z", 0, "Custom item consent off");
    module.items[0].remind = true; t.daten().einstellungen.erinnerung.an = false;
    checkAt("2026-05-10T10:00:00Z", 0, "global off overrides Custom consent");
    t.daten().einstellungen.erinnerung.an = true;
    checkAt("2026-05-10T10:00:00Z", 1, "Custom module and item consent on");
    checkAt("2026-05-10T10:01:00Z", 0, "Custom stable ID deduplication");
    module.items[0].id = "done"; module.items[0].done = true;
    checkAt("2026-05-10T10:00:00Z", 0, "completed Custom task");
    module.items[0].done = false;
    w.MacBeta.receive("init", { gesperrt: true });
    t.daten().einstellungen.erinnerung.an = true;
    t.daten().aufgaben = [{ ...base, id: "locked-candidate" }];
    checkAt("2026-05-10T10:00:00Z", 0, "locked profile gate remains intact");
    console.log(JSON.stringify({ cases, tasks, checks }));
  }
} finally { b.close(); }
