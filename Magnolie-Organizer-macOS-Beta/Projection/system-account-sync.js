  // #786: a native-granted field synchronization, separate from local copy imports.
  // Native authority, baseline and journal never come from this JavaScript object.
  let macOSBetaSystemSync = null;
  const macOSBetaSyncText = text => window.MacBeta.text(text);
  function macOSBetaSyncCanonical(value) {
    if (Array.isArray(value)) return "[" + value.map(macOSBetaSyncCanonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).filter(key =>
      value[key] !== undefined && typeof value[key] !== "function" && typeof value[key] !== "symbol").sort().map(key =>
      JSON.stringify(key) + ":" + macOSBetaSyncCanonical(value[key])).join(",") + "}";
    return JSON.stringify(value) ?? "null";
  }
  function macOSBetaSyncSettingsDraft() {
    return nextcloudEntwurfGeaendert || !!$("#briefkasten-kennwort")?.value;
  }
  function macOSBetaSyncHasDraft() {
    const settings = $("#einstellungen-schleier");
    return !!aenderungsGuard || editorIstGeaendert() ||
      modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings) ||
      !!ausstehenderNotizSnapshot || notizSnapshotTimer !== null || macOSBetaSyncSettingsDraft();
  }
  function macOSBetaSyncAvailable() {
    return initialisiert && antwortErhalten && !gesperrt && !window.MacBeta.systemSyncBlocked();
  }
  function macOSBetaStartSystemSync(selection) {
    if (macOSBetaSystemSync || !macOSBetaSyncAvailable()) return false;
    if (!selection || typeof selection.sourceUID !== "string" || !selection.sourceUID ||
        !["events", "contacts", "reminders"].includes(selection.kind) ||
        !selection.sourceUID.startsWith("macos-" + selection.kind + ":")) return false;
    if (macOSBetaSyncSettingsDraft()) {
      zettel(macOSBetaSyncText("Save or discard the account changes before synchronizing.")); return false;
    }
    const operation = { requestId: uid(), book: DATEN, phase: "preparing" };
    macOSBetaSystemSync = operation;
    const fail = error => macOSBetaSystemSyncFinished({ requestId: operation.requestId, ok: false,
      fehler: String(error?.message || error || macOSBetaSyncText("System synchronization could not start.")) });
    let admitted = false;
    try {
      navigiereMitGuard(() => { admitted = true; }).then(() => {
        if (!admitted) { macOSBetaSystemSync = null; window.MacBetaSystemAccounts?.refreshSyncControls(); return; }
        if (DATEN !== operation.book || !macOSBetaSyncAvailable()) throw new Error(macOSBetaSyncText("The current book changed; synchronization was not started."));
        nachDauerhaftemSpeichern(() => {
          try {
            if (DATEN !== operation.book || !macOSBetaSyncAvailable() || macOSBetaSyncHasDraft())
              throw new Error(macOSBetaSyncText("Finish or close the current editor before synchronizing."));
            const settings = $("#einstellungen-schleier");
            if (!settings.classList.contains("verborgen")) schliesseEinstellungen();
            operation.content = macOSBetaSyncCanonical(DATEN);
            operation.epoch = DATEN.syncEpoch;
            operation.timeZone = organizerZeitzone();
            operation.phase = "requested";
            window.MacBeta.systemSyncLock(true);
            const message = { cmd: "macos_system_sync", requestId: operation.requestId,
              sourceUID: selection.sourceUID, kind: selection.kind, action: selection.action === "revoke" ? "revoke" : "run",
              start: selection.kind === "events" ? String(selection.start || "") : "",
              end: selection.kind === "events" ? String(selection.end || "") : "", timeZone: operation.timeZone };
            if (!Bruecke.sende(message)) throw new Error(macOSBetaSyncText("System synchronization could not start."));
          } catch (error) { fail(error); }
        }, fail);
      }).catch(fail);
    } catch (error) { fail(error); }
    window.MacBetaSystemAccounts?.refreshSyncControls();
    return true;
  }
  function macOSBetaStartSelectedSystemSync(stumm = false) {
    // Scheduled desktop/DAV/phone paths are not implicitly native Apple grants.
    if (stumm) return;
    const selection = window.MacBetaSystemAccounts?.syncSelection();
    if (!selection) { zettel(macOSBetaSyncText("Choose one macOS source in System internet accounts.")); return; }
    macOSBetaStartSystemSync(selection);
  }
  function macOSBetaSyncCurrent(requestId, unchanged = true) {
    const current = macOSBetaSystemSync;
    if (!current || current.requestId !== requestId || !["requested", "prepared", "saving", "saved"].includes(current.phase) ||
        !macOSBetaSyncAvailable() || DATEN !== current.book || DATEN.syncEpoch !== current.epoch ||
        organizerZeitzone() !== current.timeZone || macOSBetaSyncHasDraft() ||
        (unchanged && macOSBetaSyncCanonical(DATEN) !== current.content))
      throw new Error(macOSBetaSyncText("The current book changed; the synchronization journal was retained."));
    return current;
  }
  function macOSBetaAdmitSystemSync(requestId, inputText) {
    const current = macOSBetaSyncCurrent(requestId);
    if (typeof inputText !== "string" || new TextEncoder().encode(inputText).length > 64 * 1024 * 1024 ||
        macOSBetaSyncCanonical(JSON.parse(inputText)) !== current.content)
      throw new Error(macOSBetaSyncText("The saved book does not match the current synchronization request."));
    return { ok: true, requestId, epoch: current.epoch };
  }
  function macOSBetaPrepareSystemSync(requestId, runID, candidateText) {
    const current = macOSBetaSyncCurrent(requestId);
    if (!["requested", "prepared"].includes(current.phase) || (current.runID && current.runID !== runID) || typeof runID !== "string" || !runID ||
        typeof candidateText !== "string" || new TextEncoder().encode(candidateText).length > 64 * 1024 * 1024)
      throw new Error(macOSBetaSyncText("Invalid system synchronization candidate."));
    const raw = JSON.parse(candidateText);
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || raw.syncEpoch !== current.epoch ||
        !["termine", "aufgaben", "kontakte", "notizen"].every(key => Array.isArray(raw[key])))
      throw new Error(macOSBetaSyncText("Invalid system synchronization candidate."));
    // Probe a detached copy with its relationship context. Only new/changed
    // rows may use the result; untouched rows and other domains remain exact.
    // Applying the whole normalized book would renumber unrelated task roots.
    const normalized = kopie(raw), probed = normalisiere(kopie(raw));
    for (const key of ["termine", "kontakte", "aufgaben"]) {
      const existing = new Map(DATEN[key].map(row => [row.id, row]));
      normalized[key] = raw[key].map(row => {
        const old = existing.get(row.id);
        if (old && macOSBetaSyncCanonical(old) === macOSBetaSyncCanonical(row)) return kopie(row);
        const matches = probed[key].filter(item => item.id === row.id);
        if (matches.length !== 1)
          throw new Error(macOSBetaSyncText("Invalid system synchronization candidate."));
        const value = matches[0];
        if (key === "aufgaben" && Number.isSafeInteger(row.reihenfolge)) value.reihenfolge = row.reihenfolge;
        return window.MacBeta.preserve(row, value);
      });
    }
    macOSBetaSyncCurrent(requestId);
    const text = JSON.stringify(normalized);
    current.prepared = normalized; current.preparedText = text; current.runID = runID; current.phase = "prepared";
    return { ok: true, requestId, runID, text };
  }
  async function macOSBetaCommitSystemSync(requestId, runID, candidateText) {
    const current = macOSBetaSyncCurrent(requestId);
    if (current.phase !== "prepared" || current.runID !== runID || typeof candidateText !== "string" ||
        macOSBetaSyncCanonical(JSON.parse(candidateText)) !== macOSBetaSyncCanonical(JSON.parse(current.preparedText)))
      throw new Error(macOSBetaSyncText("Stale system synchronization candidate."));
    DATEN = current.prepared; current.book = DATEN; current.content = macOSBetaSyncCanonical(DATEN); current.phase = "saving";
    let renderingFailed = false;
    // Register persistence before rendering: renderer failure must never turn an
    // already applied candidate into a fictional rollback or a success without ACK.
    const saved = new Promise((resolve, reject) => {
      nachDauerhaftemSpeichern(() => {
        try {
          macOSBetaSyncCurrent(requestId);
          current.phase = "saved"; resolve(true);
        } catch (error) { reject(error); }
      }, error => reject(new Error(macOSBetaSyncText("Synchronization changes are in the current book but saving was not confirmed. Retry saving; the native journal is retained.") + " " + error.message)));
    });
    try { terminIndexVeraltet = true; jahrestagIndexVeraltet = true; zeichneAlles(); }
    catch (_) { renderingFailed = true; }
    await saved;
    return { ok: true, requestId, runID, text: JSON.stringify(DATEN), renderingFailed };
  }
  function macOSBetaSystemSyncFinished(value) {
    const current = macOSBetaSystemSync;
    if (!current || !value || value.requestId !== current.requestId) return;
    const sameBook = DATEN === current.book;
    macOSBetaSystemSync = null;
    window.MacBeta.systemSyncLock(false);
    window.MacBetaSystemAccounts?.refreshSyncControls();
    if (sameBook) {
      const message = value.ok === true
      ? macOSBetaSyncText(value.revoked === true ? "System synchronization permission removed." : "System synchronization was saved and verified.") +
        (value.bericht ? " " + value.bericht : "")
      : String(value.fehler || macOSBetaSyncText("System synchronization was not completed. Pending evidence was retained."));
      window.MacBeta.systemSyncNotice(message); zettel(message);
    }
  }
  function macOSBetaSystemSyncBusy() { return macOSBetaSystemSync !== null; }
