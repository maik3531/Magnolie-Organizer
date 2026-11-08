/* Synthetic, read-only native WebView audit. No recurrence expansion or native ACK. */
(() => {
  'use strict';
  window.NativeTimezoneInterop = {
    run(fixture) {
      const T = window.OrganizerTest, book = T.daten();
      const before = JSON.stringify(book), regional = book.einstellungen.regional;
      const hadZone = Object.prototype.hasOwnProperty.call(regional, 'timeZone'), oldZone = regional.timeZone;
      const failures = []; let checks = 0;
      const compare = (row, path, actual, expected) => {
        checks++;
        if (actual !== expected) failures.push({identifier: row.identifier, wall: row.wall, path, expected, actual});
      };
      try {
        for (const row of fixture.clocks) {
          regional.timeZone = row.identifier;
          const [datum, zeit] = row.wall.split('T');
          try { compare(row, 'shared-appointment-reminder', +T.terminZeitpunkt({datum, zeit}), row.epochMs); }
          catch (error) { compare(row, 'shared-appointment-reminder', String(error), row.epochMs); }
          const stamp = row.wall.replace(/[-:]/g, '') + '00';
          try {
            const values = T.icsExpansion({icsRoundtrip: ['DUE;TZID=' + row.identifier + ':' + stamp]}, -Infinity, Infinity, true);
            compare(row, 'shared-task-source-count', values?.length, 1);
            compare(row, 'shared-task-source-reminder', values?.[0]?.icsStartUtc, row.epochMs);
          } catch (error) { compare(row, 'shared-task-source-reminder', String(error), row.epochMs); }
          try {
            const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone: row.identifier,
              year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'})
              .formatToParts(new Date(row.epochMs)).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
            compare(row, 'webview-intl-wall', parts.year + '-' + parts.month + '-' + parts.day + 'T' + parts.hour + ':' + parts.minute, row.wall);
          } catch (error) { compare(row, 'webview-intl-wall', String(error), row.wall); }
        }
      } finally {
        if (hadZone) regional.timeZone = oldZone; else delete regional.timeZone;
      }
      if (JSON.stringify(book) !== before) throw new Error('Timezone audit changed the book');
      return {clocks: fixture.clocks.length, checks, failures, bookUnchanged: true};
    }
  };
})();
