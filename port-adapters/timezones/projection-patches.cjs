'use strict';
const {createHash}=require('node:crypto');
const sha=text=>createHash('sha256').update(text).digest('hex');
module.exports=function timezonePatches(source,read,undo=false,canonical=source) {
  const manifest=JSON.parse(read('projection-patches.json').toString()),snippets=read('app-hooks.snippets').toString();
  const original=entry=>{
    const start=canonical.indexOf(entry.start);
    if(start<0 || canonical.indexOf(entry.start,start+1)>=0)throw Error('Timezone start anchor changed: '+entry.id);
    let end=start+entry.start.length;
    if(entry.end) {end=canonical.indexOf(entry.end,end);if(end<0)throw Error('Timezone end anchor changed: '+entry.id);if(entry.includeEnd)end+=entry.end.length;}
    const text=canonical.slice(start,end);
    if(sha(text)!==entry.sha256)throw Error('Timezone canonical block changed: '+entry.id);
    return text;
  };
  for(const entry of undo?[...manifest].reverse():manifest) {
    const before=original(entry),begin='/*TZ_PORT:'+entry.id+':BEGIN*/',end='/*TZ_PORT:'+entry.id+':END*/';
    let after;
    if(entry.hook) {
      const a='/*TZ_HOOK:'+entry.hook+'*/\n',b='/*TZ_HOOK_END:'+entry.hook+'*/';
      if(snippets.split(a).length!==2 || snippets.split(b).length!==2)throw Error('Timezone hook changed: '+entry.id);
      after=snippets.split(a)[1].split(b)[0];
    } else after=entry.replacement;
    const patched=begin+after+end;
    const needle=undo?patched:before;
    if(source.split(needle).length!==2)throw Error('Timezone projection match changed: '+entry.id);
    source=source.replace(needle,()=>undo?before:patched);
  }
  return source;
};
