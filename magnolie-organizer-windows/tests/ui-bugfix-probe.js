/* Synthetic source-UI regression, shared by jsdom and isolated software WebKit. */
"use strict";
const uiCheck = (value, message) => { if (!value) throw new Error(message); };
const uiClose = () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
const uiButton = (root, text) => [...root.querySelectorAll("button")].find(b => b.textContent === MagnolieI18n.gettext(text));
const uiPeer = { device_id: "a".repeat(32), own_device: false, remote_own_device: false, state: "pair_commit_pending",
  local_grants: { grants: {} }, grants: { grants: {} }, custom_sync: { local: { enabled: false } },
  capabilities: { items: { personal_tasks_sync: { available: true, versions: [4] } } } };

window.uiBugfixPrepare = function (locale, screen) {
  for (let i = 0; i < 6; i++) uiClose();
  MagnolieI18n.setLocale(locale);
  const data = OrganizerTest.daten();
  data.einstellungen.adressen.smsSchedulingEnabled = false;
  data.smsPlanung = ["planned", "queued", "uncertain"].map((status, i) => ({ id: "ui-plan-" + i,
    kontaktId: "other-contact", nummer: "+12025550123", land: "US", text: "Synthetic " + status,
    zeit: Date.now() + 86400000, status, clientRef: i ? "plan:ui-plan-" + i : "", fehler: "" }));
  App.telefonStand({ enabled: false, peers: [uiPeer], kdeconnect: { available: false } });
  if (screen.startsWith("sms") || screen === "settings" || screen === "plans") {
    App.telefonAntwort({ nummer: "+12025550123", device_id: "b".repeat(32) });
    const chat = document.querySelector(".sms-dialog");
    uiCheck(chat, "SMS dialog did not open");
    const schedule = uiButton(chat, "Schedule");
    uiCheck(schedule.classList.contains("verborgen"), "Schedule must be hidden by default");
    uiCheck(!chat.querySelector(".sms-planung-hinweis").classList.contains("verborgen"), "Missing paused-plan reminder");
    if (screen !== "sms-off") {
      chat.querySelector(".sms-praegung").click();
      const settings = document.querySelector(".sms-einstellungen-dialog");
      const toggle = settings.querySelector('input[type="checkbox"]');
      uiCheck(toggle && !toggle.checked, "SMS scheduling must default off in the real settings");
      if (screen === "sms-on") {
        toggle.click();
        uiCheck(data.einstellungen.adressen.smsSchedulingEnabled === true, "Toggle did not save the preference");
        uiCheck(!schedule.classList.contains("verborgen"), "Explicit opt-in did not show Schedule");
        uiCheck(OrganizerTest.normalisiere(JSON.parse(JSON.stringify(data))).einstellungen.adressen.smsSchedulingEnabled,
          "Preference lost on persistence/import normalization");
        const before = JSON.stringify(data.smsPlanung);
        toggle.click();
        uiCheck(schedule.classList.contains("verborgen"), "Disabling must hide Schedule immediately");
        uiCheck(data.einstellungen.adressen.smsSchedulingEnabled === false && JSON.stringify(data.smsPlanung) === before,
          "Disabling must preserve all plans and their statuses");
        uiCheck(!chat.querySelector(".sms-planung-hinweis").classList.contains("verborgen"), "Disabling must restore the paused-plan reminder");
        toggle.click();
        uiClose();
      } else if (screen === "plans") {
        uiButton(settings, "Pending SMS messages").click();
        uiCheck(document.querySelectorAll(".sms-planung-eintrag").length === 3, "Disabled review must include plans from other contacts");
        uiCheck(!document.querySelector(".sms-planung-zeile"), "Disabled review must not create new plans");
        uiCheck(data.smsPlanung.map(p => p.status).join() === "planned,queued,uncertain", "Review changed persisted statuses");
      }
    }
  } else if (screen === "designer") {
    data.einstellungen.allgemein.customTab.enabled = true;
    data.customOrganizer.modules = ["notes", "tasks", "notes", "appointments"].map((type, i) => ({
      id: "module-" + i, type, title: "", items: [], page: i < 2 ? "left" : "right", order: i, reminders: false }));
    OrganizerTest.oeffneCustomDesigner();
    uiCheck(document.querySelectorAll(".custom-editor-aktionen > button").length === 4, "Each Remove needs its own action row");
    const before = JSON.stringify(data.customOrganizer.modules.map(m => m.id));
    document.querySelector('.custom-editor-karte input[type="checkbox"]').click();
    uiCheck(before === JSON.stringify(data.customOrganizer.modules.map(m => m.id)), "Checkbox activated Remove");
  } else {
    data.einstellungen.allgemein.customTab.name = "Tagebuch";
    OrganizerTest.oeffneGeraeteDialog({ kennung: uiPeer.device_id, name: "Synthetic phone", status: { online: true, battery_percent: 75 } });
    const panel = document.querySelector(".telefon-personal-sync"); panel.open = true;
    const custom = panel.querySelector("[data-personal-custom-peer]");
    uiCheck(custom.parentElement.textContent.includes("Tagebuch"), "Device label does not use the current tab name");
    uiCheck(!document.querySelector('[data-geraet="storage"], [data-geraet="memory"]'), "Redundant available/total device rows remain");
    const unsafe = 'New <b>&"$&%(tab)s';
    data.einstellungen.allgemein.customTab.name = unsafe;
    App.telefonStand({ enabled: false, peers: [uiPeer], kdeconnect: { available: false } });
    uiCheck(custom.parentElement.textContent.includes(unsafe) && !custom.parentElement.querySelector("b"),
      "Tab name must refresh as literal text, not HTML or a replacement template");
    data.einstellungen.allgemein.customTab.name = "";
    App.telefonStand({ enabled: false, peers: [uiPeer], kdeconnect: { available: false } });
    uiCheck(custom.parentElement.textContent.trim() === MagnolieI18n.gettext("Synchronize tasks and appointments from the custom tab"),
      "Unnamed custom tab needs the localized generic description");
    data.einstellungen.allgemein.customTab.name = "Tagebuch";
    App.telefonStand({ enabled: false, peers: [uiPeer], kdeconnect: { available: false } });
    panel.scrollIntoView({ block: "end" });
  }
  return true;
}

