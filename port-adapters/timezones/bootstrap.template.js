/* Fixed synchronous bootstrap; placeholders are verified build inputs, never user data. */
(function(root) {
  'use strict';
  if(root.MagnolieTime || typeof root.MagnolieTimezoneProvider!=='function' || typeof root.MagnolieTimezonePort!=='function') throw new Error('timezone-bootstrap-order');
  const payloadText=/*NORMATIVE_TZDB_TEXT*/null;
  const manifest=/*NORMATIVE_TZDB_MANIFEST*/null;
  const runtime=root.MagnolieTimezonePort(root.MagnolieTimezoneProvider,payloadText,manifest);
  Object.defineProperty(root,'MagnolieTime',{value:runtime,writable:false,configurable:false});
})(typeof globalThis!=='undefined'?globalThis:self);
