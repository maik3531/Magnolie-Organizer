/* Native media UI: opaque choices only, no browser paths, grants or Saved proofs. */
(() => {
  "use strict";
  const pending = new Map();
  const panels = new Map();
  function createPanel(peerId, translate, send, saveBefore, currentContext = () => true) {
    const t = translate, root = document.createElement("details");
    root.className = "telefon-medien einst-gruppe"; root.hidden = true;
    const node = (tag, text) => { const e = document.createElement(tag); if (text) e.textContent = t(text); return e; };
    const advanced = node("details"); advanced.className = "telefon-erweitert telefon-freigaben einst-gruppe";
    advanced.hidden = true; advanced.open = false;
    advanced.append(node("summary", "Advanced functions"), root);
    const title = node("summary"), caption = node("span", "Photos and videos"), status = node("p", "Waiting for native media status");
    title.append(caption);
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
    masterRow.className = "telefon-medien-aktivierung"; masterRow.hidden = true;
    master.setAttribute("aria-label", t("Enable photo and video synchronization"));
    masterRow.title = t("Enable photo and video synchronization");
    masterRow.append(master); title.append(masterRow);
    // Activation is independent from expanding the settings.
    masterRow.addEventListener("click", event => event.stopPropagation());
    masterRow.addEventListener("keydown", event => event.stopPropagation());
    const receiveRow = node("label"), receiveConsent = node("input"); receiveConsent.type = "checkbox"; receiveConsent.dataset.media = "receive_consent";
    receiveRow.className = "hak"; receiveRow.hidden = true;
    receiveRow.append(receiveConsent, document.createTextNode(" Organizer – " + t("Receive files"))); rightsArea.append(receiveRow);
    const sendChoices = new Map();
    for (const [key, label, mediaType] of [["photos", "Photos", "images"], ["videos", "Videos", "video"]]) {
      const row = node("label"), input = node("input"); input.type = "checkbox"; input.dataset.media = "send_" + key;
      row.className = "hak"; row.hidden = true;
      row.append(input, document.createTextNode(" Organizer → " + t("Send") + " · " + t(label))); rightsArea.append(row);
      sendChoices.set(key, { input, row, mediaType });
    }
    const check = (text, key) => {
      const label = node("label"), input = node("input"); input.type = "checkbox"; input.dataset.media = key;
      label.className = "hak"; label.append(input, document.createTextNode(" " + t(text))); settingsArea.append(label); return input;
    };
    const photos = check("Synchronize photos", "photos"), videos = check("Synchronize videos", "videos"),
      photosOnly = check("Photos only", "photos_only"), skip = check("Skip deletions", "skip_deletions");
    photosOnly.parentElement.hidden = true;
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
    const scope = select("collection_mode", "Scope", [["phone_inventory", "Only the phone inventory"], ["entire_collection", "Entire collection"], ["import_only", "Import phone → PC only"]]);
    const direction = select("direction", "Direction", [["phone_to_pc", "Phone → PC"], ["two_way", "Two-way synchronization"], ["pc_to_phone", "PC → phone"]]);
    settingsArea.append(scope.parentElement, modeRow, direction.parentElement, photos.parentElement, videos.parentElement, photosOnly.parentElement, skip.parentElement);
    const mode = node("p", "Manual synchronization"), destinations = node("div"), controls = node("div"), albumList = node("div"), review = node("ul");
    const sourceArea = node("section"), sourceRows = new Map(); sourceArea.hidden = true;
    sourceArea.append(node("h4", "Selected PC source folders"), node("p", "PC source folders are separate from receive destinations."));
    settingsArea.append(mode, destinations, sourceArea); manualArea.append(controls, albumList, review);
    const trashArea = node("details"), trashRows = node("ul"); trashArea.append(node("summary", "Media recycle bin"),
      node("p", "Media files use the saved recycle-bin retention period. Never means manual removal only. Restoring never replaces an existing file."), trashRows);
    settingsArea.append(trashArea);
    let nextTrash = null;
    const trashThumbnails = node("input"), trashThumbnailLabel = node("label", "Preview");
    trashThumbnails.type = "checkbox"; trashThumbnails.dataset.mediaThumbnails = "";
    trashThumbnailLabel.prepend(trashThumbnails); trashArea.insertBefore(trashThumbnailLabel, trashRows);
    const previewStatus = node("p"); previewStatus.setAttribute("role", "status"); trashArea.insertBefore(previewStatus, trashRows);
    const previewRows = new Map(); let thumbnailQueue = [], thumbnailObserver = null, previewDialog = null;
    function closePreview() {
      if (!previewDialog) return;
      previewDialog.querySelectorAll("img").forEach(image => image.removeAttribute("src"));
      previewDialog.remove(); previewDialog = null;
    }
    function clearPreviews() {
      closePreview(); thumbnailObserver?.disconnect(); thumbnailObserver = null; thumbnailQueue = [];
      for (const [id, item] of pending) if (item.root === root && ["trash_thumbnail", "trash_preview"].includes(item.action)) {
        clearTimeout(item.timer); pending.delete(id);
      }
      trashRows.querySelectorAll("img").forEach(image => { image.removeAttribute("src"); image.remove(); });
      previewRows.clear();
    }
    function pumpThumbnails() {
      if (!trashThumbnails.checked || busy || previewDialog || !root.isConnected || !trashArea.open) return;
      while (thumbnailQueue.length) {
        const entry = thumbnailQueue.shift();
        if (!entry.row.isConnected || entry.loaded) continue;
        entry.loaded = true;
        request("trash_thumbnail", entry.data, false); break;
      }
    }
    function observeThumbnails() {
      thumbnailObserver?.disconnect(); thumbnailObserver = null;
      if (!trashThumbnails.checked || typeof IntersectionObserver !== "function") return;
      thumbnailObserver = new IntersectionObserver(items => {
        for (const item of items) {
          const entry = previewRows.get(item.target.dataset.mediaOperation);
          if (item.isIntersecting && entry && !entry.queued && !entry.loaded) { entry.queued = true; thumbnailQueue.push(entry); }
        }
        pumpThumbnails();
      });
      for (const entry of previewRows.values()) thumbnailObserver.observe(entry.row);
    }
    trashThumbnails.addEventListener("change", () => {
      if (!trashThumbnails.checked) {
        thumbnailQueue = []; thumbnailObserver?.disconnect();
        for (const entry of previewRows.values()) { entry.loaded = entry.queued = false; entry.image?.removeAttribute("src"); entry.image?.remove(); entry.image = null; }
      } else observeThumbnails();
    });
    trashArea.addEventListener("toggle", pumpThumbnails);
    const previewLifetime = new MutationObserver(() => {
      if (!root.isConnected) { clearPreviews(); previewLifetime.disconnect(); }
    });
    // Observe after the caller has had a chance to attach this panel.
    queueMicrotask(() => { if (root.isConnected) previewLifetime.observe(document.body, { childList: true, subtree: true }); });
    let native = null, busy = false, transfer = false, catalog = null, kind = "images", selectedAlbum = null;
    let requestSequence = 0, appliedSettingsSequence = 0;
    let deferredStatus = false;
    let sourceChoiceWaiting = false; // Shared Save-ACK slot for native folder choices.
    const settingsActions = new Set(["status", "mode", "settings", "pick_collection_source", "pick_destination", "default_destination", "shared_setting", "receive_consent", "send_consent"]);
    const defaultDestinations = new Map();
    const allButtons = [], actions = [], rightActions = []; let refresh, manualSync;
    const albumChoice = node("select"); albumChoice.className = "feld"; albumChoice.hidden = true;
    albumChoice.setAttribute("aria-label", t("Phone album")); albumList.append(albumChoice);
    albumChoice.addEventListener("change", () => { selectedAlbum = albumChoice.value || null; toggle(); });
    const button = (text, action, parent = controls) => {
      const b = node("button", text); b.type = "button"; b.className = "knopf klein" + (text === "Delete permanently" ? " rot" : ""); b.addEventListener("click", action); parent.append(b); allButtons.push(b); return b;
    };
    const toggle = () => {
      busy ||= sourceChoiceWaiting;
      const shared = !!native?.shared_settings, enabled = !shared || master.checked;
      const runtimeReady = !shared || native.shared_runtime_ready === true;
      masterRow.hidden = receiveRow.hidden = scope.parentElement.hidden = direction.parentElement.hidden = !shared;
      photosOnly.parentElement.hidden = !shared || typeof native.shared_settings.versions?.photos_only !== "string";
      master.disabled = !native;
      receiveConsent.disabled = !enabled || (busy && !receiveConsent.checked);
      for (const entry of sendChoices.values()) {
        entry.row.hidden = !shared || !native?.send_consent || native.metadata_ready?.[entry.mediaType] !== true;
        entry.input.disabled = sourceChoiceWaiting || !native?.send_consent || (busy && !entry.input.checked);
      }
      scope.disabled = direction.disabled = busy || !enabled;
      for (let i = allButtons.length - 1; i >= 0; i--) if (!root.contains(allButtons[i])) allButtons.splice(i, 1);
      for (const b of allButtons) b.disabled = busy;
      photos.disabled = videos.disabled = skip.disabled = busy || !native || !enabled;
      photosOnly.disabled = busy || !native || !enabled || photosOnly.parentElement.hidden;
      // Keep switching a live transfer back to manual possible, but don't
      // overlap an unacknowledged settings edit with another mode request.
      automatic.disabled = (busy && !transfer) || !native || !enabled || native.automatic_ready !== true;
      for (const entry of actions) entry.button.disabled = busy || !enabled || !runtimeReady || native?.metadata_ready?.[entry.mediaType] !== true || !(entry.mediaType === "video" ? videos.checked : photos.checked) || !native?.[entry.key];
      stop.disabled = !transfer;
      if (refresh) refresh.disabled = false;
      albumChoice.disabled = busy || !catalog;
      if (manualSync) manualSync.disabled = busy || !enabled || !runtimeReady || (shared
        ? native.shared_matched !== true || !/^[a-f0-9]{64}$/.test(native.shared_start_version || "")
        : !selectedAlbum || !catalog || native?.metadata_ready?.[kind] !== true);
      for (const entry of rightActions) {
        entry.row.hidden = native?.metadata_ready?.[entry.mediaType] !== true;
        entry.button.disabled = busy || !enabled || !runtimeReady || !(entry.mediaType === "video" ? videos.checked : photos.checked);
      }
      for (const b of destinations.querySelectorAll("button")) b.disabled = busy || !enabled || (shared && !receiveConsent.checked) ||
        !/^[a-f0-9]{64}$/.test(native?.destination_choices?.[b.dataset.destination] || "");
      for (const [key, b] of defaultDestinations) b.disabled ||= !native || native[key]?.default === true;
      const sourceValues = native?.shared_settings?.values;
      sourceArea.hidden = native?.collection_sources_supported !== true || sourceValues?.collection_mode !== "entire_collection" ||
        !["pc_to_phone", "two_way"].includes(sourceValues?.direction);
      for (const [mediaType, entry] of sourceRows) {
        entry.row.hidden = native?.metadata_ready?.[mediaType] !== true;
        entry.button.disabled = busy || sourceChoiceWaiting || sourceArea.hidden || !enabled || !runtimeReady || native?.shared_matched !== true ||
          native?.metadata_ready?.[mediaType] !== true || !/^[a-f0-9]{64}$/.test(native?.collection_sources_version || "") ||
          sourceValues?.[mediaType === "video" ? "videos_enabled" : "photos_enabled"] !== true ||
          native?.send_consent?.[mediaType === "video" ? "videos" : "photos"] !== true;
      }
      if (deferredStatus && !busy) {
        deferredStatus = false;
        queueMicrotask(() => {
          if (!root.isConnected) return;
          if (busy) { deferredStatus = true; return; }
          request("status", {}, false);
        });
      }
    };
    const request = async (action, data = {}, save = true) => {
      const sourceChoice = action === "pick_collection_source";
      const destinationChoice = action === "pick_destination" || action === "default_destination";
      const folderChoice = sourceChoice || destinationChoice;
      if (folderChoice) {
        const choiceButton = sourceChoice ? sourceRows.get(data.media_type)?.button :
          destinations.querySelector(`[data-destination="${data.media_type}"][data-destination-action="${action}"]`);
        if (!choiceButton || choiceButton.disabled || sourceChoiceWaiting || !currentContext()) return;
        sourceChoiceWaiting = true; busy = true; toggle();
      }
      if (save) {
        try { await saveBefore(); } catch {
          if (folderChoice) { sourceChoiceWaiting = false; busy = false; }
          restoreSharedInputs(); toggle(); status.textContent = t("The book could not be saved. Media synchronization was not started."); return;
        }
      }
      if (folderChoice && (!root.isConnected || !currentContext() ||
          (sourceChoice ? native?.collection_sources_version : native?.destination_choices?.[data.media_type]) !== data.version)) {
        sourceChoiceWaiting = false; busy = false; toggle(); return;
      }
      const now = Date.now();
      for (const [id, item] of pending) if (item.until < now || !item.root.isConnected) pending.delete(id);
      if (pending.size >= 128) {
        if (folderChoice) { sourceChoiceWaiting = false; busy = false; toggle(); }
        status.textContent = t("Too many pending requests. Wait for the current operation."); return;
      }
      const requestId = crypto.randomUUID(), message = { cmd: "telefon_medien", requestId, device_id: peerId, action, ...data };
      const sequence = ++requestSequence;
      const item = { root, peerId, action, receive: (reply, action) => receive(reply, action, sequence, data), until: now + 60000 };
      pending.set(requestId, item);
      if (folderChoice || ["trash_thumbnail", "trash_preview"].includes(action)) item.timer = setTimeout(() => {
        if (pending.get(requestId) !== item) return;
        pending.delete(requestId); busy = false;
        if (folderChoice) sourceChoiceWaiting = false;
        if (action === "trash_preview") previewStatus.textContent = t("Preview") + " · " + t("Failed");
        toggle(); pumpThumbnails();
      }, 65000);
      if (action !== "status" && action !== "cancel") busy = true;
      if (action === "sync" || action === "sync_shared") { transfer = true; status.textContent = t("Waiting for native media status"); }
      if (["sync", "sync_shared", "discover"].includes(action)) review.replaceChildren();
      toggle();
      if (!send(message)) { clearTimeout(item.timer); pending.delete(requestId); busy = false; if (folderChoice) sourceChoiceWaiting = false; if (["sync", "sync_shared"].includes(action)) transfer = false; restoreSharedInputs(); toggle(); status.textContent = t("Native media connection is unavailable."); }
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
      photosOnly.checked = values.photos_only === true;
      automatic.value = values.auto_mode; scope.value = values.collection_mode; direction.value = values.direction;
      receiveConsent.checked = native.receive_consent?.granted === true;
      for (const [key, entry] of sendChoices) entry.input.checked = native.send_consent?.[key] === true;
    };
    master.addEventListener("change", () => sharedSetting("enabled", master.checked));
    receiveConsent.addEventListener("change", () => request("receive_consent", { granted: receiveConsent.checked, version: native.receive_consent.version }));
    for (const entry of sendChoices.values()) entry.input.addEventListener("change", () => request("send_consent", {
      photos: sendChoices.get("photos").input.checked, videos: sendChoices.get("videos").input.checked, version: native.send_consent.version
    }));
    for (const [input, field] of [[photos, "photos_enabled"], [videos, "videos_enabled"], [skip, "skip_deletions"]])
      input.addEventListener("change", () => native?.shared_settings ? sharedSetting(field, input.checked) : settings());
    photosOnly.addEventListener("change", () => {
      if (typeof native?.shared_settings?.versions?.photos_only === "string") sharedSetting("photos_only", photosOnly.checked);
      else restoreSharedInputs();
    });
    automatic.addEventListener("change", () => native?.shared_settings ? sharedSetting("auto_mode", automatic.value) : request("mode", { version: native.version ?? null, automatic: automatic.value === "wifi" }));
    scope.addEventListener("change", () => sharedSetting("collection_mode", scope.value));
    direction.addEventListener("change", () => sharedSetting("direction", direction.value));
    const kinds = [["images", "Photos", "pictures"], ["video", "Videos", "video_destination"]];
    for (const [mediaType, label, key] of kinds) {
      const sourceRow = node("div"), hints = node("span"); sourceRow.dataset.collectionSourceKind = mediaType; sourceArea.append(sourceRow);
      const sourceButton = button("Add PC source folder …", () => request("pick_collection_source", {
        media_type: mediaType, version: native?.collection_sources_version }), sourceRow);
      sourceButton.dataset.collectionSourceAdd = mediaType; sourceButton.textContent = t(label) + " · " + t("Add PC source folder …");
      sourceRow.append(hints); sourceRows.set(mediaType, { row: sourceRow, button: sourceButton, hints });
      const row = node("div"), picker = node("div");
      row.dataset.destinationKind = mediaType; picker.className = "kde-empfangsordner";
      row.append(picker); destinations.append(row);
      const folder = button("Choose folder …", () => request("pick_destination", { media_type: mediaType, version: native?.destination_choices?.[mediaType] }), picker);
      folder.dataset.destinationAction = "pick_destination";
      folder.dataset.destination = mediaType; folder.textContent = t(label) + " · " + t("Destination folder");
      defaultDestinations.set(key, button("Use default", () => request("default_destination", {
        media_type: mediaType, version: native?.destination_choices?.[mediaType] }), picker));
      defaultDestinations.get(key).dataset.destination = mediaType;
      defaultDestinations.get(key).dataset.destinationAction = "default_destination";
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
    manualSync = button("Synchronize now", () => {
      if (native?.shared_settings) {
        if (!manualSync.disabled) request("sync_shared", { version: native.shared_start_version });
      } else if (selectedAlbum && catalog) request("sync", {
        media_type: kind, version: catalog.version, catalog_id: catalog.id, album_id: selectedAlbum });
    }, manualArea);
    function receive(reply, action, sequence, data) {
      const completedChoice = ["pick_collection_source", "pick_destination", "default_destination"].includes(action);
      if (completedChoice) { sourceChoiceWaiting = false; busy = false; }
      if (action === "trash_thumbnail" || action === "trash_preview") {
        busy = false;
        const entry = previewRows.get(data.operation_id), preview = reply.preview, side = action === "trash_thumbnail" ? 192 : 1024;
        const valid = reply.ok === true && entry?.row.isConnected && entry.data.version === data.version &&
          reply.operation_id === data.operation_id && reply.version === data.version && preview &&
          ["image/png", "image/jpeg"].includes(preview.mime_type) && Number.isSafeInteger(preview.width) && Number.isSafeInteger(preview.height) &&
          preview.width > 0 && preview.height > 0 && Math.max(preview.width, preview.height) <= side &&
          typeof preview.data_base64 === "string" && preview.data_base64.length > 0 && preview.data_base64.length <= 699052 &&
          preview.data_base64.length % 4 === 0 && /^[A-Za-z0-9+/]+={0,2}$/.test(preview.data_base64) &&
          (preview.mime_type === "image/png" ? preview.data_base64.startsWith("iVBORw0KGgo") : preview.data_base64.startsWith("/9j/"));
        if (action === "trash_preview") previewStatus.textContent = valid ? "" : t("Preview") + " · " + t("Failed");
        if (valid && (action === "trash_preview" || trashThumbnails.checked)) {
          const image = node("img"); image.alt = entry.name; image.src = "data:" + preview.mime_type + ";base64," + preview.data_base64;
          if (action === "trash_thumbnail") { image.className = "media-trash-thumbnail"; entry.row.prepend(image); entry.image = image; }
          else {
            closePreview(); previewDialog = node("dialog"); previewDialog.className = "media-trash-preview";
            const heading = node("h3"); heading.textContent = entry.name; previewDialog.append(heading, image);
            if (["prepared", "trashed", "restore_prepared"].includes(entry.state)) button("Restore", () => {
              closePreview(); request("trash_restore", entry.data);
            }, previewDialog);
            if (["trashed", "purge_prepared"].includes(entry.state)) button("Delete permanently", () => {
              closePreview(); request("trash_purge", entry.data);
            }, previewDialog);
            const close = button("Close", () => { closePreview(); pumpThumbnails(); }, previewDialog);
            previewDialog.addEventListener("cancel", event => { event.preventDefault(); closePreview(); pumpThumbnails(); });
            trashArea.append(previewDialog);
            if (typeof previewDialog.showModal === "function") previewDialog.showModal(); else previewDialog.setAttribute("open", "");
            close.focus();
          }
        }
        toggle(); pumpThumbnails(); return;
      }
      if (settingsActions.has(action)) {
        if (sequence < appliedSettingsSequence) { if (completedChoice) toggle(); return; }
        appliedSettingsSequence = sequence;
      }
      if (action === "activate" && reply.supported !== false) {
        busy = false; activate.disabled = false;
        if (reply.canceled) return;
        if (!reply.ok) { status.textContent = t("Media operation paused. No completion was confirmed."); return; }
      }
      if (reply.supported === false) {
        clearPreviews();
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
      if (["sync", "sync_shared"].includes(action) || reply.state === "idle") transfer = false;
      if (!reply.ok) {
        restoreSharedInputs();
        status.textContent = t(reply.state === "partial" ? "Stopped or incomplete. Original files and recovery history are retained." : "Media operation paused. No completion was confirmed.") + (reply.error ? " · " + String(reply.error) : "");
        toggle();
        if (native?.shared_settings && ["shared_setting", "receive_consent", "send_consent"].includes(action)) request("status", {}, false);
        return;
      }
      if (reply.canceled) { restoreSharedInputs(); toggle(); return; }
      if (action === "trash_list") {
        clearPreviews();
        trashRows.replaceChildren();
        nextTrash = reply.next_cursor; moreTrash.hidden = !Number.isSafeInteger(nextTrash);
        for (const item of (reply.trash || []).slice(0, 128)) {
          const row = node("li"); row.append(document.createTextNode(String(item.display_name || "") + " · " + t(item.media_type === "video" ? "Videos" : "Photos")));
          trashRows.append(row);
          const data = { operation_id: item.operation_id, version: item.version };
          row.dataset.mediaOperation = item.operation_id;
          if (typeof data.operation_id === "string" && /^[0-9a-f]{32}$/.test(data.operation_id) && typeof data.version === "string" && /^[0-9a-f]{64}$/.test(data.version)) {
            previewRows.set(data.operation_id, { row, data, state: item.state, name: String(item.display_name || ""), queued: false, loaded: false });
            button("Preview", () => request("trash_preview", data, false), row);
          }
          if (["prepared", "trashed", "restore_prepared"].includes(item.state))
            button(item.state === "prepared" ? "Recover operation" : "Restore", () => request("trash_restore", data), row);
          if (["trashed", "purge_prepared"].includes(item.state))
            button("Delete permanently", () => request("trash_purge", data), row);
        }
        status.textContent = t(trashRows.children.length ? "Media recycle bin loaded. Permanent removal requires native confirmation." : "No retained media entries on this page.");
        toggle(); observeThumbnails(); return;
      }
      if (action === "trash_restore" || action === "trash_purge") {
        clearPreviews();
        trashRows.replaceChildren(); nextTrash = null; moreTrash.hidden = true;
        status.textContent = t("Media recycle-bin operation finished. Read the entries again before another operation.");
        toggle(); return;
      }
      if (settingsActions.has(action)) {
        native = reply; photos.checked = !!reply.photos; videos.checked = !!reply.videos;
        photosOnly.checked = reply.shared_settings?.values?.photos_only === true;
        const shared = reply.shared_settings?.values;
        master.checked = shared?.enabled === true;
        receiveConsent.checked = reply.receive_consent?.granted === true;
        for (const [key, entry] of sendChoices) entry.input.checked = reply.send_consent?.[key] === true;
        if (shared) {
          photos.checked = shared.photos_enabled === true; videos.checked = shared.videos_enabled === true;
          scope.value = shared.collection_mode; direction.value = shared.direction;
        }
        const videoAvailable = reply.metadata_ready?.video === true;
        videos.parentElement.hidden = !videoAvailable;
        destinations.querySelector('[data-destination-kind="video"]').hidden = !videoAvailable;
        actions.find(entry => entry.mediaType === "video").button.hidden = !videoAvailable;
        caption.textContent = t(videoAvailable ? "Photos and videos" : "Photos");
        busy = !!reply.busy || !!reply.transfer_busy || !!reply.automatic_busy;
        transfer = !!reply.transfer_busy || !!reply.automatic_busy;
        automatic.value = shared?.auto_mode ?? (reply.automatic ? "wifi" : "manual"); automatic.parentElement.hidden = reply.automatic_ready !== true;
        skip.indeterminate = !shared && reply.skip_deletions === null; skip.checked = shared ? shared.skip_deletions === true : reply.skip_deletions !== false;
        mode.textContent = t(automatic.value === "wifi" ? "Automatically synchronize over Wi-Fi" : "Manual synchronization");
        for (const [mediaType, , key] of kinds) {
          const path = destinations.querySelector(`[data-destination="${mediaType}"]`);
          path.title = reply[key]?.display_path || "";
          const hints = sourceRows.get(mediaType).hints; hints.replaceChildren();
          for (const [index, source] of (reply.collection_sources || []).filter(item => item.media_type === mediaType).entries()) {
            const hint = node("span"); hint.textContent = t(mediaType === "video" ? "Videos" : "Photos") + " " + (index + 1);
            hint.title = String(source.display_path || ""); hints.append(hint);
          }
        }
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
      } else if (action === "sync_shared") {
        status.textContent = t(reply.state === "content_pass" ? "Content comparison finished." : "Content comparison needs review.") +
          " · " + t("Deletions are not synchronized yet.");
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
    for (const old of panels.keys()) if (!old.isConnected) panels.delete(old);
    panels.set(root, { peerId, refresh: () => { if (busy) deferredStatus = true; else request("status", {}, false); } });
    return advanced;
  }
  function createBackupPanel(peerId, mediaType, translate, send, saveBefore) {
    const t = translate, root = document.createElement("details"), title = document.createElement("summary"), rows = document.createElement("ul"), status = document.createElement("p");
    root.hidden = true; root.className = "telefon-medien-sicherungen einst-gruppe";
    title.textContent = t(mediaType === "video" ? "Videos" : "Photos") + " · " + t("Restore");
    status.setAttribute("role", "status"); root.append(title, rows, status);
    let busy = false, next = null, sourceId = null, remainingSources = [], visitedSources = new Set(), refreshing = true;
    const button = (label, action, parent) => {
      const b = document.createElement("button"); b.type = "button"; b.className = "knopf klein"; b.textContent = t(label); b.addEventListener("click", action); parent.append(b); return b;
    };
    function toggle() {
      for (const b of root.querySelectorAll("button")) b.disabled = busy;
    }
    async function request(action, data = {}) {
      if (busy) return;
      if (action === "backup_restore") {
        try { await saveBefore(); } catch { status.textContent = t("The book could not be saved. Media synchronization was not started."); return; }
      }
      const requestId = crypto.randomUUID(); busy = true; toggle();
      const nativeDialog = action === "backup_restore";
      pending.set(requestId, { root, peerId, action, receive, until: Date.now() + (nativeDialog ? 2 * 60 * 60 * 1000 : 60000) });
      if (!send({ cmd: "telefon_medien", requestId, device_id: peerId, media_type: mediaType, action, ...data })) {
        pending.delete(requestId); busy = false; refreshing = false; toggle();
      }
    }
    function receive(reply, action) {
      busy = false;
      if (!reply.ok) {
        refreshing = false;
        status.textContent = t("Media operation paused. No completion was confirmed."); toggle(); return;
      }
      if (reply.canceled) { toggle(); return; }
      if (action === "backup_list") {
        if (refreshing) { rows.replaceChildren(); remainingSources = []; visitedSources.clear(); refreshing = false; }
        sourceId = reply.location_id ?? null;
        if (sourceId) visitedSources.add(sourceId);
        for (const item of (reply.backup_location?.sources || []).slice(0, 64)) {
          const id = item.location_id;
          if (typeof id === "string" && id && visitedSources.size + remainingSources.length < 64 &&
              !visitedSources.has(id) && !remainingSources.includes(id)) remainingSources.push(id);
        }
        remainingSources = remainingSources.filter(id => !visitedSources.has(id));
        next = reply.next_cursor;
        more.hidden = !Number.isSafeInteger(next) && !remainingSources.length;
        const rowSource = sourceId;
        for (const item of (reply.backups || []).slice(0, 128)) {
          const row = document.createElement("li"); row.append(document.createTextNode(String(item.display_name || "") + " · " + new Date(item.saved_ms).toLocaleString()));
          button("Restore", () => request("backup_restore", { backup_id: item.backup_id, version: item.version,
            ...(rowSource ? { location_id: rowSource } : {}) }), row); rows.append(row);
        }
        root.hidden = !reply.backup_location && rows.children.length === 0 && !remainingSources.length; status.textContent = "";
        root.dispatchEvent(new Event("media-recovery-visibility"));
      } else if (action === "backup_restore") {
        status.textContent = t("Restore") + ": " + String(reply.display_name || "");
      }
      toggle();
    }
    button("Refresh", () => {
      if (busy) return;
      refreshing = true;
      request("backup_list", { after: 0 });
    }, root);
    const more = button("Next entries", () => {
      if (Number.isSafeInteger(next)) request("backup_list", { after: next, ...(sourceId ? { location_id: sourceId } : {}) });
      else if (remainingSources.length) request("backup_list", { after: 0, location_id: remainingSources[0] });
    }, root); more.hidden = true;
    // Read-only existing local history, even while the phone is disconnected.
    request("backup_list", { after: 0 }); return root;
  }
  function createRecoveryPanel(peerId, translate, send, saveBefore) {
    const root = document.createElement("details"), title = document.createElement("summary");
    root.className = "telefon-medien-wiederherstellung einst-gruppe"; root.hidden = true;
    title.textContent = translate("Photos and videos") + " · " + translate("Restore"); root.append(title);
    for (const kind of ["images", "video"]) {
      const history = createBackupPanel(peerId, kind, translate, send, saveBefore);
      history.addEventListener("media-recovery-visibility", () => {
        root.hidden = [...root.querySelectorAll(".telefon-medien-sicherungen")].every(panel => panel.hidden);
      });
      root.append(history);
    }
    return root;
  }
  window.MagnolieMedia = {
    createPanel,
    createBackupPanel,
    createRecoveryPanel,
    changed(reply) {
      if (!reply || typeof reply.device_id !== "string") return;
      for (const [root, panel] of panels) {
        if (!root.isConnected) { panels.delete(root); continue; }
        if (panel.peerId === reply.device_id) panel.refresh();
      }
    },
    receive(reply) {
      if (!reply || typeof reply.requestId !== "string") return;
      const item = pending.get(reply.requestId);
      if (!item || reply.device_id !== item.peerId || !item.root.isConnected || item.until < Date.now()) return;
      if (reply.state === "running") item.until = Date.now() + 2 * 60 * 60 * 1000;
      else { clearTimeout(item.timer); pending.delete(reply.requestId); }
      item.receive(reply, item.action);
    }
  };
})();
