"use strict";

// Refs #792. Real Chromium layout of the generated tablet projection, with a
// synthetic, in-memory native bridge. This is not Android/TalkBack/IME proof.
// First run tools/project-web.cjs. Requires Playwright and Chromium, as does the
// shared time-edit-browser test. Optional MAGNOLIE_PLAYWRIGHT/MAGNOLIE_CHROMIUM.
// Optional MAGNOLIE_TABLET_LAYOUT_OUTPUT saves measurements and screenshots.
// MAGNOLIE_TABLET_LAYOUT_CSS can supply the pre-fix stylesheet for regression
// reproduction without modifying the generated projection or canonical source.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.MAGNOLIE_PLAYWRIGHT || "playwright");
const web = path.resolve(__dirname, "../app/build/generated/projection/assets/web");
const output = process.env.MAGNOLIE_TABLET_LAYOUT_OUTPUT;
const overrideCss = process.env.MAGNOLIE_TABLET_LAYOUT_CSS;
const cases = [
  { name: "landscape", width: 1280, height: 800, columns: true },
  { name: "large-portrait", width: 1200, height: 1600, columns: true },
  { name: "portrait", width: 800, height: 1280 },
  { name: "compact-landscape", width: 800, height: 480 },
  { name: "split-screen", width: 600, height: 960 },
  { name: "narrow-split", width: 360, height: 740 },
  { name: "resized-keyboard-window", width: 1280, height: 360, columns: true },
  { name: "compact-keyboard-window", width: 640, height: 360 },
  { name: "rtl-split", width: 600, height: 960, rtl: true },
  { name: "enlarged-text", width: 600, height: 960, enlarged: true },
];
const failures = [];
const results = [];
let checks = 0;
function check(value, message) {
  checks++;
  if (!value) failures.push(message);
}

