// Refs #720. Shared by the source and isolated native WebKit probes.
function notesDateSearchProbe() {
  const stamp = (iso) => Date.parse(iso);
  const notes = [
    { id: "sept", titel: "Planung", text: "Besprechung", angelegt: stamp("2026-09-18T12:00:00Z"), geaendert: "2026-10-02" },
    { id: "edge-in", titel: "Nach Mitternacht", angelegt: stamp("2026-08-31T22:30:00Z"), geaendert: "2026-10-02" },
    { id: "edge-out", titel: "Schon Oktober", angelegt: stamp("2026-09-30T22:00:00Z"), geaendert: "2026-10-02" },
    { id: "leap", titel: "Schalttag", geaendert: "2024-02-29" },
    { id: "edited", titel: "Später bearbeitet", angelegt: stamp("2026-05-01T08:00:00Z"), personalGeaendert: stamp("2026-09-30T21:59:59Z") },
    { id: "missing", titel: "Ohne Datum", angelegt: 0, geaendert: "" }
  ];
  const regional = { language: "en", timeZone: "Europe/Berlin" };
  App.init({ neu: false, regional, daten: { einstellungen: { regional, notizUebersicht: { view: "days" } }, notizen: notes } });
  OrganizerTest.oeffneBuch();
  OrganizerTest.wechsel("notizen");
  const data = OrganizerTest.daten();
  const unchanged = JSON.stringify(data.notizen);
  const errors = [];
  let checks = 0;
  const equal = (actual, expected, label) => {
    checks++;
    if (JSON.stringify(actual) !== JSON.stringify(expected)) errors.push({ label, actual, expected });
  };
  function search(query) {
    const input = document.querySelector("#notiz-suche");
    if (!input) throw new Error("Notes search did not render");
    input.value = query;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    const ids = new Set([...document.querySelectorAll(".notiz-uebersicht [data-notiz-id]")].map(row => row.dataset.notizId));
    return notes.filter(note => ids.has(note.id)).map(note => note.id);
  }
  const unknown = data.notizen.find(note => note.id === "missing");
  equal([unknown.angelegt, unknown.personalGeaendert, unknown.geaendert], [0, 0, ""], "unknown date remains unknown");
  for (const view of ["days", "default"]) {
    data.einstellungen.notizUebersicht.view = view;
    const all = notes.map(note => note.id);
    const september = ["sept", "edge-in", "edited"];
    for (const [query, expected] of [
      ["09.2026", september], ["09.26", september], ["2026-09", september], [" 9.26. ", september],
      ["18.9.26", ["sept"]], ["2026-10-01", ["edge-out"]], ["29.02.2024", ["leap"]], ["29.02.2026", []],
      ["01.1970", []], ["2026", ["sept", "edge-in", "edge-out", "edited"]], ["besprechung", ["sept"]],
      ["planung besprechung", ["sept"]], [data.notizbuecher[0].name, all], ["", all]
    ]) equal(search(query), expected, `${view}: ${query}`);
  }
  equal(JSON.stringify(data.notizen), unchanged, "search does not modify stored notes");
  return { checks, errors };
}
