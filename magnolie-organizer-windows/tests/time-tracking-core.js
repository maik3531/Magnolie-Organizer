"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const sources = [path.resolve(__dirname, "../app/web/anwendung.js")];
const linux = path.join(root, "magnolie-organizer/web/anwendung.js");
if (fs.existsSync(linux)) sources.push(linux);
const actor = "11111111-1111-4111-8111-111111111111";
const id = "22222222-2222-4222-8222-222222222222";
const clone = value => JSON.parse(JSON.stringify(value));
const record = { id, startMinute: 1000, endMinute: 1060, pauseMinute: null, pauseMinutes: 15,
  zone: "Europe/Berlin", type: "Synthetic", note: "", modifiedMs: 1000, deleted: false, clock: { [actor]: 1 } };
let previous;
for (const file of sources) {
  const source = fs.readFileSync(file, "utf8");
  const core = source.slice(source.indexOf("  function zeitPruefen("), source.indexOf("  function normalisiereTermine("));
  assert.ok(core.includes("function normalisiereZeiterfassung"));
  if (previous) assert.equal(core, previous, "Both desktop editions must use the same time model");
  previous = core;
  const canonical = source.slice(source.indexOf("  function personalSyncKanonisch("), source.indexOf("  async function personalSyncHash("));
  const api = { kopie: clone, _: value => value, pgettext: (_context, value) => value,
    anrufClientRef: () => "33333333-3333-4333-8333-333333333333" };
  vm.createContext(api); vm.runInContext(canonical + core, api);
  assert.deepEqual(clone(api.normalisiereZeiterfassung()), { enabled: false, actor: "", counter: 0, entries: [], conflicts: {}, reportName: "" });
  const state = api.normalisiereZeiterfassung({ enabled: true, actor, counter: 1, entries: [record] });
  assert.deepEqual(clone(state.entries), [record]);
  for (const patch of [{ counter: false }, { actor: false }, { reportName: 3 }, { entries: [record, record] }, { counter: 0 }])
    assert.throws(() => api.normalisiereZeiterfassung({ enabled: true, actor, counter: 1, entries: [record], ...patch }));
  for (const patch of [{ pauseMinutes: 61 }, { startMinute: "1000" }, { clock: {} }, { zone: "Missing/Zone" }, { note: "\ud800" }])
    assert.throws(() => api.zeitPruefeEintrag({ ...record, ...patch }));
  const offset = api.zeitDatumTeile(1000, "UTC+05:30");
  assert.equal(offset.hour, 22); assert.equal(offset.minute, 10);
  assert.throws(() => api.zeitDatumTeile(1000, "UTC+25:00"));
  const plan = { fixed: [{ start: 720, end: 750 }], manual: [{ start: 1000, end: 1015 }],
    replaced: [], fixedEnds: {}, baseMinutes: 0 };
  assert.deepEqual(clone(api.zeitPruefeEintrag({ ...record, endMinute: null, pausePlan: plan })).pausePlan, plan);
  for (const changed of [{ ...plan, endAlarm: {} }, { ...plan, replaced: [1000, 1000] },
    { ...plan, fixedEnds: { "01000": 1010 } }, { ...plan, fixed: [{ start: 720, end: 720 }] }])
    assert.throws(() => api.zeitPruefeEintrag({ ...record, endMinute: null, pausePlan: changed }));
  assert.throws(() => api.zeitPruefeEintrag({ ...record, pausePlan: plan }));
  const minute = text => Math.floor(Date.parse(text) / 60000);
  const civil = (year, month, day, hour, minute) => ({ year, month, day, hour, minute });
  assert.throws(() => api.zeitLokaleMinute(civil(2026, 3, 29, 2, 30), "Europe/Berlin"));
  assert.equal(api.zeitLokaleMinute(civil(2026, 3, 29, 2, 30), "Europe/Berlin", null, true), minute("2026-03-29T01:30:00Z"));
  assert.equal(api.zeitLokaleMinute(civil(2026, 10, 25, 2, 30), "Europe/Berlin"), minute("2026-10-25T00:30:00Z"));
  assert.equal(api.zeitLokaleMinute(civil(2026, 10, 25, 2, 30), "Europe/Berlin", minute("2026-10-25T01:15:00Z")), minute("2026-10-25T01:30:00Z"));
  assert.equal(api.zeitLokaleMinute(civil(2026, 10, 4, 2, 15), "Australia/Lord_Howe", null, true), minute("2026-10-03T15:45:00Z"));
  assert.equal(api.zeitLokaleMinute(civil(2011, 12, 30, 12, 0), "Pacific/Apia", null, true), minute("2011-12-30T22:00:00Z"));
  assert.equal(api.zeitLokaleMinute(civil(1970, 1, 1, 2, 0), "Africa/Monrovia"), minute("1970-01-01T02:44:30Z"));
  const start = minute("2026-10-04T08:00:00Z"), finish = minute("2026-10-04T17:00:00Z");
  const live = { ...record, startMinute: start, endMinute: null, pauseMinutes: 0, zone: "UTC",
    pausePlan: { fixed: [{ start: 720, end: 750 }], manual: [], replaced: [], fixedEnds: {}, baseMinutes: 0 } };
  const before = JSON.stringify(live);
  assert.deepEqual(clone(api.zeitMinuten(live, minute("2026-10-04T12:10:00Z"))),
    { grossMinutes: 250, pauseMinutes: 10, totalMinutes: 240, paused: true });
  assert.equal(api.zeitMinuten(live, finish).pauseMinutes, 30);
  assert.equal(JSON.stringify(live), before, "Rendering must not mutate the entry or its causal clock");
  const separate = clone(live);
  separate.pausePlan.manual.push({ start: minute("2026-10-04T15:00:00Z"), end: minute("2026-10-04T15:15:00Z") });
  assert.equal(api.zeitMinuten(separate, finish).pauseMinutes, 45);
  const replacement = clone(live);
  replacement.pausePlan.manual.push({ start: minute("2026-10-04T11:55:00Z"), end: minute("2026-10-04T12:10:00Z") });
  assert.equal(api.zeitMinuten(replacement, finish).pauseMinutes, 15);
  const endedEarly = clone(live);
  endedEarly.pausePlan.fixedEnds[minute("2026-10-04T12:00:00Z")] = minute("2026-10-04T12:10:00Z");
  endedEarly.pausePlan.manual.push({ start: minute("2026-10-04T12:15:00Z"), end: minute("2026-10-04T12:20:00Z") });
  assert.equal(api.zeitMinuten(endedEarly, finish).pauseMinutes, 15);
  const autumn = { ...clone(live), zone: "Europe/Berlin", startMinute: minute("2026-10-24T23:00:00Z") };
  autumn.pausePlan.fixed = [{ start: 120, end: 180 }];
  assert.equal(api.zeitMinuten(autumn, minute("2026-10-25T04:00:00Z")).pauseMinutes, 120);
  assert.equal(api.zeitDauer(168 * 60 + 30, "en-US"), "168:30");
  assert.equal(api.zeitDauerLesen("١٦٨:٣٠"), 168 * 60 + 30);
  assert.equal(api.zeitDauerLesen("१६८:३०"), 168 * 60 + 30);
  assert.throws(() => api.zeitDauerLesen("168:61"));
  const changed = api.zeitErsetze(state, state.entries[0], { ...record, note: "Edited" });
  assert.equal(changed.counter, 2); assert.equal(changed.entries[0].clock[actor], 2);
  assert.throws(() => api.zeitErsetze(changed, record, { ...record, note: "Stale" }));
  assert.equal(api.zeitErsetze(changed, record, { ...record, note: "Edited" }), changed);
  const empty = { ...api.normalisiereZeiterfassung(), enabled: true };
  const created = api.zeitErsetze(empty, null, { ...record, clock: {} });
  assert.equal(created.counter, 1); assert.equal(created.entries[0].clock[created.actor], 1);
  assert.throws(() => api.zeitErsetze(created, created.entries[0], { ...created.entries[0], endMinute: null }));
  const remoteActor = "44444444-4444-4444-8444-444444444444";
  const remote = { ...record, note: "Remote edit", clock: { [remoteActor]: 1 } };
  const conflict = api.zeitAbgleichen(state, [remote]);
  assert.equal(conflict.outcomes[id], "conflict"); assert.equal(conflict.state.entries[0].note, record.note);
  assert.equal(api.zeitAbgleichen(conflict.state, [remote]).state.conflicts[id].length, 1);
  const later = api.zeitErsetze(conflict.state, conflict.state.entries[0], { ...record, note: "Later local edit" });
  assert.throws(() => api.zeitKonfliktLoesen(later, id, remote, conflict.state.conflicts[id], conflict.state.entries[0]));
  const resolved = api.zeitKonfliktLoesen(conflict.state, id, remote, conflict.state.conflicts[id], conflict.state.entries[0]);
  assert.equal(resolved.entries[0].note, "Remote edit"); assert.equal(Object.keys(resolved.conflicts).length, 0);
  assert.equal(resolved.entries[0].clock[remoteActor], 1); assert.equal(resolved.entries[0].clock[actor], 2);
  const deleted = api.zeitErsetze(state, state.entries[0], { ...record, startMinute: 0, endMinute: 0, pauseMinutes: 0,
    zone: "UTC", type: "", note: "", deleted: true });
  const proposedRestore = { ...record, clock: { ...deleted.entries[0].clock, [remoteActor]: 1 } };
  const blockedRestore = api.zeitAbgleichen(deleted, [proposedRestore]);
  assert.equal(blockedRestore.state.entries[0].deleted, true, "Notes cannot silently undo an Organizer deletion");
  assert.equal(blockedRestore.outcomes[id], "conflict");
  const restored = api.zeitKonfliktLoesen(blockedRestore.state, id, proposedRestore, blockedRestore.state.conflicts[id], blockedRestore.state.entries[0]);
  assert.equal(restored.entries[0].deleted, false);
  assert.throws(() => api.zeitAbgleichen(state, deleted.entries));
}
console.log(`TIME TRACKING CORE PASSED (${sources.length} desktop edition(s))`);
