/* Explicit Android copies. Provider data never grants synchronization authority. Refs #791, #799, #800. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TabletSystemImport = factory();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  const MAX_RECORDS = 5000, MAX_BYTES = 4 * 1024 * 1024, MAX_BOOK_BYTES = 16 * 1024 * 1024;
  const contactFields = new Set(['uid','anzeigename','vorname','nachname','firma','telefone','emailEintraege',
    'anschriften','notiz','geburtstag','jubilaeum','geburtstagJahrUnbekannt','androidContactDates','sync']);
  const eventFields = new Set(['uid','titel','notiz','ort','datum','zeit','endDatum','endZeit','icsAnzeigeZeitzone',
    'icsRoundtrip','wiederholung','standardErinnerung','sync','icsEndeFehlt','icsNullDauer']);
  const bytes = value => new TextEncoder().encode(JSON.stringify(value)).length;
  const copy = value => JSON.parse(JSON.stringify(value));
  const require = (value, code) => { if (!value) throw Error(code); };

  function prepare(payload, request, book, api) {
    require(payload && request && book && typeof payload === 'object', 'invalid_result');
    for (const key of ['requestId','session','revision','sourceUid'])
      require(typeof request[key] === 'string' && payload[key] === request[key], 'stale_request');
    require(['contacts','events'].includes(request.art) && payload.kind === request.art, 'invalid_result');
    require(payload.ok === true && payload.complete === true, 'incomplete_result');
    require(payload.scope === (request.art === 'contacts' ? 'source-contacts' : 'calendar-instances-window'), 'invalid_scope');
    require(new RegExp('^android-' + request.art + ':[0-9a-f]{64}$').test(request.sourceUid), 'invalid_source');
    if (request.art === 'events') {
      require(Number.isSafeInteger(request.from) && Number.isSafeInteger(request.to) && request.to > request.from &&
        request.to - request.from <= 368 * 86400000 && payload.from === request.from && payload.to === request.to &&
        payload.dateFrom === request.dateFrom && payload.dateTo === request.dateTo, 'invalid_window');
      const validDate=value=>typeof value==='string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
        Number.isFinite(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
      require(validDate(request.dateFrom) && validDate(request.dateTo), 'invalid_window');
      const start=Date.parse(request.dateFrom+'T00:00:00Z'),end=Date.parse(request.dateTo+'T00:00:00Z')+86400000;
      require(end>start && end-start<=366*86400000 && Math.abs(request.from-start)<=86400000 &&
        Math.abs(request.to-end)<=86400000, 'invalid_window');
    }
    require(Array.isArray(payload.records) && payload.records.length <= MAX_RECORDS && bytes(payload) <= MAX_BYTES, 'record_limit');
    const collection = request.art === 'contacts' ? 'kontakte' : 'termine';
    require(Array.isArray(book[collection]), 'invalid_book');
    const contacts = request.art === 'contacts';
    require(payload.identitySchema === 2, 'invalid_identity');
    // Old experimental copies lack the provider's stable identity. Neither a
    // recycled row ID nor matching names/phone numbers can prove equivalence.
    require(!payload.records.length || !book[collection].some(row =>
      row.androidSystemImport?.kind === request.art && row.androidSystemImport.sourceUid === request.sourceUid &&
      row.androidSystemImport.schema !== 2), 'legacy_identity_conflict');
    const existing = new Set(book[collection].flatMap(row => [row.id, row.uid,
      row.androidSystemImport?.recordId].filter(value => typeof value === 'string' && value)));
    const existingRows = new Map();
    if (contacts) for (const row of book.kontakte) {
      const origin = row.androidSystemImport;
      if (origin?.schema === 2 && origin.kind === 'contacts' && origin.sourceUid === request.sourceUid && origin.rowBinding) {
        const ids = existingRows.get(origin.rowBinding) || new Set();
        ids.add(origin.recordId); existingRows.set(origin.rowBinding, ids);
      }
    }
    const seen = new Set(), seenRows = new Map(), rows = [];
    let skipped = 0;
    for (const record of payload.records) {
      const prefix = request.art === 'contacts' ? 'android-contact:' : 'android-event:';
      require(record && new RegExp('^' + prefix + '[0-9a-f]{64}$').test(record.recordId || ''), 'invalid_identity');
      require(!seen.has(record.recordId), 'duplicate_result'); seen.add(record.recordId);
      const data = record.data;
      require(data && typeof data === 'object' && !Array.isArray(data) && data.uid === record.recordId, 'invalid_record');
      const fields = request.art === 'contacts' ? contactFields : eventFields;
      require(Object.keys(data).every(key => fields.has(key)) && data.sync === false, 'invalid_record');
      require((contacts ? ['source-id','backup-id','device-raw-id'] : ['single-event','recurring-instance'])
        .includes(record.identityKind), 'invalid_identity');
      if (contacts) {
        require(/^android-contact-row:[0-9a-f]{64}$/.test(record.rowBinding || ''), 'invalid_identity');
        require(!seenRows.has(record.rowBinding) || seenRows.get(record.rowBinding) === record.recordId, 'identity_conflict');
        seenRows.set(record.rowBinding, record.recordId);
      }
      // A stable provider identity remains known even when a resync assigns it
      // another local row. Such known copies never overwrite local edits.
      if (existing.has(record.recordId)) { skipped++; continue; }
      if (contacts) {
        const prior = existingRows.get(record.rowBinding);
        require(!prior || [...prior].every(id => id === record.recordId), 'identity_conflict');
      }
      let row = {...copy(data), id:record.recordId, uid:record.recordId, sync:false, syncQuellen:{},
        androidSystemImport:{schema:2,kind:request.art,sourceUid:request.sourceUid,recordId:record.recordId,
          scope:payload.scope,identityKind:record.identityKind,...(contacts ? {rowBinding:record.rowBinding} : {})}};
      if (request.art === 'events') {
        require(Array.isArray(row.icsRoundtrip) && row.icsRoundtrip.length === 2 &&
          row.icsRoundtrip.every(line => typeof line === 'string' && /^(DTSTART|DTEND)(;VALUE=DATE)?:[0-9TZ]+$/.test(line)) &&
          row.icsRoundtrip.filter(line => /^DTSTART[;:]/.test(line)).length === 1 &&
          row.icsRoundtrip.filter(line => /^DTEND[;:]/.test(line)).length === 1 &&
          row.wiederholung?.art === 'none', 'invalid_event');
        // Use the same normative time-zone conversion as the organizer, retaining the original UTC instants.
        if (row.zeit) row = api.projectEvent(row);
      }
      rows.push(row);
    }
    const candidate = api.empty(); candidate.einstellungen=copy(book.einstellungen);candidate[collection] = rows;
    // Linked birthdays are part of the canonical contact state. Derive them with
    // the existing collection present, but never replace/normalize existing rows.
    if(collection==='kontakte') {candidate.kontakte=copy(book.kontakte).concat(rows);candidate.jahrestage=copy(book.jahrestage);}
    const normalizedBook=api.normalize(candidate),newIds=new Set(rows.map(row=>row.id));
    const normalized = normalizedBook[collection].filter(row=>newIds.has(row.id));
    require(Array.isArray(normalized) && normalized.length === rows.length, 'lossy_result');
    normalized.forEach((row, i) => {
      require(row.id === rows[i].id && row.uid === rows[i].uid && row.sync === false &&
        JSON.stringify(row.androidSystemImport) === JSON.stringify(rows[i].androidSystemImport), 'lossy_result');
    });
    const oldAnniversaryIds=new Set(book.jahrestage.map(row=>row.id));
    const anniversaries=collection==='kontakte' ? normalizedBook.jahrestage.filter(row=>!oldAnniversaryIds.has(row.id) && newIds.has(row.kontaktId)) : [];
    const proposed={...copy(book),[collection]:copy(book[collection]).concat(normalized),jahrestage:copy(book.jahrestage).concat(anniversaries)};
    const baseline=api.normalize(copy(book)),reopened=api.normalize(copy(proposed)),again=api.normalize(copy(reopened));
    for(const field of [collection,'jahrestage']) {
      // The shared core can otherwise auto-link an existing, unbound birthday by
      // name and collapse it only on a subsequent reopen. Such ambiguous copies
      // require explicit conflict resolution, never a silent change to old data.
      const oldRows=new Map(baseline[field].map(row=>[row.id,row]));
      const nextRows=new Map(reopened[field].map(row=>[row.id,row]));
      for(const row of book[field]) require(oldRows.has(row.id) && nextRows.has(row.id) &&
        JSON.stringify(oldRows.get(row.id))===JSON.stringify(nextRows.get(row.id)), 'existing_record_conflict');
      require(reopened[field].length===proposed[field].length && again[field].length===reopened[field].length &&
        again[field].every((row,i)=>row.id===reopened[field][i].id), 'unstable_reopen');
    }
    const result = {book, collection, before:JSON.stringify(book[collection]),anniversariesBefore:JSON.stringify(book.jahrestage),
      rows:normalized,anniversaries,added:normalized.length,skipped};
    require(bytes({...book,[collection]:book[collection].concat(normalized),jahrestage:book.jahrestage.concat(anniversaries)}) <= MAX_BOOK_BYTES, 'book_limit');
    return result;
  }
  return Object.freeze({prepare, MAX_RECORDS, MAX_BYTES});
});
