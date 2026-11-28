"use strict";
// Refs #855: real desktop request/callback/import/save paths, synthetic native HTTP replies.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../..");
const ref = process.env.MAGNOLIE_HOLIDAY_SOURCE_REF || "";
const read = relative => ref ? execFileSync("git", ["show", `${ref}:${relative}`], { cwd: root, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 })
  : fs.readFileSync(path.join(root, relative), "utf8");
const tzRoot = path.join(root, "port-adapters/timezones");
const timezones = require(path.join(tzRoot, "projection-assets.cjs"))(name => fs.readFileSync(path.join(tzRoot, name)))["normative-timezones.js"].toString();
const plain = value => JSON.parse(JSON.stringify(value));
const fixedNow = Date.parse("2026-11-28T12:00:00Z");
const entry = (id, values = {}) => ({ id, von: "2026-10-12", bis: "2026-10-24", name: "Autumn fixture", art: "school-holiday",
  country: "DE", region: "DE-SN", regions: ["DE-SN"], nationwide: false, ...values });
const scope = (region = "DE-SN", art = "school-holiday", year = 2026, country = "DE") =>
  ({ country, region, art, von: `${year}-01-01`, bis: `${year}-12-31` });
function boot(web, entries, options = {}, saved) {
  const dom = new JSDOM(read(`${web}/index.html`), { runScripts: "outside-only", url: "https://holiday-cache.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  w.Date = class extends Date { constructor(...args) { super(...(args.length ? args : [fixedNow])); } static now() { return fixedNow; } };
  w.setTimeout = () => 0; w.clearTimeout = () => {}; w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "cacheTest";
  w.webkit = { messageHandlers: { cacheTest: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(read(`${web}/i18n.js`)); w.MagnolieI18n.setLocale("en"); w.eval(timezones); w.eval(read(`${web}/anwendung.js`));
  w.App.init({ daten: saved || { feiertage: entries, einstellungen: { ort: { land: "DE", region: "DE-SN", ferien: true, ...options } },
    termine: [{ id: "ordinary", datum: "2026-10-12", titel: "Ordinary recurrence", zeit: "09:00", wiederholung: { art: "weekly" } },
      { id: "synced", datum: "2026-10-12", endDatum: "2026-10-24", titel: "Herbstferien (SN)", sync: true }],
    notizen: [{ id: "note", titel: "Keep note", text: "Preserve" }], aufgaben: [{ id: "task", titel: "Keep task" }] },
    neu: false, regional: { language: "en", timeZone: "UTC" } });
  const t = w.OrganizerTest, untouched = JSON.stringify([t.daten().termine, t.daten().notizen, t.daten().aufgaben]);
  return { w, t, messages, entries: () => plain(t.daten().feiertage),
    start(yearCount = 1) {
      t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-ort").click();
      const year = w.document.querySelector("#ort-jahre"); year.value = yearCount === 1 ? "2026" : `2026+${yearCount - 1}`;
      const count = messages.filter(item => item.cmd === "feiertage").length;
      w.document.querySelector("#ort-abrufen").click();
      const requests = messages.filter(item => item.cmd === "feiertage"); assert.equal(requests.length, count + 1, "Actual UI request issued");
      return requests.at(-1);
    },
    reply(values) { w.App.feiertageErgebnis({ jahre: [2026], feiertage: [], ...values }); },
    save() { t.speichereJetzt(); const save = messages.filter(item => item.cmd === "speichern").at(-1); assert.ok(save);
      w.App.gespeichert({ id: save.id, ok: true }); return JSON.parse(save.text); },
    close() { try { assert.equal(JSON.stringify([t.daten().termine, t.daten().notizen, t.daten().aufgaben]), untouched,
      "Holiday retrieval preserves appointments, recurrence, synced records, notes and tasks"); } finally { w.close(); } }
  };
}
const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const find = (b, id) => b.entries().find(item => item.id === id);
for (const [name, old, options] of [
  ["foreign country", entry("old", { country: "AT", region: "AT-9", regions: ["AT-9"], art: "public-holiday" }), {}],
  ["other school region", entry("old", { region: "DE-BY", regions: ["DE-BY"] }), {}],
  ["school opt-out", entry("old"), { ferien: false }],
  ["foreign cross-year period", entry("old", { country: "CH", region: "CH-ZH", regions: ["CH-ZH"], von: "2025-12-22", bis: "2026-01-05" }), {}],
  ["unqualified legacy record", entry("old", { country: "", region: "", regions: [] }), {}],
  ["nationwide record with only local coverage", entry("old", { nationwide: true, regions: [] }), {}],
  ["different entry type", entry("old", { art: "public-holiday" }), {}],
  ["unrequested previous-year portion", entry("old", { von: "2025-12-22", bis: "2026-01-05" }), {}],
  ["unrequested next-year portion", entry("old", { von: "2026-12-22", bis: "2027-01-05" }), {}]
]) test(name, web => {
  const b = boot(web, [old], options);
  try { const before = b.entries(); b.start(); b.reply({ abrufbereiche: [scope()] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
for (const [name, coverage] of [
  ["missing legacy coverage", undefined], ["empty partial-failure coverage", []],
  ["public success with failed school retrieval", [scope("DE-SN", "public-holiday")]],
  ["forged foreign country", [scope("DE-SN", "school-holiday", 2026, "AT")]],
  ["unrequested region", [scope("DE-BY")]], ["unrequested whole country", [scope("")]],
  ["unrequested year", [scope("DE-SN", "school-holiday", 2027)]],
  ["malformed time window", [{ ...scope(), bis: "2026-12-30" }]],
  ["unknown kind", [{ ...scope(), art: "all" }]],
  ["invalid coverage entries", [null, {}, "invalid"]]
]) test(name, web => {
  const b = boot(web, [entry("old")]);
  try { const before = b.entries(); b.start(); b.reply({ abrufbereiche: coverage }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("successful empty selected-region reply removes only covered record", web => {
  const b = boot(web, [entry("old"), entry("other", { region: "DE-BY", regions: ["DE-BY"] })]);
  try { b.start(); b.reply({ abrufbereiche: [scope()] }); assert.equal(find(b, "old"), undefined); assert.ok(find(b, "other")); }
  finally { b.close(); }
});
test("public visibility is independent of replacement authority", web => {
  const b = boot(web, [entry("old", { art: "public-holiday" })], { feiertage: false });
  try { b.start(); b.reply({ abrufbereiche: [scope("DE-SN", "public-holiday")] }); assert.equal(b.entries().length, 0); }
  finally { b.close(); }
});
test("whole-country retrieval replaces nationwide and unqualified regional rows of known country", web => {
  const b = boot(web, [entry("national", { nationwide: true, art: "public-holiday", regions: [] }),
    entry("unqualified", { art: "public-holiday", region: "", regions: [] }), entry("school")], { region: "" });
  try { b.start(); b.reply({ abrufbereiche: [scope("", "public-holiday")] }); assert.deepEqual(b.entries().map(item => item.id), ["school"]); }
  finally { b.close(); }
});
test("partial aggregate retains only unaffected region and a consistent label", web => {
  const old = entry("old", { name: "Autumn fixture (Bavaria, Saxony)", region: "DE-BY,DE-SN", regions: ["DE-BY", "DE-SN"], regionName: "Bavaria, Saxony" });
  const b = boot(web, [old]);
  try { const input = JSON.stringify(old), cacheObject = b.t.daten().feiertage[0], before = JSON.stringify(cacheObject);
    b.start(); b.reply({ abrufbereiche: [scope()], feiertage: [entry("ignored", { von: "2026-10-13", bis: "2026-10-25" })] });
    const retained = find(b, "old"); assert.deepEqual(retained.regions, ["DE-BY"]); assert.equal(retained.region, "DE-BY");
    assert.ok(!retained.name.includes("Saxony")); assert.ok(!retained.regionName.includes("Saxony"));
    assert.equal(JSON.stringify(cacheObject), before, "Original aggregate object is not mutated"); assert.equal(JSON.stringify(old), input);
    assert.equal(b.entries().length, 2); assert.ok(b.entries().some(item => item.von === "2026-10-13"));
  } finally { b.close(); }
});
test("all-regions partial failure preserves failed-region cache", web => {
  const b = boot(web, [entry("saxony"), entry("bavaria", { region: "DE-BY", regions: ["DE-BY"] })], { alleRegionen: true });
  try { const request = b.start(); assert.ok(request.regionen.some(item => item[0] === "DE-BY"));
    b.reply({ abrufbereiche: [scope()] }); assert.equal(find(b, "saxony"), undefined); assert.ok(find(b, "bavaria")); }
  finally { b.close(); }
});
test("complete adjacent-year coverage can replace a cross-year period", web => {
  const b = boot(web, [entry("old", { von: "2026-12-22", bis: "2027-01-05" })]);
  try { b.start(2); b.reply({ jahre: [2026, 2027], abrufbereiche: [scope(), scope("DE-SN", "school-holiday", 2027)] }); assert.equal(b.entries().length, 0); }
  finally { b.close(); }
});
test("failed adjacent-year portion is retained", web => {
  const b = boot(web, [entry("old", { von: "2026-12-22", bis: "2027-01-05" })]);
  try { const before = b.entries(); b.start(2); b.reply({ jahre: [2026, 2027], abrufbereiche: [scope()] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("empty requested year does not touch later-year rows", web => {
  const b = boot(web, [entry("old", { von: "2028-01-01", bis: "2028-01-01" })]);
  try { const before = b.entries(); b.start(); b.reply({ abrufbereiche: [scope()] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("cross-year repeats without complete coverage are idempotent and retain id", web => {
  const old = entry("old", { von: "2025-12-22", bis: "2026-01-05" }), b = boot(web, [old]);
  try { b.start(); const reply = { abrufbereiche: [scope()], feiertage: [old, { ...old, id: "provider-repeat" }] };
    b.reply(reply); b.reply(reply); assert.equal(b.entries().length, 1); assert.equal(b.entries()[0].id, "old"); }
  finally { b.close(); }
});
test("legacy repeated replies merge without deleting other cache", web => {
  const b = boot(web, [entry("foreign", { country: "AT", region: "AT-9", regions: ["AT-9"] })]);
  try { b.start(); const reply = { feiertage: [entry("incoming")] }; b.reply(reply); const id = b.entries().find(item => item.country === "DE").id;
    b.reply(reply); assert.equal(b.entries().length, 2); assert.ok(find(b, "foreign")); assert.ok(find(b, id)); }
  finally { b.close(); }
});
test("nationwide repeat ignores lookup-region label", web => {
  const b = boot(web, [entry("old", { nationwide: true, regions: [], name: "National fixture (all states)", regionName: "all states", region: "DE-BY,DE-SN" })]);
  try { b.start(); b.reply({ feiertage: [entry("new", { nationwide: true, regions: [], name: "National fixture", regionName: "" })] });
    assert.equal(b.entries().length, 1); assert.equal(b.entries()[0].id, "old"); }
  finally { b.close(); }
});
test("failed native request preserves cache and retrieval metadata", web => {
  const b = boot(web, [entry("old")]);
  try { const before = b.entries(), metadata = plain(b.t.daten().einstellungen.ort); b.start(); b.reply({ fehler: "Offline fixture" });
    assert.deepEqual(b.entries(), before); assert.deepEqual(plain(b.t.daten().einstellungen.ort), metadata); }
  finally { b.close(); }
});
test("response after region change cannot mutate cache", web => {
  const b = boot(web, [entry("old")]);
  try { const before = b.entries(); b.start(); b.t.daten().einstellungen.ort.region = "DE-BY";
    b.reply({ abrufbereiche: [scope()], feiertage: [entry("new")] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("coverage without a current request cannot clear data", web => {
  const b = boot(web, [entry("old")]);
  try { const before = b.entries(); b.reply({ abrufbereiche: [scope()] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("save and restart preserve unaffected countries and refined regional remainder", web => {
  const b = boot(web, [entry("combined", { region: "DE-BY,DE-SN", regions: ["DE-BY", "DE-SN"] }),
    entry("foreign", { country: "CH", region: "CH-ZH", regions: ["CH-ZH"] })]);
  try { b.start(); b.reply({ abrufbereiche: [scope()] }); const expected = b.entries();
    const restarted = boot(web, [], {}, b.save()); try { assert.deepEqual(restarted.entries(), expected); } finally { restarted.close(); }
  } finally { b.close(); }
});
for (const art of ["public-holiday", "school-holiday"]) test(`repeated narrow refresh with broader provider regions stays bounded: ${art}`, web => {
  const old = entry("old", { art, region: "DE-SN,DE-BY", regions: ["DE-SN", "DE-BY"] });
  const b = boot(web, [old]);
  try {
    for (let i = 0; i < 4; i++) {
      b.start(); b.reply({ abrufbereiche: [scope("DE-SN", art)], feiertage: [old] });
      assert.equal(b.entries().length, 1, `Fresh request ${i + 1} cannot accumulate regional remainders`);
      assert.deepEqual(b.entries()[0].regions.slice().sort(), ["DE-BY", "DE-SN"]);
    }
    b.t.daten().einstellungen.ort.region = "DE-BY";
    assert.equal(b.t.feiertageAm("2026-10-12", true).filter(item => item.art === art && item.name.includes("Autumn fixture")).length, 1);
  } finally { b.close(); }
});
test("equivalent remainders formed by subtraction are consolidated by a positive row", web => {
  const b = boot(web, [entry("one", { region: "DE-SN,DE-BY", regions: ["DE-SN", "DE-BY"] }),
    entry("two", { region: "DE-SN,DE-BY", regions: ["DE-SN", "DE-BY"] })]);
  try { b.start(); b.reply({ abrufbereiche: [scope()], feiertage: [entry("new")] });
    assert.equal(b.entries().length, 1); assert.deepEqual(b.entries()[0].regions.slice().sort(), ["DE-BY", "DE-SN"]); }
  finally { b.close(); }
});
test("contradictory existing geography survives whole-country coverage", web => {
  const b = boot(web, [entry("ambiguous", { country: "DE", region: "AT-9", regions: ["AT-9"], art: "public-holiday" })], { region: "" });
  try { const before = b.entries(); b.start(); b.reply({ abrufbereiche: [scope("", "public-holiday")] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("unknown free-text regions are not conflated during a legacy merge", web => {
  const b = boot(web, [entry("bavaria", { country: "DE", region: "Bayern", regions: [] })]);
  try { b.start(); b.reply({ feiertage: [entry("new", { country: "DE", region: "Berlin", regions: [] })] });
    assert.equal(b.entries().length, 2); assert.ok(find(b, "bavaria")); }
  finally { b.close(); }
});
test("duplicate unbound legacy callback cannot add an unqualified copy", web => {
  const b = boot(web, []);
  try { b.start(); const row = { von: "2026-01-01", bis: "2026-01-01", name: "Legacy national fixture", art: "public-holiday", nationwide: true };
    b.reply({ feiertage: [row] }); const before = b.entries(); b.reply({ feiertage: [row] }); assert.deepEqual(b.entries(), before); }
  finally { b.close(); }
});
test("location status counts matching cache without attributing a pending or past fetch", web => {
  const b = boot(web, [
    entry("saxon", { art: "public-holiday" }), entry("bavarian-school", { region: "DE-BY", regions: ["DE-BY"] }),
    entry("vienna", { country: "AT", region: "AT-9", regions: ["AT-9"] }),
    entry("unqualified", { country: "", region: "", regions: [] })
  ], { abgerufen: 1764000000000, jahre: [2025] });
  try {
    const d = b.w.document, status = () => d.querySelector("#ort-stand").textContent;
    const change = (selector, value) => {
      const select = d.querySelector(selector); select.value = value;
      select.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    };
    const before = b.entries();
    b.start();
    assert.equal(status(), "Retrieving holidays …");
    change("#ort-region", "DE-BY");
    assert.match(status(), /Bavaria.*\b1 holiday period\b/);
    assert.doesNotMatch(status(), /Retrieving|Retrieved|2025/);
    b.reply({ abrufbereiche: [scope("DE-SN", "public-holiday")] });
    assert.match(status(), /Bavaria.*\b1 holiday period\b/);
    assert.equal(d.querySelector("#ort-abrufen").disabled, false);
    change("#ort-land", "AT");
    assert.match(status(), /\b1 holiday period\b/);
    assert.doesNotMatch(status(), /Bavaria|Retrieved|2025/);
    change("#ort-land", "");
    assert.equal(status(), "Choose a country first.");
    assert.deepEqual(b.entries(), before);
  } finally { b.close(); }
});

const france = (id, region, values = {}) => entry(id, { name: id, country: "FR", region, regions: [region], ...values });
test("France exposes verified subdivisions and explicitly keeps the unfiltered request", web => {
  const b = boot(web, [], { land: "FR", region: "", alleRegionen: true });
  try {
    const request = b.start();
    const d = b.w.document;
    assert.deepEqual([...d.querySelector("#ort-region").options].map(node => node.value),
      ["", "FR-ZA", "FR-ZB", "FR-ZC", "FR-CO", "FR-GP", "FR-GY", "FR-MQ", "FR-YT", "FR-RU", "FR-BL", "FR-MF", "FR-SP"]);
    assert.equal(d.querySelector("#ort-region").options[0].textContent, "All");
    assert.equal(d.querySelector("#ort-alle-regionen"), null);
    assert.deepEqual([request.land, request.region, request.regionen, request.regionErforderlich, request.ferien],
      ["FR", "", [], false, true]);
    b.reply({ abrufbereiche: [scope("", "school-holiday", 2026, "FR")] });
    assert.match(d.querySelector("#ort-stand").textContent, /coverage could not be confirmed for 2026/);
    const picker = d.querySelector("#ort-region");
    picker.value = "FR-ZB";
    const priorRequests = b.messages.filter(item => item.cmd === "feiertage").length;
    picker.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(b.messages.filter(item => item.cmd === "feiertage").length, priorRequests);
    assert.doesNotMatch(d.querySelector("#ort-stand").textContent, /could not be confirmed/);
    assert.equal(b.start().region, "FR-ZB");
  } finally { b.close(); }
});
test("French incomplete school year merges its verified periods and preserves old dates", web => {
  const b = boot(web, [france("old-corsica-autumn", "FR-CO"), france("other-zone", "FR-ZA")],
    { land: "FR", region: "FR-CO" });
  try {
    b.start();
    b.reply({ feiertage: [france("published-term", "FR-CO", { von: "2026-02-01", bis: "2026-02-14" })],
      abrufbereiche: [scope("FR-CO", "school-holiday", 2026, "FR")] });
    assert.ok(find(b, "old-corsica-autumn") && find(b, "other-zone"));
    assert.ok(b.entries().some(item => item.name === "published-term"));
    assert.match(b.w.document.querySelector("#ort-stand").textContent, /coverage could not be confirmed for 2026/);
  } finally { b.close(); }
});
test("French nationwide public holidays remain applicable and full school response replaces only its subdivision", web => {
  const national = france("national-holiday", "", { art: "public-holiday", nationwide: true, regions: [] });
  const b = boot(web, [france("outdated-zone-a", "FR-ZA"), france("other-zone", "FR-ZB")], { land: "FR", region: "FR-ZA" });
  try {
    b.start();
    b.reply({ feiertage: [
      france("winter-start", "FR-ZA", { von: "2025-12-21", bis: "2026-01-04", regions: ["FR-ZA", "FR-ZB"] }),
      france("winter-end", "FR-ZA", { von: "2026-12-20", bis: "2027-01-03", regions: ["FR-ZA", "FR-ZB"] }), national
    ], abrufbereiche: [scope("FR-ZA", "school-holiday", 2026, "FR")] });
    assert.equal(find(b, "outdated-zone-a"), undefined);
    assert.ok(find(b, "other-zone"));
    assert.ok(b.t.feiertageAm(national.von, true).some(item => item.name === national.name));
    assert.doesNotMatch(b.w.document.querySelector("#ort-stand").textContent, /could not be confirmed/);
    const reopened = boot(web, [], {}, b.save());
    try { assert.deepEqual(reopened.entries(), b.entries()); } finally { reopened.close(); }
  } finally { b.close(); }
});
for (const wrong of [
  { feiertage: [france("wrong-subdivision", "FR-ZB")] },
  { feiertage: [france("wrong-country", "BE-FR", { country: "BE" })] },
  { jahre: [2027] }
]) test(`French misplaced response retains cache and status: ${JSON.stringify(wrong)}`, web => {
  const b = boot(web, [france("old", "FR-ZA")], { land: "FR", region: "FR-ZA" });
  try {
    const before = b.entries(), settings = plain(b.t.daten().einstellungen.ort);
    b.start();
    b.reply({ abrufbereiche: [scope("FR-ZA", "school-holiday", 2026, "FR")], ...wrong });
    assert.deepEqual(b.entries(), before);
    assert.deepEqual(plain(b.t.daten().einstellungen.ort), settings);
    assert.equal(b.w.document.querySelector("#ort-stand").textContent, "Retrieval failed.");
  } finally { b.close(); }
});

for (const [land, region, other, administrative, groups] of [
  ["BE", "BE-FR", "BE-NL", "BE-WAL", ["BE-DE", "BE-FR", "BE-NL"]],
  ["NL", "NL-NO", "NL-MI", "NL-NH", ["NL-NO", "NL-MI", "NL-ZU"]]
]) {
  const groupRow = (id, code = region, values = {}) => entry(id, { name: id, country: land, region: code, regions: [code], ...values });
  const national = id => groupRow(id, "", { art: "public-holiday", nationwide: true, regions: [] });
  const local = id => groupRow(id, administrative, { art: "public-holiday" });
  const coverage = [scope("", "public-holiday", 2026, land), scope(region, "school-holiday", 2026, land)];
  test(`${land}: normal group picker and deliberate unfiltered request`, web => {
    const b = boot(web, [], { land, region: "", alleRegionen: true });
    try {
      const request = b.start(), d = b.w.document;
      assert.deepEqual([...d.querySelector("#ort-region").options].map(node => node.value), ["", ...groups]);
      assert.equal(d.querySelector("#ort-alle-regionen"), null);
      assert.deepEqual([request.region, request.regionen, request.regionErforderlich], ["", [], false]);
      b.reply({});
      const picker = d.querySelector("#ort-region");
      picker.value = region; picker.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.equal(b.messages.filter(item => item.cmd === "feiertage").length, 1);
      assert.equal(b.start().region, region);
    } finally { b.close(); }
  });
  test(`${land}: a selected group replaces only its term dates and the national public calendar`, web => {
    const b = boot(web, [groupRow("old-school"), groupRow("other-school", other), national("old-national"), local("old-local")], { land, region });
    try {
      b.start();
      b.reply({ abrufbereiche: coverage, feiertage: [
        groupRow("new-school", region, { regions: [region, other] }),
        groupRow("winter-start", region, { von: "2025-12-22", bis: "2026-01-04" }),
        groupRow("winter-end", region, { von: "2026-12-21", bis: "2027-01-04" }),
        national("new-national"), local("new-local") ] });
      assert.ok(find(b, "other-school") && find(b, "old-local"));
      assert.equal(find(b, "old-school"), undefined);
      assert.equal(find(b, "old-national"), undefined);
      assert.deepEqual(b.entries().find(item => item.name === "new-school").regions, [region]);
      assert.ok(b.entries().some(item => item.name === "new-national"));
      assert.ok(!b.entries().some(item => item.name === "new-local"));
      assert.ok(b.t.feiertageAm("2026-10-12", true).some(item => item.name === "new-national"));
      const reopened = boot(web, [], {}, b.save());
      try { assert.deepEqual(reopened.entries(), b.entries()); } finally { reopened.close(); }
    } finally { b.close(); }
  });
  test(`${land}: a missing or wrong school group cannot erase dates or block the national calendar`, web => {
    const b = boot(web, [groupRow("old-school"), national("old-national")], { land, region });
    try {
      b.start();
      b.reply({ abrufbereiche: coverage, feiertage: [groupRow("wrong-school", other), national("new-national")] });
      assert.ok(find(b, "old-school"));
      assert.equal(find(b, "old-national"), undefined);
      assert.ok(b.entries().some(item => item.name === "new-national"));
      assert.ok(!b.entries().some(item => item.name === "wrong-school"));
      assert.match(b.w.document.querySelector("#ort-stand").textContent, /1 public holiday.*could not be confirmed for 2026/);
      b.start();
      b.reply({ abrufbereiche: coverage, feiertage: [groupRow("first-term", region, { von: "2025-12-22", bis: "2026-01-04" })] });
      assert.ok(find(b, "old-school"));
      assert.ok(b.entries().some(item => item.name === "first-term"));
      b.start();
      b.reply({ abrufbereiche: coverage, feiertage: [] });
      assert.ok(find(b, "old-school"));
      assert.ok(b.entries().some(item => item.name === "new-national"));
    } finally { b.close(); }
  });
}

test("only unconfirmed requested years are shown and an offline retry never rewrites the cache", web => {
  const b = boot(web, [], { land: "NL", region: "NL-NO" }), d = b.w.document;
  const group = (id, von, bis) => entry(id, { country: "NL", region: "NL-NO", regions: ["NL-NO"], von, bis, name: id });
  const status = () => d.querySelector("#ort-stand").textContent;
  try {
    b.start(2);
    b.reply({ jahre: [2026, 2027], abrufbereiche: [
      scope("NL-NO", "school-holiday", 2026, "NL"), scope("NL-NO", "school-holiday", 2027, "NL")
    ], feiertage: [group("winter-2025", "2025-12-20", "2026-01-04"), group("winter-2026", "2026-12-20", "2027-01-04")] });
    assert.match(status(), /coverage could not be confirmed for 2027\.$/);
    const cache = b.entries(), settings = plain(b.t.daten().einstellungen.ort);
    const school = d.querySelector("#ort-ferien");
    school.click();
    assert.doesNotMatch(status(), /could not be confirmed/);
    school.click();
    assert.match(status(), /for 2027\.$/);
    const reopened = boot(web, [], {}, b.save());
    try {
      reopened.t.oeffneEinstellungen();
      reopened.w.document.querySelector("#einst-tab-ort").click();
      assert.doesNotMatch(reopened.w.document.querySelector("#ort-stand").textContent, /could not be confirmed/);
      assert.deepEqual(reopened.entries(), cache);
    } finally { reopened.close(); }
    b.start(2);
    b.reply({ fehler: "Offline fixture" });
    assert.equal(status(), "Retrieval failed.");
    assert.deepEqual(b.entries(), cache);
    assert.deepEqual(plain(b.t.daten().einstellungen.ort), settings);
  } finally { b.close(); }
});

const results = [];
for (const web of ["magnolie-organizer/web", "magnolie-organizer-windows/app/web"]) {
  for (const { name, fn } of cases) {
    try { fn(web); results.push({ web, name, passed: true }); }
    catch (error) { results.push({ web, name, passed: false, error: error.message }); console.error(`FAIL ${web}: ${name}\n${error.stack}`); }
  }
}
const passed = results.filter(item => item.passed).length;
console.log(`Holiday cache: ${passed}/${results.length} cases passed (full desktop scripts, controlled native responses).`);
if (process.env.MAGNOLIE_HOLIDAY_REPORT) fs.writeFileSync(process.env.MAGNOLIE_HOLIDAY_REPORT,
  JSON.stringify({ sourceRef: ref || "working-tree", node: process.version, jsdom: require("jsdom/package.json").version, passed, total: results.length, results }, null, 2) + "\n");
if (passed !== results.length) process.exitCode = 1;
