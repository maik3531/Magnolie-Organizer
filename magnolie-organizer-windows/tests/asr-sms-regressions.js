"use strict";

// Execute the complete current frontends with DOM events and a delayed ACK bridge.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const harnessPath = path.join(__dirname, "save-custom-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(harnessPath, "utf8").split("const cases = [")[0].replace(
  "nachDauerhaftemSpeichern, personalCustomSenden,",
  "oeffneSmsDialog, oeffneSmsPlanung, pruefeSmsPlanung, smsTextAnpassen, setPhone: value => telefonStand = value, nachDauerhaftemSpeichern, personalCustomSenden,") +
  "\nmodule.exports = { boot };", harnessPath);
const windowsWeb = path.resolve(__dirname, "../app/web");
const linuxRoot = process.env.MAGNOLIE_LINUX_SOURCE || path.resolve(__dirname, "../../magnolie-organizer");
const linuxWeb = path.join(linuxRoot, "web");
const roots = [windowsWeb];
if (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linuxRoot)) roots.push(linuxWeb);
const tick = () => new Promise(resolve => setTimeout(resolve, 2));
const plain = value => JSON.parse(JSON.stringify(value));
const captures = [];
const samples = ["Привет — 你好", "مرحبا بالعالم", "नमस्ते दुनिया", "日本語", "Прывітанне", "Привіт", "🙂 ❤️ 👍🏽 🧑‍💻", "Cafe\u0301 č ł İstanbul", "“Hello”…\tworld\u00a0!", "GSM ÄÖÜ ß é € ^{}\\[~]|", "  padded text\n "];
const contact = { id: "synthetic-contact", vorname: "Synthetic", nachname: "Only",
  telefon: "07700900123", mobil: "07700900124",
  telefone: [{ wert: "07700900123", typen: ["CELL"] }, { wert: "07700900124", typen: ["CELL"] }] };
function button(node, label) {
  const localized = node.ownerDocument.defaultView.MagnolieI18n.gettext(label);
  const found = [...node.querySelectorAll("button")].find(n => n.textContent === label || n.textContent === localized || n.getAttribute("aria-label") === localized);
  assert.ok(found, "button " + label); return found;
}
function configure(b) {
  const d = b.t.daten(); d.einstellungen.adressen.smsSchedulingEnabled = true;
  d.einstellungen.regional.homeCountry = "GB";
  b.t.setPhone({ peers: [], kdeconnect: { available: true, device_id: "a".repeat(32), device_fingerprint: "1".repeat(64) } });
  b.t.speichereJetzt(); b.ack();
}
const smsCalls = b => b.messages.filter(m => m.cmd === "kde_sms_senden");
function open(b, sample) {
  b.t.oeffneSmsPlanung(contact, "07700900123", sample);
  const dialog = b.w.document.querySelector(".sms-planung-dialog"); assert.ok(dialog); return dialog;
}
async function preview(b, dialog) {
  button(dialog, "Schedule SMS").click();
  return waitPreview(dialog);
}
async function waitPreview(dialog) {
  for (let i = 0; i < 100 && !dialog.querySelector(".sms-plan-vorschau:not(.verborgen)"); i++) await tick();
  return dialog.querySelector(".sms-plan-vorschau:not(.verborgen)");
}

async function before(b, label) {
  configure(b);
  const sample = samples[0], dialog = open(b, sample);
  button(dialog, "Schedule SMS").click();
  assert.equal(b.t.daten().smsPlanung.length, 1);
  assert.equal(b.t.daten().smsPlanung[0].text, "?????? - ??");
  assert.equal(dialog.querySelectorAll(".sms-plan-vorschau").length, 0);
  b.w.App.gesamtarchivImportiert({ ok: true, daten: { ...plain(b.t.daten()),
    smsPlanung: [{ id: "unknown-on-another-profile", nummer: "+447700900123", land: "GB", text: "Archive", zeit: 1, status: "planned" }] } });
  b.t.pruefeSmsPlanung(); b.ack();
  assert.equal(smsCalls(b).length, 1);
  console.log("BEFORE", label, "unconfirmed stored:", JSON.stringify(sample), "=>", JSON.stringify("?????? - ??"), "; unknown restored ID: 1 captured SMS");
}

