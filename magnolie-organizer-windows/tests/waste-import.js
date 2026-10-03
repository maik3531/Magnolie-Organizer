"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const { spawnSync } = require("node:child_process"), { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../.."), scratch = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-waste-test-"));
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
const python = `import sys,os,json,pathlib
root=pathlib.Path(sys.argv[1]); sys.modules['gi']=None
sys.path.insert(0,str(root/'magnolie-organizer/pruefungen'))
from modul_laden import quellmodul_laden
m=quellmodul_laden('waste_fixture',root/'magnolie-organizer/bin/magnolie-organizer')
fixture=json.loads((root/'contracts/waste-calendar-v1.json').read_text())
print(json.dumps(m.muell_import_lesen(fixture['ics'].encode(),'waste.ics')))
`;
let parsed;
if (fs.existsSync(path.join(root, "magnolie-organizer/pruefungen/modul_laden.py"))) {
  parsed = spawnSync(process.env.MAGNOLIE_PYTHON || "python3", ["-c", python, root], { encoding: "utf8",
    env: { ...process.env, HOME: scratch, XDG_CONFIG_HOME: scratch, XDG_DATA_HOME: scratch, XDG_CACHE_HOME: scratch,
      XDG_STATE_HOME: scratch, XDG_RUNTIME_DIR: scratch, DBUS_SESSION_BUS_ADDRESS: "unix:path=/nonexistent-waste-fixture" } });
} else {
  const dotnet = process.env.MAGNOLIE_DOTNET || process.env.DOTNET_HOST_PATH || "dotnet";
  const runner = process.env.MAGNOLIE_CORE_TESTS || path.join(__dirname, "bin/Debug/net8.0/CoreTests.dll");
  if (!process.env.MAGNOLIE_CORE_TESTS) {
    const build = spawnSync(dotnet, ["build", path.join(__dirname, "CoreTests.csproj"), "--no-restore", "-v", "quiet"], { encoding: "utf8" });
    assert.equal(build.status, 0, build.error?.message || build.stderr || build.stdout);
  }
  parsed = spawnSync(dotnet, [runner, "--waste-import-fixture"], { encoding: "utf8" });
}
assert.equal(parsed.status, 0, parsed.stderr);
const fixture = JSON.parse(parsed.stdout);
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = []; let snapshots = 0;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => {
      snapshots++;
      assert.equal(m.reason, "pre-change");
      if (mode === "stale") w.OrganizerTest.daten().muelltermine[0].name = "Changed meanwhile";
      w.App.mutationsSnapshot({ token: m.token, ok: mode !== "snapshot-error", fehler: "Fixture snapshot failure" });
    });
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "tagmarkenStreifen, speichereJetzt: speichereJetzt,"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ neu: false, regional: { language: "en" }, daten: { einstellungen: { kalender: { muellkalenderAn: true } },
      termine: [{ id: "ordinary", datum: "2026-01-12", titel: "Keep ordinary appointment" }],
      muelltermine: [{ id: "manual", name: "Manual glass", von: "2026-01-01", intervallTage: 14, farbe: "#123456", art: "custom" }] } });
    const T = w.OrganizerTest;
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-kalender").click();
    const begin = payload => {
      const button = w.document.querySelector("[data-muell-import]"); assert.ok(button, "settings lacks direct waste import"); button.click();
      const request = messages.filter(m => m.cmd === "import" && m.art === "muell").at(-1); assert.ok(request?.muellToken);
      return w.App.importErgebnis({ ...JSON.parse(JSON.stringify(payload)), art: "muell", muellToken: request.muellToken });
    };
    const original = JSON.stringify(T.daten().muelltermine), appointments = JSON.stringify(T.daten().termine);
    const payload = mode === "bulk" ? { ...fixture, termine: Array.from({ length: 130 }, (_, i) => ({ ...fixture.termine[0],
      uid: "bulk-" + i, datum: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10) })) } : mode === "csv" ? { muellFormat: "csv", muellQuelle: "waste:csv:" + "b".repeat(64), datei: "waste.csv",
      zeilen: [["Datum", "Abfallart", "Ort", "Notiz"], ["12.01.2026", "Biotonne", "CSV point", "Keep CSV note"],
        ["13.01.2026", "Gelbe Tonne", "CSV point", ""]] } : fixture;
    const pending = begin(payload);
    assert.ok(w.document.querySelector(".muell-import-vorschau"));
    assert.equal(JSON.stringify(T.daten().muelltermine), original, "preview wrote waste dates");
    if (mode === "cancel") [...w.document.querySelectorAll(".muell-import-vorschau button")].find(b => b.textContent === "Cancel").click();
    else if (mode === "profile") w.App.init({ neu: false, daten: { muelltermine: [] } });
    else if (mode === "lock") T.zeigeSperrbildschirm(false);
    else {
      w.document.querySelector("[data-muell-import-anwenden]").click();
      if (mode === "changed-choice") {
        const checkbox = w.document.querySelector("[data-muell-import-typ]"); checkbox.checked = false; checkbox.dispatchEvent(new w.Event("change"));
        for (let i = 0; i < 500 && w.document.querySelector("[data-muell-import-anwenden]").disabled; i++) await tick();
        assert.equal(snapshots, 0);
        [...w.document.querySelectorAll(".muell-import-vorschau button")].find(b => b.textContent === "Cancel").click();
      }
      else {
      for (let i = 0; i < 500 && snapshots === 0; i++) await tick();
      await tick();
      if (["snapshot-error", "stale"].includes(mode)) [...w.document.querySelectorAll(".muell-import-vorschau button")].find(b => b.textContent === "Cancel").click();
      }
    }
    await Promise.race([pending, new Promise((_, reject) => w.setTimeout(() => reject(new Error("waste preview did not finish: " + mode)), 5000))]);
    assert.equal(JSON.stringify(T.daten().termine), mode === "profile" ? "[]" : appointments, "waste import altered ordinary appointments");
    if (["cancel", "lock", "snapshot-error", "changed-choice"].includes(mode)) { assert.equal(JSON.stringify(T.daten().muelltermine), original); return; }
    if (mode === "profile") { assert.equal(T.daten().muelltermine.length, 0); return; }
    if (mode === "stale") { assert.equal(T.daten().muelltermine.length, 1); assert.equal(T.daten().muelltermine[0].name, "Changed meanwhile"); return; }
    assert.equal(snapshots, 1);
    assert.equal(T.daten().muelltermine.find(m => m.id === "manual").farbe, "#123456");
    assert.equal(T.daten().muelltermine.length, mode === "bulk" ? 2 : mode === "csv" ? 3 : 6);
    assert.equal(T.muelltermineAm("2026-01-12").length, ["csv", "bulk"].includes(mode) ? 1 : 2);
    assert.equal(T.muelltermineAm("2026-01-13").length, 1, "exclusive ICS end date produced an extra collection");
    const marker = T.tagmarkenStreifen("2026-01-12", false).querySelector(".muell-marke");
    const manual = T.tagmarkenStreifen("2026-01-01", false).querySelector(".muell-marke");
    assert.equal(marker.querySelector("path").getAttribute("d"), manual.querySelector("path").getAttribute("d"));
    if (mode === "ics") {
      const dangerous = T.muelltermineAm("2026-03-03").find(m => m.name === "Schadstoffe");
      assert.ok(dangerous.hinweis.includes("First collection point") && dangerous.hinweis.includes("Second collection point") && dangerous.hinweis.includes("14:30"));
      assert.equal(T.muelltermineAm("2026-12-31").filter(m => m.importQuelle).length, 1);
      assert.equal(T.muelltermineAm("2027-01-01").filter(m => m.importQuelle).length, 0);
    }
    const beforeReplay = JSON.stringify(T.daten().muelltermine);
    const replay = begin(payload); w.document.querySelector("[data-muell-import-anwenden]").click(); await replay;
    assert.equal(JSON.stringify(T.daten().muelltermine), beforeReplay, "repeated import duplicated or regenerated dates");
    const saved = JSON.parse(JSON.stringify(T.daten())); w.App.init({ neu: false, daten: saved });
    assert.deepEqual(JSON.parse(JSON.stringify(T.daten().muelltermine)), JSON.parse(beforeReplay), "reload lost imported collections");
    if (mode === "bulk") assert.equal(T.daten().muelltermine.find(m => m.importQuelle).importierteTermine.length, 130, "64-rule limit truncated individual dates");
    if (mode === "ics") {
      T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-kalender").click();
      const corrected = JSON.parse(JSON.stringify(payload)); corrected.termine[0].datum = "2026-01-14";
      const update = begin(corrected); w.document.querySelector("[data-muell-import-anwenden]").click(); await update;
      assert.equal(T.muelltermineAm("2026-01-12").filter(m => m.art === "residual").length, 0);
      assert.equal(T.muelltermineAm("2026-01-14").filter(m => m.art === "residual").length, 1);
      assert.equal(T.daten().muelltermine.reduce((count, m) => count + (m.importierteTermine?.length || 0), 0), 7);
    }
  } finally { w.close(); }
}
(async () => {
  try {
    for (const web of require("./web-test-roots"))
      for (const mode of ["ics", "csv", "bulk", "cancel", "profile", "lock", "snapshot-error", "stale", "changed-choice"]) await check(web, mode);
    console.log("WASTE IMPORT PASSED: native ICS, CSV mapping, grouping, markers, replay, reload and transaction guards");
  } finally { fs.rmSync(scratch, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
