using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static partial class UiSelfTest
{
    // Refs #101 / #214: real packaged WebView2, private profile, synthetic phone
    // replies only. All book saves and pre-import checkpoints use the native bridge.
    private static async Task TestContactImportAsync(Microsoft.Web.WebView2.Core.CoreWebView2 core, WindowsPaths paths)
    {
        await core.ExecuteScriptAsync("""
            window.contactUiResult = null;
            (async () => {
              const check = (value, message) => { if (!value) throw new Error(message); };
              const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right);
              const wait = async predicate => {
                const until = Date.now() + 10000;
                while (!predicate()) {
                  check(Date.now() < until, 'Native contact UI deadline');
                  await new Promise(resolve => setTimeout(resolve, 20));
                }
              };
              const handler = window.webkit.messageHandlers[window.__MAGNOLIE_BRUECKE__ || 'bridge'];
              const send = handler.postMessage.bind(handler);
              const setPhone = App.telefonStand.bind(App);
              const fingerprint = 'a'.repeat(64);
              const cases = [];
              let current;
              App.telefonStand = () => {};
              handler.postMessage = serialized => {
                const request = JSON.parse(serialized);
                if (request.cmd !== 'telefon_kontakte') return send(serialized);
                const state = current;
                if (request.uids) state.batches.push(request.uids.slice());
                else state.indexes++;
                const reply = { ok: true, requestId: request.requestId, device_id: state.device, fingerprint,
                  contacts: request.uids ? request.uids.map(uid => state.cards.find(card => card.uid === uid)) :
                    state.cards.map(card => ({ uid: card.uid, modified_ms: 1 })) };
                if (state.mode === 'denied') { reply.ok = false; reply.fehler = 'Synthetic permission denied'; }
                if (request.uids && state.mode === 'pending' && request.uids.includes('card-5')) {
                  state.pending = reply; return;
                }
                setTimeout(() => App.telefonKontakte(reply), 10);
              };
              try {
                for (const provider of ['kde', 'notes']) {
                  for (const mode of ['complete', 'pending', 'invalid', 'denied', 'incoming', 'clear', 'keep']) {
                    const grouping = ['incoming', 'clear', 'keep'].includes(mode);
                    const device = provider === 'notes' ? 'notes:11111111-1111-4111-8111-111111111111' : 'synthetic-kde';
                    current = { mode, device, cards: [], batches: [], indexes: 0 };
                    for (let index = 0; index < (grouping ? 1 : 6); index++) {
                      const uid = 'card-' + index;
                      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(provider + '-contact-v1\0' + device + '\0' + fingerprint + '\0' + uid));
                      const hash = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
                      current.cards.push({ uid, bindung: 'urn:magnolie:import:' + provider + ':' + hash,
                        kontakt: { vorname: 'Synthetic ' + index, email: 'fixture' + index + '@example.test',
                          vcardRoundtrip: mode === 'clear' ? [] : ['CATEGORIES:Arbeit'] } });
                    }
                    if (mode === 'invalid') current.cards[5].bindung = 'urn:magnolie:import:' + provider + ':' + '0'.repeat(64);
                    App.init({ daten: { kontakte: grouping ? [{ id: 'local-synthetic', vorname: 'Synthetic 0',
                      email: 'fixture0@example.test', vcardRoundtrip: ['CATEGORIES:Kollegen', 'X-LOCAL:preserve'] }] : [],
                      einstellungen: { adressen: { foto: false, fotoVoreinstellung: 1 } } },
                      neu: false, regional: { language: 'en', timeZone: 'UTC' } });
                    if (grouping) check(OrganizerTest.daten().kontakte[0].email === 'fixture0@example.test',
                      'Synthetic matching address was rejected by product normalization');
                    setPhone(provider === 'notes' ? { peers: [{ device_id: device.slice(6), state: 'online_wifi', own_device: true,
                      remote_own_device: true, contacts_read_available: true, contacts_fingerprint: fingerprint }],
                      kdeconnect: { contacts_available: false } } :
                      { peers: [], kdeconnect: { contacts_available: true, contacts_device_id: device } });
                    OrganizerTest.baueEinstellungen();
                    document.querySelector('#einst-tab-sync').click();
                    document.querySelector('#kde-kontakte-abrufen').click();
                    await wait(() => document.querySelector('.kontakt-import-dialog'));
                    const dialog = document.querySelector('.kontakt-import-dialog');
                    const apply = dialog.querySelector('.hauptknopf');
                    const cancel = Array.from(dialog.querySelectorAll('.dialog-knoepfe button')).find(button => button !== apply);
                    if (mode === 'pending') {
                      await wait(() => current.pending);
                      check(apply.disabled && !OrganizerTest.daten().kontakte.length, 'Pending cards allowed adoption');
                      cancel.click();
                      App.telefonKontakte(current.pending);
                      check(!document.querySelector('.kontakt-import-dialog') && !OrganizerTest.daten().kontakte.length, 'Late reply revived cancelled import');
                    } else if (mode === 'invalid' || mode === 'denied') {
                      await wait(() => /Conflict|denied|incomplete/.test(dialog.querySelector('.einst-hinweis').textContent));
                      check(apply.disabled && !OrganizerTest.daten().kontakte.length, 'Invalid/denied preview allowed adoption');
                      cancel.click();
                    } else {
                      await wait(() => !apply.disabled);
                      check(dialog.querySelectorAll('details').length === current.cards.length, 'Incomplete preview card count');
                      if (mode === 'complete') {
                        check(current.batches.length === (provider === 'notes' ? 6 : 2), 'Wrong native card request batching');
                        check(current.batches.every(batch => batch.length <= (provider === 'notes' ? 1 : 5)), 'Native card deadline multiplied');
                        cancel.click();
                      } else {
                        check(equal(OrganizerTest.kontaktGruppen(OrganizerTest.daten().kontakte[0]), ['Colleagues']), 'Preview changed saved groups');
                        const row = Array.from(dialog.querySelectorAll('.formzeile')).find(row => row.textContent.startsWith('Contact groups'));
                        check(row, 'Missing dedicated group decision: ' + dialog.textContent);
                        dialog.querySelector('details').open = true;
                        row.scrollIntoView({ block: 'center' });
                        const select = row.querySelector('select');
                        check(select.getBoundingClientRect().width > 0, 'Group choice has no native layout');
                        if (mode === 'clear') check(Array.from(select.options).some(option => option.value === 'incoming' && option.textContent.includes('No contact group')), 'Missing readable empty-group choice');
                        select.value = mode === 'keep' ? 'keep' : 'incoming';
                        select.dispatchEvent(new Event('change', { bubbles: true }));
                        apply.click();
                        await wait(() => !document.querySelector('.kontakt-import-dialog'));
                        const contact = OrganizerTest.daten().kontakte[0];
                        check(equal(OrganizerTest.kontaktGruppen(contact), mode === 'keep' ? ['Colleagues'] : mode === 'clear' ? [] : ['Work']), 'Native group Apply lost decision');
                        check(contact.vcardRoundtrip.includes('X-LOCAL:preserve'), 'Unrelated vCard information lost');
                      }
                    }
                    cases.push({ provider, mode, cards: current.cards.length, batches: current.batches.map(batch => batch.length) });
                  }
                }
                window.contactUiResult = { ok: true, cases, finalRoundtrip: OrganizerTest.daten().kontakte[0].vcardRoundtrip };
              } catch (error) {
                window.contactUiResult = { ok: false, error: String(error) + '\n' + (error.stack || ''), cases };
              } finally { handler.postMessage = send; App.telefonStand = setPhone; }
            })();
            """);
        var watch = System.Diagnostics.Stopwatch.StartNew();
        while (watch.Elapsed < TimeSpan.FromSeconds(100))
        {
            var raw = await core.ExecuteScriptAsync("window.contactUiResult");
            if (raw != "null")
            {
                using var result = JsonDocument.Parse(raw);
                Test(result.RootElement.GetProperty("ok").GetBoolean(), "Native contact scenario failed: " + raw);
                Test(result.RootElement.GetProperty("cases").GetArrayLength() == 14, "Missing native contact cases: " + raw);
                using var saved = JsonDocument.Parse(await File.ReadAllTextAsync(paths.Data));
                var contacts = saved.RootElement.GetProperty("kontakte");
                Test(contacts.GetArrayLength() == 1, "Private native book did not persist the final contact.");
                var expected = result.RootElement.GetProperty("finalRoundtrip").EnumerateArray().Select(value => value.GetString());
                var actual = contacts[0].GetProperty("vcardRoundtrip").EnumerateArray().Select(value => value.GetString());
                Test(actual.SequenceEqual(expected), "Native disk readback differs from the acknowledged group decision.");
                Console.WriteLine("WINDOWS-CONTACT-PREVIEW-GROUPS-OK " + raw);
                return;
            }
            await Task.Delay(100);
        }
        Test(false, "Native contact scenario exceeded its deadline.");
    }
}
