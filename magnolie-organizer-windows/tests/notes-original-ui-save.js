"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = process.env.MAGNOLIE_TEST_WEB ? path.resolve(process.env.MAGNOLIE_TEST_WEB) : path.resolve(__dirname, "../app/web");
const sha = text => createHash("sha256").update(text).digest("hex");
const copy = value => JSON.parse(JSON.stringify(value));
async function boot(options = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://notes-ui.test.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  w.setTimeout = (fn, delay) => ({ fn, delay }); w.clearTimeout = t => { if (t) t.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: raw => { const value = JSON.parse(raw); messages.push(value); options.emit?.(value); } } } };
  for (const name of ["i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
  await new Promise(resolve => setImmediate(resolve));
  w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: options.data || {
    kontakte: [{ id: "synthetic-id", uid: "synthetic-uid", vorname: "Synthetic", notiz: "Keep", notesOriginalBasis: { old: true } }],
    notizen: [{ id: "synthetic-note", titel: "Keep", text: "Unrelated synthetic note" }] } });
  const commands = cmd => messages.filter(value => value.cmd === cmd);
  const ack = () => { const save = commands("speichern").at(-1); w.App.gespeichert({ id: save.id, ok: true, standSha256: sha(save.text) }); };
  if (!options.wire) { w.OrganizerTest.speichereJetzt(); ack(); }
  return { w, t: w.OrganizerTest, commands, ack, close: () => w.close() };
}
async function run() {
  const modes = ["metadata", "bootstrap", "unsaved-contact", "unsaved-note", "pending-save", "save-timer", "wrong-before", "wrong-uid", "noncontact",
    "bad-bootstrap", "malformed-token", "late-user-edit", "duplicate", "readiness", "readiness-unsaved", "readiness-pending"];
  for (const mode of modes) {
    const b = await boot();
    try {
      const before = b.commands("speichern").at(-1).text, candidate = JSON.parse(before);
      candidate.kontakte[0].notesOriginalBasis = { fassung: 1, share_id: "synthetic-share", basis: "b".repeat(64) };
      const offer = { token: "a".repeat(64), kind: mode === "bootstrap" || mode === "bad-bootstrap" ? "bootstrap" : "save", beforeText: before,
        text: mode === "bootstrap" ? before : JSON.stringify(candidate) };
      if (mode === "unsaved-contact") b.t.daten().kontakte[0].notiz = "Preserve unsent contact";
      if (mode === "unsaved-note") b.t.daten().notizen[0].text = "Preserve unsent note";
      if (mode === "pending-save") { b.t.daten().kontakte[0].notiz = "Pending save"; b.t.speichereJetzt(); }
      if (mode === "save-timer") b.t.planeSpeichern();
      if (mode === "wrong-before") offer.beforeText = "{}";
      if (mode === "wrong-uid") { candidate.kontakte[0].uid = "different-uid"; offer.text = JSON.stringify(candidate); }
      if (mode === "noncontact") { candidate.notizen[0].text = "Must not change"; offer.text = JSON.stringify(candidate); }
      if (mode === "malformed-token") offer.token = "not-a-native-token";
      if (mode.startsWith("readiness")) {
        if (mode === "readiness-unsaved") b.t.daten().kontakte[0].notiz = "Unsent readiness edit";
        if (mode === "readiness-pending") { b.t.daten().kontakte[0].notiz = "Pending readiness edit"; b.t.speichereJetzt(); }
        const saves = b.commands("speichern").length, current = copy(b.t.daten());
        b.w.App.notesOriginalBereit({ token: offer.token, beforeText: before });
        assert.equal(b.commands("notes_original_ready").at(-1)?.bereit, mode === "readiness");
        assert.equal(b.commands("speichern").length, saves, "Readiness request started a save");
        assert.deepEqual(copy(b.t.daten()), current); continue;
      }
      const unchanged = copy(b.t.daten()), saves = b.commands("speichern").length;
      b.w.App.notesOriginalSpeichern(offer);
      if (["metadata", "bootstrap", "late-user-edit", "duplicate"].includes(mode)) {
        const saved = b.commands("speichern").at(-1);
        assert.equal(b.commands("speichern").length, saves + 1, "Exact native work was not sent through serial save lane: " + mode);
        assert.equal(saved.text, offer.text); assert.equal(saved.notesOriginalLauf, offer.token);
        assert.equal(saved.kontaktOriginalLauf, undefined, "Renderer supplied the native contact claim");
        assert.deepEqual(copy(b.t.daten().notizen), unchanged.notizen);
        if (mode === "duplicate") { b.w.App.notesOriginalSpeichern(offer); assert.equal(b.commands("speichern").length, saves + 1); }
        if (mode === "late-user-edit") {
          b.t.daten().kontakte[0].notiz = "New edit after metadata dispatch"; b.t.speichereJetzt();
          assert.equal(b.commands("speichern").length, saves + 1, "Concurrent user save bypassed serial lane");
          b.ack(); const later = b.commands("speichern").at(-1);
          assert.equal(JSON.parse(later.text).kontakte[0].notiz, "New edit after metadata dispatch");
          assert.equal(later.notesOriginalLauf, undefined, "Ordinary later save reused native work authority");
        } else b.ack();
      } else {
        assert.equal(b.commands("speichern").length, saves, "Held native offer caused a save: " + mode);
        assert.deepEqual(copy(b.t.daten()), unchanged, "Held offer overwrote unsent renderer edits: " + mode);
        if (mode !== "malformed-token") assert.equal(b.commands("notes_original_save_cancel").at(-1)?.token, offer.token);
      }
    } finally { b.close(); }
  }
  console.log(`Notes UI native-save CAS: ${modes.length} synthetic DOM cases passed (no native authority from renderer).`);
}
async function wire() {
  const lines = require("node:readline").createInterface({ input: process.stdin, crlfDelay: Infinity });
  const emit = value => process.stdout.write(JSON.stringify(value) + "\n");
  const deadline = setTimeout(() => { console.error("Bounded Notes native/frontend wire deadline"); process.exit(1); }, 50000);
  let b, initialized = false, metadataSaved = false, lateSaved = false, mode = "";
  const kinds = new Map();
  try {
    for await (const line of lines) {
      const packet = JSON.parse(line);
      if (packet.type === "init" || packet.type === "reopen") {
        mode = packet.mode;
        b?.close();
        b = await boot({ data: packet.daten, wire: true, emit: value => emit({ type: "command", value }) });
        if (packet.type === "reopen") {
          assert.equal(b.commands("speichern").length, 0);
          emit({ type: "reopened" });
        } else b.t.speichereJetzt();
        continue;
      }
      assert.ok(b);
      if (packet.type === "finish") { emit({ type: "finished" }); return; }
      assert.ok(["gespeichert", "notesOriginalSpeichern", "notesOriginalBereit"].includes(packet.callback));
      if (packet.callback === "notesOriginalSpeichern") kinds.set(packet.value.token, packet.value.kind);
      b.w.App[packet.callback](packet.value);
      if (packet.callback !== "gespeichert") continue;
      assert.equal(packet.value.ok, true, "Actual native writer rejected frontend wire save");
      const saved = b.commands("speichern").find(value => value.id === packet.value.id); assert.ok(saved);
      assert.equal(packet.value.standSha256, sha(saved.text));
      if (!initialized) { initialized = true; emit({ type: "initialized" }); continue; }
      const kind = kinds.get(saved.notesOriginalLauf);
      if (kind === "bootstrap") { assert.equal(metadataSaved, false); continue; }
      if (kind === "save") {
        metadataSaved = true;
        if (mode === "late-edit") {
          b.t.daten().kontakte[0].notiz = "Later local edit after genuine metadata SaveACK";
          b.t.speichereJetzt(); continue;
        }
      } else if (metadataSaved && mode === "late-edit") lateSaved = true;
      if (metadataSaved && (mode !== "late-edit" || lateSaved)) emit({ type: "frontend-complete", text: saved.text,
        contact: b.t.daten().kontakte[0], notes: b.t.daten().notizen });
    }
  } finally { clearTimeout(deadline); b?.close(); lines.close(); }
}
(process.argv.includes("--wire") ? wire() : run()).catch(error => { console.error(error); process.exitCode = 1; });
