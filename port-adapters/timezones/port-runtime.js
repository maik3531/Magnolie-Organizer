/* Shared synchronous port adapter. Intl supplies locale layout and system ID only. */
(function(root,factory) {
  if(typeof module==='object' && module.exports) module.exports=factory;
  else root.MagnolieTimezonePort=factory;
})(typeof globalThis!=='undefined'?globalThis:self,function createTimezonePort(createProvider,payloadText,manifest,detectSystemIdentifier) {
  'use strict';
  const fail=code=>{const error=new RangeError(code);error.code=code;throw error;};
  // The projection checks the actual byte digest before emitting the bootstrap.
  // This synchronous identity guard does not pretend to rehash bytes in browser JS.
  if(typeof payloadText!=='string' || payloadText.length>1048576 || typeof createProvider!=='function') fail('invalid-timezone-bootstrap');
  if(!manifest || manifest.schema!==2 || manifest.tzdbVersion!=='2026egtz' ||
    manifest.payloadSHA256!=='2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c' ||
    manifest.archiveSHA256!=='0f391ed721b54225189a1c5cac469fa24a07c1283e9e460650fd28155e19240d') fail('timezone-bootstrap-identity');
  const model=JSON.parse(payloadText),provider=createProvider(model);
  if(model.sourceArchiveSHA256!==manifest.archiveSHA256 || provider.version!==manifest.tzdbVersion) fail('timezone-bootstrap-identity');
  const identity=Object.freeze({schema:2,tzdbVersion:manifest.tzdbVersion,payloadSHA256:manifest.payloadSHA256,archiveSHA256:manifest.archiveSHA256});
  const system=detectSystemIdentifier || (()=>Intl.DateTimeFormat().resolvedOptions().timeZone);
  const named=id=>{if(typeof id!=='string' || !provider.has(id))fail('unresolved-time-zone');return id;};
  const systemIdentifier=()=>named(system());
  const zoneId=id=>id==='system'?systemIdentifier():named(id);
  const civilParts=at=>{const d=new Date(at);return {year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate(),hour:d.getUTCHours(),minute:d.getUTCMinutes(),second:d.getUTCSeconds(),millisecond:d.getUTCMilliseconds()};};
  const epoch=value=>{const result=typeof value==='number'?value:Object.prototype.toString.call(value)==='[object Date]'?Date.prototype.getTime.call(value):fail('invalid-timezone-instant');if(!Number.isSafeInteger(result))fail('invalid-timezone-instant');return result;};
  const offsetLabel=seconds=>{
    if(!Number.isSafeInteger(seconds) || seconds < -89999 || seconds > 93599)fail('invalid-timezone-offset');
    if(seconds===0)return 'UTC';
    const absolute=Math.abs(seconds),pad=value=>String(value).padStart(2,'0');
    return 'UTC'+(seconds<0?'-':'+')+pad(Math.floor(absolute/3600))+':'+pad(Math.floor(absolute/60)%60)+(absolute%60?':'+pad(absolute%60):'');
  };
  const formats=new Map();
  const formatter=(locale,options)=>{
    const effective=Object.assign({},options,{timeZone:'UTC'}),key=JSON.stringify([locale||'',effective]);
    if(formats.has(key))return formats.get(key);
    const remember=value=>{if(formats.size>=128)formats.delete(formats.keys().next().value);formats.set(key,value);return value;};
    try{return remember(new Intl.DateTimeFormat(locale,effective));}
    catch(first) {
      // Unsupported CLDR name styles may use a supported UTC token: its value
      // is replaced below. Locale fallback never changes the offset authority.
      if(effective.timeZoneName)effective.timeZoneName='short';
      try{return remember(new Intl.DateTimeFormat(locale,effective));}
      catch(second) {try{return remember(new Intl.DateTimeFormat(undefined,effective));}catch(third){return fail('unsupported-timezone-locale-format');}}
    }
  };
  const formatParts=(value,locale,options={},id)=>{
    const at=epoch(value),zone=zoneId(options.timeZone===undefined?id:options.timeZone),offset=provider.offsetAt(zone,at);
    return formatter(locale,options).formatToParts(new Date(at+offset*1000)).map(part=>
      part.type==='timeZoneName'?{type:part.type,value:offsetLabel(offset)}:{type:part.type,value:part.value});
  };
  const candidates=(id,wall)=>{
    const zone=zoneId(id),input=typeof wall==='number'?civilParts(wall):wall;
    const earlier=provider.resolveWall(zone,input,{gap:'omit',fold:'earlier'});
    if(earlier===null)return [];
    const later=provider.resolveWall(zone,input,{gap:'omit',fold:'later'});
    return earlier===later?[earlier]:[earlier,later];
  };
  const localeDefaults=(options,kind)=>{
    if(options===null || options!==undefined && typeof options!=='object')fail('unsupported-timezone-locale-format');
    const result=Object.assign({},options);
    if(kind==='date' && result.timeStyle!==undefined || kind==='time' && result.dateStyle!==undefined)fail('unsupported-timezone-locale-format');
    const date=['weekday','year','month','day'],time=['hour','minute','second','fractionalSecondDigits'];
    const fields=kind==='date'?date:kind==='time'?time:[...date,...time];
    if(result.dateStyle===undefined && result.timeStyle===undefined && fields.every(key=>result[key]===undefined)) {
      if(kind!=='time')for(const key of ['year','month','day'])result[key]='numeric';
      if(kind!=='date')for(const key of ['hour','minute','second'])result[key]='numeric';
    }
    return result;
  };
  return Object.freeze({identity,identifiers:provider.identifiers,has:id=>provider.has(id),zoneId,systemIdentifier,offsetLabel,
    offsetAt:(id,value)=>provider.offsetAt(zoneId(id),epoch(value)),
    wallParts:(id,value)=>provider.wallParts(zoneId(id),epoch(value)),
    wallMillis:(id,value)=>{const at=epoch(value);return at+provider.offsetAt(zoneId(id),at)*1000;},
    resolveWall:(id,parts,options)=>provider.resolveWall(zoneId(id),parts,options),candidates,
    formatParts,
    localeString:(value,locale,options)=>formatParts(value,locale,localeDefaults(options,'all'),'system').map(p=>p.value).join(''),
    localeDate:(value,locale,options)=>formatParts(value,locale,localeDefaults(options,'date'),'system').map(p=>p.value).join(''),
    localeTime:(value,locale,options)=>formatParts(value,locale,localeDefaults(options,'time'),'system').map(p=>p.value).join(''),
    format:(value,locale,options,id)=>formatParts(value,locale,options,id).map(part=>part.value).join(''),
    formatCivil:(parts,locale,options={})=>{
      // DATE/floating values are already civil fields, not named-zone instants.
      // Validate without converting them through a machine-local Date constructor.
      const at=provider.resolveWall('UTC',parts,{gap:'reject',fold:'reject'});
      if(options.timeZone!==undefined)fail('civil-time-has-no-zone');
      const effective=Object.assign({},options);delete effective.timeZone;
      if(effective.timeZoneName)fail('civil-time-has-no-zone');
      if(['long','full'].includes(effective.timeStyle))effective.timeStyle='medium';
      return formatter(locale,effective).format(new Date(at));
    },
    workerPrelude:()=> 'const MagnolieTime=('+createTimezonePort.toString()+')(('+createProvider.toString()+'),'+JSON.stringify(payloadText)+','+JSON.stringify(identity)+');\n'
  });
});
