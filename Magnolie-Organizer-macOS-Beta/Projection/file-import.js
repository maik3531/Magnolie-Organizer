  // #785: the existing parser/merge rules still own format semantics. This
  // native bridge binds the source result to a book and waits for durable save.
  let macOSBetaFileImport = null;
  function macOSBetaFileImportSave() {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true; clearTimeout(timer);
        if (error) reject(error); else resolve();
      };
      const timer = setTimeout(() => finish(new Error(window.MacBeta.text("Saving the import was not confirmed."))), 30000);
      try { nachDauerhaftemSpeichern(() => finish(), error => finish(error || new Error("Save rejected"))); }
      catch (error) { finish(error); }
    });
  }
  async function macOSBetaPrepareFileImport(format) {
    if (macOSBetaFileImport && macOSBetaFileImport.book !== DATEN) macOSBetaFileImport = null;
    if (macOSBetaFileImport || !["ics", "lotus", "vcf", "claws", "ldif", "muell"].includes(format) ||
        gesperrt || !initialisiert || !antwortErhalten || window.MacBeta.calendarImportBlocked())
      throw new Error(window.MacBeta.text("File import is not available right now."));
    const pending = { book: DATEN, format, token: uid(), notice: "" };
    macOSBetaFileImport = pending;
    try {
      if (macOSBetaCalendarImportHasSettingsDraft()) throw new Error(window.MacBeta.text("Save or discard the account changes before importing."));
      let admitted = false;
      await navigiereMitGuard(() => { admitted = true; });
      if (!admitted) { macOSBetaFileImport = null; if (format === "muell") muellImportLauf = null; return { cancelled: true }; }
      await macOSBetaFileImportSave();
      if (DATEN !== pending.book || gesperrt || window.MacBeta.calendarImportBlocked()) throw new Error(_("Conflict"));
      const settings = $("#einstellungen-schleier");
      if (modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings))
        throw new Error(window.MacBeta.text("Finish or close the current editor before importing."));
      if (macOSBetaCalendarImportHasSettingsDraft()) throw new Error(window.MacBeta.text("Save or discard the account changes before importing."));
      if (settings && !settings.classList.contains("verborgen")) schliesseEinstellungen();
      await new Promise((resolve, reject) => mitMutationsSnapshot("pre-file-import", resolve, reject));
      if (DATEN !== pending.book || gesperrt || window.MacBeta.calendarImportBlocked()) throw new Error(_("Conflict"));
      pending.before = JSON.stringify(DATEN);
      pending.expires = Date.now() + 5 * 60 * 1000;
      return { token: pending.token };
    } catch (error) {
      if (macOSBetaFileImport === pending) macOSBetaFileImport = null;
      if (format === "muell") muellImportLauf = null;
      throw error;
    }
  }
  function macOSBetaFileImportNotice(text) {
    if (macOSBetaFileImport?.committing) macOSBetaFileImport.notice = text;
    else zettel(text);
  }
  function macOSBetaFileImportFailure(payload) {
    if (macOSBetaFileImport?.committing && payload?.fehler) throw new Error(String(payload.fehler));
  }
  async function macOSBetaCommitFileImport(payload, token) {
    const operation = macOSBetaFileImport;
    if (!operation || operation.token !== token || operation.committing || operation.expires < Date.now() ||
        DATEN !== operation.book || gesperrt || !initialisiert || window.MacBeta.calendarImportBlocked() ||
        JSON.stringify(DATEN) !== operation.before) throw new Error(_("Conflict"));
    operation.committing = true;
    let saved = false;
    try {
      if (operation.format === "muell") {
        // The existing waste preview has its own token, model-drift and save
        // guards. Opening it is not a durable import receipt.
        App.importErgebnis(payload);
        return { ok: true, handedToPreview: true, saveConfirmed: false };
      }
      await App.macOSBetaNativeCalendarResult(payload);
      if (DATEN !== operation.book || gesperrt || window.MacBeta.calendarImportBlocked()) throw new Error(_("Conflict"));
      const changed = JSON.stringify(DATEN) !== operation.before;
      if (changed) await macOSBetaFileImportSave();
      saved = true;
      if (DATEN !== operation.book || gesperrt || window.MacBeta.calendarImportBlocked()) throw new Error(_("Conflict"));
      if (operation.notice) zettel(operation.notice);
      return { ok: true, changed, saveConfirmed: changed };
    } catch (error) {
      if (!saved && DATEN === operation.book && JSON.stringify(DATEN) !== operation.before)
        throw new Error(window.MacBeta.text("Imported data is present, but saving was not confirmed. Save the pending changes before importing again.") + " " + String(error?.message || error));
      throw error;
    } finally {
      if (macOSBetaFileImport === operation) macOSBetaFileImport = null;
    }
  }
  function macOSBetaCancelFileImport(token) {
    if (macOSBetaFileImport?.token === token && !macOSBetaFileImport.committing) macOSBetaFileImport = null;
    // The canonical waste operation must be released on picker cancellation.
    if (muellImportLauf && !macOSBetaFileImport) muellImportLauf = null;
    return { ok: true };
  }
