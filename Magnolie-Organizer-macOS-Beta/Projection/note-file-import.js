  // Port glue around canonical note constructors, normalizer and save authority.
  function macOSBetaStartNoteImport() {
    if (gesperrt) return;
    navigiereMitGuard(() => nachDauerhaftemSpeichern(() => Bruecke.sende({ cmd: "notiz_dateien_importieren" })));
  }
  function macOSBetaImportNoteFiles(payload) {
    return new Promise((resolve, reject) => {
      try {
        if (window.MacBeta.noteImportBlocked() || gesperrt || !initialisiert || !antwortErhalten || !Array.isArray(payload?.items) ||
            !payload.items.length || payload.items.length > 32) throw new Error("Note import is not available.");
        const book = DATEN, notebook = book.notizbuecher.find(item => item.id === zustand.notizen.notizbuchId) || book.notizbuecher[0];
        if (!notebook) throw new Error("Select an existing notebook.");
        let totalBytes = 0;
        const candidates = payload.items.map(item => {
          const value = item.fields;
          if (!/^[a-f0-9]{64}$/.test(item.sourceSHA256 || "") || typeof item.sourceName !== "string" ||
              !Number.isSafeInteger(item.sourceBytes) || item.sourceBytes <= 0 || item.sourceBytes > 8 * 1024 * 1024 ||
              !value || Object.keys(value).sort().join(",") !== "anhaenge,text,titel" ||
              typeof value.titel !== "string" || typeof value.text !== "string" || !Array.isArray(value.anhaenge)) {
            throw new Error("Invalid selected note-file proposal.");
          }
          totalBytes += item.sourceBytes;
          if (totalBytes > 8 * 1024 * 1024) throw new Error("Note file batch is too large.");
          const note = neueNotizDaten(value.titel, notebook.id, "notiz", value.text);
          const htmlState = {};
          const safeHTML = saeubereHtml(note.html, htmlState);
          if (htmlState.gekuerzt || safeHTML !== note.html) throw new Error("Literal text exceeds the safe rendered-note limit; selection was not imported.");
          note.anhaenge = saubereNotizAnhaenge(value.anhaenge);
          if (kanonischerEntwurf(note.anhaenge) !== kanonischerEntwurf(value.anhaenge)) throw new Error("Attachment cannot be preserved.");
          return note;
        });
        // Normalize only new records. Existing notes and extension fields are never
        // passed through normalization or mergeNotizen's title/text deduplication.
        const normalized = normalisiere({ notizen: candidates, notizbuecher: kopie(book.notizbuecher), notizgruppen: kopie(book.notizgruppen) }).notizen;
        if (normalized.length !== candidates.length || normalized.some((note, i) =>
            note.id !== candidates[i].id || note.text !== candidates[i].text || note.titel !== candidates[i].titel ||
            kanonischerEntwurf(note.anhaenge) !== kanonischerEntwurf(candidates[i].anhaenge))) throw new Error("Note import would lose content.");
        mitMutationsSnapshot("pre-note-file-import", () => {
          if (DATEN !== book || gesperrt || window.MacBeta.noteImportBlocked()) { reject(new Error("The document changed.")); return; }
          const ids = new Set(book.notizen.map(note => note.id));
          for (const note of normalized) {
            if (ids.has(note.id)) { reject(new Error("Note identity conflict.")); return; }
            ids.add(note.id);
          }
          book.notizen.push(...normalized);
          zeichneAlles();
          nachDauerhaftemSpeichern(() => resolve({ ok: true, count: normalized.length, ids: normalized.map(note => note.id) }),
            error => reject(new Error("Imported notes remain unsaved. Save the pending changes before importing again. " + error.message)));
        }, reject);
      } catch (error) { reject(error); }
    });
  }
