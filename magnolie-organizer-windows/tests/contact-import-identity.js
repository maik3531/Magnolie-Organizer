"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const binding = n => "urn:magnolie:import:android:" + String(n).repeat(64);
for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const T = w.OrganizerTest;
    const a = { id: "a", vorname: "Alex", nachname: "Person", importBindungen: [binding(1)],
      emailEintraege: [{ wert: "a@example.test" }], telefone: [{ wert: "+49305550111" }] };
    const b = { id: "b", vorname: "Alex", nachname: "Person", importBindungen: [binding(2)],
      emailEintraege: [{ wert: "b@example.test" }], telefone: [{ wert: "+49305550222" }] };
    for (const [name, cards, incoming] of [
      ["conflicting bindings", [a, b], { importBindungen: [binding(1), binding(2)] }],
      ["ambiguous binding", [a, { ...b, importBindungen: [binding(1)] }], { importBindungen: [binding(1)], emailEintraege: a.emailEintraege }],
      ["conflicting mail and phone", [a, b], { emailEintraege: a.emailEintraege, telefone: b.telefone }],
      ["multiple mail matches", [a, b], { emailEintraege: [...a.emailEintraege, ...b.emailEintraege], telefone: a.telefone }],
      ["ambiguous UID", [{ ...a, uid: "shared" }, { ...b, uid: "shared" }], { uid: "shared", emailEintraege: a.emailEintraege }],
      ["conflicting UID and binding", [{ ...a, uid: "first" }, { ...b, uid: "second" }], { uid: "second", importBindungen: [binding(1)] }]
    ]) {
      w.App.init({ neu: false, daten: { kontakte: JSON.parse(JSON.stringify(cards)) } });
      const before = JSON.stringify(T.daten().kontakte);
      T.mergeKontakte([{ vorname: "Alex", nachname: "Person", notiz: "Incoming private detail", ...incoming }]);
      assert.equal(JSON.stringify(T.daten().kontakte.slice(0, 2)), before, name + " silently mutated an existing person");
      assert.equal(T.daten().kontakte.length, 3, name + " must remain separate pending review");
    }
    w.App.init({ neu: false, daten: { kontakte: [a, b] } });
    T.mergeKontakte([{ vorname: "Alex", nachname: "Person", emailEintraege: a.emailEintraege, telefone: a.telefone, notiz: "Unambiguous" }]);
    assert.equal(T.daten().kontakte.length, 2);
    assert.equal(T.daten().kontakte[0].notiz, "Unambiguous");
    console.log("CONTACT IMPORT IDENTITY PASSED:", web);
  } finally { w.close(); }
}
