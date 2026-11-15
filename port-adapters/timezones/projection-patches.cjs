'use strict';
const {createHash}=require('node:crypto');
const sha=text=>createHash('sha256').update(text).digest('hex');
module.exports=function timezonePatches(source,read,undo=false,canonical=source) {
  const manifest=JSON.parse(read('projection-patches.json').toString()),snippets=read('app-hooks.snippets').toString();
  const replacement=entry=>{
    if(!entry.hook)return entry.replacement;
    const a='/*TZ_HOOK:'+entry.hook+'*/\n',b='/*TZ_HOOK_END:'+entry.hook+'*/';
    if(snippets.split(a).length!==2 || snippets.split(b).length!==2)throw Error('Timezone hook changed: '+entry.id);
    return snippets.split(a)[1].split(b)[0];
  };
  // Once the canonical UI owns the complete reviewed adapters, projection and
  // inverse retain them. Mixed, duplicated or changed blocks are never accepted.
  if(canonical.includes('/*TZ_PORT:')) {
    for(const text of [canonical,source]) {
      if((text.match(/\/\*TZ_PORT:/g)||[]).length!==manifest.length*2)throw Error('Timezone projection match changed: marker inventory');
      for(const entry of manifest) {
        const begin='/*TZ_PORT:'+entry.id+':BEGIN*/',end='/*TZ_PORT:'+entry.id+':END*/';
        const block=begin+replacement(entry)+end;
        if(text.split(begin).length!==2 || text.split(end).length!==2 || text.split(block).length!==2)throw Error('Timezone projection match changed: '+entry.id);
      }
    }
    return source;
  }
  const original=entry=>{
    const start=canonical.indexOf(entry.start);
    if(start<0 || canonical.indexOf(entry.start,start+1)>=0)throw Error('Timezone start anchor changed: '+entry.id);
    let end=start+entry.start.length;
    if(entry.end) {end=canonical.indexOf(entry.end,end);if(end<0)throw Error('Timezone end anchor changed: '+entry.id);if(entry.includeEnd)end+=entry.end.length;}
    const text=canonical.slice(start,end);
    const allowed=[entry.sha256,...(entry.reviewedVariants||[]).map(variant=>variant.sha256)];
    if(!allowed.includes(sha(text)))throw Error('Timezone canonical block changed: '+entry.id);
    return text;
  };
  for(const entry of undo?[...manifest].reverse():manifest) {
    const before=original(entry),begin='/*TZ_PORT:'+entry.id+':BEGIN*/',end='/*TZ_PORT:'+entry.id+':END*/';
    const after=replacement(entry);
    const patched=begin+after+end;
    const needle=undo?patched:before;
    if(source.split(needle).length!==2)throw Error('Timezone projection match changed: '+entry.id);
    source=source.replace(needle,()=>undo?before:patched);
  }
  return source;
};

module.exports.stripCanonicalBootstrap=function(html) {
  const tag='<script src="normative-timezones.js"></script>',app='<script src="anwendung.js"></script>';
  if(!html.includes('normative-timezones.js'))return html;
  if(html.split('normative-timezones.js').length!==2 || html.split(tag).length!==2 ||
     html.split(app).length!==2 || html.indexOf(tag)>html.indexOf(app))throw Error('Timezone bootstrap script changed');
  // Each port installs its own already-verified ordered bootstrap exactly once.
  return html.replace(tag,'');
};
