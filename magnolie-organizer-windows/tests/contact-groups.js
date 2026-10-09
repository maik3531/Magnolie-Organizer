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
    w.App.init({ neu: false, regional: { language: "en" }, daten: {
      kontakte: [{ id: "empty", vorname: "Empty", nachname: "Group", vcardRoundtrip: [] }],
      einstellungen: { adressen: { personengruppenAn: false } } } });
    t.zustand().adressen.buchstabe = "G"; t.zustand().adressen.auswahlId = "empty";
    t.zustand().adressen.suche = "";
    t.zustand().sektion = "kalender";
    t.wechsel("adressen");
    assert.ok(!w.document.querySelector(".kontakt-kopf-text .k-label"), "Unassigned contact shows an empty group label");
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Edit").click();
    const direct = w.document.querySelector("#kontakt-personengruppen");
    assert.ok(direct && direct.closest(".kontakt-editor-profilkopf"), "Group assignment missing next to photo in editor header");
    assert.ok(!direct.closest(".kontakt-weitere"), "Group assignment remains hidden in More fields");
    assert.equal(direct.options[0].value, "", "No-group choice must be first");
    assert.equal(direct.options[0].textContent, "No contact group");
    assert.ok(direct.options[0].selected, "Unassigned contact defaults to no group");
    assert.strictEqual(t.daten().einstellungen.adressen.personengruppenAn, false, "Opening editor silently enabled groups");
    [...direct.options].forEach(option => { option.selected = option.value === "Family"; });
    direct.dispatchEvent(new w.Event("change"));
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Save changes").click();
    assert.ok(t.kontaktGruppen(t.daten().kontakte.find(item => item.id === "empty")).includes("Family"));
    assert.ok(w.document.querySelector(".kontakt-kopf-text .k-label").textContent.includes("Family"), "Explicitly selected group is still invisible");
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Edit").click();
    const clear = w.document.querySelector("#kontakt-personengruppen");
    [...clear.options].forEach(option => { option.selected = option.value === ""; });
    clear.dispatchEvent(new w.Event("change"));
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Save changes").click();
    assert.ok(!w.document.querySelector(".kontakt-kopf-text .k-label"), "Removing last group leaves a visible placeholder");
    assert.deepEqual(Array.from(t.kontaktGruppen(t.daten().kontakte.find(item => item.id === "empty"))), []);
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Edit").click();
    const cleared = w.document.querySelector("#kontakt-personengruppen");
    assert.ok(cleared.options[0].selected, "Saved empty choice was not retained when reopening");
    // Ctrl-click can leave the preselected empty option selected alongside a group.
    [...cleared.options].find(option => option.value === "Work").selected = true;
    cleared.dispatchEvent(new w.Event("change"));
    assert.deepEqual(Array.from(cleared.selectedOptions, option => option.value), ["Work"]);
    [...cleared.options].find(option => option.value === "Family").selected = true;
    cleared.dispatchEvent(new w.Event("change"));
    assert.deepEqual(Array.from(cleared.selectedOptions, option => option.value), ["Family", "Work"]);
    cleared.options[0].selected = true;
    cleared.dispatchEvent(new w.Event("change"));
    assert.deepEqual(Array.from(cleared.selectedOptions, option => option.value), [""]);
    const ownAfterClear = w.document.querySelector("#kontakt-eigene-personengruppe");
    ownAfterClear.value = "Custom group";
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Add contact group").click();
    assert.deepEqual(Array.from(cleared.selectedOptions, option => option.value), ["Custom group"]);
    cleared.options[0].selected = true; cleared.dispatchEvent(new w.Event("change"));
    [...w.document.querySelectorAll("button")].find(button => button.textContent === "Save changes").click();
    assert.ok(!w.document.querySelector(".kontakt-kopf-text .k-label"));
    const saved = JSON.parse(JSON.stringify(t.daten()));
    w.App.init({ neu: false, regional: { language: "en" }, daten: saved });
    t.zustand().adressen.auswahlId = "empty"; t.zustand().adressen.buchstabe = "G";
    t.zustand().sektion = "kalender"; t.wechsel("adressen");
    assert.deepEqual(Array.from(t.kontaktGruppen(t.daten().kontakte.find(item => item.id === "empty"))), []);
    assert.ok(!w.document.querySelector(".kontakt-kopf-text .k-label"), "Reload shows a no-group placeholder");
  } finally { w.close(); }
}
console.log("CONTACT GROUPS PASSED: opt-in, imported categories, escaping, labels and preservation");
