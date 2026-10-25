"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "aktualisiereLandFlagge, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { einstellungen: { ort: { land: "DE", region: "DE-BW", feiertage: true } }, termine: [{ id: "owned-flag-event", datum: "2030-01-02", titel: "Keep" }] });
    try {
      if (b.saves().length) b.ack(); const records = JSON.stringify([b.t.daten().termine, b.t.daten().kontakte]);
      b.t.oeffneEinstellungen(); b.w.document.getElementById("einst-tab-ort").click();
      const flag = b.w.document.getElementById("ort-land-flagge"), country = b.w.document.getElementById("ort-land");
      assert.ok(flag && country); assert.equal(flag.dataset.land, "DE"); assert.equal(flag.hidden, false); assert.equal(flag.style.backgroundPosition, "-112px -63px");
      assert.equal(flag.getAttribute("aria-hidden"), "true");
      assert.equal(country.closest(".formzeile").querySelector("label").control, country, "Flag decoration broke the country label's control binding");
      const beforeDecoration = JSON.stringify(b.t.daten()), saves = b.saves().length;
      b.t.aktualisiereLandFlagge(flag, "ZZ"); assert.equal(flag.hidden, true); assert.equal(flag.dataset.land, "");
      b.t.aktualisiereLandFlagge(flag, "DE"); assert.equal(JSON.stringify(b.t.daten()), beforeDecoration); assert.equal(b.saves().length, saves);
      country.value = "AT"; country.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.equal(flag.dataset.land, "AT"); assert.equal(flag.style.backgroundPosition, "-532px 0px"); assert.equal(b.t.daten().einstellungen.ort.land, "AT");
      country.value = ""; country.dispatchEvent(new b.w.Event("change", { bubbles: true })); assert.equal(flag.hidden, true); assert.equal(b.t.daten().einstellungen.ort.land, "");
      assert.equal(JSON.stringify([b.t.daten().termine, b.t.daten().kontakte]), records);
      assert.ok(!b.messages.some(message => /flag|country.*image/i.test(message.cmd)), "Decorative flags emitted a native or external image request");
      console.log("COUNTRY FLAGS UI PASS: local ISO artwork, immediate selection changes, empty/invalid handling, accessible label and unchanged record/source data " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
