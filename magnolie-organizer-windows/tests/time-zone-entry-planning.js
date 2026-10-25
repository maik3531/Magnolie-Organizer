"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
   'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "zeitzonenEintragPlan, wendeTerminWerteAn, wendeAufgabenWerteAn, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      Object.assign(b.t.daten().einstellungen.regional, { timeZone: "Europe/Berlin", timeZoneManagement: "manual" });
      const event = { id: "owned-event", uid: "stable-owned-uid", datum: "2026-10-22", zeit: "01:30", endZeit: "02:30", geaendert: 1234, icsAnzeigeZeitzone: "Europe/Berlin",
        syncQuellen: { owned: { etag: "keep-etag" } }, icsRoundtrip: ["UID:stable-owned-uid", "DTSTART:20261021T233047Z", "DTEND:20261022T003047Z", "X-OWNED:retained", "BEGIN:VALARM", "TRIGGER:-PT5M", "ACTION:DISPLAY", "END:VALARM"] };
      const image = JSON.stringify(event);
      const apply = (entry, args = {}, task = false) => b.t.zeitzonenEintragPlan(entry, task, { mode: "display", time_zone: "America/New_York", ...args });
      const shown = apply(event);
      assert.equal(shown.view.start_date, "2026-10-21"); assert.equal(shown.view.start_time, "19:30:47");
      assert.equal(shown.view.start_utc_ms, Date.parse("2026-10-21T23:30:47Z")); assert.equal(shown.view.instant_changed, false);
      assert.equal(shown.next.zeit, "19:30"); assert.equal(shown.next.icsAnzeigeZeitzone, "America/New_York");
      assert.deepEqual(Array.from(shown.next.icsRoundtrip), event.icsRoundtrip); assert.equal(shown.next.geaendert, 1234);
      const planned = apply(event, { mode: "plan" });
      assert.equal(planned.view.start_date, "2026-10-22"); assert.equal(planned.view.start_time, "01:30:47");
      assert.equal(planned.view.start_utc_ms, Date.parse("2026-10-22T05:30:47Z")); assert.equal(planned.view.instant_changed, true);
      assert.ok(planned.next.icsRoundtrip.includes("DTSTART:20261022T053047Z")); assert.ok(planned.next.icsRoundtrip.includes("X-MAGNOLIE-PLANNING-TZID:America/New_York"));
      assert.equal(planned.next.uid, event.uid); assert.equal(JSON.stringify(planned.next.syncQuellen), JSON.stringify(event.syncQuellen));
      for (const line of ["X-OWNED:retained", "BEGIN:VALARM", "TRIGGER:-PT5M", "END:VALARM"]) assert.ok(planned.next.icsRoundtrip.includes(line));
      assert.throws(() => apply(event, { mode: "plan", time_zone: "Europe/Berlin", start_date: "2026-03-29", start_time: "02:30", end_date: "2026-03-29", end_time: "04:00" }), /does not exist or is ambiguous/);
      const fold = { mode: "plan", start_date: "2026-11-01", start_time: "01:30:47", end_date: "2026-11-01", end_time: "02:00:47" };
      assert.throws(() => apply(event, fold), /does not exist or is ambiguous/);
      const early = apply(event, { ...fold, start_fold: "earlier" }), late = apply(event, { ...fold, start_fold: "later" });
      assert.equal(early.view.start_utc_ms, Date.parse("2026-11-01T05:30:47Z")); assert.equal(late.view.start_utc_ms, Date.parse("2026-11-01T06:30:47Z"));
      assert.ok(late.next.icsRoundtrip.includes("DTSTART:20261101T063047Z"), "A later fold needs an unambiguous wire instant");
      const unchangedFold = apply(late.next, { mode: "plan" });
      assert.equal(unchangedFold.view.start_utc_ms, late.view.start_utc_ms); assert.equal(unchangedFold.view.instant_changed, false, "A known late-fold reference must not switch to the earlier occurrence");
      assert.throws(() => apply(event, { mode: "display", start_time: "10:00" }), /Choose local-time planning/);
      assert.throws(() => apply({ ...event, icsReadOnly: true }, { mode: "plan" }), /read-only/);
      assert.equal(apply({ ...event, icsReadOnly: true }).next.icsReadOnly, true);
      const series = { ...event, wiederholung: { art: "weekly" }, icsRoundtrip: [...event.icsRoundtrip, "RRULE:FREQ=WEEKLY", "EXDATE:20261028T233047Z"] };
      assert.throws(() => apply(series, { mode: "plan" }), /original recurrence data/);
      assert.deepEqual(Array.from(apply(series).next.icsRoundtrip), series.icsRoundtrip);
      const allDay = { ...event, zeit: "", icsRoundtrip: ["DTSTART;VALUE=DATE:20261022", "DTEND;VALUE=DATE:20261023"] };
      assert.throws(() => apply(allDay), /All-day dates/); assert.throws(() => apply(allDay, { mode: "plan" }), /All-day dates/);
      const floating = { ...event, datum: "2026-10-21", zeit: "23:30", icsRoundtrip: ["DTSTART:20261021T233047", "DTEND:20261022T003047"] };
      assert.throws(() => apply(floating), /floating local time/);
      assert.equal(apply(floating, { mode: "plan" }).view.start_utc_ms, Date.parse("2026-10-22T03:30:47Z"));
      const due = { id: "owned-due", faellig: "2026-10-22", faelligZeit: "01:30", icsAnzeigeZeitzone: "Europe/Berlin", icsRoundtrip: ["DUE:20261021T233047Z"] };
      const duePlan = apply(due, { mode: "plan" }, true);
      assert.equal(duePlan.next.startDatum, ""); assert.equal(duePlan.next.startZeit, ""); assert.equal(duePlan.view.start_utc_ms, null);
      assert.equal(duePlan.view.end_utc_ms, Date.parse("2026-10-22T05:30:47Z")); assert.ok(!duePlan.next.icsRoundtrip.some(line => /^DTSTART[;:]/.test(line)));
      const startOnly = { id: "owned-start", startDatum: "2026-10-22", startZeit: "01:30", faellig: "", faelligZeit: "", icsAnzeigeZeitzone: "Europe/Berlin", icsRoundtrip: ["DTSTART:20261021T233047Z"] };
      const startPlan = apply(startOnly, { mode: "plan" }, true);
      assert.equal(startPlan.next.faellig, ""); assert.equal(startPlan.view.end_utc_ms, null); assert.ok(!startPlan.next.icsRoundtrip.some(line => /^DUE[;:]/.test(line)));
      assert.equal(JSON.stringify(event), image, "Preparing either mode mutated the original record");
      const edited = JSON.parse(JSON.stringify(shown.next));
      b.t.daten().termine.push(edited);
      b.t.wendeTerminWerteAn(edited, { endZeit: "21:00" });
      const editView = apply(edited);
      assert.equal(editView.view.start_utc_ms, shown.view.start_utc_ms, "Editing the end shifted the unchanged start or dropped its seconds");
      assert.equal(editView.view.end_utc_ms, Date.parse("2026-10-22T01:00:00Z"), "Ordinary appointment editing lost the stored New York input context");
      const taskEdited = apply(due, {}, true).next;
      b.t.wendeAufgabenWerteAn(taskEdited, { faellig: "2026-10-22", faelligZeit: "21:00" }, true, false);
      assert.equal(apply(taskEdited, {}, true).view.end_utc_ms, Date.parse("2026-10-23T01:00:00Z"), "Ordinary task editing lost the stored input zone");
      const rejectedImage = JSON.stringify(edited);
      assert.throws(() => b.t.wendeTerminWerteAn(edited, { datum: "2026-03-08", zeit: "02:30", endDatum: "", endZeit: "04:00" }), /does not exist or is ambiguous/);
      assert.equal(JSON.stringify(edited), rejectedImage, "A rejected DST-gap edit partially mutated the appointment");
      const taskImage = JSON.stringify(taskEdited);
      assert.throws(() => b.t.wendeAufgabenWerteAn(taskEdited, { faellig: "2026-11-01", faelligZeit: "01:30" }, true, false), /does not exist or is ambiguous/);
      assert.equal(JSON.stringify(taskEdited), taskImage, "A rejected ambiguous task edit partially changed the record");
      const lateEdited = JSON.parse(JSON.stringify(late.next));
      b.t.daten().termine.push(lateEdited);
      b.t.wendeTerminWerteAn(lateEdited, { endZeit: "03:00" });
      assert.equal(apply(lateEdited).view.start_utc_ms, late.view.start_utc_ms, "End editing lost the known later-fold start");
      const floatingEdited = JSON.parse(JSON.stringify(floating));
      b.t.daten().termine.push(floatingEdited);
      b.t.wendeTerminWerteAn(floatingEdited, { endDatum: "2026-10-22", endZeit: "03:00" });
      assert.ok(floatingEdited.icsRoundtrip.includes("DTSTART:20261021T233047") && floatingEdited.icsRoundtrip.includes("DTEND:20261022T030000"), "Editing invented an absolute instant for a floating source");
      b.t.oeffneTerminBlatt(b.t.normalisiere({ termine: [edited] }).termine[0], edited.datum);
      assert.match(b.w.document.getElementById("tb-zeitzonen-kontext").textContent, /New York/, "Ordinary editor did not identify its saved input zone");
      console.log("ENTRY TIME ZONE PLAN PASS: same instant versus deliberate local clock, seconds, gaps/folds, UTC wire, raw metadata, readonly/series/all-day boundaries and task shapes " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
