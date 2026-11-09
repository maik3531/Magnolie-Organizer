"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), assert = require("node:assert/strict");
const roots = [path.resolve(__dirname, "../web"), path.resolve(__dirname, "../../magnolie-organizer-windows/app/web")];
const keys = ["Visual test only; no connections or permissions are changed.", "Tray preview", "Seasonal background", "Holiday watermark", "Both connected", "Camera", "Snowflakes", "Stars", "Boots", "Santa Claus", "Rocket", "Champagne glass", "Easter eggs", "Reset preview", "OS tray icon (60 s)", "Saved developer mode is required."];
const languages = fs.readdirSync(path.join(roots[0], "i18n")).filter(name => name.endsWith(".js")).sort();
assert.equal(languages.length, 19);
for (const language of languages) {
  const catalogs = roots.map(root => {
    let messages;
    vm.runInNewContext(fs.readFileSync(path.join(root, "i18n", language), "utf8"), { window: { MagnolieI18n: { registerCatalog(_code, data) { messages = data.messages; } } } });
    return messages;
  });
  for (const key of keys) {
    assert.equal(typeof catalogs[0][key], "string", language + ": missing " + key);
    assert(catalogs[0][key].trim(), language + ": empty " + key);
    assert.equal(catalogs[0][key], catalogs[1][key], language + ": desktop mismatch " + key);
  }
}
for (const root of roots) {
  const markers = fs.readFileSync(path.join(root, "i18n-markers.js"), "utf8");
  for (const key of keys) assert(markers.includes("gettext(" + JSON.stringify(key) + ");"), "Extraction marker missing: " + key);
}
console.log("Appearance catalogs PASS: 16 complete, identical labels in all 19 desktop languages; extraction markers retained on both platforms.");
