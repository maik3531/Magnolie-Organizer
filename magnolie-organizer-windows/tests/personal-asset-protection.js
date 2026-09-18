"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const reader = fs.readFileSync(path.join(root, "ProtectedAssetReader.cs"), "utf8");
const policy = fs.readFileSync(path.join(root, "ProtectedAssetPolicy.cs"), "utf8");
const handbook = fs.readFileSync(path.join(root, "HandbookForm.cs"), "utf8");
const main = fs.readFileSync(path.join(root, "MainForm.cs"), "utf8");
for (const token of ["MGA1", "AesGcm", "ReadExactly", "MaxContainer", "ciphertextLength",
  "CryptographicOperations.ZeroMemory", "AddWebResourceRequestedFilter", "Cache-Control: no-store"]) {
  assert.ok((reader + policy).includes(token), `C#-Schutzinvariante fehlt: ${token}`);
}
assert.ok(main.includes('["/kaffee-qr.png"] = ("kaffee-qr.mga", 1, 1, "image/png")'));
assert.ok(reader.includes("new MemoryStream(data, writable: false)") &&
  !reader.includes("ClearingMemoryStream") && reader.includes("diagnostic?.Invoke"),
"WebView2-Antwort hält entschlüsselte Bildbytes nicht stabil oder protokolliert Fehler nicht");
assert.ok(handbook.includes('["/maik-walter.jpg"] = ("maik-walter.mga", 2, 2, "image/jpeg")') &&
  handbook.includes("AddHandbookBase") &&
  handbook.includes("SetVirtualHostNameToFolderMapping(VirtualHost") &&
  handbook.includes("document.fonts.ready") && handbook.includes("resourcesReady") &&
  handbook.includes("Task.Delay(100)") &&
  !handbook.includes("Convert.ToBase64String"));
for (const directory of [path.join(root, "app", "web"),
  path.join(root, "shared", "magnolie-handbuch-stamm", "web")]) {
  for (const file of fs.readdirSync(directory).filter(name => /\.(?:js|html)$/i.test(name))) {
    const text = fs.readFileSync(path.join(directory, file), "utf8");
    assert.ok(!/MGA1|MGA-v1-nonce|native-personal-assets|kaffee-qr\.mga|maik-walter\.mga/.test(text),
      `Browser-JavaScript enthält Asset-Kryptografie: ${file}`);
  }
}
console.log("PERSONAL ASSET PROTECTION STATIC TEST PASSED");