(async () => {
  assert.ok(fs.existsSync(path.join(web, "index.html")), "Generate the tablet projection first");
  if (output) fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.MAGNOLIE_CHROMIUM || undefined });
  try {
    for (const spec of cases) {
      const errors = [];
      const context = await browser.newContext({ viewport: { width: spec.width, height: spec.height },
        hasTouch: true, locale: "de-DE", reducedMotion: "reduce" });
      const page = await context.newPage();
      page.on("pageerror", error => errors.push(error.message));
      await page.route("**/*", route => {
        const url = new URL(route.request().url());
        if (url.origin !== "https://tablet-layout.test") return route.abort();
        const relative = decodeURIComponent(url.pathname).replace(/^\/+/, "");
        const file = path.resolve(web, relative || "index.html");
        if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile())
          return route.fulfill({ status: 404, body: "Missing test asset" });
        const types = { ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
          ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
          ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf" };
        return route.fulfill({ contentType: types[path.extname(file)] || "application/octet-stream",
          body: fs.readFileSync(relative === "tablet.css" && overrideCss ? overrideCss : file) });
      });
      await page.addInitScript(() => {
        const session = crypto.randomUUID();
        let revision = crypto.randomUUID();
        let disk = null;
        window.TabletNative = { postMessage(text) {
          const request = JSON.parse(text);
          setTimeout(() => {
            const reply = (callback, payload) => window.Tablet.receive({ callback, payload });
            if (request.cmd === "bereit") reply("init", { daten: disk, session, revision });
            if (request.cmd === "tablet_loaded") reply("ready", { session, revision });
            if (request.cmd === "speichern") {
              disk = JSON.parse(request.text);
              const expectedRevision = revision;
              revision = crypto.randomUUID();
              reply("gespeichert", { id: request.id, ok: true, session, expectedRevision, revision });
            }
            if (request.cmd === "eds_status") reply("edsStatus", {
              requestId: request.requestId, verfuegbar: true, buchOk: true,
              permissions: { contacts: "not_granted", events: "not_granted" }, kalender: [], adressbuecher: [] });
            if (request.cmd === "baum_briefkasten_status") reply("baumBriefkastenStatus", {
              kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false, url: "", benutzer: "",
              kennwortVorhanden: false, revision: "a".repeat(64), zustand: "disabled", fehler: "" });
          }, 0);
        } };
      });
      await page.goto("https://tablet-layout.test/index.html");
      await page.waitForFunction(() => !!window.OrganizerTest && document.querySelector("#buch.offen") &&
        document.querySelectorAll(".registerknopf").length > 0);
      await page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      });
      if (spec.rtl) await page.evaluate(() => { document.documentElement.dir = "rtl"; });
      if (spec.enlarged) await page.evaluate(() => {
        // Synthetic font enlargement; do not claim this emulates Android's textZoom.
        for (const el of document.querySelectorAll("button,summary,input,select,label,h2,.registertext"))
          el.style.fontSize = (parseFloat(getComputedStyle(el).fontSize) * 2) + "px";
      });
      const layout = await page.evaluate(() => {
        const rect = element => {
          const r = element.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
        };
        const visible = element => {
          const s = getComputedStyle(element), r = element.getBoundingClientRect();
          return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
        };
        return {
          left: rect(document.getElementById("seite-links")),
          right: rect(document.getElementById("seite-rechts")),
          tabs: [...document.querySelectorAll(".registerknopf")].filter(visible).map(el => ({ ...rect(el),
            label: el.textContent.trim(), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth })),
          toolbar: [...document.querySelectorAll("#tablet-bar button,#tablet-bar summary,#statusleiste button")]
            .filter(visible).map(el => ({ ...rect(el), id: el.id, label: el.textContent.trim() })),
          documentWidth: document.documentElement.scrollWidth,
        };
      });
      const prefix = spec.name + ": ";
      check(layout.documentWidth <= spec.width + 1, prefix + "no document horizontal overflow");
      check(layout.left.x >= 0 && layout.left.right <= spec.width + 1 && layout.right.x >= 0 &&
        layout.right.right <= spec.width + 1, prefix + "both pages fit the available width");
      if (spec.columns) {
        check(Math.abs(layout.left.y - layout.right.y) <= 1 && layout.right.x > layout.left.x,
          prefix + "wide window keeps two pages, regardless of orientation");
        check(layout.left.width >= 400 && layout.right.width >= 400, prefix + "usable two-page width");
      } else {
        check(layout.right.y >= layout.left.bottom, prefix + "compact window stacks both pages");
        check(layout.left.width >= spec.width - 64, prefix + "compact page uses available width");
      }
      check(layout.tabs.every(tab => tab.x >= -1 && tab.right <= spec.width + 1), prefix + "all navigation tabs stay inside window");
      check(layout.tabs.every(tab => tab.width >= 48 && tab.height >= 48), prefix + "navigation targets are at least 48 CSS pixels");
      check(layout.toolbar.every(control => control.width >= 48 && control.height >= 48), prefix + "toolbar targets are at least 48 CSS pixels");

      // Exercise actual generated navigation and preserve a local note across
      // each reflow. No real Android storage or provider is involved.
      await page.evaluate(() => {
        const data = OrganizerTest.daten();
        data.notizen.push({ id: "layout-note", titel: "Layout integrity", text: "Unchanged local text",
          notizbuchId: data.notizbuecher[0].id, anhaenge: [] });
      });
      let tapped = true;
      try { await page.locator('[data-fokus="register:adressen"]').tap({ timeout: 2000 }); }
      catch (_) { tapped = false; }
      check(tapped && await page.locator('[data-fokus="register:adressen"]').getAttribute("aria-current") === "page",
        prefix + "real touch tap activates the contacts register");
      // Continue collecting independent measurements after a baseline failure.
      if (!tapped) await page.evaluate(() => OrganizerTest.wechsel("adressen"));
      await page.locator("#knopf-einstellungen").click();
      await page.waitForFunction(() => !document.getElementById("einstellungen-schleier").classList.contains("verborgen"));
      const settings = await page.evaluate(() => {
        const box = selector => {
          const r = document.querySelector(selector).getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
        };
        return { dialog: box("#einstellungen-blatt"), close: box("#einstellungen-zu"), content: box(".einst-seite") };
      });
      check(settings.dialog.x >= 0 && settings.dialog.right <= spec.width + 1 && settings.dialog.y >= 0 &&
        settings.dialog.bottom <= spec.height + 1, prefix + "settings dialog fits resized window");
      check(settings.close.width >= 48 && settings.close.height >= 48 && settings.close.y >= 0 &&
        settings.close.bottom <= spec.height + 1, prefix + "settings close control remains reachable");
      check(settings.content.height >= 72, prefix + "settings content retains a usable scroll area");
      if (output) await page.screenshot({ path: path.join(output, spec.name + "-settings.png") });
      await page.locator("#einstellungen-zu").click();
      const integrity = await page.evaluate(() => OrganizerTest.daten().notizen.find(note => note.id === "layout-note")?.text);
      check(integrity === "Unchanged local text", prefix + "navigation/settings retain local content");
      check(errors.length === 0, prefix + "no JavaScript page errors: " + errors.join("; "));
      if (output) {
        await page.evaluate(() => { document.getElementById("schreibtisch").scrollTop = 0; });
        await page.screenshot({ path: path.join(output, spec.name + ".png") });
      }
      await page.setViewportSize({ width: spec.columns ? 600 : 1280, height: 800 });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const resized = await page.evaluate(() => {
        const left = document.getElementById("seite-links").getBoundingClientRect();
        const right = document.getElementById("seite-rechts").getBoundingClientRect();
        return { stacked: right.y >= left.bottom, width: document.documentElement.scrollWidth,
          note: OrganizerTest.daten().notizen.find(note => note.id === "layout-note")?.text };
      });
      check(resized.stacked === !!spec.columns && resized.width <= (spec.columns ? 600 : 1280) + 1,
        prefix + "live resize changes page arrangement without horizontal document overflow");
      check(resized.note === "Unchanged local text", prefix + "live resize retains local content");
      results.push({ ...spec, layout, settings, errors });
      await context.close();
    }
    const result = { browser: browser.version(), scope: "Chromium host layout with synthetic native bridge; no Android acceptance",
      checks, passed: checks - failures.length, failures, cases: results };
    if (output) fs.writeFileSync(path.join(output, "layout-results.json"), JSON.stringify(result, null, 2) + "\n");
    console.log(JSON.stringify({ browser: result.browser, cases: cases.length, checks, passed: result.passed, failures }, null, 2));
    assert.equal(failures.length, 0, failures.join("\n"));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
