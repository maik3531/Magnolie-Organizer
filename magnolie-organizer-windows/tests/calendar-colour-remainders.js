"use strict";
// Real import callback, normalization, save payload/ACK and desktop redraws in
// JSDOM. Optional actual codec payloads extend this to a cross-runtime pipeline;
// neither mode claims a native GTK/WebView render or device synchronization.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const vectors = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/calendar-color-remainders.json"), "utf8"));
const native = process.env.MAGNOLIE_COLOR_NATIVE_INPUT && new Map(JSON.parse(fs.readFileSync(process.env.MAGNOLIE_COLOR_NATIVE_INPUT, "utf8")).map(value => [value.id, value.payload]));
const watchdog = setTimeout(() => { console.error("Calendar colour remainder test timed out"); process.exit(1); }, 60000);
(async () => {
  let failed = 0;
  for (const web of harness.exports.roots) {
    const results = [];
    for (const vector of vectors) {
      let b;
      try {
        const payload = native ? plain(native.get(vector.id)) : {
          art: "ics", abgebrochen: false, [vector.section]: [{ uid: vector.id,
            name: vector.id, titel: vector.id, datum: vector.expected_date, faellig: vector.expected_date,
            typ: vector.expected_type, akzentFarbe: vector.expected_accent, icsCalendarColor: "",
            icsRoundtrip: vector.preserve_line ? [vector.preserve_line] : [] }]
        };
        b = await harness.exports.boot(web);
        await b.w.App.importErgebnis(payload);
        const item = b.t.daten()[vector.section][0];
        assert.ok(item, "Import did not create the expected entry");
        assert.equal(item.akzentFarbe, vector.expected_accent);
        if (vector.section === "jahrestage") {
          assert.equal(item.typ, vector.expected_type); assert.equal(item.datum, vector.expected_date);
          assert.equal(b.t.daten().termine.length, 0, "Birthday was changed into an ordinary event");
          const iso = "2028-02-29", colour = vector.expected_accent;
          for (const view of ["month", "week", "day"]) {
            Object.assign(b.t.zustand().kalender, { jahr: 2028, monat: 1, tag: iso, ansicht: view });
            await b.t.wechsel("planer"); await b.t.wechsel("kalender");
            const selector = view === "month" ? ".jt-stern" : view === "week" ? ".wo-jt" : ".jt-kasten";
            const marker = [...b.w.document.querySelectorAll(selector)].find(value => value.textContent.includes("✱"));
            assert.ok(marker, view + ": anniversary symbol missing");
            const coloured = marker.dataset.akzentFarbe ? marker : marker.querySelector("[data-akzent-farbe]");
            assert.equal(coloured?.dataset.akzentFarbe || "", colour, view + ": visible accent differs");
            if (colour) assert.ok(coloured.style.color && coloured.style.backgroundColor, view + ": missing contrast pair");
          }
          const month = b.t.planerMonatsModell(2028, 1);
          const day = month.wochen.flatMap(week => week.tage).find(value => value.iso === iso);
          const annual = day.eintraege.find(value => value.art === "jahrestag");
          assert.equal(annual.farbe, colour || "#a66d8a");
          assert.equal(!!annual.akzent, !!colour);
          const year = b.t.planerKalenderModell(2028);
          assert.equal(year.zeilen[28][1].akzente.filter(value => value.art === "jahrestag").length, colour ? 1 : 0);
          // The real year view schedules two cancellable halves after paint.
          // The shared harness suppresses RAF/timers; execute those callbacks.
          const firstTimer = b.timers.length;
          b.w.requestAnimationFrame = callback => { callback(); return 0; };
          b.t.zustand().planer.jahr = 2028; await b.t.wechsel("planer");
          for (let index = firstTimer; index < b.timers.length; index++) {
            const timer = b.timers[index];
            if (!timer.cancelled && timer.delay === 0) timer.fn();
          }
          const bars = [...b.w.document.querySelectorAll(".mm-kategoriebalken")].filter(value => value.title === item.name);
          assert.equal(bars.length, colour ? 1 : 0, "year planner visible bars");
          await b.t.wechsel("jahrestage");
          const title = b.w.document.querySelector(".jahrestage-liste .obm");
          assert.equal(title?.dataset.akzentFarbe || "", colour);
        }
        b.t.speichereJetzt(); const save = b.saves().at(-1); assert.ok(save, "Actual save request missing");
        const book = JSON.parse(save.text); b.ack(); b.close(); b = undefined;
        b = await harness.exports.boot(web, book);
        assert.equal(b.t.daten()[vector.section][0].akzentFarbe, vector.expected_accent, "Saved book reload lost its colour");
        results.push({ id: vector.id, passed: true, book });
      } catch (error) {
        failed++; results.push({ id: vector.id, passed: false, error: error.message, stack: error.stack });
        console.error("FAIL " + web + ": " + vector.id + ": " + error.message);
      } finally { b?.close(); }
    }
    if (process.env.MAGNOLIE_COLOR_UI_OUTPUT) {
      fs.mkdirSync(process.env.MAGNOLIE_COLOR_UI_OUTPUT, { recursive: true });
      fs.writeFileSync(path.join(process.env.MAGNOLIE_COLOR_UI_OUTPUT, web.includes("magnolie-organizer-windows") ? "windows.json" : "linux.json"), JSON.stringify(results, null, 2) + "\n");
    }
    console.log("CALENDAR COLOUR REMAINDERS " + results.filter(value => value.passed).length + "/" + results.length + " " + web + (native ? " actual native codec payloads" : " UI model fixtures"));
  }
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
