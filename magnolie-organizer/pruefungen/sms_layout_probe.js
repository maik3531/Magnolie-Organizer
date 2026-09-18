/* Synthetic contact only. Geometry never sends; functional clicks use the isolated mock sink. */
"use strict";
window.smsProbePrepare = function (locale, state) {
  document.querySelector(".sms-schliessen")?.click();
  MagnolieI18n.setLocale(locale);
  OrganizerTest.daten().einstellungen.adressen.smsSchedulingEnabled = true;
  App.telefonAntwort({nummer: "+12025550123", device_id: "sms-layout-synthetic-device-00001"});
  const text = document.querySelector(".sms-eingabe");
  if (!text) throw new Error("Application SMS dialog did not open");
  text.value = state === "adjusted" ? "Synthetic SMS \u2014 adaptation preview \ud83d\ude42\nNo message will be sent." :
    state === "plain" ? "Synthetic SMS. No message will be sent." : "";
  text.dispatchEvent(new Event("input", {bubbles: true}));
  window.smsProbeReady = false;
  document.fonts.ready.then(() => requestAnimationFrame(() => requestAnimationFrame(() => {
    const dialog = document.querySelector(".sms-dialog");
    const row = dialog.querySelector(".sms-komponist");
    window.smsProbeInitialScroll = dialog.scrollTop;
    // Scroll only when needed, as a user would; never override source styles.
    if (row.getBoundingClientRect().bottom > dialog.getBoundingClientRect().bottom - dialog.clientTop)
      dialog.scrollTop = dialog.scrollHeight;
    window.smsProbeReady = true;
  })));
};

window.smsProbeMeasure = function (state) {
  const dialog = document.querySelector(".sms-dialog");
  const composer = dialog.querySelector(".sms-komponist");
  const [content, send, schedule] = composer.children;
  const textarea = content.querySelector("textarea");
  const counter = content.querySelector(".sms-segmentzaehler");
  const preview = content.querySelector(".sms-anpassung");
  const rect = element => {
    const r = element.getBoundingClientRect();
    return Object.fromEntries(["top", "left", "right", "bottom", "width", "height"].map(key => [key, r[key]]));
  };
  const boxes = Object.fromEntries(Object.entries({dialog, composer, content, textarea, counter, preview, send, schedule})
    .map(([name, element]) => [name, rect(element)]));
  const errors = [];
  const check = (value, message) => { if (!value) errors.push(message); };
  const near = (a, b) => Math.abs(a - b) <= 0.5;
  const cs = getComputedStyle(composer);
  const innerLeft = boxes.composer.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
  const innerRight = boxes.composer.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
  check(composer.children.length === 3 && content.classList.contains("sms-komponist-text") &&
    send.textContent === MagnolieI18n.gettext("Send SMS") && schedule.textContent === MagnolieI18n.gettext("Schedule"),
  "DOM order must be text, Send SMS, Schedule");
  check(near(boxes.send.top, boxes.schedule.top), "Send and Schedule tops differ");
  check(near(boxes.send.height, boxes.schedule.height), "Send and Schedule heights differ");
  check(boxes.send.height > 0 && boxes.send.width > 0 && boxes.schedule.width > 0, "Empty action box");
  check(near(boxes.content.left, innerLeft) && near(boxes.content.right, innerRight) &&
    near(boxes.textarea.width, boxes.content.width), "Text container/textarea is not full width");
  check(boxes.counter.top >= boxes.textarea.bottom - 0.5, "Counter overlaps textarea");
  check(boxes.send.top >= boxes.content.bottom + parseFloat(cs.rowGap) - 0.5, "Actions are not below all text content");
  check(preview.classList.contains("verborgen") === (state !== "adjusted"), "Wrong adaptation preview state");
  const confirmationButtons = preview.querySelectorAll("button");
  check(confirmationButtons.length === 2 &&
    confirmationButtons[0].textContent === MagnolieI18n.gettext("Send adjusted text") &&
    confirmationButtons[1].textContent === MagnolieI18n.gettext("Cancel"),
  "Adaptation confirmation must contain the actual translated buttons");
  check(!preview.textContent.includes("[object HTMLButtonElement]"), "Button was stringified instead of appended");
  if (state === "adjusted") {
    check(boxes.preview.top >= boxes.counter.bottom && near(boxes.preview.width, boxes.content.width),
      "Adaptation preview is not below counter/full width");
    check(preview.querySelector("pre").textContent.includes(":)"), "Real adaptation handler did not run");
    for (const button of confirmationButtons) {
      const r = rect(button);
      check(r.width > 0 && r.height > 0 && r.left >= boxes.preview.left && r.right <= boxes.preview.right &&
        r.top >= boxes.preview.top && r.bottom <= boxes.preview.bottom, "Confirmation button escapes preview");
      check(button.scrollWidth <= button.clientWidth + 1 && button.scrollHeight <= button.clientHeight + 1,
        "Confirmation button label overflows");
    }
  }
  for (const button of [send, schedule]) {
    const r = rect(button);
    check(r.left >= innerLeft - 0.5 && r.right <= innerRight + 0.5, "Action escapes composer horizontally");
    check(button.scrollWidth <= button.clientWidth + 1, "Action label overflows horizontally");
    check(button.scrollHeight <= button.clientHeight + 1, "Action label overflows vertically");
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    check(hit === button || button.contains(hit), "Action is clipped or not hit-testable");
  }
  check(boxes.send.bottom <= boxes.dialog.bottom && boxes.schedule.bottom <= innerHeight,
    "Action row is clipped below dialog/viewport");
  check(OrganizerTest.daten().smsPlanung.length === 0 && OrganizerTest.daten().smsVerlauf.length === 0,
    "Probe must not schedule or enqueue any SMS");
  return {boxes, errors, viewport: [innerWidth, innerHeight], locale: document.documentElement.lang,
    direction: document.documentElement.dir, labels: [send.textContent, schedule.textContent],
    fonts: [send, schedule, textarea].map(element => getComputedStyle(element).fontSize),
    previewVisible: state === "adjusted", grid: cs.gridTemplateColumns,
    scroll: {initial: window.smsProbeInitialScroll, final: dialog.scrollTop, maximum: dialog.scrollHeight - dialog.clientHeight},
    adaptationConfirmationButtons: confirmationButtons.length,
    confirmations: Array.from(confirmationButtons, button => ({label: button.textContent, box: rect(button)}))};
};

