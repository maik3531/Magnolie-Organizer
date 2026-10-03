"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => {
      if (mode === "stale") w.OrganizerTest.daten().kontakte[0].notiz = "Local edit";
      w.App.mutationsSnapshot({ token: m.token, ok: mode !== "snapshot-error" });
    });
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ neu: false, daten: { kontakte: [{ id: "local", uid: "stable", vorname: "Local", notiz: "Original" }] } });
    const T = w.OrganizerTest, before = JSON.stringify(T.daten());
    const payload = { kontaktQuelle: "datei:" + "a".repeat(64), kontakte: [
      { uid: "stable", vorname: "Remote", notiz: "Incoming", geaendert: Date.now() + 1000 },
      { uid: "new", vorname: "New", sync: true, baumKontakt: { freigabeId: "injected" }, kontaktZeit: { zeit: Date.now(), hash: "injected" } }
    ], aufgaben: [{ titel: "Mixed payload task", uid: "task" }] };
    const run = w.App.importErgebnis(payload);
    assert.ok(w.document.querySelector(".kontakt-datei-pruefung"));
    assert.equal(JSON.stringify(T.daten()), before, "preview mutated the data");
    const apply = w.document.querySelector("[data-import-anwenden]");
    apply.click();
    assert.equal(JSON.stringify(T.daten()), before, "unresolved conflict was silently accepted");
    if (mode === "profile") {
      w.App.init({ neu: false, daten: { kontakte: [{ id: "other", vorname: "Other profile" }] } });
      assert.equal(w.document.querySelector(".kontakt-datei-pruefung"), null);
    } else if (mode === "lock") {
      T.zeigeSperrbildschirm(false);
      assert.equal(w.document.querySelector(".kontakt-datei-pruefung"), null);
    } else if (mode === "cancel") {
      [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click();
    } else {
      const select = w.document.querySelector('[data-import-entscheidung="0"]');
      select.value = ["keep", "merge", "new", "skip"].includes(mode) ? mode : "replace";
      select.dispatchEvent(new w.Event("change")); apply.click();
      if (mode === "changed-choice") {
        select.value = "keep"; select.dispatchEvent(new w.Event("change"));
        for (let n = 0; n < 1000 && !w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'); n++)
          await new Promise(resolve => setTimeout(resolve, 1));
        await new Promise(resolve => setTimeout(resolve, 0));
        assert.equal(JSON.stringify(T.daten()), before, "choice changed while hashing was silently committed");
        apply.click();
      }
    }
    await run;
    if (["cancel", "snapshot-error", "lock"].includes(mode)) assert.equal(JSON.stringify(T.daten()), before);
    else if (mode === "profile") {
      assert.equal(T.daten().kontakte.length, 1); assert.equal(T.daten().kontakte[0].id, "other");
      assert.equal(T.daten().aufgaben.length, 0);
    }
    else if (mode === "stale") {
      assert.equal(T.daten().kontakte.length, 1); assert.equal(T.daten().kontakte[0].notiz, "Local edit");
      assert.equal(T.daten().aufgaben.length, 0);
    } else {
      assert.equal(T.daten().kontakte.length, mode === "new" ? 3 : 2);
      assert.equal(T.daten().aufgaben.length, 1);
      assert.equal(T.daten().kontakte[0].id, "local"); assert.equal(T.daten().kontakte[0].uid, "stable");
      assert.equal(T.daten().kontakte[0].vorname, mode === "replace" ? "Remote" : "Local");
      const added = T.daten().kontakte.find(k => k.uid === "new");
      assert.equal(added.sync, false); assert.ok(!added.baumKontakt); assert.ok(!added.kontaktZeit);
      if (mode === "skip") {
        assert.equal(T.daten().kontaktImportAblehnungen.length, 1);
        const saved = JSON.parse(JSON.stringify(T.daten()));
        for (const variant of ["replay", "transport-time", "content", "extra-field", "source", "override"]) {
          w.App.init({ neu: false, daten: saved });
          const incoming = JSON.parse(JSON.stringify(payload));
          if (variant === "transport-time") incoming.kontakte[0].geaendert += 10000;
          if (variant === "content") incoming.kontakte[0].notiz = "Changed source";
          if (variant === "extra-field") incoming.kontakte[0].additionalField = "Changed";
          if (variant === "source") incoming.kontaktQuelle = "datei:" + "b".repeat(64);
          const replay = w.App.importErgebnis(incoming);
          for (let n = 0; n < 1000 && !w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'); n++)
            await new Promise(resolve => setTimeout(resolve, 1));
          assert.ok(w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'));
          const decision = w.document.querySelector('[data-import-entscheidung="0"]');
          assert.equal(decision.value, ["replay", "transport-time", "override"].includes(variant) ? "skip" : "", variant);
          if (variant === "override") {
            decision.value = "replace"; decision.dispatchEvent(new w.Event("change"));
            w.document.querySelector("[data-import-anwenden]").click();
          } else [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click();
          await replay;
          assert.equal(T.daten().kontaktImportAblehnungen.length, variant === "override" ? 0 : 1);
        }
      }
    }
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots")) {
    for (const mode of ["replace", "merge", "keep", "skip", "new", "cancel", "snapshot-error", "stale", "profile", "lock", "changed-choice"]) await check(web, mode);
    console.log("CONTACT FILE REVIEW PASSED:", web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
