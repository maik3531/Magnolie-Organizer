"use strict";

const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const windows = path.resolve(__dirname, "../app/web");
const siblingLinux = path.resolve(__dirname, "../../magnolie-organizer");
const embeddedLinux = path.resolve(__dirname, "../shared/magnolie-organizer");
const linux = path.resolve(process.env.MAGNOLIE_LINUX_SOURCE ||
  (fs.existsSync(path.join(siblingLinux, "web/index.html")) ? siblingLinux : embeddedLinux), "web");
const roots = process.env.MAGNOLIE_WEB ? [process.env.MAGNOLIE_WEB] : [windows, linux].filter(root => fs.existsSync(root));
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function boot(web, data = {}, initialize = true) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://desktop-regression.invalid/index.html", pretendToBeVisual: true
  });
  const w = dom.window, messages = [], timers = [];
  w.setTimeout = (fn, delay) => { const timer = { fn, delay }; timers.push(timer); return timer; };
  w.clearTimeout = timer => { if (timer) timer.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w.crypto, "subtle", { value: webcrypto.subtle });
  w.__MAGNOLIE_BRUECKE__ = "regression";
  w.webkit = { messageHandlers: { regression: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "zeichenblatt.js"), "utf8"));
  if (fs.existsSync(path.join(web, "appearance.js"))) w.eval(fs.readFileSync(path.join(web, "appearance.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "normative-timezones.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  await tick();
  if (initialize) w.App.init({ daten: data, neu: false, regional: { language: "en", timeZone: "UTC" } });
  const t = w.OrganizerTest;
  return { w, t, messages, timers, close: () => dom.window.close(),
    saves: () => messages.filter(message => message.cmd === "speichern"),
    input(selector, value) { const field = w.document.querySelector(selector); assert.ok(field, selector);
      field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true })); return field; },
    answer(text) { const button = [...w.document.querySelectorAll("#aenderungen-schleier button")].find(button => button.textContent === text);
      assert.ok(button, text); button.click(); },
    ack(ok = true) { const save = messages.filter(message => message.cmd === "speichern").at(-1); assert.ok(save);
      w.App.gespeichert({ id: save.id, ok }); return save; }
  };
}

