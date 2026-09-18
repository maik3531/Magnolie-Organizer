"use strict";

// Adapter only. Organizer models, views, styles and translations remain generated desktop code.
(() => {
  const allowed = new Set(/*GENERATED_COMMANDS*/[]);
  const identity = /*GENERATED_IDENTITY*/{};
  const methods = new Set(["init", "gespeichert", "kennwortStand", "ablage", "sicherungFertig",
    "exportErgebnis", "notizAnhangDateiErgebnis", "erinnerungStand", "vorBeenden", "mutationsSnapshot",
    "sicherungAusgewaehlt", "sicherungWiederhergestellt", "regionalErgebnis"]);
  const unsupported = "Not implemented in Magnolie Organizer macOS Beta. Nothing was changed.";
  const notice = "macOS Beta: local editing/deletion with pre-change recovery files; encrypted JSON backup and full JSON restore; simple appointment ICS; " +
    "attachment Save; clipboard; reminders only while open. No sync, background " +
    "wake, auto-update, password change/removal, printing or office export. Native code is not yet validated.";
  let ready = false, restorePending = false;
  const tr = text => window.MagnolieI18n.gettext(text);

  function show(text) {
    const target = document.getElementById("macos-beta-status");
    if (target) target.textContent = text;
    const panel = document.getElementById("macos-beta-capabilities");
    if (panel) panel.open = true;
  }
  function failure(payload) {
    const app = window.App;
    const command = payload.cmd;
    if (command === "regional_einstellungen") {
      const button = document.getElementById("regional-speichern");
      if (button) button.disabled = false;
    }
    show((command ? command + ": " : "") + payload.fehler);
    if (!app) return;
    const callbacks = {
      speichern: "gespeichert", entsperren: "entsperrtFehler",
      kennwort_setzen: "kennwortStand", kennwort_entfernen: "kennwortStand",
      mutations_snapshot: "mutationsSnapshot", sicherung: "sicherungFertig",
      export: "exportErgebnis", import: "importErgebnis", import_lokal: "importErgebnis",
      erinnerung_einrichten: "erinnerungStand", erinnerung_zeigen: "erinnerungStand",
      notiz_anhang_datei: "notizAnhangDateiErgebnis", sicherung_waehlen: "sicherungAusgewaehlt",
      sicherung_wiederherstellen: "sicherungWiederhergestellt",
      regional_einstellungen: "regionalErgebnis",
      gesamtarchiv_exportieren: "gesamtarchivExportiert", gesamtarchiv_importieren: "gesamtarchivImportiert"
    };
    if (command === "sync") app.syncFehler(payload.fehler);
    else if (callbacks[command]) app[callbacks[command]](payload);
    // Do not fabricate status datasets: several desktop callbacks mutate settings on an empty reply.
  }
  function preserve(old, next, depth = 0) {
    if (depth >= 64) throw new Error("macOS Beta: JSON nesting limit exceeded.");
    if (old === null || typeof old !== "object") return next;
    if (Array.isArray(old)) {
      if (!Array.isArray(next) || next.length < old.length) {
        throw new Error("macOS Beta refused lossy normalization of existing records.");
      }
      const keyed = old.length > 0 && old.every(item => item && typeof item.id === "string");
      const ids = new Map();
      if (keyed) for (const item of next) {
        if (!item || typeof item.id !== "string" || ids.has(item.id)) throw new Error("Ambiguous record IDs.");
        ids.set(item.id, item);
      }
      old.forEach((item, index) => {
        const value = keyed ? ids.get(item.id) : next[index];
        if (keyed && !value) throw new Error("macOS Beta refused dropped record identity.");
        preserve(item, value, depth + 1);
      });
    } else {
      if (!next || typeof next !== "object" || Array.isArray(next)) {
        throw new Error("macOS Beta refused a dropped object.");
      }
      for (const [key, value] of Object.entries(old)) {
        if (!Object.hasOwn(next, key) || next[key] === undefined) {
          Object.defineProperty(next, key, { value: structuredClone(value), writable: true, enumerable: true, configurable: true });
        } else preserve(value, next[key], depth + 1);
      }
    }
    return next;
  }
  window.MacBeta = Object.freeze({
    preserve,
    validateRestore(text) {
      if (!ready || restorePending) throw new Error("Storage is not ready.");
      window.App.macOSBetaValidateRestore(text);
      restorePending = true;
      return true;
    },
    backupControls(root, backup, restore) {
      const heading = document.createElement("h3"); heading.textContent = tr("Backups and recovery");
      const description = document.createElement("p");
      description.textContent = tr("Choose a backup file. Before restoring it, the organizer automatically creates a copy of the current data. An encrypted backup requires its password.");
      const controls = document.createElement("div"); controls.className = "knopfreihe";
      for (const [label, action] of [["Create backup", backup], ["Restore backup …", restore]]) {
        const button = document.createElement("button"); button.type = "button"; button.textContent = tr(label);
        button.addEventListener("click", action); controls.append(button);
      }
      root.append(heading, description, controls);
    },
    taskAlarms(task, organizerZone) {
      if (task.erledigt || !task.faellig || !(task.id || task.uid)) return [];
      const raw = task.icsRoundtrip || [];
      if (!Array.isArray(raw) || raw.some(line => typeof line !== "string" || /^(RRULE|RDATE|EXDATE|EXRULE|RECURRENCE-ID|DURATION)[;:]|^BEGIN:VALARM$/i.test(line)) ||
          (task.wiederholung?.art && task.wiederholung.art !== "none") ||
          ["icsRangeOverrides", "icsAusnahmeTermine", "icsAusnahmen", "icsZusatzDaten", "icsZusatzTermine", "icsTimezones"].some(key => task[key]?.length)) return [];
      const days = Number(task.individuelleErinnerungTage) || 0;
      if (task.erinnern !== true && !(Number.isInteger(days) && days >= 1 && days <= 7)) return [];
      const displayZone = task.icsAnzeigeZeitzone || organizerZone || Intl.DateTimeFormat().resolvedOptions().timeZone;
      const wall = (day, time) => {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new Error("Invalid task date/time.");
        const value = Date.parse(day + "T" + time + ":00Z");
        if (!Number.isFinite(value) || new Date(value).toISOString().slice(0, 16) !== day + "T" + time) throw new Error("Invalid task date/time.");
        return value;
      };
      const resolve = (local, zone, preferred = null) => {
        const formatter = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit",
          day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
        const parts = instant => {
          const p = Object.fromEntries(formatter.formatToParts(new Date(instant)).map(v => [v.type, v.value]));
          return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
        };
        // Sample both offsets around a transition. First fold occurrence is deterministic;
        // nonexistent local times have no match and are not silently shifted into another hour.
        const candidates = new Set();
        for (const delta of [-2, 0, 2]) {
          const sample = local + delta * 86400000, instant = local - (parts(sample) - sample);
          if (parts(instant) === local) candidates.add(instant);
        }
        return candidates.has(preferred) ? preferred : candidates.size ? Math.min(...candidates) : null;
      };
      let sourceWall = wall(task.faellig, task.faelligZeit || "08:00"), sourceZone = displayZone;
      const displayWall = sourceWall;
      let structured = resolve(sourceWall, displayZone);
      if (structured === null) return [];
      const dueLines = raw.filter(line => /^DUE[;:]/i.test(line));
      if (dueLines.length > 1) throw new Error("Conflicting task due properties.");
      if (dueLines.length) {
        const match = /^DUE(?:(;VALUE=DATE)|;TZID=([A-Za-z0-9_+./-]+))?:(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})00(Z)?)?$/.exec(dueLines[0]);
        if (!match || (!!match[1] === !!match[6]) || (match[2] && match[8])) throw new Error("Unsupported task due property.");
        sourceWall = wall(`${match[3]}-${match[4]}-${match[5]}`, match[6] ? `${match[6]}:${match[7]}` : "08:00");
        sourceZone = match[8] ? "UTC" : match[2] || displayZone;
        const sourceDue = resolve(sourceWall, sourceZone);
        if (sourceDue === null || resolve(displayWall, displayZone, sourceDue) !== sourceDue) throw new Error("Raw task due time contradicts its display fields.");
        structured = sourceDue;
      }
      const result = [];
      for (const lead of [0, days]) {
        if (lead === 0 ? task.erinnern !== true || result.some(a => a.days === 0)
          : !Number.isInteger(lead) || lead < 1 || lead > 7) continue;
        // Calendar days in the source zone, not fixed 24-hour durations across DST.
        const at = resolve(sourceWall - lead * 86400000, sourceZone);
        if (at !== null) result.push({ at, dueAt: structured, days: lead,
          id: JSON.stringify(["macOS-Beta-task", task.id || task.uid, structured, lead, at]) });
      }
      return result;
    },
    reminderError() { show("macOS Beta: a task notification has unsupported or contradictory date/time data; it was not sent."); },
    platformNotice(root, text) {
      const paragraph = document.createElement("p");
      paragraph.className = "einst-hinweis"; paragraph.textContent = text;
      root.append(paragraph);
    },
    send(request, bridge) {
      if (!request || !allowed.has(request.cmd)) {
        const result = { cmd: request?.cmd, token: request?.token, ok: false, fehler: unsupported };
        queueMicrotask(() => failure(result));
        return true; // Request handled with a negative result, never a successful mutation ACK.
      }
      if (request.cmd === "speichern" && (!ready || restorePending)) {
        queueMicrotask(() => failure({ cmd: "speichern", id: request.id, ok: false, fehler: "Storage initialization has not succeeded." }));
        return true;
      }
      window.webkit.messageHandlers[bridge].postMessage(JSON.stringify(request));
      return true;
    },
    receive(method, payload) {
      if (method === "sicherungWiederhergestellt" || (method === "failure" && payload.cmd === "sicherung_wiederherstellen")) restorePending = false;
      if (method === "failure") { failure(payload); return; }
      if (!methods.has(method)) throw new Error("Invalid native callback.");
      if (method === "init") {
        ready = false;
        window.App.init(payload);
        ready = payload.gesperrt !== true;
      } else {
        if (method === "sicherungAusgewaehlt" && payload.abgebrochen) return;
        window.App[method](payload);
      }
    }
  });
  document.addEventListener("DOMContentLoaded", () => {
    const details = document.createElement("details");
    details.id = "macos-beta-capabilities";
    const summary = document.createElement("summary"); summary.textContent = identity.name + " " + identity.version;
    const info = document.createElement("p"); info.textContent = notice;
    const status = document.createElement("p"); status.id = "macos-beta-status";
    status.setAttribute("role", "status"); status.textContent = "Waiting for native storage.";
    details.append(summary, info, status); document.body.prepend(details);
  }, { once: true });
})();
