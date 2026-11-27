"use strict";
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");
const root = path.resolve(process.argv[2] || path.join(__dirname, ".."));
const results = [];
for (const relative of ["magnolie-organizer/web", "magnolie-organizer-windows/app/web"]) {
  const web = path.join(root, relative);
  for (const test of [
    { name: "explicit Arabic", language: "ar", system: "en-US", expectedLanguage: "ar", expectedDirection: "rtl" },
    { name: "Arabic regional tag", language: "ar-EG", system: "en-US", expectedLanguage: "ar-eg", expectedDirection: "rtl" },
    { name: "Arabic underscore and case", language: "AR_sa", system: "en-US", expectedLanguage: "ar-sa", expectedDirection: "rtl" },
    { name: "Arabic script and region", language: "ar-Arab-EG", system: "en-US", expectedLanguage: "ar-arab-eg", expectedDirection: "rtl" },
    { name: "Arabic system locale", language: "system", system: "ar-EG", expectedLanguage: "ar-eg", expectedDirection: "rtl" },
    { name: "German system locale", language: "system", system: "de-DE", expectedLanguage: "de-de", expectedDirection: "ltr" },
    { name: "English regional fallback", language: "en-US", system: "ar-EG", expectedLanguage: "en", expectedDirection: "ltr" },
    { name: "Arabic catalog absent", language: "ar-EG", system: "ar-EG", catalogAbsent: true, expectedLanguage: "en", expectedDirection: "ltr" }
  ]) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      runScripts: "outside-only", url: "https://app.magnolie.invalid/", pretendToBeVisual: true
    });
    const w = dom.window;
    try {
      Object.defineProperty(w.navigator, "languages", { value: [test.system, "en-US"] });
      Object.defineProperty(w, "crypto", { value: webcrypto });
      w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage() {} } } };
      for (const file of ["i18n.js", "i18n/de.js", ...test.catalogAbsent ? [] : ["i18n/ar.js"]])
        w.eval(fs.readFileSync(path.join(web, file), "utf8"));
      w.__MAGNOLIE_SPRACHE__ = test.catalogAbsent ? "en" : "ar";
      w.eval(fs.readFileSync(path.join(web, "i18n-start.js"), "utf8"));
      const before = { language: w.document.documentElement.lang, direction: w.document.documentElement.dir };
      for (const file of ["normative-timezones.js", "anwendung.js"])
        w.eval(fs.readFileSync(path.join(web, file), "utf8"));
      w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
      w.App.init({ daten: {}, neu: false, regional: { language: test.language } });
      const after = { language: w.document.documentElement.lang, direction: w.document.documentElement.dir,
        settings: w.document.querySelector("#einstellungen-titel").textContent };
      const expectedSettings = test.expectedLanguage.startsWith("ar") ? "الإعدادات"
        : test.expectedLanguage.startsWith("de") ? "Einstellungen" : "Settings";
      const passed = after.language === test.expectedLanguage && after.direction === test.expectedDirection && after.settings === expectedSettings;
      const result = { source: relative, case: test.name, before, after, expected: {
        language: test.expectedLanguage, direction: test.expectedDirection, settings: expectedSettings
      }, passed };
      results.push(result);
      console.log(JSON.stringify(result));
    } finally { w.close(); }
  }
}
console.log(JSON.stringify({ checks: results.length, passed: results.filter(x => x.passed).length,
  failed: results.filter(x => !x.passed).length, scope: "Actual desktop sources in JSDOM; native UI and visual layout not tested" }));
if (results.some(x => !x.passed)) process.exitCode = 1;
