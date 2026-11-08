"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const harnessPath = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module); harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", harnessPath);
(async () => {
  for (const web of harness.exports.roots) for (const locale of ["en", "de"]) {
    const b = await harness.exports.boot(web, { notizen: [{ id: "keep", titel: "Unchanged", text: "Original" }],
      einstellungen: { allgemein: { entwicklermodus: true } } });
    try {
      const d = b.w.document;
      if (locale === "de") { b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8")); b.w.MagnolieI18n.setLocale("de"); }
      b.t.zustand().kalender.tag = "2026-12-06";
      await b.t.wechsel("aufgaben"); await b.t.wechsel("kalender");
      assert(d.querySelector('.wo-tag[data-appearance-date="2026-12-06"] [data-appearance-watermark="boots"]'));
      b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-entwickler").click();
      const panel = d.querySelector("#entwickler-darstellung"); assert(panel && panel.textContent.includes("TEST"));
      assert(panel.textContent.includes(locale === "de" ? "Verbindungen und Berechtigungen bleiben unverändert" : "no connections or permissions are changed"));
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length, messages = b.messages.length;
      function choose(key, value) {
        const input = panel.querySelector(`[data-appearance-test="${key}"]`); input.value = value; input.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      }
      for (const value of ["none", "notes", "kde", "both"]) {
        choose("connected", value); assert.equal(panel.querySelector('[data-appearance-sample="tray"] svg').dataset.connection, value);
      }
      choose("mode", "camera"); assert(panel.querySelector('[data-appearance-shape="camera"]')); assert(!panel.querySelector('[data-appearance-shape="flower"]'));
      panel.querySelector('[data-appearance-test="sync"]').click(); assert(panel.querySelector('[data-appearance-shape="sync"]'));
      choose("mode", "phone"); assert.equal(panel.querySelector('[data-appearance-sample="tray"] svg').dataset.mode, "phone");
      choose("season", "crystals"); assert.equal(d.querySelector("#magnolie-saison").dataset.season, "crystals");
      assert.equal(d.querySelectorAll("#magnolie-saison > svg").length, 28);
      for (const image of d.querySelectorAll("#magnolie-saison > svg")) assert(parseInt(image.style.width, 10) <= 37);
      choose("season", "stars"); assert.equal(d.querySelector("#magnolie-saison").dataset.season, "stars");
      choose("holiday", "santa"); assert(d.querySelector('.wo-tag [data-appearance-watermark="santa"]'));
      assert(d.querySelector("#magnolie-test-hinweis"));
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves); assert.equal(b.messages.length, messages,
        "Visual developer controls must never send native connection, sync, camera or permission commands");
      panel.querySelector("button").click(); assert.equal(d.querySelector("#magnolie-test-hinweis"), null);
      const nativeButton = panel.querySelector('[data-appearance-native="true"]'); assert(nativeButton);
      const nativeBefore = b.messages.length; nativeButton.click();
      assert.equal(b.messages.length, nativeBefore + 1);
      assert.equal(b.messages.at(-1).cmd, "tray_darstellung_test");
      assert.deepEqual(Object.keys(b.messages.at(-1)).sort(), ["cmd", "connection", "mode", "sync"]);
      assert.equal(JSON.stringify(b.t.daten()), before);
      b.w.App.trayDarstellungTestStand({ ok: false, active: false });
      assert(panel.querySelector('[data-appearance-native-status]').textContent.includes(locale === "de" ? "gespeichertem Entwicklermodus" : "Saved developer mode"));
      nativeButton.click(); b.w.App.trayDarstellungTestStand({ ok: true, active: true });
      assert(d.body.hasAttribute("data-appearance-test"));
      b.w.App.trayDarstellungTestStand({ ok: true, active: false });
      assert.equal(d.body.hasAttribute("data-appearance-test"), false, "Native expiry must remove the TEST marker without changing real state");
      nativeButton.click(); b.w.App.trayDarstellungTestStand({ ok: true, active: true });
      panel.querySelector("button").click(); assert.equal(b.messages.at(-1).cmd, "tray_darstellung_test_ende");
      assert(d.querySelector('.wo-tag[data-appearance-date="2026-12-06"] [data-appearance-watermark="boots"]'));
      choose("season", "stars");
      nativeButton.click(); b.w.App.trayDarstellungTestStand({ ok: true, active: true });
      b.w.App.init({ gesperrt: true });
      assert.equal(b.messages.at(-1).cmd, "tray_darstellung_test_ende");
      b.w.App.trayDarstellungTestStand({ ok: true, active: true });
      assert.equal(d.querySelector("#magnolie-test-hinweis"), null); assert.equal(d.querySelector("#magnolie-saison"), null);
      choose("season", "crystals"); assert.equal(d.querySelector("#magnolie-saison"), null, "Detached developer controls cannot revive a locked preview");
      b.w.App.init({ daten: JSON.parse(before), neu: false });
      b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-entwickler").click();
      const nextPanel = d.querySelector("#entwickler-darstellung");
      const seasonInput = nextPanel.querySelector('[data-appearance-test="season"]'); seasonInput.value = "stars"; seasonInput.dispatchEvent(new b.w.Event("change"));
      assert(d.body.hasAttribute("data-appearance-test"));
      const disable = [...d.querySelectorAll("#einst-seite-entwickler button")].find(button => button.textContent === b.w.MagnolieI18n.gettext("Disable developer mode"));
      assert(disable); disable.click();
      assert.equal(b.t.daten().einstellungen.allgemein.entwicklermodus, false);
      assert.equal(d.querySelector("#magnolie-test-hinweis"), null); assert.equal(d.body.hasAttribute("data-appearance-test"), false);
      console.log("Appearance UI PASS " + locale + " " + web + ": week watermark, developer icon/season selectors, size bound, no data/native effects, lock/disable reset.");
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
