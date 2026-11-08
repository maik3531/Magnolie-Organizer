"use strict";
// Refs #437: actual first save and two reopens, each in a fresh JS realm.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
const fixed = Date.UTC(2026, 10, 8, 12, 0, 0);

function saveAndClose(web, profile, first) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://welcome.test/", pretendToBeVisual: true
  });
  try {
    const w = dom.window, messages = [];
    w.eval(`{ const OriginalDate = Date; globalThis.Date = class extends OriginalDate {
      constructor(...args) { super(...(args.length ? args : [${fixed}])); }
      static now() { return ${fixed}; }
    }; }`);
    w.webkit = { messageHandlers: { bridge: { postMessage: text => messages.push(JSON.parse(text)) } } };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
    w.App.init({ daten: profile, neu: first, echterErststart: first, datenPfad: "/synthetic/welcome.magnolie",
      regional: { language: "en", timeZone: "UTC", formatLocale: "en-US" },
      trayVerfuegbar: false, handbuchInstalliert: true });
    w.App.vorBeenden();
    const save = messages.find(message => message.cmd === "speichern");
    assert.ok(save && Number.isInteger(save.id), "Native save request missing");
    assert.equal(messages.some(message => message.cmd === "beenden_bereit"), false, "Closed before native Save-ACK");
    w.App.gespeichert({ id: save.id, ok: true });
    assert.ok(messages.some(message => message.cmd === "beenden_bereit"), "Matching Save-ACK did not finish closing");
    return JSON.parse(save.text);
  } finally { dom.window.close(); }
}

for (const web of [path.resolve(__dirname, "../../magnolie-organizer/web"), path.resolve(__dirname, "../app/web")]) {
  try {
    const first = saveAndClose(web, {}, true);
    const second = saveAndClose(web, first, false);
    const third = saveAndClose(web, second, false);
    assert.equal(first.notizen.length, 1);
    assert.deepEqual(second, first, "First reopen changed the saved profile");
    assert.deepEqual(third, first, "Second reopen changed the saved profile");
    const existing = structuredClone(first);
    Object.assign(existing.notizen[0], { titel: "Synthetic existing note", text: "Keep existing content", html: "<p>Keep existing content</p>",
      angelegt: fixed - 86400000, angelegtGeschaetzt: false, personalGeaendert: fixed - 3600000 });
    assert.deepEqual(saveAndClose(web, existing, false), existing, "Existing canonical note was rewritten or replaced");
    for (const field of ["html", "symbol", "ursprungApp", "angelegt", "personalGeaendert", "angelegtGeschaetzt",
      "zusammenfuehrungen", "baumFreigabe", "baumGeaendert", "baumInhaltVersion", "baumVersion", "baumQuelle", "persoenlichVerknuepft"])
      assert.ok(Object.hasOwn(first.notizen[0], field), "First save lacks " + field);
    console.log("PASS welcome first save / two fresh-realm reopens:", web);
  } catch (error) {
    console.error(web, error);
    process.exitCode = 1;
  }
}
