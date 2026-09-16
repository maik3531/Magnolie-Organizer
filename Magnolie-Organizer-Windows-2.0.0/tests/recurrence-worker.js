"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { Worker } = require("node:worker_threads");
const { JSDOM } = require("jsdom");

(async () => {
  const linuxWeb = path.join(process.env.MAGNOLIE_LINUX_SOURCE || path.resolve(__dirname, "../../magnolie-organizer-2.0.0"), "web");
  const webRoots = [path.resolve(__dirname, "../app/web")];
  if (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linuxWeb)) webRoots.unshift(linuxWeb);
  for (const web of webRoots) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), { runScripts: "outside-only", url: "https://recurrence.test/", pretendToBeVisual: true });
    const w = dom.window, blobs = new Map(), workers = [];
    w.Blob = class { constructor(parts) { this.source = parts.join(""); } };
    w.URL.createObjectURL = blob => { const id = "blob:" + blobs.size; blobs.set(id, blob.source); return id; };
    w.URL.revokeObjectURL = id => blobs.delete(id);
    w.Worker = class {
      constructor(url) {
        this.worker = new Worker('const { parentPort } = require("node:worker_threads"); globalThis.self = globalThis; self.postMessage = value => parentPort.postMessage(value); parentPort.on("message", data => self.onmessage({ data }));\n' + blobs.get(url), { eval: true });
        workers.push(this.worker);
        this.worker.on("message", data => this.onmessage?.({ data }));
        this.worker.on("error", error => this.onerror?.(error));
      }
      postMessage(value) { this.worker.postMessage(value); }
      terminate() { this.worker.terminate(); }
    };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
    await new Promise(resolve => setImmediate(resolve));
    w.App.init({ daten: {}, neu: true, regional: { language: "en", timeZone: "UTC" } });
    const T = w.OrganizerTest;
    async function query(mode, item, args, error = false) {
      let ticks = 0;
      const clock = setInterval(() => ticks++, 2);
      try {
        assert.equal(T.icsRuntime(mode, item, args), null, "The UI must receive pending, not a partial result");
        assert.equal(w.document.body.dataset.recurrenceState, "pending");
        assert.equal(w.document.body.getAttribute("aria-busy"), "true");
        assert.equal(T.icsRuntime.state.progress.hidden, false, "Pending expansion must have visible progress");
        const start = Date.now();
        while ([...T.icsRuntime.state.jobs.values()].some(v => v.status === "pending")) {
          assert.ok(Date.now() - start < 90000, "Worker completion timeout");
          await new Promise(resolve => setTimeout(resolve, 10));
        }
        assert.ok(ticks > 0, "The main event loop did not advance");
        const result = T.icsRuntime(mode, item, args);
        assert.equal(w.document.body.getAttribute("aria-busy"), "false");
        assert.equal(T.icsRuntime.state.progress.hidden, true);
        if (error) { assert.equal(result, null); assert.equal(w.document.body.dataset.recurrenceState, "error"); }
        else assert.ok(result, "Worker failed: " + T.icsRuntime.lastError);
        return result;
      } finally { clearInterval(clock); }
    }
    try {
      const item = { uid: "dense-old", datum: "2021-03-01", zeit: "09:00", icsRoundtrip: ["DTSTART;TZID=Europe/Berlin:20210301T090000", "DURATION:PT1S", "RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=400000"] };
      const result = await query("expand", item, [Date.parse("2026-09-07T07:00:00Z"), Date.parse("2026-09-07T07:20:00Z")]);
      assert.deepEqual(result.map(v => new Date(v.icsStartUtc).toISOString()), ["2026-09-07T07:00:00.000Z", "2026-09-07T07:10:00.000Z", "2026-09-07T07:20:00.000Z"]);
      const task = { uid: "two-year", startDatum: "2026-01-05", faellig: "2026-01-06", icsRoundtrip: ["DTSTART:20260105T090000Z", "DUE:20260106T170000Z", "RRULE:FREQ=YEARLY;INTERVAL=2;COUNT=3"] };
      assert.equal((await query("next", task, ["2026-02-01"])).startDatum, "2028-01-05");
      const overlapping = { uid: "long-next", startDatum: "1998-01-05", faellig: "1998-01-05", icsRoundtrip: ["DTSTART:19980105T090000Z", "DUE:19980105T100000Z", "RRULE:FREQ=WEEKLY", "RDATE;VALUE=PERIOD:20260801T090000Z/PT960H"] };
      assert.equal((await query("next", overlapping, ["2026-09-07"])).faellig, "2026-09-07", "Next due beats the older, longer PERIOD");
      w.App.init({ daten: {}, neu: true, regional: { language: "en", timeZone: "system" } });
      const system = await query("expand", { icsRoundtrip: ["DTSTART:20260907T090000Z", "DURATION:PT1H"] }, [Date.parse("2026-09-07"), Date.parse("2026-09-08")]);
      assert.equal(system[0].zeit, new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date("2026-09-07T09:00:00Z")), "System means the host timezone, not UTC");
      w.App.init({ daten: { termine: [{ uid: "preview", titel: "Worker preview", datum: "2026-09-07", zeit: "09:00", endZeit: "10:00", icsRoundtrip: ["DTSTART:20260907T090000Z", "DURATION:PT1H", "RRULE:FREQ=DAILY;COUNT=3"] }] }, neu: true, regional: { language: "en", timeZone: "UTC" } });
      assert.equal(T.termineAm("2026-09-07", true).length, 0);
      assert.equal(w.document.body.dataset.recurrenceState, "pending", "An unfinished calendar query must not report empty success");
      assert.equal(T.icsRuntime.state.progress.hidden, false);
      T.zustand().planer.jahr = 2026; T.zustand().kalender.monat = 8;
      const preview = T.oeffneDruckvorschau(null, "planer"), layout = preview.querySelector("#planer-druck-art");
      layout.value = "month"; layout.dispatchEvent(new w.Event("change"));
      assert.equal(preview.querySelector(".ods-knopf").disabled, true, "Pending recurrence must not become a partial export");
      const deadline = Date.now() + 30000;
      while ([...T.icsRuntime.state.jobs.values()].some(v => v.status === "pending")) {
        assert.ok(Date.now() < deadline, "Preview completion timeout");
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      assert.equal(preview.querySelector(".ods-knopf").disabled, false, "The completed preview must become exportable");
      assert.equal(T.termineAm("2026-09-07", true).filter(t => t.uid === "preview").length, 1,
        "The settled calendar must display the previously pending occurrence");
      const model = T.planerMonatsModell(2026, 8);
      assert.equal(model.wochen.flatMap(v => v.tage).flatMap(v => v.eintraege).filter(v => v.art === "termin").length, 3);
      preview.querySelector('button[title="Close"]').click();
      await query("expand", { icsRoundtrip: ["DTSTART:20260907T000000Z", "DURATION:PT1S", "RRULE:FREQ=SECONDLY"] }, [Date.parse("2026-09-07"), Date.parse("2026-09-10")], true);
      assert.ok(T.icsRuntime.lastError.includes("limit"));
      T.daten().termine = T.normalisiere({ termine: [{ id: "simple", datum: "2026-01-08", titel: "Local second Thursday",
        wiederholung: { art: "monthly", ordinal: 2, wochentag: "TH" } }] }).termine;
      T.planeSpeichern();
      const workerCount = workers.length;
      assert.equal(T.termineAm("2026-02-12", true).filter(v => v.id === "simple").length, 1,
        "Local simple recurrences must retain their synchronous fast path");
      assert.equal(workers.length, workerCount);
      const stored = JSON.stringify(T.daten()), originalWorker = w.Worker, originalUrl = w.URL.createObjectURL;
      for (const failure of ["url", "constructor", "postMessage"]) {
        T.icsRuntime.state.worker?.terminate();
        T.icsRuntime.state = undefined;
        delete w.document.body.dataset.recurrenceState;
        w.document.body.removeAttribute("aria-busy");
        w.URL.createObjectURL = failure === "url" ? () => { throw new Error("URL creation unavailable"); } : originalUrl;
        w.Worker = class {
          constructor() { if (failure === "constructor") throw new Error("unavailable"); }
          postMessage() { throw new Error("structured clone failed"); }
          terminate() {}
        };
        let ready = 0;
        const settled = () => ready++;
        w.document.addEventListener("magnolie-recurrence-ready", settled);
        assert.equal(T.icsRuntime("expand", item, [Date.parse("2026-09-07"), Date.parse("2026-09-08")]), null);
        assert.equal(w.document.body.dataset.recurrenceState, "error", failure + " must not look like an empty successful calendar");
        assert.equal(w.document.body.getAttribute("aria-busy"), "false", failure + " left an endless busy state");
        assert.ok(!T.icsRuntime.state.progress || T.icsRuntime.state.progress.hidden);
        assert.equal(ready, 1, "Failure must settle waiting previews");
        assert.ok(w.document.querySelector("#zettel").textContent.includes("original calendar data was preserved"));
        assert.equal(JSON.stringify(T.daten()), stored);
        w.document.removeEventListener("magnolie-recurrence-ready", settled);
      }
      w.URL.createObjectURL = originalUrl;
      T.icsRuntime.state = undefined;
      let constructed = 0, terminated = 0;
      w.Worker = class {
        constructor() { constructed++; }
        postMessage() {}
        terminate() { terminated++; }
      };
      assert.equal(T.icsRuntime("expand", item, [0, 1]), null);
      T.icsRuntime.state.worker.onerror(new Error("worker crashed"));
      assert.equal(T.icsRuntime.state.worker, null, "A dead worker must not be reused for new jobs");
      assert.equal(w.document.body.dataset.recurrenceState, "error");
      assert.equal(w.document.body.getAttribute("aria-busy"), "false");
      assert.equal(terminated, 1);
      assert.equal(T.icsRuntime("expand", item, [1, 2]), null);
      assert.equal(constructed, 2, "A new query after a crash needs a live worker");
      T.icsRuntime.state.worker.onerror(new Error("worker crashed again"));
      T.icsRuntime.state = undefined;
      w.Worker = undefined;
      assert.equal(T.icsRuntime("expand", { icsRoundtrip: ["DTSTART:20260907T090000Z", "RRULE:FREQ=INVALID"] }, [0, 1]), null);
      assert.equal(w.document.body.dataset.recurrenceState, "error", "Synchronous fallback failure must not become empty success");
      assert.equal(w.document.body.getAttribute("aria-busy"), "false");
      assert.equal(JSON.stringify(T.daten()), stored);
      w.Worker = originalWorker;
    } finally { for (const worker of workers) await worker.terminate(); dom.window.close(); }
  }
  process.stdout.write(`RECURRENCE WORKERS PASSED (${webRoots.length} packaged/source web roots)\n`);
})().catch(error => { console.error(error); process.exitCode = 1; });
