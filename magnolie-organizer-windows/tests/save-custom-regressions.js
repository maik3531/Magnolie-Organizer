"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../..");
const windows = path.resolve(__dirname, "..");
const contracts = fs.existsSync(path.join(root, "contracts")) ? path.join(root, "contracts") : path.join(windows, "contracts");
const consent = JSON.parse(fs.readFileSync(path.join(contracts, "personal-custom-consent-v4-vectors.json")));
const tick = () => new Promise(resolve => setTimeout(resolve, 1));
const plain = value => JSON.parse(JSON.stringify(value));
const peer = { device_id: consent.other_source_id, own_device: true, remote_own_device: true,
  transport: "wifi", auto_wifi: true, custom_sync: { local: consent.remote, remote: consent.local },
  capabilities: { items: { personal_tasks_sync: { versions: [1, 2, 3, 4] } } } };

async function boot(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://save-custom.invalid/", pretendToBeVisual: true
  });
  const w = dom.window, messages = [], timers = [];
  let rejectBatch = 0, batchNumber = 0, rejectSave = false;
  w.setTimeout = (fn, delay) => { const timer = { fn, delay }; timers.push(timer); return timer; };
  w.clearTimeout = timer => { if (timer) timer.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w.crypto, "subtle", { value: webcrypto.subtle });
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text);
    if (message.cmd === "speichern" && rejectSave) throw new Error("synthetic local save rejection");
    if (message.art === "personal_sync.custom_batch" && ++batchNumber === rejectBatch)
      throw new Error("synthetic local Custom rejection");
    messages.push(message);
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,",
    "nachDauerhaftemSpeichern, personalCustomSenden, personalCustomBestaetigt, personalSyncSenden, speichereJetzt: speichereJetzt,"));
  await tick();
  w.App.init({ daten: { personalSync: { actor_id: consent.source_id },
    notizen: [{ id: "note", titel: "Synthetic", text: "original", html: "original" }],
    customOrganizer: { modules: [{ id: "tasks", type: "tasks", title: "Synthetic", items:
      Array.from({ length: 70 }, (_, i) => ({ id: "item-" + i, title: "Task " + i })) }] } },
    neu: false, regional: { language: "en", timeZone: "UTC" } });
  const t = w.OrganizerTest;
  const saves = () => messages.filter(x => x.cmd === "speichern");
  const batches = () => messages.filter(x => x.art === "personal_sync.custom_batch");
  const ack = (save = saves().at(-1), ok = true) => w.App.gespeichert({ id: save.id, ok });
  t.speichereJetzt(); ack();
  return { w, t, timers, messages, saves, batches, ack, close: () => w.close(),
    rejectBatch(number) { batchNumber = 0; rejectBatch = number; },
    rejectSave(value) { rejectSave = value; },
    restore() { const data = plain(t.daten()); data.notizen[0].text = "restored";
      data.notizen[0].html = "restored"; data.syncEpoch = "restored-epoch";
      data.syncMetadaten.syncEpoch = data.syncEpoch;
      w.App.journalWiederhergestellt({ ok: true, daten: data }); },
    async settle(promise, autoAck = true) {
      let result;
      promise.then(value => { result = { value }; }, error => { result = { error }; });
      const handled = new Set();
      for (let i = 0; i < 1000 && !result; i++) {
        await tick();
        if (autoAck) for (const save of saves()) if (!handled.has(save.id)) { handled.add(save.id); ack(save); }
      }
      assert.ok(result, "save-dependent Promise must settle, not block the chain");
      return result;
    }
  };
}

