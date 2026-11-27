  // #784: use existing Mac import paths, without starting desktop device services.
  let macOSBetaDevicePending = null;
  function macOSBetaDeviceImport(start, file = false) {
    if (macOSBetaDevicePending || macOSBetaCalendarImportBlocked()) return;
    if (macOSBetaCalendarImportHasSettingsDraft()) {
      zettel(window.MacBeta.text("Save or discard the account changes before importing.")); return;
    }
    const operation = { book: DATEN };
    macOSBetaDevicePending = operation;
    const controls = () => document.querySelectorAll("#einst-seite-baum [data-macos-device-import]");
    for (const item of controls()) item.disabled = true;
    const finish = () => {
      if (macOSBetaDevicePending !== operation) return;
      macOSBetaDevicePending = null;
      for (const item of controls()) item.disabled = macOSBetaCalendarImportBlocked();
    };
    const failed = error => { finish(); zettel(String(error?.message || error)); };
    let admitted = false;
    try {
      // Finish the navigation guard before invoking an existing starter, which
      // has its own guard. Otherwise a synchronous discard can swallow it.
      navigiereMitGuard(() => { admitted = true; }).then(() => {
        if (!admitted || DATEN !== operation.book || macOSBetaCalendarImportBlocked()) { finish(); return; }
        nachDauerhaftemSpeichern(() => {
          try {
            if (DATEN !== operation.book || macOSBetaCalendarImportBlocked()) return;
            const settings = $("#einstellungen-schleier");
            if (modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings)) {
              zettel(window.MacBeta.text("Finish or close the current editor before importing.")); return;
            }
            if (macOSBetaCalendarImportHasSettingsDraft()) {
              zettel(window.MacBeta.text("Save or discard the account changes before importing.")); return;
            }
            if (file && !settings.classList.contains("verborgen")) schliesseEinstellungen();
            start();
          } finally { finish(); }
        }, failed);
      }).catch(failed);
    } catch (error) { failed(error); }
  }

  function macOSBetaDeviceImportPage(root) {
    const tr = text => window.MacBeta.text(text);
    const button = (id, label, action, file = false) => {
      const item = knopf(tr(label), "", () => macOSBetaDeviceImport(action, file));
      item.id = id;
      item.dataset.macosDeviceImport = "true";
      item.disabled = !!macOSBetaDevicePending || macOSBetaCalendarImportBlocked();
      return item;
    };
    const files = abschnitt(tr("Files from your devices"),
      tr("Save files received with KDE Connect or AirDrop on this Mac, then select them here."));
    const fileActions = el("div", "knopfreihe");
    fileActions.append(
      button("macos-device-note-files", "Import note files…", macOSBetaStartNoteImport, true),
      button("macos-device-calendar-file", "Import calendar file (.ics)…", () => starteImport("ics"), true));
    files.append(fileActions,
      el("p", "einst-hinweis", tr("TXT and Markdown become text notes. PDF and JPEG/PNG/GIF/WebP files remain attachments. Calendar files use the ICS import.")),
      el("p", "einst-hinweis", tr("Use KDE Connect in its own app for supported transfers. Direct phone control, pairing and synchronization from Magnolie are not available in this macOS version.")));
    const copies = abschnitt(tr("Local copies from macOS apps"),
      tr("Choose items from Calendar, Contacts, Reminders or Apple Notes. Review the local copies before saving. Changes in Magnolie do not synchronize back."));
    const copyActions = el("div", "knopfreihe");
    copyActions.append(
      button("macos-device-calendar-copy", "Import macOS calendar appointments", macOSBetaStartCalendarImport),
      button("macos-device-contact-copy", "Copy macOS contacts", macOSBetaStartContactImport),
      button("macos-device-reminder-copy", "Copy macOS reminders", macOSBetaStartReminderImport),
      button("macos-device-apple-notes-copy", "Text copies from Apple Notes", macOSBetaStartAppleNotesImport));
    copies.append(copyActions);
    root.append(files, copies,
      el("p", "einst-hinweis", tr("Magnolia tree sharing is not available in this macOS version.")));
  }
