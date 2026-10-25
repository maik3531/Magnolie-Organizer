"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const qr = require("./qr-image-fixture.js");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      for (const name of ["qr-decoder.js", "qr-dialog.js"]) b.w.eval(fs.readFileSync(path.join(web, name), "utf8"));
      const attach = qr.install(b.w), coffeePixels = qr.fixture("--image", path.join(web, "kaffee-qr.mga"));
      const opened = []; b.w.HTMLAnchorElement.prototype.click = function () { opened.push(this.href); };
      b.w.confirm = () => { throw new Error("Browser confirmation must not be used"); };
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-ueber").click();
      const image = b.w.document.querySelector("img.kaffee-qr"), original = [image.src, image.className, image.getAttribute("width"), image.getAttribute("height")];
      attach(image, coffeePixels);
      assert.equal(image.title, "Scan or click");
      assert.equal(b.w.document.querySelector(".magnolie-qr-coffee-hint"), null);
      const data = JSON.stringify(b.t.daten()), messages = b.messages.length;
      image.focus(); image.dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await qr.tick();
      const popup = b.w.document.querySelector(".magnolie-qr-dialog"); assert.ok(popup);
      assert.equal(qr.digest(popup.querySelector("pre").textContent), coffeePixels.content_sha256, "Dialog did not decode the actual coffee image");
      assert.equal(popup.querySelectorAll("button").length, 1, "Bank text must not be treated as a browser link");
      assert.ok(popup.querySelector(".magnolie-qr-coffee-hint").textContent.includes("ContributorKey"));
      assert.equal(opened.length, 0); assert.equal(JSON.stringify(b.t.daten()), data); assert.equal(b.messages.length, messages);
      popup.dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      assert.equal(b.w.document.querySelector(".magnolie-qr-dialog"), null); assert.equal(b.w.document.activeElement, image);
      assert.deepEqual([image.src, image.className, image.getAttribute("width"), image.getAttribute("height")], original);
      const linkImage = b.w.document.createElement("img"); b.w.document.body.append(linkImage);
      attach(linkImage, qr.fixture("--text", "https://example.invalid/owned-download"));
      const options = { title: "QR", close: "Close", open: "Open in browser", coffeeHint: "Never here" };
      b.w.MagnolieQr.bind(linkImage, () => ({ text: "https://wrong.invalid/not-the-qr-content" }), options);
      linkImage.dispatchEvent(new b.w.KeyboardEvent("keydown", { key: " ", bubbles: true }));
      await qr.tick();
      assert.equal(opened.length, 0); assert.equal(b.w.document.querySelector(".magnolie-qr-coffee-hint"), null);
      b.w.document.querySelector(".magnolie-qr-dialog button").click(); assert.equal(opened.length, 0);
      linkImage.click(); await qr.tick(); b.w.document.querySelector(".magnolie-qr-open").click(); assert.deepEqual(opened, ["https://example.invalid/owned-download"]);
      for (const text of ["javascript:alert(1)", "file:///owned", "data:text/plain,owned", "magnolie-paarung://owned-fixture", "https://user:password@example.invalid/"]) {
        b.w.MagnolieQr.show({ text }, options);
        assert.equal(b.w.document.querySelector(".magnolie-qr-open"), null);
        b.w.document.querySelector(".magnolie-qr-dialog button").click();
      }
      assert.equal(opened.length, 1);
      let stillValid = true;
      b.w.MagnolieQr.bind(linkImage, () => ({ valid: () => stillValid }), options);
      linkImage.click(); stillValid = false; await qr.tick();
      assert.equal(b.w.document.querySelector(".magnolie-qr-dialog"), null, "A late decoded result escaped its source/lifetime guard");
      if (web.endsWith("magnolie-organizer/web")) {
        b.w.App.baumStand({ moeglich: true, an: true, name: "Owned QR fixture", partner: [], eingang: [] });
        b.w.document.querySelector("#einst-tab-baum").click();
        b.w.App.baumPaarungsdatei({ ok: true, art: "qr", bild: "data:image/svg+xml,<svg/>", gueltigBis: Math.floor(Date.now() / 1000) + 900 });
        const pairing = b.w.document.querySelector(".baum-paarungsqr img"); assert.ok(pairing);
        attach(pairing, qr.fixture("--text", "magnolie-pair:owned-fixture"));
        const before = b.messages.length; pairing.click(); await qr.tick();
        assert.equal(b.w.document.querySelector(".magnolie-qr-text").textContent, "magnolie-pair:owned-fixture");
        assert.equal(b.w.document.querySelector(".magnolie-qr-open"), null); assert.equal(b.messages.length, before);
        b.w.document.querySelector(".magnolie-qr-dialog button").click();
      }
      console.log("QR DIALOG PASS: exact local content, unchanged images, keyboard/focus/cancel, explicit web confirmation, text-only pairing, no data/native actions " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
