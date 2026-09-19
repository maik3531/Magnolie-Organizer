"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { Worker } = require("node:worker_threads");
const { JSDOM } = require("jsdom");
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const roots = process.argv.includes('--windows') ? [path.resolve(__dirname, '../app/web')] :
    [path.resolve(__dirname, "../../magnolie-organizer/web"), path.resolve(__dirname, "../app/web")];
  for (const web of roots.filter(root => fs.existsSync(root))) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"),
      { runScripts: "outside-only", url: "https://month-recurrence.test/", pretendToBeVisual: true });
    const w = dom.window, blobs = new Map(), workers = [], submissions = new Map();
    let sent = 0, duplicates = 0, workerError;
    w.Blob = class { constructor(parts) { this.source = parts.join(""); } };
    w.URL.createObjectURL = blob => { const key = "blob:" + blobs.size; blobs.set(key, blob.source); return key; };
    w.URL.revokeObjectURL = key => blobs.delete(key);
    w.Worker = class {
      constructor(url) {
        this.worker = new Worker('const { parentPort } = require("node:worker_threads"); globalThis.self = globalThis; self.postMessage = value => parentPort.postMessage(value); parentPort.on("message", data => self.onmessage({ data }));\n' + blobs.get(url), { eval: true });
        workers.push(this.worker);
        this.worker.on("message", data => this.onmessage?.({ data }));
        this.worker.on("error", error => { workerError = error; this.onerror?.(error); });
      }
      postMessage(value) {
        sent++;
        if (submissions.has(value.key)) duplicates++;
        submissions.set(value.key, (submissions.get(value.key) || 0) + 1);
        // Stop feeding an already proven runaway loop; never leave a test worker unbounded.
        if (sent <= 5000) this.worker.postMessage(value);
      }
      terminate() { return this.worker.terminate(); }
    };
    try {
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
      w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
      await wait(0);
      w.App.init({ daten: {}, neu: true, regional: { language: "en", timeZone: "UTC" } });
      const T = w.OrganizerTest;
      await T.wechsel("notizen");
      T.daten().termine = T.normalisiere({ termine: Array.from({ length: 32 }, (_, index) => ({
        id: "series-" + index, uid: "series-" + index + "@example.invalid", titel: "Recurring " + index,
        datum: "2027-01-01", zeit: "09:00", endZeit: "10:00",
        icsRoundtrip: ["DTSTART:20270101T090000Z", "DURATION:PT1H", "RRULE:FREQ=WEEKLY;COUNT=52"]
      })) }).termine;
      T.daten().einstellungen.allgemein.wetter = false;
      Object.assign(T.zustand().kalender, { jahr: 2027, monat: 0, tag: "2027-01-15", ansicht: "month", uebersichtAb: null });
      T.planeSpeichern();
      const stored = JSON.stringify(T.daten().termine);
      await T.wechsel("kalender");
      const summary = () => JSON.stringify({ sent, duplicates, unique: submissions.size,
        rows: w.document.querySelectorAll(".termin-uebersicht .ue-termin").length,
        busy: w.document.body.getAttribute("aria-busy"), error: T.icsRuntime.lastError,
        section: T.zustand().sektion, year: T.zustand().kalender.jahr, month: T.zustand().kalender.monat });
      async function settle(expectedRows) {
        const deadline = Date.now() + 12000;
        let stableSince = 0, previousSent = -1;
        while (Date.now() < deadline && sent <= 5000) {
          await wait(25);
          if (workerError) throw workerError;
          const state = T.icsRuntime.state;
          const pending = [...(state?.jobs.values() || [])].some(job => job.status === "pending");
          const rows = w.document.querySelectorAll(".termin-uebersicht .ue-termin").length;
          if (!pending && !state?.paint && (expectedRows === undefined || rows === expectedRows) && sent === previousSent) {
            stableSince ||= Date.now();
            if (Date.now() - stableSince >= 200) return;
          } else stableSince = 0;
          previousSent = sent;
        }
        assert.fail("Calendar view did not converge: " + summary());
      }
      await settle(160);
      assert.ok(sent > 0, "The fixture must exercise actual asynchronous recurrence work");
      assert.equal(duplicates, 0, "Unchanged visible series were repeatedly submitted: " + summary());
      assert.equal(JSON.stringify(T.daten().termine), stored, "Rendering changed stored series");
      console.log("MONTH RECURRENCE STABLE " + web + " " + summary());

      await T.wechsel("notizen");
      T.daten().termine = T.normalisiere({ termine: [...T.daten().termine,
        { id: 'all-day', uid: 'all-day@example.invalid', titel: 'All-day series', datum: '2027-01-07',
          icsRoundtrip: ['DTSTART;VALUE=DATE:20270107', 'DURATION:P1D', 'RRULE:FREQ=WEEKLY;COUNT=4'] },
        { id: 'spanning', uid: 'spanning@example.invalid', titel: 'Spanning series', datum: '2027-01-14',
          zeit: '23:00', endDatum: '2027-01-16', endZeit: '01:00',
          icsRoundtrip: ['DTSTART:20270114T230000Z', 'DURATION:PT26H', 'RRULE:FREQ=WEEKLY;COUNT=3'] }
      ] }).termine;
      T.planeSpeichern();
      const mixedStored = JSON.stringify(T.daten().termine);
      await T.wechsel("kalender");
      await settle(173);
      assert.equal(w.document.querySelectorAll('.ue-termin .ue-titel').length, 173);

      w.document.querySelector('button[aria-label="Next month"]').click();
      await settle(128);
      T.zustand().kalender.tag = '2027-02-12';
      for (const view of ['week', 'day']) {
        w.document.querySelector(`[data-ansicht="${view}"]`).click();
        await settle();
        assert.equal(T.zustand().kalender.ansicht, view);
        assert.equal(T.termineAm('2027-02-12', true).length, 32, view + ' lost the Friday occurrences');
      }
      assert.equal(JSON.stringify(T.daten().termine), mixedStored, 'Navigation changed stored recurrence definitions');
      await T.wechsel("notizen");
      assert.equal(T.zustand().sektion, "notizen");
      console.log('MONTH RECURRENCE SEMANTICS PASSED: all-day, multi-day, month/week/day navigation and stored data: ' + web);
    } finally {
      await Promise.all(workers.map(worker => worker.terminate()));
      dom.window.close();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
