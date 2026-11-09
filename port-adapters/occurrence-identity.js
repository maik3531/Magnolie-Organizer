  // #464: display equality never identifies a distinct original ICS instance.
  // This gate only permits the existing deduplication; it never rewrites data.
  function portTerminOccurrenceCompatible(left, right) {
    // The sole caller is normalisiereTermine: it constructs fresh records for
    // each pass. Compatible folds cannot change their UID/RID raw lines below.
    const cache = portTerminOccurrenceCompatible.cache ||= new WeakMap();
    if (cache.has(left) && cache.has(right)) {
      const a = cache.get(left), b = cache.get(right);
      return a !== null && b !== null && a === b;
    }
    const property = line => {
      if (typeof line !== "string" || /[\r\n\0]/.test(line)) return null;
      const parts = []; let quoted = false, start = 0;
      for (let index = 0; index < line.length; index++) {
        const char = line[index];
        if (char === '"') quoted = !quoted;
        if (!quoted && (char === ";" || char === ":")) {
          parts.push(line.slice(start, index)); start = index + 1;
          if (char !== ":") continue;
          const name = parts.shift();
          if (!/^[A-Za-z0-9-]+$/.test(name)) return null;
          const params = new Map();
          for (const part of parts) {
            const equals = part.indexOf("="), spelling = part.slice(0, equals), key = spelling.toUpperCase();
            if (equals < 1 || !/^[A-Za-z0-9-]+$/.test(spelling) || params.has(key)) return null;
            let value = part.slice(equals + 1);
            if (!value || value.startsWith('"') !== value.endsWith('"')) return null;
            if (value.startsWith('"')) value = value.slice(1, -1);
            if (!value || value.includes('"')) return null;
            params.set(key, value);
          }
          return { name: name.toUpperCase(), params, value: line.slice(start), line };
        }
      }
      return null;
    };
    const text = value => {
      let result = "";
      for (let index = 0; index < value.length; index++) {
        if (value[index] !== "\\") { result += value[index]; continue; }
        const next = value[++index];
        if (next === "n" || next === "N") result += "\n";
        else if (next === "\\" || next === "," || next === ";") result += next;
        else return null;
      }
      return result;
    };
    const identity = record => {
      const raw = record.icsRoundtrip || [], metadata = record.icsSerienUid || "";
      if (!Array.isArray(raw)) return null;
      if (!raw.length) return metadata ? null : "plain";
      const source = record.icsQuelleId || record.syncKalenderUid || record.kalenderQuelle?.id || "";
      if (typeof source !== "string" || !source) return null;
      const stack = [], uids = [], rids = [];
      for (const line of raw) {
        const p = property(line); if (!p) return null;
        if (p.name === "BEGIN") {
          if (stack.length || p.params.size || !/^[A-Za-z]+$/.test(p.value) || p.value.toUpperCase() !== "VALARM") return null;
          stack.push("VALARM");
        } else if (p.name === "END") {
          if (p.params.size || !/^[A-Za-z]+$/.test(p.value) || stack.pop() !== p.value.toUpperCase()) return null;
        } else if (p.name === "UID" || p.name === "RECURRENCE-ID") {
          if (stack.length) return null; // UID/RID inside an alarm is not an event identity.
          (p.name === "UID" ? uids : rids).push(p);
        }
      }
      if (stack.length || uids.length > 1 || rids.length > 1) return null;
      const rawUID = uids.length ? text(uids[0].value) : "";
      if (rawUID === null || uids.length && (!rawUID || uids[0].params.size) || typeof metadata !== "string" ||
          rawUID && metadata && rawUID !== metadata) return null;
      // A detached local UID is an opaque local alias, never a guessed wire UID.
      const wireUID = rawUID || metadata || (!rids.length ? record.uid : "");
      if (typeof wireUID !== "string" || !wireUID) return null;
      if (!rids.length) {
        if (!uids.length && metadata && record.uid !== metadata) return null;
        return JSON.stringify([source, wireUID, "master", uids[0]?.line || ""]);
      }
      const rid = rids[0];
      const valueType = rid.params.get("VALUE") || (/^[0-9]{8}$/.test(rid.value) ? "DATE" : "DATE-TIME");
      if (!/^[A-Za-z-]+$/.test(valueType)) return null;
      if (valueType.toUpperCase() === "DATE") {
        if (!/^[0-9]{8}$/.test(rid.value) || rid.params.has("TZID")) return null;
      } else if (valueType.toUpperCase() !== "DATE-TIME" || !/^[0-9]{8}T[0-9]{6}Z?$/.test(rid.value) ||
                 rid.value.endsWith("Z") && rid.params.has("TZID")) return null;
      if (rid.params.has("RANGE") && (!/^[A-Za-z]+$/.test(rid.params.get("RANGE")) || rid.params.get("RANGE").toUpperCase() !== "THISANDFUTURE")) return null;
      // Include every original parameter/value. No Unicode normalization, TZID
      // uppercasing, date projection or replacement-DTSTART heuristic is allowed.
      // Even equivalent spellings stay separate: the existing raw-line union
      // must never create two RID/UID properties from differently spelled lines.
      return JSON.stringify([source, wireUID, "detached", uids[0]?.line || "", rid.line]);
    };
    const cached = record => {
      if (!cache.has(record)) cache.set(record, identity(record));
      return cache.get(record);
    };
    const a = cached(left), b = cached(right);
    return a !== null && b !== null && a === b;
  }
