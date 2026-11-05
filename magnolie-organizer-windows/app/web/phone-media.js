/* Native media UI: opaque choices only, no browser paths, grants or Saved proofs. */
(() => {
  "use strict";
  const pending = new Map();
  function createPanel(peerId, translate, send, saveBefore) {
    const t = translate, root = document.createElement("details");
    root.className = "telefon-medien einst-gruppe"; root.hidden = true;
    const node = (tag, text) => { const e = document.createElement(tag); if (text) e.textContent = t(text); return e; };
    const advanced = node("details"); advanced.className = "telefon-erweitert telefon-freigaben einst-gruppe";
    advanced.hidden = true; advanced.open = false;
    advanced.append(node("summary", "Advanced functions"), root);
    const title = node("summary", "Photos and videos"), status = node("p", "Waiting for native media status");
    status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const note = node("p", "Only synchronize the phone inventory. Local edits are preserved. Deletions are not synchronized yet.");
    note.className = "einst-hinweis";
    const rightsArea = node("section"), settingsArea = node("section"), manualArea = node("section");
    for (const area of [rightsArea, settingsArea, manualArea]) area.className = "telefon-medien-gruppe";
    rightsArea.append(node("h4", "Access rights"));
    settingsArea.append(node("h4", "Synchronization settings"), note);
    manualArea.append(node("h4", "Manual synchronization"));
    root.append(title, status, rightsArea, settingsArea, manualArea);
    const masterRow = node("label"), master = node("input"); master.type = "checkbox"; master.dataset.media = "enabled";
    masterRow.className = "hak"; masterRow.hidden = true;
    masterRow.append(master, document.createTextNode(" " + t("Enable photo and video synchronization")));
    root.insertBefore(masterRow, status);
    const receiveRow = node("label"), receiveConsent = node("input"); receiveConsent.type = "checkbox"; receiveConsent.dataset.media = "receive_consent";
    receiveRow.className = "hak"; receiveRow.hidden = true;
    receiveRow.append(receiveConsent, document.createTextNode(" Organizer – " + t("Receive files"))); rightsArea.append(receiveRow);
    const check = (text, key) => {
      const label = node("label"), input = node("input"); input.type = "checkbox"; input.dataset.media = key;
      label.className = "hak"; label.append(input, document.createTextNode(" " + t(text))); settingsArea.append(label); return input;
    };
    const photos = check("Synchronize photos", "photos"), videos = check("Synchronize videos", "videos"), skip = check("Skip deletions", "skip_deletions");
    const automatic = node("select"); automatic.className = "feld"; automatic.dataset.media = "automatic";
    automatic.setAttribute("aria-label", t("Synchronization"));
    for (const [value, text] of [["manual", "Manual synchronization"], ["wifi", "Automatically synchronize over Wi-Fi"]]) {
      const option = node("option", text); option.value = value; automatic.append(option);
    }
    const modeRow = node("label", "Synchronization"); modeRow.className = "formzeile"; modeRow.append(automatic); settingsArea.append(modeRow);
    const select = (key, label, choices) => {
      const row = node("label", label), input = node("select"); input.className = "feld"; input.dataset.media = key;
      input.setAttribute("aria-label", t(label)); row.className = "formzeile";
      for (const [value, text] of choices) { const option = node("option", text); option.value = value; input.append(option); }
      row.append(input); row.hidden = true; settingsArea.append(row); return input;
    };
    const scope = select("collection_mode", "Scope", [["phone_inventory", "Only the phone inventory"], ["entire_collection", "Entire collection"]]);
    const direction = select("direction", "Direction", [["phone_to_pc", "Phone → PC"], ["two_way", "Two-way synchronization"]]);
    settingsArea.append(scope.parentElement, modeRow, skip.parentElement, direction.parentElement, photos.parentElement, videos.parentElement);
    const mode = node("p", "Manual synchronization"), destinations = node("div"), controls = node("div"), albumList = node("div"), review = node("ul");
    settingsArea.append(mode, destinations); manualArea.append(controls, albumList, review);
    const trashArea = node("details"), trashRows = node("ul"); trashArea.append(node("summary", "Media recycle bin"),
      node("p", "Media files use the saved recycle-bin retention period. Never means manual removal only. Restoring never replaces an existing file."), trashRows);
    settingsArea.append(trashArea);
    let nextTrash = null;
    let native = null, busy = false, transfer = false, catalog = null, kind = "images", selectedAlbum = null;
    let requestSequence = 0, appliedSettingsSequence = 0;
    const settingsActions = new Set(["status", "mode", "settings", "pick_destination", "shared_setting", "receive_consent"]);
    const allButtons = [], actions = [], rightActions = []; let refresh, manualSync;
    const albumChoice = node("select"); albumChoice.className = "feld"; albumChoice.hidden = true;
    albumChoice.setAttribute("aria-label", t("Phone album")); albumList.append(albumChoice);
    albumChoice.addEventListener("change", () => { selectedAlbum = albumChoice.value || null; toggle(); });
    const button = (text, action, parent = controls) => {
      const b = node("button", text); b.type = "button"; b.className = "knopf klein" + (text === "Delete permanently" ? " rot" : ""); b.addEventListener("click", action); parent.append(b); allButtons.push(b); return b;
    };
    const toggle = () => {
      const shared = !!native?.shared_settings, enabled = !shared || master.checked;
      const runtimeReady = !shared || native.shared_runtime_ready === true;
      masterRow.hidden = receiveRow.hidden = scope.parentElement.hidden = direction.parentElement.hidden = !shared;
      master.disabled = !native;
      receiveConsent.disabled = !enabled || (busy && !receiveConsent.checked);
      scope.disabled = direction.disabled = busy || !enabled;
      for (let i = allButtons.length - 1; i >= 0; i--) if (!root.contains(allButtons[i])) allButtons.splice(i, 1);
      for (const b of allButtons) b.disabled = busy;
      photos.disabled = videos.disabled = skip.disabled = busy || !native || !enabled;
      automatic.disabled = !native || !enabled || native.automatic_ready !== true;
      for (const entry of actions) entry.button.disabled = busy || !enabled || !runtimeReady || native?.metadata_ready?.[entry.mediaType] !== true || !(entry.mediaType === "video" ? videos.checked : photos.checked) || !native?.[entry.key];
      stop.disabled = !transfer;
      if (refresh) refresh.disabled = false;
      albumChoice.disabled = busy || !catalog;
      if (manualSync) manualSync.disabled = busy || !enabled || !runtimeReady || !selectedAlbum || !catalog || native?.metadata_ready?.[kind] !== true;
      for (const entry of rightActions) {
        entry.row.hidden = native?.metadata_ready?.[entry.mediaType] !== true;
        entry.button.disabled = busy || !enabled || !runtimeReady || !(entry.mediaType === "video" ? videos.checked : photos.checked);
      }
      for (const b of destinations.querySelectorAll("button")) b.disabled = busy || !enabled || (shared && !receiveConsent.checked);
    };
    const request = async (action, data = {}, save = true) => {
      if (save) {
        try { await saveBefore(); } catch { restoreSharedInputs(); toggle(); status.textContent = t("The book could not be saved. Media synchronization was not started."); return; }
      }
      const now = Date.now();
      for (const [id, item] of pending) if (item.until < now || !item.root.isConnected) pending.delete(id);
      if (pending.size >= 128) { status.textContent = t("Too many pending requests. Wait for the current operation."); return; }
      const requestId = crypto.randomUUID(), message = { cmd: "telefon_medien", requestId, device_id: peerId, action, ...data };
      const sequence = ++requestSequence;
      const item = { root, peerId, action, receive: (reply, action) => receive(reply, action, sequence), until: now + 60000 };
      pending.set(requestId, item);
      if (action !== "status" && action !== "cancel") busy = true;
      if (action === "sync") { transfer = true; status.textContent = t("Waiting for native media status"); }
      if (action === "sync" || action === "discover") review.replaceChildren();
      toggle();
      if (!send(message)) { pending.delete(requestId); busy = false; if (action === "sync") transfer = false; restoreSharedInputs(); toggle(); status.textContent = t("Native media connection is unavailable."); }
    };
    const settings = () => {
      if (skip.indeterminate) {
        photos.checked = !!native?.photos; videos.checked = !!native?.videos;
        status.textContent = t("Skip deletions") + "?"; skip.focus(); return;
      }
      return request("settings", { version: native.version ?? null, photos: photos.checked, videos: videos.checked, skip_deletions: skip.checked });
    };
    const sharedSetting = (field, value) => request("shared_setting", { field, value, version: native.shared_settings.versions[field] });
    const restoreSharedInputs = () => {
      const values = native?.shared_settings?.values;
      if (!values) return;
      master.checked = values.enabled === true; photos.checked = values.photos_enabled === true;
      videos.checked = values.videos_enabled === true; skip.checked = values.skip_deletions === true;
      automatic.value = values.auto_mode; scope.value = values.collection_mode; direction.value = values.direction;
      receiveConsent.checked = native.receive_consent?.granted === true;
    };
    master.addEventListener("change", () => sharedSetting("enabled", master.checked));
    receiveConsent.addEventListener("change", () => request("receive_consent", { granted: receiveConsent.checked, version: native.receive_consent.version }));
    for (const [input, field] of [[photos, "photos_enabled"], [videos, "videos_enabled"], [skip, "skip_deletions"]])
      input.addEventListener("change", () => native?.shared_settings ? sharedSetting(field, input.checked) : settings());
    automatic.addEventListener("change", () => native?.shared_settings ? sharedSetting("auto_mode", automatic.value) : request("mode", { version: native.version ?? null, automatic: automatic.value === "wifi" }));
    scope.addEventListener("change", () => sharedSetting("collection_mode", scope.value));
    direction.addEventListener("change", () => sharedSetting("direction", direction.value));
    const kinds = [["images", "Photos", "pictures"], ["video", "Videos", "video_destination"]];
    for (const [mediaType, label, key] of kinds) {
      const row = node("div"), path = node("p", "No destination selected"); path.dataset.destination = mediaType;
      row.append(node("strong", label), path); destinations.append(row);
      button("Choose another folder…", () => request("pick_destination", { media_type: mediaType, version: native?.[key]?.version ?? null }), row);
      const rights = node("div"); rights.append(node("strong", label)); rightsArea.append(rights);
      const read = button("Request access on phone", () => request("request_read", { media_type: mediaType, version: null }), rights);
      rightActions.push({ row: rights, button: read, mediaType });
      const discover = button(label === "Photos" ? "Read photo albums" : "Read video albums", () => {
        kind = mediaType; catalog = null; selectedAlbum = null; albumChoice.replaceChildren(); albumChoice.hidden = true; request("discover", { media_type: mediaType });
      });
      actions.push({ button: discover, mediaType, key });
    }
    const more = button("More albums", () => catalog && request("page", { media_type: kind, version: catalog.version, catalog_id: catalog.id, after: catalog.next }));
    more.hidden = true;
    const stop = button("Stop", () => request("cancel", {}, false));
    refresh = button("Refresh", () => request("status", {}, false));
    button("Read media recycle bin", () => request("trash_list", { after: 0 }), trashArea);
    const moreTrash = button("Next entries", () => Number.isSafeInteger(nextTrash) && request("trash_list", { after: nextTrash }), trashArea); moreTrash.hidden = true;
    const activate = button("Enable", () => request("activate"), root); activate.hidden = true;
    manualSync = button("Synchronize now", () => selectedAlbum && catalog && request("sync", {
      media_type: kind, version: catalog.version, catalog_id: catalog.id, album_id: selectedAlbum }), manualArea);
    function receive(reply, action, sequence) {
      if (settingsActions.has(action)) {
        if (sequence < appliedSettingsSequence) return;
        appliedSettingsSequence = sequence;
      }
      if (action === "activate" && reply.supported !== false) {
        busy = false; activate.disabled = false;
        if (reply.canceled) return;
        if (!reply.ok) { status.textContent = t("Media operation paused. No completion was confirmed."); return; }
      }
      if (reply.supported === false) {
        advanced.hidden = root.hidden = true; native = null; busy = transfer = false; catalog = null;
        albumChoice.replaceChildren(); albumChoice.hidden = true; selectedAlbum = null; review.replaceChildren(); trashRows.replaceChildren(); nextTrash = null;
        more.hidden = moreTrash.hidden = true; toggle(); return;
      }
      if (!native && reply.supported !== true && action !== "status") return;
      if (!native && !reply.ok) return;
      advanced.hidden = root.hidden = false;
      if (reply.activation_required === true) {
        // A compatible legacy pairing exposes only explicit activation, never
        // transfers, paths or stored permission defaults before initialization.
        for (const child of root.children) child.hidden = child !== title && child !== status && child !== activate;
        activate.hidden = false; activate.disabled = false; busy = false;
        status.textContent = t("Waiting for native media status"); return;
      }
      for (const child of root.children) child.hidden = false;
      activate.hidden = true;
      if (reply.state === "running" || reply.state === "stopping") {
        busy = true; toggle(); status.textContent = t(reply.state === "stopping" ? "Stopping… Waiting for the native operation to end." : "Comparing media content… The total is not known yet."); return;
      }
      busy = false;
      if (action === "sync" || reply.state === "idle") transfer = false;
      if (!reply.ok) {
        restoreSharedInputs();
        status.textContent = t(reply.state === "partial" ? "Stopped or incomplete. Original files and recovery history are retained." : "Media operation paused. No completion was confirmed.") + (reply.error ? " · " + String(reply.error) : "");
        toggle();
        if (native?.shared_settings && ["shared_setting", "receive_consent"].includes(action)) request("status", {}, false);
        return;
      }
      if (reply.canceled) { restoreSharedInputs(); toggle(); return; }
      if (action === "trash_list") {
        trashRows.replaceChildren();
        nextTrash = reply.next_cursor; moreTrash.hidden = !Number.isSafeInteger(nextTrash);
        for (const item of (reply.trash || []).slice(0, 128)) {
          const row = node("li"); row.append(document.createTextNode(String(item.display_name || "") + " · " + t(item.media_type === "video" ? "Videos" : "Photos")));
          trashRows.append(row);
          const data = { operation_id: item.operation_id, version: item.version };
          if (["prepared", "trashed", "restore_prepared"].includes(item.state))
            button(item.state === "prepared" ? "Recover operation" : "Restore", () => request("trash_restore", data), row);
          if (["trashed", "purge_prepared"].includes(item.state))
            button("Delete permanently", () => request("trash_purge", data), row);
        }
        status.textContent = t(trashRows.children.length ? "Media recycle bin loaded. Permanent removal requires native confirmation." : "No retained media entries on this page.");
        toggle(); return;
      }
      if (action === "trash_restore" || action === "trash_purge") {
        trashRows.replaceChildren(); nextTrash = null; moreTrash.hidden = true;
        status.textContent = t("Media recycle-bin operation finished. Read the entries again before another operation.");
        toggle(); return;
      }
      if (settingsActions.has(action)) {
        native = reply; photos.checked = !!reply.photos; videos.checked = !!reply.videos;
        const shared = reply.shared_settings?.values;
        master.checked = shared?.enabled === true;
        receiveConsent.checked = reply.receive_consent?.granted === true;
        if (shared) {
          photos.checked = shared.photos_enabled === true; videos.checked = shared.videos_enabled === true;
          scope.value = shared.collection_mode; direction.value = shared.direction;
        }
        const videoAvailable = reply.metadata_ready?.video === true;
        videos.parentElement.hidden = !videoAvailable;
        destinations.querySelector('[data-destination="video"]').parentElement.hidden = !videoAvailable;
        actions.find(entry => entry.mediaType === "video").button.hidden = !videoAvailable;
        title.textContent = t(videoAvailable ? "Photos and videos" : "Photos");
        busy = !!reply.busy || !!reply.transfer_busy || !!reply.automatic_busy;
        transfer = !!reply.transfer_busy || !!reply.automatic_busy;
        automatic.value = shared?.auto_mode ?? (reply.automatic ? "wifi" : "manual"); automatic.parentElement.hidden = reply.automatic_ready !== true;
        skip.indeterminate = !shared && reply.skip_deletions === null; skip.checked = shared ? shared.skip_deletions === true : reply.skip_deletions !== false;
        mode.textContent = t(automatic.value === "wifi" ? "Automatically synchronize over Wi-Fi" : "Manual synchronization");
        for (const [mediaType, , key] of kinds) destinations.querySelector(`[data-destination="${mediaType}"]`).textContent = reply[key]?.display_path || t("No destination selected");
        status.textContent = t(busy ? "A native media operation is still running." : reply.metadata_ready?.images !== true
          ? "Media transfer is not available on this connection yet." : "Native settings loaded. No transfer has been started.");
        if (shared && reply.shared_runtime_ready !== true && shared.enabled)
          status.textContent = t("Media transfer is not available on this connection yet.");
        if (!busy && reply.automatic) {
          if (reply.automatic_phase === "paused") status.textContent = t("Automatic synchronization is paused. Switch to manual mode and enable it again to resume.");
          else if (["review", "held", "partial"].includes(reply.automatic_phase)) status.textContent = t("Automatic content comparison needs attention. No deletion completion was confirmed.");
          else if (reply.automatic_phase === "content_pass") status.textContent = t("Automatic pass checked one album per media type. Further albums follow; deletions remain pending.");
        }
      } else if (action === "discover" || action === "page") {
        if (action === "discover") {
          albumChoice.replaceChildren(); selectedAlbum = null;
          const empty = node("option", "Phone album"); empty.value = ""; albumChoice.append(empty);
          catalog = { version: reply.version, id: reply.catalog_id, next: reply.next_cursor };
        }
        if (!catalog || catalog.id !== reply.catalog_id || catalog.version !== reply.version) { status.textContent = t("Album selection changed. Read the albums again."); toggle(); return; }
        catalog.next = reply.next_cursor; more.hidden = !Number.isSafeInteger(catalog.next);
        for (const album of reply.albums || []) {
          const option = node("option"); option.value = String(album.album_id); option.textContent = String(album.display_name || "Album"); albumChoice.append(option);
        }
        albumChoice.hidden = albumChoice.options.length < 2;
        status.textContent = t("Choose an album to compare. An incomplete catalog never proves deletion.") + " · " + String(reply.coverage || "");
      } else if (action === "request_read") {
        status.textContent = t("Check the access request on your phone, then read the albums again.");
      } else if (action === "cancel" && reply.state === "idle") {
        status.textContent = t("No active media operation.");
      } else if (action === "sync") {
        review.replaceChildren();
        status.textContent = t(reply.state === "review" ? "Content comparison needs review." : "Content comparison finished.") +
          " " + t("New") + ": " + Number(reply.copied || 0) + " · " + t("Replaced") + ": " + Number(reply.replaced || 0) +
          " · " + t("Unchanged") + ": " + Number(reply.unchanged || 0) + " · " + t("Local edits kept") + ": " + Number(reply.kept_edits || 0) +
          " · " + t("Deletions are not synchronized yet.");
        for (const entry of reply.review || []) review.append(node("li", ""));
        [...review.children].forEach((item, index) => { item.textContent = String(reply.review[index].name) + " · " + String(reply.review[index].reason); });
        if (reply.coverage_uncertain) review.append(node("li", "Some source entries may not have been offered. Read the albums again."));
      }
      toggle();
    }
    request("status", {}, false);
    return advanced;
  }
  function createBackupPanel(peerId, mediaType, translate, send, saveBefore) {
    const t = translate, root = document.createElement("details"), title = document.createElement("summary"), rows = document.createElement("ul"), status = document.createElement("p");
    root.hidden = true; root.className = "telefon-medien-sicherungen einst-gruppe";
    title.textContent = t("Backups") + " · " + t(mediaType === "video" ? "Videos" : "Photos");
    status.setAttribute("role", "status"); root.append(title, rows, status);
    let busy = false, next = null;
    const button = (label, action, parent) => {
      const b = document.createElement("button"); b.type = "button"; b.className = "knopf klein"; b.textContent = t(label); b.addEventListener("click", action); parent.append(b); return b;
    };
    function toggle() { for (const b of root.querySelectorAll("button")) b.disabled = busy; }
    async function request(action, data = {}) {
      if (busy) return;
      if (action === "backup_restore") {
        try { await saveBefore(); } catch { status.textContent = t("The book could not be saved. Media synchronization was not started."); return; }
      }
      const requestId = crypto.randomUUID(); busy = true; toggle();
      pending.set(requestId, { root, peerId, action, receive, until: Date.now() + 60000 });
      if (!send({ cmd: "telefon_medien", requestId, device_id: peerId, media_type: mediaType, action, ...data })) {
        pending.delete(requestId); busy = false; toggle();
      }
    }
    function receive(reply, action) {
      busy = false;
      if (!reply.ok) { status.textContent = t("Media operation paused. No completion was confirmed."); toggle(); return; }
      if (reply.canceled) { toggle(); return; }
      if (action === "backup_list") {
        rows.replaceChildren(); next = reply.next_cursor;
        more.hidden = !Number.isSafeInteger(next);
        for (const item of (reply.backups || []).slice(0, 128)) {
          const row = document.createElement("li"); row.append(document.createTextNode(String(item.display_name || "") + " · " + new Date(item.saved_ms).toLocaleString()));
          button("Restore", () => request("backup_restore", { backup_id: item.backup_id, version: item.version }), row); rows.append(row);
        }
        root.hidden = rows.children.length === 0; status.textContent = "";
      } else if (action === "backup_restore") {
        status.textContent = t("Restore") + ": " + String(reply.display_name || "");
      }
      toggle();
    }
    button("Refresh", () => request("backup_list", { after: 0 }), root);
    const more = button("Next entries", () => Number.isSafeInteger(next) && request("backup_list", { after: next }), root); more.hidden = true;
    // Read-only existing local history, even while the phone is disconnected.
    request("backup_list", { after: 0 }); return root;
  }
  window.MagnolieMedia = {
    createPanel,
    createBackupPanel,
    receive(reply) {
      if (!reply || typeof reply.requestId !== "string") return;
      const item = pending.get(reply.requestId);
      if (!item || reply.device_id !== item.peerId || !item.root.isConnected || item.until < Date.now()) return;
      if (reply.state === "running") item.until = Date.now() + 2 * 60 * 60 * 1000;
      else pending.delete(reply.requestId);
      item.receive(reply, item.action);
    }
  };
})();