window.smsProbeFunctional = function (action) {
  const dialog = document.querySelector(".sms-dialog");
  const textarea = dialog.querySelector("textarea");
  const preview = dialog.querySelector(".sms-anpassung");
  const [confirm, cancel] = preview.querySelectorAll("button");
  const send = dialog.querySelector(".sms-komponist > .hauptknopf");
  const data = OrganizerTest.daten();
  const expectedText = "Synthetic SMS - adaptation preview :)\nNo message will be sent.";
  const errors = [];
  const check = (value, message) => { if (!value) errors.push(message); };
  let expectedCommand = null;
  if (action === "cancel") {
    const draft = textarea.value;
    check(draft.includes("\u2014") && draft.includes("\ud83d\ude42"), "Missing original synthetic draft");
    cancel.click();
    check(preview.classList.contains("verborgen"), "Cancel did not hide adaptation preview");
    check(textarea.value === draft, "Cancel changed the original draft");
    check(data.smsVerlauf.length === 0, "Cancel enqueued an SMS");
    send.click();
    check(!preview.classList.contains("verborgen") && textarea.value === draft,
      "Send must reopen adaptation preview without changing the draft");
    check(data.smsVerlauf.length === 0, "Send bypassed adjustment confirmation");
    check(preview.querySelector("pre").textContent === expectedText, "Incorrect adapted preview text");
  } else if (action === "confirm") {
    confirm.click();
    const entry = data.smsVerlauf[0];
    check(data.smsVerlauf.length === 1 && entry.text === expectedText && entry.status === "queued",
      "Confirmation must enqueue exactly one adapted synthetic SMS");
    check(send.disabled, "Send must await the mock acknowledgement");
    expectedCommand = {cmd: "kde_sms_senden", nummer: "+12025550123", text: expectedText,
      clientRef: entry?.clientRef, land: "DE"};
  } else if (action === "ack") {
    check(data.smsVerlauf.length === 1 && data.smsVerlauf[0].status === "queued" &&
      data.smsVerlauf[0].text === expectedText, "Mock acknowledgement must not claim actual delivery");
  } else throw new Error("Unknown functional test action");
  check(data.smsPlanung.length === 0, "Functional test must not schedule an SMS");
  return {action, errors, expectedCommand, draft: textarea.value, sendDisabled: send.disabled};
};
