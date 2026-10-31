"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
   'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kontaktGruppen, kontaktGruppeKanonisch, fotoAktiv: () => !!kontaktFotoLauf, fotoSyncBusy: value => { syncLaeuft = value; }, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const plain = x => JSON.parse(JSON.stringify(x));
const photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6SpAAAAAASUVORK5CYII=";
const other = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
const fingerprint = "a".repeat(64), device = "paired-phone";
const status = { enabled: false, peers: [], kdeconnect: { contacts_available: true, contacts_device_id: device } };

function editGroups(b, values) {
  b.t.zustand().adressen.auswahlId = "local"; b.t.zustand().adressen.buchstabe = "O";
  b.t.wechsel("adressen");
  [...b.w.document.querySelectorAll("button")].find(button => button.textContent === "Edit").click();
  const picker = b.w.document.querySelector("#kontakt-personengruppen");
  assert.ok(picker);
  const choices = [...picker.querySelectorAll('input[type="checkbox"]')];
  if (!values.length) choices.find(input => input.value === "").click();
  else for (const input of choices) if (input.value && input.checked !== values.includes(input.value)) input.click();
  [...b.w.document.querySelectorAll("button")].find(button => button.textContent === "Save changes").click();
}

async function run(web, data, remote, options = {}) {
  const b = await harness.exports.boot(web, data);
  // jsdom has no image decoder; rendered decoding is covered by the native probe.
  b.w.Image = class {
    constructor() { this.width = this.height = 1; }
    set src(value) { if (this.onload) this.onload(); }
  };
  const done = new Set(), timers = new Set(), requests = [];
  let resumed = false;
  if (options.beforeStart) options.beforeStart(b);
  b.w.App.telefonStand(options.status || status);
  const deadline = Date.now() + 10000;
  try {
    do {
      assert.ok(Date.now() < deadline, "photo job must finish");
      await new Promise(resolve => setImmediate(resolve));
      for (const message of b.messages) {
        if (done.has(message)) continue;
        done.add(message);
        if (message.cmd === "speichern") b.w.App.gespeichert({ id: message.id, ok: true });
        if (message.cmd !== "telefon_kontaktfotos") continue;
        requests.push(message);
        if (message.uids && options.beforeReply) options.beforeReply(b);
        if (message.uids && options.timeout) {
          const timer = b.timers.find(t => t.delay === 12000 && !t.cancelled);
          assert.ok(timer); timer.fn(); timer.cancelled = true; continue;
        }
        b.w.App.kontaktFotos({ ok: true, requestId: message.requestId, device_id: options.device || device,
          fingerprint: message.uids && options.changedSource ? "b".repeat(64) : fingerprint,
          contacts: message.uids ? remote.filter(k => message.uids.includes(k.uid)) :
            remote.map(k => ({ uid: k.uid, modified_ms: k.modified_ms })) });
      }
      for (const timer of b.timers) if (!timers.has(timer) && !timer.cancelled && [200, 1000].includes(timer.delay)) {
        timers.add(timer); timer.fn();
      }
      if (options.resumeBusy && !resumed && !b.t.fotoAktiv()) {
        const timer = b.timers.find(t => t.delay === 60000 && !t.cancelled);
        assert.ok(timer, "busy photo retrieval must schedule another attempt");
        resumed = true; b.t.fotoSyncBusy(false); timer.fn();
      }
    } while (b.t.fotoAktiv());
    return { data: plain(b.t.daten()), requests, saves: b.saves().map(m => JSON.parse(m.text)),
      conflicts: [...b.w.document.querySelectorAll(".kontakt-gruppen-konflikt")].map(node => node.textContent),
      groups: b.t.daten().kontakte.map(contact => Array.from(b.t.kontaktGruppen(contact))),
      expectedFamily: b.t.kontaktGruppeKanonisch("Familie") };
  } finally { b.close(); }
}

