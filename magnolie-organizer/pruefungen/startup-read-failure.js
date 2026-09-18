"use strict";

// Actual complete Linux frontend; no native window, network or user storage.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../web");
const tick = () => new Promise(resolve => setImmediate(resolve));
const locales = ["en.js", ...fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"))];
assert.equal(locales.length, 20);

(async () => {
  let cases = 0;
  for (const locale of locales) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      runScripts: "outside-only", url: "https://startup-test.invalid/", pretendToBeVisual: true
    });
    try {
      const w = dom.window, sent = [];
      w.setTimeout = () => 0; w.clearTimeout = () => {};
      w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
      w.HTMLElement.prototype.scrollIntoView = () => {};
      w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.__MAGNOLIE_BRUECKE__ = "startupTest";
      w.webkit = { messageHandlers: { startupTest: { postMessage: text => sent.push(JSON.parse(text)) } } };
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      if (locale !== "en.js") w.eval(fs.readFileSync(path.join(web, "i18n", locale), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
      await tick();
      const regional = { language: locale.slice(0, -3), timeZone: "UTC" };
      w.MagnolieI18n.setLocale(regional.language);
      const error = w.MagnolieI18n.gettext("The file could not be read.");
      const fail = () => w.App.init({ gesperrt: true, neu: false, ladeFehler: error, regional });
      const saves = () => sent.filter(message => message.cmd === "speichern");
      const test = w.OrganizerTest;
      fail();
      assert.equal(w.document.querySelector("#dialog-text").textContent, error);
      assert.equal(w.document.querySelector("#status-speicher").textContent, error);
      assert.equal(w.document.querySelector("#dialog-ja").textContent, w.MagnolieI18n.gettext("Refresh"));
      assert.equal(w.document.querySelector("#dialog-nein").textContent, w.MagnolieI18n.gettext("Close"));
      assert.equal(w.document.querySelector("#schreibtisch").hasAttribute("inert"), true);
      assert.equal(w.document.querySelector("#sperr-schleier"), null, "No password prompt for an I/O error");
      test.speichereJetzt(); w.App.vorBeenden(); await tick();
      assert.equal(saves().length, 0);
      assert.ok(sent.some(message => message.cmd === "beenden_bereit"));
      cases++;

      w.document.querySelector("#dialog-ja").click(); await tick();
      assert.equal(sent.at(-1).cmd, "bereit", "Retry uses the existing startup route");
      fail();
      test.speichereJetzt(); assert.equal(saves().length, 0);
      w.document.querySelector("#dialog-ja").click(); await tick();
      const actual = { notizen: [{ id: "actual", titel: "Actual data", text: "keep", html: "keep" }],
        termine: [{ id: "event", titel: "Actual event", datum: "2026-09-13" }] };
      w.App.init({ daten: actual, neu: false, regional });
      assert.equal(w.document.querySelector("#status-speicher").textContent, "");
      assert.equal(w.document.querySelector("#schreibtisch").hasAttribute("inert"), false);
      assert.equal(w.document.querySelector("#dialog-schleier").classList.contains("verborgen"), true);
      assert.equal(test.daten().notizen[0].id, "actual");
      test.speichereJetzt();
      const saved = saves().at(-1);
      assert.ok(saved);
      assert.equal(JSON.parse(saved.text).notizen[0].text, "keep");
      assert.equal(JSON.parse(saved.text).termine[0].id, "event");
      w.App.gespeichert({ id: saved.id, ok: true });
      cases++;

      fail(); w.document.querySelector("#dialog-nein").click(); await tick();
      assert.equal(sent.at(-1).cmd, "beenden");
      const count = saves().length;
      test.speichereJetzt(); assert.equal(saves().length, count);
      cases++;

      w.App.init({ daten: {}, neu: false, regional });
      assert.equal(test.daten().notizen.length, 0, "Deliberately empty object stays valid and empty");
      assert.equal(w.document.querySelector("#schreibtisch").hasAttribute("inert"), false);
      assert.equal(w.document.querySelector("#dialog-schleier").classList.contains("verborgen"), true);
      test.speichereJetzt(); assert.ok(saves().length > count);
      w.App.gespeichert({ id: saves().at(-1).id, ok: true });
      cases++;

      w.App.init({ daten: null, neu: true, echterErststart: true, regional });
      assert.equal(test.daten().notizen.length, 1, "Only a genuinely new book gets the welcome note");
      test.speichereJetzt(); assert.equal(JSON.parse(saves().at(-1).text).notizen.length, 1);
      cases++;
    } finally { dom.window.close(); }
  }
  console.log(`Startup read failure: ${cases} cases passed across ${locales.length} locales.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