const cases = [
  ["Unicode actual batch previews, cancel keeps draft and metadata, exact delayed dispatch", async b => {
    configure(b);
    for (const sample of samples) {
      const initial = b.t.daten().smsPlanung.length, dialog = open(b, sample);
      const row = dialog.querySelector(".sms-planung-zeile"), original = plain({ text: row._werte.text.value,
        nummer: row._werte.nummer.value, datum: row._werte.datum.value, uhrzeit: row._werte.uhrzeit.value });
      let p = await preview(b, dialog); assert.ok(p, "explicit preview before durable insertion");
      const expected = b.t.smsTextAnpassen(sample).text.trim();
      assert.equal(p.querySelector("pre").textContent, expected);
      assert.equal(b.t.daten().smsPlanung.length, initial);
      const staleConfirm = button(p, "Confirm SMS plans");
      button(p, "Cancel").click();
      assert.deepEqual(plain({ text: row._werte.text.value, nummer: row._werte.nummer.value,
        datum: row._werte.datum.value, uhrzeit: row._werte.uhrzeit.value }), original);
      assert.equal(b.t.daten().smsPlanung.length, initial);
      p = await preview(b, dialog); staleConfirm.click(); await tick();
      assert.equal(b.t.daten().smsPlanung.length, initial, "cancelled button cannot approve a later identical preview");
      p = await preview(b, dialog); button(p, "Confirm SMS plans").click(); await tick();
      assert.equal(b.t.daten().smsPlanung.length, initial + 1);
      const plan = b.t.daten().smsPlanung.at(-1);
      assert.equal(plan.text, expected); assert.equal(plan.originalText, sample); assert.equal(plan.land, "GB");
      assert.equal(b.t.normalisiere(b.t.daten()).smsPlanung.at(-1).originalText, sample);
      assert.ok(dialog.isConnected, "wait for durable save ACK before reporting success");
      b.ack(); assert.equal(dialog.isConnected, false);
      plan.zeit = 1; const n = smsCalls(b).length;
      b.t.pruefeSmsPlanung(); assert.equal(smsCalls(b).length, n);
      b.ack(); assert.equal(smsCalls(b).length, n + 1, JSON.stringify({ plan, saves: b.saves().map(s => ({ id: s.id, plans: JSON.parse(s.text).smsPlanung })) }));
      assert.equal(smsCalls(b).at(-1).text, expected); assert.equal(smsCalls(b).at(-1).land, "GB");
      assert.equal(smsCalls(b).at(-1).clientRef, "plan:" + plan.id);
      captures.push({ original: sample, ...plain(smsCalls(b).at(-1)) });
      b.t.speichereJetzt(); b.ack();
      console.log("CAPTURE", JSON.stringify(sample), "=>", JSON.stringify(expected));
    }
  }],
  ["batch edits/removal/addition/country and stale programmatic changes invalidate approval", async b => {
    configure(b); const dialog = open(b, samples[0]);
    const add = dialog.querySelector('[aria-label="Add another SMS"]'); add.click();
    const rows = dialog.querySelectorAll(".sms-planung-zeile");
    rows[1]._werte.text.value = samples[6]; rows[1]._werte.nummer.selectedIndex = 1;
    let p = await preview(b, dialog); assert.equal(p.querySelectorAll("pre").length, 2);
    const stale = button(p, "Confirm SMS plans");
    rows[0]._werte.text.value = "unreviewed 日本語";
    rows[0]._werte.text.dispatchEvent(new b.w.Event("input", { bubbles: true })); stale.click(); await tick();
    assert.equal(b.t.daten().smsPlanung.length, 0);
    p = await preview(b, dialog); rows[1]._werte.text.value = "changed without input event";
    button(p, "Confirm SMS plans").click(); await tick(); assert.equal(b.t.daten().smsPlanung.length, 0);
    p = await preview(b, dialog); b.t.daten().einstellungen.regional.homeCountry = "DE";
    button(p, "Confirm SMS plans").click(); await tick(); assert.equal(b.t.daten().smsPlanung.length, 0);
    b.t.daten().einstellungen.regional.homeCountry = "GB";
    p = await preview(b, dialog); add.click(); button(p, "Confirm SMS plans").click(); await tick();
    assert.equal(b.t.daten().smsPlanung.length, 0);
    button(dialog.querySelectorAll(".sms-planung-zeile")[2], "Remove").click();
    p = await preview(b, dialog); const exact = [...p.querySelectorAll("pre")].map(n => n.textContent);
    button(p, "Confirm SMS plans").click(); await tick(); b.ack();
    assert.deepEqual(plain(b.t.daten().smsPlanung.map(n => n.text)), exact);
    assert.equal(new Set(b.t.daten().smsPlanung.map(n => n.id)).size, 2);
  }],
  ["paused restored unknown IDs stay inert with live permission on; individual review and stable IDs", async b => {
    configure(b);
    const plans = ["unknown-a", "unknown-b"].map(id => ({ id, kontaktId: "", nummer: "+447700900123", land: "GB",
      text: "?????? - ??", originalText: samples[0], zeit: 1, status: "paused", clientRef: "", fehler: "" }));
    const restored = { ...plain(b.t.daten()), smsPlanung: plans };
    b.w.App.gesamtarchivImportiert({ ok: true, daten: restored });
    for (let i = 0; i < 3; i++) { b.t.pruefeSmsPlanung(); b.t.speichereJetzt(); b.ack(); }
    assert.equal(smsCalls(b).length, 0);
    assert.deepEqual(plain(b.t.daten().smsPlanung), plans);
    b.t.oeffneSmsPlanung(null);
    const dialog = b.w.document.querySelector(".sms-planung-dialog");
    button(dialog.querySelector(".sms-planung-eintrag"), "Review and enable").click();
    await waitPreview(dialog);
    let p = dialog.querySelector(".sms-plan-vorschau:not(.verborgen)"); assert.ok(p);
    assert.equal(p.querySelector("pre").textContent, plans[0].text);
    button(p, "Cancel").click(); assert.deepEqual(plain(b.t.daten().smsPlanung), plans);
    button(dialog.querySelector(".sms-planung-eintrag"), "Review and enable").click(); await waitPreview(dialog);
    p = dialog.querySelector(".sms-plan-vorschau:not(.verborgen)");
    button(p, "Enable this SMS plan").click(); await tick();
    assert.equal(smsCalls(b).length, 0); b.ack(); b.t.pruefeSmsPlanung(); b.ack();
    assert.equal(smsCalls(b).length, 1); assert.equal(smsCalls(b)[0].clientRef, "plan:unknown-a");
    assert.equal(b.t.daten().smsPlanung[1].status, "paused");
    assert.equal(b.t.daten().einstellungen.adressen.smsSchedulingEnabled, true);
  }],
  ["restore invalidates an open approval and a delayed save; failed plan save retains original draft", async b => {
    configure(b); let dialog = open(b, samples[0]), p = await preview(b, dialog);
    b.restore(); button(p, "Confirm SMS plans").click(); await tick();
    assert.equal(b.t.daten().smsPlanung.length, 0); assert.equal(smsCalls(b).length, 0);
    button(dialog, "Close").click(); dialog = open(b, samples[0]); p = await preview(b, dialog);
    button(p, "Confirm SMS plans").click(); await tick(); b.ack(undefined, false);
    assert.equal(dialog.querySelector("textarea").value, samples[0]); assert.equal(b.t.daten().smsPlanung.length, 0);
    p = await preview(b, dialog); button(p, "Confirm SMS plans").click(); await tick();
    const old = b.saves().at(-1); b.restore(); b.ack(old); assert.equal(smsCalls(b).length, 0);
  }],
  ["editing persisted payload during delayed save pauses it; re-enable failure cannot arm it", async b => {
    configure(b);
    const plan = { id: "exact", kontaktId: "", nummer: "+447700900123", land: "GB", text: "Reviewed", zeit: 1, status: "planned" };
    b.t.daten().smsPlanung = [plan]; b.t.pruefeSmsPlanung();
    plan.text = "unreviewed ???"; b.ack(); assert.equal(smsCalls(b).length, 0); assert.equal(plan.status, "paused");
    b.t.speichereJetzt(); b.ack(); b.t.oeffneSmsPlanung(null);
    const dialog = b.w.document.querySelector(".sms-planung-dialog");
    button(dialog, "Review and enable").click(); await waitPreview(dialog);
    button(dialog, "Enable this SMS plan").click();
    b.t.pruefeSmsPlanung(); assert.equal(plan.status, "planned", "enable ACK still pending; no reservation yet");
    b.ack(undefined, false); b.t.pruefeSmsPlanung();
    assert.equal(plan.status, "paused"); assert.equal(smsCalls(b).length, 0);
  }]
];