(async () => {
  for (const web of harness.exports.roots) {
    const base = { kontakte: [
      { id: "local", vorname: "Original", telefon: "0170 1234567" },
      { id: "manual", telefon: "+491701234568", fotoManuell: true, foto: "" },
      { id: "legacy", telefon: "+491701234569", foto: other },
      { id: "ambiguous-a", email: "shared@example.org" },
      { id: "ambiguous-b", email: "shared@example.org" }
    ], einstellungen: { regional: { homeCountry: "DE" } } };
    const remote = [
      { uid: "phone-one", modified_ms: 1, foto: photo, telefon: "+49 170 1234567", vorname: "Must not import",
        sozialeMedien: [{ dienst: "whatsapp", wert: "+491701234567" }], gruppenZeilen: ["CATEGORIES:Familie"] },
      { uid: "phone-two", modified_ms: 1, foto: photo, telefon: "+491701234568" },
      { uid: "phone-three", modified_ms: 1, foto: photo, telefon: "+491701234569" },
      { uid: "ambiguous", modified_ms: 1, foto: photo, email: "shared@example.org" }
    ];
    const first = await run(web, base, remote);
    const notesPeer = { device_id: "11111111-1111-4111-8111-111111111111", state: "online_wifi", own_device: true,
      remote_own_device: true, contacts_read_available: true, contacts_fingerprint: fingerprint };
    const notesStatus = { enabled: true, peers: [notesPeer], kdeconnect: { contacts_available: false } };
    const notesDevice = "notes:" + notesPeer.device_id;
    const notes = await run(web, base, remote, { status: notesStatus, device: notesDevice });
    assert.equal(notes.data.kontakte[0].foto, photo);
    assert.equal(notes.data.kontakte[0].vorname, "Original");
    assert.deepEqual(notes.data.kontakte[0].sozialeMedien, [{ dienst: "whatsapp", wert: "+491701234567" }]);
    assert.ok(notes.data.kontakte[0].vcardRoundtrip.some(line => line.startsWith("CATEGORIES:")));
    assert.deepEqual(notes.groups[0], [notes.expectedFamily], "Imported group membership must survive locale alias normalization");
    assert.equal(notes.data.kontakte[1].foto, "");
    assert.equal(notes.data.kontakte[2].foto, other);
    const cachedPending = plain(notes.data);
    cachedPending.kontakte[0].vcardRoundtrip = ["CATEGORIES:Work"];
    cachedPending.kontakte[0].telefonGruppenAenderung = { version: 1 };
    cachedPending.kontaktFotoCache.entries.find(entry => entry.uid === "phone-one").valueContactId = "local";
    const alreadyApplied = await run(web, cachedPending, remote.map((card, index) => index ? card : {
      ...card, gruppenZeilen: ["CATEGORIES:Arbeit"]
    }), { status: notesStatus, device: notesDevice });
    assert.ok(alreadyApplied.requests.some(request => request.uids?.includes("phone-one")),
      "A fresh positive cache hid the pending contact's unchanged-stamp native groups");
    assert.equal(alreadyApplied.data.kontakte[0].telefonGruppenAenderung, null,
      "A matching fresh native group read did not resolve the old unsent wish");
    const stillDifferent = await run(web, cachedPending, remote, { status: notesStatus, device: notesDevice });
    assert.deepEqual(stillDifferent.groups[0], ["Work"]);
    assert.ok(stillDifferent.data.kontakte[0].telefonGruppenAenderung);
    assert.ok(!stillDifferent.data.kontakte[0].telefonGruppenAenderung.base,
      "A readonly cache refresh silently authorized a baseless write");
    assert.deepEqual(stillDifferent.data.kontakte[0].telefonGruppenAenderung.beobachtet.groups, ["Family"]);
    for (const [sourceStatus, sourceDevice] of [[status, device], [notesStatus, notesDevice]]) {
      const grouped = plain(base);
      grouped.kontakte[0].vcardRoundtrip = ["CATEGORIES:Kollegen", "X-LOCAL:preserve"];
      const changedGroups = remote.map((card, index) => index ? card : { ...card, gruppenZeilen: ["CATEGORIES:Arbeit"] });
      const updated = await run(web, grouped, changedGroups, { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(updated.groups[0], ["Work"], "Current phone groups must replace removed membership, not union it back");
      assert.ok(updated.data.kontakte[0].vcardRoundtrip.includes("X-LOCAL:preserve"));
      const aged = plain(updated.data);
      aged.kontaktFotoCache.entries.forEach(entry => { entry.checkedAt = Date.now() - 3600001; });
      const groupOnlyChange = await run(web, aged, changedGroups.map((card, index) => index ? card : {
        ...card, gruppenZeilen: ["CATEGORIES:Family"]
      }), { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(groupOnlyChange.groups[0], ["Family"], "A cached photo cannot freeze group-only changes with an unchanged contact timestamp forever");
      const cleared = await run(web, updated.data, changedGroups.map((card, index) => index ? card : {
        ...card, modified_ms: 2, gruppenZeilen: []
      }), { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(cleared.groups[0], [], "Explicit empty membership must remove the last phone group");
      const unknown = await run(web, grouped, remote.map(({ gruppenZeilen, ...card }) => card), { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(unknown.groups[0], ["Colleagues"], "Unknown groups must not clear membership");
      const concurrent = await run(web, grouped, changedGroups, { status: sourceStatus, device: sourceDevice,
        beforeReply: b => { b.t.daten().kontakte[0].vcardRoundtrip = ["CATEGORIES:Family"]; } });
      assert.deepEqual(concurrent.groups[0], ["Family"], "Late phone membership must not overwrite a concurrent local group edit");
      const locallyEdited = await run(web, grouped, remote, { status: sourceStatus, device: sourceDevice,
        beforeStart: b => editGroups(b, ["Work"]) });
      assert.deepEqual(locallyEdited.groups[0], ["Work"], "A saved local edit BEFORE the photo request must not be replaced by the old phone membership");
      assert.equal(locallyEdited.data.kontakte[0].telefonGruppenAenderung.beobachtet.deviceId, sourceDevice);
      assert.deepEqual(locallyEdited.data.kontakte[0].telefonGruppenAenderung.beobachtet.groups, ["Family"]);
      assert.ok(locallyEdited.conflicts.some(text => text.includes("Not sent.") && text.includes("Work") && text.includes("Family")),
        "Without a proven common source baseline this is an unsent intent, not a confirmed competing edit");
      assert.ok(locallyEdited.saves.some(data => data.kontakte[0].telefonGruppenAenderung?.beobachtet), "Pending local edit and observed conflict must be saved");
      const restarted = plain(locallyEdited.data);
      restarted.kontaktFotoCache.entries.forEach(entry => { entry.checkedAt = Date.now() - 3600001; });
      const afterRestart = await run(web, restarted, remote, { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(afterRestart.groups[0], ["Work"], "Restart and re-read must preserve the pending edit");
      const removed = await run(web, grouped, remote, { status: sourceStatus, device: sourceDevice,
        beforeStart: b => editGroups(b, []) });
      assert.deepEqual(removed.groups[0], [], "Explicitly removing the last group before the read must remain pending too");
      const matching = remote.map((card, index) => index ? card : { ...card, modified_ms: 2, gruppenZeilen: ["CATEGORIES:Work"] });
      const observedMatch = await run(web, locallyEdited.data, matching, { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(observedMatch.groups[0], ["Work"]);
      assert.equal(observedMatch.data.kontakte[0].telefonGruppenAenderung, null, "Only an actual matching source read may resolve the observed divergence");
      const laterPhoneEdit = await run(web, observedMatch.data, remote.map((card, index) => index ? card : {
        ...card, modified_ms: 3, gruppenZeilen: ["CATEGORIES:Patients"]
      }), { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(laterPhoneEdit.groups[0], ["Patients"], "A resolved local edit must not permanently suppress later real phone changes");
      const otherSource = await run(web, locallyEdited.data, matching, { status: sourceStatus === status ? notesStatus : status,
        device: sourceStatus === status ? notesDevice : device });
      assert.ok(otherSource.data.kontakte[0].telefonGruppenAenderung, "A different contact source cannot acknowledge the pending change");
      assert.equal(otherSource.data.kontakte[0].telefonGruppenAenderung.beobachtet.deviceId, sourceDevice);
      const unchangedEditor = await run(web, grouped, changedGroups, { status: sourceStatus, device: sourceDevice,
        beforeStart: b => editGroups(b, ["Colleagues"]) });
      assert.deepEqual(unchangedEditor.groups[0], ["Work"], "Saving an unchanged chooser must not block real phone changes");
      assert.equal(unchangedEditor.data.kontakte[0].telefonGruppenAenderung, null);
      const baseline = await run(web, grouped, remote.map((card, index) => index ? card : {
        ...card, gruppenZeilen: ["CATEGORIES:Coworkers"]
      }), { status: sourceStatus, device: sourceDevice });
      assert.deepEqual(baseline.data.kontakte[0].telefonGruppenStand.groups, ["Colleagues"]);
      const ready = plain(baseline.data);
      ready.kontaktFotoCache.entries.forEach(entry => { entry.checkedAt = Date.now() - 3600001; });
      const waiting = await run(web, ready, remote.map((card, index) => index ? card : {
        ...card, gruppenZeilen: ["CATEGORIES:Coworkers"]
      }), { status: sourceStatus, device: sourceDevice, beforeStart: b => editGroups(b, ["Work"]) });
      assert.deepEqual(waiting.groups[0], ["Work"]);
      assert.deepEqual(waiting.data.kontakte[0].telefonGruppenAenderung.base.groups, ["Colleagues"]);
      assert.ok(waiting.conflicts.some(text => text.includes("Not sent.") && !text.includes("Conflict")),
        "Reading the unchanged old phone membership cannot turn an intentional local edit into a conflict");
      const bothChanged = await run(web, ready, remote.map((card, index) => index ? card : {
        ...card, gruppenZeilen: ["CATEGORIES:Family"]
      }), { status: sourceStatus, device: sourceDevice, beforeStart: b => editGroups(b, ["Work"]) });
      assert.ok(bothChanged.conflicts.some(text => text.includes("Conflict")), "A phone change after the common baseline must remain visible as a real conflict");
    }
    assert(notes.requests.every(request => request.device_id === notesDevice), "Notes photo reads must retain their own device namespace");
    const directProvider = await run(web, base, remote, { status: { ...notesStatus, kdeconnect: status.kdeconnect }, device: notesDevice });
    assert(directProvider.requests.every(request => request.device_id === notesDevice), "current authorized Android provider lost to older KDE cache");
    const ambiguousSources = await run(web, base, remote, { status: { ...notesStatus, kdeconnect: status.kdeconnect,
      peers: [notesPeer, { ...notesPeer, device_id: "22222222-2222-4222-8222-222222222222" }] } });
    assert(ambiguousSources.requests.every(request => request.device_id === device), "multiple readable phones must not be guessed");
    const revokedNotes = await run(web, base, remote, { status: notesStatus, device: notesDevice, beforeReply: b =>
      b.w.App.telefonStand({ ...notesStatus, peers: [{ ...notesPeer, contacts_read_available: false }] }) });
    assert.equal(revokedNotes.data.kontakte[0].foto, "", "revoking contact reads must reject an in-flight Notes photo");
    const unavailableNotes = await run(web, base, remote, { status: { ...notesStatus,
      peers: [{ ...notesPeer, contacts_read_available: false }] }, device: notesDevice });
    assert.equal(unavailableNotes.requests.length, 0, "pairing alone must not start contact reads");
    assert.equal(first.data.kontakte[0].foto, photo, "normalised phone number must match without importing a contact");
    assert.equal(first.data.kontakte[0].vorname, "Original");
    assert.equal(first.data.kontakte[1].foto, "", "explicit photo removal stays protected");
    assert.equal(first.data.kontakte[2].foto, other, "unknown legacy photo origin stays protected");
    assert(first.data.kontakte[1].fotoAlternativen.some(image => image.foto === photo), "explicit removal prevented discovering an alternate phone image");
    assert(first.data.kontakte[2].fotoAlternativen.some(image => image.foto === photo), "existing other-source image prevented discovering phone alternative");
    assert.equal(first.data.kontakte[2].fotoQuelle, undefined, "phone alternative seized the displayed other-source image binding");
    assert(notes.data.kontakte[2].fotoAlternativen.some(image => image.foto === photo && image.quellen.includes("Magnolie Notes")), "Notes alternative lost its actual source label");
    assert.equal(first.data.kontakte[3].foto, ""); assert.equal(first.data.kontakte[4].foto, "");
    assert.equal(first.data.kontakte.length, 5);
    assert.equal(first.data.kontakte[0].fotoQuelle.fingerprint, fingerprint);
    assert.equal(first.data.kontaktFotoCache.entries.length, 4);
    assert.ok(first.saves.some(d => d.kontakte[0].foto === photo), "photo and cache must be durably submitted together");
    const replay = await run(web, first.data, remote);
    assert.equal(replay.requests.filter(r => r.uids).length, 0, "restart must reuse unchanged cached photos");
    const legacyCache = plain(first.data); legacyCache.kontaktFotoCache.version = 1;
    const reindexed = await run(web, legacyCache, remote);
    assert.equal(reindexed.requests.filter(request => request.uids).length, remote.length, "old skip-protected cache prevented first alternative discovery");
    const changed = remote.map((r, i) => i ? r : { ...r, modified_ms: 2, foto: other });
    const refreshed = await run(web, replay.data, changed);
    assert.equal(refreshed.data.kontakte[0].foto, other, "changed source refreshes its own unchanged cached image");
    assert.equal(refreshed.requests.filter(r => r.uids).length, 1);
    const edited = plain(first.data); edited.kontakte[0].foto = "data:image/png;base64,BwgJ";
    const protectedEdit = await run(web, edited, changed);
    assert.equal(protectedEdit.data.kontakte[0].foto, edited.kontakte[0].foto, "hash mismatch protects edits outside the photo picker too");
    const late = await run(web, base, remote, { beforeReply: b => {
      b.t.daten().kontakte[0].fotoManuell = true; b.t.daten().kontakte[0].foto = other;
    }});
    assert.equal(late.data.kontakte[0].foto, other);
    const swapped = await run(web, base, remote, { changedSource: true });
    assert.equal(swapped.data.kontakte[0].foto, "", "re-paired source fingerprint cannot fill the old job");
    const timeout = await run(web, base, remote, { timeout: true });
    assert.equal(timeout.data.kontakte[0].foto, "");
    assert.ok(!timeout.data.kontaktFotoCache, "failed retrieval cannot become a cached absence");
    const replaced = await run(web, base, remote, { beforeReply: b => b.w.App.init({ daten: {
      kontakte: [{ id: "different-profile", telefon: "+491701234567" }] }, neu: false }) });
    assert.equal(replaced.data.kontakte[0].id, "different-profile");
    assert.equal(replaced.data.kontakte[0].foto, "", "late response must not cross profiles");
    const disabled = await run(web, base, remote, { beforeReply: b => { b.t.daten().einstellungen.adressen.foto = false; } });
    assert.equal(disabled.data.kontakte[0].foto, "");
    const protectedOnly = await run(web, { kontakte: base.kontakte.slice(1, 3) }, remote);
    assert(protectedOnly.requests.some(request => request.uids), "protected photos must still discover alternatives");
    assert.equal(protectedOnly.data.kontakte[0].foto, ""); assert.equal(protectedOnly.data.kontakte[1].foto, other);
    assert(protectedOnly.data.kontakte[1].fotoAlternativen.some(image => image.foto === photo));
    const differentMailbox = await run(web, { kontakte: [{ id: "mail", email: "jose@example.org" }] },
      [{ uid: "accent", modified_ms: 1, foto: photo, email: "josé@example.org" }]);
    assert.equal(differentMailbox.data.kontakte[0].foto, "", "email accents must not be folded into another mailbox");
    const canonicalMailbox = await run(web, { kontakte: [{ id: "mail", email: "josé@example.org" }] },
      [{ uid: "accent", modified_ms: 1, foto: photo, email: "JOSE\u0301@EXAMPLE.ORG" }]);
    assert.equal(canonicalMailbox.data.kontakte[0].foto, photo, "equivalent Unicode and case still match");
    const busy = await run(web, base, remote, { beforeStart: b => b.t.fotoSyncBusy(true) });
    assert.equal(busy.requests.length, 0, "provider synchronization has priority over photo retrieval");
    const resumed = await run(web, base, remote, { beforeStart: b => b.t.fotoSyncBusy(true), resumeBusy: true });
    assert.equal(resumed.data.kontakte[0].foto, photo, "photo retrieval resumes when synchronization finishes");
    const startedSync = await run(web, base, remote, { beforeReply: b => b.t.fotoSyncBusy(true) });
    assert.equal(startedSync.data.kontakte[0].foto, "", "late photos must not invalidate an active synchronization plan");
    const reviewing = await run(web, base, remote, { beforeReply: b => {
      const dialog = b.w.document.createElement("div"); dialog.className = "baum-kontakt-konflikt";
      b.w.document.body.append(dialog);
    }});
    assert.equal(reviewing.data.kontakte[0].foto, "", "photo updates must not invalidate a contact review draft");
    console.log("CONTACT PHOTO CACHE PASSED: " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
