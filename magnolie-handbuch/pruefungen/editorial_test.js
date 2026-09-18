"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const web = path.join(root, "web");
const languages = ["en", ...fs.readFileSync(path.join(root, "po/LINGUAS"), "utf8").trim().split(/\s+/)];
const dom = new JSDOM("<!doctype html><html><body></body></html>", { runScripts: "outside-only" });
const win = dom.window;
win.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
let english;
for (const language of languages) {
  const source = fs.readFileSync(path.join(web, "i18n", language + ".js"), "utf8");
  win.eval(source);
  if (language === "en") english = JSON.parse(source.split(/, (.*)/s)[1].slice(0, -3)).messages;
}
for (const file of ["mobile-downloads.js", "inhalt.js", "platform.js"])
  win.eval(fs.readFileSync(path.join(web, file), "utf8"));
const page = id => win.HANDBUCH_SEITEN.find(item => item.id === id);
const protectedSource = ["support-with-a-coffee", "about-maik-walter"].map(id => ({
  id, title: page(id)._source.titel, body: page(id)._source.inhalt
}));
assert.equal(Object.keys(english).length, 5, "English override must remain limited to the two German pages");
for (const item of protectedSource) {
  assert.ok(english[item.title] && english[item.body]);
  const original = win.document.createElement("div"), translated = win.document.createElement("div");
  original.innerHTML = item.body; translated.innerHTML = english[item.body];
  const attributes = element => Array.from(element.querySelectorAll("img,a"), node =>
    [node.tagName, node.getAttribute("src"), node.getAttribute("href"), node.className]);
  assert.deepEqual(attributes(translated), attributes(original));
  for (const image of translated.querySelectorAll("img")) assert.ok(image.alt);
}
const pin = value => crypto.createHash("sha256").update(JSON.stringify(Object.entries(value))).digest("hex");
// Exact approved English wording; existing German and Ukrainian pins stay independent.
const englishPin = "66e5db776bd4ae0ae9c1340fc089957f44bcb951352adcfa4c57d0f66cb08ae4";
assert.equal(pin(english), englishPin);
const changed = { ...english, [protectedSource[0].body]: english[protectedSource[0].body] + " changed" };
assert.throws(() => assert.equal(pin(changed), englishPin));
for (const platform of ["linux", "windows"]) {
  win.__MAGNOLIE_PLATFORM__ = platform;
  for (const language of languages) {
    win.MagnolieI18n.setLocale(language);
    assert.equal(win.document.documentElement.dir, language === "ar" ? "rtl" : "ltr");
    for (const key of ["Page {first} of {total}", "Pages {first} and {last} of {total}"]) {
      const value = win.MagnolieI18n.gettext(key);
      if (language !== "en") assert.notEqual(value, key, language);
      assert.deepEqual((value.match(/\{\w+\}/g) || []).sort(), key.match(/\{\w+\}/g).sort());
    }
    for (const id of ["first-run-assistant", "first-run-saved-intentions", "wiederherstellungspunkte-was",
      "android-notes-navigation", "android-notes-edit-save-delete", "android-tasks-reminders"]) {
      const item = page(id);
      assert.ok(item.inhalt);
      if (language !== "en") assert.notEqual(item.inhalt, item._source.inhalt, `${language}/${id}`);
    }
    for (const id of ["android-notes-navigation", "android-notes-edit-save-delete", "android-tasks-reminders"]) {
      assert.ok(page(id).inhalt.includes("1.0.14") && page(id).inhalt.includes("1.0.13"));
    }
    for (const id of ["android-apk-transfer", "android-apk-install-update"]) {
      const item = page(id);
      assert.ok(item.inhalt.includes("Magnolie-Notes.apk"), `${language}/${platform}/${id}`);
      assert.ok(!/Magnolie-Notes-\d+\.\d+\.\d+\.apk|Magnolie-Notes-PRUEFSUMMEN/.test(item.inhalt),
        `${language}/${platform}/${id}: historical filename in current installation guidance`);
      if (language !== "en") assert.notEqual(item.inhalt, item._source.inhalt);
    }
    const transfer = page("android-apk-transfer").inhalt;
    assert.ok(transfer.includes("Magnolie-Notes-latest-PRUEFSUMMEN.sha256"), language);
    assert.ok(transfer.includes("sha256sum Magnolie-Notes.apk"), language);
    assert.ok(transfer.includes("Get-FileHash .\\Magnolie-Notes.apk -Algorithm SHA256"), language);
    assert.ok(!/\b1\.0\.13\b/.test(transfer), language);
    if (language === "en") {
      assert.equal(page("support-with-a-coffee").titel, "Support Magnolie with a coffee");
      assert.ok(page("support-with-a-coffee").inhalt.includes("No valid coffee allowance"));
      assert.ok(!page("support-with-a-coffee").inhalt.includes("Eine E-Mail-Adresse bleibt freiwillig"));
      assert.ok(!page("android-notes-edit-save-delete").inhalt.includes("system Back action does not save"));
      assert.ok(!page("wiederherstellungspunkte-was").inhalt.includes("Create snapshot now"));
    }
  }
}
const mobile = JSON.parse(fs.readFileSync(path.join(web, "mobile-downloads.json"), "utf8"));
assert.equal(mobile.notes.filename, "Magnolie-Notes.apk");
assert.ok(!("version" in mobile.notes));
assert.ok(mobile.notes.url.endsWith("/Magnolie-Notes.apk"));
for (const [language, id, forbidden] of [
  ["hi", "settings-tray-autostart", ["tray enabled", "Local desktop state", "visible window fallback"]],
  ["zh_CN", "android-import-results-limits", ["5,000 entries", "No readable notes were found in this file.", "The import failed."]],
  ["ja", "sms-adjusted-send", ["SMS text was adjusted:", "1 SMS parts"]],
  ["ja", "personal-deletions-trash", ["助成金", "プロポーザル"]]
]) {
  win.MagnolieI18n.setLocale(language);
  for (const text of forbidden) assert.ok(!page(id).inhalt.includes(text), `${language}/${id}: ${text}`);
}
dom.window.close();
console.log("EDITORIAL RUNTIME CHECKS PASSED (20 languages, both platforms, exact English pin and negative probe)");
