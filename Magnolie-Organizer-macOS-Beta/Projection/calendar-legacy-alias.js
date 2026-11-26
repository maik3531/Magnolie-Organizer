  // #465: consume the native reader's exact, transient legacy-hash evidence.
  // Selection, ambiguity checks and mutation remain in the shared desktop
  // alias planner/merge. A book field is never sufficient to register evidence.
  const macOSBetaNativeCalendarEvidence = new WeakMap();
  function macOSBetaCalendarAliasIdentities(rows) {
    const sourceUIDs = new Set(), occurrences = new Set();
    return JSON.stringify(rows.map(row => {
      if (!row || typeof row !== "object" || typeof row.uid !== "string" ||
          !Array.isArray(row.icsRoundtrip) || row.icsRoundtrip.some(line => typeof line !== "string"))
        throw alterAndroidTerminKonflikt();
      const sourceUID = JSON.stringify([row.icsQuelleId || "", row.uid]);
      const identity = alteAndroidTerminIdentitaet(row);
      if (sourceUIDs.has(sourceUID) || (identity && occurrences.has(identity.key))) throw alterAndroidTerminKonflikt();
      sourceUIDs.add(sourceUID); if (identity) occurrences.add(identity.key);
      return [row.uid, row.icsQuelleId || "", row.icsSerienUid || "",
        row.icsRoundtrip.filter(line => /^RECURRENCE-ID[;:]/i.test(line))];
    }));
  }
  function macOSBetaRegisterCalendarAliases(payload) {
    const proof = payload.legacyAndroidAliases, rows = payload.termine, metadata = payload.icsImportMetadata;
    const object = value => value && typeof value === "object" && !Array.isArray(value);
    const exactKeys = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
    if (!exactKeys(proof, ["version", "algorithm", "sourceSHA256", "appointmentCount", "entries"]) ||
        proof.version !== 1 || proof.algorithm !== "android-jsonobject-quote-v1" ||
        typeof proof.sourceSHA256 !== "string" || !/^[a-f0-9]{64}$/.test(proof.sourceSHA256) ||
        !object(metadata) || metadata.version !== 1 || metadata.sourceSHA256 !== proof.sourceSHA256 ||
        !Array.isArray(rows) || rows.length > 50000 || proof.appointmentCount !== rows.length ||
        !Array.isArray(proof.entries) || !proof.entries.length || proof.entries.length > rows.length ||
        new TextEncoder().encode(JSON.stringify(payload)).length > 96 * 1024 * 1024)
      throw alterAndroidTerminKonflikt();
    const entries = new Map(), indexes = new Set(), identities = new Set();
    for (const entry of proof.entries) {
      if (!exactKeys(entry, ["appointmentIndex", "canonicalUID", "legacyUID", "sourceID", "wireUID", "recurrenceLine"]) ||
          !Number.isInteger(entry.appointmentIndex) || entry.appointmentIndex < 0 || entry.appointmentIndex >= rows.length ||
          indexes.has(entry.appointmentIndex) ||
          ["canonicalUID", "legacyUID", "sourceID", "wireUID", "recurrenceLine"].some(key => typeof entry[key] !== "string" || !entry[key]))
        throw alterAndroidTerminKonflikt();
      const row = rows[entry.appointmentIndex], identity = alteAndroidTerminIdentitaet(row);
      if (!identity || row.uid !== entry.canonicalUID || row.icsQuelleId !== entry.sourceID ||
          row.icsSerienUid !== entry.wireUID ||
          identity.key !== JSON.stringify([entry.sourceID, entry.wireUID, entry.recurrenceLine]) ||
          entry.canonicalUID === entry.legacyUID ||
          !entry.canonicalUID.startsWith(entry.wireUID + "-magnolie-instanz-") ||
          !entry.legacyUID.startsWith(entry.wireUID + "-magnolie-instanz-") ||
          !/-magnolie-instanz-[a-f0-9]{16}$/.test(entry.canonicalUID) ||
          !/-magnolie-instanz-[a-f0-9]{16}$/.test(entry.legacyUID) || identities.has(identity.key))
        throw alterAndroidTerminKonflikt();
      indexes.add(entry.appointmentIndex); identities.add(identity.key);
      entries.set(JSON.stringify([identity.key, entry.canonicalUID]), entry.legacyUID);
    }
    macOSBetaNativeCalendarEvidence.set(proof, { book: DATEN, before: JSON.stringify(DATEN),
      proof: JSON.stringify(proof), metadata: JSON.stringify(metadata), count: rows.length,
      identities: macOSBetaCalendarAliasIdentities(rows), entries });
  }
  function macOSBetaNativeCalendarAliases(payload) {
    if (!Object.hasOwn(payload, "legacyAndroidAliases")) return null;
    const proof = macOSBetaNativeCalendarEvidence.get(payload.legacyAndroidAliases);
    if (!proof || DATEN !== proof.book || gesperrt || !initialisiert ||
        window.MacBeta.calendarImportBlocked() || JSON.stringify(DATEN) !== proof.before ||
        JSON.stringify(payload.legacyAndroidAliases) !== proof.proof ||
        JSON.stringify(payload.icsImportMetadata) !== proof.metadata ||
        !Array.isArray(payload.termine) || payload.termine.length !== proof.count ||
        macOSBetaCalendarAliasIdentities(payload.termine) !== proof.identities)
      throw alterAndroidTerminKonflikt();
    return proof.entries;
  }
  function macOSBetaNativeCalendarResult(payload) {
    if (!payload || payload.fehler || payload.abgebrochen || !Object.hasOwn(payload, "legacyAndroidAliases"))
      return App.importErgebnis(payload);
    let owned;
    try {
      if (gesperrt || !initialisiert || window.MacBeta.calendarImportBlocked()) throw alterAndroidTerminKonflikt();
      // Own the callback data. Later native/UI caller mutations cannot replace
      // the registered source or aliases. Shallow normalization copies retain
      // this private sidecar object's identity, including the >1000-row path.
      owned = structuredClone(payload);
      macOSBetaRegisterCalendarAliases(owned);
    } catch { return App.importErgebnis({ fehler: _("Conflict") }); }
    // Only pure registration failures are translated above. Do not turn a
    // later renderer/save failure into a pre-mutation alias rejection.
    return App.importErgebnis(owned);
  }
