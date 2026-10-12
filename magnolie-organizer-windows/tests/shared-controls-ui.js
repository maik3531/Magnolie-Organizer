// Exercise real DOM controls against delayed native status/receipt callbacks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const { webcrypto } = require('node:crypto');
for (const web of [path.join(__dirname, '../app/web'), path.join(__dirname, '../../magnolie-organizer/web')]) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), {
    runScripts: 'outside-only', url: 'https://app.magnolie.invalid/', pretendToBeVisual: true });
  const w = dom.window, sent = [];
  try {
    Object.defineProperty(w, 'crypto', { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.__MAGNOLIE_BRUECKE__ = 'test'; w.webkit = { messageHandlers: { test: { postMessage(value) {
      sent.push(typeof value === 'string' ? JSON.parse(value) : value);
    } } } };
    w.eval(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8')); w.MagnolieI18n.setLocale('en');
    w.eval(fs.readFileSync(path.join(web, 'anwendung.js'), 'utf8'));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded')); w.App.init({ daten: {}, neu: false });
    const values = { content_mode: 'phone_scope', auto_mode: 'manual', skip_deletions: true,
      custom_enabled: false, time_enabled: false, time_mode: 'phone_import' };
    const peer = { device_id: '11111111-1111-4111-8111-111111111111', fingerprint: 'PIN',
      display_name: 'Synthetic phone', state: 'online_wifi', own_device: true, remote_own_device: true,
      local_grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true } },
      grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true } },
      shared_sync: { supported: true, initialized: true, ready: true, values } };
    w.App.telefonStand({ peers: [structuredClone(peer)] });
    w.OrganizerTest.oeffneGeraeteDialog({ kennung: peer.device_id, name: peer.display_name });
    const skip = w.document.querySelector('[data-shared-sync-field="skip_deletions"]');
    assert.ok(skip && !skip.parentElement.hidden, 'Skip deletions must be visible in the Notes collection');
    skip.checked = false; skip.dispatchEvent(new w.Event('change'));
    const change = sent.findLast(value => value.cmd === 'personal_sync_gemeinsam_aendern');
    assert.ok(change.requestId); assert.equal(change.wert, false);
    assert.equal(skip.checked, false); assert.equal(skip.disabled, true);
    w.App.telefonStand({ peers: [structuredClone(peer)] });
    assert.equal(skip.checked, false, 'A delayed pre-save status must not undo the pending choice');
    w.App.gemeinsameSyncGespeichert({ kennung: peer.device_id, feld: 'skip_deletions', requestId: 'obsolete', ok: false });
    assert.equal(skip.disabled, true);
    const changed = { ...peer.shared_sync, values: { ...values, skip_deletions: false } };
    w.App.gemeinsameSyncGespeichert({ kennung: peer.device_id, feld: 'skip_deletions', requestId: change.requestId,
      ok: true, status: structuredClone(changed) });
    assert.equal(skip.disabled, false); assert.equal(skip.checked, false);
    w.App.telefonStand({ peers: [{ ...structuredClone(peer), shared_sync: structuredClone(changed) }] });
    assert.equal(skip.checked, false);
    skip.checked = true; skip.dispatchEvent(new w.Event('change'));
    const failed = sent.findLast(value => value.cmd === 'personal_sync_gemeinsam_aendern');
    w.App.gemeinsameSyncGespeichert({ kennung: peer.device_id, feld: 'skip_deletions', requestId: failed.requestId,
      ok: false, fehler: 'Synthetic save failure' });
    assert.equal(skip.disabled, false); assert.equal(skip.checked, false, 'A failed write returns to the persisted choice');
    w.App.telefonPairingCode({ attempt_id: 'attempt', code: '123 456', confirmation_required: false });
    let buttons = [...w.document.querySelectorAll('#telefon-pairing-dialog button')].map(button => button.textContent);
    assert.ok(!buttons.includes('Codes match'), 'The initiating desktop displays the code without a second approval');
    assert.ok(w.document.querySelector('#telefon-pairing-dialog').textContent.includes('other device'));
    w.App.telefonPairingCode({ attempt_id: 'attempt', code: '123 456', confirmation_required: true });
    buttons = [...w.document.querySelectorAll('#telefon-pairing-dialog button')].map(button => button.textContent);
    assert.ok(buttons.includes('Codes match'));
  } finally { w.close(); }
}
console.log('Shared controls and counterpart-only pairing: both desktop sources PASS');
