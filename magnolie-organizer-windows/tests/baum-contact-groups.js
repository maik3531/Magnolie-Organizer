"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kontaktBaumInhalt, baumKontaktKarte, baumKontaktEntwurf, baumKontaktPruefung, bereiteBaumKontaktNutzlastVor, kontaktGruppen, setzeKontaktGruppen, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [{ id: "group-fixture", vorname: "Synthetic", email: "fixture@example.test",
      vcardRoundtrip: ["CATEGORIES:MY CONTACTS,Colleagues", "X-OWNED:preserve"],
      baumKontakt: { freigabeId: "fixture:contact", version: 1, quelle: "desktop", partner: ["peer"], staende: [] } }] });
    try {
      const contact = b.t.daten().kontakte.find(item => item.id === "group-fixture");
      const exported = b.t.kontaktBaumInhalt(contact, 4);
      assert.deepEqual(Array.from(exported.kontakt.gruppen), ["Colleagues"]);
      for (const version of [1, 2, 3]) assert.equal(Object.hasOwn(b.t.kontaktBaumInhalt(contact, version).kontakt, "gruppen"), false);
      const offer = (groups, version = 2) => ({ von: "peer", art: "kontakt_sync", inhalt: { ...JSON.parse(JSON.stringify(exported)),
        fassung: 4, freigabeId: "fixture:contact", version, quelle: "phone", kontakt: { ...JSON.parse(JSON.stringify(exported.kontakt)), gruppen: groups } } });
      for (const [groups, version] of [[["Work", "Colleagues"], 2], [["Work"], 3], [[], 4]]) {
        const incoming = offer(groups, version), card = b.t.baumKontaktKarte(incoming);
        assert.equal(card.baumGruppenBekannt, true); assert.ok(!JSON.stringify(card).includes("baumGruppenBekannt"));
        const planned = b.t.baumKontaktPruefung(incoming);
        assert.notEqual(planned.art, "gleich", "A group-only change cannot disappear from contact comparison");
        const kept = b.t.baumKontaktEntwurf(contact, card, {}, "keep");
        assert.deepEqual(Array.from(b.t.kontaktGruppen(kept)).sort(), Array.from(b.t.kontaktGruppen(contact)).sort());
       const draft = b.t.baumKontaktEntwurf(contact, card, {}, "merge");
        const keepGroups = b.t.baumKontaktEntwurf(contact, card, { gruppen: "keep" }, "merge");
        assert.deepEqual(Array.from(b.t.kontaktGruppen(keepGroups)).sort(), Array.from(b.t.kontaktGruppen(contact)).sort(), "Merge can explicitly retain local memberships");
        const replaceGroups = b.t.baumKontaktEntwurf(contact, card, { gruppen: "keep" }, "replace");
        assert.deepEqual(Array.from(b.t.kontaktGruppen(replaceGroups)).sort(), [...groups].sort(), "Complete replacement accepts the incoming group set");
        assert.deepEqual(Array.from(b.t.kontaktGruppen(draft)).sort(), [...groups].sort());
        assert.ok(draft.vcardRoundtrip.includes("X-OWNED:preserve")); assert.ok(draft.vcardRoundtrip.some(line => line.includes("MY CONTACTS")));
        Object.assign(contact, draft);
        assert.equal(b.t.baumKontaktPruefung(incoming).art, "gleich", "The following sync must not reintroduce a removed group");
      }
      b.t.setzeKontaktGruppen(contact, ["Work"]);
      const old = offer([], 5); old.inhalt.fassung = 3; delete old.inhalt.kontakt.gruppen;
      const legacy = b.t.baumKontaktEntwurf(contact, b.t.baumKontaktKarte(old));
      assert.deepEqual(Array.from(b.t.kontaktGruppen(legacy)), ["Work"], "An old peer with unknown groups cannot clear memberships");
      const peer = { kontaktFaehigkeiten: { kontakt_sync: [1, 2, 3, 4] } };
      const first = await b.t.bereiteBaumKontaktNutzlastVor(b.t.daten(), peer);
      assert.equal(first.fassung, 4); assert.deepEqual(Array.from(first.inhalte[0].kontakt.gruppen), ["Work"]);
      b.t.setzeKontaktGruppen(contact, ["Work", "Colleagues"]);
      const second = await b.t.bereiteBaumKontaktNutzlastVor(b.t.daten(), peer);
      assert.notEqual(first.hashes[0], second.hashes[0], "Group-only edits must increment the outbound content revision");
      console.log("CONTACT GROUP SYNC PASS: v4 add/remove/empty/re-sync, no legacy clearing, preserved metadata and outbound hash " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
