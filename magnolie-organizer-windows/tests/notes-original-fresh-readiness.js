"use strict";
// #639 explicit positive DOM-only reproduction. No native saved witness or key.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../app/web");
async function boot(data) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://fresh-readiness.test.invalid/", pretendToBeVisual: true });
  const w = dom.window, commands = [];
  w.setTimeout = () => 1; w.clearTimeout = () => {}; w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: raw => commands.push(JSON.parse(raw)) } } };
  for (const name of ["normative-timezones.js", "i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
  await new Promise(resolve => setImmediate(resolve));
  w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: data });
  return { dom, w, commands };
}
async function run() {
  let seed, fresh;
  try {
    seed = await boot({ kontakte: [{ id: "synthetic-id", uid: "synthetic-uid", vorname: "Synthetic", notiz: "Keep" }] });
    // Obtain the normalized fixture shape, not a native witness. Neither window
    // performs a save or receives any synthetic/fake SaveACK.
    const loaded = JSON.parse(JSON.stringify(seed.w.OrganizerTest.daten()));
    const modes = ["readiness", "unsent", "metadata-no-witness", "bootstrap", "locked", "normalization-change"];
    for (const mode of modes) {
      fresh?.dom.window.close();
      const input = JSON.parse(JSON.stringify(loaded));
      if (mode === "normalization-change") delete input.kontakte[0].uid;
      fresh = await boot(input);
      const before = JSON.stringify(input);
      if (mode !== "normalization-change") assert.deepEqual(fresh.w.OrganizerTest.daten().kontakte[0].uid, loaded.kontakte[0].uid);
      if (mode === "unsent") fresh.w.OrganizerTest.daten().kontakte[0].notiz = "Unsent fresh-window edit";
      if (mode === "locked") fresh.w.App.init({ gesperrt: true });
      assert.equal(fresh.commands.filter(value => value.cmd === "speichern").length, 0);
      fresh.w.App.notesOriginalBereit({ token: "a".repeat(64), beforeText: before });
      const reply = fresh.commands.filter(value => value.cmd === "notes_original_ready").at(-1);
      assert.equal(reply?.bereit, !["unsent", "locked", "normalization-change"].includes(mode),
        "Fresh loaded-model readiness failed: " + mode);
      assert.equal(fresh.commands.filter(value => value.cmd === "speichern").length, 0);
      if (mode !== "readiness") {
        const candidate = JSON.parse(before);
        candidate.kontakte[0].notesOriginalBasis = { basis: "b".repeat(64) };
        const offer = { token: "b".repeat(64), kind: mode === "metadata-no-witness" ? "save" : "bootstrap",
          beforeText: before, text: mode === "metadata-no-witness" ? JSON.stringify(candidate) : before };
        fresh.w.App.notesOriginalSpeichern(offer);
        const saves = fresh.commands.filter(value => value.cmd === "speichern");
        assert.equal(saves.length, mode === "bootstrap" ? 1 : 0, "Fresh loaded baseline became a metadata save witness: " + mode);
        if (mode === "bootstrap") {
          assert.equal(saves[0].text, before); assert.ok(Number.isSafeInteger(saves[0].id));
          assert.equal(saves[0].notesOriginalLauf, offer.token);
        }
      }
    }
    console.log(`${modes.length} fresh Windows DOM cases passed; no SaveACK/native saved witness fabricated.`);
  } finally { fresh?.dom.window.close(); seed?.dom.window.close(); }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
