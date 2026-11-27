"use strict";

// Refs #798/#801 (Android-data form from #791, window layout from #792). Exercise the
// actual projected Android-data form with Chromium
// touch input and a synthetic provider/SaveACK. This is not Android permission,
// native date-picker, IME or TalkBack acceptance. Generate the projection first.
// Optional MAGNOLIE_PLAYWRIGHT/MAGNOLIE_CHROMIUM choose the browser runtime;
// MAGNOLIE_TABLET_SYSTEM_OUTPUT saves measurements and screenshots.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.MAGNOLIE_PLAYWRIGHT || "playwright");
const web = path.resolve(__dirname, "../app/build/generated/projection/assets/web");
const output = process.env.MAGNOLIE_TABLET_SYSTEM_OUTPUT;
const systemStrings = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../web/system-import-i18n.json"), "utf8"));
const betaStrings = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../web/beta-i18n.json"), "utf8"));
const systemKeys = ["title", "copyNote", "windowNote", "busy", "scope", "allowAccess", "startDate", "endDate", "identityConflict"];
const contactsSource = "android-contacts:" + "a".repeat(64);
const eventsSource = "android-events:" + "b".repeat(64);
const cases = [
  { name: "split-screen", width: 600, height: 960 },
  { name: "compact-landscape", width: 800, height: 480 },
  { name: "keyboard-reduced-window", width: 600, height: 360 },
];
const failures = [], results = [];
let checks = 0;
function check(value, label) { checks++; if (!value) failures.push(label); }

