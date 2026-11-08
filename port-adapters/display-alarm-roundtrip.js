  // Shared private-core adapter for macOS/Tablet (Issue #444). Calendar data is
  // never code: original DISPLAY components are matched before any book mutation.
  function portDisplayAlarmLines(termin, vorher, alt) {
    const conflict = () => {
      const error = new Error(_("Conflict") + ": " + _("Unsupported alarm"));
      error.code = "ambiguous-alarm";
      throw error;
    };
    const semantic = alarm => JSON.stringify([alarm.offsetMinuten, alarm.aktion, alarm.related]);
    const previous = vorher || termin;
    let prior = saubereAlarme(previous.alarme === undefined ? icsProjektion(alt).alarme : previous.alarme)
      .filter(alarm => alarm.bearbeitbar);
    const desired = saubereAlarme(termin.alarme === undefined ? icsProjektion(alt).alarme : termin.alarme)
      .filter(alarm => alarm.bearbeitbar);
    if (new Set(prior.map(alarm => alarm.id)).size !== prior.length ||
        new Set(desired.map(alarm => alarm.id)).size !== desired.length) conflict();
    const blocks = [];
    let current = null;
    for (const line of alt) {
      const property = icsEigenschaft(line);
      if (property?.name === "BEGIN" && property.wert.toUpperCase() === "VALARM") {
        if (current) conflict();
        current = [line];
      } else if (current) {
        current.push(line);
        if (property?.name === "END" && property.wert.toUpperCase() === "VALARM") {
          const view = icsProjektion(current).alarme[0];
          if (!view) conflict();
          if (view.bearbeitbar) blocks.push({ lines: current, view });
          current = null;
        }
      }
    }
    if (current) conflict();
    // No previous record means creation/clone. Desired alarms with no raw
    // counterpart are new, not an old active source that must already exist.
    // Every existing raw block must still bind uniquely below; a stale clone
    // therefore cannot silently replace/drop an unmatched opaque component.
    if (!vorher) prior = prior.filter(alarm => blocks.some(block => semantic(block.view) === semantic(alarm)));
    // Raw hash IDs change after edits; the prior UI view intentionally keeps its
    // ID/triggerRaw. Bind desired -> old ID -> UNIQUE old semantic raw component.
    // Canonical projection deduplicates equal alarms, so duplicates cannot be
    // resolved merely by accepting the first matching ID or physical position.
    const binding = new Map(), used = new Set();
    for (const alarm of prior) {
      const matches = blocks.filter(block => semantic(block.view) === semantic(alarm));
      if (!alarm.aktiviert && !matches.length) continue;
      if (!alarm.aktiviert || matches.length !== 1 || used.has(matches[0])) conflict();
      binding.set(alarm.id, matches[0]);
      used.add(matches[0]);
    }
    if (used.size !== blocks.length) conflict();
    const header = line => {
      let quoted = false, start = 0;
      const parts = [];
      for (let index = 0; index < line.length; index++) {
        if (line[index] === '"') quoted = !quoted;
        if (!quoted && (line[index] === ";" || line[index] === ":")) {
          parts.push(line.slice(start, index));
          start = index + 1;
          if (line[index] === ":") return { parts, value: line.slice(start) };
        }
      }
      conflict();
    };
    const patch = (block, alarm) => {
      let triggers = 0, actions = 0;
      const result = block.lines.map(line => {
        const property = icsEigenschaft(line);
        if (property?.name === "ACTION") actions++;
        if (property?.name !== "TRIGGER") return line;
        triggers++;
        const value = header(line);
        if (alarm.related !== block.view.related) {
          const indexes = value.parts.map((part, index) => /^RELATED=/i.test(part) ? index : -1).filter(index => index >= 0);
          if (indexes.length > 1) conflict();
          if (indexes.length) {
            const at = indexes[0];
            value.parts[at] = value.parts[at].slice(0, value.parts[at].indexOf("=") + 1) + alarm.related;
          } else value.parts.push("RELATED=" + alarm.related);
        }
        // Every unrelated parameter retains its exact spelling/quoting/order.
        if (alarm.offsetMinuten !== block.view.offsetMinuten)
          value.value = "-PT" + alarm.offsetMinuten + "M";
        return value.parts.join(";") + ":" + value.value;
      });
      if (triggers !== 1 || actions !== 1) conflict();
      return result;
    };
    const result = [];
    for (const alarm of desired) {
      if (alarm.aktion !== "display") conflict();
      if (!alarm.aktiviert) continue;
      const existing = binding.get(alarm.id);
      if (existing) result.push(...patch(existing, alarm));
      else {
        // Existing source IDs may only disappear through explicit removal;
        // genuinely new form alarms have no entry in the previous view.
        if (prior.some(value => value.id === alarm.id && value.aktiviert)) conflict();
        result.push("BEGIN:VALARM", "TRIGGER;RELATED=" + alarm.related + ":-PT" + alarm.offsetMinuten + "M",
          "ACTION:DISPLAY", "DESCRIPTION:" + icsSicher(termin.titel || "Termin"), "END:VALARM");
      }
    }
    return result;
  }
