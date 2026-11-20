'use strict';
const language = document.documentElement.lang;
const buttons = document.querySelectorAll('[data-screen]');
buttons.forEach(button => button.addEventListener('click', () => {
  const selected = button.dataset.screen;
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.querySelectorAll('[data-panel]').forEach(panel => panel.hidden = panel.dataset.panel !== selected);
}));
const shareButton = document.querySelector('[data-share]');
if (shareButton) shareButton.addEventListener('click', async () => {
  const url = new URL(window.location.href);
  url.hash = '';
  url.search = '';
  const text = language === 'de'
    ? 'Magnolie Organizer: Kalender, Aufgaben, Kontakte und Notizen mit Buchgefühl. Kostenlos für Linux und Windows, mit lokaler Datenhaltung.'
    : 'Magnolie Organizer: calendars, tasks, contacts and notes with the feel of a paper planner. Free for Linux and Windows, with local storage.';
  const status = document.querySelector('[data-share-status]');
  try {
    await navigator.clipboard.writeText(text + '\n' + url);
    status.textContent = language === 'de' ? 'Text und Link kopiert.' : 'Text and link copied.';
  } catch {
    const fallback = document.querySelector('[data-share-fallback]');
    fallback.hidden = false;
    fallback.textContent = text + '\n' + url;
    status.textContent = language === 'de' ? 'Bitte Text und Link unten kopieren.' : 'Please copy the text and link below.';
  }
});
