'use strict';
const {createHash}=require('node:crypto');
module.exports=function(source,read,undo=false) {
  const patch=JSON.parse(read('occurrence-identity-patch.json').toString());
  if(patch.schema!==1 || createHash('sha256').update(patch.before).digest('hex')!==patch.sha256 ||
     typeof patch.mainBefore!=='string' || createHash('sha256').update(patch.mainBefore).digest('hex')!==patch.mainSHA256 ||
     patch.after.split('/*PORT_OCCURRENCE_HELPER*/').length!==2) throw Error('Occurrence identity patch manifest changed');
  const after=patch.after.replace('/*PORT_OCCURRENCE_HELPER*/',()=>read('occurrence-identity.js').toString());
  const mainAfter=after+'/*PORT_OCCURRENCE_MAIN_SOURCE*/\n';
  const main=undo?source.includes(mainAfter):source.includes(patch.mainBefore);
  const original=main?patch.mainBefore:patch.before,projected=main?mainAfter:after;
  const before=undo?projected:original;
  if(source.split(before).length!==2)throw Error('Occurrence identity canonical anchor changed');
  return source.replace(before,()=>undo?original:projected);
};
