"use strict";

// macOS discovery and source selection only. Shared Organizer settings remain
// the sole stored selection; discovering/denying access never rewrites them.
(() => {
  let view = null, snapshot = null, pending = null;
  const note = "macOS system sources can be discovered and selected. Full synchronization is not available yet. Selecting a source does not import or change its data.";
  function node(tag, text) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function request(art) {
    if (!view?.root.isConnected || pending) return;
    const requestId = view.id();
    pending = requestId;
    draw();
    const message = art ? { cmd: "macos_systemzugriff", art, requestId } : { cmd: "eds_status", requestId };
    if (!view.send(message)) update({ requestId, fehler: "The macOS source request could not be sent.", ok: false });
  }
  function draw() {
    if (!view?.root.isConnected) return;
    const { root, tr, settings, change } = view;
    root.textContent = "";
    root.append(node("h3", tr("System internet accounts")), node("p", note));
    const state = node("p", snapshot?.fehler || (pending ? tr("Loading …") : ""));
    state.id = "macos-system-status"; state.setAttribute("role", "status"); root.append(state);
    const permissions = snapshot?.permissions || {};
    for (const [art, label] of [["events", "Calendars"], ["reminders", "Tasks"], ["contacts", "Contacts"]]) {
      const row = node("p");
      row.append(node("span", `${tr(label)}: ${permissions[art] || "not_determined"} `));
      const button = node("button", `${tr("Allow access")}: ${tr(label)}`);
      button.type = "button"; button.dataset.systemAccess = art;
      button.disabled = !!pending || permissions[art] === "authorized";
      button.addEventListener("click", () => request(art)); row.append(button); root.append(row);
    }
    const refresh = node("button", tr("Refresh")); refresh.type = "button";
    refresh.id = "macos-system-refresh"; refresh.disabled = !!pending;
    refresh.addEventListener("click", () => request()); root.append(refresh);
    const chosen = settings();
    const selected = [...new Set([...(chosen.kalenderUids || []), ...(chosen.kalenderUid ? [chosen.kalenderUid] : [])])];
    const calendars = Array.isArray(snapshot?.kalender) ? snapshot.kalender : [];
    const known = new Set(calendars.map(item => item.uid));
    const all = [...calendars, ...selected.filter(uid => !known.has(uid)).map(uid => ({ uid, name: `${tr("Unavailable")}: ${uid}` }))];
    const fieldset = node("fieldset"); fieldset.append(node("legend", tr("Calendars (multiple selections allowed)")));
    fieldset.id = "macos-system-calendars";
    for (const source of all) {
      if (typeof source.uid !== "string" || typeof source.name !== "string") continue;
      const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.value = source.uid;
      checkbox.checked = selected.includes(source.uid); checkbox.dataset.calendarUid = source.uid;
      const label = node("label"); label.className = "hak";
      label.append(checkbox, document.createTextNode(` ${source.name}${source.readOnly ? " (read-only)" : ""}`));
      checkbox.addEventListener("change", () => {
        const values = [...fieldset.querySelectorAll("input:checked")].map(item => item.value);
        change({ kalenderUids: values });
      }); fieldset.append(label);
    }
    root.append(fieldset);
    const books = Array.isArray(snapshot?.adressbuecher) ? snapshot.adressbuecher : [];
    const book = node("select"); book.id = "macos-system-addressbook";
    const empty = node("option", tr("— do not link —")); empty.value = ""; book.append(empty);
    const options = [...books];
    if (chosen.adressbuchUid && !books.some(item => item.uid === chosen.adressbuchUid))
      options.push({ uid: chosen.adressbuchUid, name: `${tr("Unavailable")}: ${chosen.adressbuchUid}` });
    for (const source of options) {
      if (typeof source.uid !== "string" || typeof source.name !== "string") continue;
      const option = node("option", source.name); option.value = source.uid; book.append(option);
    }
    book.value = chosen.adressbuchUid || "";
    book.addEventListener("change", () => change({ adressbuchUid: book.value }));
    const label = node("label", tr("Address book") + " "); label.append(book); root.append(label);
    const sync = node("button", tr("Synchronize now")); sync.id = "sync-jetzt"; sync.disabled = true; sync.type = "button";
    root.append(sync);
  }
  function update(value) {
    if (!value || typeof value !== "object") return;
    // Correlated user requests cannot be completed by stale/native MCP replies.
    if (value.requestId && value.requestId !== pending) return;
    if (value.requestId) pending = null;
    snapshot = value;
    draw();
  }
  window.MacBetaSystemAccounts = Object.freeze({
    render(root, options) {
      view = { root, ...options };
      // A page rebuild does not cancel the OS consent dialog or forget its request.
      draw();
      if (!pending) request();
    }, update,
    reset() { view = null; snapshot = null; pending = null; }
  });
})();
