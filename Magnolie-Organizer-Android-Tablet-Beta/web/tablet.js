/* Android adapter, not an application fork. OrganizerTest is the existing shared core API. */
(() => {
  'use strict';
  const document = window.document;
  const name = 'Magnolie Organizer Android Tablet Beta 2.0.30Beta';
  const supported = new Set(['bereit','speichern','beenden_bereit','beenden_abgebrochen',
    'drucken','ablage_kopieren','ablage_holen','tablet_import','tablet_export',
    'feiertage','tablet_notifications','tablet_about','tablet_replace','tablet_import_cancel','tablet_calendar_import_done','erinnerung_einrichten','tablet_loaded']);
  const davCommands = new Set(['baum_briefkasten_status','baum_briefkasten_speichern',
    'baum_briefkasten_pruefen','baum_dav_pruefen','eds_status']);
  const davCallbacks = new Set(['baumBriefkastenStatus','baumBriefkastenGespeichert',
    'baumBriefkastenPruefung','baumDavPruefung','edsStatus']);
  for (const command of davCommands) supported.add(command);
  const rejected = new Set();
  let loaded = false, pendingAction = null, replacement = null, pendingCalendar = null;
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
  const davNotice = 'Account setup and read-only discovery. Calendar/contact synchronization is not implemented.';
  window.TabletDav = Object.freeze({
    sourceView(payload, settings) {
      const value = payload && typeof payload==='object' ? payload : {};
      const list = (all, current) => (Array.isArray(value[all]) ? value[all] : Array.isArray(value[current]) ? value[current] : [])
        .filter(item=>item && typeof item.uid==='string' && item.uid).map(item=>({...item}));
      const calendars=list('alleKalender','kalender'), books=list('alleAdressbuecher','adressbuecher');
      const selected=Array.isArray(settings.kalenderUids) ? settings.kalenderUids : settings.kalenderUid ? [settings.kalenderUid] : [];
      const retain=(target,id)=>{
        if (typeof id==='string' && id && !target.some(item=>item.uid===id))
          target.push({uid:id,name:tr('Unavailable')+' — '+id,quelle:'unavailable',unavailable:true});
      };
      for (const id of selected) retain(calendars,id);
      retain(books,settings.adressbuchUid);
      return {...value,alleKalender:calendars,alleAdressbuecher:books,
        buchOk:value.buchOk===true || books.length>0};
    },
    sourcesRendered(payload) {
      const start=document.getElementById('sync-jetzt');
      if (start) { start.disabled=true; start.title=davNotice; start.setAttribute('aria-disabled','true'); }
      const target=document.getElementById('sync-status');
      if (target) target.textContent=(typeof payload?.fehler==='string' && payload.fehler ? payload.fehler+' ' : payload?.verfuegbar===false ? tr('Unavailable')+'. ' : '')+davNotice;
    },
    accountRendered(account) {
      const form=document.getElementById('nextcloud-konto');
      if (!form) return;
      const enabled=document.getElementById('nextcloud-dav-an');
      if (enabled?.parentElement) for (const child of enabled.parentElement.childNodes)
        if (child.nodeType===3) child.textContent=' '+tr('DAV account')+' (setup and read-only discovery)';
      if (!account || typeof account.revision!=='string' || !/^[0-9a-f]{64}$/.test(account.revision)) {
        for (const control of form.querySelectorAll('input,button,select')) control.disabled=true;
        const refresh=document.createElement('button');
        refresh.type='button'; refresh.id='tablet-dav-refresh'; refresh.textContent=tr('Refresh');
        refresh.disabled=!loaded || blocked || !!replacement;
        refresh.addEventListener('click',()=>{
          if (!loaded || blocked || replacement) return;
          send({cmd:'baum_briefkasten_status'});
        });
        form.append(refresh);
      }
    }
  });
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
    if (message.cmd === 'import') {
      if (message.art !== 'ics' || Object.keys(message).some(key=>!['cmd','art'].includes(key))) throw Error(beta(0));
      action('tablet_import','ics'); return;
    }
    if (davCommands.has(message.cmd) && (!loaded || blocked || replacement)) throw Error(tr('Warning: The data could not be saved.'));
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
  function action(cmd, format = 'json') {
    if (!loaded || blocked || replacement || pendingAction || pendingCalendar) return;
    if (cmd === 'tablet_import' && !['json','ics'].includes(format)) throw Error(beta(0));
    // Reuse the desktop editor guard and its durable-save queue before opening SAF.
    pendingAction = cmd;
    window.MagnolieTabletActions.afterSave(() => {
      pendingAction = null;
      if (cmd === 'tablet_import') {
        const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
        if (format === 'ics') pendingCalendar = {requestId};
        native({cmd,format,requestId});
      } else native({cmd});
    }).then(ok => { if (!ok) pendingAction = null; });
  }
  function calendarMetadata(data, payload, commit) {
    const metadata = payload.icsImportMetadata;
    if (!metadata) return false;
    const hash = metadata.sourceSHA256, old = data.icsImportSources;
    if (metadata.version !== 1 || typeof hash !== 'string' || !/^[a-f0-9]{64}$/.test(hash) ||
        !Array.isArray(metadata.calendarProperties) || metadata.calendarProperties.some(line=>typeof line!=='string') ||
        (old !== undefined && (!old || typeof old!=='object' || Array.isArray(old)))) throw Error(tr('Import failed.'));
    if (old && Object.hasOwn(old,hash)) {
      if (JSON.stringify(old[hash]) !== JSON.stringify(metadata)) throw Error(tr('Import failed.'));
      return false;
    }
    if (commit) {
      if (old === undefined) data.icsImportSources = {};
      data.icsImportSources[hash] = JSON.parse(JSON.stringify(metadata));
    }
    return true;
  }
  async function calendarImport(payload) {
    const candidate = pendingCalendar;
    if (!loaded || blocked || replacement || !candidate || candidate.requestId !== payload.requestId ||
        payload.session !== session || (!payload.fehler && payload.revision !== revision) || candidate.received) return;
    candidate.received = true;
    const finish = () => {
      if (pendingCalendar !== candidate) return;
      pendingCalendar = null;
      if (Number.isSafeInteger(payload.pickerToken)) native({cmd:'tablet_calendar_import_done',
        requestId:payload.requestId,pickerToken:payload.pickerToken});
    };
    if (payload.fehler) { pendingCalendar=null; status(tr('Import failed.')); return; }
    try {
      const incoming = payload.data, data = window.OrganizerTest.daten();
      if (!incoming || !incoming.icsImportMetadata || !['termine','aufgaben','jahrestage'].every(key=>Array.isArray(incoming[key]))) throw Error(tr('Import failed.'));
      const bytes = text => new TextEncoder().encode(text).length;
      const size = bytes(JSON.stringify(incoming));
      if (size > 8*1024*1024 || ['termine','aufgaben','jahrestage'].reduce((sum,key)=>sum+incoming[key].length,0)>5000 || size + bytes(JSON.stringify(data)) > 16*1024*1024) throw Error(tr('Import failed.'));
      calendarMetadata(data,incoming,false);
      await Promise.resolve(window.App.importErgebnis(incoming));
      if (pendingCalendar !== candidate || blocked || replacement) return;
      const saved = await new Promise(resolve=>window.MagnolieTabletActions.persist(()=>resolve(true),()=>resolve(false)));
      if (!saved) status(tr('Warning: The data could not be saved.'));
      finish();
    } catch (_) { status(tr('Import failed.')); finish(); }
  }
  function saveRegional(control) {
    if (!loaded || blocked || replacement || pendingAction || pendingCalendar || control.disabled) return;
    const fields = {language:'sprache',formatLocale:'formatgebiet',hourCycle:'stunden',
      firstDayOfWeek:'wochenanfang',temperatureUnit:'temperatur',timeZone:'zeitzone',homeCountry:'heimatland'};
    const values = Object.fromEntries(Object.entries(fields).map(([key,id])=>
      [key,document.getElementById('regional-'+id).value.trim()]));
    const T=window.OrganizerTest, before=T.daten().einstellungen.regional;
    // Reuse canonical validation and retain imported regional extension fields.
    const regional={...before,...T.normalisiere({...T.daten(),einstellungen:{...T.daten().einstellungen,
      regional:{...before,...values}}}).einstellungen.regional};
    pendingAction='tablet_regional'; control.disabled=true;
    const finish=success=>{
      pendingAction=null; control.disabled=false;
      status(tr(success ? 'Regional settings saved. Restart the Organizer to apply them completely.' :
        'The regional settings could not be saved.'));
    };
    // First settle an active editor and its save. Then acknowledge the changed
    // preferences only after the existing native whole-document save succeeds.
    window.MagnolieTabletActions.afterSave(()=>{
      if (blocked || replacement) { finish(false); return; }
      T.daten().einstellungen.regional=regional;
      window.MagnolieTabletActions.persist(()=>finish(true),()=>finish(false));
    },()=>finish(false)).then(ok=>{if(!ok) finish(false);}).catch(()=>finish(false));
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
    blocked=true; loaded=false; pendingAction=null; pendingCalendar=null;
    document.getElementById('schreibtisch').inert=true;
    document.querySelectorAll('[role=dialog]').forEach(el=>{el.inert=true;});
    status((payload.text || tr('Warning: The data could not be saved.'))+' ['+payload.outcome+']');
    if (!document.getElementById('tablet-reload')) {
      const reload=button(tr('Open organizer'),()=>location.reload()); reload.id='tablet-reload';
      document.getElementById('tablet-bar').append(reload);
    }
  }
  window.Tablet = {
    alarms, validateImport, action, rejected, calendarMetadata,
    flush() { if (loaded && !replacement) window.OrganizerTest.speichereJetzt(); },
    receive(message) {
      if (typeof message === 'string') message = JSON.parse(message);
      const p = message.payload;
      if (davCallbacks.has(message.callback)) {
        if (loaded && !blocked && !replacement) window.App[message.callback](p);
        return;
      }
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
        case 'calendarImport': void calendarImport(p); break;
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
          if (pendingCalendar && pendingCalendar.requestId !== p.requestId) break;
          pendingCalendar=null;
          replacement=null; pendingAction=null; status(tr('Cancel')); break;
        case 'feiertageErgebnis': if (loaded && !blocked && !replacement) window.App.feiertageErgebnis(p); break;
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
    const syncStart=document.getElementById('sync-jetzt'); if (syncStart) syncStart.disabled=true;
    for (const id of ['baum','sicherheit','ueber']) {
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
      if (id==='import') {
        page.append(button(tr('Import')+' ICS',()=>action('tablet_import','ics')));
        const note=document.createElement('p'); note.textContent=beta(2); page.append(note);
      }
    }
    const unsupportedIds = ['schrift-pruefung','erinnerung-wecken','knopf-sicherung',
      'ort-zeitzonenmanagement','adressen-brief','adressen-brief-layout',
      'adressen-karte','adressen-route','adressen-karten','adressen-soziale-symbole'];
    for (const id of unsupportedIds) {
      const b = document.getElementById(id);
      if (b && !b.disabled) { b.disabled = true; b.title = beta(0); }
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
    const davControlIds=new Set(['dav-konto-art','nextcloud-dav-an','briefkasten-url','briefkasten-benutzer','briefkasten-kennwort']);
    for (const b of document.querySelectorAll('button[id],input[id],select[id]')) {
      if (b.closest('#nextcloud-konto') && davControlIds.has(b.id)) continue;
      if (/(?:sicherung|cloud|journal|telefon|sms|handbuch|wetter|eds|contributor|medikament-such)/.test(b.id)) {
        b.disabled=true; b.title=beta(0);
      }
    }
    // These actions require native desktop services, unlike local binder editing.
    const labels = ['Synchronize','Send SMS','Call','Write a letter','Show on map','Route',
      'Check for updates','ODS','Export ODS'];
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
    bar.append(title,button(tr('Import')+' JSON',()=>action('tablet_import')),button(tr('Import')+' ICS',()=>action('tablet_import','ics')),
      button(tr('Export')+' JSON',()=>action('tablet_export')),
      button(tr('Notifications'),()=>action('tablet_notifications')),details,notice);
    document.body.prepend(bar);
    new MutationObserver(applyCapabilities).observe(document.body,{childList:true,subtree:true});
    document.addEventListener('click',event=>{
      const control=event.target.closest('#regional-speichern');
      if (!control) return;
      event.preventDefault(); event.stopImmediatePropagation();
      saveRegional(control);
    },true);
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
