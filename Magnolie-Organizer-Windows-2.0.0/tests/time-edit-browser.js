"use strict";

// Run with node (or bun); requires playwright and a Chromium installation.
// Optional: MAGNOLIE_CHROMIUM, MAGNOLIE_PLAYWRIGHT.
// Uses isolated browser contexts and an inert native bridge, never a user profile.
const fs = require("node:fs"), path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.MAGNOLIE_PLAYWRIGHT || "playwright");
const roots = [path.resolve(__dirname, "../app/web"),
  path.resolve(__dirname, "../../magnolie-organizer-2.0.0/web")];

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.MAGNOLIE_CHROMIUM || undefined });
  let cases = 0;
  try {
    for (const web of roots) {
      const context = await browser.newContext({ locale: "de-DE", bypassCSP: true });
      const page = await context.newPage();
      await page.route("**/*", route => route.abort());
      await page.setContent(fs.readFileSync(path.join(web, "index.html"), "utf8"));
      await page.evaluate(() => {
        window.__MAGNOLIE_BRUECKE__ = "timeTest";
        window.webkit = { messageHandlers: { timeTest: { postMessage() {} } } };
      });
      await page.addScriptTag({ content: fs.readFileSync(path.join(web, "i18n.js"), "utf8") });
      let source = fs.readFileSync(path.join(web, "anwendung.js"), "utf8");
      // Expose only the dialog entry point, without changing production exports.
      source = source.replace("window.OrganizerTest = {",
        "window.OrganizerTest = { oeffneCustomEintrag,");
      await page.addScriptTag({ content: source });
      await page.evaluate(() => App.init({ daten: {}, neu: false,
        regional: { language: "en", timeZone: "UTC" } }));
      const field = page.locator('#custom-eintrag-schleier input[type="time"]');
      const apply = page.locator(".custom-eintrag-aktionen .haupt");
      const snapshot = () => field.evaluate(e => ({ value: e.value, bad: e.validity.badInput }));
      for (const type of ["appointments", "tasks"]) {
        for (const edit of [false, true]) {
          for (const action of ["digits", "spinner-key", "keyboard-apply", "midnight", "partial", "empty", "focused-apply"]) {
            await page.evaluate(({ type, edit, action }) => {
              document.querySelector("#custom-eintrag-schleier")?.remove();
              const item = { id: "entry", title: "Time regression", time: "09:00",
                date: "2026-09-11", due: "2026-09-11", note: "" };
              const module = { id: "time-module", type, title: "Time test", items: edit ? [item] : [] };
              OrganizerTest.daten().customOrganizer.modules = [module];
              OrganizerTest.oeffneCustomEintrag(module, edit ? item : null);
              const input = document.querySelector('#custom-eintrag-schleier input[type="time"]');
              // The minutes already exist; edit only the native hour segment below.
              if (!edit && !["partial", "empty"].includes(action)) input.value = "09:00";
              if (["partial", "empty"].includes(action)) input.value = "";
            }, { type, edit, action });
            if (action !== "empty") await field.focus();
            if (action === "digits") await page.keyboard.type("10");
            if (["spinner-key", "keyboard-apply", "partial", "focused-apply"].includes(action)) await page.keyboard.press("ArrowUp");
            if (action === "midnight") await page.keyboard.type("00");
            if (action === "focused-apply") {
              // Read the value produced by real native editing, without forcing a blur.
              await apply.evaluate(e => e.click());
            } else {
              const state = await snapshot();
              if (action === "partial") assert.deepEqual(state, { value: "", bad: true });
              else assert.deepEqual(state, { value: action === "empty" ? "" : action === "midnight" ? "00:00" : "10:00", bad: false });
              // Both real activation paths leave the minute segment untouched.
              if (action === "keyboard-apply") { await apply.focus(); await page.keyboard.press("Enter"); }
              else await apply.click();
            }
            const items = await page.evaluate(() => OrganizerTest.daten().customOrganizer.modules[0].items);
            if (action === "partial") {
              assert.equal(await field.count(), 1, "partial input must keep the editor open");
              assert.equal(items.length, edit ? 1 : 0, "partial input must not add data");
              if (edit) assert.equal(items[0].time, "09:00", "partial input must not clear the saved time");
              assert.deepEqual(await snapshot(), { value: "", bad: true }, "blur must not invent missing minutes");
            } else {
              assert.equal(await field.count(), 0, "valid Apply closes the editor");
              assert.equal(items[0].time, action === "empty" ? "" : action === "midnight" ? "00:00" : "10:00");
            }
            cases++;
          }
        }
      }
      await context.close();
      console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": 28 time-edit cases passed");
    }
    console.log(`${cases} cases passed; Chromium ${browser.version()}. Native spinner keys tested; popup/mouse spinner and WebView2 not covered.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
