"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window;
  w.Date.now = () => 1790000000000;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest, clean = v => JSON.parse(JSON.stringify(v));
  const actor = "11111111-1111-4111-8111-111111111111", remoteActor = "22222222-2222-4222-8222-222222222222";
  const data = "data:image/png;base64,AQID";
  try {
    for (const format of [1, 2, 3]) for (const remoteWins of [false, true]) {
      w.App.init({ daten: { personalSync: { actor_id: actor }, notizen: [{ id: "same-note", titel: "Welcome",
        text: "Same content", html: "Same content", angelegt: 1, personalGeaendert: 10,
        anhaenge: [{ id: "attachment", name: "image.png", art: "image", daten: data }] }] }, neu: false });
      const baseline = (await T.personalSyncSnapshot(["notes"], format, "peer")).find(r => r.kind === "note");
      let remote;
      for (let i = 0; i < 100; i++) {
        const value = { ...clean(baseline.value), created_ms: 100 + i, modified_ms: 200 + i };
        const hash = await T.personalSyncHash(value);
        if ((hash < baseline.hash) === remoteWins) { remote = { ...clean(baseline), value, hash,
          modified_ms: value.modified_ms, clock: [{ actor_id: remoteActor, counter: 1 }] }; break; }
      }
      assert.ok(remote, JSON.stringify({ format, remoteWins, hash: baseline.hash }));
      const attachments = format >= 2 ? { [remote.value.attachments[0].sha256]: data } : {};
      const result = await T.personalSyncAnwenden([remote], attachments, format, "peer", ["notes"]);
      assert.equal(result.conflicts, 0); assert.equal(T.daten().notizen.length, 1);
      assert.equal(T.daten().notizen[0].anhaenge.length, 1, "timestamp convergence removed an unrepresented attachment");
      const snapshot = (await T.personalSyncSnapshot(["notes"], format, "peer")).find(r => r.kind === "note");
      assert.equal(snapshot.hash, remoteWins ? remote.hash : baseline.hash, "wire hash disagrees with the retained value");
      assert.equal((await T.personalSyncAnwenden([remote], attachments, format, "peer", ["notes"])).conflicts, 0);
      assert.equal(T.daten().notizen.length, 1);
      const changedValue = { ...remote.value, html: "<b>Same content</b>" };
      const changed = { ...remote, value: changedValue, hash: await T.personalSyncHash(changedValue),
        clock: [{ actor_id: remoteActor, counter: 2 }] };
      assert.equal((await T.personalSyncAnwenden([changed], attachments, format, "peer", ["notes"])).conflicts, 1);
      assert.equal(T.daten().notizen.length, 2, "a real formatting conflict was discarded");
    }
    console.log("PERSONAL NOTE TIMESTAMPS PASSED: " + web);
  } finally { w.close(); }
}
(async () => { for (const p of ["../app/web", "../../magnolie-organizer/web"]) await check(path.resolve(__dirname, p)); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
