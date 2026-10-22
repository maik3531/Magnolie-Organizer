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
      { id: "colleague", vorname: "Owned", nachname: "Colleague", vcardRoundtrip: ["CATEGORIES:Colleagues,Own group"] },
      { id: "same-excluded", vorname: "Same", nachname: "Name", vcardRoundtrip: ["CATEGORIES:Patients"] },
      { id: "same-visible", vorname: "Same", nachname: "Name", vcardRoundtrip: [] }],
      termine: [
        { id: "patient-visit", kontaktId: "patient", titel: "Visit", datum: "2026-10-18", zeit: "08:00" },
        { id: "work-meeting", kalenderQuelle: { id: "work-calendar", name: "Work calendar" }, titel: "Meeting", datum: "2026-10-18", zeit: "09:00" },
        { id: "private-visit", kontaktId: "colleague", titel: "Private", datum: "2026-10-18", zeit: "10:00" }],
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
      assert.ok(!b.t.jahrestageAm("2026-10-18", true, "anniversaries").some(item => item.kontaktId === "patient" && item.typ === "birthday"));
      assert.ok(b.t.druckStoff("jahrestage").liste.some(item => item.kontaktId === "patient" && item.typ === "birthday"), "Print must have its own independent group choice");
      policy.print.groups = ["Patients"];
      assert.ok(!b.t.druckStoff("jahrestage").liste.some(item => item.kontaktId === "patient" && item.typ === "birthday"));
      policy.print.groups = [];
      policy.enabled = false;
      assert.ok(b.t.jahrestageAm("2026-10-18", true).some(item => item.kontaktId === "patient" && item.typ === "birthday"));
      assert.deepEqual(Array.from(policy.overview.groups), ["Patients"], "disabling must retain the previous group choice");
      assert.equal(JSON.stringify([b.t.daten().kontakte, b.t.daten().jahrestage]), records, "filtering must not alter provider records, groups or birthday sources");
      await b.t.wechsel("adressen");
      assert.equal(b.w.document.querySelector("#kontakt-gruppenausschluss"), null, "The exclusion dialog needs only one entry point in Notifications");
      b.t.oeffneEinstellungen();
      b.w.document.querySelector("#einst-tab-adressen").click();
      assert.ok(![...b.w.document.querySelectorAll("#einst-seite-adressen button")].some(button => button.textContent === "Exclude contact groups"));
      b.w.document.querySelector("#einst-tab-allgemein").click();
      const tray = b.w.document.querySelector("#allgemein-gruppe-tray");
      const send = b.w.document.querySelector("#notiz-versand-aktiv").closest("details");
      assert.equal(tray.nextElementSibling, send, "Send settings belong with the lower General option groups after Tray applet");
      b.w.document.querySelector("#einst-tab-erinnerung").click();
      const rulesButton = [...b.w.document.querySelectorAll("#einst-seite-erinnerung button")].find(button => button.textContent === "Exclude contact groups");
      assert.equal(rulesButton.style.marginBlock, "5mm");
      rulesButton.click();
      await new Promise(resolve => setImmediate(resolve));
      const master = b.w.document.querySelector("#gruppen-ausschluss-aktiv");
      assert.ok(master && !master.checked);
      assert.ok(!b.w.document.querySelector("#gruppen-ausschluss-bereich").closest("[hidden]"));
      assert.ok(!b.w.document.querySelector('[data-gruppe="Own group"]').closest("[hidden],[inert]"), "Actual custom groups must be available even before exclusions are enabled");
      master.click();
      const patientChoice = b.w.document.querySelector('[data-gruppe="Patients"]');
      assert.ok(!patientChoice.checked); patientChoice.click();
      const area = b.w.document.querySelector("#gruppen-ausschluss-bereich");
      area.value = "anniversaries"; area.dispatchEvent(new b.w.Event("change"));
      b.w.document.querySelector('[data-gruppe="Colleagues"]').click();
      area.value = "notifications"; area.dispatchEvent(new b.w.Event("change"));
      assert.ok(b.w.document.querySelector('[data-gruppe="Patients"]').checked);
      assert.ok(!b.w.document.querySelector('[data-gruppe="Colleagues"]').checked, "Group choices must be independent for each area");
      assert.ok(!b.w.document.querySelector('[data-gruppe="Own group"]').checked, "Unselected groups must stay unaffected");
      area.value = "overview"; area.dispatchEvent(new b.w.Event("change"));
      const scope = b.w.document.querySelector("#gruppen-ausschluss-umfang");
      scope.value = "appointments"; scope.dispatchEvent(new b.w.Event("change"));
      const workCalendar = b.w.document.querySelector('[data-kalender="work-calendar"]');
      assert.ok(workCalendar && !workCalendar.checked, "A synchronized work calendar must be explicitly selectable for vacation exclusions");
      workCalendar.click();
      area.value = "notifications"; area.dispatchEvent(new b.w.Event("change"));
      assert.equal(policy.enabled, false, "dialog changes must remain a draft before saving");
      master.click(); master.click();
      assert.ok(b.w.document.querySelector('[data-gruppe="Patients"]').checked, "disable/re-enable must retain draft group choices");
      b.w.document.querySelector("#gruppen-ausschluss-speichern").click();
      assert.ok(!b.w.document.querySelector("#gruppen-ausschluss"));
      assert.equal(b.t.daten().einstellungen.adressen.gruppenAusschluss.enabled, true);
      assert.deepEqual(Array.from(b.t.daten().einstellungen.adressen.gruppenAusschluss.notifications.groups), ["Patients"]);
      assert.deepEqual(Array.from(b.t.daten().einstellungen.adressen.gruppenAusschluss.anniversaries.groups), ["Patients", "Colleagues"]);
      // Vacation controls: ordinary contact-linked appointments, an explicitly
      // selected synchronized calendar and print-only omissions are independent.
      const savedPolicy = b.t.daten().einstellungen.adressen.gruppenAusschluss;
      assert.equal(savedPolicy.overview.scope, "appointments");
      assert.deepEqual(Array.from(savedPolicy.overview.calendars), ["work-calendar"]);
      savedPolicy.overview.scope = "appointments";
      savedPolicy.overview.groups = ["Patients"];
      savedPolicy.overview.calendars = ["work-calendar"];
      savedPolicy.overview.calendar = false;
      assert.equal(b.t.termineAm("2026-10-18", true).length, 3, "Overview-only exclusions must retain calendar appointments");
      assert.deepEqual(Array.from(b.t.termineAm("2026-10-18", true, undefined, "overview"), item => item.id), ["private-visit"]);
      savedPolicy.overview.calendar = true;
      assert.deepEqual(Array.from(b.t.termineAm("2026-10-18", true), item => item.id), ["private-visit"]);
      assert.equal(b.t.druckStoff("adressen").liste.length, 4, "Display exclusion must not silently alter contact print selection");
      savedPolicy.print.groups = ["Patients"];
      assert.ok(!b.t.druckStoff("adressen").liste.some(item => item.id === "patient"));
      assert.ok(b.t.druckStoff("adressen").liste.some(item => item.id === "colleague"));
      savedPolicy.print.scope = "appointments";
      savedPolicy.print.calendars = ["work-calendar"];
      assert.deepEqual(Array.from(b.t.termineAm("2026-10-18", true, undefined, "print"), item => item.id), ["private-visit"]);
      savedPolicy.overview.groups = []; savedPolicy.overview.calendars = [];
      assert.equal(b.t.termineAm("2026-10-18", true).length, 3, "Editing choices must immediately restore calendar entries");
      b.t.schliesseEinstellungen();
      savedPolicy.overview.groups = ["Patients"]; savedPolicy.overview.calendars = ["work-calendar"];
      savedPolicy.overview.calendar = false;
      Object.assign(b.t.zustand().kalender, { jahr: 2026, monat: 9, tag: "2026-10-18", ansicht: "month", uebersichtAb: null });
      await b.t.wechsel("kalender");
      assert.ok(b.w.document.querySelector('.mini-termin[data-termin-id="patient-visit"]'), "The actual month grid must retain appointments when only the overview is excluded");
      assert.deepEqual([...b.w.document.querySelectorAll(".termin-uebersicht .ue-titel")].map(node => node.textContent), ["Private"], "The actual appointment overview must use its own group rule");
      savedPolicy.overview.calendar = true;
      await b.t.wechsel("adressen"); await b.t.wechsel("kalender");
      assert.equal(b.w.document.querySelector('.mini-termin[data-termin-id="patient-visit"]'), null);
      assert.ok(b.w.document.querySelector('.mini-termin[data-termin-id="private-visit"]'), "Unselected groups must remain on the actual calendar");
      b.t.zustand().planer.jahr = 2026;
      const planner = b.t.oeffneDruckvorschau(null, "planer");
      const layout = planner.querySelector("#planer-druck-art"); layout.value = "month"; layout.dispatchEvent(new b.w.Event("change"));
      assert.ok(planner.querySelector(".druck-vorschau").textContent.includes("Private"));
      assert.ok(!planner.querySelector(".druck-vorschau").textContent.includes("Visit") && !planner.querySelector(".druck-vorschau").textContent.includes("Meeting"), "Planner print preview must honor the print-specific excluded groups/calendars");
      savedPolicy.print.groups = []; savedPolicy.print.calendars = [];
      layout.dispatchEvent(new b.w.Event("change"));
      assert.ok(planner.querySelector(".druck-vorschau").textContent.includes("Visit") && planner.querySelector(".druck-vorschau").textContent.includes("Meeting"), "Calendar hiding must not silently remove appointments from an independent planner printout");
      [...planner.querySelectorAll(".druck-fuss button")].find(button => button.textContent === "Cancel").click();
      savedPolicy.overview.groups = []; savedPolicy.overview.calendars = [];
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
      b.t.daten().einstellungen.adressen.gruppenAusschluss.overview.scope = "birthdays";
      b.t.daten().einstellungen.adressen.gruppenAusschluss.overview.groups = ["Patients"];
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
