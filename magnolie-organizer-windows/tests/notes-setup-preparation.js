"use strict";
// Actual DOM endpoint; --wire receives only the real native writer's SaveACKs.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = process.env.MAGNOLIE_TEST_WEB ? path.resolve(process.env.MAGNOLIE_TEST_WEB) : path.resolve(__dirname, "../app/web");
async function boot(data, emit) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://setup-preparation.test.invalid/", pretendToBeVisual: true });
  const w = dom.window, commands = [];
  w.setTimeout = (fn, delay) => ({ fn, delay }); w.clearTimeout = t => { if (t) t.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: raw => { const value = JSON.parse(raw); commands.push(value); emit({ type: "command", value }); } } } };
  for (const name of ["normative-timezones.js", "i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
  await new Promise(resolve => setImmediate(resolve));
  w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: data });
  return { w, t: w.OrganizerTest, commands };
}
async function wire() {
  const emit = value => process.stdout.write(JSON.stringify(value) + "\n");
  const lines = require("node:readline").createInterface({ input: process.stdin, crlfDelay: Infinity });
  const deadline = setTimeout(() => { console.error("Setup preparation wire deadline"); process.exit(1); }, 25000);
  let b, mode;
  try {
    for await (const line of lines) {
      const packet = JSON.parse(line);
      if (packet.type === "init") { mode = packet.mode; b = await boot(packet.daten, emit); emit({ type: "initialized" }); continue; }
      assert.ok(b);
      if (packet.type === "finish") return;
      if (packet.callback === "notesSetupVorbereiten") {
        if (mode === "locked") b.w.App.init({ gesperrt: true });
        if (mode === "modal") b.t.oeffnePersonenblatt();
        if (mode === "editor") {
          b.t.zustand().adressen.auswahlId = b.t.daten().kontakte[0].id; b.t.zustand().adressen.modus = "bearbeiten";
          await b.t.wechsel("adressen");
          const field = b.w.document.querySelector("#kontakt-nachname"); assert.ok(field);
          field.value = "Uncommitted synthetic draft"; field.dispatchEvent(new b.w.Event("input", { bubbles: true }));
        }
        if (mode === "pending") {
          b.t.daten().kontakte[0].notiz = "First pending synthetic edit"; b.t.speichereJetzt();
          b.t.daten().kontakte[0].notiz = "Latest synthetic edit during pending save";
        }
        if (mode === "note-snapshot") {
          await b.t.wechsel("notizen");
          const field = b.w.document.querySelector("#notiz-text"); assert.ok(field);
          field.innerHTML = "Latest pending synthetic note"; field.dispatchEvent(new b.w.Event("input", { bubbles: true }));
        }
        b.w.App.notesSetupVorbereiten(packet.value);
        if (mode === "replay") b.w.App.notesSetupVorbereiten(packet.value);
        continue;
      }
      assert.equal(packet.callback, "gespeichert");
      const repliesBefore = b.commands.filter(value => value.cmd === "notes_setup_prepared").length;
      b.w.App.gespeichert(packet.value);
      if (typeof packet.value.id === "string") {
        assert.equal(b.commands.filter(value => value.cmd === "notes_setup_prepared").length, repliesBefore);
        emit({ type: "string-ack-ignored" });
      }
    }
  } finally { clearTimeout(deadline); b?.w.close(); lines.close(); }
}
wire().catch(error => { console.error(error); process.exitCode = 1; });
