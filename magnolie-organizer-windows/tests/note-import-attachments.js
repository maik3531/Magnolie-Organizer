"use strict";
// Refs #445: actual common import and save/ACK/reopen; synthetic profiles only.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), zlib = require("node:zlib"), cp = require("node:child_process");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../..");
const plain = value => JSON.parse(JSON.stringify(value));
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function png(rgb) {
  function chunk(type, data) {
    const payload = Buffer.concat([Buffer.from(type), data]), length = Buffer.alloc(4), checksum = Buffer.alloc(4);
    length.writeUInt32BE(data.length); checksum.writeUInt32BE(crc32(payload));
    return Buffer.concat([length, payload, checksum]);
  }
  const header = Buffer.alloc(13); header.writeUInt32BE(1, 0); header.writeUInt32BE(1, 4); header[8] = 8; header[9] = 2;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk("IHDR", header),
    chunk("IDAT", zlib.deflateSync(Buffer.from([0, ...rgb]))), chunk("IEND", Buffer.alloc(0))]);
}
const pixels = [[255,0,0], [0,0,255]], images = pixels.map(png);
cp.execFileSync("python3", ["-c", `import io,json,base64,sys
from PIL import Image
for encoded,pixel in json.load(sys.stdin):
 im=Image.open(io.BytesIO(base64.b64decode(encoded)));im.load()
 assert im.size==(1,1) and im.convert('RGB').getpixel((0,0))==tuple(pixel)
`], { input: JSON.stringify(images.map((image, index) => [image.toString("base64"), pixels[index]])) });
const urls = images.map(image => "data:image/png;base64," + image.toString("base64"));
function pdf(color) {
  const stream = color + " rg 0 0 1 1 re f\n";
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] /Resources << >> /Contents 4 0 R >>",
    "<< /Length " + Buffer.byteLength(stream) + " >>\nstream\n" + stream + "endstream"];
  let text = "%PDF-1.4\n"; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(text)); text += (index + 1) + " 0 obj\n" + object + "\nendobj\n"; });
  const xref = Buffer.byteLength(text);
  text += "xref\n0 5\n0000000000 65535 f \n" + offsets.slice(1).map(offset => String(offset).padStart(10, "0") + " 00000 n \n").join("") +
    "trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n";
  const bytes = Buffer.from(text);
  assert.match(cp.execFileSync("pdfinfo", ["-"], { input: bytes, encoding: "utf8" }), /Pages:\s+1/);
  return "data:application/pdf;base64," + bytes.toString("base64");
}
const pdfs = [pdf("1 0 0"), pdf("0 0 1")];
function note(data, id = "attachment-fixture") {
  return { titel: "same.png", text: "", anhaenge: [{ id, name: "same.png", art: "image", daten: data }] };
}
function boot(web, profile = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://note-import.test/", pretendToBeVisual: true
  });
  const w = dom.window, messages = [];
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.webkit = { messageHandlers: { bridge: { postMessage: raw => messages.push(JSON.parse(raw)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
  w.App.init({ daten: profile, neu: false, regional: { language: "en", timeZone: "UTC" } });
  return { w, t: w.OrganizerTest, messages, close: () => w.close() };
}
function save(app) {
  app.t.speichereJetzt();
  const request = app.messages.filter(message => message.cmd === "speichern").at(-1);
  assert.ok(request && Number.isInteger(request.id), "Actual native save envelope missing");
  app.w.App.gespeichert({ id: request.id, ok: true });
  return JSON.parse(request.text);
}
function check(web, profile, test) {
  const app = boot(web, profile);
  try { test(app); } finally { app.close(); }
}
for (const web of [path.join(root, "magnolie-organizer/web"), path.join(root, "magnolie-organizer-windows/app/web")]) {
  try {
    const app = boot(web); let stored;
    try {
      app.w.App.importErgebnis({ notizen: [note(urls[0]), note(urls[1])] });
      assert.equal(app.t.daten().notizen.length, 2, "Actual import misclassified different valid PNG bytes as a duplicate");
      assert.deepEqual(plain(app.t.daten().notizen.map(record => record.anhaenge[0].daten).sort()), [...urls].sort());
      stored = save(app);
    } finally { app.close(); }
    const reopened = boot(web, stored);
    try {
      assert.equal(reopened.t.daten().notizen.length, 2);
      assert.deepEqual(plain(reopened.t.daten().notizen.map(record => record.anhaenge[0].daten).sort()), [...urls].sort());
    } finally { reopened.close(); }
    check(web, { notizen: [note(urls[0], "existing-id")] }, app => {
      const original = plain(app.t.daten().notizen[0]);
      app.w.App.importErgebnis({ notizen: [note(urls[1], "new-id")] });
      assert.equal(app.t.daten().notizen.length, 2);
      assert.deepEqual(plain(app.t.daten().notizen[0]), original, "Existing note/history/attachment IDs were changed");
      assert.deepEqual(save(app).notizen.map(record => record.anhaenge[0].daten).sort(), [...urls].sort());
    });
    check(web, { notizen: [note(urls[0], "existing-id")] }, app => {
      const before = JSON.stringify(app.t.daten());
      app.w.App.importErgebnis({ notizen: [note(urls[0], "random-new-id")] });
      assert.equal(JSON.stringify(app.t.daten()), before, "Random attachment IDs created a content duplicate");
      assert.ok(app.w.document.querySelector("#zettel").textContent.includes("existing entry skipped"));
      const normalized = note(urls[0].replace("base64,", "base64,\n  "), "another-id");
      normalized.anhaenge[0].art = "pdf"; // Derived from validated URI, never this hint.
      app.w.App.importErgebnis({ notizen: [normalized] });
      assert.equal(JSON.stringify(app.t.daten()), before);
    });
    check(web, {}, app => {
      app.w.App.importErgebnis({ notizen: [note(urls[0], "one"), note(urls[0], "two")] });
      assert.equal(app.t.daten().notizen.length, 1, "Same-batch equivalent attachments were not deduplicated");
      const renamed = note(urls[0]); renamed.anhaenge[0].name = "different-visible-name.png";
      app.w.App.importErgebnis({ notizen: [renamed] });
      assert.equal(app.t.daten().notizen.length, 2, "Visible attachment properties were ignored");
    });
    check(web, {}, app => {
      app.w.App.importErgebnis({ notizen: pdfs.map(data => note(data)) });
      assert.equal(app.t.daten().notizen.length, 2, "Different complete PDFs were collapsed");
      assert.deepEqual(save(app).notizen.map(record => record.anhaenge[0].daten).sort(), [...pdfs].sort());
    });
    check(web, {}, app => {
      app.w.App.importErgebnis({ notizen: [{ titel: "Plain note", text: "Keep bare-note policy" },
        { titel: "Plain note", text: "Keep bare-note policy" }] });
      assert.equal(app.t.daten().notizen.length, 1, "Attachment-free duplicate policy changed");
      const before = JSON.stringify(app.t.daten()), saves = app.messages.filter(message => message.cmd === "speichern").length;
      app.w.App.importErgebnis({ abgebrochen: true, notizen: [note(urls[1])] });
      assert.equal(JSON.stringify(app.t.daten()), before);
      assert.equal(app.messages.filter(message => message.cmd === "speichern").length, saves);
    });
    check(web, {}, app => {
      const invalid = note("data:image/png;base64,not?valid");
      invalid.anhaenge.unshift(note(urls[0]).anhaenge[0]);
      app.w.App.importErgebnis({ notizen: [invalid] });
      assert.equal(app.t.daten().notizen.length, 0, "Invalid attachment produced a silently partial note");
      assert.ok(app.w.document.querySelector("#zettel").textContent.includes("unreadable row omitted"));
      const malformed = note(urls[0]); malformed.anhaenge = {};
      app.w.App.importErgebnis({ notizen: [malformed] });
      assert.equal(app.t.daten().notizen.length, 0);
      assert.equal(app.messages.filter(message => message.cmd === "speichern").length, 0);
    });
    check(web, {}, app => {
      const tooLarge = note("data:image/png;base64," + "A".repeat(12000000));
      app.w.App.importErgebnis({ notizen: [tooLarge] });
      assert.equal(app.t.daten().notizen.length, 0);
      assert.ok(app.w.document.querySelector("#zettel").textContent.includes("unreadable row omitted"));
      const data = "data:image/png;base64," + "A".repeat(8000000), aggregate = note(data);
      aggregate.anhaenge = Array.from({ length: 3 }, (_, index) => ({ ...aggregate.anhaenge[0], id: "large-" + index }));
      app.w.App.importErgebnis({ notizen: [aggregate, note(urls[0])], uebersprungen: 1 });
      assert.equal(app.t.daten().notizen.length, 1, "Rejected aggregate must not leave a truncated attachment list");
      assert.equal(app.t.daten().notizen[0].anhaenge[0].daten, urls[0]);
      assert.ok(app.w.document.querySelector("#zettel").textContent.includes("2 unreadable rows omitted"));
      assert.equal(save(app).notizen.length, 1);
    });
    console.log("PASS actual note import / attachment bytes / save ACK / fresh reopen:", web);
  } catch (error) { console.error(web, error); process.exitCode = 1; }
}
