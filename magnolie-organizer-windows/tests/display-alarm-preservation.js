"use strict";
// Refs #444: canonical DOM editor, real Python import/export, synthetic save ACK.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), cp = require("node:child_process");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../..");
const source = ["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:synthetic-alarm",
  "DTSTART:20300510T090000Z", "DTEND:20300510T100000Z", "SUMMARY:Synthetic alarm fixture",
  "BEGIN:VALARM", "ACTION:DISPLAY", 'TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma":-PT15M',
  "DESCRIPTION:Synthetic reminder", "X-OPAQUE-ALARM:keep", "END:VALARM",
  "BEGIN:VALARM", "ACTION:AUDIO", "TRIGGER;VALUE=DATE-TIME:20300510T083000Z", "END:VALARM",
  "END:VEVENT", "END:VCALENDAR"].join("\r\n") + "\r\n";
function python(mode, input) {
  return cp.execFileSync("python3", ["-c", `import json,sys
sys.path.insert(0, 'magnolie-organizer/pruefungen')
from test_nextcloud import m
value=sys.stdin.read()
if sys.argv[1]=='import': print(json.dumps(m.ics_lesen(value)))
else: print(m.ics_schreiben_termine(json.loads(value)))`, mode],
    { cwd: root, input, encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", TMPDIR: "/tmp/opencode" } });
}
const imported = JSON.parse(python("import", source));
const plain = value => JSON.parse(JSON.stringify(value));
function blocks(lines) {
  const result = []; let current = null;
  for (const line of lines) {
    if (line === "BEGIN:VALARM") current = [line];
    else if (current) { current.push(line); if (line === "END:VALARM") { result.push(current); current = null; } }
  }
  return result;
}
function boot(web, profile) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://alarm.test/", pretendToBeVisual: true
  });
  const w = dom.window, messages = [];
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.webkit = { messageHandlers: { bridge: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
  w.App.init({ daten: profile, neu: false, regional: { language: "en", timeZone: "UTC" } });
  return { w, t: w.OrganizerTest, messages, close: () => w.close() };
}
function save(app) {
  app.t.speichereJetzt();
  const message = app.messages.filter(item => item.cmd === "speichern").at(-1);
  assert.ok(message && Number.isInteger(message.id));
  app.w.App.gespeichert({ id: message.id, ok: true });
  return JSON.parse(message.text);
}
function edit(app, value) {
  const record = app.t.daten().termine[0];
  const editor = app.t.oeffneTerminBlatt(record, record.datum);
  const input = editor.querySelector(".tb-alarm-zahl");
  assert.ok(input); input.value = String(value);
  input.dispatchEvent(new app.w.Event("input", { bubbles: true }));
  editor.querySelector("#tb-fertig").click();
  return record;
}
for (const web of [path.join(root, "magnolie-organizer/web"), path.join(root, "magnolie-organizer-windows/app/web")]) {
  try {
    let profile = { termine: imported.termine };
    const audio = blocks(imported.termine[0].icsRoundtrip).find(block => block.includes("ACTION:AUDIO"));
    for (const value of [30, 45]) {
      const app = boot(web, profile);
      try {
        const priorId = app.t.daten().termine[0].alarme.find(alarm => alarm.bearbeitbar).id;
        const record = edit(app, value);
        assert.equal(app.w.document.querySelector("#tb-fertig"), null);
        const display = blocks(record.icsRoundtrip).find(block => block.includes("ACTION:DISPLAY"));
        assert.ok(display.includes("X-OPAQUE-ALARM:keep"), "Actual form dropped opaque DISPLAY property");
        assert.ok(display.includes('TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma":-PT' + value + "M"));
        assert.equal(record.alarme.find(alarm => alarm.bearbeitbar).id, priorId);
        assert.deepEqual(plain(blocks(record.icsRoundtrip).find(block => block.includes("ACTION:AUDIO"))), audio);
        profile = save(app);
        const exported = python("export", JSON.stringify(profile.termine));
        assert.ok(exported.includes("X-OPAQUE-ALARM:keep"));
        assert.ok(exported.includes("-PT" + value + "M"));
        assert.ok(exported.includes('X-OPAQUE-PARAM="alpha:beta;gamma"'));
        assert.ok(exported.includes(audio.join("\r\n")), "Python export changed readonly AUDIO sibling");
      } finally { app.close(); }
    }
    const repeat = boot(web, profile);
    try {
      const record = edit(repeat, 50); edit(repeat, 60);
      assert.ok(record.icsRoundtrip.includes('TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma":-PT60M'));
      assert.ok(record.icsRoundtrip.includes("X-OPAQUE-ALARM:keep"));
      assert.ok(record.icsRoundtrip.includes("DESCRIPTION:Synthetic reminder"));
      const clone = plain(record);
      assert.deepEqual(plain(blocks(repeat.t.spiegeleTerminInIcs(clone))), plain(blocks(record.icsRoundtrip)));
      clone.alarme.find(alarm => alarm.bearbeitbar).offsetMinuten++;
      assert.throws(() => repeat.t.spiegeleTerminInIcs(clone), error => error.code === "ambiguous-alarm");
      const related = plain(record); related.alarme.find(alarm => alarm.bearbeitbar).related = "END";
      assert.ok(repeat.t.spiegeleTerminInIcs(related, plain(record))
        .includes('TRIGGER;X-OPAQUE-PARAM="alpha:beta;gamma";RELATED=END:-PT60M'));
      let editor = repeat.t.oeffneTerminBlatt(record, record.datum);
      assert.equal(editor.querySelectorAll('#tb-alarme input[type="checkbox"]').length, 0);
      editor.querySelector(".tb-alarm-zahl").closest(".tb-alarm-zeile").querySelector("button").click();
      editor.querySelector("#tb-fertig").click();
      assert.deepEqual(plain(blocks(record.icsRoundtrip)), [audio]);
      assert.ok(!python("export", JSON.stringify(save(repeat).termine)).includes("X-OPAQUE-ALARM:keep"));
      editor = repeat.t.oeffneTerminBlatt(record, record.datum);
      [...editor.querySelectorAll("#tb-alarme button")].find(button => button.textContent === "Add reminder").click();
      const input = editor.querySelector(".tb-alarm-zahl"); input.value = "20";
      input.dispatchEvent(new repeat.w.Event("input", { bubbles: true })); editor.querySelector("#tb-fertig").click();
      assert.ok(record.icsRoundtrip.includes("TRIGGER;RELATED=START:-PT20M"));
      assert.deepEqual(plain(blocks(record.icsRoundtrip).find(block => block.includes("ACTION:AUDIO"))), audio);
      save(repeat);
    } finally { repeat.close(); }
    for (const ambiguous of ["duplicate-source", "colliding-edit"]) {
      const record = plain(imported.termine[0]);
      const duplicate = blocks(record.icsRoundtrip)[0].map(line => {
        if (line === "X-OPAQUE-ALARM:keep") return "X-OPAQUE-ALARM:other";
        return ambiguous === "colliding-edit" ? line.replace("-PT15M", "-PT30M") : line;
      });
      record.icsRoundtrip.push(...duplicate);
      // Reproject the added source, as on actual import.
      delete record.alarme;
      const app = boot(web, { termine: [record] });
      try {
        const before = JSON.stringify(app.t.daten());
        const saves = app.messages.filter(message => message.cmd === "speichern").length;
        edit(app, ambiguous === "colliding-edit" ? 30 : 45);
        assert.ok(app.w.document.querySelector("#tb-fertig"), "Ambiguous editor unexpectedly closed");
        assert.equal(JSON.stringify(app.t.daten()), before, "Ambiguous edit mutated the book");
        assert.equal(app.messages.filter(message => message.cmd === "speichern").length, saves);
        assert.ok(app.w.document.querySelector("#zettel").textContent.includes("Unsupported alarm"));
      } finally { app.close(); }
    }
    const fresh = boot(web, {});
    try {
      const editor = fresh.t.oeffneTerminBlatt(null, "2030-05-10");
      editor.querySelector("#tb-titel").value = "New synthetic appointment";
      [...editor.querySelectorAll("#tb-alarme button")].find(button => button.textContent === "Add reminder").click();
      editor.querySelector("#tb-fertig").click();
      assert.equal(fresh.w.document.querySelector("#tb-fertig"), null);
      assert.ok(save(fresh).termine[0].icsRoundtrip.includes("TRIGGER;RELATED=START:-PT15M"));
    } finally { fresh.close(); }
    console.log("PASS DISPLAY opaque preservation / actual form / fresh reopen / Python export:", web);
  } catch (error) { console.error(web, error); process.exitCode = 1; }
}
