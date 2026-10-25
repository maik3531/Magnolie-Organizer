"use strict";
const path = require("node:path"), { execFileSync } = require("node:child_process"), { createHash } = require("node:crypto");
const root = path.resolve(__dirname, "../..");
const cache = new Map();
function fixture(kind, value) {
  const key = kind + value;
  if (!cache.has(key)) cache.set(key, JSON.parse(execFileSync(process.env.MAGNOLIE_PYTHON || "python3",
    [path.join(root, "magnolie-organizer/pruefungen/qr_image_fixture.py"), kind, value], { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 })));
  return cache.get(key);
}
function install(window) {
  const images = new WeakMap();
  window.HTMLCanvasElement.prototype.getContext = function () {
    let source;
    return { drawImage(image) { source = images.get(image); if (!source) throw new Error("Missing owned QR pixel fixture"); },
      getImageData() { return { data: new window.Uint8ClampedArray(Buffer.from(source.pixels, "base64")) }; } };
  };
  return (image, pixels) => {
    images.set(image, pixels);
    Object.defineProperties(image, { naturalWidth: { configurable: true, value: pixels.width }, naturalHeight: { configurable: true, value: pixels.height }, complete: { configurable: true, value: true } });
    image.decode = () => Promise.resolve();
  };
}
const digest = text => createHash("sha256").update(text).digest("hex");
const tick = () => new Promise(resolve => setImmediate(resolve));
module.exports = { fixture, install, digest, tick };
