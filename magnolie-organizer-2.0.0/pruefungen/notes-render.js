/* Real-render regression; run in a fresh test-host WebView, never a user profile. */
async function pruefeNotizlinienRender() {
  const check = (value, label) => { if (!value) throw Error(label); };
  const wait = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const evidence = [];
  App.init({daten: {notizen: [{id: 'ruling-test', titel: 'Ruling', text: 'Magnolie', html: 'Magnolie'}]},
    neu: false, regional: {language: 'en', timeZone: 'UTC'}});
  OrganizerTest.oeffneBuch();
  OrganizerTest.wechsel('notizen');
  await wait();
  const note = document.querySelector('#notiz-text');
  check(note, 'standard note editor missing');
  const face = [...document.fonts].find(f => f.family.includes('Magnolie Handschrift'));
  check(face && face.status === 'unloaded', 'cold bundled font required');
  const text = 'Magnolie schreibt einen langen Satz, der im schmalen Pr\u00fcffeld automatisch umbrechen muss. ';
  async function measure(editor, font, size, scale, sample = text) {
    document.body.dataset.schrift = font;
    document.body.dataset.groesse = size;
    editor.style.fontSize = '';
    editor.style.fontSize = (parseFloat(getComputedStyle(editor).fontSize) * scale) + 'px';
    editor.style.width = '280px';
    editor.replaceChildren();
    const markers = [];
    for (const content of [sample, 'Magnolie', sample]) {
      const line = document.createElement('span');
      line.textContent = content;
      const marker = document.createElement('span');
      Object.assign(marker.style, {display: 'inline-block', width: '0', height: '0', verticalAlign: 'baseline'});
      line.append(marker);
      editor.append(line, document.createElement('br'));
      markers.push(marker);
    }
    OrganizerTest.aktualisiereNotizlinien();
    const style = getComputedStyle(editor);
    const family = style.fontFamily;
    await document.fonts.load(`${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${family}`, sample);
    await document.fonts.ready;
    await wait();
    // No manual remeasurement here: a cold face must repair its own ruler.
    const period = parseFloat(style.getPropertyValue('--zeilenhoehe'));
    const offset = parseFloat(style.getPropertyValue('--linien-stelle'));
    const baselines = markers.map(m => m.getBoundingClientRect().top - editor.getBoundingClientRect().top);
    const errors = baselines.map(b => { const d = ((b - offset) % period + period) % period; return Math.min(d, period - d); });
    check(style.fontFamily === family, 'font substitution');
    if (font === 'handwriting') check(face.status === 'loaded' && family.includes('Magnolie Handschrift'), 'bundled font not loaded');
    const row = {editor: editor.id || 'custom', font, size, scale, sample, family, period, offset, baselines, errors};
    evidence.push(row);
    check(errors.every(error => error <= 1.6), JSON.stringify(row));
  }
  await measure(note, 'handwriting', 'small', 1);
  for (const font of ['print', 'handwriting']) for (const size of ['small', 'medium', 'large']) {
    for (const scale of [1, 1.25, 1.5]) await measure(note, font, size, scale);
  }
  const data = OrganizerTest.daten();
  data.einstellungen.allgemein.customTab.enabled = true;
  OrganizerTest.oeffneCustomDesigner();
  data.customOrganizer.modules = [];
  const select = document.querySelector('.custom-designer-werkzeuge select');
  select.value = 'notes';
  document.querySelector('.custom-designer-werkzeuge button').click();
  data.customOrganizer.modules[0].items = [{id: 'custom-ruling', title: 'Ruling', text: 'Magnolie', html: '<p>Magnolie</p>'}];
  document.querySelector('.custom-designer-kopf button').click();
  OrganizerTest.wechsel('custom');
  await wait();
  const custom = document.querySelector('#inhalt-links .custom-text-editor');
  check(custom, 'custom editor missing');
  for (const font of ['print', 'handwriting']) for (const size of ['small', 'medium', 'large']) {
    for (const scale of [1, 1.25, 1.5]) await measure(custom, font, size, scale);
  }
  const height = custom.getBoundingClientRect().height;
  document.body.dataset.linien = 'aus';
  check(getComputedStyle(custom).backgroundImage === 'none', 'global lines off');
  custom.dataset.lines = 'on';
  check(getComputedStyle(custom).backgroundImage !== 'none', 'custom lines on');
  custom.dataset.lines = 'off';
  check(getComputedStyle(custom).backgroundImage === 'none', 'custom lines off');
  check(custom.getBoundingClientRect().height === height, 'line toggle changes geometry');
  check(getComputedStyle(custom).backgroundAttachment === 'local', 'custom scroll ruling');
  return evidence;
}
