"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const harnessPath = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module); harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", harnessPath);
(async () => {
  const locales = ["en", ...fs.readdirSync(path.resolve(__dirname, "../web/i18n")).filter(name => name.endsWith(".js")).map(name => name.slice(0, -3))];
  for (const web of harness.exports.roots) for (const locale of locales) {
    const data = { notizen: [{ id: "keep", titel: "Unchanged", text: "Original" }],
      einstellungen: { allgemein: { entwicklermodus: true }, ort: { land: "DE" } } };
    const b = await harness.exports.boot(web, data);
    try {
      const d = b.w.document;
      if (locale !== "en") { b.w.eval(fs.readFileSync(path.join(web, "i18n", locale + ".js"), "utf8")); b.w.MagnolieI18n.setLocale(locale); }
      if (locale === "en") {
        const now = Date.parse("2026-12-10T12:00:00Z");
        b.w.Date = class extends Date {
          constructor(...args) { super(...(args.length ? args : [now])); }
          static now() { return now; }
        };
        b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-ort").click();
        const country = d.querySelector("#ort-land");
        const selectCountry = value => {
          country.value = value;
          country.dispatchEvent(new b.w.Event("change", { bubbles: true }));
        };
        for (const [value, season] of [["ES", null], ["DE", "crystals"], ["ES", null], ["DE", "crystals"]]) {
          selectCountry(value);
          assert.equal(d.querySelector("#magnolie-saison")?.dataset.season || null, season,
            "Changing the saved country updates the actual background immediately");
        }
        for (const [date, land, motif] of [
          ["2026-10-03", "DE", "unity-gate"], ["2026-10-26", "AT", "neutrality-parliament"],
          ["2026-08-01", "CH", "swiss-lantern"], ["2026-07-14", "FR", "french-rosette"],
          ["2025-04-26", "NL", "kings-crown"], ["2026-07-21", "BE", "belgian-banner"],
          ["2026-06-23", "LU", "luxembourg-concert"]
        ]) {
          b.t.zustand().kalender.tag = date;
          await b.t.wechsel("aufgaben"); await b.t.wechsel("kalender");
          selectCountry(land);
          const watermarks = () => d.querySelectorAll(`.wo-tag[data-appearance-date="${date}"] [data-appearance-watermark]`);
          assert.equal(watermarks().length, 1);
          assert.equal(watermarks()[0].dataset.appearanceWatermark, motif);
          assert.equal(watermarks()[0].getAttribute("aria-hidden"), "true");
          selectCountry("ES");
          assert.equal(watermarks().length, 0);
        }
        selectCountry("DE");
      }
      b.t.zustand().kalender.tag = "2026-12-06";
      await b.t.wechsel("aufgaben"); await b.t.wechsel("kalender");
      assert(d.querySelector('.wo-tag[data-appearance-date="2026-12-06"] [data-appearance-watermark="boots"]'));
      b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-entwickler").click();
      assert(d.querySelector("#einst-seite-entwickler"));
      assert.equal(d.querySelector("#entwickler-darstellung"), null);
      assert.equal(d.querySelector("[data-appearance-native]"), null);
      assert(!b.messages.some(message => message.cmd.startsWith("tray_darstellung_test")));

      // Exercise the retained implementation in this disposable DOM only.
      const source = fs.readFileSync(path.join(web, "appearance.js"), "utf8");
      const enabledSource = source.replace("const SHOW_DEVELOPER_PREVIEW = false;", "const SHOW_DEVELOPER_PREVIEW = true;");
      assert.notEqual(enabledSource, source);
      b.w.eval(enabledSource);
      b.w.MagnolieAppearance.update({ today: "2026-12-06", country: "DE", developer: true, locked: false });
      b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-entwickler").click();
      const panel = d.querySelector("#entwickler-darstellung"); assert(panel && panel.textContent.includes("TEST"));
      const t = text => b.w.MagnolieI18n.gettext(text);
      assert(panel.textContent.includes(t("Visual test only; no connections or permissions are changed.")));
      assert.equal(panel.querySelector('[data-appearance-test="season"]').closest("label").firstChild.textContent, t("Seasonal background"));
      assert.equal(panel.querySelector('[data-appearance-test="holiday"] option[value="eggs"]').textContent, t("Easter eggs"));
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
      assert.equal(d.querySelectorAll("#magnolie-saison > svg").length, 34);
      assert.equal(d.querySelectorAll("#magnolie-saison > svg[data-season-accent]").length, 6);
      for (const image of d.querySelectorAll("#magnolie-saison > svg")) assert(parseInt(image.style.width, 10) <= 37);
      choose("season", "stars"); assert.equal(d.querySelector("#magnolie-saison").dataset.season, "stars");
      assert.equal(d.querySelectorAll("#magnolie-saison > svg[data-season-accent]").length, 6);
      choose("holiday", "santa"); assert(d.querySelector('.wo-tag [data-appearance-watermark="santa"]'));
      const holiday = panel.querySelector('[data-appearance-test="holiday"]');
      const sample = panel.querySelector('[data-appearance-sample="watermark"]');
      for (const [motif, country] of [
        ["unity-gate", "Germany"], ["neutrality-parliament", "Austria"], ["swiss-lantern", "Switzerland"],
        ["french-rosette", "France"], ["kings-crown", "Netherlands"],
        ["belgian-banner", "Belgium"], ["luxembourg-concert", "Luxembourg"]
      ]) {
        assert.equal(holiday.querySelector(`option[value="${motif}"]`)?.textContent, t(country));
        choose("holiday", motif);
        assert.equal(sample.querySelector("svg")?.dataset.appearanceWatermark, motif);
        assert(d.querySelector(`.wo-tag [data-appearance-watermark="${motif}"]`));
      }
      choose("holiday", "unknown");
      assert.equal(sample.querySelector("svg")?.dataset.appearanceWatermark, "luxembourg-concert");
      choose("date", "2026-12-06");
      choose("holiday", "auto");
      assert.equal(sample.querySelector("svg")?.dataset.appearanceWatermark, "boots");
      assert(d.querySelector("#magnolie-test-hinweis"));
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves); assert.equal(b.messages.length, messages,
        "Visual developer controls must never send native connection, sync, camera or permission commands");
      panel.querySelector("button").click(); assert.equal(d.querySelector("#magnolie-test-hinweis"), null);
      const nativeButton = panel.querySelector('[data-appearance-native="true"]'); assert(nativeButton);
      assert.equal(nativeButton.textContent, "TEST · " + t("OS tray icon (60 s)"));
      const nativeBefore = b.messages.length; nativeButton.click();
      assert.equal(b.messages.length, nativeBefore + 1);
      assert.equal(b.messages.at(-1).cmd, "tray_darstellung_test");
      assert.deepEqual(Object.keys(b.messages.at(-1)).sort(), ["cmd", "connection", "mode", "sync"]);
      assert.equal(JSON.stringify(b.t.daten()), before);
      b.w.App.trayDarstellungTestStand({ ok: false, active: false });
      assert.equal(panel.querySelector('[data-appearance-native-status]').textContent, "TEST · " + t("Saved developer mode is required."));
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
