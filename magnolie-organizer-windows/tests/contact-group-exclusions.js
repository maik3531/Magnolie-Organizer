"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const vm = require("node:vm");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const watchdog = setTimeout(() => { console.error("Contact-group exclusions timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [
      { id: "patient", vorname: "Owned", nachname: "Patient", kontaktAliase: { ids: ["old-patient"] }, vcardRoundtrip: ["CATEGORIES:Work,PATIENTEN", "X-OWNED:preserved"] },
      { id: "colleague", vorname: "Owned", nachname: "Colleague", vcardRoundtrip: ["CATEGORIES:Colleagues"] },
      { id: "same-excluded", vorname: "Same", nachname: "Name", vcardRoundtrip: ["CATEGORIES:Patients"] },
      { id: "same-visible", vorname: "Same", nachname: "Name", vcardRoundtrip: [] }],
      jahrestage: [
        { id: "patient-birthday", uid: "patient-birthday", kontaktId: "patient", name: "Owned Patient", datum: "1980-10-18", typ: "birthday" },
        { id: "patient-provider-copy", uid: "patient-birthday", kontaktId: "old-patient", name: "Owned Patient", datum: "1980-10-18", typ: "birthday", syncQuellen: { owned: { id: "provider-owned" } } },
        { id: "patient-wedding", kontaktId: "patient", name: "Owned Patient", datum: "2000-10-18", typ: "wedding-anniversary" },
        { id: "colleague-birthday", kontaktId: "colleague", name: "Owned Colleague", datum: "1981-10-18", typ: "birthday" },
        { id: "same-excluded-birthday", kontaktId: "same-excluded", name: "Same Name", datum: "1982-10-19", typ: "birthday" },
        { id: "same-visible-birthday", kontaktId: "same-visible", name: "Same Name", datum: "1982-10-19", typ: "birthday" },
        { id: "same-unlinked-birthday", name: "Same Name", datum: "1982-10-19", typ: "birthday" }] });
    try {
      b.w.eval(fs.readFileSync(path.join(web, "contact-group-aliases.js"), "utf8"));
      assert.deepEqual(Array.from(b.t.kontaktGruppen({ vcardRoundtrip: ["CATEGORIES:Famille,Kollegen,Patients,My Contacts,Owned\\, custom"] })),
        ["Family", "Colleagues", "Patients", "Owned, custom"], "translated presets and escaped own names must use existing memberships without rewriting them");
      for (const file of fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"))) {
        let catalog;
        vm.runInNewContext(fs.readFileSync(path.join(web, "i18n", file), "utf8"), { window: { MagnolieI18n: { registerCatalog: (_locale, value) => { catalog = value.messages; } } } });
        for (const preset of ["Family", "Work", "Colleagues", "Patients", "Client", "Tradesperson", "Insurance", "Doctor"])
          assert.deepEqual(Array.from(b.t.kontaktGruppen({ vcardRoundtrip: ["CATEGORIES:" + catalog[preset]] })), [preset], file + ": cross-language group identity " + preset);
        for (const label of ["Exclude contact groups", "Enable contact group exclusions", "Birthdays only", "All anniversaries", "Also hide in the calendar", "Apply to", "Scope",
          "An entry is excluded when any of its contact groups is selected. No contacts or anniversaries are deleted."])
          assert.ok(catalog[label] && catalog[label] !== label, file + ": missing exclusion dialog translation " + label);
      }
      const policy = b.t.daten().einstellungen.adressen.gruppenAusschluss;
      assert.equal(policy.enabled, false);
      const records = JSON.stringify([b.t.daten().kontakte, b.t.daten().jahrestage]);
      policy.enabled = true; policy.overview.groups = ["Patients"];
      const calendar = b.t.jahrestageAm("2026-10-18", true);
      assert.ok(calendar.some(item => item.kontaktId === "patient" && item.typ === "birthday"), "overview-only exclusions must retain calendar marks");
      const overview = b.t.jahrestageAm("2026-10-18", true, "overview");
      assert.ok(!overview.some(item => item.kontaktId === "patient" && item.typ === "birthday"));
      assert.ok(overview.some(item => item.id === "patient-wedding"));
      assert.ok(overview.some(item => item.id === "colleague-birthday"));
      assert.ok(b.t.druckStoff("jahrestage").liste.some(item => item.kontaktId === "patient" && item.typ === "birthday"), "anniversary-list rules are separate");
      policy.overview.calendar = true;
      assert.ok(!b.t.jahrestageAm("2026-10-18", true).some(item => item.kontaktId === "patient" && item.typ === "birthday"), "changing rules must affect an already built day index");
      policy.overview.scope = "anniversaries";
      assert.ok(!b.t.jahrestageAm("2026-10-18", true).some(item => item.kontaktId === "patient"));
      const ambiguous = b.t.jahrestageAm("2026-10-19", true);
      assert.ok(ambiguous.some(item => item.kontaktId === "same-visible"));
      assert.ok(ambiguous.some(item => item.id === "same-unlinked-birthday"));
      assert.ok(!ambiguous.some(item => item.kontaktId === "same-excluded"));
      policy.anniversaries.groups = ["Patients"];
      assert.ok(!b.t.druckStoff("jahrestage").liste.some(item => item.kontaktId === "patient" && item.typ === "birthday"));
      policy.enabled = false;
      assert.ok(b.t.jahrestageAm("2026-10-18", true).some(item => item.kontaktId === "patient" && item.typ === "birthday"));
      assert.deepEqual(Array.from(policy.overview.groups), ["Patients"], "disabling must retain the previous group choice");
      assert.equal(JSON.stringify([b.t.daten().kontakte, b.t.daten().jahrestage]), records, "filtering must not alter provider records, groups or birthday sources");
      b.t.oeffneEinstellungen();
      b.w.document.querySelector("#einst-tab-erinnerung").click();
      [...b.w.document.querySelectorAll("button")].find(button => button.textContent === "Exclude contact groups").click();
      await new Promise(resolve => setImmediate(resolve));
      const master = b.w.document.querySelector("#gruppen-ausschluss-aktiv");
      assert.ok(master && !master.checked);
      assert.ok(b.w.document.querySelector("#gruppen-ausschluss-bereich").closest("[hidden]"));
      master.click();
      const patientChoice = b.w.document.querySelector('[data-gruppe="Patients"]');
      assert.ok(!patientChoice.checked); patientChoice.click();
      assert.equal(policy.enabled, false, "dialog changes must remain a draft before saving");
      master.click(); master.click();
      assert.ok(b.w.document.querySelector('[data-gruppe="Patients"]').checked, "disable/re-enable must retain draft group choices");
      b.w.document.querySelector("#gruppen-ausschluss-speichern").click();
      assert.ok(!b.w.document.querySelector("#gruppen-ausschluss"));
      assert.equal(b.t.daten().einstellungen.adressen.gruppenAusschluss.enabled, true);
      assert.deepEqual(Array.from(b.t.daten().einstellungen.adressen.gruppenAusschluss.notifications.groups), ["Patients"]);
      b.t.schliesseEinstellungen();
      if (b.saves().length) b.ack();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
      };
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args = {}) => (await rpc("tools/call", { name, arguments: args })).result;
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-contact-groups", version: "1" } });
      await rpc("notifications/initialized", {});
      const current = ok(await call("organizer_contact_group_exclusions_read"));
      assert.equal(current.settings.enabled, true);
      const saved = ok(await call("organizer_contact_group_exclusions_update", { expected_revision: current.revision, enabled: false }));
      assert.equal(saved.persisted, true);
      const disabled = ok(await call("organizer_contact_group_exclusions_read"));
      assert.equal(disabled.settings.enabled, false);
      assert.deepEqual(disabled.settings.notifications.groups, current.settings.notifications.groups);
      const stale = await call("organizer_contact_group_exclusions_update", { expected_revision: current.revision, enabled: true });
      assert.equal(stale.structuredContent.code, "conflict");
      const stored = JSON.parse(b.saves().at(-1).text);
      const reloaded = await harness.exports.boot(web, stored);
      try {
        const after = reloaded.t.daten().einstellungen.adressen.gruppenAusschluss;
        assert.equal(after.enabled, false); assert.deepEqual(Array.from(after.notifications.groups), ["Patients"]);
      } finally { reloaded.close(); }
      b.t.daten().einstellungen.adressen.gruppenAusschluss.enabled = true;
      b.t.daten().einstellungen.adressen.gruppenAusschluss.overview.calendar = true;
      b.t.daten().einstellungen.regional.homeCountry = "US";
      b.t.daten().einstellungen.adressen.landCode = "DE";
      b.t.daten().kontakte[0].telefone = [{ wert: "+12025550123" }];
      b.t.daten().kontakte.push({ id: "other-provider", telefone: [{ wert: "2025550123" }], vcardRoundtrip: [] });
      b.t.daten().jahrestage.push({ id: "other-provider-birthday", kontaktId: "other-provider", name: "Owned merged person", datum: "1980-10-18", typ: "birthday" });
      b.t.planeSpeichern();
      assert.ok(!b.t.jahrestageAm("2026-10-18", true).some(item => item.id === "other-provider-birthday"), "merged provider membership must use explicit regional home country before the address fallback");
      console.log("CONTACT GROUP EXCLUSIONS DOMAIN PASS: separate areas/scopes, identity aliases, ambiguity, preserved provider records, disable/retained choices " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
