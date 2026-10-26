/* Native GTK/WebKit scenario; only the probe bridge supplies synthetic contacts. */
(async () => {
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const same = (actual, expected) => JSON.stringify(actual) === JSON.stringify(expected);
  const waitFor = async predicate => {
    const deadline = Date.now() + 4000;
    while (!predicate()) {
      check(Date.now() < deadline, "Native contact operation did not finish");
      await new Promise(resolve => setTimeout(resolve, 15));
    }
  };
  const report = data => window.webkit.messageHandlers.desktop_probe.postMessage(JSON.stringify({ probe: "groups", ...data }));
  const fingerprint = "a".repeat(64), uid = "synthetic-contact";
  let remote, device, results = [];
  window.contactGroupProbeReply = message => App.telefonKontakte({ ok: true, requestId: message.requestId,
    device_id: device, fingerprint, contacts: message.uids ? [remote] : [{ uid, modified_ms: 1 }] });
  try {
    for (const provider of ["kde", "notes"]) for (const mode of ["incoming", "clear", "keep"]) {
      device = provider === "notes" ? "notes:11111111-1111-4111-8111-111111111111" : "synthetic-kde";
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(provider + "-contact-v1\0" + device + "\0" + fingerprint + "\0" + uid));
      const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      remote = { uid, bindung: "urn:magnolie:import:" + provider + ":" + hash,
        kontakt: { vorname: "Synthetic", email: "fixture@example.test", vcardRoundtrip: mode === "clear" ? [] : ["CATEGORIES:Arbeit"] } };
      App.init({ daten: { kontakte: [{ id: "local-synthetic", vorname: "Synthetic", email: "fixture@example.test",
        vcardRoundtrip: ["CATEGORIES:Kollegen", "X-LOCAL:preserve"] }], einstellungen: { adressen: { foto: false, fotoVoreinstellung: 1 } } },
        neu: false, regional: { language: "en", timeZone: "UTC" } });
      App.telefonStand(provider === "notes" ? { peers: [{ device_id: device.slice(6), state: "online_wifi", own_device: true,
        remote_own_device: true, contacts_read_available: true, contacts_fingerprint: fingerprint }], kdeconnect: { contacts_available: false } } :
        { peers: [], kdeconnect: { contacts_available: true, contacts_device_id: device } });
      await OrganizerTest.kdeStart();
      const dialog = document.querySelector(".kontakt-import-dialog");
      check(dialog && !dialog.querySelector(".hauptknopf").disabled, "Complete native preview must allow Apply: " + dialog?.textContent + " " + JSON.stringify(OrganizerTest.kdeProbeState()));
      check(same(OrganizerTest.kontaktGruppen(OrganizerTest.daten().kontakte[0]), ["Colleagues"]), "Preview changed local groups");
      const row = Array.from(dialog.querySelectorAll(".formzeile")).find(row => row.textContent.startsWith("Contact groups"));
      check(row, "Missing dedicated group decision in native dialog: " + dialog.textContent);
      dialog.querySelector("details").open = true;
      row.scrollIntoView({ block: "center" });
      const select = row.querySelector("select");
      check(select.getBoundingClientRect().width > 0, "Native group choice is not laid out");
      if (mode === "clear") check(Array.from(select.options).some(option => option.value === "incoming" && option.textContent.includes("No contact group")), "Empty group choice has no readable label");
      select.value = mode === "keep" ? "keep" : "incoming";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      dialog.querySelector(".hauptknopf").click();
      await waitFor(() => !document.querySelector(".kontakt-import-dialog"));
      const contact = OrganizerTest.daten().kontakte[0], expected = mode === "keep" ? ["Colleagues"] : mode === "clear" ? [] : ["Work"];
      check(same(OrganizerTest.kontaktGruppen(contact), expected), "Native Apply lost group choice: " + provider + "/" + mode);
      check(contact.vcardRoundtrip.includes("X-LOCAL:preserve"), "Group change removed unrelated vCard information");
      results.push({ provider, mode, groups: expected });
    }
    report({ ok: true, cases: results, scope: "Native GTK/WebKit preview/layout/Apply/SaveACK with synthetic provider replies" });
  } catch (error) { report({ ok: false, error: String(error) + "\n" + (error.stack || ""), cases: results }); }
})();