window.uiBugfixMeasure = function (screen) {
  const selector = screen === "designer" ? ".custom-designer" : screen === "device" ? "#geraet-dialog" :
    screen === "settings" ? ".sms-einstellungen-dialog" : screen === "plans" ? ".sms-planung-dialog" : ".sms-dialog";
  const dialog = document.querySelector(selector), r = dialog.getBoundingClientRect();
  const errors = [], check = (value, message) => { if (!value) errors.push(message); };
  check(r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1, "Dialog escapes viewport");
  check(dialog.scrollWidth <= dialog.clientWidth + 1, "Dialog has horizontal overflow");
  for (const node of dialog.querySelectorAll("button, label.hak, .einst-hinweis, .einst-warnung")) {
    if (!node.getClientRects().length) continue;
    check(node.scrollWidth <= node.clientWidth + 1, "Text/control overflows: " + node.textContent.slice(0, 60));
  }
  if (screen === "designer") {
    const columns = [...dialog.querySelectorAll(".custom-designer-blatt")].map(n => n.getBoundingClientRect());
    check(innerWidth > 700 ? Math.abs(columns[0].top - columns[1].top) < 1 : columns[1].top >= columns[0].bottom,
      "Responsive designer columns changed");
    for (const row of dialog.querySelectorAll(".custom-editor-aktionen")) {
      const previous = row.previousElementSibling.getBoundingClientRect();
      check(row.getBoundingClientRect().top >= previous.bottom + 11, "Remove is attached to checkbox/field");
    }
  }
  if (screen.startsWith("sms")) {
    const schedule = uiButton(dialog, "Schedule"), send = uiButton(dialog, "Send SMS");
    check((schedule.getBoundingClientRect().width > 0) === (screen === "sms-on"), "Wrong Schedule visibility");
    if (screen === "sms-on") check(Math.abs(schedule.getBoundingClientRect().top - send.getBoundingClientRect().top) < 1,
      "Opt-in actions are not aligned");
  }
  return { screen, locale: document.documentElement.lang, viewport: [innerWidth, innerHeight],
    dialog: [r.x, r.y, r.width, r.height], errors };
}
