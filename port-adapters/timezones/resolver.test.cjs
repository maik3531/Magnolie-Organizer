'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),create=require('./resolver.js');
const source=JSON.parse(fs.readFileSync(__dirname+'/tzdb-2026egtz.json','utf8')),provider=create(source);
const manifest=JSON.parse(fs.readFileSync(__dirname+'/provenance.json','utf8'));
assert.equal(manifest.schema,2);assert.equal(manifest.payloadSHA256,crypto.createHash('sha256').update(fs.readFileSync(__dirname+'/tzdb-2026egtz.json')).digest('hex'));
assert.equal(source.sourceArchiveSHA256,manifest.archiveSHA256);assert.equal(source.rules.length,manifest.uniqueRuleData);
const utc=(y,m,d,h=0,min=0,s=0)=>{const v=new Date(0);v.setUTCFullYear(y,m-1,d);v.setUTCHours(h,min,s,0);return +v;};
assert.equal(provider.identifiers.length,597);assert.equal(provider.version,'2026egtz');
let duplicates=0;const groups=new Map();
for(const [name,index] of Object.entries(source.zones)) {
 if(!groups.has(index))groups.set(index,name);else {
  duplicates++;
  for(const year of [1,99,400,2400,9999])for(const month of [1,7])
   assert.equal(provider.offsetAt(name,utc(year,month,15,12)),provider.offsetAt(groups.get(index),utc(year,month,15,12)));
 }
 const row=source.rules[index],history=row[2],types=row[1];
 // Both last history boundaries are inclusive; preserve predecessor offsets.
 for(let i=Math.max(0,history.length-4);i<history.length;i+=2) {
  const at=history[i]*1000;
  assert.equal(provider.offsetAt(name,at),types[history[i+1]][0]);
  assert.equal(provider.offsetAt(name,at-1),types[i?history[i-1]:row[0]][0]);
 }
}
assert.equal(duplicates,158);
const before=provider.offsetAt('Europe/Berlin',utc(2400,7,15));source.rules[source.zones['Europe/Berlin']][1][0][0]=123;source.zones['Europe/Berlin']=0;
assert.equal(provider.offsetAt('Europe/Berlin',utc(2400,7,15)),before,'caller mutation cannot change provider');
for(const year of [1,99,400,2400,9999])for(const name of ['UTC','Etc/UTC','GMT','UT','Z']) {
 const at=provider.resolveWall(name,{year,month:1,day:1});assert.equal(at,utc(year,1,1));assert.equal(provider.wallParts(name,at).year,year);
}
for(const [name,offset] of [['Etc/GMT-14',50400],['Etc/GMT+12',-43200]])for(const [year,month,day,hour] of [[1,1,1,0],[9999,12,31,23]]) {
 const at=provider.resolveWall(name,{year,month,day,hour});assert.equal(at,utc(year,month,day,hour)-offset*1000);assert.equal(provider.wallParts(name,at).year,year);
}
const model=tail=>create({schema:2,tzdbVersion:'2026egtz',zones:{Synthetic:0},rules:[[0,[[tail[0],0,tail[1],0,0],[tail[2]??tail[0],1,tail[3]??tail[1],0,0]],[],tail]]});
// UTC/STANDARD/WALL source rules normalize to exact POSIX wall-clock hours.
for(const [definition,clock,hour] of [['UTC',4,2],['STANDARD',3,1],['WALL',2,0]]) {
 const p=model([7200,'STD',10800,'DST',['J',152,0,0,clock*3600],['J',244,0,0,18000],`STD-2DST-3,J152/${clock},J244/5`]);
 const at=utc(2400,6,1,hour);assert.equal(p.offsetAt('Synthetic',at-1),7200,definition);assert.equal(p.offsetAt('Synthetic',at),10800,definition);
 const gap={year:2400,month:6,day:1,hour:hour+2,minute:30};
 assert.throws(()=>p.resolveWall('Synthetic',gap),{code:'nonexistent-timezone-wall'});
 assert.equal(p.resolveWall('Synthetic',gap,{gap:'forward'}),at+1800000);assert.equal(p.resolveWall('Synthetic',gap,{gap:'omit'}),null);
}
for(const [kind,day,date] of [['J',60,'J60'],['N',59,'59']])for(const year of [1,99,400,2400,9999]) {
 const p=model([0,'STD',3600,'DST',[kind,day,0,0,0],['J',300,0,0,7200],`STD0DST,${date}/0,J300`]);
 const leap=year%4===0&&(year%100!==0||year%400===0);const at=kind==='N'&&leap?utc(year,2,29):utc(year,3,1);
 assert.equal(p.offsetAt('Synthetic',at-1),0);assert.equal(p.offsetAt('Synthetic',at),3600);
}
const midnight=model([0,'STD',3600,'DST',['J',365,0,0,86400],['J',152,0,0,0],'STD0DST,J365/24,J152/0']);
for(const year of [1,99,400,2400,9999]){const at=utc(year,1,1);assert.equal(midnight.offsetAt('Synthetic',at-1),0);assert.equal(midnight.offsetAt('Synthetic',at),3600);}
const day365=model([0,'STD',3600,'DST',['N',365,0,0,0],['J',152,0,0,0],'STD0DST,365/0,J152/0']);
for(const at of [utc(2000,12,31),utc(2002,1,1)]){assert.equal(day365.offsetAt('Synthetic',at-1),0);assert.equal(day365.offsetAt('Synthetic',at),3600);}
for(const [clock,text] of [[-604799,'-167:59:59'],[604799,'167:59:59']]) {
 const p=model([0,'STD',3600,'DST',['J',60,0,0,clock],['J',300,0,0,7200],`STD0DST,J60/${text},J300`]);
 const at=utc(2400,3,1)+clock*1000;assert.equal(p.offsetAt('Synthetic',at-1),0);assert.equal(p.offsetAt('Synthetic',at),3600);
}
const month=model([0,'STD',3600,'DST',['M',3,5,0,7200],['M',10,5,0,10800],'STD0DST,M3.5.0,M10.5.0/3']);
const fold={year:2026,month:10,day:25,hour:2,minute:30};
assert.equal(month.resolveWall('Synthetic',fold,{fold:'earlier'}),utc(2026,10,25,1,30));
assert.equal(month.resolveWall('Synthetic',fold,{fold:'later'}),utc(2026,10,25,2,30));
assert.throws(()=>month.resolveWall('Synthetic',fold,{fold:'reject'}),{code:'ambiguous-timezone-wall'});
// Actual regressions: never let future rules overwrite historical policy.
assert.equal(provider.resolveWall('America/Indiana/Petersburg',{year:2007,month:3,day:11,hour:2,minute:30},{gap:'forward'}),1173601800000);
for(const name of ['Asia/Gaza','Asia/Hebron'])assert.equal(provider.resolveWall(name,{year:2074,month:7,day:15,hour:12,minute:30}),utc(2074,7,15,9,30));
for(const p of [{year:0,month:1,day:1},{year:99,month:2,day:29},{year:2400,month:1,day:32},{year:2400,month:1,day:1,hour:24}])assert.throws(()=>provider.resolveWall('UTC',p),{code:'invalid-timezone-wall'});
for(const id of ['Unknown/Raw-source','__proto__'])assert.throws(()=>provider.offsetAt(id,0),{code:'unknown-time-zone'});
assert.equal(provider.has('Factory'),false);assert.throws(()=>provider.offsetAt('Factory',0),{code:'unsupported-time-zone'});
assert.throws(()=>provider.offsetAt('UTC',NaN),{code:'invalid-timezone-instant'});
assert.throws(()=>provider.resolveWall('UTC',{year:2400,month:1,day:1},{fold:'guess'}),{code:'invalid-timezone-policy'});
assert.throws(()=>create({schema:3}),{code:'invalid-timezone-database'});
for(const bad of ['', 'STD0DST', 'STD0DST,M3.5.0/2u,M10.5.0/3', 'STD0DST,J60/168,J300']) {
 assert.throws(()=>model([0,'STD',3600,'DST',['J',60,0,0,7200],['J',300,0,0,7200],bad]));
}
// Aggregate limits must reject before the first potentially large rules copy.
const fixedRow=()=>[0,[[0,0,'STD',0,0]],[],[0,'STD',null,null,null,null,'STD0']];
const bounded=(rules,zones={Synthetic:0})=>({schema:2,tzdbVersion:'2026egtz',rules,zones});
const rejectBeforeCopy=packet=>{
 packet.rules.map=()=>{throw new Error('copied before aggregate preflight')};
 assert.throws(()=>create(packet),{code:'timezone-database-limit'});
};
rejectBeforeCopy(bounded(Array.from({length:1025},fixedRow)));
rejectBeforeCopy(bounded([fixedRow()],Object.fromEntries(Array.from({length:2049},(_,i)=>['Zone'+i,0]))));
const tooManyTransitions=[fixedRow(),fixedRow()];tooManyTransitions[0][2]=new Array(120000).fill(0);tooManyTransitions[1][2]=new Array(80002).fill(0);rejectBeforeCopy(bounded(tooManyTransitions));
const tooManyTypes=Array.from({length:33},()=>{const row=fixedRow();row[1]=Array.from({length:256},()=>[0,0,'STD',0,0]);return row});rejectBeforeCopy(bounded(tooManyTypes));
const tooManyStrings=Array.from({length:1024},()=>{const row=fixedRow();row[1]=Array.from({length:8},()=>[0,0,'x'.repeat(64),0,0]);row[3][1]='x'.repeat(64);row[3][6]='x'.repeat(512);return row});rejectBeforeCopy(bounded(tooManyStrings));
for(const mutate of [p=>p.zones={['x'.repeat(256)]:0},p=>p.rules[0][1][0][2]='x'.repeat(65),p=>p.rules[0][3][6]='x'.repeat(513),p=>p.rejectedZones=Object.fromEntries(Array.from({length:17},(_,i)=>['Zone'+i,'unsupported']))]) {
 const packet=bounded([fixedRow()]);mutate(packet);rejectBeforeCopy(packet);
}
const inherited=bounded([fixedRow()]);inherited.zones=Object.create({Hidden:0});assert.throws(()=>create(inherited),{code:'invalid-timezone-database'});
const start=performance.now();for(let i=0;i<10000;i++)provider.offsetAt('Europe/Berlin',utc(2400+i%400,7,15,12));
console.log(JSON.stringify({unit:'shared normative timezone resolver',namedZones:597,duplicateDataAliases:duplicates,allPassed:true,nodePoint10kMs:performance.now()-start,nativeDeviceProof:false}));
