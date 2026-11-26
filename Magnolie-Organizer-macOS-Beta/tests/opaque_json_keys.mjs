import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash } from "node:crypto";
import { boot, tick } from "./ui_harness.mjs";

// Actual generated UI, with synthetic native transport. This demonstrates the
// input at the native boundary; it never emulates a Swift dictionary/parser.
const nfc = "caf\u00e9", nfd = "cafe\u0301";
const host = await boot(process.argv[2]);
let checks = 0;
const equal = (actual, expected, label) => {
  assert.deepEqual(JSON.parse(JSON.stringify(actual)), JSON.parse(JSON.stringify(expected)), label);
  checks++;
};
const input = {
  termine: [], aufgaben: [], kontakte: [], notizen: [],
  [nfc]: { meaning: "NFC root" }, [nfd]: { meaning: "NFD root" },
  future: { [nfc]: { value: 1 }, [nfd]: { value: 2 },
    array: [{ [nfc]: "NFC array", [nfd]: "NFD array" }] },
  records: [{ id: nfc, exact: "NFC record" }, { id: nfd, exact: "NFD record" }],
  einstellungen: { allgemein: { handbuchHinweisGezeigt: true } }
};
function verify(value, label) {
  equal(value[nfc], input[nfc], label + " NFC root");
  equal(value[nfd], input[nfd], label + " NFD root");
  equal(value.future, input.future, label + " nested objects and array");
  equal(value.records, input.records, label + " exact record identities");
  equal(Object.keys(value.future).map(key => Buffer.from(key).toString("hex")),
    Object.keys(input.future).map(key => Buffer.from(key).toString("hex")), label + " lexical UTF-8 key bytes");
}
try {
  equal(nfc === nfd, false, "JavaScript opaque identity distinguishes the fixture");
  equal(nfc.normalize("NFC"), nfd.normalize("NFC"), "The fixture is canonically equivalent");
  host.w.MacBeta.receive("init", { daten: input, neu: false, regional: { language: "en", timeZone: "UTC" } });
  verify(host.t.daten(), "real init/normalizer");
  host.t.speichereJetzt();
  const save = host.messages.filter(message => message.cmd === "speichern").at(-1);
  assert.ok(save, "Actual shared save serializer must execute"); checks++;
  verify(JSON.parse(save.text), "actual save request");
  host.w.MacBeta.receive("gespeichert", { id: save.id, ok: true }); // explicitly synthetic
  equal(host.w.MacBeta.validateRestore(save.text), true, "actual projected restore validator");
  const operation = "51105110-5110-4511-8511-511051105110";
  const prepared = host.w.MacBeta.prepareNativeRestore(save.text, operation);
  equal(prepared.operationID, operation, "restore snapshot belongs to this operation");
  verify(JSON.parse(prepared.snapshot), "actual prepared restore snapshot");
  if (process.argv[3]) {
    const sha = file => createHash("sha256").update(fs.readFileSync(new URL(file, import.meta.url))).digest("hex");
    fs.writeFileSync(process.argv[3], JSON.stringify({
      schema: 1, issue: 511, checks,
      description: "Actual projected UI output with synthetic native transport. Native dictionary acceptance is deliberately not claimed.",
      sharedSourceSHA256: sha("../../magnolie-organizer/web/anwendung.js"),
      projectionSHA256: sha("../Projection/macos-beta.js"),
      saveRequest: save, restoreSnapshot: prepared.snapshot
    }, null, 2) + "\n");
  }
  console.log(`Opaque JSON boundary: ${checks} actual projected UI assertions passed; Swift acceptance remains a separate test.`);
} finally { await tick(); host.close(); }
