  // #770: native EventKit snapshots become deliberate local copies. Preparation
  // never changes DATEN; only the reviewed private proposal can cross the existing
  // recovery-checkpoint and durable-save fences. No source write/sync is implied.
  let macOSBetaCalendarProposal = null;
  const macOSBetaCalendarImportLimit = 16 * 1024 * 1024;
  function macOSBetaCalendarImportBlocked() {
    return (window.MacBeta.calendarImportBlocked?.() ?? window.MacBeta.noteImportBlocked()) ||
      gesperrt || !initialisiert || !antwortErhalten;
  }
  function macOSBetaCalendarImportExpired(proposal) {
    return Date.now() >= proposal.expires || performance.now() >= proposal.monotonicExpires;
  }
  function macOSBetaCalendarImportHasDraft() {
    return !!aenderungsGuard || editorIstGeaendert() || modalStapel.some(item => item.schleier.isConnected);
  }
  function macOSBetaCalendarImportHasSettingsDraft() {
    // These account fields are separate from DATEN and the active form editor.
    // A password-only edit does not set nextcloudEntwurfGeaendert.
    return !$("#einstellungen-schleier").classList.contains("verborgen") &&
      (nextcloudEntwurfGeaendert || !!$("#briefkasten-kennwort")?.value);
  }
  function macOSBetaStartCalendarImport() {
    if (macOSBetaCalendarImportBlocked()) return;
    if (macOSBetaCalendarProposal && macOSBetaCalendarProposal.state === "prepared" &&
        macOSBetaCalendarImportExpired(macOSBetaCalendarProposal)) macOSBetaCalendarProposal = null;
    if (macOSBetaCalendarProposal) { zettel("A calendar import is already being reviewed."); return; }
    if (macOSBetaCalendarImportHasSettingsDraft()) {
      zettel(_("Save or discard the account changes before importing.")); return;
    }
    navigiereMitGuard(() => nachDauerhaftemSpeichern(() => {
      if (macOSBetaCalendarImportBlocked()) return;
      const settings = $("#einstellungen-schleier");
      if (modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings)) {
        zettel("Finish or close the current editor before reviewing a calendar import."); return;
      }
      if (macOSBetaCalendarImportHasSettingsDraft()) {
        zettel(_("Save or discard the account changes before importing.")); return;
      }
      // #773: the System Sources button lives inside Settings. Close only this
      // parent modal after the save ACK so the native result can be reviewed.
      if (!settings.classList.contains("verborgen")) schliesseEinstellungen();
      if (!Bruecke.sende({ cmd: "macos_kalender_importieren" }))
        zettel("The macOS calendar import could not be opened.");
    }, error => zettel(error.message)));
  }
  function macOSBetaCalendarImportObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  function macOSBetaCalendarImportText(value, maximum, empty = true) {
    return typeof value === "string" && (empty || value.length > 0) &&
      value.length <= maximum && new TextEncoder().encode(value).length <= maximum;
  }
  function macOSBetaCalendarImportDigest(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  }
  function macOSBetaCalendarImportSourceUID(value) {
    if (!macOSBetaCalendarImportText(value, 4096, false) || !/^macos-events:[A-Za-z0-9+/]+={0,2}$/.test(value)) return false;
    try {
      const encoded = value.slice("macos-events:".length), bytes = atob(encoded);
      return bytes.length > 0 && btoa(bytes) === encoded &&
        new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(bytes, letter => letter.charCodeAt(0))).length > 0;
    } catch (_) { return false; }
  }
  function macOSBetaCalendarImportProvenance(record) {
    const meta = record?.nativeCalendarImport, native = record?.nativeSystemRecord;
    if (!macOSBetaCalendarImportObject(meta) || meta.version !== 1 ||
        !macOSBetaCalendarImportDigest(meta.identity) || !macOSBetaCalendarImportDigest(meta.revision) ||
        !macOSBetaCalendarImportSourceUID(meta.sourceUID) ||
        !macOSBetaCalendarImportText(meta.identifier, 16384, false) ||
        !macOSBetaCalendarImportText(meta.sourceTitle, 4096) ||
        !(meta.parentUID === null || macOSBetaCalendarImportText(meta.parentUID, 8192)) ||
        !macOSBetaCalendarImportObject(native) || native.kind !== "events" ||
        native.sourceUID !== meta.sourceUID || native.identifier !== meta.identifier || native.revision !== meta.revision ||
        native.revisionCoverage !== "serialized-fields-only" || !macOSBetaCalendarImportObject(native.fields) ||
        record.uid !== "mac-native-copy:" + meta.identity) throw new Error("Conflicting native calendar identity.");
    return { meta, key: JSON.stringify([meta.sourceUID, meta.identifier]) };
  }
  function macOSBetaCalendarImportIndex(book) {
    const byUID = new Map(), byIdentity = new Map(), bySource = new Map(), trashBySource = new Map();
    const add = (map, key, record) => {
      if (typeof key !== "string" || !key) return;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(record);
    };
    const sourceKey = record => {
      const meta = record?.nativeCalendarImport;
      return typeof meta?.sourceUID === "string" && typeof meta?.identifier === "string"
        ? JSON.stringify([meta.sourceUID, meta.identifier]) : "";
    };
    for (const record of book.termine) {
      add(byUID, record?.uid, record);
      add(byIdentity, record?.nativeCalendarImport?.identity, record);
      add(bySource, sourceKey(record), record);
    }
    for (const item of book.papierkorb || []) if (["appointment", "termin"].includes(item?.art))
      add(trashBySource, sourceKey(item.eintrag), item.eintrag);
    return { byUID, byIdentity, bySource, trashBySource };
  }
  function macOSBetaCalendarImportClassification(record, index) {
    const { meta, key } = macOSBetaCalendarImportProvenance(record);
    const found = [...new Set([...(index.byUID.get(record.uid) || []),
      ...(index.byIdentity.get(meta.identity) || []), ...(index.bySource.get(key) || [])])];
    if (found.length > 1) throw new Error("Multiple local records have the same native calendar identity.");
    if (found.length) {
      const previous = macOSBetaCalendarImportProvenance(found[0]);
      if (previous.key !== key || previous.meta.identity !== meta.identity || previous.meta.parentUID !== meta.parentUID)
        throw new Error("Conflicting native calendar identity.");
      // Local fields may have been edited. Neither equal nor changed source
      // revisions authorize overwriting the user's existing local copy.
      return previous.meta.revision === meta.revision ? "existing" : "changed";
    }
    if (index.trashBySource.has(key)) return "trash";
    return "new";
  }
  function macOSBetaPrepareCalendarImport(payload) {
    if (macOSBetaCalendarImportBlocked()) throw new Error("Calendar import is not available.");
    if (macOSBetaCalendarImportHasDraft()) throw new Error("Finish or close the current editor before reviewing a calendar import.");
    if (macOSBetaCalendarProposal && macOSBetaCalendarProposal.state === "prepared" &&
        macOSBetaCalendarImportExpired(macOSBetaCalendarProposal)) macOSBetaCalendarProposal = null;
    if (macOSBetaCalendarProposal) throw new Error("A calendar import is already being reviewed.");
    const text = JSON.stringify(payload);
    if (!text || text.length > macOSBetaCalendarImportLimit || new TextEncoder().encode(text).length > macOSBetaCalendarImportLimit)
      throw new Error("Native calendar import exceeds the byte limit.");
    const value = JSON.parse(text);
    if (!macOSBetaCalendarImportObject(value)) throw new Error("Invalid native calendar import proposal.");
    const source = value.source, scope = value.window;
    if (value.version !== 1 || !macOSBetaCalendarImportObject(source) ||
        !macOSBetaCalendarImportSourceUID(source.uid) || !macOSBetaCalendarImportText(source.title, 4096) ||
        !macOSBetaCalendarImportText(source.nativeType, 256, false) ||
        !["parentUID", "parentTitle", "parentType"].every(name => source[name] === null ||
          macOSBetaCalendarImportText(source[name], name === "parentUID" ? 8192 : name === "parentTitle" ? 4096 : 256)) ||
        !macOSBetaCalendarImportObject(scope) || !Number.isFinite(scope.start) || !Number.isFinite(scope.end) ||
        scope.end <= scope.start || scope.end - scope.start > 366 * 86400 ||
        !macOSBetaCalendarImportDigest(value.snapshotRevision) ||
        !Array.isArray(value.appointments) || !Array.isArray(value.excluded) ||
        value.appointments.length + value.excluded.length > 10000)
      throw new Error("Invalid native calendar import proposal.");
    const excluded = value.excluded.map(item => {
      if (!macOSBetaCalendarImportObject(item) || !macOSBetaCalendarImportText(item.title, 65536) ||
          !Array.isArray(item.reasons) || !item.reasons.length || item.reasons.length > 256 ||
          item.reasons.some(reason => !macOSBetaCalendarImportText(reason, 1024, false)))
        throw new Error("Invalid native calendar exclusion.");
      return { title: item.title, reasons: item.reasons.slice() };
    });
    const book = DATEN, content = JSON.stringify(book), displayZone = organizerZeitzone();
    const index = macOSBetaCalendarImportIndex(book), candidates = [], seen = new Set(), seenIdentity = new Set();
    let existingCount = 0, changedCount = 0;
    const changedPreview = [];
    const localIDs = new Set(book.termine.map(record => record.id));
    for (const draft of value.appointments) {
      const { meta, key } = macOSBetaCalendarImportProvenance(draft);
      if (meta.sourceUID !== source.uid || meta.sourceTitle !== source.title || meta.parentUID !== source.parentUID ||
          seen.has(key) || seenIdentity.has(meta.identity))
        throw new Error("Ambiguous native calendar import proposal.");
      seen.add(key); seenIdentity.add(meta.identity);
      const nativeFields = draft.nativeSystemRecord.fields;
      if (draft.sync !== false || draft.syncKalenderUid !== "" || draft.icsQuelleId !== "" ||
          !macOSBetaCalendarImportObject(draft.syncQuellen) || Object.keys(draft.syncQuellen).length ||
          !Array.isArray(draft.icsRoundtrip) || draft.icsRoundtrip.some(line => typeof line !== "string" || /[\r\n]/.test(line)) ||
          draft.icsRoundtrip.filter(line => /^DTSTART[;:]/i.test(line)).length !== 1 ||
          draft.icsRoundtrip.filter(line => /^DTEND[;:]/i.test(line)).length !== 1 ||
          draft.icsRoundtrip.some(line => /^(?:RRULE|RDATE|EXDATE|EXRULE|RECURRENCE-ID|ATTENDEE|ORGANIZER)[;:]|^BEGIN:VALARM$/i.test(line)) ||
          draft.wiederholung?.art !== "none" || draft.standardErinnerung !== false || draft.individuelleErinnerungTage !== 0 ||
          !Array.isArray(draft.alarme) || draft.alarme.length || draft.icsReadOnly === true || draft.icsKomplex === true ||
          ["icsAusnahmen", "icsZusatzDaten", "icsZusatzTermine", "icsRangeOverrides", "icsAusnahmeTermine", "teilnehmer", "kalenderAnhaenge"]
            .some(name => draft[name] !== undefined && (!Array.isArray(draft[name]) || draft[name].length)) ||
          !["titel", "notiz", "ort", "datum", "endDatum", "zeit", "endZeit", "icsAnzeigeZeitzone"].every(name => typeof draft[name] === "string") ||
          !draft.titel || typeof draft.nativeSourceReadOnly !== "boolean" ||
          nativeFields.title !== draft.titel || (nativeFields.notes ?? "") !== draft.notiz || (nativeFields.location ?? "") !== draft.ort ||
          !Number.isFinite(nativeFields.start) || !Number.isFinite(nativeFields.end) || nativeFields.end < nativeFields.start ||
          typeof nativeFields.allDay !== "boolean" || nativeFields.allDay !== !draft.zeit ||
          nativeFields.recurring !== false || nativeFields.isDetached !== false || nativeFields.attendeeCount !== 0 || nativeFields.hasOrganizer !== false ||
          !Array.isArray(nativeFields.recurrenceRules) || nativeFields.recurrenceRules.length || !Array.isArray(nativeFields.alarms) || nativeFields.alarms.length)
        throw new Error("Unsupported native calendar draft.");
      const classification = macOSBetaCalendarImportClassification(draft, index);
      if (classification === "existing") { existingCount++; continue; }
      if (classification === "changed") {
        changedCount++; changedPreview.push({ title: draft.titel, date: draft.datum, time: draft.zeit }); continue;
      }
      if (classification === "trash") {
        excluded.push({ title: draft.titel, reasons: ["local-calendar-copy-in-trash"] }); continue;
      }
      const candidate = { ...draft, id: uid() };
      if (localIDs.has(candidate.id)) throw new Error("Local appointment identity conflict.");
      localIDs.add(candidate.id);
      const normalized = normalisiereTermine([candidate], false);
      if (normalized.length !== 1 || normalized[0].id !== candidate.id ||
          Object.keys(candidate).some(name => name !== "wiederholung" &&
            kanonischerEntwurf(normalized[0][name]) !== kanonischerEntwurf(candidate[name])) ||
          Object.keys(candidate.wiederholung).some(name =>
            kanonischerEntwurf(normalized[0].wiederholung[name]) !== kanonischerEntwurf(candidate.wiederholung[name])) ||
          normalized[0].wiederholung.art !== "none") {
        excluded.push({ title: draft.titel, reasons: ["canonical-calendar-content-would-change"] }); continue;
      }
      candidates.push(normalized[0]);
    }
    if (DATEN !== book || JSON.stringify(book) !== content || organizerZeitzone() !== displayZone || macOSBetaCalendarImportBlocked())
      throw new Error("The document changed while preparing the calendar import.");
    const token = anrufClientRef(), proposal = {
      token, book, content, displayZone, candidates, source, scope, snapshotRevision: value.snapshotRevision,
      expires: Date.now() + 5 * 60000, monotonicExpires: performance.now() + 5 * 60000, state: "prepared"
    };
    macOSBetaCalendarProposal = proposal;
    // Return copies: the native review cannot mutate the private commit plan.
    return kopie({ ok: true, token, newCount: candidates.length, existingCount, changedCount, changedPreview, excluded,
      source, window: scope, snapshotRevision: value.snapshotRevision,
      preview: candidates.map(record => ({ title: record.titel, date: record.datum, time: record.zeit,
        endDate: record.endDatum, endTime: record.endZeit, allDay: !record.zeit, location: record.ort })) });
  }
  function macOSBetaCalendarImportRequireCurrent(proposal) {
    if (macOSBetaCalendarProposal !== proposal || macOSBetaCalendarImportBlocked() ||
        macOSBetaCalendarImportHasDraft() ||
        macOSBetaCalendarImportExpired(proposal) || DATEN !== proposal.book ||
        JSON.stringify(DATEN) !== proposal.content || organizerZeitzone() !== proposal.displayZone)
      throw new Error("The calendar import review is stale. Open it again.");
    const index = macOSBetaCalendarImportIndex(DATEN), ids = new Set(DATEN.termine.map(record => record.id));
    for (const candidate of proposal.candidates) {
      if (ids.has(candidate.id) || macOSBetaCalendarImportClassification(candidate, index) !== "new")
        throw new Error("The calendar import identity changed. Open it again.");
      ids.add(candidate.id);
    }
  }
  function macOSBetaCommitCalendarImport(token) {
    return new Promise((resolve, reject) => {
      const proposal = macOSBetaCalendarProposal;
      let ownsProposal = false, appended = false, saveConfirmed = false;
      const failed = (error, saveRejected = false) => {
        // #778: the renderer may fail after the local append and before the
        // save callback is registered. Report the mutation, never a rollback or
        // an unobserved write failure; a scheduled save may still be pending.
        if (appended && !saveConfirmed) {
          const prefix = saveRejected
            ? window.MacBeta.text("Imported appointments remain unsaved. Save the pending changes before importing again.")
            : window.MacBeta.text("Appointment copies were added, but saving was not confirmed. Check and save the pending changes before importing again.");
          const detail = String(error?.message || error);
          if (!detail.startsWith(prefix)) error = new Error(prefix + " " + detail);
        }
        if (ownsProposal && macOSBetaCalendarProposal === proposal) macOSBetaCalendarProposal = null;
        reject(error);
      };
      try {
        if (!proposal || proposal.token !== token || proposal.state !== "prepared")
          throw new Error("Invalid or already used calendar import review.");
        ownsProposal = true;
        macOSBetaCalendarImportRequireCurrent(proposal);
        if (!proposal.candidates.length) {
          macOSBetaCalendarProposal = null;
          resolve({ ok: true, count: 0, ids: [] }); return;
        }
        proposal.state = "checkpoint";
        mitMutationsSnapshot("pre-system-calendar-import", () => {
          try {
            macOSBetaCalendarImportRequireCurrent(proposal);
            proposal.state = "saving";
            proposal.book.termine.push(...proposal.candidates);
            appended = true;
            planeSpeichern();
            zeichneAlles();
            nachDauerhaftemSpeichern(() => {
              saveConfirmed = true;
              if (DATEN !== proposal.book || macOSBetaCalendarImportBlocked() ||
                  proposal.candidates.some(record => !DATEN.termine.includes(record))) {
                failed(new Error("The document changed before the calendar import save completed.")); return;
              }
              if (macOSBetaCalendarProposal === proposal) macOSBetaCalendarProposal = null;
              resolve({ ok: true, count: proposal.candidates.length, ids: proposal.candidates.map(record => record.id) });
            }, error => failed(error, true));
          } catch (error) { failed(error); }
        }, failed);
      } catch (error) { failed(error); }
    });
  }
  function macOSBetaCancelCalendarImport(token) {
    const proposal = macOSBetaCalendarProposal;
    if (!proposal || proposal.token !== token || proposal.state === "saving") return { ok: true, cancelled: false };
    macOSBetaCalendarProposal = null;
    return { ok: true, cancelled: true };
  }
