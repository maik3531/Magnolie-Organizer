/* Run only in an ephemeral source-test WebView. */
function pruefeCustomDesigner() {
  const check = (ok, message) => { if (!ok) throw Error(message); };
  App.init({daten: {}, neu: false, regional: {language: 'en', timeZone: 'UTC'}});
  OrganizerTest.oeffneBuch();
  const data = OrganizerTest.daten();
  data.einstellungen.allgemein.customTab.enabled = true;
  data.customOrganizer.modules = [];
  OrganizerTest.oeffneCustomDesigner();
  const type = document.querySelector('.custom-designer-werkzeuge select');
  const add = value => {
    type.value = value;
    document.querySelector('.custom-designer-werkzeuge button').click();
  };
  const cards = () => [...document.querySelectorAll('.custom-editor-karte')];
  const card = module => cards().find(c => c.dataset.moduleId === module.id);
  const move = (module, side) => {
    const select = card(module).querySelector('select');
    select.focus(); select.value = side; select.dispatchEvent(new Event('change'));
    check(document.activeElement === select, 'move loses DOM focus');
    check(card(module).querySelector('select') === select, 'move replaces editable controls');
    return select;
  };
  add('notes'); add('tasks'); add('appointments');
  const [note, task, appointment] = data.customOrganizer.modules;
  check(note.page === 'left' && task.page === 'right' && appointment.page === 'right', 'default sides');
  check(!document.querySelector('.custom-layout-vorschau'), 'extra readonly preview');
  note.items = [{id: 'stable-text', title: 'Keep', text: 'Keep text', html: '<p>Keep text</p>'}];
  note.lines = 'off';
  const original = JSON.stringify(note.items);
  move(task, 'left');
  check(task.page === 'left', 'valid move rejected');
  move(appointment, 'left');
  check(appointment.page === 'right', 'overfull page accepted');
  add('notes');
  const second = data.customOrganizer.modules[3];
  check(second.page === 'right', 'second text not opposite');
  move(note, 'right');
  check(note.page === 'left', 'two texts allowed on one page');
  add('tasks'); add('appointments'); add('notes');
  check(data.customOrganizer.modules.length === 4, 'module limits lost');
  const title = card(note).querySelector('input[type=text]');
  title.value = 'Edited'; title.dispatchEvent(new Event('input'));
  check(note.title === 'Edited' && JSON.stringify(note.items) === original && note.lines === 'off', 'edit changes stored text/overrides');
  const domOrder = cards().map(c => c.dataset.moduleId);
  const expected = [...data.customOrganizer.modules].sort((a, b) => a.page.localeCompare(b.page) || a.order - b.order).map(m => m.id);
  check(JSON.stringify(domOrder) === JSON.stringify(expected), 'DOM order differs from main custom tab');
  const dialog = document.querySelector('.custom-designer');
  const rect = dialog.getBoundingClientRect();
  check(rect.left >= 0 && rect.right <= innerWidth + 1 && rect.top >= 0 && rect.bottom <= innerHeight + 1, 'dialog outside screen');
  check(dialog.scrollWidth <= dialog.clientWidth + 1, 'horizontal overflow');
  const columns = [...document.querySelectorAll('.custom-designer-blatt')].map(c => c.getBoundingClientRect());
  if (innerWidth > 700) {
    check(rect.width >= Math.min(1000, innerWidth - 100), 'generic dialog width overrides designer');
    check(Math.abs(columns[0].top - columns[1].top) < 1 && columns[0].right < columns[1].left, 'columns not side by side');
    check(Math.abs(columns[0].width - columns[1].width) < 1, 'column widths differ');
  } else check(columns[1].top >= columns[0].bottom, 'mobile columns do not stack');
  if (innerWidth === 1920 && innerHeight >= 1080) check(dialog.scrollHeight <= dialog.clientHeight + 1, 'avoidable desktop scroll');
  for (const control of dialog.querySelectorAll('input, select, button')) {
    control.focus();
    check(document.activeElement === control, 'control cannot receive focus');
    check(control.getBoundingClientRect().width > 0, 'control has zero width');
  }
  const result = {viewport: [innerWidth, innerHeight], dialog: [rect.width, rect.height], scroll: [dialog.clientHeight, dialog.scrollHeight], cards: cards().length};
  const controls = [...dialog.querySelectorAll('button, input, select')];
  controls[controls.length - 1].focus();
  document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true}));
  check(document.activeElement === controls[0], 'forward modal focus wrap');
  controls[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', shiftKey: true, bubbles: true, cancelable: true}));
  check(document.activeElement === controls[controls.length - 1], 'backward modal focus wrap');
  document.querySelector('.custom-designer-kopf button').click();
  OrganizerTest.wechsel('custom');
  for (const [side, id] of [['left', 'inhalt-links'], ['right', 'inhalt-rechts']]) {
    const actual = [...document.querySelectorAll('#' + id + ' > .custom-modul')];
    const modules = data.customOrganizer.modules.filter(m => m.page === side).sort((a, b) => a.order - b.order);
    check(actual.length === modules.length && actual.every((element, index) => element.classList.contains('custom-modul-' + modules[index].type)), 'main tab differs from designer');
  }
  check(document.querySelector('#inhalt-links .custom-text-editor').dataset.lines === 'off', 'main tab loses line override');
  return result;
}
