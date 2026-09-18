/* Android adapter, not an application fork. OrganizerTest is the existing shared core API. */
(() => {
  'use strict';
  const document = window.document;
  const name = 'Magnolie Organizer Android Tablet Beta 2.0.18Beta';
  const supported = new Set(['bereit','speichern','beenden_bereit','beenden_abgebrochen',
    'drucken','ablage_kopieren','ablage_holen','tablet_import','tablet_export',
    'tablet_notifications','tablet_about','tablet_replace','tablet_import_cancel','erinnerung_einrichten','tablet_loaded']);
  const rejected = new Set();
  let loaded = false, pendingAction = null, replacement = null;
  let session = null, revision = null, blocked = false;
  const tr = text => window.MagnolieI18n?.gettext(text) || text;
  function beta(index) {
    const lang = window.MagnolieI18n?.locale() || navigator.language;
    const code = /^zh/i.test(lang) ? 'zh_CN' : lang.split('-')[0];
    return (window.TabletStrings[code] || window.TabletStrings.en)[index];
  }
  function status(text) {
    const el = document.getElementById('tablet-status');
    if (el) el.textContent = text;
  }
  function native(message) {
    if (blocked) throw Error(tr('Warning: The data could not be saved.'));
    if (!window.TabletNative) throw Error(tr('Warning: The data could not be saved.'));
    if (message.cmd !== 'bereit') Object.assign(message,{session,revision});
    window.TabletNative.postMessage(JSON.stringify(message));
  }
  function alarms() {
    const T = window.OrganizerTest, data = T.daten(), result = [];
    const settings = data.einstellungen.erinnerung;
    if (!settings.an) return result;
    const add = (item, time, section, custom, mode = '') => {
      if (!Number.isFinite(time) || time <= 0) return;
      // Keep existing due receipts valid; early alarms have their own namespace.
      result.push({id: section+':'+item.id+':'+(mode && mode !== 'due' ? mode+':' : '')+time, at:time,
        title: String(item.titel || tr('Untitled')).slice(0,300), section, custom});
    };
    const recurring = x => !Array.isArray(x.icsRoundtrip || []) ||
      (x.icsRoundtrip || []).some(line => /^\s*(RRULE|RDATE|EXDATE|EXRULE|RECURRENCE-ID)\b/i.test(line)) ||
      ['icsZusatzDaten','icsZusatzTermine','icsAusnahmen','icsAusnahmeTermine','icsOverrides','icsRangeOverrides']
        .some(key => (x[key] || []).length) || x.rrule ||
      (x.wiederholung?.art && !['none','keine'].includes(x.wiederholung.art));
    for (const item of data.termine.concat(T.customTermineFuerErinnerung())) {
      if (recurring(item)) continue;
      const time = +T.terminZeitpunkt(item);
      const offsets = new Set();
      if (!item.individuelleErinnerungTage || item.standardErinnerung !== false) offsets.add(settings.vorlauf);
      if (item.individuelleErinnerungTage) offsets.add(item.individuelleErinnerungTage*1440);
      for (const offset of offsets) add(item,time-offset*60000,'kalender',item.id.startsWith('custom:'));
      for (const alarm of item.alarme || []) if (alarm.bearbeitbar && alarm.aktiviert) {
        const base = alarm.related === 'END' ? +T.terminZeitpunkt({datum:item.endDatum || item.datum,
          zeit:item.endZeit || item.zeit}) : time;
        add(item,base-alarm.offsetMinuten*60000,'kalender',false);
      }
    }
    for (const item of data.aufgaben.concat(T.customAufgabenFuerErinnerung())) {
      const days = Number(item.individuelleErinnerungTage || 0);
      if (item.erledigt || !item.faellig || !item.erinnern && !days) continue;
      if (recurring(item)) { status(beta(0)); continue; }
      try {
        if (![0,1,2,3,4,5,6,7].includes(days)) throw Error('Invalid lead days');
        const lines = item.icsRoundtrip || [];
        if (!Array.isArray(lines) || lines.some(line => typeof line !== 'string' || !/^[A-Z][A-Z0-9-]*(?:;[^:\r\n]+)?:[^\r\n]*$/i.test(line))) throw Error('Invalid ICS');
        if (String(item.icsStatus || '').toUpperCase() === 'CANCELLED' ||
            lines.some(line => /^STATUS:(CANCELLED|COMPLETED)$/i.test(line))) continue;
        const starts=lines.filter(line => /^DTSTART[;:]/i.test(line));
        if (starts.length > 1) throw Error('Ambiguous DTSTART');
        if (starts.length) {
          const parsed = T.icsExpansion(item,-Infinity,Infinity,true);
          if (!parsed || parsed.length !== 1) throw Error('Invalid one-off ICS');
        }
        const dues = lines.filter(line => /^DUE[;:]/i.test(line));
        if (dues.length > 1) throw Error('Ambiguous DUE');
        // Reuse the canonical timezone resolver, but never pass it a recurrence rule.
        // Calendar-day subtraction happens in source wall time, not UTC elapsed hours.
        const at = lead => {
          let parameters = '', stamp;
          if (dues.length) {
            const raw = /^DUE((?:;(?:TZID="?[^";:\r\n]+"?|VALUE=DATE(?:-TIME)?))*):(\d{8}(?:T\d{4}(?:\d{2})?Z?)?)$/i.exec(dues[0]);
            if (!raw || /TZID=/i.test(raw[1]) && raw[2].endsWith('Z')) throw Error('Unsupported DUE');
            const keys=[...raw[1].matchAll(/;(TZID|VALUE)=/gi)].map(m=>m[1].toUpperCase());
            if (new Set(keys).size !== keys.length || /;VALUE=DATE(?:;|$)/i.test(raw[1]) && raw[2].length !== 8 ||
                raw[2].length === 8 && /TZID=|VALUE=DATE-TIME/i.test(raw[1])) throw Error('Conflicting DUE parameters');
            parameters = raw[1].replace(/;VALUE=DATE(?:-TIME)?/i,''); stamp = raw[2];
            if (stamp.length === 8) { parameters=''; stamp += 'T080000'; }
          } else {
            if (!/^\d{4}-\d{2}-\d{2}$/.test(item.faellig) || item.faelligZeit && !/^\d{2}:\d{2}(?::\d{2})?$/.test(item.faelligZeit)) throw Error('Invalid due date/time');
            stamp = item.faellig.replaceAll('-','')+'T'+(item.faelligZeit || '08:00').replaceAll(':','').padEnd(6,'0');
          }
          const iso = stamp.slice(0,4)+'-'+stamp.slice(4,6)+'-'+stamp.slice(6,8);
          const day = new Date(iso+'T00:00:00Z');
          if (!Number.isFinite(+day) || day.toISOString().slice(0,10) !== iso) throw Error('Invalid source date');
          day.setUTCDate(day.getUTCDate()-lead);
          const shifted = day.toISOString().slice(0,10).replaceAll('-','')+stamp.slice(8);
          const resolved = T.icsExpansion({icsRoundtrip:['DTSTART'+parameters+':'+shifted,'DURATION:PT0S'],
            icsTimezones:item.icsTimezones || []},-Infinity,Infinity);
          if (!resolved || resolved.length !== 1) throw Error('Unresolved source time');
          return resolved[0].icsStartUtc;
        };
        const due = at(0), early = days ? at(days) : null;
        const custom = item.id.startsWith('custom:');
        if (item.erinnern) add(item,due,'aufgaben',custom,'due');
        if (days) add(item,early,'aufgaben',custom,'early-'+days);
      } catch (_) { status(beta(0)); }
    }
    return [...new Map(result.map(x=>[x.id,x])).values()].sort((a,b)=>a.at-b.at);
  }
  function send(message) {
    if (!supported.has(message.cmd)) {
      rejected.add(message.cmd);
      status(beta(0)+' '+message.cmd);
      // Throw rather than let the desktop's Bruecke.sende report a false success.
      throw Error(beta(0));
    }
    if (message.cmd === 'speichern') {
      if (!loaded || replacement) throw Error(tr('Warning: The data could not be saved.'));
      message.alarms = alarms();
    }
    native(message);
  }
  window.webkit = {messageHandlers:{bridge:{postMessage: text => send(JSON.parse(text))}}};
  function action(cmd) {
    if (!loaded || replacement || pendingAction) return;
    // Reuse the desktop editor guard and its durable-save queue before opening SAF.
    pendingAction = cmd;
    window.MagnolieTabletActions.afterSave(() => {
      pendingAction = null; native({cmd});
    }).then(ok => { if (!ok) pendingAction = null; });
  }
  function initialize(payload) {
    if (session || blocked) return;
    if (typeof payload.session !== 'string' || typeof payload.revision !== 'string') throw Error('Missing native session');
    session=payload.session; revision=payload.revision;
    const T = window.OrganizerTest;
    let data = payload.daten;
    if (data === null) {
      data = T.leereDaten();
      data.einstellungen.regional.language = navigator.language;
      data.einstellungen.allgemein.hilfsrahmen = true;
      data.einstellungen.allgemein.handbuchHinweisGezeigt = true;
      data.einstellungen.update.automatisch = false;
      data.einstellungen.schrift.rechtschreibung = false;
    }
    // Desktop integration preferences are retained on disk, never advertised as Android services.
    try { if (payload.daten !== null) validateImport(JSON.stringify(data)); }
    catch (_) { blockStorage({text:tr('Import failed.'),outcome:'load-validation'}); return; }
    window.App.init({daten:data,neu:false,regional:data.einstellungen.regional,
      trayVerfuegbar:false,handbuchInstalliert:false,datenPfad:'Android / AES-GCM / Keystore'});
    status(beta(1));
    T.oeffneBuch();
    native({cmd:'tablet_loaded'});
    applyCapabilities();
  }
  function validateImport(text) {
    const input = JSON.parse(text), T = window.OrganizerTest;
    if (!input || input.version !== T.leereDaten().version) throw Error(tr('Import failed.'));
    for (const k of ['termine','aufgaben','kontakte','notizen']) if (!Array.isArray(input[k])) throw Error(tr('Import failed.'));
    const normalized = T.normalisiere(JSON.parse(text));
    // Reject lossy imports instead of quietly discarding invalid rows or nested attachments.
    function counts(before, after, path = '$') {
      if (Array.isArray(before)) {
        // Canonical contact normalization folds legacy telefon/mobil aliases into
        // the typed number, adding e.g. VOICE to CELL on a later load. This is
        // lossless metadata enrichment, not a dropped contact/attachment/row.
        if (/^\$\.kontakte\[\d+\]\.telefone\[\d+\]\.typen$/.test(path) &&
            Array.isArray(after) && before.every(x=>typeof x==='string' && after.includes(x)) &&
            after.every(x=>typeof x==='string') && after.length>=before.length) return;
        if (!Array.isArray(after) || before.length !== after.length) throw Error(tr('Import failed.')+' '+path);
        before.forEach((x,i)=>counts(x,after[i],path+'['+i+']'));
      } else if (before && typeof before === 'object') {
        for (const [k,v] of Object.entries(before)) {
          if (!after || !Object.hasOwn(after,k)) throw Error(tr('Import failed.')+' '+path+'.'+k);
          counts(v,after[k],path+'.'+k);
        }
      }
    }
    counts(input,normalized);
    return normalized;
  }
  function blockStorage(payload) {
    blocked=true; loaded=false; pendingAction=null;
    document.getElementById('schreibtisch').inert=true;
    document.querySelectorAll('[role=dialog]').forEach(el=>{el.inert=true;});
    status((payload.text || tr('Warning: The data could not be saved.'))+' ['+payload.outcome+']');
    if (!document.getElementById('tablet-reload')) {
      const reload=button(tr('Open organizer'),()=>location.reload()); reload.id='tablet-reload';
      document.getElementById('tablet-bar').append(reload);
    }
  }
  window.Tablet = {
    alarms, validateImport, action, rejected,
    flush() { if (loaded && !replacement) window.OrganizerTest.speichereJetzt(); },
    receive(message) {
      if (typeof message === 'string') message = JSON.parse(message);
      const p = message.payload;
      switch (message.callback) {
        case 'init': initialize(p); break;
        case 'ready':
          if (blocked || p.session !== session || p.revision !== revision) break;
          loaded=true; window.Tablet.flush(); break;
        case 'gespeichert':
          if (!loaded || blocked || p.session !== session || p.expectedRevision !== revision) break;
          if (p.reloadRequired) { blockStorage({text:p.fehler,outcome:p.outcome}); break; }
          if (p.ok) revision=p.revision; else pendingAction=null;
          window.App.gespeichert(p); break;
        case 'importCandidate':
          if (!loaded || blocked || replacement) break;
          try {
            validateImport(p.text);
            replacement = {token:p.token};
            // Native retains the selected bytes. Neither a replacement body nor authorization comes from imported JSON.
            native({cmd:'tablet_replace',token:p.token});
          } catch (_) { replacement = null; native({cmd:'tablet_import_cancel',token:p.token}); status(tr('Import failed.')); }
          break;
        case 'replaced':
          if (blocked || p.token !== replacement?.token) break;
          blockStorage({text:tr('Saved.'),outcome:'committed'}); location.reload(); break;
        case 'restoreFailed':
          if (p.token === replacement?.token) blockStorage(p); break;
        case 'storageBlocked': blockStorage(p); break;
        case 'cancelled':
          if (blocked || replacement && p.token !== replacement.token) break;
          replacement=null; pendingAction=null; status(tr('Cancel')); break;
        case 'clipboard': window.App.ablage({text:p}); break;
        case 'notificationConsent':
          if (!loaded || replacement || blocked || p.session !== session || p.revision !== revision) break;
          window.OrganizerTest.daten().einstellungen.erinnerung.an = p.enabled === true;
          window.Tablet.flush(); break;
        case 'notice': if (!blocked) status(tr(p)); break;
        case 'error': if (!blocked) { pendingAction=null; status(tr(p)); } break;
        default: throw Error('Unknown native callback');
      }
    }
  };
  if (window.TabletNative) window.TabletNative.onmessage = event => window.Tablet.receive(event.data);
  function button(label, fn) {
    const b = document.createElement('button'); b.className = 'knopf'; b.textContent = label;
    b.type = 'button'; b.addEventListener('click',fn); return b;
  }
  function applyCapabilities() {
    for (const id of ['sync','baum','sicherheit','ueber']) {
      const b = document.getElementById('einst-tab-'+id);
      if (b && !b.disabled) { b.disabled = true; b.title = beta(0); b.setAttribute('aria-disabled','true'); }
      const page = document.getElementById('einst-seite-'+id);
      if (page && !page.dataset.tablet) {
        page.dataset.tablet='true'; page.textContent=beta(0)+' '+beta(1);
      }
    }
    for (const id of ['import','export','erinnerung']) {
      const page = document.getElementById('einst-seite-'+id);
      if (!page || page.dataset.tablet) continue;
      page.dataset.tablet = 'true'; page.replaceChildren();
      const p = document.createElement('p'); p.textContent = beta(1); page.append(p);
      page.append(button(tr(id==='import'?'Import':id==='export'?'Export':'Notifications')+
        (id==='erinnerung'?'':' JSON'),()=>action('tablet_'+(id==='erinnerung'?'notifications':id))));
    }
    const unsupportedIds = ['schrift-pruefung','erinnerung-wecken','knopf-sicherung',
      'ort-abrufen','ort-jahre','adressen-brief','adressen-brief-layout',
      'adressen-karte','adressen-route','adressen-karten','adressen-soziale-symbole'];
    for (const id of unsupportedIds) {
      const b = document.getElementById(id);
      if (b && !b.disabled) { b.disabled = true; b.title = beta(0); }
    }
    const holidayAction = document.getElementById('ort-abrufen');
    if (holidayAction && !document.getElementById('tablet-holiday-limit')) {
      const hint = document.createElement('p'); hint.id='tablet-holiday-limit'; hint.textContent=beta(0);
      holidayAction.parentElement.before(hint);
    }
    // Contact communication buttons have no IDs and may contain icon labels.
    // Local phone/email fields remain editable; these actions have no native backend.
    for (const b of document.querySelectorAll('.kontakt-sms,.kontakt-anruf,.post-anschrift,.k-wege button')) {
      b.disabled=true; b.title=beta(0); b.setAttribute('aria-disabled','true');
    }
    for (const selector of ['#allgemein-gruppe-sicherung','#allgemein-gruppe-tray']) {
      document.querySelectorAll(selector+' input,'+selector+' button,'+selector+' select').forEach(b=>{
        b.disabled = true; b.title = beta(0);
      });
    }
    for (const b of document.querySelectorAll('button[id],input[id],select[id]')) {
      if (/(?:sicherung|cloud|journal|telefon|sms|handbuch|wetter|eds|contributor|medikament-such)/.test(b.id)) {
        b.disabled=true; b.title=beta(0);
      }
    }
    // These actions require native desktop services, unlike local binder editing.
    const labels = ['Synchronize','Send SMS','Call','Write a letter','Show on map','Route',
      'Check for updates','ODS','Export ODS','Import public holidays','Import school holidays'];
    for (const b of document.querySelectorAll('button')) if (labels.some(x=>b.textContent.trim()===tr(x)) && !b.disabled) {
      b.disabled = true; b.title = beta(0);
    }
    for (const b of document.querySelectorAll('input[type=file],.eingabe-datei-knopf,.notiz-anhang-symbol,.notiz-anhang-bild,.notiz-anhang-name')) {
      b.disabled=true; b.title=beta(0);
    }
    for (const b of document.querySelectorAll('.notiz-zusatz-knopf,#kontakt-foto-knopf')) {
      if ([tr('Image'),'PDF',tr('Choose photo…')].includes(b.textContent.trim())) {
        b.disabled=true; b.title=beta(0);
      }
    }
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const bar = document.createElement('aside'); bar.id = 'tablet-bar';
    const title = document.createElement('strong'); title.textContent = name;
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = tr('About');
    const info = document.createElement('p'); info.id='tablet-limits'; info.textContent=beta(1);
    const notice = document.createElement('p'); notice.id='tablet-status'; notice.setAttribute('role','status');
    details.append(summary,info);
    bar.append(title,button(tr('Import')+' JSON',()=>action('tablet_import')),
      button(tr('Export')+' JSON',()=>action('tablet_export')),
      button(tr('Notifications'),()=>action('tablet_notifications')),details,notice);
    document.body.prepend(bar);
    new MutationObserver(applyCapabilities).observe(document.body,{childList:true,subtree:true});
    document.addEventListener('contextmenu',event=>{
      if (event.target.closest('.kontakt-sms,.kontakt-anruf')?.disabled) {
        event.preventDefault(); event.stopImmediatePropagation(); status(beta(0));
      }
    },true);
    document.addEventListener('visibilitychange',()=>{if(document.hidden) window.Tablet.flush();});
    if (!window.TabletNative) {
      document.getElementById('schreibtisch').inert = true;
      status(tr('Warning: The data could not be saved.'));
    }
  });
})();
