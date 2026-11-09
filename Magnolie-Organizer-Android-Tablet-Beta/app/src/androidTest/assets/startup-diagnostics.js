/* Test APK only: fixed technical fields; never return document data or message text. */
(() => {
  const status = document.getElementById('tablet-status')?.textContent || '';
  const milliseconds = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const timing = value => Object.fromEntries(['startTime','duration','fetchStart','responseEnd',
    'domInteractive','domContentLoadedEventStart','domContentLoadedEventEnd','loadEventStart','loadEventEnd']
    .map(key => [key, milliseconds(value?.[key])]));
  const entries = type => {
    try { return typeof performance?.getEntriesByType === 'function' ? performance.getEntriesByType(type) : []; }
    catch (_) { return []; }
  };
  const resources = entries('resource');
  const scripts = ['normative-timezones.js','tablet.js','anwendung.js'].map(name => {
    const entry = resources.find(value => {
      try { return new URL(value.name).pathname.split('/').pop() === name; } catch (_) { return false; }
    });
    return {name, timing: entry ? timing(entry) : null};
  });
  return {
    readyState: document.readyState,
    origin: location.origin,
    tabletPresent: typeof window.Tablet === 'object',
    organizerPresent: typeof window.OrganizerTest === 'object',
    storageBlocked: document.getElementById('schreibtisch')?.inert === true,
    statusCode: (status.match(/\[(load-validation|before-commit|committed|uncertain|rejected)\]/) || [])[1] || 'none',
    browserTiming: {
      sampledEpochMs: milliseconds(Date.now()),
      timeOriginMs: milliseconds(performance.timeOrigin),
      sampledNowMs: milliseconds(performance.now()),
      navigation: entries('navigation')[0] ? timing(entries('navigation')[0]) : null,
      scripts
    }
  };
})()
