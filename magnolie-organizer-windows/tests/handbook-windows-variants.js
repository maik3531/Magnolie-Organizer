"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const { canonicalPageIds, selectHandbookWeb } = require("./handbook-source");

const root = path.resolve(__dirname, "..");
const selected = selectHandbookWeb(root, ["index.html", "platform.js", "inhalt.js", "i18n/de.js"]);
const web = selected.directory;
const read = name => fs.readFileSync(path.join(web, name), "utf8");
const locales = ["en", "de", "ar", "be", "cs", "da", "es", "fr", "hi", "hsb",
  "it", "ja", "nb", "nl", "pl", "pt", "ru", "tr", "uk", "zh_CN"];
const variantIds = ["what-your-computer-needs", "installing-the-organizer",
  "all-day-appointments", "writing-letters", "maps-routes-and-messages",
  "appointment-reminders", "importing-data-from-other-programs", "moving-from-lotus-organizer",
  "exporting-data-to-other-programs", "synchronizing-with-online-accounts", "font-size-and-color",
  "version-and-updates", "backing-up-and-restoring", "troubleshooting", "phone-pairing"];
const expectedIds = canonicalPageIds(web);
const version = JSON.parse(read("version.json")).version;
const installer = `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`;
const dom = new JSDOM(read("index.html"), { url: "https://handbook.test/index.html",
  pretendToBeVisual: true, runScripts: "outside-only" });
const w = dom.window;
w.__MAGNOLIE_PLATFORM__ = "windows";
w.__MAGNOLIE_SPRACHE__ = "de";
try {
  for (const file of ["i18n.js", ...locales.filter(l => l !== "en").map(l => `i18n/${l}.js`),
    "i18n-start.js", "mobile-downloads.js", "inhalt.js", "platform.js"])
    w.eval(read(file));
  assert.strictEqual(w.MagnolieI18n.locale(), "de", "host language is ignored");
  const variants = w.HANDBUCH_WINDOWS_VARIANTEN;
  assert.deepStrictEqual(Object.keys(variants), variantIds);
  for (const locale of locales) {
    const code = locale.replace("_", "-").toLowerCase();
    w.MagnolieI18n.setLocale(locale);
    assert.strictEqual(w.document.documentElement.lang, code);
    assert.strictEqual(w.document.documentElement.dir, code === "ar" ? "rtl" : "ltr");
    const pages = w.HANDBUCH_SEITEN;
    assert.deepStrictEqual(pages.map(p => p.id), expectedIds);
    for (const id of variantIds) {
      const source = variants[id].en;
      const expected = w.MagnolieI18n.gettext(source);
      assert.ok(locale === "en" || expected !== source, `${locale}: untranslated Windows variant ${id}`);
      assert.strictEqual(pages.find(p => p.id === id).inhalt, expected);
    }
    assert.ok(pages.find(p => p.id === "installing-the-organizer").inhalt.includes(installer));
    for (const id of ["welcome", "starting-for-the-first-time", "first-run-assistant",
      "first-run-saved-intentions", "technical-update-trust"]) {
      const page = pages.find(p => p.id === id);
      const source = page.inhaltAnhangErsetzt ? page.inhaltAnhang.en : page._source.inhalt;
      const expected = w.MagnolieI18n.gettext(source);
      assert.ok(locale === "en" || expected !== source, `${locale}: untranslated current page ${id}`);
      assert.strictEqual(page.inhalt, expected, `${locale}: old Windows override replaced ${id}`);
    }
    assert.ok(pages.find(p => p.id === "platform-security-matrix").inhalt.includes("data-backup-automation='true'"),
      `${locale}: portable/automatic backup clarification was lost`);
    const helper = w.document.createElement("div");
    helper.innerHTML = pages.find(p => p.id === "first-run-assistant").inhalt;
    assert.strictEqual(helper.querySelectorAll("ol.schritte > li").length, 7);
    for (const page of pages)
      for (const [, target] of page.inhalt.matchAll(/data-page=['"]([^'"]+)['"]/g))
        assert.ok(expectedIds.includes(target), `${locale}: dead reference on ${page.id}`);
  }
  w.MagnolieI18n.setLocale("ar");
  w.eval(read("handbuch.js"));
  if (!w.Handbuch) w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  for (const id of ["welcome", "starting-for-the-first-time", "first-run-assistant",
    "first-run-saved-intentions", "technical-update-trust"]) {
    const page = w.Handbuch.seiten().find(p => p.id === id);
    assert.ok(w.Handbuch.blaettereZuId(id));
    assert.ok([...w.document.querySelectorAll(".seiten-kopf h2")].some(h => h.textContent === page.titel));
  }
  const printed = new JSDOM(w.Handbuch.druckFassung());
  assert.strictEqual(printed.window.document.documentElement.dir, "rtl");
  printed.window.close();
  console.log(`HANDBOOK WINDOWS VARIANTS PASSED (${variantIds.length} variants, ${locales.length} locales; ${selected.label})`);
} finally {
  dom.window.close();
}
