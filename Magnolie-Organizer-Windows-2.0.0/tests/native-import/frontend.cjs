"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("../../node_modules/jsdom");
const root = path.resolve(__dirname, "../../..");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const web = path.join(root, input.platform === "windows"
  ? "Magnolie-Organizer-Windows-2.0.0/app/web" : "magnolie-organizer-2.0.0/web");
const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
  runScripts: "outside-only", url: "https://native-import.test/", pretendToBeVisual: true
});
const w = dom.window;
w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
w.App.init({ daten: w.JSON.parse(JSON.stringify(input.initial || {})), neu: true,
  regional: { language: "en", timeZone: "UTC" } });
for (const payload of input.payloads || []) w.App.importErgebnis(w.JSON.parse(JSON.stringify(payload)));
console.log(w.JSON.stringify(w.OrganizerTest.daten()));
dom.window.close();
