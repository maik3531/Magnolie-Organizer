  // #777: deliberate standalone copies of the public EventKit reminder fields.
  // Source evidence is inert: it never grants sync, delegation or alarm consent.
  function macOSBetaReminderTr(text) { return window.MacBeta.text(text); }
  let macOSBetaReminderProposal = null;
  const macOSBetaReminderPayloadLimit = 16 * 1024 * 1024;
  function macOSBetaReminderBlocked() {
    return (window.MacBeta.reminderImportBlocked?.() ?? window.MacBeta.noteImportBlocked()) ||
      gesperrt || !initialisiert || !antwortErhalten;
  }
  function macOSBetaReminderHasDraft() {
    return !!aenderungsGuard || editorIstGeaendert() || modalStapel.some(item => item.schleier.isConnected) ||
      !!ausstehenderNotizSnapshot || notizSnapshotTimer !== null;
  }
  function macOSBetaReminderHasSettingsDraft() {
    return !$("#einstellungen-schleier").classList.contains("verborgen") &&
      (nextcloudEntwurfGeaendert || !!$("#briefkasten-kennwort")?.value);
  }
  function macOSBetaReminderExpired(proposal) {
    return Date.now() >= proposal.expires || performance.now() >= proposal.monotonicExpires;
  }
  function macOSBetaReminderDiscardObsoleteReview() {
    const proposal = macOSBetaReminderProposal;
    if (proposal?.state === "prepared" && (proposal.book !== DATEN || macOSBetaReminderExpired(proposal)))
      macOSBetaReminderProposal = null;
  }
  function macOSBetaStartReminderImport() {
    if (macOSBetaReminderBlocked()) return;
    macOSBetaReminderDiscardObsoleteReview();
    if (macOSBetaReminderProposal) { zettel(macOSBetaReminderTr("A Reminders copy is already being reviewed.")); return; }
    if (macOSBetaReminderHasSettingsDraft()) {
      zettel(macOSBetaReminderTr("Save or discard the account changes before importing.")); return;
    }
    navigiereMitGuard(() => nachDauerhaftemSpeichern(() => {
      if (macOSBetaReminderBlocked()) return;
      const settings = $("#einstellungen-schleier");
      if (aenderungsGuard || editorIstGeaendert() || ausstehenderNotizSnapshot || notizSnapshotTimer !== null ||
          modalStapel.some(item => item.schleier.isConnected && item.schleier !== settings)) {
        zettel(macOSBetaReminderTr("Finish or close the current editor before reviewing Reminders copies.")); return;
      }
      if (macOSBetaReminderHasSettingsDraft()) {
        zettel(macOSBetaReminderTr("Save or discard the account changes before importing.")); return;
      }
      if (!settings.classList.contains("verborgen")) schliesseEinstellungen();
      if (!Bruecke.sende({ cmd: "macos_erinnerungen_importieren" }))
        zettel(macOSBetaReminderTr("The Reminders copy dialog could not be opened."));
    }, error => zettel(error.message)));
  }
  function macOSBetaReminderObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  function macOSBetaReminderText(value, maximum, empty = true) {
    if (typeof value !== "string" || (!empty && !value.length) || value.length > maximum) return false;
    for (const character of value) {
      const scalar = character.codePointAt(0);
      if (scalar >= 0xD800 && scalar <= 0xDFFF) return false;
    }
    return new TextEncoder().encode(value).length <= maximum;
  }
  function macOSBetaReminderDigest(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  }
  function macOSBetaReminderEncodedIdentity(value, prefix, maximum) {
    if (!macOSBetaReminderText(value, maximum, false) || !value.startsWith(prefix)) return false;
    try {
      const encoded = value.slice(prefix.length), bytes = atob(encoded);
      return bytes.length > 0 && btoa(bytes) === encoded &&
        new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(bytes, letter => letter.charCodeAt(0))).length > 0;
    } catch (_) { return false; }
  }
  function macOSBetaReminderSource(source) {
    return macOSBetaReminderObject(source) && macOSBetaReminderText(source.calendarID, 16384, false) &&
      macOSBetaReminderEncodedIdentity(source.sourceUID, "macos-reminders:", 4096) &&
      source.sourceUID === "macos-reminders:" + btoa(String.fromCharCode(...new TextEncoder().encode(source.calendarID))) &&
      macOSBetaReminderText(source.title, 4096) && macOSBetaReminderText(source.parentTitle, 4096) &&
      macOSBetaReminderEncodedIdentity(source.parentUID, "macos-account:", 8192) &&
      macOSBetaReminderText(source.parentType, 64, false) && /^source:[0-9]+$/.test(source.parentType) &&
      macOSBetaReminderText(source.nativeType, 64, false) && /^calendar:[0-9]+$/.test(source.nativeType) &&
      typeof source.readOnly === "boolean" && source.permission === "authorized";
  }
  function macOSBetaReminderNativeRecord(record) {
    if (!macOSBetaReminderObject(record) || !macOSBetaReminderText(record.identifier, 16384, false) ||
        record.failure !== null || !macOSBetaReminderObject(record.fields)) return false;
    const fields = record.fields, strings = ["title", "notes", "location", "url", "externalIdentifier", "itemTimeZone"],
      timestamps = ["created", "modified", "completionDate"], flags = ["completed", "hasNotes", "hasAlarms", "hasRecurrenceRules", "hierarchyAvailable"],
      keys = strings.concat(timestamps, flags, ["priority", "startComponents", "dueComponents", "alarms", "recurrenceRules", "metadataIncomplete"]),
      coverage = ["native-reminder-hierarchy", "native-reminder-attachments", "native-reminder-tags", "native-reminder-flags",
        "native-reminder-assignees", "native-reminder-rich-text", "provider-opaque-fields"];
    if (Object.keys(fields).length !== keys.length || keys.some(key => !Object.hasOwn(fields, key)) ||
        strings.some(key => fields[key] !== null && !macOSBetaReminderText(fields[key],
          { title: 4096, notes: 1048576, externalIdentifier: 16384, itemTimeZone: 1024 }[key] || 65536)) ||
        timestamps.some(key => fields[key] !== null && (!Number.isFinite(fields[key]) || fields[key] < -62135596800 || fields[key] > 253402300799.999)) ||
        flags.some(key => typeof fields[key] !== "boolean") || !fields.completed && fields.completionDate !== null ||
        !Number.isInteger(fields.priority) || fields.priority < 0 || fields.priority > 9 || fields.hierarchyAvailable !== false ||
        fields.hasAlarms !== false || !Array.isArray(fields.alarms) || fields.alarms.length ||
        fields.hasRecurrenceRules !== false || !Array.isArray(fields.recurrenceRules) || fields.recurrenceRules.length ||
        fields.hasNotes && fields.notes === null || !fields.hasNotes && fields.notes !== null && fields.notes !== "" ||
        !Array.isArray(fields.metadataIncomplete) || fields.metadataIncomplete.length > 64 ||
        coverage.some(code => !fields.metadataIncomplete.includes(code)) ||
        fields.metadataIncomplete.some(code => !coverage.includes(code) && code !== "alarm-procedure-url-not-exposed")) return false;
    let nodes = 0;
    const valid = (value, depth) => {
      if (++nodes > 1024 || depth > 8) return false;
      if (value === null || typeof value === "boolean") return true;
      if (typeof value === "number") return Number.isFinite(value);
      if (typeof value === "string") return macOSBetaReminderText(value, 65536);
      if (Array.isArray(value)) return value.length <= 64 && value.every(child => valid(child, depth + 1));
      return macOSBetaReminderObject(value) && Object.keys(value).length <= 64 &&
        Object.entries(value).every(([key, child]) => macOSBetaReminderText(key, 256) && valid(child, depth + 1));
    };
    return ["startComponents", "dueComponents"].every(key => fields[key] === null ||
      macOSBetaReminderObject(fields[key]) && valid(fields[key], 0));
  }
  function macOSBetaReminderProvenance(task) {
    const meta = task?.nativeReminderImport, native = task?.nativeReminderRecord;
    if (!macOSBetaReminderSource(meta && { ...meta, title: meta.sourceTitle }) || meta.version !== 1 ||
        meta.copyKind !== "standalone-public-fields" || meta.revisionCoverage !== "serialized-fields-only" ||
        !macOSBetaReminderDigest(meta.identity) || !macOSBetaReminderDigest(meta.revision) ||
        !macOSBetaReminderText(meta.identifier, 16384, false) ||
        !macOSBetaReminderNativeRecord(native) || native.identifier !== meta.identifier)
      throw new Error(macOSBetaReminderTr("Conflicting Reminders copy identity."));
    return { meta, key: JSON.stringify([meta.sourceUID, meta.identifier]) };
  }
  function macOSBetaReminderIndex(book) {
    const byIdentity = new Map(), bySource = new Map(), trashIdentity = new Map(), trashSource = new Map();
    const add = (map, key, task) => {
      if (typeof key !== "string" || !key) return;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(task);
    };
    const sourceKey = task => {
      const meta = task?.nativeReminderImport;
      return typeof meta?.sourceUID === "string" && typeof meta?.identifier === "string"
        ? JSON.stringify([meta.sourceUID, meta.identifier]) : "";
    };
    for (const task of book.aufgaben) {
      add(byIdentity, task?.nativeReminderImport?.identity, task); add(bySource, sourceKey(task), task);
    }
    for (const item of book.papierkorb || []) if (["task", "aufgabe"].includes(item?.art)) {
      add(trashIdentity, item.eintrag?.nativeReminderImport?.identity, item.eintrag);
      add(trashSource, sourceKey(item.eintrag), item.eintrag);
    }
    return { byIdentity, bySource, trashIdentity, trashSource };
  }
  function macOSBetaReminderClassification(task, index) {
    const { meta, key } = macOSBetaReminderProvenance(task);
    const found = [...new Set([...(index.byIdentity.get(meta.identity) || []), ...(index.bySource.get(key) || [])])];
    if (found.length > 1) throw new Error(macOSBetaReminderTr("Multiple local tasks have the same Reminders identity."));
    const matching = previous => {
      const evidence = macOSBetaReminderProvenance(previous);
      if (evidence.key !== key || evidence.meta.identity !== meta.identity || evidence.meta.calendarID !== meta.calendarID || evidence.meta.parentUID !== meta.parentUID)
        throw new Error(macOSBetaReminderTr("Conflicting Reminders copy identity."));
      return evidence.meta;
    };
    if (found.length) {
      const previous = matching(found[0]);
      return ["revision", "sourceTitle", "parentTitle", "parentType", "nativeType", "readOnly", "permission"]
        .every(name => previous[name] === meta[name]) ? "existing" : "changed";
    }
    const trash = [...new Set([...(index.trashIdentity.get(meta.identity) || []), ...(index.trashSource.get(key) || [])])];
    trash.forEach(matching);
    return trash.length ? "trash" : "new";
  }
  function macOSBetaReminderFields(task) {
    if (!macOSBetaReminderObject(task)) return false;
    const strings = ["titel", "notiz", "startDatum", "startZeit", "faellig", "faelligZeit", "icsAnzeigeZeitzone"],
      keys = strings.concat(["prio", "erledigt", "icsRoundtrip", "erinnern", "individuelleErinnerungTage", "vorlaufTage", "erinnerungsMinute"]);
    return Object.keys(task).length === keys.length && keys.every(key => Object.hasOwn(task, key)) &&
      strings.every(key => macOSBetaReminderText(task[key], key === "notiz" ? 1048576 : key === "titel" ? 4096 : 256)) &&
      [1, 2, 3].includes(task.prio) && typeof task.erledigt === "boolean" && task.erinnern === false &&
      task.individuelleErinnerungTage === 0 && task.vorlaufTage === 0 && task.erinnerungsMinute === 480 &&
      Array.isArray(task.icsRoundtrip) && task.icsRoundtrip.length <= 2 &&
      task.icsRoundtrip.every(line => macOSBetaReminderText(line, 1024, false) && !/[\r\n]/.test(line));
  }
  function macOSBetaReminderNativeDates(fields, task) {
    const allowed = new Set(["era", "year", "month", "day", "hour", "minute", "second", "nanosecond", "isLeapMonth", "calendar",
      "calendarTimeZone", "calendarFirstWeekday", "calendarMinimumDaysInFirstWeek", "calendarLocale", "timeZone"]), lines = [], kinds = [];
    for (const [key, name] of [["startComponents", "DTSTART"], ["dueComponents", "DUE"]]) {
      const value = fields[key];
      if (value === null) continue;
      if (!macOSBetaReminderObject(value) || Object.keys(value).some(key => !allowed.has(key)) || value.calendar !== "gregorian" ||
          !["year", "month", "day"].every(key => Number.isSafeInteger(value[key])) || value.year < 1000 || value.year > 9999 ||
          value.era !== undefined && value.era !== 1 || value.isLeapMonth !== undefined && value.isLeapMonth !== false ||
          value.second !== undefined && value.second !== 0 || value.nanosecond !== undefined && value.nanosecond !== 0) return false;
      for (const key of ["calendarTimeZone", "calendarLocale", "timeZone"]) if (value[key] !== undefined &&
          (!macOSBetaReminderText(value[key], 1024, key !== "timeZone") || /[\x00-\x1F\x7F-\x9F]/.test(value[key]))) return false;
      for (const key of ["calendarFirstWeekday", "calendarMinimumDaysInFirstWeek"]) if (value[key] !== undefined &&
          (!Number.isInteger(value[key]) || value[key] < 1 || value[key] > 7)) return false;
      const date = String(value.year).padStart(4, "0") + "-" + pad2(value.month) + "-" + pad2(value.day);
      if (!gueltigesISO(date)) return false;
      const dateOnly = ["hour", "minute", "second"].every(key => value[key] === undefined);
      if (!dateOnly && (!Number.isInteger(value.hour) || value.hour < 0 || value.hour > 23 ||
          !Number.isInteger(value.minute) || value.minute < 0 || value.minute > 59)) return false;
      const floating = value.timeZone === undefined;
      kinds.push({ dateOnly, floating });
      lines.push(name + (dateOnly ? ";VALUE=DATE" : floating ? "" : ";TZID=" + value.timeZone) + ":" + date.replace(/-/g, "") +
        (dateOnly ? "" : "T" + pad2(value.hour) + pad2(value.minute) + "00"));
    }
    if (kinds.length === 2 && kinds.every(kind => !kind.dateOnly) && kinds[0].floating !== kinds[1].floating) return false;
    // Exact checked-source fields produce these two live lines. Never accept a
    // different valid task date merely because it independently normalizes.
    return JSON.stringify(lines) === JSON.stringify(task.icsRoundtrip);
  }
  function macOSBetaReminderEditable(task, displayZone, fields) {
    if (!task.titel || task.titel.trim() !== task.titel || /[\x00-\x1F\x7F-\x9F]/.test(task.titel) || /[\x00-\x08\x0B-\x1F\x7F-\x9F]/.test(task.notiz) ||
        task.icsAnzeigeZeitzone !== displayZone || !gueltigeIanaZeitzone(displayZone) || !macOSBetaReminderNativeDates(fields, task)) return false;
    for (const [date, time] of [[task.startDatum, task.startZeit], [task.faellig, task.faelligZeit]])
      if (date && !gueltigesISO(date) || time && (!date || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time))) return false;
    if (task.startDatum && task.faellig && task.faellig < task.startDatum) return false;
    if (task.startZeit && task.faellig && (!task.faelligZeit || task.startDatum + "T" + task.startZeit >= task.faellig + "T" + task.faelligZeit)) return false;
    const expected = new Map([["DTSTART", [task.startDatum, task.startZeit]], ["DUE", [task.faellig, task.faelligZeit]]]), instants = new Map();
    for (const line of task.icsRoundtrip) {
      const match = /^(DTSTART|DUE)(?:(;VALUE=DATE)|;TZID=([A-Za-z0-9_+./-]+))?:(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})00(Z)?)?$/.exec(line);
      if (!match || !expected.has(match[1]) || (!!match[2] === !!match[7]) || match[3] && match[9]) return false;
      const [date, time] = expected.get(match[1]), sourceDate = `${match[4]}-${match[5]}-${match[6]}`;
      expected.delete(match[1]);
      if (!date || !gueltigesISO(sourceDate)) return false;
      if (match[2]) { if (date !== sourceDate || time) return false; continue; }
      if (!time || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(`${match[7]}:${match[8]}`)) return false;
      // A floating wall time has no native zone. Its exact date/clock is kept
      // even in a gap/fold of the current display zone; no instant is invented.
      if (!match[3] && !match[9]) {
        if (date !== sourceDate || time !== `${match[7]}:${match[8]}`) return false;
        continue;
      }
      try {
        const zone = match[9] ? "UTC" : match[3];
        const values = MagnolieTime.candidates(zone, { year: +match[4], month: +match[5], day: +match[6], hour: +match[7], minute: +match[8], second: 0 });
        if (values.length !== 1) return false;
        instants.set(match[1], values[0]);
        const parts = MagnolieTime.wallParts(displayZone, new Date(values[0]));
        if (date !== String(parts.year).padStart(4, "0") + "-" + pad2(parts.month) + "-" + pad2(parts.day) ||
            time !== pad2(parts.hour) + ":" + pad2(parts.minute) || parts.second !== 0) return false;
      } catch (_) { return false; }
    }
    return [...expected.values()].every(([date, time]) => !date && !time) &&
      (instants.size !== 2 || instants.get("DUE") > instants.get("DTSTART"));
  }
  function macOSBetaReminderGraph(book, candidates) {
    if (!candidates.length) return;
    // Rendering also normalizes this graph. Prove on clones that this later
    // normalization is a no-op for every existing task, not only its parent.
    const before = JSON.stringify(book.aufgaben), proposed = kopie(book.aufgaben.concat(candidates));
    normalisiereAufgabenGraph(proposed);
    if (JSON.stringify(proposed.slice(0, book.aufgaben.length)) !== before ||
        JSON.stringify(proposed.slice(book.aufgaben.length)) !== JSON.stringify(candidates))
      throw new Error(macOSBetaReminderTr("The task hierarchy would change. Reopen the document before importing."));
  }
  function macOSBetaReminderPreview(task, item) {
    const lines = [], add = (label, value) => { if (value !== "" && value !== null) lines.push(label + ": " + value); };
    add(macOSBetaReminderTr("Title"), task.titel);
    add(macOSBetaReminderTr("Note"), task.notiz);
    add(macOSBetaReminderTr("Priority"), macOSBetaReminderTr(task.prio === 1 ? "High" : task.prio === 3 ? "Low" : "Normal"));
    add(macOSBetaReminderTr("Original priority"), item.nativeRecord.fields.priority);
    add(macOSBetaReminderTr("Status"), macOSBetaReminderTr(task.erledigt ? "Completed" : "Open"));
    if (task.startDatum) add(macOSBetaReminderTr("Start date"), task.startDatum + (task.startZeit ? " " + task.startZeit : ""));
    if (task.faellig) add(macOSBetaReminderTr("Due on"), task.faellig + (task.faelligZeit ? " " + task.faelligZeit : ""));
    if (task.startZeit || task.faelligZeit) add(macOSBetaReminderTr("Display timezone"), task.icsAnzeigeZeitzone);
    if (task.icsRoundtrip.some(line => /^(?:DTSTART|DUE):\d{8}T\d{6}$/.test(line)))
      lines.push(macOSBetaReminderTr("Floating time; no source time zone is assigned."));
    const fields = item.nativeRecord.fields;
    for (const [key, label] of [["created", "Source creation time"], ["modified", "Source modification time"], ["completionDate", "Source completion time"]])
      if (fields[key] !== null) add(macOSBetaReminderTr(label), new Date(fields[key] * 1000).toISOString());
    if (fields.location) add(macOSBetaReminderTr("Location in source data"), fields.location);
    if (fields.url) add(macOSBetaReminderTr("URL in source data"), fields.url);
    lines.push(macOSBetaReminderTr("Standalone local task; source hierarchy and unavailable fields are not copied."));
    lines.push(macOSBetaReminderTr("No task notification is enabled by this copy."));
    return { title: item.title, text: lines.join("\n"), notices: item.notices.slice() };
  }
  function macOSBetaPrepareReminderImport(payload) {
    if (macOSBetaReminderBlocked()) throw new Error(macOSBetaReminderTr("Reminders copying is not available."));
    if (macOSBetaReminderHasDraft()) throw new Error(macOSBetaReminderTr("Finish or close the current editor before reviewing Reminders copies."));
    macOSBetaReminderDiscardObsoleteReview();
    if (macOSBetaReminderProposal) throw new Error(macOSBetaReminderTr("A Reminders copy is already being reviewed."));
    const text = JSON.stringify(payload);
    if (!text || text.length > macOSBetaReminderPayloadLimit || new TextEncoder().encode(text).length > macOSBetaReminderPayloadLimit)
      throw new Error(macOSBetaReminderTr("Reminders copy proposal exceeds the byte limit."));
    const value = JSON.parse(text), displayZone = eigeneIanaZeitzone();
    if (!macOSBetaReminderObject(value) || value.version !== 1 || !macOSBetaReminderSource(value.source) ||
        !macOSBetaReminderText(value.displayTimeZone, 256, false) || !gueltigeIanaZeitzone(value.displayTimeZone) || value.displayTimeZone !== displayZone ||
        !macOSBetaReminderDigest(value.snapshotRevision) || !Array.isArray(value.tasks) || !Array.isArray(value.excluded) ||
        value.tasks.length + value.excluded.length > 100) throw new Error(macOSBetaReminderTr("Invalid Reminders copy proposal."));
    const source = Object.fromEntries(["sourceUID", "calendarID", "title", "parentUID", "parentTitle", "parentType", "nativeType", "readOnly", "permission"]
      .map(name => [name, value.source[name]]));
    const seen = new Set(), identities = new Set();
    const excluded = value.excluded.map(item => {
      if (!macOSBetaReminderObject(item) || !macOSBetaReminderText(item.identifier, 16384, false) ||
          !macOSBetaReminderText(item.title, 4096) || !Array.isArray(item.reasons) || !item.reasons.length || item.reasons.length > 256 ||
          item.reasons.some(reason => !macOSBetaReminderText(reason, 1024, false)) || seen.has(item.identifier))
        throw new Error(macOSBetaReminderTr("Invalid Reminders copy exclusion."));
      seen.add(item.identifier); return { identifier: item.identifier, title: item.title, reasons: item.reasons.slice() };
    });
    const book = DATEN, content = JSON.stringify(book), index = macOSBetaReminderIndex(book), candidates = [], preview = [], changedPreview = [];
    const ids = new Set(book.aufgaben.map(task => task.id)), uids = new Set(book.aufgaben.map(task => task.uid));
    const rootCount = book.aufgaben.filter(task => !task.elternUid).length;
    let existingCount = 0, changedCount = 0;
    for (const item of value.tasks) {
      if (!macOSBetaReminderObject(item) || !macOSBetaReminderDigest(item.identity) || !macOSBetaReminderDigest(item.revision) ||
          !macOSBetaReminderText(item.identifier, 16384, false) || !macOSBetaReminderText(item.title, 4096) ||
          !macOSBetaReminderFields(item.task) || !macOSBetaReminderNativeRecord(item.nativeRecord) ||
          item.identifier !== item.nativeRecord.identifier || item.title !== item.task.titel || item.title !== item.nativeRecord.fields.title ||
          item.task.notiz !== (item.nativeRecord.fields.notes ?? "") || item.task.erledigt !== item.nativeRecord.fields.completed ||
          item.task.prio !== (item.nativeRecord.fields.priority >= 1 && item.nativeRecord.fields.priority <= 3 ? 1 : item.nativeRecord.fields.priority >= 7 ? 3 : 2) ||
          !Array.isArray(item.notices) || item.notices.length > 256 || item.notices.some(code => !macOSBetaReminderText(code, 1024, false)) ||
          ["native-reminder-standalone-copy", "native-reminder-public-fields-only", "native-reminder-priority-grouped"].some(code => !item.notices.includes(code)) ||
          seen.has(item.identifier) || identities.has(item.identity))
        throw new Error(macOSBetaReminderTr("Invalid or ambiguous Reminders copy proposal."));
      seen.add(item.identifier); identities.add(item.identity);
      const evidence = { nativeReminderImport: { version: 1, identity: item.identity, sourceUID: source.sourceUID, calendarID: source.calendarID,
        sourceTitle: source.title, parentUID: source.parentUID, parentTitle: source.parentTitle, parentType: source.parentType,
        nativeType: source.nativeType, readOnly: source.readOnly, permission: source.permission, identifier: item.identifier, revision: item.revision,
        copyKind: "standalone-public-fields", revisionCoverage: "serialized-fields-only" }, nativeReminderRecord: item.nativeRecord };
      const classification = macOSBetaReminderClassification(evidence, index);
      if (classification === "existing") { existingCount++; continue; }
      if (classification === "changed") { changedCount++; changedPreview.push({ title: item.title }); continue; }
      if (classification === "trash") {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["local-reminder-copy-in-trash"] }); continue;
      }
      if (!macOSBetaReminderEditable(item.task, displayZone, item.nativeRecord.fields)) {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["canonical-reminder-content-would-change"] }); continue;
      }
      const candidate = neueAufgabeDaten({ ...item.task, uid: syncUid(), elternUid: "", reihenfolge: 0,
        icsImportUid: "", icsElternUid: "", icsElternQuelleId: "", icsSerienUid: "", icsQuelleId: "", icsQuelleName: "",
        sync: false, syncKalenderUid: "", syncQuellen: {}, personen: [], kontaktId: "", vonTermin: "", herkunft: "", vonZweig: "", fremdId: "", delegiertAn: "",
        icsRangeOverrides: [], icsAusnahmeTermine: [], icsAusnahmen: [], icsZusatzTermine: [], icsTimezones: [], ...evidence });
      if (ids.has(candidate.id) || uids.has(candidate.uid)) throw new Error(macOSBetaReminderTr("Local task identity conflict."));
      ids.add(candidate.id); uids.add(candidate.uid);
      let normalized;
      try {
        // Never put existing records through mergeAufgaben or normalisiere.
        const isolated = normalisiere({ aufgaben: [candidate], einstellungen: kopie(book.einstellungen) });
        if (isolated.aufgaben.length === 1 && !isolated.jahrestage.length) normalized = isolated.aufgaben[0];
      } catch (_) { /* A canonical field loss is a visible per-record exclusion. */ }
      if (!normalized || Object.keys(candidate).some(name => kanonischerEntwurf(normalized[name]) !== kanonischerEntwurf(candidate[name]))) {
        excluded.push({ identifier: item.identifier, title: item.title, reasons: ["canonical-reminder-content-would-change"] }); continue;
      }
      normalized.reihenfolge = rootCount + candidates.length;
      candidates.push(normalized); preview.push(macOSBetaReminderPreview(normalized, item));
    }
    macOSBetaReminderGraph(book, candidates);
    if (DATEN !== book || JSON.stringify(book) !== content || eigeneIanaZeitzone() !== displayZone || macOSBetaReminderBlocked() || macOSBetaReminderHasDraft())
      throw new Error(macOSBetaReminderTr("The document changed while preparing Reminders copies."));
    const token = anrufClientRef();
    macOSBetaReminderProposal = { token, book, content, candidates, displayZone,
      expires: Date.now() + 5 * 60000, monotonicExpires: performance.now() + 5 * 60000, state: "prepared" };
    return kopie({ ok: true, token, source, displayTimeZone: displayZone, snapshotRevision: value.snapshotRevision,
      newCount: candidates.length, existingCount, changedCount, changedPreview, excluded, targetTitle: macOSBetaReminderTr("Tasks"), preview });
  }
  function macOSBetaReminderRequireCurrent(proposal) {
    if (macOSBetaReminderProposal !== proposal || macOSBetaReminderBlocked() || macOSBetaReminderHasDraft() ||
        macOSBetaReminderExpired(proposal) || DATEN !== proposal.book || JSON.stringify(DATEN) !== proposal.content || eigeneIanaZeitzone() !== proposal.displayZone)
      throw new Error(macOSBetaReminderTr("The Reminders copy review is stale. Open it again."));
    const index = macOSBetaReminderIndex(DATEN), ids = new Set(DATEN.aufgaben.map(task => task.id)), uids = new Set(DATEN.aufgaben.map(task => task.uid));
    for (const candidate of proposal.candidates) {
      if (ids.has(candidate.id) || uids.has(candidate.uid) || macOSBetaReminderClassification(candidate, index) !== "new")
        throw new Error(macOSBetaReminderTr("The Reminders copy identity changed. Open it again."));
      ids.add(candidate.id); uids.add(candidate.uid);
    }
    macOSBetaReminderGraph(DATEN, proposal.candidates);
  }
  function macOSBetaCommitReminderImport(token) {
    return new Promise((resolve, reject) => {
      const proposal = macOSBetaReminderProposal;
      let ownsProposal = false, appended = false, saveConfirmed = false;
      const failed = (error, saveRejected = false) => {
        if (appended && !saveConfirmed) {
          const prefix = saveRejected
            ? macOSBetaReminderTr("Imported tasks remain unsaved. Save the pending changes before importing again.")
            : macOSBetaReminderTr("Task copies were added, but saving was not confirmed. Check and save the pending changes before importing again.");
          const detail = String(error?.message || error);
          if (!detail.startsWith(prefix)) error = new Error(prefix + " " + detail);
        }
        if (ownsProposal && macOSBetaReminderProposal === proposal) macOSBetaReminderProposal = null;
        reject(error);
      };
      try {
        if (!proposal || proposal.token !== token || proposal.state !== "prepared")
          throw new Error(macOSBetaReminderTr("Invalid or already used Reminders copy review."));
        ownsProposal = true; macOSBetaReminderRequireCurrent(proposal);
        if (!proposal.candidates.length) {
          macOSBetaReminderProposal = null; resolve({ ok: true, count: 0, ids: [] }); return;
        }
        proposal.state = "checkpoint";
        mitMutationsSnapshot("pre-system-reminder-copy", () => {
          try {
            macOSBetaReminderRequireCurrent(proposal); proposal.state = "saving";
            proposal.book.aufgaben.push(...proposal.candidates);
            appended = true;
            planeSpeichern(); zeichneAlles();
            nachDauerhaftemSpeichern(() => {
              saveConfirmed = true;
              if (DATEN !== proposal.book || macOSBetaReminderBlocked() ||
                  proposal.candidates.some(task => !DATEN.aufgaben.includes(task))) {
                failed(new Error(macOSBetaReminderTr("The document changed before the Reminders copy save completed."))); return;
              }
              if (macOSBetaReminderProposal === proposal) macOSBetaReminderProposal = null;
              resolve({ ok: true, count: proposal.candidates.length, ids: proposal.candidates.map(task => task.id) });
            }, error => failed(error, true));
          } catch (error) { failed(error); }
        }, failed);
      } catch (error) { failed(error); }
    });
  }
  function macOSBetaCancelReminderImport(token) {
    const proposal = macOSBetaReminderProposal;
    if (!proposal || proposal.token !== token || proposal.state === "saving") return { ok: true, cancelled: false };
    macOSBetaReminderProposal = null; return { ok: true, cancelled: true };
  }
