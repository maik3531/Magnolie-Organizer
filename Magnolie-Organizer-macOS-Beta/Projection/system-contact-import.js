  // #775: deliberate additive copies of the enumerated public Contacts fields.
  // Native metadata is inert evidence, never provider identity or write consent.
  function macOSBetaContactTr(text) { return window.MacBeta.text(text); }
  let macOSBetaContactProposal = null;
  const macOSBetaContactPayloadLimit = 16 * 1024 * 1024;
  function macOSBetaContactBlocked() {
    return (window.MacBeta.contactImportBlocked?.() ?? window.MacBeta.noteImportBlocked()) ||
      gesperrt || !initialisiert || !antwortErhalten;
  }
  function macOSBetaContactHasDraft() {
    return !!aenderungsGuard || editorIstGeaendert() || modalStapel.some(item => item.schleier.isConnected) ||
      !!ausstehenderNotizSnapshot || notizSnapshotTimer !== null;
  }
  function macOSBetaContactHasSettingsDraft() {
    return !$("#einstellungen-schleier").classList.contains("verborgen") &&
      (nextcloudEntwurfGeaendert || !!$("#briefkasten-kennwort")?.value);
  }
  function macOSBetaContactExpired(proposal) {
    return Date.now() >= proposal.expires || performance.now() >= proposal.monotonicExpires;
  }
  function macOSBetaContactDiscardObsoleteReview() {
    const proposal = macOSBetaContactProposal;
    if (proposal?.state === "prepared" && (proposal.book !== DATEN || macOSBetaContactExpired(proposal)))
      macOSBetaContactProposal = null;
  }
  function macOSBetaStartContactImport() {
    if (macOSBetaContactBlocked()) return;
    macOSBetaContactDiscardObsoleteReview();
    if (macOSBetaContactProposal) { zettel(macOSBetaContactTr("A Contacts copy is already being reviewed.")); return; }
    if (macOSBetaContactHasSettingsDraft()) {
      zettel(macOSBetaContactTr("Save or discard the account changes before importing.")); return;
    }
    navigiereMitGuard(() => nachDauerhaftemSpeichern(() => {
      if (macOSBetaContactBlocked()) return;
      const settings = $("#einstellungen-schleier");
      if (modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings)) {
        zettel(macOSBetaContactTr("Finish or close the current editor before reviewing Contacts copies.")); return;
      }
      if (macOSBetaContactHasSettingsDraft()) {
        zettel(macOSBetaContactTr("Save or discard the account changes before importing.")); return;
      }
      if (!settings.classList.contains("verborgen")) schliesseEinstellungen();
      if (!Bruecke.sende({ cmd: "macos_kontakte_importieren" }))
        zettel(macOSBetaContactTr("The Contacts copy dialog could not be opened."));
    }, error => zettel(error.message)));
  }
  function macOSBetaContactObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  function macOSBetaContactText(value, maximum, empty = true) {
    if (typeof value !== "string" || (!empty && !value.length) || value.length > maximum) return false;
    for (const character of value) {
      const scalar = character.codePointAt(0);
      if (scalar >= 0xD800 && scalar <= 0xDFFF) return false;
    }
    return new TextEncoder().encode(value).length <= maximum;
  }
  function macOSBetaContactDigest(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  }
  function macOSBetaContactSource(source) {
    if (!macOSBetaContactObject(source) || !macOSBetaContactText(source.containerID, 16384, false) ||
        !macOSBetaContactText(source.sourceUID, 4096, false) || !macOSBetaContactText(source.title, 4096) ||
        !macOSBetaContactText(source.nativeType, 64, false) || !/^container:[0-9]+$/.test(source.nativeType)) return false;
    return source.sourceUID === "macos-contacts:" + btoa(String.fromCharCode(...new TextEncoder().encode(source.containerID)));
  }
  function macOSBetaContactNativeRecord(record) {
    if (!macOSBetaContactObject(record) || !macOSBetaContactText(record.identifier, 16384, false) ||
        !macOSBetaContactText(record.title, 4096) || record.failure !== null || !macOSBetaContactObject(record.fields)) return false;
    const fields = record.fields, names = ["namePrefix", "givenName", "middleName", "familyName", "previousFamilyName",
      "nameSuffix", "nickname", "phoneticGivenName", "phoneticMiddleName", "phoneticFamilyName", "phoneticOrganizationName",
      "organizationName", "departmentName", "jobTitle"], lists = ["phoneNumbers", "emailAddresses", "urlAddresses", "postalAddresses",
      "contactRelations", "socialProfiles", "instantMessageAddresses", "dates"];
    const keys = names.concat(lists, ["unification", "unavailableKeys", "contactType", "birthday", "nonGregorianBirthday",
      "imageDataAvailable", "imageData", "imageMIME"]);
    if (Object.keys(fields).length !== keys.length || keys.some(key => !Object.hasOwn(fields, key)) ||
        fields.unification !== "nonUnifiedContainer" || ![0, 1].includes(fields.contactType) ||
        !Array.isArray(fields.unavailableKeys) || fields.unavailableKeys.some(key => key !== "note") ||
        names.some(key => !macOSBetaContactText(fields[key], 65536)) ||
        lists.some(key => !Array.isArray(fields[key]) || fields[key].length > 1000) ||
        typeof fields.imageDataAvailable !== "boolean" ||
        (fields.imageData !== null && !macOSBetaContactText(fields.imageData, 3466668)) ||
        (fields.imageMIME !== null && !["image/jpeg", "image/png", "image/gif", "image/webp"].includes(fields.imageMIME))) return false;
    let nodes = 0;
    const valid = (value, depth) => {
      if (++nodes > 100000 || depth > 16) return false;
      if (value === null || typeof value === "boolean") return true;
      if (typeof value === "number") return Number.isFinite(value);
      if (typeof value === "string") return macOSBetaContactText(value, 65536);
      if (Array.isArray(value)) return value.length <= 1000 && value.every(child => valid(child, depth + 1));
      return macOSBetaContactObject(value) && Object.keys(value).length <= 1000 &&
        Object.entries(value).every(([key, child]) => macOSBetaContactText(key, 65536) && valid(child, depth + 1));
    };
    return Object.entries(fields).every(([key, value]) => key === "imageData" || valid(value, 0));
  }
  function macOSBetaContactProvenance(contact) {
    const meta = contact?.nativeContactImport, native = contact?.nativeContactRecord;
    if (!macOSBetaContactSource(meta && { ...meta, title: meta.sourceTitle }) || !kontaktGeburtstagNurAmKontakt(contact) ||
        !macOSBetaContactDigest(meta.identity) || !macOSBetaContactDigest(meta.revision) ||
        !macOSBetaContactText(meta.identifier, 16384, false) || meta.revisionCoverage !== "serialized-fields-only" ||
        !macOSBetaContactNativeRecord(native) || native.identifier !== meta.identifier)
      throw new Error(macOSBetaContactTr("Conflicting Contacts copy identity."));
    return { meta, key: JSON.stringify([meta.sourceUID, meta.identifier]) };
  }
  function macOSBetaContactIndex(book) {
    const byIdentity = new Map(), bySource = new Map(), trashIdentity = new Map(), trashSource = new Map();
    const add = (map, key, contact) => {
      if (typeof key !== "string" || !key) return;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(contact);
    };
    const sourceKey = contact => {
      const meta = contact?.nativeContactImport;
      return typeof meta?.sourceUID === "string" && typeof meta?.identifier === "string"
        ? JSON.stringify([meta.sourceUID, meta.identifier]) : "";
    };
    for (const contact of book.kontakte) {
      add(byIdentity, contact?.nativeContactImport?.identity, contact); add(bySource, sourceKey(contact), contact);
    }
    for (const item of book.papierkorb || []) if (["contact", "kontakt", "duplicate", "duplikat"].includes(item?.art)) {
      add(trashIdentity, item.eintrag?.nativeContactImport?.identity, item.eintrag);
      add(trashSource, sourceKey(item.eintrag), item.eintrag);
    }
    return { byIdentity, bySource, trashIdentity, trashSource };
  }
  function macOSBetaContactClassification(contact, index) {
    const { meta, key } = macOSBetaContactProvenance(contact);
    const found = [...new Set([...(index.byIdentity.get(meta.identity) || []), ...(index.bySource.get(key) || [])])];
    if (found.length > 1) throw new Error(macOSBetaContactTr("Multiple local contacts have the same Contacts identity."));
    const matching = previous => {
      const evidence = macOSBetaContactProvenance(previous);
      if (evidence.key !== key || evidence.meta.identity !== meta.identity || evidence.meta.containerID !== meta.containerID)
        throw new Error(macOSBetaContactTr("Conflicting Contacts copy identity."));
      return evidence.meta;
    };
    if (found.length) {
      const previous = matching(found[0]);
      return ["revision", "sourceTitle", "nativeType"].every(name => previous[name] === meta[name]) ? "existing" : "changed";
    }
    const trash = [...new Set([...(index.trashIdentity.get(meta.identity) || []), ...(index.trashSource.get(key) || [])])];
    trash.forEach(matching);
    return trash.length ? "trash" : "new";
  }
  function macOSBetaContactFields(contact) {
    if (!macOSBetaContactObject(contact)) return false;
    const text = ["vorname", "nachname", "anzeigename", "firma", "geburtstag"], lists = ["telefone", "emailEintraege", "anschriften"];
    const keys = text.concat(lists, ["foto", "geburtstagJahrUnbekannt", "vcardRoundtrip"]);
    if (Object.keys(contact).length !== keys.length || keys.some(key => !Object.hasOwn(contact, key)) ||
        text.some(key => !macOSBetaContactText(contact[key], 65536)) || typeof contact.geburtstagJahrUnbekannt !== "boolean" ||
        !macOSBetaContactText(contact.foto, 3500000) || !Array.isArray(contact.vcardRoundtrip) || contact.vcardRoundtrip.length > 1003 ||
        contact.vcardRoundtrip.some(line => !macOSBetaContactText(line, 400000) || !/^(?:N|FN|ORG|URL):[^\r\n]*$/.test(line))) return false;
    return lists.every(key => Array.isArray(contact[key]) && contact[key].length <= 1000 && contact[key].every(row => {
      const fields = key === "anschriften" ? ["postfach", "zusatz", "strasse", "ort", "region", "plz", "land", "label"] : ["wert", "label"];
      return macOSBetaContactObject(row) && Object.keys(row).length === fields.length + 1 &&
        fields.every(name => macOSBetaContactText(row[name], 65536)) && Array.isArray(row.typen) && row.typen.length <= 32 &&
        row.typen.every(type => macOSBetaContactText(type, 80, false));
    }));
  }
  function macOSBetaContactPreview(contact, title, notices) {
    const lines = [], add = (label, value) => { if (value) lines.push(label + ": " + value); };
    add(macOSBetaContactTr("Name"), contact.anzeigename); add(macOSBetaContactTr("First name"), contact.vorname); add(macOSBetaContactTr("Last name"), contact.nachname);
    add(macOSBetaContactTr("Company"), contact.firma);
    for (const row of contact.telefone) add(telefonBezeichnung(row), row.wert);
    for (const row of contact.emailEintraege) add(emailBezeichnung(row), row.wert);
    contact.anschriften.forEach((row, index) => {
      const parts = [[macOSBetaContactTr("PO box"), row.postfach], [macOSBetaContactTr("Address supplement"), row.zusatz], [macOSBetaContactTr("Street and house number"), row.strasse],
        [macOSBetaContactTr("Postal code"), row.plz], [macOSBetaContactTr("City"), row.ort], [macOSBetaContactTr("Region"), row.region], [macOSBetaContactTr("Country (optional)"), row.land]];
      lines.push(anschriftBezeichnung(row, index));
      parts.forEach(([label, value]) => add(label, value));
    });
    for (const url of kontaktWebseiten(contact)) add(macOSBetaContactTr("Website"), url);
    if (contact.geburtstag) {
      add(macOSBetaContactTr("Birthday"), contact.geburtstagJahrUnbekannt ? fmtTagMonat(contact.geburtstag) : fmtPunkt(contact.geburtstag));
      lines.push(macOSBetaContactTr("Birthday stored with this contact; no calendar entry."));
    }
    if (contact.foto) lines.push(macOSBetaContactTr("Photo"));
    return { title, text: lines.join("\n"), notices: notices.slice(), ...(contact.foto ? { photo: contact.foto } : {}) };
  }
  function macOSBetaPrepareContactImport(payload) {
    if (macOSBetaContactBlocked()) throw new Error(macOSBetaContactTr("Contacts copying is not available."));
    if (macOSBetaContactHasDraft()) throw new Error(macOSBetaContactTr("Finish or close the current editor before reviewing Contacts copies."));
    macOSBetaContactDiscardObsoleteReview();
    if (macOSBetaContactProposal) throw new Error(macOSBetaContactTr("A Contacts copy is already being reviewed."));
    const text = JSON.stringify(payload);
    if (!text || text.length > macOSBetaContactPayloadLimit || new TextEncoder().encode(text).length > macOSBetaContactPayloadLimit)
      throw new Error(macOSBetaContactTr("Contacts copy proposal exceeds the byte limit."));
    const value = JSON.parse(text);
    if (!macOSBetaContactObject(value) || value.version !== 1 || !macOSBetaContactSource(value.source) ||
        !macOSBetaContactDigest(value.snapshotRevision) || !Array.isArray(value.contacts) || !Array.isArray(value.excluded) ||
        value.contacts.length + value.excluded.length > 100) throw new Error(macOSBetaContactTr("Invalid Contacts copy proposal."));
    const source = Object.fromEntries(["sourceUID", "containerID", "title", "nativeType"].map(name => [name, value.source[name]]));
    const seen = new Set(), seenIdentities = new Set();
    const excluded = value.excluded.map(item => {
      if (!macOSBetaContactObject(item) || !macOSBetaContactText(item.identifier, 16384, false) ||
          !macOSBetaContactText(item.title, 4096) || !Array.isArray(item.reasons) || !item.reasons.length || item.reasons.length > 256 ||
          item.reasons.some(reason => !macOSBetaContactText(reason, 1024, false)) || seen.has(item.identifier))
        throw new Error(macOSBetaContactTr("Invalid Contacts copy exclusion."));
      seen.add(item.identifier);
      return { identifier: item.identifier, title: item.title, reasons: item.reasons.slice() };
    });
    const book = DATEN, content = JSON.stringify(book), index = macOSBetaContactIndex(book), candidates = [], preview = [], changedPreview = [];
    const localIDs = new Set(book.kontakte.map(contact => contact.id)), localUIDs = new Set(book.kontakte.map(contact => contact.uid));
    let existingCount = 0, changedCount = 0;
    for (const item of value.contacts) {
      if (!macOSBetaContactObject(item) || !macOSBetaContactDigest(item.identity) || !macOSBetaContactDigest(item.revision) ||
          !macOSBetaContactText(item.identifier, 16384, false) || !macOSBetaContactText(item.title, 4096) ||
          !macOSBetaContactFields(item.contact) || !macOSBetaContactNativeRecord(item.nativeRecord) ||
          item.identifier !== item.nativeRecord.identifier || item.title !== item.nativeRecord.title || item.title !== item.contact.anzeigename ||
          !Array.isArray(item.notices) || item.notices.length > 256 || item.notices.some(code => !macOSBetaContactText(code, 1024, false)) ||
          !item.notices.includes("native-contact-public-fields-only") || seen.has(item.identifier) || seenIdentities.has(item.identity))
        throw new Error(macOSBetaContactTr("Invalid or ambiguous Contacts copy proposal."));
      seen.add(item.identifier); seenIdentities.add(item.identity);
      const evidence = { nativeContactImport: { version: 1, identity: item.identity, sourceUID: source.sourceUID, containerID: source.containerID,
        sourceTitle: source.title, nativeType: source.nativeType, identifier: item.identifier, revision: item.revision,
        copyKind: "public-fields", revisionCoverage: "serialized-fields-only", birthdayPolicy: "contact-only" }, nativeContactRecord: item.nativeRecord };
      const classification = macOSBetaContactClassification(evidence, index);
      if (classification === "existing") { existingCount++; continue; }
      if (classification === "changed") { changedCount++; changedPreview.push({ title: item.title }); continue; }
      if (classification === "trash") {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["local-contact-copy-in-trash"] }); continue;
      }
      if (item.nativeRecord.fields.urlAddresses.some(row => !macOSBetaContactObject(row) ||
          typeof row.value !== "string" || !webLinkZiel(row.value))) {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["canonical-contact-content-would-change"] }); continue;
      }
      const fields = kopie(item.contact), notices = new Set(item.notices);
      for (const key of ["telefone", "emailEintraege", "anschriften"]) for (const row of fields[key]) {
        if (row.label === "") delete row.label;
        if (row.postfach === "") delete row.postfach;
        if (row.zusatz === "") delete row.zusatz;
        if (key === "emailEintraege" && row.wert !== row.wert.toLowerCase()) {
          row.wert = row.wert.toLowerCase(); notices.add("native-contact-email-case-normalized");
        }
      }
      const candidate = { ...fields, id: uid(), uid: syncUid(), sync: false, syncQuellen: {}, ...evidence };
      if (localIDs.has(candidate.id) || localUIDs.has(candidate.uid)) throw new Error(macOSBetaContactTr("Local contact identity conflict."));
      localIDs.add(candidate.id); localUIDs.add(candidate.uid);
      let normalized;
      try {
        // Existing records never enter mergeKontakte or the normalizer here.
        // Actual regional phone rules apply; automatic birthday synthesis is
        // disabled only for these marked copies by the audited projection.
        const isolated = normalisiere({ kontakte: [candidate], einstellungen: kopie(book.einstellungen) });
        if (isolated.kontakte.length === 1 && !isolated.jahrestage.length) normalized = isolated.kontakte[0];
      } catch (_) { /* A shortened canonical array is a visible exclusion. */ }
      if (!normalized || Object.keys(candidate).some(name =>
          kanonischerEntwurf(normalized[name]) !== kanonischerEntwurf(candidate[name]))) {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["canonical-contact-content-would-change"] }); continue;
      }
      candidates.push(normalized);
      preview.push(macOSBetaContactPreview(normalized, item.title, [...notices].sort()));
    }
    if (DATEN !== book || JSON.stringify(book) !== content || macOSBetaContactBlocked() || macOSBetaContactHasDraft())
      throw new Error(macOSBetaContactTr("The document changed while preparing Contacts copies."));
    const token = anrufClientRef();
    macOSBetaContactProposal = { token, book, content, candidates,
      expires: Date.now() + 5 * 60000, monotonicExpires: performance.now() + 5 * 60000, state: "prepared" };
    return kopie({ ok: true, token, source, snapshotRevision: value.snapshotRevision,
      newCount: candidates.length, existingCount, changedCount, changedPreview, excluded, addressbookTitle: macOSBetaContactTr("Contacts"), preview });
  }
  function macOSBetaContactRequireCurrent(proposal) {
    if (macOSBetaContactProposal !== proposal || macOSBetaContactBlocked() || macOSBetaContactHasDraft() ||
        macOSBetaContactExpired(proposal) || DATEN !== proposal.book || JSON.stringify(DATEN) !== proposal.content)
      throw new Error(macOSBetaContactTr("The Contacts copy review is stale. Open it again."));
    const index = macOSBetaContactIndex(DATEN), ids = new Set(DATEN.kontakte.map(contact => contact.id)), uids = new Set(DATEN.kontakte.map(contact => contact.uid));
    for (const candidate of proposal.candidates) {
      if (ids.has(candidate.id) || uids.has(candidate.uid) || macOSBetaContactClassification(candidate, index) !== "new")
        throw new Error(macOSBetaContactTr("The Contacts copy identity changed. Open it again."));
      ids.add(candidate.id); uids.add(candidate.uid);
    }
  }
  function macOSBetaCommitContactImport(token) {
    return new Promise((resolve, reject) => {
      const proposal = macOSBetaContactProposal;
      let ownsProposal = false, appended = false, saveConfirmed = false;
      const failed = (error, saveRejected = false) => {
        // #778: the renderer may fail after the local append and before the
        // save callback is registered. Report the mutation, never a rollback or
        // an unobserved write failure; a scheduled save may still be pending.
        if (appended && !saveConfirmed) {
          const prefix = saveRejected
            ? window.MacBeta.text("Imported contacts remain unsaved. Save the pending changes before importing again.")
            : window.MacBeta.text("Contact copies were added, but saving was not confirmed. Check and save the pending changes before importing again.");
          const detail = String(error?.message || error);
          if (!detail.startsWith(prefix)) error = new Error(prefix + " " + detail);
        }
        if (ownsProposal && macOSBetaContactProposal === proposal) macOSBetaContactProposal = null;
        reject(error);
      };
      try {
        if (!proposal || proposal.token !== token || proposal.state !== "prepared")
          throw new Error(macOSBetaContactTr("Invalid or already used Contacts copy review."));
        ownsProposal = true;
        macOSBetaContactRequireCurrent(proposal);
        if (!proposal.candidates.length) {
          macOSBetaContactProposal = null; resolve({ ok: true, count: 0, ids: [] }); return;
        }
        proposal.state = "checkpoint";
        mitMutationsSnapshot("pre-system-contact-copy", () => {
          try {
            macOSBetaContactRequireCurrent(proposal);
            proposal.state = "saving";
            proposal.book.kontakte.push(...proposal.candidates);
            appended = true;
            planeSpeichern(); zeichneAlles();
            nachDauerhaftemSpeichern(() => {
              saveConfirmed = true;
              if (DATEN !== proposal.book || macOSBetaContactBlocked() ||
                  proposal.candidates.some(contact => !DATEN.kontakte.includes(contact))) {
                failed(new Error(macOSBetaContactTr("The document changed before the Contacts copy save completed."))); return;
              }
              if (macOSBetaContactProposal === proposal) macOSBetaContactProposal = null;
              resolve({ ok: true, count: proposal.candidates.length, ids: proposal.candidates.map(contact => contact.id) });
            }, error => failed(error, true));
          } catch (error) { failed(error); }
        }, failed);
      } catch (error) { failed(error); }
    });
  }
  function macOSBetaCancelContactImport(token) {
    const proposal = macOSBetaContactProposal;
    if (!proposal || proposal.token !== token || proposal.state === "saving") return { ok: true, cancelled: false };
    macOSBetaContactProposal = null;
    return { ok: true, cancelled: true };
  }
