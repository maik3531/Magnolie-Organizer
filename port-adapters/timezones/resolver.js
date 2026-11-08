/* Synchronous civil-time points from a complete, versioned normative rule model.
 * No Intl offsets, global patches, occurrence expansion or finite future table. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.MagnolieTimezoneProvider = factory;
})(typeof globalThis !== 'undefined' ? globalThis : self, function createTimezoneProvider(payload) {
  'use strict';
  const fail = code => { const error = new RangeError(code); error.code = code; throw error; };
  const integer = n => Number.isSafeInteger(n);
  if (!payload || payload.schema !== 2 || payload.tzdbVersion !== '2026egtz' || !Array.isArray(payload.rules) || !payload.zones) fail('invalid-timezone-database');
  // Preflight aggregate bounds before cloning any registry, history or type array.
  // The separately pinned asset digest is authoritative; this also bounds callers.
  const plain = value => value && typeof value === 'object' && [Object.prototype,null].includes(Object.getPrototypeOf(value));
  if (!plain(payload) || !plain(payload.zones)) fail('invalid-timezone-database');
  const limits = {zones:2048,rules:1024,types:8192,transitions:100000,stringUnits:1048576};
  let zoneCount=0,typeCount=0,transitionCount=0,stringUnits=0,rootFields=0;
  const stringBudget = (value, maximum, nullable = false) => {
    if (nullable && value === null) return;
    if (typeof value !== 'string' || value.length > maximum || (stringUnits += value.length) > limits.stringUnits) fail('timezone-database-limit');
  };
  for (const key in payload) if (Object.prototype.hasOwnProperty.call(payload,key)) {
    if (++rootFields > 6 || !['schema','tzdbVersion','sourceArchiveSHA256','zones','rules','rejectedZones'].includes(key)) fail('invalid-timezone-database-field');
  }
  if (payload.rules.length > limits.rules || typeof payload.zones !== 'object' || Array.isArray(payload.zones)) fail('timezone-database-limit');
  stringBudget(payload.tzdbVersion,64);
  if (payload.sourceArchiveSHA256 !== undefined) stringBudget(payload.sourceArchiveSHA256,64);
  for (const id in payload.zones) if (Object.prototype.hasOwnProperty.call(payload.zones,id)) {
    if (++zoneCount > limits.zones) fail('timezone-database-limit');
    stringBudget(id,255);
  }
  for (const row of payload.rules) {
    if (!Array.isArray(row) || row.length !== 4 || !Array.isArray(row[1]) || row[1].length > 256 || !Array.isArray(row[2]) || row[2].length % 2 ||
        (typeCount += row[1].length) > limits.types || (transitionCount += row[2].length/2) > limits.transitions || !Array.isArray(row[3]) || row[3].length !== 7) fail('timezone-database-limit');
    for (const type of row[1]) {if (!Array.isArray(type) || type.length !== 5) fail('invalid-timezone-type');stringBudget(type[2],64);}
    const tail=row[3];stringBudget(tail[1],64);stringBudget(tail[3],64,true);stringBudget(tail[6],512);
    for (const selector of [tail[4],tail[5]]) if (selector !== null) {
      if (!Array.isArray(selector) || selector.length !== 5 || typeof selector[0] !== 'string' || selector[0].length !== 1 || !selector.slice(1).every(value => typeof value === 'number')) fail('invalid-timezone-future-rule');
      stringBudget(selector[0],1);
    }
  }
  if (payload.rejectedZones !== undefined) {
    if (!payload.rejectedZones || !plain(payload.rejectedZones)) fail('invalid-timezone-rejections');
    let rejectedCount=0;
    for (const id in payload.rejectedZones) if (Object.prototype.hasOwnProperty.call(payload.rejectedZones,id)) {
      if (++rejectedCount > 16) fail('timezone-database-limit');
      stringBudget(id,255);stringBudget(payload.rejectedZones[id],128);
    }
  }
  const rawUTC = (year, month, day, hour = 0, minute = 0, second = 0, millisecond = 0) => {
    const date = new Date(0); date.setUTCFullYear(year, month - 1, day); date.setUTCHours(hour, minute, second, millisecond); return +date;
  };
  const parts = value => {
    const date = new Date(value);
    return {year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate(),
      hour: date.getUTCHours(), minute: date.getUTCMinutes(), second: date.getUTCSeconds(), millisecond: date.getUTCMilliseconds()};
  };
  const offsetOK = n => integer(n) && n >= -89999 && n <= 93599;
  const parseTail = text => {
    const token = '(?:<[A-Za-z0-9+\\-]{3,}>|[A-Za-z]{3,})', number = '[+-]?\\d{1,3}(?::\\d{1,2}(?::\\d{1,2})?)?';
    const match = new RegExp('^('+token+')('+number+')('+token+')?('+number+')?(?:,([^,]+),([^,]+))?$').exec(text);
    if (!match) fail('invalid-timezone-future');
    const seconds = (value, limit) => {
      if (!new RegExp('^'+number+'$').test(value)) fail('invalid-timezone-future-clock');
      const values = value.replace(/^[+-]/,'').split(':').map(Number);
      if (values[0] > limit || values.slice(1).some(n => n > 59)) fail('invalid-timezone-future-clock');
      return (value.startsWith('-') ? -1 : 1)*values.reduce((sum,v,i) => sum+v*[3600,60,1][i],0);
    };
    const dateRule = value => {
      const split = value.split('/'); if (split.length > 2) fail('invalid-timezone-future-rule');
      const date = split[0], time = split.length === 2 ? seconds(split[1],167) : 7200;
      const month = /^M(\d{1,2})\.([1-5])\.([0-6])$/.exec(date);
      if (month && +month[1] >= 1 && +month[1] <= 12) return ['M',+month[1],+month[2],+month[3],time];
      if (/^J\d{1,3}$/.test(date) && +date.slice(1) >= 1 && +date.slice(1) <= 365) return ['J',+date.slice(1),0,0,time];
      if (/^\d{1,3}$/.test(date) && +date <= 365) return ['N',+date,0,0,time];
      return fail('invalid-timezone-future-rule');
    };
    const standard = -seconds(match[2],24), name = value => value.replace(/^<|>$/g,'');
    if (!match[3]) {if (match[4] || match[5] || match[6]) fail('invalid-timezone-future'); return [standard,name(match[1]),null,null,null,null,text];}
    if (!match[5] || !match[6]) fail('missing-timezone-future-rule');
    return [standard,name(match[1]),match[4] ? -seconds(match[4],24) : standard+3600,name(match[3]),dateRule(match[5]),dateRule(match[6]),text];
  };
  const rules = payload.rules.map(row => {
    if (!Array.isArray(row) || row.length !== 4 || !integer(row[0]) || !Array.isArray(row[1]) || !row[1].length || row[1].length > 256 || row[0] < 0 || row[0] >= row[1].length || !Array.isArray(row[2]) || row[2].length % 2) fail('invalid-timezone-rule');
    const types = row[1].map(type => {
      if (!Array.isArray(type) || type.length !== 5 || !offsetOK(type[0]) || ![0,1].includes(type[1]) || typeof type[2] !== 'string' || !/^[\x20-\x7e]*$/.test(type[2]) || ![0,1].includes(type[3]) || ![0,1].includes(type[4])) fail('invalid-timezone-type');
      return Object.freeze(type.slice());
    });
    const history = row[2].slice();
    for (let i = 0; i < history.length; i += 2) {
      if (!integer(history[i]) || Math.abs(history[i]) > 9007199254740 || !integer(history[i+1]) || history[i+1] < 0 || history[i+1] >= types.length || i && history[i] <= history[i-2]) fail('invalid-timezone-history');
      history[i+1] = types[history[i+1]][0];
    }
    const tail = row[3];
    if (!Array.isArray(tail) || tail.length !== 7 || !offsetOK(tail[0]) || typeof tail[1] !== 'string' || !tail[1] || typeof tail[6] !== 'string' || !tail[6]) fail('missing-timezone-future');
    if (JSON.stringify(parseTail(tail[6])) !== JSON.stringify(tail)) fail('inconsistent-timezone-future');
    const ruleOK = r => Array.isArray(r) && r.length === 5 && ['M','J','N'].includes(r[0]) && r.slice(1).every(integer) && Math.abs(r[4]) <= 604799 &&
      (r[0] === 'M' ? r[1] >= 1 && r[1] <= 12 && r[2] >= 1 && r[2] <= 5 && r[3] >= 0 && r[3] <= 6 : r[1] >= (r[0] === 'J' ? 1 : 0) && r[1] <= 365 && r[2] === 0 && r[3] === 0);
    let future = [];
    if (tail[2] === null) {
      if (tail[3] !== null || tail[4] !== null || tail[5] !== null || (history.length ? history[history.length-1] : types[row[0]][0]) !== tail[0]) fail('invalid-timezone-fixed-future');
    } else {
      if (!offsetOK(tail[2]) || typeof tail[3] !== 'string' || !tail[3] || !ruleOK(tail[4]) || !ruleOK(tail[5])) fail('invalid-timezone-future-rule');
      future = [{date:Object.freeze(tail[4].slice()),before:tail[0],after:tail[2]}, {date:Object.freeze(tail[5].slice()),before:tail[2],after:tail[0]}].map(Object.freeze);
    }
    const offsets = Object.freeze([...new Set([...types.map(type => type[0]),tail[0],...(tail[2] === null ? [] : [tail[2]])])]);
    return Object.freeze({initial: types[row[0]][0], history: Object.freeze(history), future: Object.freeze(future), offsets, types:Object.freeze(types)});
  });
  const zones = Object.create(null);
  for (const id of Object.keys(payload.zones)) {
    const index = payload.zones[id];
    if (!/^[A-Za-z0-9_+./-]{1,255}$/.test(id) || id.includes('..') || !integer(index) || index < 0 || index >= rules.length) fail('invalid-timezone-identifier');
    zones[id] = rules[index];
  }
  const zero = Object.freeze({initial: 0, history: Object.freeze([]), future: Object.freeze([]), offsets: Object.freeze([0])});
  const rejected = Object.freeze(Object.assign(Object.create(null),payload.rejectedZones || {}));
  const lookup = id => typeof id !== 'string' ? fail('unknown-time-zone') : Object.prototype.hasOwnProperty.call(rejected,id) ? fail('unsupported-time-zone') : Object.prototype.hasOwnProperty.call(zones,id) ? zones[id] : ['UTC','GMT','UT','Z'].includes(id) ? zero : fail('unknown-time-zone');
  const instantOK = value => {
    if (!integer(value) || value < rawUTC(0,12,29) || value > rawUTC(10000,1,3)) fail('invalid-timezone-instant');
    return value;
  };
  // Last rules are evaluated for the requested civil year and its neighbours.
  // Their model is unlimited; no generated list is treated as an infinite tail.
  const transition = (rule, year) => {
    const [kind, a, b, c, seconds] = rule.date;
    let local;
    if (kind === 'M') {
      const firstWeekday = new Date(rawUTC(year,a,1)).getUTCDay();
      let day = 1 + (c-firstWeekday+7)%7 + (b-1)*7;
      if (day > new Date(rawUTC(year,a+1,0)).getUTCDate()) day -= 7;
      local = rawUTC(year,a,day);
    } else {
      const leap = year%4 === 0 && (year%100 !== 0 || year%400 === 0);
      const day = kind === 'J' ? a-1+(leap && a >= 60 ? 1 : 0) : a;
      local = rawUTC(year,1,1) + day*86400000;
    }
    return {at:local + (seconds-rule.before)*1000, before:rule.before, after:rule.after};
  };
  const nearby = (rule, year) => {
    const result = [];
    for (let y = year - 1; y <= year + 1; y++) for (const last of rule.future) result.push(transition(last, y));
    return result.sort((a,b) => a.at - b.at);
  };
  const historyIndex = (rule, value) => {
    let low = 0, high = rule.history.length / 2;
    while (low < high) { const middle = Math.floor((low+high)/2); if (rule.history[middle*2]*1000 <= value) low = middle+1; else high = middle; }
    return low;
  };
  const getOffset = (rule, value) => {
    const index = historyIndex(rule,value), history = rule.history;
    const boundary = history.length ? history[history.length-2]*1000 : -Infinity;
    if (rule.future.length && value > boundary) {
      const candidates = nearby(rule, new Date(value).getUTCFullYear()).filter(t => t.at > boundary && t.at <= value);
      if (candidates.length) return candidates[candidates.length-1].after;
    }
    return index ? history[(index-1)*2+1] : rule.initial;
  };
  const wallMillis = input => {
    if (!input || !['year','month','day'].every(k => integer(input[k]))) fail('invalid-timezone-wall');
    const clean = {year:input.year,month:input.month,day:input.day,hour:input.hour ?? 0,minute:input.minute ?? 0,second:input.second ?? 0,millisecond:input.millisecond ?? 0};
    if (clean.year < 1 || clean.year > 9999 || !Object.values(clean).every(integer)) fail('invalid-timezone-wall');
    const value = rawUTC(clean.year,clean.month,clean.day,clean.hour,clean.minute,clean.second,clean.millisecond), actual = parts(value);
    if (!Object.keys(clean).every(k => clean[k] === actual[k])) fail('invalid-timezone-wall');
    return value;
  };
  return Object.freeze({
    version: payload.tzdbVersion,
    identifiers: Object.freeze(Object.keys(zones).sort()),
    has: id => typeof id === 'string' && (Object.prototype.hasOwnProperty.call(zones,id) || ['UTC','GMT','UT','Z'].includes(id)),
    offsetAt(id, epochMs) {return getOffset(lookup(id),instantOK(epochMs));},
    wallParts(id, epochMs) {const offsetSeconds = getOffset(lookup(id),instantOK(epochMs)); return Object.assign(parts(epochMs + offsetSeconds*1000),{offsetSeconds});},
    resolveWall(id, input, options = {}) {
      const rule = lookup(id), value = wallMillis(input), gap = options.gap ?? 'reject', fold = options.fold ?? 'earlier';
      if (!['reject','forward','omit'].includes(gap) || !['earlier','later','reject'].includes(fold)) fail('invalid-timezone-policy');
      const valid = rule.offsets.map(offset => value-offset*1000).filter(epoch => getOffset(rule,epoch) === (value-epoch)/1000).sort((a,b) => a-b);
      if (valid.length) {if (valid.length > 1 && fold === 'reject') fail('ambiguous-timezone-wall'); return fold === 'later' ? valid[valid.length-1] : valid[0];}
      const low = value-Math.max(...rule.offsets)*1000, high = value-Math.min(...rule.offsets)*1000;
      const boundary = rule.history.length ? rule.history[rule.history.length-2]*1000 : -Infinity;
      const candidates = nearby(rule,input.year).filter(t => t.at > boundary); let index = historyIndex(rule,low-1);
      for (; index < rule.history.length/2 && rule.history[index*2]*1000 <= high; index++) candidates.push({at:rule.history[index*2]*1000,before:index ? rule.history[(index-1)*2+1] : rule.initial,after:rule.history[index*2+1]});
      const transitionGap = candidates.find(t => t.after > t.before && value >= t.at+t.before*1000 && value < t.at+t.after*1000);
      if (!transitionGap) fail('unresolved-timezone-wall');
      if (gap === 'omit') return null;
      if (gap === 'forward') return value-transitionGap.before*1000;
      return fail('nonexistent-timezone-wall');
    }
  });
});
