/* Pure state machine shared by the browser probe and offline false-case tests. */
(() => {
  // Android MotionEvent uptimeMillis is integral. After mapping to the DOM clock,
  // stamp denotes a coarse interval [stamp, stamp+1), not an exact instant.
  // Receipt time is independently checked in the same performance clock as arm.
  const precisionMs = 1;
  const time = n => Number.isFinite(n) && n >= 0 && n < Number.MAX_SAFE_INTEGER;
  function create(expected) {
    let down = null, up = null, click = null, cancelled = false, delivered = false;
    const valid = time(expected.armedAt) && Number.isSafeInteger(expected.step) && expected.step > 0 &&
      Number.isSafeInteger(expected.node) && expected.node > 0 &&
      typeof expected.token === 'string' && expected.token.length > 0 &&
      typeof expected.documentId === 'string' && expected.documentId.length > 0;
    const matches = e => valid && e.trusted === true && e.documentId === expected.documentId &&
      e.token === expected.token && e.step === expected.step && e.node === expected.node &&
      e.target === expected.target && e.connected === true && time(e.stamp) && time(e.at) &&
      e.at >= expected.armedAt && e.stamp + precisionMs > expected.armedAt &&
      e.stamp <= e.at + precisionMs;
    return {
      observe(e) {
        if (delivered || !matches(e)) return false;
        if (e.type === 'contextmenu' || e.type === 'pointercancel') { cancelled = true; return false; }
        if (cancelled) return false;
        if (e.type === 'pointerdown' && !down && e.pointerType === 'touch' && e.button === 0 &&
            Number.isSafeInteger(e.pointerId) && e.pointerId >= 0) {
          down = e;
        } else if (e.type === 'pointerup' && down && !up &&
                   e.pointerType === 'touch' && e.pointerId === down.pointerId &&
                   e.stamp >= down.stamp && e.at >= down.at) {
          up = e;
        } else if (e.type === 'click' && down && up && !click && e.stamp >= up.stamp && e.at >= up.at &&
                   (e.pointerId === undefined || e.pointerId === down.pointerId)) {
          click = e;
          return true;
        } else {
          // A malformed/reordered matching sequence cannot be salvaged by a
          // later event or by the section already displaying the expected value.
          cancelled = true;
        }
        return false;
      },
      finish(actualSection, connected, label, focusKey, pendingJobs) {
        if (delivered || cancelled || !click || !connected || label !== expected.label ||
            focusKey !== 'register:' + expected.section || actualSection !== expected.section ||
            expected.before === expected.section || (expected.section === 'planer' && pendingJobs !== 0)) return null;
        delivered = true;
        return {step:expected.step,documentId:expected.documentId,node:expected.node,
          label:expected.label,section:actualSection,before:expected.before,sourceHash:expected.sourceHash,
          armedAt:expected.armedAt,clockPrecisionMs:precisionMs,
          trusted:true,downStamp:down.stamp,upStamp:up.stamp,clickStamp:click.stamp,
          downAt:down.at,upAt:up.at,clickAt:click.at,pendingJobs};
      }
    };
  }
  const api = {create};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.NativeTouchProof = api;
})();
