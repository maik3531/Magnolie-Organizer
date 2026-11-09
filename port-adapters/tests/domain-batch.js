/* Test-only round-trip reduction. The canonical durable-save callback remains
 * authoritative; batching never manufactures an ACK or changes book data. */
window.NativeDomainBatch = Object.freeze({
  async afterSave(detail, capture = false) {
    const clone = value => JSON.parse(JSON.stringify(value));
    const beforeSave = capture ? clone(OrganizerTest.daten()) : null;
    await new Promise((resolve, reject) => MagnolieTabletActions.afterSave(resolve,
      () => reject(new Error('Native domain save failed'))));
    if (!capture) return detail;
    return { detail, beforeSave, afterSave: clone(OrganizerTest.daten()),
      expectedBook: NativeDomains.expectedAfterReopen(OrganizerTest.daten()),
      expectedFeatures: NativeDomains.expectedAfterReopen(NativeDomains.snapshot()) };
  },
  snapshot() { return {book: OrganizerTest.daten(), features: NativeDomains.snapshot()}; }
});
