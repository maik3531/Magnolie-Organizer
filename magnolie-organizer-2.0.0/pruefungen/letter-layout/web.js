"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../../..");
const cases = JSON.parse(fs.readFileSync(process.argv[2] || path.join(__dirname, "contacts.json"), "utf8"));
const bridgeCases = {};

(async () => {
  for (const web of ["magnolie-organizer-2.0.0/web", "Magnolie-Organizer-Windows-2.0.0/app/web"]) {
    for (const saved of [undefined, "", "compact", "kompakt", "din5008", "din5008-a", "din5008-b"]) {
      const dom = new JSDOM(fs.readFileSync(path.join(root, web, "index.html"), "utf8"), {
        runScripts: "outside-only", url: "https://letter-test.invalid", pretendToBeVisual: true
      });
      const w = dom.window, messages = [];
      w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 0;
      w.HTMLElement.prototype.scrollIntoView = () => {};
      w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.__MAGNOLIE_BRUECKE__ = "nativeBridge";
      w.webkit = { messageHandlers: { nativeBridge: { postMessage: value => messages.push(JSON.parse(value)) } } };
      w.eval(fs.readFileSync(path.join(root, web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(root, web, "anwendung.js"), "utf8"));
      w.App.init({ daten: { kontakte: [{ id: "test", nachname: "Example", strasse: "Testweg 1", ort: "Teststadt" }],
        einstellungen: { adressen: { brief: true, briefLayout: saved, briefLayoutVoreinstellung: 2 } } },
        neu: false, regional: { language: "en", timeZone: "UTC" } });
      const t = w.OrganizerTest, expected = saved === "kompakt" ? "compact" : saved || "din5008-b";
      assert.equal(t.leereDaten().einstellungen.adressen.briefLayout, "din5008-b");
      assert.equal(t.daten().einstellungen.adressen.briefLayout, expected);
      assert.equal(t.normalisiere(JSON.parse(JSON.stringify(t.daten()))).einstellungen.adressen.briefLayout, expected);
      t.baueEinstellungen();
      w.document.querySelector("#einst-tab-adressen").click();
      const select = w.document.querySelector("#adressen-brief-layout");
      assert.equal(select.value, expected);
      select.dispatchEvent(new w.Event("change", { bubbles: true }));
      assert.equal(t.daten().einstellungen.adressen.briefLayout, expected);
      t.zustand().adressen.buchstabe = "E";
      t.zustand().adressen.auswahlId = "test";
      await t.wechsel("adressen");
      const button = w.document.querySelector('[title="Open this address as a letter in LibreOffice"]');
      assert.ok(button, web); button.click();
      assert.equal(messages.filter(message => message.cmd === "brief").at(-1).layout, expected);
      select.value = "din5008-a";
      select.dispatchEvent(new w.Event("change", { bubbles: true }));
      t.speichereJetzt();
      const save = messages.filter(message => message.cmd === "speichern").at(-1);
      assert.equal(JSON.parse(save.text).einstellungen.adressen.briefLayout, "din5008-a");
      dom.window.close();
    }
    console.log(web + ": seven default/persisted/dialog/nativeBridge letter cases passed");
    const platform = web.startsWith("magnolie-") ? "linux" : "windows";
    bridgeCases[platform] = [];
    for (const item of cases) {
      const dom = new JSDOM(fs.readFileSync(path.join(root, web, "index.html"), "utf8"), {
        runScripts: "outside-only", url: "https://letter-test.invalid", pretendToBeVisual: true
      });
      const w = dom.window, messages = [];
      w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 0;
      w.HTMLElement.prototype.scrollIntoView = () => {};
      w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.__MAGNOLIE_BRUECKE__ = "nativeBridge";
      w.webkit = { messageHandlers: { nativeBridge: { postMessage: value => messages.push(JSON.parse(value)) } } };
      w.eval(fs.readFileSync(path.join(root, web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(root, web, "anwendung.js"), "utf8"));
      w.App.init({ daten: { kontakte: [
        { id: "decoy", nachname: "Decoy", strasse: "Otherway 99", ort: "Elsewhere" },
        { ...item.contact, id: "selected" }
      ], einstellungen: { adressen: { brief: true, absender: item.sender, briefLayout: item.layout } } },
        neu: false, regional: { language: "en", formatLocale: item.culture, timeZone: "UTC" } });
      const t = w.OrganizerTest, before = JSON.stringify(t.daten().kontakte);
      const selected = t.daten().kontakte.find(k => k.id === "selected");
      t.zustand().adressen.suche = selected.ort;
      t.zustand().adressen.auswahlId = "decoy";
      await t.wechsel("adressen");
      const row = w.document.querySelector(".zeilen-aktion");
      assert.ok(row, item.id); row.click();
      assert.equal(t.zustand().adressen.auswahlId, "selected", item.id);
      const button = w.document.querySelector('[title="Open this address as a letter in LibreOffice"]');
      assert.ok(button, item.id); button.click();
      const message = messages.filter(message => message.cmd === "brief").at(-1);
      assert.equal(message.kontakt.id, "selected");
      assert.equal(message.absender, item.sender);
      assert.equal(message.layout, item.layout === "kompakt" ? "compact" : item.layout || "din5008-b");
      assert.equal(JSON.stringify(t.daten().kontakte), before, "Letter must not modify the contact");
      bridgeCases[platform].push({ ...item, contact: message.kontakt, sender: message.absender, layout: message.layout });
      dom.window.close();
    }
    console.log(web + ": " + cases.length + " selected-contact letter payloads passed");
  }
  if (process.argv[3]) fs.writeFileSync(process.argv[3], JSON.stringify(bridgeCases, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
