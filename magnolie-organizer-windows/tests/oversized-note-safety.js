"use strict";

const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

(async () => {
  const web = path.resolve(__dirname, "..", "app", "web");
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only",
    url: "https://app.magnolie.invalid/index.html",
    pretendToBeVisual: true
  });
  const { window } = dom;
  const messages = [];
  window.__MAGNOLIE_BRUECKE__ = "windows_test_bridge";
  window.webkit = { messageHandlers: { windows_test_bridge: {
    postMessage: (text) => messages.push(JSON.parse(text))
  } } };
  Object.defineProperty(window, "crypto", { value: crypto.webcrypto });
  window.TextEncoder = TextEncoder;
  window.TextDecoder = TextDecoder;
  window.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  window.document.dispatchEvent(new window.Event("DOMContentLoaded", { bubbles: true }));

  const T = window.OrganizerTest;
  const oversized = "<span>x</span>".repeat(10001);
  const status = {};
  T.saeubereHtml(oversized, status);
  assert.strictEqual(status.gekuerzt, true, "sanitizer does not report truncation");

  const data = T.leereDaten();
  data.notizen.push({ id: "oversized-existing", titel: "Large", text: "x", html: oversized,
    anhaenge: [], notizbuchId: data.notizbuecher[0].id, geaendert: "2026-08-25" });
  window.App.init({ daten: data, neu: false, regional: { language: "de" } });
  assert.strictEqual(T.daten().notizen[0].html, oversized,
    "normalization replaces original oversized HTML with a partial document");
  T.zustand().notizen.auswahlId = "oversized-existing";
  T.wechsel("notizen");
  assert.strictEqual(window.document.querySelector("#notiz-text").getAttribute("contenteditable"),
    "false", "an existing oversized note remains editable");
  assert.ok(window.document.querySelector(".notiz-editor .einst-warnung")?.textContent.trim(),
    "an existing oversized note has no visible warning");
  assert.strictEqual(T.daten().notizen[0].html, oversized,
    "opening an oversized note changes its original HTML");

  const existing = T.daten().notizen[0];
  existing.html = "<p>safe</p>";
  T.wechsel("kalender");
  T.wechsel("notizen");
  const editor = window.document.querySelector("#notiz-text");
  editor.innerHTML = oversized;
  editor.dispatchEvent(new window.Event("input", { bubbles: true }));
  assert.strictEqual(existing.html, "<p>safe</p>",
    "oversized editor input saves the sanitizer's partial result");

  const countBeforeImport = T.daten().notizen.length;
  window.App.importErgebnis({ notizen: [{ titel: "Imported large", text: "x", html: oversized }] });
  assert.strictEqual(T.daten().notizen.length, countBeforeImport,
    "an oversized imported note is saved partially");

  window.App.baumStand({ moeglich: true, an: true, laeuft: true, kennung: "windows",
    partner: [{ kennung: "peer", name: "Peer", bestaetigt: true, vertraut: true }],
    eingang: [{ id: "large-offer", von: "peer", art: "notiz", inhalt: { art: "notiz",
      freigabeId: "peer:large", titel: "Shared large", text: "x", html: oversized } }] });
  assert.ok(!T.daten().notizen.some((note) => note.baumFreigabe?.id === "peer:large"),
    "an oversized shared-note offer is saved partially");

  existing.baumFreigabe = { id: "peer:existing", partner: ["peer"], anhangPartner: ["peer"] };
  existing.baumVersion = 1;
  existing.baumQuelle = "peer";
  window.App.baumStand({ moeglich: true, an: true, laeuft: true, kennung: "windows",
    partner: [{ kennung: "peer", name: "Peer", bestaetigt: true, vertraut: true }],
    eingang: [{ id: "large-update", von: "peer", art: "notiz_sync",
      inhalt: { art: "notiz_sync", freigabeId: "peer:existing", titel: "Changed",
        text: "changed", html: oversized, version: 2, quelle: "peer-z" } }] });
  assert.strictEqual(existing.html, "<p>safe</p>",
    "an oversized shared-note update overwrites existing content partially");

  const value = { title: "Personal large", text: "x", html: oversized,
    notebook_id: T.daten().notizbuecher[0].id, symbol: "notiz", created_ms: 1, modified_ms: 2 };
  const record = { kind: "note", id: "personal-large", state: "live",
    clock: [{ actor_id: "remote", counter: 1 }], modified_ms: 2, value };
  record.hash = await T.personalSyncHash(value);
  await assert.rejects(T.personalSyncAnwenden([record]), /too large/i,
    "personal sync accepts an oversized note");
  assert.ok(!T.daten().notizen.some((note) => note.id === "personal-large"),
    "rejected personal sync leaves a partial note behind");

  dom.window.close();
  console.log("OVERSIZED NOTE SAFETY TEST PASSED");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
