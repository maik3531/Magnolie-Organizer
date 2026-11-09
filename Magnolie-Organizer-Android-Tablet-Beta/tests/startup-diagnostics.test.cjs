'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
module.exports=function run({root=path.resolve(__dirname,'..')}={}) {
  const source=fs.readFileSync(path.join(root,'app/src/androidTest/assets/startup-diagnostics.js'),'utf8');
  const execute=performance=>JSON.parse(JSON.stringify(vm.runInNewContext(source,{
    document:{getElementById:()=>null,readyState:'complete'},window:{Tablet:{},OrganizerTest:{}},
    location:{origin:'https://appassets.androidplatform.net'},Date:{now:()=>100000},URL,performance
  })));
  const nav={startTime:0,duration:31000,domInteractive:20000,domContentLoadedEventStart:21000,
    domContentLoadedEventEnd:25000,loadEventStart:31000,loadEventEnd:31000,name:'private-navigation',serverTiming:'private'};
  const perf={timeOrigin:69000,now:()=>31000,getEntriesByType:type=>type==='navigation'?[nav]:[
    {name:'https://appassets.androidplatform.net/private-path/anwendung.js?secret=private',startTime:30,duration:40,responseEnd:70},
    {name:'https://elsewhere.invalid/private-record',duration:999},
    ...Array.from({length:100},()=>({name:'https://elsewhere.invalid/tablet.js?private',duration:8}))]};
  const result=execute(perf);assert.equal(result.browserTiming.navigation.domContentLoadedEventEnd,25000);
  assert.equal(result.browserTiming.sampledEpochMs-result.browserTiming.timeOriginMs,result.browserTiming.sampledNowMs);
  assert.equal(result.browserTiming.scripts.length,3);assert.equal(result.browserTiming.scripts[2].timing.responseEnd,70);
  assert(!JSON.stringify(result).includes('private'));assert(!JSON.stringify(result).includes('elsewhere'));let count=1;
  const unavailable=execute({now:()=>3,getEntriesByType(){throw Error('private');}});
  assert.equal(unavailable.browserTiming.navigation,null);assert(unavailable.browserTiming.scripts.every(x=>x.timing===null));count++;
  const invalid=execute({timeOrigin:Infinity,now:()=>NaN,getEntriesByType:type=>type==='navigation'?[{duration:-2,fetchStart:NaN}]:[]});
  assert.equal(invalid.browserTiming.timeOriginMs,null);assert.equal(invalid.browserTiming.sampledNowMs,null);
  assert.equal(invalid.browserTiming.navigation.duration,null);assert.equal(invalid.browserTiming.navigation.fetchStart,null);count++;
  console.log('PASS startup timing observation: fixed bounded fields, original clock/navigation values, no URL/query/private text');
  return count;
};
if(require.main===module)module.exports();
