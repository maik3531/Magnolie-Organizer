/* Magnolie QR interaction: local display only; opening an HTTP(S) link requires a second action. */
(function () {
  "use strict";
  const bindings = new WeakMap();
  let active = null;
  async function read(image) {
    if (!image.complete || !image.naturalWidth) {
      await Promise.race([
        image.decode(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("qr_image_unavailable")), 5000))
      ]);
    }
    if (!image.naturalWidth || !image.naturalHeight || typeof window.jsQR !== "function") throw new Error("qr_image_unavailable");
    const scale = Math.min(1, 2048 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("qr_image_unavailable");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const result = window.jsQR(pixels.data, canvas.width, canvas.height, { inversionAttempts: "attemptBoth" });
    canvas.width = canvas.height = 0;
    if (!result || !result.data || result.data.length > 65536) throw new Error("qr_unreadable");
    return result.data;
  }
  function webLink(text) {
    if (typeof text !== "string" || !/^https?:\/\//i.test(text) || /[\s\u0000-\u001f\u007f]/.test(text)) return "";
    try { const url = new URL(text); return url.username || url.password ? "" : url.href; } catch (_) { return ""; }
  }
  function show(payload, options) {
    if (!payload || typeof payload.text !== "string" || !payload.text || payload.text.length > 65536) return;
    if (active) active();
    const previous = document.activeElement;
    const veil = document.createElement("div"), panel = document.createElement("div");
    veil.className = "magnolie-qr-veil"; panel.className = "magnolie-qr-dialog";
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true"); panel.setAttribute("aria-label", options.title);
    const title = document.createElement("h3"); title.textContent = options.title;
    const text = document.createElement("pre"); text.className = "magnolie-qr-text"; text.textContent = payload.text;
    text.tabIndex = 0;
    const buttons = document.createElement("div"); buttons.className = "magnolie-qr-buttons";
    const close = document.createElement("button"); close.type = "button"; close.textContent = options.close;
    const finish = () => {
      if (!veil.isConnected) return;
      if (options.unregister) options.unregister(veil);
      veil.remove(); if (active === finish) active = null;
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
    close.addEventListener("click", finish); buttons.append(close); panel.append(title, text);
    if (payload.coffee) { const hint = document.createElement("p"); hint.className = "magnolie-qr-coffee-hint"; hint.textContent = options.coffeeHint; panel.append(hint); }
    const link = webLink(payload.text);
    if (link) {
      const open = document.createElement("button"); open.type = "button"; open.textContent = options.open;
      open.className = "magnolie-qr-open";
      open.addEventListener("click", () => {
        if (payload.valid && !payload.valid()) { finish(); return; }
        const anchor = document.createElement("a"); anchor.href = link; anchor.target = options.target || "_blank"; anchor.rel = "noopener noreferrer";
        finish(); anchor.click();
      });
      buttons.append(open);
    }
    panel.append(buttons); veil.append(panel); document.body.append(veil); active = finish;
    if (options.register) options.register(veil, panel, { anfang: close, schliessen: finish });
    else {
      veil.addEventListener("keydown", event => {
        event.stopPropagation();
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(); }
        if (event.key === "Tab") {
          const nodes = [text, ...buttons.querySelectorAll("button")], first = nodes[0], last = nodes[nodes.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      });
      close.focus();
    }
  }
  function bind(image, resolve, options) {
    bindings.set(image, { resolve, options, pending: false });
    image.tabIndex = 0; image.setAttribute("role", "button"); image.setAttribute("aria-haspopup", "dialog");
    image.setAttribute("aria-label", image.alt || options.title);
    if (options.scanHint) image.title = options.scanHint;
    if (image.dataset.qrInteractive) return;
    image.dataset.qrInteractive = "true";
    const activate = async event => {
      event.preventDefault(); event.stopPropagation();
      const binding = bindings.get(image), payload = binding.resolve() || {};
      if (binding.pending || payload.valid && !payload.valid()) return;
      binding.pending = true; image.setAttribute("aria-busy", "true");
      try {
        const text = await read(image);
        if (image.isConnected && (!payload.valid || payload.valid())) show({ ...payload, text }, binding.options);
      } catch (_) {
        if (image.isConnected && (!payload.valid || payload.valid())) show({ text: binding.options.readError }, binding.options);
      } finally { binding.pending = false; image.removeAttribute("aria-busy"); }
    };
    image.addEventListener("click", activate);
    image.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") activate(event); });
  }
  window.MagnolieQr = Object.freeze({ bind, show, webLink, read });
})();
