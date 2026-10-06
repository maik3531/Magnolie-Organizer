"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
for (const web of require("./web-test-roots")) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.setTimeout = w.setInterval = () => 0;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.App.init({ neu: false, regional: { language: "en" }, daten: { kontakte: [{ id: "local", uid: "stable", vorname: "Synthetic", nachname: "Person",
      vcardRoundtrip: ["CATEGORIES:Client,Team\\, North", "X-UNKNOWN:preserve"] }] } });
    const t = w.OrganizerTest, card = t.daten().kontakte[0];
    assert.equal(t.daten().einstellungen.adressen.personengruppenAn, false);
    assert.deepEqual(Array.from(t.kontaktGruppen(card)), ["Client", "Team, North"]);
    t.setzeKontaktGruppen(card, ["Family", "Team, North", "Own; group", "constructor"]);
    assert.deepEqual(Array.from(t.kontaktGruppen(card)), ["Family", "Team, North", "Own; group", "constructor"]);
    assert.ok(card.vcardRoundtrip.includes("X-UNKNOWN:preserve"));
    t.daten().einstellungen.adressen.personengruppenAn = true;
    t.zustand().adressen.buchstabe = "P"; t.zustand().adressen.auswahlId = card.id;
    t.wechsel("adressen");
    assert.ok(w.document.querySelector(".kontakt-kopf-text .k-label").textContent.includes("Team, North"));
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Edit").click();
    const picker = w.document.querySelector("#kontakt-personengruppen");
    assert.ok(picker && picker.multiple);
    assert.ok([...picker.options].some(option => option.value === "Doctor"));
    const own = w.document.querySelector("#kontakt-eigene-personengruppe"); own.value = "Own new group";
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Add contact group").click();
    assert.ok([...picker.selectedOptions].some(option => option.value === "Own new group"));
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Save changes").click();
    assert.ok(t.kontaktGruppen(t.daten().kontakte[0]).includes("Own new group"));
    assert.ok(t.daten().kontakte[0].vcardRoundtrip.includes("X-UNKNOWN:preserve"));
    const search = w.document.querySelector('#kopf-links input[type="search"]');
    search.value = "Own new group"; search.dispatchEvent(new w.Event("input"));
    assert.ok(w.document.querySelector("#inhalt-links .liste").textContent.includes("Synthetic"), "Group names must participate in search");
    t.setzeKontaktGruppen(card, Array.from({ length: 40 }, (_, n) => "Imported group " + n));
    assert.equal(t.kontaktGruppen(card).length, 40, "Imported groups must not be silently trimmed");
  } finally { w.close(); }
}
console.log("CONTACT GROUPS PASSED: opt-in, imported categories, escaping, labels and preservation");