async function run(web) {
  if (web === windows) assert.match(fs.readFileSync(path.resolve(web, "../../ExchangeCodec.cs"), "utf8"),
    /InstanceUid\(string uid, IcsProperty recurrenceId\) => uid \+ "#" \+ recurrenceId.Value/,
    "Update frontend instance identities together with the native decoder contract");
  let cases = 0;
  async function test(name, fn, data = {}, initialize = true) {
    const b = await boot(web, data, initialize);
    let timeout;
    if (process.env.MAGNOLIE_TEST_TRACE) console.log(web + ": " + name);
    try {
      await Promise.race([fn(b), new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error("Test timed out")), 10000);
      })]);
      cases++;
    }
    catch (error) { error.message = path.basename(path.dirname(web)) + ": " + name + ": " + error.message; throw error; }
    finally { clearTimeout(timeout); b.close(); }
  }

  await test("unconfirmed startup cannot save", async b => {
    assert.equal(b.w.document.querySelector("#schreibtisch").hasAttribute("inert"), true);
    for (const timer of b.timers.filter(timer => timer.delay === 2500)) timer.fn();
    b.t.speichereJetzt(); assert.equal(b.saves().length, 0);
    b.w.App.vorBeenden(); await tick();
    assert.equal(b.saves().length, 0);
    b.w.App.init({ daten: { notizen: [{ id: "existing", titel: "Existing", text: "Keep", html: "Keep" }] }, neu: false });
    assert.equal(b.w.document.querySelector("#schreibtisch").hasAttribute("inert"), false);
    b.t.speichereJetzt(); assert.equal(JSON.parse(b.saves().at(-1).text).notizen[0].id, "existing");
  }, {}, false);

  await test("anniversary dismissal defaults to manual and saves independently", async b => {
    const reminder = b.t.daten().einstellungen.erinnerung;
    assert.equal(reminder.jahrestage.autoAusblenden, false);
    const ordinary = { vorlauf: reminder.vorlauf, art: reminder.art, verpasste: reminder.verpasste };
    b.t.oeffneEinstellungen();
    b.w.document.querySelector("#einst-tab-erinnerung").click();
    const toggle = b.w.document.querySelector("#erinnerung-jahrestage-auto-ausblenden");
    assert.ok(toggle && !toggle.checked && !toggle.disabled);
    toggle.checked = true; toggle.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(reminder.jahrestage.autoAusblenden, true);
    assert.deepEqual({ vorlauf: reminder.vorlauf, art: reminder.art, verpasste: reminder.verpasste }, ordinary);
    const saved = JSON.parse(b.saves().at(-1).text);
    assert.equal(saved.einstellungen.erinnerung.jahrestage.autoAusblenden, true);
    assert.equal(b.t.normalisiere(saved).einstellungen.erinnerung.jahrestage.autoAusblenden, true);
    b.ack();
    toggle.checked = false; toggle.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(b.t.daten().einstellungen.erinnerung.jahrestage.autoAusblenden, false);
  }, { einstellungen: { erinnerung: { an: true, vorlauf: 30, art: "notification", jahrestage: { an: true } } } });

  await test("notification controls share persistent partial settings without changing records", async b => {
    const records = JSON.stringify([b.t.daten().termine, b.t.daten().kontakte]);
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-erinnerung").click();
    for (const [selector, value] of [["#erinnerung-vorlauf", "120"], ["#erinnerung-jahrestage-tage", "7"], ["#erinnerung-art", "sound"]]) {
      const field = b.w.document.querySelector(selector); field.value = value;
      field.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      b.ack(); await tick();
    }
    const saved = b.t.normalisiere(JSON.parse(b.saves().at(-1).text)).einstellungen.erinnerung;
    assert.equal(saved.vorlauf, 120); assert.equal(saved.art, "sound"); assert.equal(saved.jahrestage.tage, 7);
    assert.equal(saved.jahrestage.stunde, 10); assert.equal(saved.jahrestage.autoAusblenden, true);
    assert.equal(JSON.stringify([b.t.daten().termine, b.t.daten().kontakte]), records);
  }, { einstellungen: { erinnerung: { an: true, jahrestage: { an: true, stunde: 10, autoAusblenden: true } } } });

  await test("contact preference controls preserve membership and move the selected index", async b => {
    const records = JSON.stringify([b.t.daten().kontakte, b.t.daten().eigenesProfil]);
    b.t.zustand().adressen.auswahlId = "owned-sort-contact"; b.t.zustand().adressen.buchstabe = "Z";
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-adressen").click();
    const sort = b.w.document.querySelector("#adressen-sortierung"); sort.value = "first-name";
    sort.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(b.t.zustand().adressen.buchstabe, "A");
    for (const selector of ["#adressen-personengruppen", "#adressen-eigenes-profil", "#adressen-foto"]) {
      const field = b.w.document.querySelector(selector); field.checked = false;
      field.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    }
    const sender = b.w.document.querySelector("#adressen-absender"); sender.value = "Owned sender\nOwned street 1";
    sender.dispatchEvent(new b.w.Event("input", { bubbles: true }));
    const country = b.w.document.querySelector("#adressen-land"); country.value = "France";
    country.dispatchEvent(new b.w.Event("input", { bubbles: true }));
    b.t.speichereJetzt(); b.ack(); await tick(); b.t.speichereJetzt();
    const saved = b.t.normalisiere(JSON.parse(b.saves().at(-1).text)).einstellungen.adressen;
    assert.equal(saved.sortierung, "first-name"); assert.equal(saved.absender, sender.value);
    assert.equal(saved.personengruppenAn, false); assert.equal(saved.eigenesProfilAn, false); assert.equal(saved.foto, false);
    assert.equal(saved.landCode, ""); assert.equal(JSON.stringify([b.t.daten().kontakte, b.t.daten().eigenesProfil]), records);
  }, { kontakte: [{ id: "owned-sort-contact", vorname: "Alice", nachname: "Zed", vcardRoundtrip: ["BEGIN:VCARD", "CATEGORIES:Work,Colleagues", "END:VCARD"] }],
    einstellungen: { adressen: { personengruppenAn: true } } });

  await test("trash policy controls retain contents and manual-only retention", async b => {
    const contents = JSON.stringify(b.t.daten().papierkorb); assert.equal(b.t.daten().papierkorb.length, 1);
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sicherheit").click();
    const days = b.w.document.querySelector("#papierkorb-tage"); days.value = "0";
    days.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    const enabled = b.w.document.querySelector("#papierkorb-an"); enabled.checked = false;
    enabled.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(b.w.document.querySelector("#papierkorb-tage").disabled, true);
    b.t.speichereJetzt(); b.ack(); await tick(); b.t.speichereJetzt();
    const saved = b.t.normalisiere(JSON.parse(b.saves().at(-1).text));
    assert.equal(saved.einstellungen.papierkorb.an, false); assert.equal(saved.einstellungen.papierkorb.tage, 0);
    assert.equal(JSON.stringify(b.t.daten().papierkorb), contents); assert.equal(saved.papierkorb.length, 1);
  }, { papierkorb: [{ id: "owned-trash-policy", art: "note", name: "Owned trash", geloescht: Date.now(), eintrag: { id: "owned-trashed-note", titel: "Owned trash", text: "Owned content" } }] });

  await test("reminder privacy revocation clears the independent confidential opt-in", async b => {
    const background = JSON.stringify(b.t.daten().einstellungen.sicherheit.hintergrund);
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sicherheit").click();
    const change = (selector, value) => {
      const field = b.w.document.querySelector(selector); field.checked = value;
      field.dispatchEvent(new b.w.Event("change", { bubbles: true })); b.ack();
    };
    change("#kennwort-erinnerungen", false);
    assert.equal(b.w.document.querySelector("#kennwort-vertraulich").disabled, true);
    assert.equal(b.w.document.querySelector("#kennwort-vertraulich").checked, false);
    change("#kennwort-erinnerungen", true);
    assert.equal(b.w.document.querySelector("#kennwort-vertraulich").checked, false);
    change("#kennwort-vertraulich", true);
    const saved = b.t.normalisiere(JSON.parse(b.saves().at(-1).text)).einstellungen.sicherheit;
    assert.equal(saved.erinnernTrotzKennwort, true); assert.equal(saved.vertraulicheErinnerungen, true);
    assert.equal(JSON.stringify(saved.hintergrund), background);
  }, { einstellungen: { sicherheit: { erinnernTrotzKennwort: true, vertraulicheErinnerungen: true } } });

  await test("GUI exchange exports share contact preparation without changing private records", async b => {
    const before = JSON.stringify(b.t.daten());
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-export").click();
    for (const name of ["Appointments (.ics)", "Contacts (.vcf)"]) {
      const button = [...b.w.document.querySelectorAll("#einstellungen-schleier button")].find(button => button.textContent === name);
      assert.ok(button, name); button.click(); await tick();
    }
    const exports = b.messages.filter(message => message.cmd === "export");
    assert.equal(exports.length, 2); assert.equal(exports[0].art, "ics-termine"); assert.equal(exports[1].art, "vcf-adressen");
    assert.equal(exports[1].daten[0].syncQuellen, undefined); assert.equal(exports[1].daten[0].fotoAlternativen, undefined);
    assert.equal(JSON.stringify(b.t.daten()), before);
  }, { termine: [{ id: "owned-export-event", titel: "Owned event", datum: "2030-01-02", zeit: "09:00" }],
    kontakte: [{ id: "owned-export-contact", vorname: "Owned", nachname: "Export", syncQuellen: { owned: { marker: "private" } } }] });

  await test("mixed file import shares entity merges and preserves source metadata on replay", async b => {
    const payload = { termine: [{ uid: "owned-mixed-event", datum: "2030-01-02", zeit: "09:00", titel: "Owned mixed appointment", icsQuelleId: "owned-source",
      icsRoundtrip: ["BEGIN:VEVENT", "UID:owned-mixed-event", "DTSTART:20300102T090000Z", "X-OWNED-FIELD:preserve", "END:VEVENT"] }],
      jahrestage: [{ uid: "owned-mixed-anniversary", name: "Owned anniversary", datum: "2000-02-03", typ: "anniversary" }],
      geburtstage: [{ uid: "owned-mixed-birthday", name: "Owned birthday", datum: "2000-02-04" }],
      aufgaben: [{ uid: "owned-mixed-task", titel: "Owned mixed task", faellig: "2030-01-02", icsQuelleId: "owned-source" }],
      notizen: [{ titel: "Owned mixed note", text: "Owned note text", html: "<p>Owned note text</p>" }] };
    b.w.App.importErgebnis(payload);
    assert.equal(b.t.daten().termine.length, 1); assert.equal(b.t.daten().jahrestage.length, 2);
    assert.equal(b.t.daten().aufgaben.length, 1); assert.equal(b.t.daten().notizen.length, 1);
    assert.ok(b.t.daten().termine[0].icsRoundtrip.includes("X-OWNED-FIELD:preserve"));
    const after = JSON.stringify(b.t.daten()); b.w.App.importErgebnis(payload);
    assert.equal(JSON.stringify(b.t.daten()), after, "Replaying an unchanged additive file import must not duplicate its records");
    b.t.speichereJetzt();
    for (let index = 0; index < 3; index++) { b.ack(); await tick(); }
    const stored = JSON.parse(b.saves().at(-1).text);
    assert.equal(stored.termine.length, 1); assert.equal(stored.jahrestage.length, 2); assert.equal(stored.notizen.length, 1);
  });

  await test("silent note import reports omissions and honors an explicit destination notebook", async b => {
    const first = b.t.daten().notizbuecher[0];
    b.t.daten().notizbuecher.push({ ...plain(first), id: "owned-import-destination", name: "Owned import destination" });
    b.t.zustand().notizen.notizbuchId = first.id;
    const toast = b.w.document.querySelector("#zettel").textContent;
    const result = b.t.mergeNotizen([null, {}, { titel: "Owned oversized import", text: "Owned oversized", html: "<span>x</span>".repeat(10001) },
      { titel: "Owned silent import", text: "Owned imported content", html: "<p>Owned imported content</p>" }], true, "owned-import-destination");
    assert.deepEqual(plain(result), { neu: 1, doppelt: 0, uebersprungen: 3 });
    assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
    assert.equal(b.t.zustand().notizen.notizbuchId, first.id);
    assert.equal(b.t.daten().notizen.find(note => note.titel === "Owned silent import").notizbuchId, "owned-import-destination");
    assert.ok(!b.t.daten().notizen.some(note => note.titel === "Owned oversized import"));
  });

  await test("health preference controls retain canonical measurements and mirror tab state", async b => {
    const measurements = JSON.stringify(b.t.daten().gesundheit);
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-kalender").click();
    const change = async (selector, value) => {
      const field = b.w.document.querySelector(selector); assert.ok(field, selector);
      if (field.type === "checkbox") field.checked = value;
      else { field.value = value; field.dispatchEvent(new b.w.Event("input", { bubbles: true })); }
      field.dispatchEvent(new b.w.Event("change", { bubbles: true })); await tick(); return field;
    };
    await change("#kalender-gesundheit-einheit-gewicht", "lb");
    assert.equal(b.t.daten().einstellungen.kalender.gesundheitEinheiten.gewicht, "lb");
    await change("#kalender-gesundheit-plan-vital", true);
    await change("#kalender-gesundheit-von-vital", "2028-02-29");
    await change("#kalender-gesundheit-intervall-vital", "7");
    assert.equal(b.t.daten().einstellungen.kalender.gesundheitPlanung.vital.zeit, "");
    assert.equal(b.t.daten().einstellungen.kalender.gesundheitPlanung.vital.intervallTage, 7);
    for (const key of ["medikamente", "blutzucker", "verlauf"]) await change("#kalender-gesundheit-" + key, false);
    const lastView = await change("#kalender-gesundheit-vital", false);
    assert.equal(lastView.checked, true); assert.equal(b.t.daten().einstellungen.kalender.gesundheitBereiche.vital, true);
    await change("#kalender-gesundheit", false);
    assert.equal(b.t.daten().einstellungen.kalender.gesundheitAn, false);
    assert.equal(b.t.daten().einstellungen.allgemein.registerkarten.gesundheit, false);
    assert.equal(JSON.stringify(b.t.daten().gesundheit), measurements);
    b.t.speichereJetzt(); const saved = JSON.parse(b.saves().at(-1).text), reloaded = b.t.normalisiere(saved);
    assert.equal(reloaded.einstellungen.kalender.gesundheitPlanung.vital.von, "2028-02-29");
    assert.equal(reloaded.einstellungen.kalender.gesundheitAn, false);
  }, { gesundheit: { vitalwerte: [{ id: "owned-vital-units", datum: "2028-02-29", gewicht: 80 }] },
    einstellungen: { kalender: { gesundheitPlanung: { vital: { an: false, von: "2028-01-01", zeit: "06:30", intervallTage: 3 } } } } });

  await test("calendar display controls retain definitions and cycle opt-ins", async b => {
    const records = JSON.stringify([b.t.daten().termine, b.t.daten().tagmarken, b.t.daten().schichten, b.t.daten().zyklusmarker, b.t.daten().urlaube, b.t.daten().muelltermine]);
    b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-kalender").click();
    for (const selector of ["#kalender-wochennummern", "#kalender-planer-wochennummern", "#kalender-vergangene-termine", "#kalender-vergangene-jahrestage", "#kalender-vergangene-ferien", "#kalender-schichtplaner", "#kalender-zykluskalender", "#kalender-urlaubsplaner", "#kalender-muellkalender"]) {
      const field = b.w.document.querySelector(selector); assert.ok(field, selector); field.checked = true;
      field.dispatchEvent(new b.w.Event("change", { bubbles: true })); await tick();
    }
    const calendar = b.t.daten().einstellungen.kalender;
    assert.equal(calendar.wochenNummern, true); assert.equal(calendar.schichtplanerAn, true); assert.equal(calendar.urlaubsplanerAn, true);
    assert.equal(calendar.zyklusErinnerungen.prognose, false); assert.equal(calendar.zyklusErinnerungen.abweichung, false);
    const cycleInputs = [...b.w.document.querySelectorAll("#kalender-gruppe-zykluskalender input[type=number]")];
    assert.equal(cycleInputs.length, 2); cycleInputs[0].value = "4"; cycleInputs[1].value = "9";
    cycleInputs[0].dispatchEvent(new b.w.Event("change", { bubbles: true })); await tick();
    assert.equal(calendar.zyklusErinnerungen.vorlauf, 4); assert.equal(calendar.zyklusErinnerungen.abweichungTage, 9);
    assert.equal(calendar.zyklusErinnerungen.prognose, false);
    assert.equal(JSON.stringify([b.t.daten().termine, b.t.daten().tagmarken, b.t.daten().schichten, b.t.daten().zyklusmarker, b.t.daten().urlaube, b.t.daten().muelltermine]), records);
    b.t.speichereJetzt(); const saved = b.t.normalisiere(JSON.parse(b.saves().at(-1).text));
    assert.equal(saved.einstellungen.kalender.zyklusErinnerungen.vorlauf, 4); assert.equal(saved.einstellungen.kalender.planerWochenNummern, true);
  });

  await test("display typography and tab controls share durable helpers and real view selection", async b => {
    const records = JSON.stringify([b.t.daten().notizen, b.t.daten().aufgaben, b.t.daten().kontakte, b.t.daten().customOrganizer]);
    b.t.oeffneEinstellungen();
    const change = async (selector, value) => {
      const field = b.w.document.querySelector(selector); assert.ok(field, selector);
      if (field.type === "checkbox") field.checked = value; else field.value = value;
      field.dispatchEvent(new b.w.Event("change", { bubbles: true })); await tick();
    };
    await change("#allgemein-drucken", false); await change("#allgemein-hilfsrahmen", true);
    await change("#allgemein-kalenderauswahl", true); await change("#allgemein-linien", false);
    await change("#allgemein-rad", "up-later"); await change("#allgemein-register-notizen", false);
    await change("#allgemein-register-gesundheit", false); await change("#allgemein-register-custom", true);
    b.input("#allgemein-custom-name", "Owned custom tab"); await tick();
    b.w.document.querySelector("#einst-tab-schrift").click();
    await change("#schrift-art", "handwriting"); await change("#schrift-farbe", "blue");
    await change("#schrift-groesse", "large"); await change("#schrift-pruefung", false);
    assert.equal(b.w.document.body.dataset.hilfsrahmen, "an"); assert.equal(b.w.document.body.dataset.kalenderauswahl, "an");
    assert.equal(b.w.document.body.dataset.schrift, "handwriting"); assert.equal(b.w.document.body.dataset.tinte, "blue");
    assert.equal(b.w.document.body.dataset.groesse, "large"); assert.equal(b.w.document.body.dataset.linien, "aus");
    assert.equal(b.t.daten().einstellungen.kalender.gesundheitAn, false);
    b.w.document.querySelector("#einstellungen-zu").click(); await tick();
    b.w.document.querySelector("#ansicht-umschalter [data-ansicht=month]").click(); await tick();
    assert.equal(b.t.zustand().kalender.ansicht, "month");
    assert.equal(b.w.document.querySelector("#ansicht-umschalter [data-ansicht=month]").getAttribute("aria-pressed"), "true");
    assert.equal(JSON.stringify([b.t.daten().notizen, b.t.daten().aufgaben, b.t.daten().kontakte, b.t.daten().customOrganizer]), records);
    b.t.speichereJetzt(); const reloaded = b.t.normalisiere(JSON.parse(b.saves().at(-1).text));
    assert.equal(reloaded.einstellungen.schrift.art, "handwriting"); assert.equal(reloaded.einstellungen.ansicht, "month");
    assert.equal(reloaded.einstellungen.allgemein.customTab.name, "Owned custom tab"); assert.equal(reloaded.einstellungen.kalender.gesundheitAn, false);
  });

  await test("search ASCII fast path preserves Turkish I and non-ASCII folding", async b => {
    b.t.daten().termine = [{ id: "ascii", titel: "I", datum: "2026-09-08" },
      { id: "unicode", titel: "ÉCOLE", datum: "2026-09-08" }];
    assert.equal(b.t.suchTrefferFuer("kalender", ["i"], 101).length, 1);
    assert.equal(b.t.suchTrefferFuer("kalender", ["école"], 101).length, 1);
    b.w.eval(fs.readFileSync(path.join(web, "i18n/tr.js"), "utf8"));
    b.w.MagnolieI18n.setLocale("tr");
    assert.equal(b.t.suchTrefferFuer("kalender", ["ı"], 101).length, 1);
    assert.equal(b.t.suchTrefferFuer("kalender", ["i"], 101).length, 0);
    assert.equal(b.t.suchTrefferFuer("kalender", ["école"], 101).length, 1);
    b.t.daten().einstellungen.regional.formatLocale = "system";
    const systemI = "I".toLocaleLowerCase(new b.w.Intl.DateTimeFormat().resolvedOptions().locale);
    assert.equal(b.t.suchTrefferFuer("kalender", [systemI], 101).length, 1);
  });

  await test("filtered completed deletion", async b => {
    b.t.zustand().aufgaben.filter.person = "p1"; await b.t.wechsel("aufgaben");
    b.w.document.querySelector(".zwischentitel button").click();
    assert.match(b.w.document.querySelector("#dialog-text").textContent, /1 completed task/);
    b.w.document.querySelector("#dialog-ja").click(); await tick();
    assert.deepEqual(plain(b.t.daten().aufgaben.map(a => a.id)), ["hidden"]);
    assert.deepEqual(plain(b.t.daten().geloescht.aufgaben.map(a => a.uid)), ["visible-uid"]);
  }, { personen: [{ id: "p1", name: "One" }, { id: "p2", name: "Two" }], aufgaben: [
    { id: "visible", uid: "visible-uid", titel: "Visible", erledigt: true, personen: ["p1"], sync: true },
    { id: "hidden", uid: "hidden-uid", titel: "Hidden", erledigt: true, personen: ["p2"], sync: true }] });

  await test("task navigation save and cancel", async b => {
    await b.t.wechsel("aufgaben"); b.input("#aufgabe-titel", "Draft task");
    const cancelled = b.t.wechsel("notizen"); b.answer("Cancel"); await cancelled;
    assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Draft task");
    const saved = b.t.wechsel("notizen"); b.answer("Save"); await saved;
    assert.equal(b.t.daten().aufgaben[0].titel, "Draft task"); assert.equal(b.t.zustand().sektion, "notizen");
  });

  await test("task filter and cancelled delete retain editor registration", async b => {
    await b.t.wechsel("aufgaben");
    b.w.document.querySelector(".loesch-x").click();
    b.w.document.querySelector("#dialog-nein").click(); await tick();
    b.input("#aufgabe-titel", "Still guarded");
    const filter = b.w.document.querySelector("#filter-person");
    filter.value = "person"; filter.dispatchEvent(new b.w.Event("change"));
    b.answer("Cancel"); await tick();
    assert.equal(filter.value, ""); assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Still guarded");
    const navigation = b.t.wechsel("notizen"); b.answer("Discard"); await navigation;
    assert.equal(b.t.daten().aufgaben.length, 1);
  }, { personen: [{ id: "person", name: "Person" }], aufgaben: [{ id: "existing", uid: "existing", titel: "Existing" }] });

  await test("native quit preserves modal appointment", async b => {
    b.t.oeffneTerminBlatt(null, "2026-09-10"); b.input("#tb-titel", "Draft appointment");
    b.w.App.vorBeenden(); b.answer("Cancel"); await tick();
    assert.ok(b.messages.some(message => message.cmd === "beenden_abgebrochen"));
    assert.equal(b.w.document.querySelector("#tb-titel").value, "Draft appointment");
    b.w.App.vorBeenden(); b.answer("Save"); await tick();
    assert.equal(b.t.daten().termine[0].titel, "Draft appointment");
    assert.ok(!b.messages.some(message => message.cmd === "beenden_bereit"));
    b.ack(); assert.ok(b.messages.some(message => message.cmd === "beenden_bereit"));
  });

  await test("calendar arrows turn the current spread without taking keys from focused controls", async b => {
    const d = b.w.document, calendar = b.t.zustand().kalender;
    const key = (name, target = d.body, options = {}) => {
      const event = new b.w.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...options });
      target.dispatchEvent(event);
      return event.defaultPrevented;
    };
    d.querySelector("#deckel").click();
    const original = JSON.stringify(b.t.daten());
    for (const [view, expected, previous] of [["month", 0, 11], ["week", "2027-01-07", "2026-12-31"], ["day", "2027-01-02", "2026-12-31"]]) {
      await b.t.wechsel("aufgaben");
      Object.assign(calendar, { ansicht: view, jahr: 2026, monat: 11, tag: "2026-12-31", uebersichtAb: "2026-12-31" });
      await b.t.wechsel("kalender");
      assert.equal(key("ArrowRight"), true);
      assert.deepEqual(view === "month" ? [calendar.jahr, calendar.monat] : calendar.tag,
        view === "month" ? [2027, expected] : expected);
      assert.equal(key("ArrowLeft"), true);
      assert.deepEqual(view === "month" ? [calendar.jahr, calendar.monat] : calendar.tag,
        view === "month" ? [2026, previous] : previous);
    }
    assert.equal(key("ArrowRight", d.body, { altKey: true }), false);
    assert.equal(key("ArrowRight", d.body, { shiftKey: true }), false);
    const input = d.createElement("input"); input.value = "Editable text"; d.body.append(input);
    input.focus();
    assert.equal(key("ArrowRight", input), false);
    assert.equal(input.value, "Editable text"); input.remove();
    const text = d.createElement("div"); text.setAttribute("contenteditable", "true"); const inner = d.createElement("span");
    text.append(inner); d.body.append(text);
    assert.equal(key("ArrowRight", inner), false); text.remove();
    b.t.oeffneTerminBlatt(null, "2026-12-31");
    assert.equal(key("ArrowRight"), false);
    assert.equal(calendar.tag, "2026-12-31");
    assert.equal(JSON.stringify(b.t.daten()), original);
    assert.equal(b.saves().length, 0);
  });

  await test("a focused calendar day retains arrow-key day navigation", async b => {
    const d = b.w.document, calendar = b.t.zustand().kalender;
    d.querySelector("#deckel").click();
    await b.t.wechsel("aufgaben");
    assert.equal(d.body.dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })), true);
    Object.assign(calendar, { ansicht: "month", jahr: 2026, monat: 11, tag: "2026-12-15", uebersichtAb: "2026-12-15" });
    await b.t.wechsel("kalender");
    const day = d.querySelector('[data-fokus="kalender-tag:2026-12-15"]');
    day.focus();
    const event = new b.w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true });
    day.dispatchEvent(event);
    assert.equal(event.defaultPrevented, true);
    assert.equal(d.activeElement.getAttribute("data-fokus"), "kalender-tag:2026-12-16");
    assert.equal(calendar.tag, "2026-12-15");
    assert.equal(calendar.monat, 11);
  });

  await test("grid time is initialized before the dirty snapshot and time-wheel baseline", async b => {
    await b.t.wechsel("aufgaben");
    b.t.zustand().kalender.ansicht = "day";
    await b.t.wechsel("kalender");
    const hour = () => b.w.document.querySelector('#inhalt-links .stunden-reihe[data-stunde="9"] .stunden-feld');
    assert.ok(hour()); hour().click();
    assert.equal(b.w.document.querySelector("#tb-zeit").value, "09:00");
    const cancel = () => [...b.w.document.querySelectorAll("#termin-schleier button")].find(button => button.textContent === "Cancel").click();
    cancel();
    assert.ok(!b.w.document.querySelector("#termin-schleier"));
    assert.ok(!b.w.document.querySelector("#aenderungen-schleier"));
    hour().click();
    const time = b.input("#tb-zeit", "10:00"); time.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.equal(b.w.document.querySelector("#tb-endzeit").value, "11:00");
    cancel(); assert.ok(b.w.document.querySelector("#aenderungen-schleier"));
    b.answer("Discard"); await tick();
    assert.equal(b.t.daten().termine.length, 0);
  });

  await test("late calendar worker does not rebuild contact", async b => {
    let worker, frame, terminations = 0;
    b.w.Worker = class {
      constructor() { worker = this; }
      postMessage(job) { this.job = job; }
      terminate() { terminations++; }
    };
    b.w.URL.createObjectURL = () => "blob:regression"; b.w.URL.revokeObjectURL = () => {};
    b.w.requestAnimationFrame = fn => { frame = fn; return 1; };
    b.t.icsRuntime("expand", { icsRoundtrip: ["DTSTART:20260908T120000Z", "RRULE:FREQ=DAILY"] }, [0, 1]);
    await b.t.wechsel("adressen");
    [...b.w.document.querySelectorAll("#kopf-links button")].find(button => button.textContent === "New").click();
    const field = b.input("#kontakt-nachname", "Keep draft"); field.focus();
    const identity = b.w.MagnolieTime.identity.payloadSHA256;
    assert.equal(worker.job.timeZoneIdentity, identity);
    const before = JSON.stringify(b.t.daten());
    worker.onmessage({ data: { key: worker.job.key, timeZoneIdentity: identity, result: [] } }); frame();
    assert.equal(terminations, 0);
    assert.equal(b.t.icsRuntime.state.jobs.get(worker.job.key).status, "ready");
    assert.equal(field.isConnected, true); assert.equal(field.value, "Keep draft");
    assert.equal(b.w.document.activeElement, field);
    // A separate malformed response must still fail closed without losing the
    // contact draft; supplying a no-op terminate alone would hide this branch.
    b.t.icsRuntime("expand", { uid: "synthetic-wrong-provider", icsRoundtrip: ["DTSTART:20260908T120000Z", "RRULE:FREQ=DAILY"] }, [0, 1]);
    const key = worker.job.key;
    worker.onmessage({ data: { key, timeZoneIdentity: "0".repeat(64), result: [] } }); frame();
    assert.equal(terminations, 1);
    assert.equal(b.t.icsRuntime.state.worker, null);
    assert.equal(b.t.icsRuntime.state.jobs.get(key).error, "timezone-provider-identity");
    assert.equal(JSON.stringify(b.t.daten()), before);
    assert.equal(field.isConnected, true); assert.equal(field.value, "Keep draft");
    assert.equal(b.w.document.activeElement, field);
  });

  await test("custom text recycle bin survives reload with links", async b => {
    const d = b.t.daten(); d.einstellungen.allgemein.customTab.enabled = true;
    d.customOrganizer = { version: 3, modules: [
      { id: "text", type: "notes", page: "left", order: 0, items: [{ id: "stable", title: "Text", text: "Keep", html: "<b>Keep</b>" }] },
      { id: "tasks", type: "tasks", page: "right", order: 0, items: [{ id: "task", title: "Task", textItemId: "stable" }] }] };
    await b.t.wechsel("custom"); b.w.document.querySelector(".custom-modul-notes .rot").click();
    assert.equal(d.customOrganizer.modules[0].items.length, 1);
    b.w.document.querySelector("#dialog-ja").click(); await tick();
    assert.equal(d.customOrganizer.modules[0].items.length, 0);
    assert.equal(d.customOrganizer.modules[1].items[0].textItemId, "");
    b.w.App.init({ daten: plain(d), neu: false });
    assert.equal(b.t.daten().papierkorb.length, 1);
    assert.equal(b.t.ausDemPapierkorb(b.t.daten().papierkorb[0]), true);
    const modules = b.t.daten().customOrganizer.modules;
    assert.equal(modules.find(m => m.type === "notes").items[0].html, "<b>Keep</b>");
    assert.equal(modules.find(m => m.type === "tasks").items[0].textItemId, "stable");
  });

  await test("custom modal participates in native quit guard", async b => {
    b.t.daten().einstellungen.allgemein.customTab.enabled = true;
    b.t.daten().customOrganizer = { version: 3, modules: [{ id: "module", type: "tasks", page: "left", items: [] }] };
    await b.t.wechsel("custom"); b.w.document.querySelector(".custom-modul-kopf-aktionen button").click();
    b.input(".custom-eintrag-formular input[type=text]", "Custom draft");
    b.w.App.vorBeenden(); b.answer("Save"); await tick();
    assert.equal(b.t.daten().customOrganizer.modules[0].items[0].title, "Custom draft");
    b.ack(); assert.ok(b.messages.some(m => m.cmd === "beenden_bereit"));
  });

  await test("note snapshot survives asynchronous sync handoff", async b => {
    await b.t.wechsel("notizen");
    const field = b.w.document.querySelector("#notiz-text");
    field.innerHTML = "Latest pending text"; field.dispatchEvent(new b.w.Event("input", { bubbles: true }));
    b.w.App.syncFertig({ termine: [], aufgaben: [], kontakte: [], jahrestage: [] });
    assert.equal(b.t.daten().notizen[0].text, "Latest pending text");
    await b.t.wechsel("adressen"); b.t.speichereJetzt();
    assert.equal(JSON.parse(b.saves().at(-1).text).notizen[0].text, "Latest pending text");
  }, { notizen: [{ id: "note", titel: "Note", text: "Old", html: "Old" }] });

  await test("successful provider sync cleans existing equal notes without a new note delivery", async b => {
    assert.equal(b.t.daten().notizen.length,2,"opening a profile must not silently rewrite its notes");
    b.w.App.syncFertig({ok:true,termine:[],aufgaben:[],kontakte:[],jahrestage:[]});
    assert.equal(b.t.daten().notizen.length,1,"a completed explicit sync must not leave old equal copies waiting for an unrelated future delivery");
    const note=b.t.daten().notizen[0];
    assert.ok(note.baumFreigabe.partner.includes("peer"));
    assert.equal(note.persoenlichVerknuepft,true,"keep the pre-existing personal side of the merged note");
    b.t.speichereJetzt();
    assert.equal(JSON.parse(b.saves().at(-1).text).notizen.length,1);
  },{notizen:[
    {id:"own-copy",titel:"Same",text:"Same body",html:"",angelegt:"2026-01-01",geaendert:"2026-01-01"},
    {id:"tree-copy",titel:"Same",text:"Same body",html:"<p>Same body</p>",angelegt:"2026-02-01",geaendert:"2026-02-01",baumQuelle:"peer",baumFreigabe:{id:"remote-note",partner:["peer"],anhangPartner:[]}}
  ]});

  await test("failed provider sync leaves existing note copies untouched",async b=>{
    b.w.App.syncFertig({ok:false,fehler:"Fixture failure",termine:[],aufgaben:[],kontakte:[],jahrestage:[]});
    assert.equal(b.t.daten().notizen.length,2);
  },{notizen:[{id:"first",titel:"Same",text:"Body"},{id:"second",titel:"Same",text:"Body"}]});

  await test("restore protection defers note cleanup through the additive sync",async b=>{
    b.w.App.syncFertig({ok:true,syncMetadaten:{...plain(b.t.daten().syncMetadaten),ersteSyncLoeschungsfrei:false},termine:[],aufgaben:[],kontakte:[],jahrestage:[]});
    assert.equal(b.t.daten().notizen.length,2,"the first protected post-restore run must retain the restored copies");
    b.w.App.syncFertig({ok:true,termine:[],aufgaben:[],kontakte:[],jahrestage:[]});
    assert.equal(b.t.daten().notizen.length,1,"a later ordinary successful synchronization may reconcile equal copies");
  },{syncMetadaten:{ersteSyncLoeschungsfrei:true},notizen:[{id:"first",titel:"Same",text:"Body"},{id:"second",titel:"Same",text:"Body"}]});

  await test("two imported profiles retain their own task parents", async b => {
    for (const source of ["profile-a", "profile-b"]) b.t.mergeAufgaben([
      { uid: "parent", titel: "Parent", icsQuelleId: source, geaendert: 1 },
      { uid: "child", elternUid: "parent", titel: "Child", icsQuelleId: source, geaendert: 1 }]);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    b.t.mergeAufgaben([{ uid: "child", elternUid: "parent", titel: "Updated", icsQuelleId: "profile-b", geaendert: 2 }]);
    const tasks = b.t.daten().aufgaben; assert.equal(tasks.length, 4);
    for (const source of ["profile-a", "profile-b"]) {
      const own = tasks.filter(a => a.icsQuelleId === source);
      const parent = own.find(a => a.icsImportUid === "parent"), child = own.find(a => a.icsImportUid === "child");
      assert.equal(child.elternUid, parent.uid);
    }
    assert.equal(tasks.find(a => a.icsQuelleId === "profile-a" && a.icsImportUid === "child").titel, "Child");
  });

  await test("calendar and anniversary metadata roundtrip", async b => {
    const metadata = { icsTimezones: [["BEGIN:VTIMEZONE", "TZID:Private", "END:VTIMEZONE"]],
      icsAnzeigeZeitzone: "Europe/Berlin", icsRangeOverrides: [["RECURRENCE-ID:20260908T120000Z"]],
      icsAusnahmeTermine: [{ datum: "2026-09-08", zeit: "12:00:01" }], icsRoundtrip: ["X-LONG:" + "x".repeat(5000)] };
    b.t.mergeTermine([{ uid: "event", datum: "2026-09-08", titel: "Event", ...metadata }]);
    b.t.mergeJahrestage([{ uid: "anniversary", datum: "2026-09-08", name: "Anniversary", ...metadata }]);
    const normalized = b.t.normalisiere(plain(b.t.daten()));
    for (const field of Object.keys(metadata)) {
      assert.deepEqual(plain(normalized.termine[0][field]), metadata[field], field);
      assert.deepEqual(plain(normalized.jahrestage[0][field]), metadata[field], field);
    }
  });

  await test("older imported task parents stay linked on reimport", async b => {
    b.t.mergeAufgaben([{ uid: "child", elternUid: "parent", titel: "Updated", icsQuelleId: "old-profile", geaendert: 20 }]);
    const task = b.t.daten().aufgaben.find(a => a.id === "child");
    assert.equal(task.elternUid, "parent"); assert.equal(task.titel, "Updated");
  }, { aufgaben: [{ id: "parent", uid: "parent", titel: "Parent", icsQuelleId: "old-profile", geaendert: 10 },
    { id: "child", uid: "child", elternUid: "parent", titel: "Child", icsQuelleId: "old-profile", geaendert: 10 }] });

  await test("source-qualified detached task IDs match native identities", async b => {
    const value = "20260909T120000Z";
    const suffix = web === windows ? "#" + value : "-magnolie-instanz-" + (await b.t.personalSyncHash([{}, value])).slice(0, 16);
    for (const source of ["a", "b"]) b.t.mergeAufgaben([
      { uid: "same", titel: "Master", icsQuelleId: source, geaendert: 1 },
      { uid: "same" + suffix, icsSerienUid: "same", titel: "Instance", icsQuelleId: source,
        icsRoundtrip: ["RECURRENCE-ID:" + value], geaendert: 1 }]);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    for (const source of ["a", "b"]) {
      const own = b.t.daten().aufgaben.filter(item => item.icsQuelleId === source);
      const master = own.find(item => item.icsImportUid === "same");
      const instance = own.find(item => item.icsImportUid === "same" + suffix);
      assert.equal(instance.uid, master.uid + suffix); assert.equal(instance.icsSerienUid, "same");
    }
    assert.equal(b.t.daten().aufgaben.length, 4);
  });

  await test("task series migration requires original identity proof", async b => {
    const source = "proof", suffixes = ["#20260911", "-magnolie-instanz-8e04acb78995f24b"];
    b.t.mergeAufgaben([{ uid: "family", titel: "Master", icsQuelleId: source }]);
    const local = b.t.daten().aufgaben[0].uid;
    const tasks = [{ id: "master", uid: local, icsImportUid: "family", icsSerienUid: local, icsQuelleId: source, titel: "Master" }];
    suffixes.forEach((suffix, i) => tasks.push({ id: "instance" + i, uid: local + suffix,
      icsImportUid: "family" + suffix, icsSerienUid: local, icsQuelleId: source, titel: "Instance",
      icsRoundtrip: ["RECURRENCE-ID;VALUE=DATE:20260911"] }));
    tasks.push({ id: "legitimate", uid: "mag-task-legitimate", titel: "Legitimate", icsSerienUid: "mag-task-legitimate" });
    b.w.App.init({ daten: { aufgaben: tasks }, neu: false });
    for (const task of b.t.daten().aufgaben) assert.equal(task.icsSerienUid,
      task.id === "legitimate" ? "mag-task-legitimate" : "family");
    assert.equal(b.t.daten().aufgaben.find(a => a.id === "master").uid, local);
  });

  await test("both native instance spellings merge by external family and recurrence ID", async b => {
    const source = "same-source";
    b.t.mergeAufgaben([{ uid: "family", titel: "Master", icsQuelleId: source },
      { uid: "family-magnolie-instanz-8e04acb78995f24b", icsSerienUid: "family", icsQuelleId: source,
        titel: "Moved", icsRoundtrip: ["RECURRENCE-ID;VALUE=DATE:20260911"] }]);
    const ids = b.t.daten().aufgaben.map(a => a.id);
    b.t.mergeAufgaben([{ uid: "family#20260911", icsSerienUid: "family", icsQuelleId: source,
      titel: "Moved", icsRoundtrip: ["RECURRENCE-ID;VALUE=DATE:20260911"] }]);
    assert.deepEqual(b.t.daten().aufgaben.map(a => a.id), ids);
    assert.equal(b.t.daten().aufgaben[1].icsSerienUid, "family");
  });

  await test("task draft saves into current objects after metadata sync", async b => {
    b.t.zustand().aufgaben.bearbeiteId = "task"; await b.t.wechsel("aufgaben");
    b.input("#aufgabe-titel", "Local draft");
    const tasks = plain(b.t.daten().aufgaben); tasks[0].geaendert = 200;
    b.w.App.syncFertig({ aufgaben: tasks });
    assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Local draft");
    b.w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    assert.equal(b.t.daten().aufgaben[0].titel, "Local draft");
  }, { aufgaben: [{ id: "task", uid: "task", titel: "Original", geaendert: 100 }] });

  await test("contact merge preserves local messenger targets and adds only distinct targets", async b => {
    const contact = b.t.daten().kontakte[0];
    const incoming = { sozialeMedien: [
      { dienst: "whatsapp", wert: "+49 170 1234567" },
      { dienst: "whatsapp", wert: "https://wa.me/491701234567" },
      { dienst: "threema", wert: "https://threema.id/ABC12345" },
      { dienst: "signal", wert: "+49 170 1234567" },
      { dienst: "whatsapp", wert: "+49 171 1234567" },
      { dienst: "whatsapp", wert: "https://wa.me/491711234567" },
      { dienst: "threema", wert: "XYZ98765" },
      { dienst: "telegram", wert: "new_profile" }
    ] };
    const before = plain(contact.sozialeMedien);
    assert.equal(before.length, 2);
    const expected = before.concat([incoming.sozialeMedien[3], incoming.sozialeMedien[4], incoming.sozialeMedien[6], incoming.sozialeMedien[7]]);
    b.t.mergeKontakte([incoming], contact.id);
    assert.deepEqual(plain(contact.sozialeMedien), expected);
    contact.sozialeMedien.push({ dienst: "whatsapp", wert: "+491701234567" });
    b.t.mergeKontakte([incoming], contact.id);
    assert.deepEqual(plain(contact.sozialeMedien), expected, "Already imported duplicate was not removed on recheck");
    const differentAction = { dienst: "whatsapp", wert: "+491701234567", aktionArt: "website", aktionZiel: "https://example.invalid/other" };
    contact.sozialeMedien.push(differentAction);
    b.t.mergeKontakte([incoming], contact.id);
    assert.deepEqual(plain(contact.sozialeMedien), [...expected, differentAction], "A distinct local action was lost");
    b.t.mergeKontakte([incoming], contact.id);
    assert.deepEqual(plain(contact.sozialeMedien), [...expected, differentAction]);
  }, { einstellungen: { regional: { homeCountry: "DE" } }, kontakte: [{ id: "messenger", vorname: "Fixture", sozialeMedien: [
    { dienst: "whatsapp", wert: "0170 / 1234567", aktionArt: "website", aktionZiel: "https://example.invalid/manual" },
    { dienst: "threema", wert: "abc12345" }
  ] }] });

  await test("contact draft saves into current objects after metadata sync", async b => {
    b.t.zustand().adressen.auswahlId = "contact"; b.t.zustand().adressen.modus = "bearbeiten";
    await b.t.wechsel("adressen"); b.input("#kontakt-nachname", "Local draft");
    const contacts = plain(b.t.daten().kontakte); contacts[0].geaendert = 200;
    b.w.App.syncFertig({ kontakte: contacts });
    b.w.document.querySelector(".kontakt-form-knoepfe button").click();
    assert.equal(b.t.daten().kontakte[0].nachname, "Local draft");
  }, { kontakte: [{ id: "contact", uid: "contact", nachname: "Original", geaendert: 100 }] });

  await test("conflicting appointment response cannot silently overwrite either draft", async b => {
    b.t.oeffneTerminBlatt(b.t.daten().termine[0], "2026-09-08"); b.input("#tb-titel", "Local title");
    const appointments = plain(b.t.daten().termine); appointments[0].titel = "Remote title";
    b.w.App.syncFertig({ termine: appointments });
    b.w.document.querySelector("#tb-fertig").click();
    assert.equal(b.t.daten().termine[0].titel, "Remote title");
    assert.equal(b.w.document.querySelector("#tb-titel").value, "Local title");
    assert.match(b.w.document.querySelector("#zettel").textContent, /Conflict/);
  }, { termine: [{ id: "appointment", uid: "appointment", datum: "2026-09-08", titel: "Original" }] });

  await test("title-only appointment editor keeps DTSTART and RRULE", async b => {
    const appointment = b.t.daten().termine[0];
    b.t.oeffneTerminBlatt(appointment, "2026-09-08"); b.input("#tb-titel", "Renamed");
    b.w.document.querySelector("#tb-fertig").click();
    assert.equal(appointment.titel, "Renamed");
    assert.ok(appointment.icsRoundtrip.includes("DTSTART:20260908T120000Z"));
    assert.ok(appointment.icsRoundtrip.includes("RRULE:FREQ=DAILY"));
  }, { termine: [{ id: "appointment", uid: "appointment", datum: "2026-09-08", zeit: "12:00", endZeit: "13:00", titel: "Original",
    wiederholung: { art: "daily", bis: "" }, icsRoundtrip: ["DTSTART:20260908T120000Z", "DTEND:20260908T130000Z", "RRULE:FREQ=DAILY"] }] });

  for (const [art, intervall, ordinal] of [["daily", 3, false], ["weekly", 2, false],
    ["monthly", 2, false], ["yearly", 2, false], ["monthly", 2, true]]) {
    const recurrence = { art, bis: "", intervall,
      ...(ordinal ? { ordinal: 2, wochentag: "MO" } : {}) };
    const rule = `RRULE:FREQ=${art.toUpperCase()};INTERVAL=${intervall}` + (ordinal ? ";BYDAY=2MO" : "");
    await test(`title-only edit preserves ${rule}`, async b => {
      const appointment = b.t.daten().termine[0];
      b.t.oeffneTerminBlatt(appointment, "2026-01-12"); b.input("#tb-titel", "Renamed interval");
      b.w.document.querySelector("#tb-fertig").click();
      assert.equal(appointment.titel, "Renamed interval");
      assert.deepEqual(plain(appointment.wiederholung), recurrence);
      assert.ok(appointment.icsRoundtrip.includes(rule));
    }, { termine: [{ id: "interval", uid: "interval", datum: "2026-01-12", zeit: "", titel: "Original",
      wiederholung: recurrence, icsRoundtrip: ["DTSTART;VALUE=DATE:20260112", rule] }] });
  }

  await test("imported interval can explicitly change to the ordinary daily option", async b => {
    const appointment = b.t.daten().termine[0];
    b.t.oeffneTerminBlatt(appointment, "2026-01-12");
    const frequency = b.w.document.querySelector("#tb-wiederholung");
    assert.equal(frequency.value, "daily-3");
    frequency.value = "daily"; frequency.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    b.w.document.querySelector("#tb-fertig").click();
    assert.deepEqual(plain(appointment.wiederholung), { art: "daily", bis: "" });
    assert.ok(appointment.icsRoundtrip.includes("RRULE:FREQ=DAILY"));
    assert.ok(!appointment.icsRoundtrip.some(line => line.includes("INTERVAL=3")));
  }, { termine: [{ id: "interval", uid: "interval", datum: "2026-01-12", zeit: "", titel: "Original",
    wiederholung: { art: "daily", bis: "", intervall: 3 },
    icsRoundtrip: ["DTSTART;VALUE=DATE:20260112", "RRULE:FREQ=DAILY;INTERVAL=3"] }] });

  await test("start-only recurring task keeps its schedule when its title changes", async b => {
    b.t.zustand().aufgaben.bearbeiteId = "start-only"; await b.t.wechsel("aufgaben");
    b.input("#aufgabe-titel", "Renamed start-only");
    b.w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    const task = b.t.daten().aufgaben[0];
    assert.equal(task.titel, "Renamed start-only");
    assert.deepEqual([task.startDatum, task.startZeit, task.faellig, task.faelligZeit],
      ["2026-09-10", "09:00", "", ""]);
    assert.ok(task.icsRoundtrip.includes("DTSTART:20260910T090000Z"));
    assert.ok(task.icsRoundtrip.includes("RRULE:FREQ=DAILY"));
  }, { aufgaben: [{ id: "start-only", uid: "start-only", titel: "Original", startDatum: "2026-09-10",
    startZeit: "09:00", faellig: "", faelligZeit: "",
    icsRoundtrip: ["DTSTART:20260910T090000Z", "RRULE:FREQ=DAILY"] }] });

  await test("overnight task title edit", async b => {
    b.t.zustand().aufgaben.bearbeiteId = "overnight"; await b.t.wechsel("aufgaben");
    assert.match(b.w.document.querySelector("#aufgabe-startdatum").getAttribute("aria-label"), /Date/);
    b.input("#aufgabe-titel", "Updated overnight");
    b.w.document.querySelector("#inhalt-rechts .form-knoepfe button").click();
    const task = b.t.daten().aufgaben[0];
    assert.equal(task.titel, "Updated overnight"); assert.equal(task.startDatum, "2026-09-07");
    assert.equal(task.faellig, "2026-09-08"); assert.equal(task.startZeit, "23:00"); assert.equal(task.faelligZeit, "02:00");
  }, { aufgaben: [{ id: "overnight", uid: "overnight", titel: "Overnight", startDatum: "2026-09-07", faellig: "2026-09-08", startZeit: "23:00", faelligZeit: "02:00" }] });

  await test("recurring checkbox completes only the displayed occurrence", async b => {
    await b.t.wechsel("aufgaben");
    for (let i = 0; i < 1000 && b.w.document.querySelector(".check").disabled; i++) await tick();
    assert.equal(b.w.document.querySelector(".check").disabled, false);
    b.w.document.querySelector(".check").click(); await tick();
    const master = b.t.daten().aufgaben.find(a => a.id === "series");
    assert.equal(master.erledigt, false);
    assert.equal(b.t.daten().aufgaben.filter(a => a.erledigt).length, 1);
    const done = b.t.daten().aufgaben.find(a => a.erledigt);
    const rid = done.icsRoundtrip.find(line => line.startsWith("RECURRENCE-ID"));
    const value = rid.slice(rid.lastIndexOf(":") + 1);
    const suffix = web === windows ? "#" + value : "-magnolie-instanz-" + (await b.t.personalSyncHash([{}, value])).slice(0, 16);
    assert.equal(done.uid, master.uid + suffix, "Native decoder instance identity must roundtrip");
    assert.ok(master.icsRoundtrip.some(line => line.startsWith("EXDATE:")));
    const next = b.t.icsNaechsteAufgabe(master, b.t.isoHeute());
    assert.ok(next && next.icsOccurrence > b.t.daten().aufgaben.find(a => a.erledigt).icsOccurrence);
  }, { aufgaben: [{ id: "series", uid: "series", titel: "Series", startDatum: "2026-01-01", faellig: "2026-01-01", startZeit: "12:00", faelligZeit: "13:00",
    icsRoundtrip: ["BEGIN:VTODO", "UID:series", "DTSTART:20260101T120000Z", "DUE:20260101T130000Z", "RRULE:FREQ=DAILY", "END:VTODO"] }] });

  await test("cached calendar error keeps second print incomplete", async b => {
    const first = b.t.planerMonatsModell(2026, 8), second = b.t.planerMonatsModell(2026, 8);
    assert.equal(first.icsIncomplete, true); assert.equal(second.icsIncomplete, true);
  }, { termine: [{ id: "bad", uid: "bad", datum: "2026-09-08", titel: "Bad zone", icsRoundtrip: ["DTSTART;TZID=Invalid/Zone:20260908T120000", "DURATION:PT1H"] }] });

  await test("all-day instance identity includes native VALUE=DATE parameters", async b => {
    await b.t.wechsel("aufgaben");
    for (let i = 0; i < 1000 && b.w.document.querySelector(".check").disabled; i++) await tick();
    assert.equal(b.w.document.querySelector(".check").disabled, false);
    b.w.document.querySelector(".check").click(); await tick();
    const done = b.t.daten().aufgaben.find(item => item.erledigt);
    const rid = done.icsRoundtrip.find(line => line.startsWith("RECURRENCE-ID;VALUE=DATE:"));
    assert.ok(rid);
    const value = rid.slice(rid.lastIndexOf(":") + 1);
    const suffix = web === windows ? "#" + value : "-magnolie-instanz-" + (await b.t.personalSyncHash([{ VALUE: "DATE" }, value])).slice(0, 16);
    assert.equal(done.uid, "all-day" + suffix);
  }, { aufgaben: [{ id: "all-day", uid: "all-day", titel: "All day", startDatum: "2026-01-01", faellig: "2026-01-02",
    icsRoundtrip: ["DTSTART;VALUE=DATE:20260101", "DUE;VALUE=DATE:20260102", "RRULE:FREQ=DAILY"] }] });

  await test("Personal Sync dirty timestamp preserves DAV baseline despite clock rollback", async b => {
    const old = b.t.daten().aufgaben[0]; b.w.Date.now = () => 100;
    const baseline = plain(old.syncQuellen);
    b.t.personalSyncSetze({ kind: "task", value: { title: "Incoming", note: "", due: "2026-09-09", priority: 2, completed: false, remind: false, modified_ms: 200 } }, "dav", false);
    const task = b.t.daten().aufgaben[0];
    assert.ok(task.geaendert > 10000); assert.deepEqual(plain(task.syncQuellen), baseline);
  }, { aufgaben: [{ id: "dav", uid: "dav", titel: "Original", geaendert: 10000, syncQuellen: { calendar: { id: "href", etag: "baseline" } } }] });

  await test("sync journal ACK requires matching durable save", async b => {
    const transactionId = "a".repeat(64), cmd = web === windows ? "sync_commit" : "sync_bestaetigen";
    b.w.App.syncFertig({ transactionId, termine: [], aufgaben: [], kontakte: [], jahrestage: [] });
    assert.ok(!b.messages.some(message => message.cmd === cmd));
    assert.ok(b.saves().length > 0);
    b.w.App.gespeichert({ id: b.saves().at(-1).id + 20, ok: true });
    assert.ok(!b.messages.some(message => message.cmd === cmd));
    b.ack(false); assert.ok(!b.messages.some(message => message.cmd === cmd));
    b.w.App.syncFertig({ transactionId, termine: [], aufgaben: [], kontakte: [], jahrestage: [] });
    b.ack(); assert.equal(b.messages.filter(message => message.cmd === cmd).length, 1);
  });

  if (fs.existsSync(path.join(web, "phone-media.js"))) await test("Notes live media belongs to Notes and requires one live WLAN peer", async b => {
    b.w.eval(fs.readFileSync(path.join(web, "phone-media.js"), "utf8"));
    const d = b.w.document;
    const peer = { device_id: "notes-peer", fingerprint: "synthetic-pin", display_name: "Test Notes" };
    const report = (peers, extra = {}) => b.w.App.telefonStand({ enabled: true, peers,
      kdeconnect: { paired: 1, available: true, listening: true, device_id: "kde-peer" }, ...extra });
    const webcam = () => d.querySelector("#telefon-webcam");
    const screen = () => d.querySelector("#telefon-bildschirm");
    const wifi = { ...peer, state: "online_wifi", transport: "wifi" };
    report([{ ...peer, state: "offline", transport: "" }]);
    b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-baum").click();
    assert(!webcam() && !screen(), "KDE pairing alone cannot show Notes live media");
    report([wifi]);
    const advanced = d.querySelector(".telefon-karte .telefon-erweitert");
    assert(advanced && !advanced.hidden && !advanced.open);
    assert(advanced.contains(webcam()) && advanced.contains(screen()));
    assert(!d.querySelector(".telefon-kde-karte #telefon-webcam, .telefon-kde-karte #telefon-bildschirm"));
    assert(!b.messages.some(m => /^telefon_(webcam|screen)_/.test(m.cmd)), "Closed section must not request a live operation");
    const oldButton = webcam().querySelector("button:last-child");
    report([{ ...peer, state: "online_bluetooth", transport: "bluetooth" }]);
    assert(!webcam() && !screen());
    oldButton.dispatchEvent(new b.w.Event("click"));
    assert(!b.messages.some(m => /^telefon_(webcam|screen)_/.test(m.cmd)), "Detached tools cannot dispatch");
    report([wifi], { binding_conflict: true }); assert(!webcam() && !screen());
    report([wifi, { ...wifi, device_id: "other" }]); assert(!webcam() && !screen());
    report([wifi]); assert(webcam() && screen());
    report([wifi], { enabled: false }); assert(!webcam() && !screen());
  });

  await test("school holiday display follows region without changing cached rows", async b => {
    await b.t.wechsel("aufgaben");
    const calendar = b.t.zustand().kalender;
    Object.assign(calendar, { jahr: 2026, monat: 11, tag: "2026-12-10", ansicht: "month" });
    await b.t.wechsel("kalender");
    const document = b.w.document;
    const labels = () => [...document.querySelectorAll(".ferien-marke")].map(mark => mark.title).join(" ");
    const before = plain(b.t.daten().feiertage);
    assert.match(labels(), /Saxon break/);
    assert.doesNotMatch(labels(), /Bavarian break|Austrian break/);
    b.t.oeffneEinstellungen(); document.querySelector("#einst-tab-ort").click();
    const region = document.querySelector("#ort-region");
    region.value = "DE-BY"; region.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.match(labels(), /Bavarian break/);
    assert.doesNotMatch(labels(), /Saxon break|Austrian break/);
    const country = document.querySelector("#ort-land");
    country.value = "AT"; country.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    assert.match(labels(), /Austrian break/);
    assert.doesNotMatch(labels(), /Saxon break|Bavarian break/);
    assert.deepEqual(plain(b.t.daten().feiertage), before);
  }, {
    einstellungen: { ort: { land: "DE", region: "DE-SN", ferien: true, feiertage: false } },
    feiertage: [["Saxon break", "DE", "DE-SN"], ["Bavarian break", "DE", "DE-BY"], ["Austrian break", "AT", "AT-9"]]
      .map(([name, country, region]) => ({ id: region, art: "school-holiday", name, country, region, regions: [region],
        von: "2026-12-10", bis: "2026-12-10" }))
  });

  await test("duplicate pending Personal Sync joins save and retries failure", async b => {
    b.w.App.telefonStand({ peers: [{ device_id: "peer", display_name: "Synthetic" }] });
    b.t.daten().personalSync.applied_batches.push("pending-token");
    b.t.speichereJetzt();
    const message = { device_id: "peer", kind: "personal_sync.batch", commit_token: "pending-token", pending_message_id: "message",
      body: { format: 1, run_id: "run", requested_modules: ["tasks"], records: [], reply: true } };
    b.w.App.personalSync(message);
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit").length, 0);
    b.w.App.gespeichert({ ok: true });
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit").length, 0);
    b.ack(false);
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit").length, 0);
    b.w.App.personalSync(message); b.ack();
    assert.equal(b.messages.filter(m => m.cmd === "telefon_personal_sync_commit" && m.erfolgreich).length, 1);
  });

  if (web === windows) await test("connection batch uses isolated candidate and exact SaveACK before reply", async b => {
    const peer = "22222222-2222-4222-8222-222222222222", fingerprint = "ab".repeat(32);
    b.w.App.telefonStand({ enabled: true, peers: [{ device_id: peer, fingerprint, state: "online_wifi", transport: "wifi",
      shared_sync: { supported: true, ready: true, values: { auto_mode: "connection", content_mode: "phone_scope" } } }] });
    const current = b.t.daten();
    const members = { notes: [], tasks: ["connection-task"] };
    const manifest = { format: 10, epoch: "44444444-4444-4444-8444-444444444444", revision: 1,
      scope_hash: await b.t.personalSyncHash(members), members };
    const value = { title: "Connection task", note: "", due: "2026-09-09", priority: 2, completed: false, remind: false,
      lead_days: 0, reminder_minute: 480, uid: "", parent_uid: "", order: 0, created_ms: 1, modified_ms: 2 };
    const record = { kind: "task", id: "connection-task", state: "live", value, hash: await b.t.personalSyncHash(value),
      modified_ms: 2, clock: [{ actor_id: peer, counter: 1 }] };
    const offer = { device_id: peer, content_scope_fingerprint: fingerprint, transport: "wifi", content_scope: manifest,
      expires_ms: Date.now() + 60000, pending_message_id: "batch-message", commit_token: "protected-token",
      body: { format: 3, run_id: "11111111-1111-4111-8111-111111111111", requested_modules: ["tasks"], records: [record] } };
    const protectedSaves = () => b.saves().filter(message => message.personalConnectionLauf);
    const replies = () => b.messages.filter(message => message.cmd === "telefon_personal_connection_reply");
    const waitFor = async condition => {
      const end = Date.now() + 1500;
      while (!condition() && Date.now() < end) await tick();
      assert.ok(condition(), "Protected batch did not reach its next step");
    };
    const acknowledge = (save, ok) => b.w.App.gespeichert({ id: save.id, ok, committed: ok,
      standSha256: require("node:crypto").createHash("sha256").update(save.text).digest("hex") });
    b.t.speichereJetzt();
    acknowledge(b.saves().at(-1), true);
    b.w.App.personalSyncConnectionBatch(offer);
    await waitFor(() => protectedSaves().length === 1);
    const denied = protectedSaves()[0];
    assert.equal(current.aufgaben.length, 0);
    assert.equal(replies().length, 0);
    acknowledge(denied, false);
    await tick();
    assert.equal(current.aufgaben.length, 0);
    assert.equal(replies().length, 0);

    b.w.App.personalSyncConnectionBatch(offer);
    await waitFor(() => protectedSaves().length === 2);
    const save = protectedSaves()[1];
    assert.equal(JSON.parse(save.text).aufgaben[0].titel, "Connection task");
    b.w.App.gespeichert({ id: save.id + 1, ok: true, committed: true, standSha256: "a".repeat(64) });
    assert.equal(replies().length, 0);
    acknowledge(save, true);
    await waitFor(() => replies().length === 1);
    assert.equal(current.aufgaben[0].titel, "Connection task");
    assert.equal(replies()[0].token, offer.commit_token);
    assert.equal(replies()[0].batches[0].records[0].id, "connection-task");
  });

  if (web === windows) await test("scoped original is included in the protected candidate and applied only after its SaveACK", async b => {
    const peer = "22222222-2222-4222-8222-222222222222";
    const fingerprint = "ab".repeat(32);
    b.w.App.telefonStand({ enabled: true, peers: [{ device_id: peer, fingerprint, state: "online_wifi", transport: "wifi",
      shared_sync: { supported: true, ready: true, values: { auto_mode: "connection", content_mode: "phone_scope" } } }] });
    const digest = bytes => require("node:crypto").createHash("sha256").update(bytes).digest("hex");
    const bytes = Buffer.from("%PDF-1.4\nMagnolie attachment fixture\n%%EOF\n");
    const hash = digest(bytes);
    const original = "data:application/pdf;base64," + bytes.toString("base64");
    const id = "original-note";
    const members = { notes: [id], tasks: [] };
    const manifest = { format: 10, epoch: "44444444-4444-4444-8444-444444444444", revision: 1,
      scope_hash: await b.t.personalSyncHash(members), members };
    const descriptor = { attachment_id: "original-file", name: "Original.pdf", kind: "pdf", mime: "application/pdf", size: bytes.length, sha256: hash };
    const value = { title: "Incoming Original", text: "", html: "", notebook_id: "", symbol: "", created_ms: 1, modified_ms: 2,
      attachments: [descriptor] };
    const record = { kind: "note", id, state: "live", value, hash: await b.t.personalSyncHash(value), modified_ms: 2,
      clock: [{ actor_id: peer, counter: 1 }] };
    const offer = { device_id: peer, content_scope_fingerprint: fingerprint, transport: "wifi", content_scope: manifest,
      expires_ms: Date.now() + 60000, pending_message_id: "original-message", commit_token: "original-token",
      body: { format: 3, run_id: "11111111-1111-4111-8111-111111111111", requested_modules: ["notes"], records: [record],
        attachment_data: { [hash]: original } } };
    const acknowledge = save => b.w.App.gespeichert({ id: save.id, ok: true, committed: true, standSha256: digest(save.text) });
    b.t.speichereJetzt();
    acknowledge(b.saves().at(-1));
    b.w.App.personalSyncConnectionBatch(offer);
    const protectedSave = () => b.saves().find(save => save.personalConnectionLauf);
    const deadline = Date.now() + 1500;
    while (!protectedSave() && Date.now() < deadline) await tick();
    const save = protectedSave();
    assert.ok(save, "The original did not reach the protected writer");
    assert.deepEqual(JSON.parse(save.text).notizen[0].anhaenge, [{ id: "original-file", name: "Original.pdf", art: "pdf", daten: original }]);
    assert.equal(b.t.daten().notizen.length, 0);
    acknowledge(save);
    assert.equal(b.t.daten().notizen[0].anhaenge[0].daten, original);
    await tick();
    const reply = b.messages.find(message => message.cmd === "telefon_personal_connection_reply");
    assert.equal(reply.token, "original-token");
    assert.deepEqual(plain(reply.batches[0].records[0].value.attachments), [descriptor]);
    assert(!JSON.stringify(reply).includes(original), "Reply bytes must be obtained from the native saved book");
  });

  if (web === windows) await test("elected connection start waits for its scoped plan and confirmed book", async b => {
    const peer = "22222222-2222-4222-8222-222222222222", fingerprint = "ab".repeat(32);
    const report = ready => b.w.App.telefonStand({ enabled: true, peers: [{ device_id: peer, fingerprint,
      state: "online_bluetooth", transport: "bluetooth", personal_connection_start_ready: ready,
      shared_sync: { supported: true, ready: true, values: { auto_mode: "connection", content_mode: "phone_scope" } } }] });
    const prepares = () => b.messages.filter(m => m.cmd === "telefon_personal_connection_prepare");
    const launches = () => b.messages.filter(m => m.cmd === "telefon_personal_connection_start");
    const members = { notes: ["only-scope"], tasks: [] };
    const plan = { token: "one-use", run_id: "11111111-1111-4111-8111-111111111111", format: 3, transport: "bluetooth",
      scope: { format: 10, epoch: "44444444-4444-4444-8444-444444444444", revision: 1, scope_hash: await b.t.personalSyncHash(members), members } };
    const initial = b.saves().length;
    report(false);
    assert.equal(prepares().length, 0);
    report(true); report(true);
    assert.equal(prepares().length, 1);
    assert.equal(prepares()[0].fingerprint, fingerprint);
    b.w.App.personalConnectionStartPlan({ requestId: "other", plan });
    assert.equal(launches().length, 0);
    b.w.App.personalConnectionStartPlan({ requestId: prepares()[0].requestId, plan });
    const deadline = Date.now() + 1500;
    while (b.saves().length === initial && Date.now() < deadline) await tick();
    const save = b.saves().at(-1);
    assert.ok(b.saves().length > initial && save.cmd === "speichern");
    const sha = require("node:crypto").createHash("sha256").update(save.text).digest("hex");
    b.w.App.gespeichert({ id: save.id + 1, ok: true, committed: true, standSha256: sha });
    assert.equal(launches().length, 0);
    b.w.App.gespeichert({ id: save.id, ok: true, committed: true, standSha256: sha });
    await tick();
    assert.equal(launches().length, 1);
    const start = launches()[0];
    assert.equal(start.sha256, sha);
    assert.equal(start.request.trigger, "auto_connection");
    assert.equal(start.request.run_id, plan.run_id);
    assert.equal(start.token, plan.token);
    const rows = plain(start.batches.flatMap(batch => batch.records));
    const note = rows.find(record => record.kind === "note");
    assert.equal(note.id, "only-scope");
    assert.deepEqual(rows.map(record => record.id), [note.id, note.value.notebook_id]);
    assert(!Object.hasOwn(start, "sources"));
    assert(!b.messages.some(message => message.cmd === "personal_sync_lauf_senden"), "The normal legacy queue received the elected start");
  }, { notizen: [{ id: "only-scope", titel: "Selected" }, { id: "other-note", titel: "Unselected" }] });

  await test("batch hash fault cannot partly update data or clocks", async b => {
    const value = { title: "Valid first record", note: "", due: "2026-09-09", priority: 2, completed: false,
      remind: false, lead_days: 0, reminder_minute: 480, created_ms: 1, modified_ms: 2 };
    const good = { kind: "task", id: "incoming", value, hash: await b.t.personalSyncHash(value),
      modified_ms: 2, clock: [{ actor_id: "00000000-0000-4000-8000-000000000001", counter: 1 }] };
    const before = plain(b.t.daten());
    await assert.rejects(b.t.personalSyncAnwenden([good, { ...good, id: "bad", hash: "0".repeat(64) }], {}, 1, "peer", ["tasks"]));
    assert.deepEqual(plain(b.t.daten().aufgaben), before.aufgaben);
    assert.deepEqual(plain(b.t.daten().personalSync), before.personalSync);
  });

  await test("worker continuation yields beyond sixteen attempts", async b => {
    let source;
    b.w.Blob = class { constructor(parts) { source = parts.join(""); } };
    b.w.URL.createObjectURL = () => "blob:scheduler";
    b.w.URL.revokeObjectURL = () => {};
    b.w.Worker = class { postMessage() {} };
    b.t.icsRuntime("expand", { icsRoundtrip: ["DTSTART:20260908T120000Z"] }, [0, 1]);
    const turns = [], results = [], sandbox = { self: { postMessage: value => results.push(value) }, setTimeout: fn => turns.push(fn), Date, performance };
    vm.createContext(sandbox);
    vm.runInContext(source + '\nlet probes = 0; icsExpansion = () => { if (++probes <= 20) { const error = new Error("continue"); error.retryable = true; error.code = "recurrence-work-limit"; throw error; } return [probes]; };', sandbox);
    const identity = b.w.MagnolieTime.identity.payloadSHA256;
    sandbox.self.onmessage({ data: { key: "job", timeZoneIdentity: identity, zone: "UTC", mode: "expand", item: {}, args: [] } });
    assert.equal(results.length, 0); assert.equal(turns.length, 1);
    let count = 0;
    while (turns.length) { assert.ok(++count < 30); turns.shift()(); }
    assert.equal(count, 20); assert.deepEqual(plain(results), [{ key: "job", timeZoneIdentity: identity, result: [21] }]);
    sandbox.self.onmessage({ data: { key: "wrong-provider", timeZoneIdentity: "0".repeat(64), zone: "UTC", mode: "expand", item: {}, args: [] } });
    assert.deepEqual(plain(results[1]), { key: "wrong-provider", timeZoneIdentity: identity, error: "timezone-provider-identity" });
    assert.equal(turns.length, 0); assert.equal(vm.runInContext("probes", sandbox), 21);
  });

  await test("disabled reminder remains disabled after native response", async b => {
    b.t.oeffneEinstellungen();
    [...b.w.document.querySelectorAll(".einst-reiter-knopf")].find(button => button.textContent === "Notifications").click();
    const toggle = b.w.document.querySelector("#erinnerung-an");
    toggle.checked = false; toggle.dispatchEvent(new b.w.Event("change"));
    b.w.App.erinnerungStand({ ok: true });
    assert.equal(b.t.daten().einstellungen.erinnerung.an, false);
    assert.match(b.w.document.querySelector("#erinnerung-stand").textContent, /not currently reminding/);
  });

  await test("custom bulk removal restores links in either order", async b => {
    b.t.daten().customOrganizer = { version: 3, modules: [
      { id: "note", type: "notes", page: "left", items: [{ id: "text", text: "Keep", html: "Keep" }] },
      { id: "task", type: "tasks", page: "right", items: [{ id: "linked", title: "Linked", textItemId: "text" }] }] };
    const stoff = b.t.druckStoff("custom"); stoff.entfernen(stoff.liste);
    assert.equal(b.t.daten().papierkorb.length, 2);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    const taskTrash = b.t.daten().papierkorb.find(s => s.eintrag.type === "tasks");
    assert.equal(b.t.ausDemPapierkorb(taskTrash), true);
    b.w.App.init({ daten: plain(b.t.daten()), neu: false });
    assert.equal(b.t.ausDemPapierkorb(b.t.daten().papierkorb[0]), true);
    assert.equal(b.t.daten().customOrganizer.modules.find(m => m.type === "tasks").items[0].textItemId, "text");
  });
  console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": " + cases + " desktop state regressions passed");
}

(async () => { for (const root of roots) await run(root); })().catch(error => { console.error(error); process.exitCode = 1; });