async function nativeRestores(file) {
  for (const scenario of JSON.parse(fs.readFileSync(file, "utf8"))) {
    for (const callback of ["journalWiederhergestellt", "sicherungWiederhergestellt", "gesamtarchivImportiert"]) {
      assert.ok(["windows", "linux"].includes(scenario.platform), "Unknown native restore platform");
      const web = scenario.platform === "windows" ? windowsWeb : linuxWeb;
      const b = await harness.exports.boot(web);
      try {
        configure(b); b.w.App[callback]({ ok: true, daten: scenario.data });
        assert.equal(b.t.daten().einstellungen.adressen.smsSchedulingEnabled, scenario.enabled);
        b.t.pruefeSmsPlanung(); b.t.speichereJetzt(); b.ack();
        if (scenario.partial) {
          if (scenario.enabled) { b.ack(); assert.equal(smsCalls(b).length, 1, "partial restore keeps live plan schedulable"); }
          else assert.equal(smsCalls(b).length, 0);
        } else {
          assert.equal(smsCalls(b).length, 0, "native-restored unknown ID must not dispatch");
          const plan = b.t.daten().smsPlanung[0]; assert.equal(plan.status, "paused");
          b.t.oeffneSmsDialog(contact);
          button(b.w.document.querySelector(".sms-dialog"), "SMS settings").click();
          const toggle = b.w.document.querySelector('.sms-einstellungen-dialog input[type="checkbox"]');
          if (toggle.checked) toggle.click(); toggle.click();
          b.t.pruefeSmsPlanung(); b.t.speichereJetzt(); b.ack();
          assert.equal(plan.status, "paused"); assert.equal(smsCalls(b).length, 0, "global toggle is not per-plan review");
          button(b.w.document.querySelector(".sms-einstellungen-dialog"), "Pending SMS messages").click();
          const dialog = b.w.document.querySelector(".sms-planung-dialog");
          button(dialog, "Review and enable").click();
          for (let i = 0; i < 100 && !dialog.querySelector(".sms-plan-vorschau:not(.verborgen)"); i++) await tick();
          button(dialog, "Enable this SMS plan").click();
          assert.equal(smsCalls(b).length, 0); b.ack(); b.ack();
          assert.equal(smsCalls(b).length, 1); assert.equal(smsCalls(b)[0].clientRef, "plan:" + plan.id);
          assert.equal(smsCalls(b)[0].text, scenario.data.smsPlanung[0].text);
          assert.equal(smsCalls(b)[0].land, "GB");
        }
        console.log("PASS NATIVE→FRONTEND", scenario.platform, callback, "live=" + scenario.enabled, "partial=" + scenario.partial);
      } finally { b.close(); }
    }
  }
}

(async () => {
  let count = 0;
  for (const web of roots) {
    if (process.argv.includes("--before")) { const b = await harness.exports.boot(web);
      try { await before(b, web); } finally { b.close(); } continue; }
    for (const [name, test] of cases) { const b = await harness.exports.boot(web);
      try { await test(b); console.log("PASS", web, name); count++; } finally { b.close(); } }
  }
  console.log("PASS", count, "ASR SMS frontend cases; all SMS calls captured, no native transport");
  if (process.argv.includes("--native-restores")) await nativeRestores(process.argv[process.argv.indexOf("--native-restores") + 1]);
  if (process.argv.includes("--capture-out")) fs.writeFileSync(process.argv[process.argv.indexOf("--capture-out") + 1], JSON.stringify(captures));
})().catch(error => { console.error(error); process.exitCode = 1; });
