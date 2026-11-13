"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const binding = n => "urn:magnolie:import:android:" + String(n).repeat(64);
for (const web of require("./web-test-roots")) {
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
    // #602: exercise actual import matching in both full frontends.
    for (const [country, national, international] of [
      ["DE", "0123456", "+49123456"], ["DE", "030 123456", "+4930123456"],
      ["GB", "07700 900123", "+447700900123"], ["IT", "02 12345678", "+390212345678"],
      ["DE", "0123456 ext 1", "+49123456 ext 1"]]) {
      const alternatives = international.includes("ext") ? [national, international] : [national, "00" + international.slice(1), international];
      for (const number of alternatives) {
        const saved = { id: "country-person", vorname: "Country", nachname: "Fixture", telefone: [{ wert: national }] };
        w.App.init({ neu: false, regional: { homeCountry: country }, daten: {
          einstellungen: { regional: { homeCountry: country } }, kontakte: [saved] } });
        T.mergeKontakte([{ vorname: "Country", nachname: "Fixture", telefone: [{ wert: number }], notiz: "Matched" }]);
        assert.equal(T.daten().kontakte.length, 1, country + " import created duplicate " + number);
        assert.equal(T.daten().kontakte[0].notiz, "Matched");
        assert.equal(T.daten().kontakte[0].telefone[0].wert, national, "Original spelling changed");
      }
    }
    for (const [country, number] of [["ZZ", "+49123456"], ["GB", "+49123456"],
      ["DE", "+49123457"], ["DE", "+49123456 ext 2"]]) {
      w.App.init({ neu: false, regional: { homeCountry: country }, daten: {
        einstellungen: { regional: { homeCountry: country } }, kontakte: [
          { id: "different", vorname: "Country", nachname: "Fixture", telefone: [{ wert: number.includes("ext") ? "0123456 ext 1" : "0123456" }] }] } });
      const before = JSON.stringify(T.daten().kontakte[0]);
      T.mergeKontakte([{ vorname: "Country", nachname: "Fixture", telefone: [{ wert: number }] }]);
      assert.equal(T.daten().kontakte.length, 2, "Different country/number/extension was silently merged");
      assert.equal(JSON.stringify(T.daten().kontakte[0]), before);
    }
    console.log("CONTACT IMPORT IDENTITY PASSED:", web);
  } finally { w.close(); }
}