const cases = [
  ["AUR01 failed old save, restore, unchanged exit", async b => {
    b.t.daten().notizen[0].text = "failed old text"; b.t.speichereJetzt(); b.ack(undefined, false);
    b.restore(); const before = b.saves().length;
    b.t.speichereJetzt(true);
    assert.equal(b.saves().length, before, "unchanged restored state must not resend old text");
    assert.equal(b.messages.at(-1).cmd, "beenden_bereit");
    for (const callback of ["gesamtarchivImportiert", "sicherungWiederhergestellt"]) {
      b.t.daten().notizen[0].text = "obsolete"; b.t.speichereJetzt(); const old = b.saves().at(-1);
      b.ack(old, false);
      const data = plain(b.t.daten()); data.notizen[0].text = "archive restored";
      b.w.App[callback]({ ok: true, daten: data }); b.t.speichereJetzt(true);
      if (b.saves().at(-1).id !== old.id) {
        assert.equal(JSON.parse(b.saves().at(-1).text).notizen[0].text, "archive restored"); b.ack();
      }
      assert.equal(b.t.daten().notizen[0].text, "archive restored");
    }
    b.t.daten().notizen[0].text = "first exit save";
    b.t.nachDauerhaftemSpeichern(() => { b.t.daten().notizen[0].text = "second exit save"; b.t.speichereJetzt(); });
    b.t.speichereJetzt(true); b.ack();
    assert.notEqual(b.messages.at(-1).cmd, "beenden_bereit", "callback-triggered followup save must finish before exit");
    b.ack(); assert.equal(b.messages.at(-1).cmd, "beenden_bereit");
  }],
  ["AUR01 in-flight ACK invalidation and current edit preservation", async b => {
    b.t.daten().notizen[0].text = "in flight"; b.t.speichereJetzt(); const old = b.saves().at(-1);
    b.restore(); b.t.daten().notizen[0].text = "current edit"; b.t.speichereJetzt();
    const current = b.saves().at(-1); assert.notEqual(current.id, old.id);
    let effects = 0; b.t.nachDauerhaftemSpeichern(() => effects++);
    b.ack(old); b.ack(old, false); b.w.App.gespeichert({ ok: false });
    b.ack({ id: current.id + 500 }); assert.equal(effects, 0);
    b.ack(current); assert.equal(effects, 1);
    b.t.daten().notizen[0].text = "older request"; b.t.speichereJetzt(); const failed = b.saves().at(-1);
    b.t.daten().notizen[0].text = "newest edit"; b.t.speichereJetzt(); b.ack(failed, false);
    b.t.speichereJetzt(); assert.equal(JSON.parse(b.saves().at(-1).text).notizen[0].text, "newest edit");
    b.ack();
    const before = b.saves().length, pending = b.t.personalCustomSenden(peer, "manual");
    for (let i = 0; i < 1000 && b.saves().length === before; i++) await tick();
    const obsolete = b.saves().at(-1); b.restore();
    assert.ok((await b.settle(pending, false)).error, "restore must reject a save-dependent Custom operation");
    b.ack(obsolete); assert.equal(b.batches().length, 0);
    assert.equal((await b.settle(b.t.personalCustomSenden(peer, "manual"))).value, true);
  }],
  ["AUR05 asynchronous error settles Custom and allows retry", async b => {
    const pending = b.t.personalCustomSenden(peer, "manual");
    const before = b.saves().length;
    for (let i = 0; i < 1000 && b.saves().length === before; i++) await tick();
    b.ack(undefined, false);
    const failed = await b.settle(pending, false); assert.ok(failed.error); assert.equal(b.batches().length, 0);
    const retry = await b.settle(b.t.personalCustomSenden(peer, "manual")); assert.equal(retry.value, true);
    const normalPeer = { ...peer, custom_sync: {}, local_grants: { grants: { personal_notes_sync: true } },
      grants: { grants: { personal_notes_sync: true } } };
    const normal = await b.settle(b.t.personalSyncSenden(normalPeer, "manual"));
    assert.equal(typeof normal.value, "string");
    assert.ok(b.messages.some(message => message.art === "personal_sync.request"));
    b.rejectSave(true); b.t.daten().notizen[0].text = "local rejection";
    b.w.document.querySelector("#sicherung-bestaetigen").disabled = true;
    let effect = 0, error = 0; b.t.nachDauerhaftemSpeichern(() => effect++, () => error++);
    assert.equal(effect, 0); assert.equal(error, 1);
    assert.equal(b.w.document.querySelector("#sicherung-bestaetigen").disabled, false);
    b.rejectSave(false); b.t.daten().cycle = b.t.daten();
    b.t.nachDauerhaftemSpeichern(() => effect++, () => error++);
    assert.equal(effect, 0); assert.equal(error, 2);
    delete b.t.daten().cycle;
    b.t.nachDauerhaftemSpeichern(() => effect++, () => error++); b.ack(); assert.equal(effect, 1);
  }],
  ["AUR05 lost ACK fails closed and late ACK cannot release retry", async b => {
    b.t.daten().notizen[0].text = "lost ACK";
    let effect = 0, error = 0; b.t.nachDauerhaftemSpeichern(() => effect++, () => error++);
    const lost = b.saves().at(-1);
    b.t.daten().notizen[0].text = "original";
    const timeout = b.timers.findLast(timer => !timer.cancelled && timer.delay >= 10000 && timer.delay <= 120000);
    assert.ok(timeout, "native save must have a bounded ACK wait"); timeout.fn();
    assert.equal(effect, 0); assert.equal(error, 1);
    b.t.nachDauerhaftemSpeichern(() => effect++, () => error++);
    const retry = b.saves().at(-1); assert.notEqual(retry.id, lost.id);
    b.ack(lost); assert.equal(effect, 0); b.ack(retry); assert.equal(effect, 1);
    b.t.daten().notizen[0].text = "cancel on lock";
    b.t.nachDauerhaftemSpeichern(() => effect++, () => { throw new Error("synthetic callback error"); });
    b.t.nachDauerhaftemSpeichern(() => effect++, () => error++);
    const locked = b.saves().at(-1);
    b.w.App.init({ gesperrt: true }); b.ack(locked);
    assert.equal(effect, 1); assert.equal(error, 2, "one throwing callback must not strand other waiters");
  }],
  ...[1, 2].map(rejected => ["AUR06 local rejection at batch " + rejected + ", retry and scoped receipt", async b => {
    b.rejectBatch(rejected);
    const result = await b.settle(b.t.personalCustomSenden(peer, "auto_wifi"));
    assert.ok(result.error || result.value === false, "partial bridge handoff must not report success");
    assert.equal(b.t.daten().personalSync.custom_auto_hash, "", "incomplete handoff must not persist auto signature");
    assert.equal(b.batches().length, rejected - 1, "stop at the first rejected batch");
    const prefix = plain(b.batches()); b.rejectBatch(0);
    assert.equal((await b.settle(b.t.personalCustomSenden(peer, "auto_wifi"))).value, true);
    const retry = b.batches().slice(prefix.length);
    assert.equal(retry.length, 3);
    if (prefix.length) assert.deepEqual(retry[0].inhalt, prefix[0].inhalt);
    if (rejected === 1) {
      const previousHash = b.t.daten().personalSync.custom_auto_hash;
      b.t.daten().customOrganizer.modules[0].items[0].title = "changed before signature save";
      const saveCount = b.saves().length;
      const pending = b.t.personalCustomSenden(peer, "auto_wifi");
      for (let i = 0; i < 1000 && b.saves().length === saveCount; i++) await tick();
      b.ack();
      for (let i = 0; i < 1000 && b.saves().length < saveCount + 2; i++) await tick();
      assert.equal(b.saves().length, saveCount + 2, "auto signature is a separate post-handoff save");
      b.ack(undefined, false);
      assert.ok((await b.settle(pending, false)).error);
      assert.equal(b.t.daten().personalSync.custom_auto_hash, previousHash, "failed signature save restores exact prior hash");
      assert.equal((await b.settle(b.t.personalCustomSenden(peer, "auto_wifi"))).value, true);
    }
    b.t.daten().customOrganizer.modules[0].items = [];
    const start = b.batches().length;
    await b.settle(b.t.personalCustomSenden(peer, "manual"));
    const deletions = b.batches().slice(start);
    assert.equal(deletions.flatMap(x => x.inhalt.deletions).length, 70);
    const saveCount = b.saves().length;
    const receipt = b.t.personalCustomBestaetigt({ device_id: peer.device_id, body: deletions[0].inhalt });
    if (rejected === 2) {
      for (let i = 0; i < 1000 && b.saves().length === saveCount; i++) await tick();
      b.ack(undefined, false);
      assert.ok((await b.settle(receipt, false)).error, "receipt save error must settle its chain");
      assert.equal((await b.settle(b.t.personalCustomSenden(peer, "manual"))).value, true);
    } else await b.settle(receipt);
    assert.equal(Object.keys(b.t.daten().personalSync.custom_entities).length, 38, "receipt retires only its own batch");
  }])
];

(async () => {
  let failed = 0, total = 0;
  const roots = [path.join(windows, "app/web")];
  if (fs.existsSync(path.join(root, "magnolie-organizer/web"))) roots.push(path.join(root, "magnolie-organizer/web"));
  for (const web of roots) {
    const relative = path.relative(root, web);
    for (const [name, test] of cases) {
      const b = await boot(web); total++;
      try { await test(b); console.log("PASS " + relative + ": " + name); }
      catch (error) { failed++; console.error("FAIL " + relative + ": " + name + ": " + error.message); }
      finally { b.close(); }
    }
  }
  console.log(`${total - failed}/${total} save/Custom cases passed`);
  process.exitCode = failed ? 1 : 0;
})().catch(error => { console.error(error); process.exitCode = 1; });
