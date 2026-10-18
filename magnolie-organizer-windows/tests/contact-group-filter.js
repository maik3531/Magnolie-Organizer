"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const watchdog = setTimeout(() => { console.error("Contact-group filter timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [
      { id: "office", firma: "Büro", vcardRoundtrip: ["CATEGORIES:Work,COWORKERS", "X-OWNED:provider"], providerMetadaten: { owned: { label: "keep" } } },
      { id: "family", vorname: "Alex", nachname: "Alpha", vcardRoundtrip: ["CATEGORIES:Famille"] },
      { id: "custom", vorname: "Owned", nachname: "Zulu", vcardRoundtrip: ["CATEGORIES:Owned\\, custom"] },
      { id: "ungrouped", vorname: "Owned", nachname: "Xray", vcardRoundtrip: ["CATEGORIES:MY CONTACTS"] }] });
    try {
      b.w.eval(fs.readFileSync(path.join(web, "contact-group-aliases.js"), "utf8"));
      if (b.saves().length) b.ack();
      const records = JSON.stringify(b.t.daten().kontakte);
      await b.t.wechsel("adressen");
      const select = b.w.document.querySelector("#kontakt-gruppenfilter");
      assert.ok(select);
      const ids = () => [...b.w.document.querySelectorAll('#inhalt-links [data-fokus^="kontakt:"]')].map(button => button.dataset.fokus.slice(8));
      const choose = value => { select.value = value; select.dispatchEvent(new b.w.Event("change", { bubbles: true })); };
      choose("group:Work"); assert.deepEqual(ids(), ["office"], "selected groups search across alphabet tabs");
      b.input('#kopf-links input[type="search"]', "Büro"); assert.deepEqual(ids(), ["office"]);
      b.input('#kopf-links input[type="search"]', "Alpha"); assert.deepEqual(ids(), [], "free text and group constraints must intersect");
      b.input('#kopf-links input[type="search"]', "");
      choose("none"); assert.deepEqual(ids(), ["ungrouped"], "hidden provider system membership is not a personal group");
      choose("group:Family"); assert.deepEqual(ids(), ["family"]);
      choose("group:Colleagues"); assert.deepEqual(ids(), ["office"], "multiple memberships remain searchable independently");
      choose("group:Owned, custom"); assert.deepEqual(ids(), ["custom"]);
      choose("group:Doctor"); assert.deepEqual(ids(), [], "empty standard groups remain selectable");
      choose("all"); assert.deepEqual(ids(), ["family"], "all groups restores the ordinary alphabet browser");
      choose("group:Work"); b.w.document.querySelector('[data-buchstabe="A"]').click();
      assert.equal(b.t.zustand().adressen.gruppenFilter, "all", "an explicit alphabet-tab selection restores alphabet browsing");
      assert.equal(JSON.stringify(b.t.daten().kontakte), records);
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0;
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "b".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args = {}) => (await rpc("tools/call", { name, arguments: args })).result;
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-contact-group-filter", version: "1" } });
      await rpc("notifications/initialized", {});
      const guiBefore = JSON.stringify(b.t.zustand().adressen), savesBefore = b.saves().length;
      const groups = ok(await call("organizer_contact_groups_list", { limit: 2 }));
      assert.equal(groups.entries.length, 2); assert.equal(groups.next_offset, 2);
      const rest = ok(await call("organizer_contact_groups_list", { offset: 2, expected_revision: groups.revision }));
      assert.ok([...groups.entries, ...rest.entries].some(group => group.name === "Doctor" && group.count === 0));
      const all = ok(await call("organizer_contacts_search", { limit: 2 }));
      assert.equal(all.total, 4); assert.equal(all.entries.length, 2); assert.equal(all.next_offset, 2);
      const next = ok(await call("organizer_contacts_search", { offset: 2, expected_revision: all.revision }));
      assert.equal(new Set([...all.entries, ...next.entries].map(item => item.id)).size, 4);
      const translated = ok(await call("organizer_contacts_search", { group_mode: "group", group: "Famille" }));
      assert.deepEqual(translated.entries.map(item => item.id), ["family"]);
      const work = ok(await call("organizer_contacts_search", { group_mode: "group", group: "Arbeit", query: "Büro" }));
      assert.deepEqual(work.entries.map(item => item.id), ["office"]);
      const none = ok(await call("organizer_contacts_search", { group_mode: "none" }));
      assert.deepEqual(none.entries.map(item => item.id), ["ungrouped"]);
      const empty = ok(await call("organizer_contacts_search", { group_mode: "group", group: "Doctor" })); assert.equal(empty.total, 0);
      const invalid = await call("organizer_contacts_search", { group_mode: "group" }); assert.equal(invalid.structuredContent.code, "invalid_selection");
      const stale = await call("organizer_contacts_search", { expected_revision: "0".repeat(64) }); assert.equal(stale.structuredContent.code, "conflict");
      assert.equal(JSON.stringify(b.t.zustand().adressen), guiBefore); assert.equal(b.saves().length, savesBefore);
      assert.equal(JSON.stringify(b.t.daten().kontakte), records);
      b.t.speichereJetzt(); const stored = JSON.parse(b.saves().at(-1).text); b.ack();
      const reload = await harness.exports.boot(web, stored);
      try { assert.equal(JSON.stringify(reload.t.daten().kontakte), records); } finally { reload.close(); }
      console.log("CONTACT GROUP FILTER PASS: actual group/no-group/empty/multiple/text GUI selection, translated memberships, shared MCP pagination/revision, unchanged provider data and serialized reload " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
