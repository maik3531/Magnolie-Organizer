"use strict";
// #776: real canonical Linux/Windows UI; native transport replies are synthetic.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const clone = value => JSON.parse(JSON.stringify(value)), tick = () => new Promise(resolve => setImmediate(resolve));
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
// Frozen #775 exchange fixture lives with this test so the standalone Windows
// source archive can exercise the contract without the macOS development tree.
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "resources/system-contact-copy-exchange-v1.json"), "utf8"));
let checks = 0;
const eq = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const ok = (actual, label) => { assert.ok(actual, label); checks++; };
function copy(id, date = "1604-02-29") {
  const native = clone(fixture.records[0]); native.identifier = id;
  return { ...clone(fixture.expectedContact), id, uid: "independent-local-" + id, vorname: "Ada", nachname: "Lovelace",
    geburtstag: date, geburtstagJahrUnbekannt: date.startsWith("--"), sync: false, syncQuellen: {},
    nativeContactImport: { version: 1, copyKind: "public-fields", birthdayPolicy: "contact-only", revisionCoverage: "serialized-fields-only",
      identity: digest([fixture.source.sourceUID, id]), sourceUID: fixture.source.sourceUID, containerID: fixture.source.containerID,
      sourceTitle: fixture.source.title, nativeType: fixture.source.nativeType, identifier: id, revision: digest(native) },
    nativeContactRecord: native, futureCopyField: { keep: ["café", "cafe\u0301", 17] } };
}
function book(date = "1604-02-29") {
  return { kontakte: [copy("local-copy", date)],
    jahrestage: [{ id: "namesake", uid: "unlinked-annual", name: "Ada Lovelace", datum: "1990-02-28", typ: "birthday", kontaktId: "", sourceExtension: { keep: true } },
      { id: "deliberate", uid: "explicit-annual", name: "Ada Lovelace", datum: "2001-03-01", typ: "birthday", kontaktId: "local-copy", sourceExtension: [1, 2] }],
    einstellungen: { allgemein: { handbuchHinweisGezeigt: true }, erinnerung: { an: true, jahrestage: { an: true, stunde: 10 } } },
    futureRoot: { keep: [1, 2] } };
}
async function context(web, data = book()) {
  const b = await harness.exports.boot(web, clone(data)), seen = new Set();
  b.pump = async () => {
    for (let step = 0; step < 8; step++) {
      for (const message of [...b.messages]) {
        const key = message.cmd + ":" + (message.id || message.token || "");
        if (seen.has(key)) continue;
        if (message.cmd === "speichern") { seen.add(key); b.w.App.gespeichert({ id: message.id, ok: true }); }
        if (message.cmd === "mutations_snapshot") { seen.add(key); b.w.App.mutationsSnapshot({ token: message.token, ok: true }); }
      }
      await tick();
    }
  };
  b.settle = async promise => {
    let finished = false, result, failure;
    promise.then(value => { finished = true; result = value; }, error => { finished = true; failure = error; });
    for (let attempt = 0; attempt < 100 && !finished; attempt++) await b.pump();
    assert.ok(finished, "Actual UI operation settles within the bounded synthetic transport loop");
    if (failure) throw failure;
    return result;
  };
  b.save = async () => { b.t.speichereJetzt(); await b.pump(); return JSON.parse(b.saves().at(-1).text); };
  await b.save(); return b;
}
async function edit(b, contact) {
  if (b.t.zustand().sektion === "adressen") await b.t.wechsel("planer");
  b.t.zustand().adressen.auswahlId = contact.id; b.t.zustand().adressen.modus = "bearbeiten";
  await b.t.wechsel("adressen");
  const form = b.w.document.querySelector(".kontakt-formular"); ok(form, "Actual canonical contact editor opens"); return form;
}
function change(b, field, value) { field.value = value; field.dispatchEvent(new b.w.Event("input", { bubbles: true })); }
async function saveEditor(b, form) {
  const button = [...form.querySelectorAll(".kontakt-form-knoepfe button")].find(value => value.textContent === b.w.MagnolieI18n.gettext("Save changes"));
  ok(button, "Actual editor save action exists"); button.click(); await b.pump(); await b.save();
  eq(form.isConnected, false, "Valid contact edit closes the actual form");
}
async function mcp(b) {
  b.w.eval(fs.readFileSync(path.join(b.web, "mcp-protocol.js"), "utf8"));
  let sequence = 0;
  const call = async message => {
    const invocation = (++sequence).toString(16).padStart(48, "0");
    await b.settle(b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message }));
    const reply = b.messages.find(value => value.cmd === "mcp_antwort" && value.invocation === invocation);
    ok(reply, "Actual MCP bridge returns its bounded response"); return reply.response;
  };
  await call({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "Contact-only exchange test", version: "1" } } });
  await call({ jsonrpc: "2.0", method: "notifications/initialized" });
  return async (name, args) => {
    const response = await call({ jsonrpc: "2.0", id: sequence + 1, method: "tools/call", params: { name, arguments: args } });
    if (response.error || response.result?.isError) throw new Error(JSON.stringify(response));
    return response.result.structuredContent;
  };
}
(async () => {
  eq(harness.exports.roots.length, 2, "Both canonical product sources are required");
  for (const web of harness.exports.roots) {
    const start = checks;
    for (const date of ["1988-02-29", "--02-29", "1604-02-29", ""]) {
      const input = book(date), b = await context(web, input), { w, t } = b;
      try {
        const contact = t.daten().kontakte[0];
        eq([contact.geburtstag, contact.geburtstagJahrUnbekannt], [date, date.startsWith("--")], "Canonical initialization preserves the active date including explicit 1604");
        eq(t.daten().jahrestage.map(item => [item.id, item.kontaktId, item.datum]), [["namesake", "", "1990-02-28"], ["deliberate", "local-copy", "2001-03-01"]], "Initialization never links a namesake or reconciles explicit annual dates");
        eq(contact.nativeContactImport, input.kontakte[0].nativeContactImport, "Exact import provenance survives actual initialization");
        eq(contact.nativeContactRecord, input.kontakte[0].nativeContactRecord, "Exact native public record survives initialization");
        const odsBirthday = t.adressenOdsNutzlast([contact], ["geburtstag"]);
        eq(odsBirthday.spalten, date ? ["Birthday"] : [], "ODS includes only the independent active contact birthday");
        const numbers = (odsBirthday.zeilen[0][0]?.match(/\d+/g) || []).map(Number).sort((a, b) => a - b);
        eq(numbers, date.split("-").filter(Boolean).map(Number).sort((a, b) => a - b), "ODS retains day/month and an explicitly known year, including 1604");
        const stored = await b.save(), annuals = clone(t.daten().jahrestage), reminder = clone(t.daten().einstellungen.erinnerung);
        w.App.sicherungWiederhergestellt({ ok: true, daten: clone(stored) }); await b.save();
        eq(t.daten().kontakte[0].geburtstag, date, "Actual backup-restore callback preserves the date");
        eq(t.daten().jahrestage, annuals, "Backup restore preserves all existing annual records");
        eq(t.daten().einstellungen.erinnerung, reminder, "Backup restore creates no reminder preference");
        w.App.journalWiederhergestellt({ ok: true, daten: clone(stored) }); await b.pump();
        eq(t.daten().kontakte[0].geburtstag, date, "Actual journal-restore callback preserves the date");
        eq(t.daten().jahrestage, annuals, "Journal restore preserves independent annual records");
        const normalized = t.normalisiere(JSON.parse(JSON.stringify(t.daten())));
        eq(normalized.kontakte[0].nativeContactImport, contact.nativeContactImport, "JSON re-normalization preserves the policy marker");
        eq(normalized.kontakte[0].futureCopyField, input.kontakte[0].futureCopyField, "Unrelated contact extension fields remain intact");
        eq(b.messages.filter(value => ["eds_speichern", "sync"].includes(value.cmd)).length, 0, "Reading/restoring passive provenance starts no provider write or sync");
      } finally { b.close(); }
    }
    {
      const b = await context(web), { w, t } = b;
      try {
        const contact = t.daten().kontakte[0], evidence = JSON.stringify(contact.nativeContactRecord), annuals = JSON.stringify(t.daten().jahrestage);
        let form = await edit(b, contact), field = w.document.querySelector("#kontakt-geburtstag");
        ok(field && field.dataset.datumIso === "1604-02-29", "Shared birthday editor exposes the exact explicit year");
        ok(form.textContent.includes("Birthday stored with this contact; no calendar entry."), "Editor explains contact-only behavior");
        for (const invalid of ["31.02.2000", "12."]) {
          const before = JSON.stringify(contact); change(b, field, invalid); field.dispatchEvent(new w.Event("change", { bubbles: true }));
          const value = field.value; [...form.querySelectorAll(".kontakt-form-knoepfe button")].find(button => button.textContent === "Save changes").click();
          eq([form.isConnected, field.value, JSON.stringify(contact)], [true, value, before], "Invalid/incomplete date cannot clear or mutate a contact");
          eq(w.document.activeElement === field, true, "Invalid birthday retains focus and its draft");
          eq(w.document.querySelector("#zettel").textContent, "Please enter a valid birth date.", "Invalid date is explained");
        }
        change(b, field, "1604-02-29"); field.dispatchEvent(new w.Event("change", { bubbles: true }));
        change(b, w.document.querySelector("#kontakt-notiz"), "Local edit preserved across platforms"); await saveEditor(b, form);
        eq([contact.geburtstag, contact.notiz], ["1604-02-29", "Local edit preserved across platforms"], "Normal text edits preserve the independent birthday");
        eq(JSON.stringify(t.daten().jahrestage), annuals, "Editing cannot overwrite explicitly linked or namesake annuals");
        ok(t.kontaktKarte(contact).textContent.includes("1604"), "Actual contact card shows the explicit year");
        for (const [date, unknown] of [["1988-02-29", false], ["--02-29", true], ["1604-02-29", false], ["", false]]) {
          form = await edit(b, contact); field = w.document.querySelector("#kontakt-geburtstag");
          change(b, field, date); field.dispatchEvent(new w.Event("change", { bubbles: true })); await saveEditor(b, form);
          eq([contact.geburtstag, contact.geburtstagJahrUnbekannt], [date, unknown], "User can deliberately edit or clear the birthday");
          eq(t.normalisiere(clone(t.daten())).kontakte[0].geburtstag, date, "Edited birthday survives canonical reload");
          eq(JSON.stringify(t.daten().jahrestage), annuals, "Explicit date edit creates no implicit calendar change");
        }
        eq(JSON.stringify(contact.nativeContactRecord), evidence, "Local date edits retain original source evidence");
        const before = JSON.stringify(t.daten()), ods = t.adressenOdsNutzlast([contact], ["geburtstag"]), print = t.druckStoff("adressen");
        eq([ods.spalten, ods.zeilen], [[], [[]]], "ODS cannot fill an empty contact-only birthday from another annual");
        ok(t.druckSeite([contact], print).includes("Local edit preserved across platforms"), "Real print HTML uses the edited canonical contact");
        print.karte(contact);
        eq(JSON.stringify(t.daten()), before, "Card, print and ODS do not mutate dates, annuals or reminder rules");
        const ordinaryODS = t.adressenOdsNutzlast([{ id: "ordinary-namesake", vorname: "Ada", nachname: "Lovelace" }], ["geburtstag"]);
        eq(ordinaryODS.spalten.length, 1, "Ordinary ODS fallback keeps its existing behavior");
      } finally { b.close(); }
    }
    {
      const b = await context(web), { w, t } = b; b.web = web;
      try {
        const call = await mcp(b), contact = t.daten().kontakte[0], evidence = clone(contact.nativeContactRecord), annuals = clone(t.daten().jahrestage);
        const update = async fields => {
          const before = await call("organizer_contact_read", { id: contact.id });
          return call("organizer_contact_update", { id: contact.id, expected_revision: before.revision, ...fields });
        };
        for (const date of ["1988-02-29", "--02-29", "1604-02-29", ""]) {
          eq((await update({ birth_date: date })).persisted, true, "MCP uses the actual native-save acknowledgement path");
          eq([contact.geburtstag, contact.geburtstagJahrUnbekannt], [date, date.startsWith("--")], "MCP updates the independent active birthday");
          eq(t.daten().jahrestage, annuals, "MCP birth_date creates or alters no annual entry");
        }
        for (const invalid of ["2000-02-31", "--02-30", "12."]) {
          const before = JSON.stringify(contact);
          await assert.rejects(update({ birth_date: invalid }), /invalid_date|Invalid tool arguments/); checks++;
          eq(JSON.stringify(contact), before, "Invalid MCP date retains exact record");
        }
        await update({ birth_date: "--02-29", anniversaries: [{ type: "birthday", date: "2004-03-01" }, { type: "anniversary", date: "--06-15" }] });
        eq(contact.geburtstag, "--02-29", "Explicit annuals do not overwrite an independent contact birthday");
        eq(t.daten().jahrestage.filter(item => item.kontaktId === contact.id).map(item => [item.typ, item.datum]), [["birthday", "2004-03-01"], ["anniversary", "--06-15"]], "Deliberately requested MCP annuals retain their normal behavior");
        eq(contact.nativeContactRecord, evidence, "MCP edits do not rewrite native evidence");
        const saved = await b.save(); w.App.init({ daten: saved, neu: false, regional: { language: "en", timeZone: "UTC" } });
        eq(t.daten().kontakte[0].geburtstag, "--02-29", "Actual saved MCP bytes reopen unchanged");
        eq(t.daten().jahrestage.filter(item => item.kontaktId === contact.id).map(item => item.datum), ["2004-03-01", "--06-15"], "Reopen never reconciles explicit annuals to the separate birthday");
      } finally { b.close(); }
    }
    {
      const b = await context(web, { einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } }), { w, t } = b;
      try {
        const imported = copy("json-copy"), input = { kontaktQuelle: "datei:" + "c".repeat(64), kontakte: [imported] };
        const pending = w.App.importErgebnis(clone(input));
        for (let step = 0; step < 100 && w.document.querySelector("[data-import-anwenden]")?.disabled; step++) await b.pump();
        const apply = w.document.querySelector("[data-import-anwenden]"); ok(apply && !apply.disabled, "Actual JSON contact review becomes ready");
        apply.click(); await b.settle(pending); await b.save();
        eq(t.daten().kontakte.length, 1, "Explicit file review creates exactly one contact");
        const contact = t.daten().kontakte[0];
        eq(contact.geburtstag, "1604-02-29", "Actual reviewed JSON import preserves the explicit year");
        eq(contact.nativeContactImport, imported.nativeContactImport, "Actual JSON importer retains passive source provenance");
        eq(contact.nativeContactRecord, imported.nativeContactRecord, "Actual JSON importer retains public source fields");
        eq([contact.sync, Object.keys(contact.syncQuellen || {}).length, t.daten().jahrestage.length], [false, 0, 0], "File import activates neither sharing nor an implicit birthday annual");
      } finally { b.close(); }
    }
    {
      const b = await context(web), { t } = b;
      try {
        for (const meta of [undefined, { version: 2, copyKind: "public-fields", birthdayPolicy: "contact-only" },
          { version: 1, copyKind: "unknown", birthdayPolicy: "contact-only" }, { version: 1, copyKind: "public-fields", birthdayPolicy: "unknown" }]) {
          const normal = t.normalisiere({ kontakte: [{ id: "ordinary", vorname: "Ordinary", nachname: "Birthday", geburtstag: "1604-02-29", nativeContactImport: meta }] });
          eq([normal.kontakte[0].geburtstag, normal.jahrestage.length, normal.jahrestage[0].datum], ["--02-29", 1, "--02-29"], "Only the exact copy contract changes legacy behavior");
        }
      } finally { b.close(); }
    }
    {
      const b = await context(web), { w, t } = b;
      try {
        w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8")); w.MagnolieI18n.setLocale("de");
        const contact = t.daten().kontakte[0], form = await edit(b, contact), field = w.document.querySelector("#kontakt-geburtstag");
        ok(form.textContent.includes("Geburtstag am Kontakt gespeichert; kein Kalendereintrag."), "Actual compiled German catalog explains the separate birthday");
        const before = JSON.stringify(contact); change(b, field, "31.02.2000");
        [...form.querySelectorAll(".kontakt-form-knoepfe button")].find(button => button.textContent === "Änderungen speichern").click();
        eq(w.document.querySelector("#zettel").textContent, "Geben Sie ein gültiges Geburtsdatum ein.", "Actual compiled German catalog explains an invalid birthday");
        eq(JSON.stringify(contact), before, "German invalid draft preserves the contact");
      } finally { b.close(); }
    }
    {
      const b = await context(web, { kontakte: [{ id: "ordinary-editor", vorname: "Ordinary", nachname: "Editor", geburtstag: "1988-02-29" }] }), { w, t } = b;
      try {
        const contact = t.daten().kontakte[0], form = await edit(b, contact);
        eq(w.document.querySelector("#kontakt-geburtstag"), null, "Ordinary contacts retain their existing annual-entry editor");
        const date = form.querySelector(".kontakt-ereignis-datum"); ok(date, "Existing ordinary birthday annual remains editable");
        change(b, date, "1992-02-29"); date.dispatchEvent(new w.Event("change", { bubbles: true })); await saveEditor(b, form);
        eq([contact.geburtstag, t.daten().jahrestage.length, t.daten().jahrestage[0].datum], ["1992-02-29", 1, "1992-02-29"], "Ordinary editor still keeps the linked birthday in sync");
      } finally { b.close(); }
    }
    console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": " + (checks - start) + " contact-only birthday checks passed");
  }
  console.log(JSON.stringify({ contactOnlyBirthdayChecks: checks, canonicalGUIs: 2, nativeHostAcceptance: false }));
})().catch(error => { console.error(error); process.exitCode = 1; });
