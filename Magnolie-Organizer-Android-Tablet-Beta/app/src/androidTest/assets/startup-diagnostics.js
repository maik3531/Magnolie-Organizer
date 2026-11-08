/* Test APK only: fixed technical fields; never return document data or message text. */
(() => {
  const status = document.getElementById('tablet-status')?.textContent || '';
  return {
    readyState: document.readyState,
    origin: location.origin,
    tabletPresent: typeof window.Tablet === 'object',
    organizerPresent: typeof window.OrganizerTest === 'object',
    storageBlocked: document.getElementById('schreibtisch')?.inert === true,
    statusCode: (status.match(/\[(load-validation|before-commit|committed|uncertain|rejected)\]/) || [])[1] || 'none'
  };
})()