(async () => {
  assert.ok(fs.existsSync(path.join(web, "index.html")), "Generate the tablet projection first");
  check(Object.keys(systemStrings).length === 20 && Object.keys(systemStrings).sort().join() === Object.keys(betaStrings).sort().join(),
    "Android import text covers the same 20 locales as the tablet UI");
  check(Object.values(systemStrings).every(strings => Object.keys(strings).sort().join() === [...systemKeys].sort().join() &&
    systemKeys.every(key => typeof strings[key] === "string" && strings[key].trim())),
  "All 20 locales contain exactly the nine nonempty Android import text keys");
  if (output) fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.MAGNOLIE_CHROMIUM || undefined });
  try {
    for (const spec of cases) {
      const prefix = spec.name + ": ";
      const errors = [], measurements = [];
      const context = await browser.newContext({ viewport: { width: spec.width, height: spec.height },
        hasTouch: true, locale: "de-DE", timezoneId: "Europe/Berlin", reducedMotion: "reduce" });
      const page = await context.newPage();
      page.on("pageerror", error => errors.push(error.message));
      await page.route("**/*", route => {
        const url = new URL(route.request().url());
        if (url.origin !== "https://tablet-system.test") return route.abort();
        const file = path.resolve(web, decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html");
        if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile())
          return route.fulfill({ status: 404, body: "Missing test asset" });
        const types = { ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
          ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
          ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf" };
        return route.fulfill({ contentType: types[path.extname(file)] || "application/octet-stream",
          body: fs.readFileSync(file) });
      });
      await page.addInitScript(({ contactsSource, eventsSource }) => {
        const session = crypto.randomUUID();
        let revision = crypto.randomUUID(), disk = null;
        const messages = [], saves = [];
        const snapshot = { verfuegbar: true, buchOk: true,
          permissions: { contacts: "not_granted", events: "not_granted" },
          systemImportImplemented: { contacts: true, events: "instances-window" },
          kalender: [{ uid: eventsSource, name: "Firmenkalender – Forschung und Entwicklung – Gemeinsame Termine und Abstimmungen", art: "android-events" }],
          adressbuecher: [{ uid: contactsSource, name: "Adressbuch der gemeinsamen Arbeitsgruppe für Projektplanung und Kundenbetreuung", art: "android-contacts" }] };
        const reply = (callback, payload) => window.Tablet.receive({ callback, payload });
        function acknowledge(request) {
          disk = JSON.parse(request.text);
          const expectedRevision = revision;
          revision = crypto.randomUUID();
          reply("gespeichert", { id: request.id, ok: true, session, expectedRevision, revision });
        }
        window.systemBrowserFixture = {
          messages, saves, holdStatus: false, holdSave: false,
          savedEventIds: () => (disk?.termine || []).map(event => event.id),
          savedBook: () => JSON.stringify(disk),
          grant(art) {
            const request = messages.filter(message => message.cmd === "android_systemzugriff" && message.art === art).at(-1);
            snapshot.permissions[art] = "authorized";
            reply("edsStatus", { ...snapshot, requestId: request.requestId });
          },
          sources() {
            const request = messages.filter(message => message.cmd === "eds_status").at(-1);
            reply("edsStatus", { ...snapshot, requestId: request.requestId });
          },
          finish(request) {
            const recordId = "android-event:" + request.requestId.replace(/-/g, "").repeat(2);
            const day = request.dateFrom?.replace(/-/g, "");
            const records = request.art === "events" ? [{ recordId, identityKind: "single-event", data: {
              uid: recordId, titel: "Synthetic browser appointment", notiz: "", ort: "",
              datum: request.dateFrom, zeit: "09:00", endDatum: "", endZeit: "10:00", icsAnzeigeZeitzone: "UTC",
              icsRoundtrip: ["DTSTART:" + day + "T090000Z", "DTEND:" + day + "T100000Z"],
              wiederholung: { art: "none", bis: "" }, sync: false, standardErinnerung: false,
              icsEndeFehlt: false, icsNullDauer: false,
            } }] : [{ recordId: "android-contact:" + "c".repeat(64), identityKind: "source-id",
              rowBinding: "android-contact-row:" + "d".repeat(64), data: {
                uid: "android-contact:" + "c".repeat(64), anzeigename: "Existing browser contact", notiz: "Keep this local copy", sync: false,
              } }];
            reply("androidSystemImport", { ...request, kind: request.art, ok: true, complete: true, identitySchema: 2,
              scope: request.art === "contacts" ? "source-contacts" : "calendar-instances-window", records });
          },
          conflict(request) {
            const recordId = "android-contact:" + "f".repeat(64);
            reply("androidSystemImport", { ...request, kind: "contacts", ok: true, complete: true, identitySchema: 2,
              scope: "source-contacts", records: [{ recordId, identityKind: "source-id",
                rowBinding: "android-contact-row:" + "d".repeat(64),
                data: { uid: recordId, anzeigename: "Another provider identity", sync: false } }] });
          },
          releaseSave() { acknowledge(saves.shift()); },
        };
        window.TabletNative = { postMessage(text) {
          const request = JSON.parse(text); messages.push(request);
          setTimeout(() => {
            if (request.cmd === "bereit") reply("init", { daten: disk, session, revision });
            if (request.cmd === "tablet_loaded") reply("ready", { session, revision });
            if (request.cmd === "speichern") {
              if (window.systemBrowserFixture.holdSave) saves.push(request);
              else acknowledge(request);
            }
            if (request.cmd === "eds_status" && !window.systemBrowserFixture.holdStatus)
              reply("edsStatus", { ...snapshot, requestId: request.requestId });
            if (request.cmd === "baum_briefkasten_status") reply("baumBriefkastenStatus", {
              kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false, url: "", benutzer: "",
              kennwortVorhanden: false, revision: "f".repeat(64), zustand: "disabled", fehler: "" });
          }, 0);
        } };
      }, { contactsSource, eventsSource });
      await page.goto("https://tablet-system.test/index.html");
      await page.waitForFunction(() => !!window.OrganizerTest && document.querySelector("#buch.offen"));
      await page.locator("#knopf-einstellungen").tap();
      await page.waitForFunction(() => document.activeElement?.id === "einstellungen-zu");
      check(await page.evaluate(() => document.activeElement.id === "einstellungen-zu"), prefix + "opening settings focuses its close control");
      await page.locator("#einst-tab-sync").tap();
      await page.waitForFunction(() => document.querySelector("#tablet-system-source-contacts")?.options.length === 2);
      check(await page.locator('[data-system-access="contacts"]').textContent() === "Zugriff erlauben: Adressen" &&
        await page.locator('[data-system-access="events"]').textContent() === "Zugriff erlauben: Kalender",
      prefix + "both permission controls use the German Android import labels");
      check(await page.locator("#tablet-system-from").evaluate(element => element.labels[0].textContent.trim()) === "Startdatum" &&
        await page.locator("#tablet-system-to").evaluate(element => element.labels[0].textContent.trim()) === "Enddatum",
      prefix + "date fields use German labels without English fallback");
      check(await page.evaluate(() => window.Tablet.systemText("identityConflict")) ===
        "Übernahme gestoppt: Eine vorhandene Android-Kopie lässt sich nicht eindeutig zuordnen. Vorhandene Einträge bleiben unverändert.",
      prefix + "identity conflict message is available in German");
      const liveStatus = await page.locator("#tablet-system-status").elementHandle();
      check(await liveStatus.evaluate(element => element.closest("#einstellungen-blatt") &&
        element.getAttribute("role") === "status" && element.getAttribute("aria-live") === "polite"),
      prefix + "import status has a live region within the settings dialog");

      const active = () => page.evaluate(() => ({ id: document.activeElement?.id || document.activeElement?.tagName,
        inside: document.getElementById("einstellungen-blatt").contains(document.activeElement) }));
      async function touchTarget(selector, label) {
        const target = page.locator(selector);
        await target.scrollIntoViewIfNeeded();
        const measured = await target.evaluate(element => {
          const r = element.getBoundingClientRect(), content = element.closest(".einst-seite").getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height,
            visible: r.x >= content.x && r.right <= content.right && r.y >= content.y && r.bottom <= content.bottom,
            hit: element.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)) };
        });
        measurements.push({ label, ...measured });
        check(measured.width >= 48 && measured.height >= 48 && measured.visible && measured.hit,
          prefix + label + " has a visible, unobstructed 48px touch target after scrolling");
        return target;
      }
      check(await page.evaluate(() => systemBrowserFixture.messages.every(message =>
        message.cmd !== "android_systemzugriff" && message.cmd !== "android_systemimport")),
      prefix + "opening the form does not prompt for permission or read records");
      for (const art of ["contacts", "events"]) {
        const button = await touchTarget('[data-system-access="' + art + '"]', art + " permission");
        await button.tap();
        check((await active()).inside, prefix + art + " permission wait keeps focus inside the dialog");
        await page.evaluate(art => systemBrowserFixture.grant(art), art);
        check((await active()).id === "tablet-system-source-" + art,
          prefix + art + " permission result focuses the now available source choice");
        const select = await touchTarget("#tablet-system-source-" + art, art + " source choice");
        await select.selectOption(art === "contacts" ? contactsSource : eventsSource);
      }
      for (const [key, value] of [["from", "2026-11-26"], ["to", "2026-12-10"]]) {
        const input = await touchTarget("#tablet-system-" + key, key + " date");
        await input.fill(value); await input.press("Tab");
      }
      const formBounds = await page.evaluate(() => {
        const content = document.querySelector(".einst-seite"), r = content.getBoundingClientRect();
        return { clientWidth: content.clientWidth, scrollWidth: content.scrollWidth, height: r.height };
      });
      check(formBounds.scrollWidth <= formBounds.clientWidth && formBounds.height >= 72,
        prefix + "long source names retain a usable form without horizontal overflow");

      await page.evaluate(() => { systemBrowserFixture.holdStatus = true; });
      const refresh = await touchTarget("#tablet-system-refresh", "source refresh");
      await refresh.tap();
      check((await active()).inside, prefix + "source refresh wait keeps focus inside the dialog");
      await page.evaluate(() => systemBrowserFixture.sources());
      check((await active()).id === "tablet-system-refresh", prefix + "source refresh restores its trigger");
      await page.locator("#tablet-system-from").focus();
      await page.evaluate(() => systemBrowserFixture.sources());
      check((await active()).id === "tablet-system-from", prefix + "source update retains the focused date field");
      check(await page.locator("#tablet-system-from").inputValue() === "2026-11-26" &&
        await page.locator("#tablet-system-to").inputValue() === "2026-12-10",
      prefix + "source updates retain both selected dates");
      check(await liveStatus.evaluate(element => element.isConnected && element === document.getElementById("tablet-system-status")),
        prefix + "source and focus updates retain the live status node");
      if (output) await page.screenshot({ path: path.join(output, spec.name + "-form.png") });

      async function start(art) {
        const previous = await page.evaluate(() => systemBrowserFixture.messages.filter(message => message.cmd === "android_systemimport").length);
        const button = await touchTarget("#tablet-system-import-" + art, art + " import");
        await button.tap();
        await page.waitForFunction(previous => systemBrowserFixture.messages.filter(message => message.cmd === "android_systemimport").length > previous, previous);
        const request = await page.evaluate(() => systemBrowserFixture.messages.filter(message => message.cmd === "android_systemimport").at(-1));
        check(request.art === art && request.sourceUid === (art === "contacts" ? contactsSource : eventsSource),
          prefix + art + " touch import requests the selected source");
        const cancel = page.locator("#tablet-system-access button").filter({ hasText: /^Abbrechen$/ });
        check(await cancel.evaluate(element => element === document.activeElement && !element.disabled),
          prefix + art + " import wait moves focus to the available cancel action");
        return { request, cancel };
      }
      let pending = await start("contacts");
      check(await page.locator("#tablet-system-status").textContent() === systemStrings.de.busy,
        prefix + "reading status appears in the Android dialog section");
      await pending.cancel.tap();
      check((await active()).id === "tablet-system-import-contacts", prefix + "cancel restores the contact import trigger");
      check(await page.locator("#tablet-system-status").textContent() === "Abbrechen",
        prefix + "cancelled import is reported in the Android dialog section");
      const afterCancel = (await active()).id;
      await page.evaluate(request => systemBrowserFixture.finish(request), pending.request);
      check((await active()).id === afterCancel, prefix + "late cancelled result does not move focus");

      pending = await start("events");
      check(pending.request.dateFrom === "2026-11-26" && pending.request.dateTo === "2026-12-10",
        prefix + "calendar touch import uses the dates entered in the form");
      if (output) await page.screenshot({ path: path.join(output, spec.name + "-reading.png") });
      await page.evaluate(request => { systemBrowserFixture.holdSave = true; systemBrowserFixture.finish(request); }, pending.request);
      await page.waitForFunction(() => systemBrowserFixture.saves.length > 0);
      check((await active()).inside, prefix + "save acknowledgement wait keeps focus inside the dialog");
      await page.evaluate(() => { systemBrowserFixture.holdSave = false; systemBrowserFixture.releaseSave(); });
      await page.waitForFunction(() => !document.getElementById("tablet-system-refresh").disabled);
      check((await active()).id === "tablet-system-import-events", prefix + "completed import restores the calendar import trigger");
      check(await page.evaluate(request => systemBrowserFixture.savedEventIds().includes(
        "android-event:" + request.requestId.replace(/-/g, "").repeat(2)), pending.request),
      prefix + "completed import includes the synthetic event in the acknowledged save");
      check(await page.evaluate(() => {
        const text = document.getElementById("tablet-system-status").textContent;
        return text && text === document.getElementById("tablet-status").textContent && text !== Tablet.systemText("busy");
      }), prefix + "acknowledged import result appears in the Android dialog section");

      pending = await start("events");
      await page.locator("#einstellungen-zu").focus();
      await page.evaluate(request => systemBrowserFixture.finish(request), pending.request);
      await page.waitForFunction(() => !document.getElementById("tablet-system-refresh").disabled);
      check((await active()).id === "einstellungen-zu", prefix + "background completion does not steal focus from another control");

      // Import an actual synthetic contact, then change its provider identity
      // while reusing that provider row. The real prepare() must reject it.
      pending = await start("contacts");
      await page.evaluate(request => systemBrowserFixture.finish(request), pending.request);
      await page.waitForFunction(() => !document.getElementById("tablet-system-refresh").disabled);
      const beforeConflict = await page.evaluate(() => ({ saved: systemBrowserFixture.savedBook(),
        live: JSON.stringify(OrganizerTest.daten()), contacts: OrganizerTest.daten().kontakte.length }));
      check(beforeConflict.contacts === 1, prefix + "conflict fixture begins with one copied contact");
      pending = await start("contacts");
      await page.evaluate(request => systemBrowserFixture.conflict(request), pending.request);
      await page.waitForFunction(() => !document.getElementById("tablet-system-refresh").disabled);
      check((await active()).id === "tablet-system-import-contacts", prefix + "identity conflict retains the import trigger focus");
      const afterConflict = await page.evaluate(() => ({ saved: systemBrowserFixture.savedBook(), live: JSON.stringify(OrganizerTest.daten()) }));
      check(afterConflict.saved === beforeConflict.saved && afterConflict.live === beforeConflict.live,
        prefix + "identity conflict changes neither the live book nor the saved book");
      const notice = page.locator("#tablet-system-status");
      check(await notice.textContent() === systemStrings.de.identityConflict,
        prefix + "actual identity conflict is explained in the dialog in German");
      // The short window can scroll to the complete message without closing the
      // modal. A textContent/isVisible check alone misses occlusion by the modal.
      await notice.scrollIntoViewIfNeeded();
      const conflict = await notice.evaluate(element => {
        const r = element.getBoundingClientRect(), content = element.closest(".einst-seite").getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height,
          insideDialog: !!element.closest("#einstellungen-blatt"),
          visible: r.x >= content.x && r.right <= content.right && r.y >= content.y && r.bottom <= content.bottom &&
            r.x >= 0 && r.right <= innerWidth && r.y >= 0 && r.bottom <= innerHeight,
          hit: element.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)) };
      });
      check(conflict.insideDialog && conflict.visible && conflict.hit,
        prefix + "complete conflict message is reachable and unobstructed inside the modal");
      if (output) await page.screenshot({ path: path.join(output, spec.name + "-identity-conflict.png") });
      await page.locator("#einstellungen-zu").tap();
      check((await active()).id === "knopf-einstellungen", prefix + "closing settings restores its opener");
      check(errors.length === 0, prefix + "no JavaScript page errors: " + errors.join("; "));
      results.push({ ...spec, formBounds, measurements, conflict, errors });
      await context.close();
    }
    const result = { browser: browser.version(), scope: "Chromium host with synthetic Android provider and SaveACK; no native acceptance",
      checks, passed: checks - failures.length, failures, cases: results };
    if (output) fs.writeFileSync(path.join(output, "system-import-results.json"), JSON.stringify(result, null, 2) + "\n");
    console.log(JSON.stringify({ browser: result.browser, cases: cases.length, checks, passed: result.passed, failures }, null, 2));
    assert.equal(failures.length, 0, failures.join("\n"));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
