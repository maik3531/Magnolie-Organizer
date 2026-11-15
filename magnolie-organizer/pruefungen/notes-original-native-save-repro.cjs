"use strict";
// Actual Linux application DOM; all SaveACKs must come from the real native test writer.
const fs = require("node:fs"), path = require("node:path"), { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../web");
const lines = require("node:readline").createInterface({ input: process.stdin, crlfDelay: Infinity });
const emit = value => process.stdout.write(JSON.stringify(value) + "\n");
const timeout = setTimeout(() => { console.error("Bounded native Notes UI reproduction deadline"); process.exit(1); }, 45000);
let dom, w, initialized = false, nativeObserved = false, nativePending = false, mode = "normal", pendingKind;
async function run() {
  try {
    for await (const line of lines) {
      const packet = JSON.parse(line);
      if (packet.type === "init" || packet.type === "reopen") {
        dom?.window.close();
        mode = packet.mode || "normal";
        dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
          runScripts: "outside-only", url: "https://synthetic-notes-linux.test.invalid/", pretendToBeVisual: true });
        w = dom.window;
        w.setTimeout = () => 1; w.clearTimeout = () => {}; w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
        w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
        Object.defineProperty(w, "crypto", { value: webcrypto }); w.__MAGNOLIE_BRUECKE__ = "test";
        w.webkit = { messageHandlers: { test: { postMessage: raw => emit({ type: "command", value: JSON.parse(raw) }) } } };
        for (const name of ["normative-timezones.js", "i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
        await new Promise(resolve => setImmediate(resolve));
        w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: packet.data });
        if (packet.type === "reopen") { initialized = true; emit({ type: "reopened" }); }
        else w.OrganizerTest.speichereJetzt();
      } else if (packet.type === "ack") {
        w.App.gespeichert(packet.value);
        if (!initialized) { initialized = true; emit({ type: "initialized" }); }
        else if (nativePending) {
          nativePending = false;
          if (pendingKind === "bootstrap") { emit({ type: "bootstrap-observation" }); continue; }
          nativeObserved = true;
          emit({ type: "native-observation", basis: w.OrganizerTest.daten().kontakte[0].notesOriginalBasis ?? null,
            idType: typeof packet.value.id });
        } else if (nativeObserved) {
          emit({ type: "complete", data: JSON.parse(JSON.stringify(w.OrganizerTest.daten())) });
        }
      } else if (packet.type === "offer") {
        if (mode === "unsent" || mode === "reopen-unsent") w.OrganizerTest.daten().kontakte[0].notiz = "Unsent synthetic edit";
        if (mode === "unknown-ack") w.App.gespeichert({ id: "notes-original-unowned", ok: true });
        nativePending = true;
        pendingKind = packet.value.kind;
        w.App.notesOriginalSpeichern(packet.value);
      } else if (packet.type === "edit") {
        w.OrganizerTest.daten().kontakte[0].notiz = "Later synthetic user edit must survive";
        w.OrganizerTest.speichereJetzt();
      } else if (packet.type === "finish") {
        emit({ type: "finished" }); return;
      }
    }
  } finally { clearTimeout(timeout); dom?.window.close(); lines.close(); }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
