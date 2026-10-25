"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window, clean = value => JSON.parse(JSON.stringify(value));
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest, actor = "11111111-1111-4111-8111-111111111111", other = "22222222-2222-4222-8222-222222222222";
  try {
    for (const origin of ["notes", "organizer", ""]) {
      const base = { angelegt: 1000, geaendert: 2000, personalGeaendert: 2000, ursprungApp: origin };
      w.App.init({ daten: { personalSync: { actor_id: actor },
        notizen: [{ ...base, id: "note", titel: "Synthetic note", text: "Text", html: "Text", anhaenge: [] }],
        aufgaben: [{ ...base, id: "task", uid: "task-uid", titel: "Synthetic task", prio: 2 }] }, neu: false });
      const sent = clean(await T.personalSyncSnapshot(["notes", "tasks"], 14, "peer"));
      for (const record of sent.filter(record => record.kind !== "notebook")) assert.equal(record.value.origin_app, origin);
      w.App.init({ daten: { personalSync: { actor_id: other } }, neu: false });
      await T.personalSyncAnwenden(sent, {}, 14, "peer", ["notes", "tasks"]);
      assert.equal(T.daten().notizen[0].ursprungApp, origin); assert.equal(T.daten().aufgaben[0].ursprungApp, origin);
      const saved = clean(T.daten()); w.App.init({ daten: saved, neu: false });
      assert.equal(T.daten().notizen[0].ursprungApp, origin); assert.equal(T.daten().aufgaben[0].ursprungApp, origin);
      const legacy = clean(await T.personalSyncSnapshot(["notes", "tasks"], 3, "peer"));
      assert.ok(legacy.every(record => !("origin_app" in record.value)));
      assert.equal(T.daten().notizen[0].ursprungApp, origin); assert.equal(T.daten().aufgaben[0].ursprungApp, origin);
      const remote = sent.filter(record => record.kind !== "notebook").map(record => {
        const value = { ...record.value, title: "Changed elsewhere", modified_ms: 3000, origin_app: origin === "notes" ? "organizer" : "notes" };
        return { ...record, value, modified_ms: 3000, clock: [...record.clock, { actor_id: other, counter: 100 }] };
      });
      for (const record of remote) record.hash = await T.personalSyncHash(record.value);
      await T.personalSyncAnwenden(remote, {}, 14, "peer", ["notes", "tasks"]);
      if (origin) {
        assert.equal(T.daten().notizen[0].ursprungApp, origin, "Last editor replaced original note app");
        assert.equal(T.daten().aufgaben[0].ursprungApp, origin, "Last editor replaced original task app");
      }
    }
    console.log("PERSONAL PROVENANCE PASSED: " + web);
  } finally { w.close(); }
}
(async () => {
  for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
