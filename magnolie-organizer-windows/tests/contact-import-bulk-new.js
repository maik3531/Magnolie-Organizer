"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
async function until(test) {
  for (let n = 0; n < 600; n++) { if (test()) return; await tick(); }
  throw new Error("Bulk import review timeout");
}
async function check(web, checkboxFirst, mode = "success") {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text); messages.push(message);
    if (message.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: message.id, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const T = w.OrganizerTest;
    // Name-only candidates are deliberately not proof that either saved person
    // is the incoming one. Creating separate contacts needs no guessed target.
    w.App.init({ neu: false, daten: { kontakte: [
      { id: "a", vorname: "Alex", nachname: "Fixture", notiz: "Saved A" },
      { id: "b", vorname: "Alex", nachname: "Fixture", notiz: "Saved B" }
    ] } });
    const before = JSON.stringify(T.daten().kontakte);
    const count = mode === "success" && checkboxFirst ? 27 : 2;
    const incoming = Array.from({ length: count }, (_, i) => ({ uid: "or6:synthetic:" + i,
      vorname: "Alex", nachname: "Fixture", notiz: "Incoming " + i }));
    const importing = w.App.importErgebnis({ kontakte: incoming });
    await until(() => w.document.querySelector('[data-import-rest]:not(:disabled)'));
    const change = field => field.dispatchEvent(new w.Event("change"));
    const rest = w.document.querySelector("[data-import-rest]");
    if (mode === "individual") {
      const individual = w.document.querySelector('[data-import-entscheidung="1"]');
      individual.value = "skip"; change(individual);
    }
    if (checkboxFirst) { rest.checked = true; change(rest); }
    let decision = w.document.querySelector('[data-import-entscheidung="0"]');
    decision.value = mode === "merge" ? "merge" : "new"; change(decision);
    if (!checkboxFirst) { rest.checked = true; change(rest); }
    if (mode === "merge") {
      assert.equal(w.document.querySelector('[data-import-entscheidung="1"]').value, "",
        "Target-dependent merge propagated across ambiguous identities");
      w.document.querySelector("[data-import-anwenden]").click();
      await tick();
      assert.equal(messages.some(m => m.cmd === "mutations_snapshot"), false);
      w.document.querySelector(".kontakt-datei-pruefung .dialog-knoepfe button:last-child").click();
      await importing;
      assert.equal(JSON.stringify(T.daten().kontakte), before);
      return;
    }
    assert.equal(w.document.querySelector('[data-import-entscheidung="1"]').value, mode === "individual" ? "skip" : "new",
      "Explicit create-new-for-all left name-only conflicts undecided");
    if (count > 25) {
      const next = Array.from(w.document.querySelectorAll(".kontakt-datei-pruefung button")).find(b => b.textContent === "Next");
      next.click();
      assert.equal(w.document.querySelector('[data-import-entscheidung="26"]').value, "new", "Bulk choice missed the next page");
    }
    assert.equal(JSON.stringify(T.daten().kontakte), before, "Preview mutated the saved contacts");
    if (mode === "cancel") {
      w.document.querySelector(".kontakt-datei-pruefung .dialog-knoepfe button:last-child").click();
      await importing;
      assert.equal(JSON.stringify(T.daten().kontakte), before);
      assert.equal(messages.some(m => m.cmd === "mutations_snapshot"), false);
      return;
    }
    if (mode === "stale") {
      T.daten().kontakte[0].notiz = "Concurrent local edit";
      w.document.querySelector("[data-import-anwenden]").click();
      await importing;
      assert.equal(T.daten().kontakte.length, 2);
      assert.equal(T.daten().kontakte[0].notiz, "Concurrent local edit");
      assert.equal(messages.some(m => m.cmd === "mutations_snapshot"), false);
      return;
    }
    w.document.querySelector("[data-import-anwenden]").click();
    await until(() => messages.some(m => m.cmd === "mutations_snapshot"));
    const snapshot = messages.find(m => m.cmd === "mutations_snapshot");
    w.App.mutationsSnapshot({ token: snapshot.token, ok: true });
    await importing;
    const expected = mode === "individual" ? incoming.slice(0, 1) : incoming;
    assert.equal(T.daten().kontakte.length, 2 + expected.length, "Bulk create did not retain incoming people separately");
    assert.equal(JSON.stringify(T.daten().kontakte.slice(0, 2)), before, "Bulk create changed an existing person");
    assert.deepEqual(Array.from(T.daten().kontakte.slice(2), k => k.notiz), expected.map(k => k.notiz));
  } finally { w.close(); }
}
(async () => {
  const results = [];
  for (const web of require("./web-test-roots")) for (const [checkboxFirst, mode] of [
    [true, "success"], [false, "success"], [true, "merge"], [true, "individual"], [true, "cancel"], [true, "stale"]
  ]) {
    try { await check(web, checkboxFirst, mode); results.push({ web, checkboxFirst, mode, passed: true }); }
    catch (error) { results.push({ web, checkboxFirst, mode, passed: false, error: error.message }); }
  }
  console.log(JSON.stringify(results, null, 2));
  assert.ok(results.every(result => result.passed), "Bulk create-new review failed");
})().catch(error => { console.error(error); process.exitCode = 1; });
