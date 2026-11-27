"use strict";

// Shared Organizer settings remain
// the sole stored selection; discovering/denying access never rewrites them.
(() => {
  let view = null, snapshot = null, pending = null, syncChoice = null;
  const note = "Discover macOS sources, copy selected items, or enable field synchronization for one source. Synchronization first links supported native entries, then exchanges changes to those linked entries. Existing copies and other local entries are not exported. Native confirmation is required once for each source and book.";
  function node(tag, text) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function request(art) {
    if (!view?.root.isConnected || pending) return;
    const requestId = view.id();
    pending = requestId;
    draw();
    const message = art ? { cmd: "macos_systemzugriff", art, requestId } : { cmd: "eds_status", requestId };
    if (!view.send(message)) update({ requestId, fehler: "The macOS source request could not be sent.", ok: false });
  }
  function draw() {
    if (!view?.root.isConnected) return;
    const { root, tr: sharedText, settings, change } = view;
    const tr = text => window.MacBeta.text?.(text) || sharedText(text);
    root.textContent = "";
    root.append(node("h3", tr("System internet accounts")), node("p", tr(note)));
    const state = node("p", snapshot?.fehler || (pending ? tr("Loading …") : ""));
    state.id = "macos-system-status"; state.setAttribute("role", "status"); root.append(state);
    const permissions = snapshot?.permissions || {};
    for (const [art, label] of [["events", "Calendars"], ["reminders", "Tasks"], ["contacts", "Contacts"]]) {
      const row = node("p");
      row.append(node("span", `${tr(label)}: ${permissions[art] || "not_determined"} `));
      const button = node("button", `${tr("Allow access")}: ${tr(label)}`);
      button.type = "button"; button.dataset.systemAccess = art;
      button.disabled = !!pending || permissions[art] === "authorized";
      button.addEventListener("click", () => request(art)); row.append(button); root.append(row);
    }
    const refresh = node("button", tr("Refresh")); refresh.type = "button";
    refresh.id = "macos-system-refresh"; refresh.disabled = !!pending;
    refresh.addEventListener("click", () => request()); root.append(refresh);
    const importCalendar = node("button", tr("Import") + ": macOS " + tr("Calendars"));
    importCalendar.type = "button"; importCalendar.id = "macos-system-calendar-import";
    importCalendar.disabled = !!pending;
    importCalendar.addEventListener("click", () => window.App.macOSBetaStartCalendarImport());
    root.append(importCalendar);
    const importReminders = node("button", tr("Copy macOS reminders"));
    importReminders.type = "button"; importReminders.id = "macos-system-reminder-import";
    importReminders.disabled = !!pending;
    importReminders.addEventListener("click", () => window.App.macOSBetaStartReminderImport());
    root.append(importReminders);
    const importContacts = node("button", tr("Copy macOS contacts"));
    importContacts.type = "button"; importContacts.id = "macos-system-contact-import";
    importContacts.disabled = !!pending;
    importContacts.addEventListener("click", () => window.App.macOSBetaStartContactImport());
    root.append(importContacts);
    const importNotes = node("button", tr("Text copies from Apple Notes"));
    importNotes.type = "button"; importNotes.id = "macos-apple-notes-import";
    importNotes.disabled = !!pending;
    importNotes.addEventListener("click", () => window.App.macOSBetaStartAppleNotesImport());
    root.append(importNotes);
    const chosen = settings();
    const selected = [...new Set([...(chosen.kalenderUids || []), ...(chosen.kalenderUid ? [chosen.kalenderUid] : [])])];
    const calendars = Array.isArray(snapshot?.kalender) ? snapshot.kalender : [];
    const known = new Set(calendars.map(item => item.uid));
    const all = [...calendars, ...selected.filter(uid => !known.has(uid)).map(uid => ({ uid, name: `${tr("Unavailable")}: ${uid}` }))];
    const fieldset = node("fieldset"); fieldset.append(node("legend", tr("Calendars (multiple selections allowed)")));
    fieldset.id = "macos-system-calendars";
    for (const source of all) {
      if (typeof source.uid !== "string" || typeof source.name !== "string") continue;
      const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.value = source.uid;
      checkbox.checked = selected.includes(source.uid); checkbox.dataset.calendarUid = source.uid;
      const label = node("label"); label.className = "hak";
      label.append(checkbox, document.createTextNode(` ${source.name}${source.readOnly ? " (read-only)" : ""}`));
      checkbox.addEventListener("change", () => {
        const values = [...fieldset.querySelectorAll("input:checked")].map(item => item.value);
        change({ kalenderUids: values });
      }); fieldset.append(label);
    }
    root.append(fieldset);
    const books = Array.isArray(snapshot?.adressbuecher) ? snapshot.adressbuecher : [];
    const book = node("select"); book.id = "macos-system-addressbook";
    const empty = node("option", tr("— do not link —")); empty.value = ""; book.append(empty);
    const options = [...books];
    if (chosen.adressbuchUid && !books.some(item => item.uid === chosen.adressbuchUid))
      options.push({ uid: chosen.adressbuchUid, name: `${tr("Unavailable")}: ${chosen.adressbuchUid}` });
    for (const source of options) {
      if (typeof source.uid !== "string" || typeof source.name !== "string") continue;
      const option = node("option", source.name); option.value = source.uid; book.append(option);
    }
    book.value = chosen.adressbuchUid || "";
    book.addEventListener("change", () => change({ adressbuchUid: book.value }));
    const label = node("label", tr("Address book") + " "); label.append(book); root.append(label);
    const syncSection = node("fieldset"); syncSection.id = "macos-system-sync";
    syncSection.append(node("legend", tr("macOS field synchronization")),
      node("p", tr("Only supported fields of linked entries are synchronized. New local entries, deletions, recurring events and unsupported fields are not sent. The first run is additive. This is not full Linux synchronization parity.")),
      node("p", tr("Apple APIs cannot atomically protect the comparison and save against another app. Conflicts or uncertain writes retain the journal and stop automatic repetition.")));
    const sources = [...calendars, ...books].filter(source => source.systemSyncFields === true &&
      typeof source.uid === "string" && ["events", "contacts", "reminders"].includes(source.art));
    if (!syncChoice || (!syncChoice.sourceUID && !syncChoice.explicit)) {
      const year = new Date().getFullYear();
      const initial = sources.find(source => selected.includes(source.uid) || chosen.adressbuchUid === source.uid) || sources[0];
      syncChoice = { sourceUID: initial?.uid || "", start: `${year}-01-01`, end: `${year + 1}-01-01` };
    }
    const sourceSelect = node("select"); sourceSelect.id = "macos-system-sync-source";
    const noSource = node("option", tr("Choose one macOS source")); noSource.value = ""; sourceSelect.append(noSource);
    for (const source of sources) { const option = node("option", `${tr(source.art === "events" ? "Calendars" : source.art === "contacts" ? "Contacts" : "Tasks")}: ${source.name}`); option.value = source.uid; sourceSelect.append(option); }
    sourceSelect.value = sources.some(source => source.uid === syncChoice.sourceUID) ? syncChoice.sourceUID : "";
    sourceSelect.disabled = !!pending || !!window.App?.macOSBetaSystemSyncBusy?.();
    sourceSelect.addEventListener("change", () => { syncChoice.sourceUID = sourceSelect.value; syncChoice.explicit = true; draw(); });
    const sourceLabel = node("label", tr("Source") + " "); sourceLabel.append(sourceSelect); syncSection.append(sourceLabel);
    const currentSource = sources.find(source => source.uid === sourceSelect.value);
    if (currentSource?.art === "events") {
      for (const [key, label] of [["start", "Window start (UTC)"], ["end", "Window end, exclusive (UTC)"]]) {
        const input = node("input"); input.type = "date"; input.id = "macos-system-sync-" + key; input.value = syncChoice[key];
        input.disabled = sourceSelect.disabled;
        input.addEventListener("change", () => { syncChoice[key] = input.value; });
        const row = node("label", tr(label) + " "); row.append(input); syncSection.append(row);
      }
    }
    const sync = node("button", tr("Synchronize now")); sync.id = "sync-jetzt"; sync.type = "button";
    sync.disabled = sourceSelect.disabled || !currentSource || snapshot?.systemAccountSyncImplemented !== true;
    sync.addEventListener("click", () => { const selection = syncSelection(); if (selection) window.App.macOSBetaStartSystemSync(selection); });
    const revoke = node("button", tr("Remove synchronization permission")); revoke.type = "button"; revoke.id = "macos-system-sync-revoke";
    revoke.disabled = sync.disabled;
    revoke.addEventListener("click", () => { const selection = syncSelection(); if (selection) window.App.macOSBetaStartSystemSync({ ...selection, action: "revoke" }); });
    syncSection.append(sync, revoke); root.append(syncSection);
  }
  function syncSelection() {
    if (!syncChoice || snapshot?.systemAccountSyncImplemented !== true) return null;
    const source = [...(snapshot.kalender || []), ...(snapshot.adressbuecher || [])].find(item =>
      item.uid === syncChoice.sourceUID && item.systemSyncFields === true);
    return source ? { sourceUID: source.uid, kind: source.art, start: syncChoice.start, end: syncChoice.end } : null;
  }
  function update(value) {
    if (!value || typeof value !== "object") return;
    // Correlated user requests cannot be completed by stale/native MCP replies.
    if (value.requestId && value.requestId !== pending) return;
    if (value.requestId) pending = null;
    snapshot = value;
    draw();
  }
  window.MacBetaSystemAccounts = Object.freeze({
    render(root, options) {
      view = { root, ...options };
      // A page rebuild does not cancel the OS consent dialog or forget its request.
      draw();
      if (!pending) request();
    }, update, syncSelection, refreshSyncControls: draw,
    reset() { view = null; snapshot = null; pending = null; syncChoice = null; }
  });
})();
