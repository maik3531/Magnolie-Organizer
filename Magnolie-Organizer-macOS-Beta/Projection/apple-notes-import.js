  // #772: explicit local plaintext copies from the native Apple Notes reader.
  // Source HTML is inert provenance, never the note's rendered content. Review
  // and append use the existing canonical constructors/checkpoint/save authority.
  let macOSBetaAppleNotesProposal = null;
  const macOSBetaAppleNotesPayloadLimit = 8 * 1024 * 1024;
  function macOSBetaAppleNotesBlocked() {
    return (window.MacBeta.appleNotesImportBlocked?.() ?? window.MacBeta.noteImportBlocked()) ||
      gesperrt || !initialisiert || !antwortErhalten;
  }
  function macOSBetaAppleNotesHasDraft() {
    return !!aenderungsGuard || editorIstGeaendert() || modalStapel.some(item => item.schleier.isConnected) ||
      !!ausstehenderNotizSnapshot || notizSnapshotTimer !== null;
  }
  function macOSBetaAppleNotesHasSettingsDraft() {
    // #774: account fields are separate from DATEN and the active form editor.
    // A password-only edit does not set nextcloudEntwurfGeaendert.
    return !$("#einstellungen-schleier").classList.contains("verborgen") &&
      (nextcloudEntwurfGeaendert || !!$("#briefkasten-kennwort")?.value);
  }
  function macOSBetaAppleNotesExpired(proposal) {
    return Date.now() >= proposal.expires || performance.now() >= proposal.monotonicExpires;
  }
  function macOSBetaAppleNotesDiscardObsoleteReview() {
    const proposal = macOSBetaAppleNotesProposal;
    // Native generation changes intentionally skip callbacks into the old book.
    // Only an idle review may be discarded here; an in-flight save/checkpoint
    // retains its own completion path and cannot be replaced by a new request.
    if (proposal?.state === "prepared" && (proposal.book !== DATEN || macOSBetaAppleNotesExpired(proposal)))
      macOSBetaAppleNotesProposal = null;
  }
  function macOSBetaStartAppleNotesImport() {
    if (macOSBetaAppleNotesBlocked()) return;
    macOSBetaAppleNotesDiscardObsoleteReview();
    if (macOSBetaAppleNotesProposal) { zettel("An Apple Notes copy is already being reviewed."); return; }
    if (macOSBetaAppleNotesHasSettingsDraft()) {
      zettel(_("Save or discard the account changes before importing.")); return;
    }
    navigiereMitGuard(() => nachDauerhaftemSpeichern(() => {
      if (macOSBetaAppleNotesBlocked()) return;
      const settings = $("#einstellungen-schleier");
      if (modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings)) {
        zettel("Finish or close the current editor before reviewing Apple Notes copies."); return;
      }
      if (macOSBetaAppleNotesHasSettingsDraft()) {
        zettel(_("Save or discard the account changes before importing.")); return;
      }
      // The System Sources button lives inside the Settings modal. Leave it via
      // the canonical close path before opening the native picker; otherwise
      // the later review would correctly refuse that still-open parent modal.
      if (!settings.classList.contains("verborgen")) schliesseEinstellungen();
      if (!Bruecke.sende({ cmd: "macos_apple_notizen_importieren" }))
        zettel("The Apple Notes copy dialog could not be opened.");
    }, error => zettel(error.message)));
  }
  function macOSBetaAppleNotesObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  function macOSBetaAppleNotesText(value, maximum, empty = true) {
    if (typeof value !== "string" || (!empty && !value.length) || value.length > maximum) return false;
    // for..of combines valid UTF-16 pairs. Lone surrogates would otherwise be
    // silently replaced by TextEncoder, losing the reviewed native content.
    for (const character of value) {
      const scalar = character.codePointAt(0);
      if (scalar >= 0xD800 && scalar <= 0xDFFF) return false;
    }
    return new TextEncoder().encode(value).length <= maximum;
  }
  function macOSBetaAppleNotesDigest(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  }
  function macOSBetaAppleNotesSource(source) {
    return macOSBetaAppleNotesObject(source) &&
      ["accountID", "folderID"].every(name => macOSBetaAppleNotesText(source[name], 16384, false)) &&
      ["accountTitle", "folderTitle"].every(name => macOSBetaAppleNotesText(source[name], 4096));
  }
  function macOSBetaAppleNotesNativeRecord(record) {
    return macOSBetaAppleNotesObject(record) && macOSBetaAppleNotesText(record.identifier, 16384, false) &&
      macOSBetaAppleNotesText(record.title, 4096) && record.passwordProtected === false && record.attachmentCount === 0 &&
      macOSBetaAppleNotesText(record.plaintext, 1024 * 1024) && macOSBetaAppleNotesText(record.bodyHTML, 1024 * 1024) &&
      Number.isFinite(record.modified) && record.failure === null;
  }
  function macOSBetaAppleNotesProvenance(note) {
    const meta = note?.nativeAppleNotesImport, native = note?.nativeAppleNotesRecord;
    if (!macOSBetaAppleNotesSource(meta) || meta.version !== 1 ||
        !macOSBetaAppleNotesDigest(meta.identity) || !macOSBetaAppleNotesDigest(meta.revision) ||
        !macOSBetaAppleNotesText(meta.identifier, 16384, false) ||
        meta.copyKind !== "plaintext" || meta.revisionCoverage !== "serialized-fields-only" ||
        !macOSBetaAppleNotesNativeRecord(native) || native.identifier !== meta.identifier)
      throw new Error("Conflicting Apple Notes copy identity.");
    return { meta, key: JSON.stringify([meta.accountID, meta.identifier]) };
  }
  function macOSBetaAppleNotesIndex(book) {
    const byIdentity = new Map(), bySource = new Map(), trashIdentity = new Map(), trashSource = new Map();
    const add = (map, key, note) => {
      if (typeof key !== "string" || !key) return;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(note);
    };
    const sourceKey = note => {
      const meta = note?.nativeAppleNotesImport;
      return typeof meta?.accountID === "string" && typeof meta?.identifier === "string"
        ? JSON.stringify([meta.accountID, meta.identifier]) : "";
    };
    for (const note of book.notizen) {
      add(byIdentity, note?.nativeAppleNotesImport?.identity, note); add(bySource, sourceKey(note), note);
    }
    for (const item of book.papierkorb || []) if (["note", "notiz"].includes(item?.art)) {
      add(trashIdentity, item.eintrag?.nativeAppleNotesImport?.identity, item.eintrag);
      add(trashSource, sourceKey(item.eintrag), item.eintrag);
    }
    return { byIdentity, bySource, trashIdentity, trashSource };
  }
  function macOSBetaAppleNotesClassification(note, index) {
    const { meta, key } = macOSBetaAppleNotesProvenance(note);
    const found = [...new Set([...(index.byIdentity.get(meta.identity) || []), ...(index.bySource.get(key) || [])])];
    if (found.length > 1) throw new Error("Multiple local notes have the same Apple Notes identity.");
    if (found.length) {
      const previous = macOSBetaAppleNotesProvenance(found[0]);
      if (previous.key !== key || previous.meta.identity !== meta.identity) throw new Error("Conflicting Apple Notes copy identity.");
      // Folder changes never produce a new local copy of the same account/note.
      // Local title, text and formatting edits remain entirely untouched.
      return ["revision", "folderID", "accountTitle", "folderTitle"].every(name => previous.meta[name] === meta[name])
        ? "existing" : "changed";
    }
    const trash = [...new Set([...(index.trashIdentity.get(meta.identity) || []), ...(index.trashSource.get(key) || [])])];
    for (const previous of trash) {
      const provenance = macOSBetaAppleNotesProvenance(previous);
      if (provenance.key !== key || provenance.meta.identity !== meta.identity) throw new Error("Conflicting Apple Notes copy identity.");
    }
    return trash.length ? "trash" : "new";
  }
  function macOSBetaAppleNotesTarget(book) {
    const selected = zustand.notizen.notizbuchId;
    const notebook = book.notizbuecher.find(item => item.id === selected) || book.notizbuecher[0];
    if (!notebook || typeof notebook.id !== "string" || !notebook.id || typeof notebook.name !== "string" ||
        book.notizbuecher.filter(item => item.id === notebook.id).length !== 1)
      throw new Error("Select an existing notebook before copying Apple Notes.");
    return { selected, notebook };
  }
  function macOSBetaPrepareAppleNotesImport(payload) {
    if (macOSBetaAppleNotesBlocked()) throw new Error("Apple Notes copying is not available.");
    if (macOSBetaAppleNotesHasDraft()) throw new Error("Finish or close the current editor before reviewing Apple Notes copies.");
    macOSBetaAppleNotesDiscardObsoleteReview();
    if (macOSBetaAppleNotesProposal) throw new Error("An Apple Notes copy is already being reviewed.");
    const text = JSON.stringify(payload);
    if (!text || text.length > macOSBetaAppleNotesPayloadLimit || new TextEncoder().encode(text).length > macOSBetaAppleNotesPayloadLimit)
      throw new Error("Apple Notes copy proposal exceeds the byte limit.");
    const value = JSON.parse(text);
    if (!macOSBetaAppleNotesObject(value) || value.version !== 1 || !macOSBetaAppleNotesSource(value.source) ||
        !macOSBetaAppleNotesDigest(value.snapshotRevision) || !Array.isArray(value.notes) || !Array.isArray(value.excluded) ||
        value.notes.length + value.excluded.length > 32) throw new Error("Invalid Apple Notes copy proposal.");
    const source = Object.fromEntries(["accountID", "accountTitle", "folderID", "folderTitle"].map(name => [name, value.source[name]]));
    const seen = new Set(), seenIdentities = new Set();
    const excluded = value.excluded.map(item => {
      if (!macOSBetaAppleNotesObject(item) || !macOSBetaAppleNotesText(item.identifier, 16384, false) ||
          !macOSBetaAppleNotesText(item.title, 4096) || !Array.isArray(item.reasons) ||
          !item.reasons.length || item.reasons.length > 256 || item.reasons.some(reason => !macOSBetaAppleNotesText(reason, 1024, false)) ||
          seen.has(item.identifier)) throw new Error("Invalid Apple Notes copy exclusion.");
      seen.add(item.identifier);
      return { identifier: item.identifier, title: item.title, reasons: item.reasons.slice() };
    });
    const book = DATEN, content = JSON.stringify(book), { selected, notebook } = macOSBetaAppleNotesTarget(book);
    const index = macOSBetaAppleNotesIndex(book), candidates = [], localIDs = new Set(book.notizen.map(note => note.id));
    const changedPreview = [];
    let existingCount = 0, changedCount = 0;
    for (const item of value.notes) {
      if (!macOSBetaAppleNotesObject(item) || !macOSBetaAppleNotesDigest(item.identity) || !macOSBetaAppleNotesDigest(item.revision) ||
          !macOSBetaAppleNotesText(item.identifier, 16384, false) || !macOSBetaAppleNotesText(item.title, 4096) ||
          !macOSBetaAppleNotesText(item.text, 1024 * 1024) || !macOSBetaAppleNotesNativeRecord(item.nativeRecord) ||
          item.identifier !== item.nativeRecord.identifier || item.title !== item.nativeRecord.title || item.text !== item.nativeRecord.plaintext ||
          seen.has(item.identifier) || seenIdentities.has(item.identity)) throw new Error("Invalid or ambiguous Apple Notes copy proposal.");
      seen.add(item.identifier); seenIdentities.add(item.identity);
      const provenance = { version: 1, identity: item.identity, ...source, identifier: item.identifier, revision: item.revision,
        copyKind: "plaintext", revisionCoverage: "serialized-fields-only" };
      const evidence = { nativeAppleNotesImport: provenance, nativeAppleNotesRecord: item.nativeRecord };
      const classification = macOSBetaAppleNotesClassification(evidence, index);
      if (classification === "existing") { existingCount++; continue; }
      if (classification === "changed") { changedCount++; changedPreview.push({ title: item.title }); continue; }
      if (classification === "trash") {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["local-apple-note-copy-in-trash"] }); continue;
      }
      const candidate = neueNotizDaten(item.title, notebook.id, "notiz", item.text);
      if (localIDs.has(candidate.id)) throw new Error("Local note identity conflict.");
      localIDs.add(candidate.id);
      Object.assign(candidate, evidence);
      const htmlState = {}, safeHTML = saeubereHtml(candidate.html, htmlState);
      if (htmlState.gekuerzt || safeHTML !== candidate.html) {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["canonical-note-content-would-change"] }); continue;
      }
      // Clone the notebook context; never pass the existing book or its domains
      // through normalization or mergeNotizen's content-based deduplication.
      const normalized = normalisiere({ notizen: [candidate], notizbuecher: kopie(book.notizbuecher), notizgruppen: kopie(book.notizgruppen) }).notizen;
      if (normalized.length !== 1 || Object.hasOwn(normalized[0], "uid") ||
          Object.keys(candidate).some(name => kanonischerEntwurf(normalized[0][name]) !== kanonischerEntwurf(candidate[name]))) {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["canonical-note-content-would-change"] }); continue;
      }
      candidates.push(normalized[0]);
    }
    if (DATEN !== book || JSON.stringify(book) !== content || macOSBetaAppleNotesBlocked() || macOSBetaAppleNotesHasDraft() ||
        zustand.notizen.notizbuchId !== selected || macOSBetaAppleNotesTarget(book).notebook !== notebook)
      throw new Error("The document or target notebook changed while preparing Apple Notes copies.");
    const token = anrufClientRef();
    macOSBetaAppleNotesProposal = { token, book, content, selected, notebook, candidates,
      expires: Date.now() + 5 * 60000, monotonicExpires: performance.now() + 5 * 60000, state: "prepared" };
    return kopie({ ok: true, token, source, snapshotRevision: value.snapshotRevision,
      newCount: candidates.length, existingCount, changedCount, changedPreview, excluded, notebookTitle: notebook.name,
      preview: candidates.map(note => ({ title: note.titel, text: note.text })) });
  }
  function macOSBetaAppleNotesRequireCurrent(proposal) {
    if (macOSBetaAppleNotesProposal !== proposal || macOSBetaAppleNotesBlocked() || macOSBetaAppleNotesHasDraft() ||
        macOSBetaAppleNotesExpired(proposal) || DATEN !== proposal.book || JSON.stringify(DATEN) !== proposal.content ||
        zustand.notizen.notizbuchId !== proposal.selected || macOSBetaAppleNotesTarget(DATEN).notebook !== proposal.notebook)
      throw new Error("The Apple Notes copy review is stale. Open it again.");
    const index = macOSBetaAppleNotesIndex(DATEN), ids = new Set(DATEN.notizen.map(note => note.id));
    for (const candidate of proposal.candidates) {
      if (ids.has(candidate.id) || macOSBetaAppleNotesClassification(candidate, index) !== "new")
        throw new Error("The Apple Notes copy identity changed. Open it again.");
      ids.add(candidate.id);
    }
  }
  function macOSBetaCommitAppleNotesImport(token) {
    return new Promise((resolve, reject) => {
      const proposal = macOSBetaAppleNotesProposal;
      let ownsProposal = false;
      const failed = error => {
        if (ownsProposal && macOSBetaAppleNotesProposal === proposal) macOSBetaAppleNotesProposal = null;
        reject(error);
      };
      try {
        if (!proposal || proposal.token !== token || proposal.state !== "prepared")
          throw new Error("Invalid or already used Apple Notes copy review.");
        ownsProposal = true;
        macOSBetaAppleNotesRequireCurrent(proposal);
        if (!proposal.candidates.length) {
          macOSBetaAppleNotesProposal = null; resolve({ ok: true, count: 0, ids: [] }); return;
        }
        proposal.state = "checkpoint";
        mitMutationsSnapshot("pre-apple-notes-copy", () => {
          try {
            macOSBetaAppleNotesRequireCurrent(proposal);
            proposal.state = "saving";
            proposal.book.notizen.push(...proposal.candidates);
            planeSpeichern(); zeichneAlles();
            nachDauerhaftemSpeichern(() => {
              if (DATEN !== proposal.book || macOSBetaAppleNotesBlocked() ||
                  proposal.candidates.some(note => !DATEN.notizen.includes(note))) {
                failed(new Error("The document changed before the Apple Notes copy save completed.")); return;
              }
              if (macOSBetaAppleNotesProposal === proposal) macOSBetaAppleNotesProposal = null;
              resolve({ ok: true, count: proposal.candidates.length, ids: proposal.candidates.map(note => note.id) });
            }, error => failed(new Error("Imported notes remain unsaved. Save the pending changes before importing again. " + error.message)));
          } catch (error) { failed(error); }
        }, failed);
      } catch (error) { failed(error); }
    });
  }
  function macOSBetaCancelAppleNotesImport(token) {
    const proposal = macOSBetaAppleNotesProposal;
    if (!proposal || proposal.token !== token || proposal.state === "saving") return { ok: true, cancelled: false };
    macOSBetaAppleNotesProposal = null;
    return { ok: true, cancelled: true };
  }
