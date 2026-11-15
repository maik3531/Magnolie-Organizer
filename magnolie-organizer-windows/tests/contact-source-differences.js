"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const local = { id: "local", uid: "fixture", vorname: "Alex", nachname: "Fixture", notiz: "Saved note",
      importHerkunfte: ["Saved account"], vcardRoundtrip: ["CATEGORIES:Colleagues"],
      telefone: [{ wert: "+49305550123", label: "CELL", typen: ["CELL"] }],
      anschriften: [{ strasse: "Testweg 12", plz: "10115", ort: "Berlin", label: "Privat" }],
      emailEintraege: [{ wert: "alex@example.test", label: "HOME" }] };
    w.App.init({ neu: false, daten: { kontakte: [local] } });
    if (mode === "file") {
      w.App.importErgebnis({ kontakte: [{ ...local, id: undefined, notiz: "Incoming <script>not markup</script>",
        importHerkunfte: ["Phone account"], telefone: [{ wert: "+49305550123", label: "HOME", typen: ["HOME"] }],
        anschriften: [{ ...local.anschriften[0], label: "Home" }], emailEintraege: [{ wert: "alex@example.test", label: "WORK" }] }] });
    } else {
      const offer = { id: "offer", von: "peer", inhalt: { art: "kontakt_sync", fassung: 2,
        freigabeId: "share", version: 1, quelle: "peer", kontakt: { vorname: "Alex", nachname: "Fixture",
          notiz: "Incoming <script>not markup</script>", telefone: [{ wert: "+49305550123", art: "HOME" }],
          anschriften: [{ strasse: "Testweg 12", plz: "10115", ort: "Berlin", art: "Home" }],
          emailEintraege: [{ wert: "alex@example.test", art: "WORK" }] } } };
      w.App.baumStand({ an: true, moeglich: true, kennung: "local", eingang: [offer],
        partner: [{ kennung: "peer", name: "Phone account", bestaetigt: true }] });
      await w.OrganizerTest.oeffneBaumKontakt(offer);
    }
    const differences = w.document.querySelector(".kontakt-quellenvergleich");
    assert.ok(differences, "No source-coloured value comparison was shown");
    const note = differences.querySelector('[data-kontakt-vergleich="notiz"]');
    assert.ok(note);
    const saved = note.querySelector(".kontakt-quelle-gespeichert"), incoming = note.querySelector(".kontakt-quelle-eingang");
    assert.ok(saved.textContent.includes("Saved account") && saved.textContent.includes("Saved note"));
    assert.ok(incoming.textContent.includes("Phone account") && incoming.textContent.includes("Incoming <script>not markup</script>"));
    assert.equal(incoming.querySelector("script"), null, "Source content became markup");
    assert.equal(differences.querySelector('[data-kontakt-vergleich="telefone"]'), null,
      "Identical phone value was highlighted as a difference merely because of its label");
    assert.equal(differences.querySelector('[data-kontakt-vergleich="anschriften"]'), null, "Same address with Privat/Home was highlighted");
    assert.equal(differences.querySelector('[data-kontakt-vergleich="emailEintraege"]'), null, "Same email with different labels was highlighted");
    assert.equal(differences.querySelector('[data-kontakt-vergleich="gruppen"]'), null, "Missing old-protocol group information became a claimed deletion");
    const css = fs.readFileSync(path.join(web, "stil.css"), "utf8");
    assert.ok(css.includes(".kontakt-quelle-gespeichert") && css.includes(".kontakt-quelle-eingang"));
    assert.ok(saved.textContent.includes("Saved") && incoming.textContent.includes("Incoming"), "Colour must not be the only distinction");
    assert.equal(w.OrganizerTest.daten().kontakte[0].notiz, "Saved note", "Opening comparison changed the book");
  } finally { w.close(); }
}
(async () => {
  const results = [];
  for (const web of require("./web-test-roots")) for (const mode of ["file", "notes"]) {
    try { await check(web, mode); results.push({ web, mode, passed: true }); }
    catch (error) { results.push({ web, mode, passed: false, error: error.message }); }
  }
  console.log(JSON.stringify(results, null, 2)); assert.ok(results.every(r => r.passed));
})().catch(error => { console.error(error); process.exitCode = 1; });
