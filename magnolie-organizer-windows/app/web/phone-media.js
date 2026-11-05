/* Native media UI: opaque choices only, no browser paths, grants or Saved proofs. */
(() => {
  "use strict";
  const pending = new Map();
  function createPanel(peerId, translate, send, saveBefore) {
    const t = translate, root = document.createElement("details");
    root.className = "telefon-medien einst-gruppe"; root.hidden = true;
    const node = (tag, text) => { const e = document.createElement(tag); if (text) e.textContent = t(text); return e; };
    const title = node("summary", "Photos and videos"), status = node("p", "Waiting for native media status");
    status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const note = node("p", "Only synchronize the phone inventory. Local edits are preserved. Deletions are not synchronized yet.");
    note.className = "einst-hinweis";
    root.append(title, note, status);
    const check = (text, key) => {
      const label = node("label"), input = node("input"); input.type = "checkbox"; input.dataset.media = key;
      label.className = "hak"; label.append(input, document.createTextNode(" " + t(text))); root.append(label); return input;
    };
    const photos = check("Synchronize photos", "photos"), videos = check("Synchronize videos", "videos"), skip = check("Skip deletions", "skip_deletions");
    const automatic = check("Automatically synchronize over Wi-Fi", "automatic");
    const mode = node("p", "Manual synchronization"), destinations = node("div"), controls = node("div"), albumList = node("div"), review = node("ul");
    root.append(mode, destinations, controls, albumList, review);
    let native = null, busy = false, transfer = false, catalog = null, kind = "images";
    const allButtons = [], actions = []; let refresh;
    const button = (text, action, parent = controls) => {
      const b = node("button", text); b.type = "button"; b.addEventListener("click", action); parent.append(b); allButtons.push(b); return b;
    };
    const toggle = () => {
      for (let i = allButtons.length - 1; i >= 0; i--) if (!root.contains(allButtons[i])) allButtons.splice(i, 1);
      for (const b of allButtons) b.disabled = busy;
      photos.disabled = videos.disabled = skip.disabled = busy || !native;
      automatic.disabled = !native || native.automatic_ready !== true;
      for (const entry of actions) entry.button.disabled = busy || native?.metadata_ready?.[entry.mediaType] !== true || !native?.[entry.mediaType === "video" ? "videos" : "photos"] || !native?.[entry.key];
      stop.disabled = !transfer;
      if (refresh) refresh.disabled = false;
    };
    const request = async (action, data = {}, save = true) => {
      if (save) {
        try { await saveBefore(); } catch { status.textContent = t("The book could not be saved. Media synchronization was not started."); return; }
      }
      const now = Date.now();
      for (const [id, item] of pending) if (item.until < now || !item.root.isConnected) pending.delete(id);
      if (pending.size >= 128) { status.textContent = t("Too many pending requests. Wait for the current operation."); return; }
      const requestId = crypto.randomUUID(), message = { cmd: "telefon_medien", requestId, device_id: peerId, action, ...data };
      const item = { root, peerId, action, receive, until: now + 60000 };
      pending.set(requestId, item);
      if (action !== "status" && action !== "cancel") busy = true;
      if (action === "sync") { transfer = true; status.textContent = t("Waiting for native media status"); }
      if (action === "sync" || action === "discover") review.replaceChildren();
      toggle();
      if (!send(message)) { pending.delete(requestId); busy = false; if (action === "sync") transfer = false; toggle(); status.textContent = t("Native media connection is unavailable."); }
    };
    const settings = () => {
      if (skip.indeterminate) {
        photos.checked = !!native?.photos; videos.checked = !!native?.videos;
        status.textContent = t("Skip deletions") + "?"; skip.focus(); return;
      }
      return request("settings", { version: native.version ?? null, photos: photos.checked, videos: videos.checked, skip_deletions: skip.checked });
    };
    for (const input of [photos, videos, skip]) input.addEventListener("change", settings);
    automatic.addEventListener("change", () => request("mode", { version: native.version ?? null, automatic: automatic.checked }));
    const kinds = [["images", "Photos", "pictures"], ["video", "Videos", "video_destination"]];
    for (const [mediaType, label, key] of kinds) {
      const row = node("div"), path = node("p", "No destination selected"); path.dataset.destination = mediaType;
      row.append(node("strong", label), path); destinations.append(row);
      button("Choose destination…", () => request("pick_destination", { media_type: mediaType, version: native?.[key]?.version ?? null }), row);
      const discover = button(label === "Photos" ? "Read photo albums" : "Read video albums", () => {
        kind = mediaType; catalog = null; albumList.replaceChildren(); request("discover", { media_type: mediaType });
      });
      actions.push({ button: discover, mediaType, key });
    }
    const more = button("More albums", () => catalog && request("page", { media_type: kind, version: catalog.version, catalog_id: catalog.id, after: catalog.next }));
    more.hidden = true;
    const permission = button("Request access on phone", () => catalog && request("request_read", { media_type: kind, version: catalog.version })); permission.hidden = true;
    const stop = button("Stop", () => request("cancel", {}, false));
    refresh = button("Refresh", () => request("status", {}, false));
    function receive(reply, action) {
      if (reply.supported === false) {
        root.hidden = true; native = null; busy = transfer = false; catalog = null;
        albumList.replaceChildren(); review.replaceChildren(); more.hidden = permission.hidden = true; toggle(); return;
      }
      if (!native && reply.supported !== true && action !== "status") return;
      if (!native && !reply.ok) return;
      root.hidden = false;
      if (reply.state === "running" || reply.state === "stopping") {
        busy = true; toggle(); status.textContent = t(reply.state === "stopping" ? "Stopping… Waiting for the native operation to end." : "Comparing media content… The total is not known yet."); return;
      }
      busy = false;
      if (action === "sync" || reply.state === "idle") transfer = false;
      if (!reply.ok) {
        status.textContent = t(reply.state === "partial" ? "Stopped or incomplete. Original files and recovery history are retained." : "Media operation paused. No completion was confirmed.") + (reply.error ? " · " + String(reply.error) : "");
        toggle(); return;
      }
      if (reply.canceled) { toggle(); return; }
      if (action === "status" || action === "mode" || action === "settings" || action === "pick_destination") {
        native = reply; photos.checked = !!reply.photos; videos.checked = !!reply.videos;
        const videoAvailable = reply.metadata_ready?.video === true;
        videos.parentElement.hidden = !videoAvailable;
        destinations.querySelector('[data-destination="video"]').parentElement.hidden = !videoAvailable;
        actions.find(entry => entry.mediaType === "video").button.hidden = !videoAvailable;
        title.textContent = t(videoAvailable ? "Photos and videos" : "Photos");
        busy = !!reply.busy || !!reply.transfer_busy || !!reply.automatic_busy;
        transfer = !!reply.transfer_busy || !!reply.automatic_busy;
        automatic.checked = !!reply.automatic; automatic.parentElement.hidden = reply.automatic_ready !== true;
        skip.indeterminate = reply.skip_deletions === null; skip.checked = reply.skip_deletions !== false;
        mode.textContent = t(reply.automatic ? "Automatically synchronize over Wi-Fi" : "Manual synchronization");
        for (const [mediaType, , key] of kinds) destinations.querySelector(`[data-destination="${mediaType}"]`).textContent = reply[key]?.display_path || t("No destination selected");
        status.textContent = t(busy ? "A native media operation is still running." : reply.metadata_ready?.images !== true
          ? "Media transfer is not available on this connection yet." : "Native settings loaded. No transfer has been started.");
        if (!busy && reply.automatic) {
          if (reply.automatic_phase === "paused") status.textContent = t("Automatic synchronization is paused. Switch to manual mode and enable it again to resume.");
          else if (["review", "held", "partial"].includes(reply.automatic_phase)) status.textContent = t("Automatic content comparison needs attention. No deletion completion was confirmed.");
          else if (reply.automatic_phase === "content_pass") status.textContent = t("Automatic pass checked one album per media type. Further albums follow; deletions remain pending.");
        }
      } else if (action === "discover" || action === "page") {
        if (action === "discover") { albumList.replaceChildren(); catalog = { version: reply.version, id: reply.catalog_id, next: reply.next_cursor }; }
        if (!catalog || catalog.id !== reply.catalog_id || catalog.version !== reply.version) { status.textContent = t("Album selection changed. Read the albums again."); toggle(); return; }
        catalog.next = reply.next_cursor; more.hidden = !Number.isSafeInteger(catalog.next);
        permission.hidden = false;
        for (const album of reply.albums || []) {
          button(String(album.display_name || "Album"), () => request("sync", { media_type: kind, version: catalog.version, catalog_id: catalog.id, album_id: album.album_id }), albumList);
        }
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
    return root;
  }
  window.MagnolieMedia = {
    createPanel,
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
