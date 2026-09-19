/* Native regression for the recurring-month redraw loop. Synthetic data only. */
"use strict";
(async () => {
  const send = value => window.webkit.messageHandlers.planner_probe.postMessage(JSON.stringify(value));
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const T = OrganizerTest, requests = [], NativeWorker = Worker;
  window.Worker = class extends NativeWorker {
    postMessage(data, ...args) {
      if (data.key) requests.push(data.key);
      super.postMessage(data, ...args);
    }
  };
  const status = () => ({ requests: requests.length,
    duplicates: requests.length - new Set(requests).size,
    pending: [...(T.icsRuntime.state?.jobs.values() || [])].filter(job => job.status === "pending").length,
    rows: document.querySelectorAll(".termin-uebersicht .ue-termin").length,
    busy: document.body.getAttribute("aria-busy"), recurrenceError: T.icsRuntime.lastError });
  const click = selector => new Promise((resolve, reject) => {
    const button = document.querySelector(selector);
    assert(button, "Missing target: " + selector);
    const rect = button.getBoundingClientRect(), x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    assert(rect.width && rect.height && button.contains(document.elementFromPoint(x, y)), "Covered target: " + selector);
    const timer = setTimeout(() => { document.removeEventListener("click", done); reject(new Error("Native click timeout: " + selector)); }, 3000);
    const done = event => {
      if (!event.target.closest(selector)) return;
      clearTimeout(timer); document.removeEventListener("click", done);
      if (!event.isTrusted) reject(new Error("Untrusted click"));
      else queueMicrotask(resolve);
    };
    document.addEventListener("click", done);
    send({ probe: "native-click", selector, x, y });
  });
  const ready = async expectedRows => {
    const deadline = performance.now() + 12000;
    let stableSince = 0, previous = -1;
    while (performance.now() < deadline) {
      const state = status();
      if (!state.pending && !T.icsRuntime.state?.paint && previous === state.requests &&
          (expectedRows === undefined || state.rows === expectedRows)) {
        stableSince ||= performance.now();
        if (performance.now() - stableSince >= 250) return;
      } else stableSince = 0;
      previous = state.requests;
      await wait(25);
    }
    throw new Error("Calendar did not become quiet: " + JSON.stringify(status()));
  };
  const snapshot = name => new Promise(resolve => {
    window.plannerSnapshotDone = resolve; send({ probe: "snapshot", name });
  });
  try {
    const data = { termine: Array.from({ length: 32 }, (_, index) => ({
      id: "series-" + index, uid: "series-" + index + "@example.invalid", titel: "Recurring " + index,
      datum: "2027-01-01", zeit: "09:00", endZeit: "10:00",
      icsRoundtrip: ["DTSTART:20270101T090000Z", "DURATION:PT1H", "RRULE:FREQ=WEEKLY;COUNT=52"]
    })), einstellungen: { ansicht: "month", allgemein: { handbuchHinweisGezeigt: true, wetter: false } } };
    send({ probe: "synthetic-profile", data });
    T.zustand().sektion = "notizen";
    App.init({ daten: data, neu: false, handbuchInstalliert: true,
      regional: { language: "de", timeZone: "UTC" } });
    Object.assign(T.zustand().kalender, { jahr: 2027, monat: 0, tag: "2027-01-15", ansicht: "month", uebersichtAb: null });
    await click("#deckel"); await wait(1600);
    assert(document.querySelector("#deckel").classList.contains("weg"), "Cover did not open");
    const stored = JSON.stringify(T.daten().termine);
    await click('[data-fokus="register:kalender"]');
    await ready(160);
    assert(status().duplicates === 0, "Repeated requests for unchanged series: " + JSON.stringify(status()));
    const quietRequests = requests.length;
    await wait(750);
    assert(requests.length === quietRequests && status().busy === "false", "Recurrence work restarted without input");
    await snapshot("month-recurring-quiet");
    send({ probe: "month-quiet", ...status() });
    for (const view of ["week", "day"]) {
      await click('[data-ansicht="' + view + '"]');
      await ready();
      assert(T.zustand().kalender.ansicht === view, "View did not change: " + view);
      assert(T.termineAm("2027-01-15", true).length === 32, "View lost recurring appointments: " + view);
    }
    await click('[data-fokus="register:notizen"]');
    assert(T.zustand().sektion === "notizen", "Leaving calendar failed");
    assert(JSON.stringify(T.daten().termine) === stored, "Stored recurrence data changed");
    send({ probe: "done", ok: true, scope: "native-month-recurrence", dataUnchanged: true, ...status() });
  } catch (error) {
    send({ probe: "failure", error: String(error) + "\n" + String(error.stack || ""), ...status() });
  }
})();
