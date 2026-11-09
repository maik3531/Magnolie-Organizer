'use strict';
const {createHash}=require('node:crypto');
module.exports=function timezoneAssets(read) {
  const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
  const data=read('tzdb-2026egtz.json'),manifest=JSON.parse(read('provenance.json').toString());
  if(manifest.schema!==2 || manifest.tzdbVersion!=='2026egtz' || manifest.payloadBytes!==428473 ||
    manifest.payloadSHA256!=='2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c' ||
    sha(data)!==manifest.payloadSHA256 || sha(read('LICENSE-tzdb.txt'))!==manifest.licenseSHA256)
    throw Error('Normative timezone source/identity/license mismatch');
  let bootstrap=read('bootstrap.template.js').toString();
  for(const [marker,value] of [['/*NORMATIVE_TZDB_TEXT*/null',JSON.stringify(data.toString())],
    ['/*NORMATIVE_TZDB_MANIFEST*/null',read('provenance.json').toString().trim()]]) {
    if(bootstrap.split(marker).length!==2) throw Error('Normative timezone bootstrap anchor changed');
    bootstrap=bootstrap.replace(marker,value);
  }
  const result={'normative-timezones.js':Buffer.concat([read('resolver.js'),Buffer.from('\n'),read('port-runtime.js'),Buffer.from('\n'+bootstrap)])};
  for(const name of ['tzdb-2026egtz.json','provenance.json','LICENSE-tzdb.txt']) result['timezones/'+name]=read(name);
  return result;
};
