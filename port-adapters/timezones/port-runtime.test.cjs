'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),cp=require('node:child_process');
const create=require('./port-runtime.js'),providerFactory=require('./resolver.js'),assets=require('./projection-assets.cjs');
const read=name=>fs.readFileSync(path.join(__dirname,name)),text=read('tzdb-2026egtz.json').toString(),manifest=JSON.parse(read('provenance.json'));
let system='Europe/Berlin';const port=create(providerFactory,text,manifest,()=>system);
assert.equal(port.identity.payloadSHA256,crypto.createHash('sha256').update(text).digest('hex'));
assert.equal(port.zoneId('US/Eastern'),'US/Eastern');assert.equal(port.systemIdentifier(),'Europe/Berlin');
system='America/New_York';assert.equal(port.zoneId('system'),'America/New_York');
assert.throws(()=>port.zoneId('Unknown/RawSource'),{code:'unresolved-time-zone'});
assert.throws(()=>port.offsetAt('UTC',null),{code:'invalid-timezone-instant'});
assert.throws(()=>port.offsetAt('UTC','0'),{code:'invalid-timezone-instant'});
for(const invalid of ['',null]) {
 assert.throws(()=>port.formatParts(0,'en',{timeZone:invalid},'Europe/Berlin'),{code:'unresolved-time-zone'});
 assert.throws(()=>port.formatCivil({year:2026,month:1,day:1},'en',{timeZone:invalid}),{code:'civil-time-has-no-zone'});
}
assert.ok(port.formatParts(0,'en',{timeZone:undefined},'Europe/Berlin').length>0);
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'../tests/timezone-interop-oracle.json')));
const utc=wall=>{const [date,time]=wall.split('T'),[y,m,d]=date.split('-').map(Number),[h,min]=time.split(':').map(Number);const result=new Date(0);result.setUTCFullYear(y,m-1,d);result.setUTCHours(h,min,0,0);return result;};
let clocks=0,formats=0;
for(const row of fixture.clocks) {
 const d=utc(row.wall),parts={year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate(),hour:d.getUTCHours(),minute:d.getUTCMinutes()};
 assert.equal(port.resolveWall(row.identifier,parts),row.epochMs);assert.equal(port.offsetAt(row.identifier,row.epochMs),row.offsetSeconds);clocks++;
 for(const locale of ['en-CA','de-DE','ar-EG','fa-IR','ja-JP-u-ca-japanese'])for(const options of [
  {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZoneName:'short'},
  {dateStyle:'full',timeStyle:'long',hourCycle:'h12'}]) {
  const expected=new Intl.DateTimeFormat(locale,{...options,timeZone:'UTC'}).formatToParts(d)
   .map(p=>p.type==='timeZoneName'?port.offsetLabel(row.offsetSeconds):p.value).join('');
  assert.equal(port.format(row.epochMs,locale,options,row.identifier),expected,row.identifier+row.wall+locale);formats++;
 }
}
assert.equal(clocks,37);assert.equal(formats,370);
assert.equal(port.resolveWall('Asia/Gaza',{year:2074,month:7,day:15,hour:12,minute:30}),+utc('2074-07-15T09:30'));
assert.deepEqual(port.candidates('Europe/Berlin',{year:2026,month:10,day:25,hour:2,minute:30}),[Date.parse('2026-10-25T00:30Z'),Date.parse('2026-10-25T01:30Z')]);
assert.deepEqual(port.candidates('Europe/Berlin',{year:2026,month:3,day:29,hour:2,minute:30}),[]);
assert.equal(port.formatCivil({year:2026,month:3,day:29,hour:2,minute:30},'en-GB',{hour:'2-digit',minute:'2-digit',hourCycle:'h23'}),'02:30');
assert.equal(port.offsetLabel(1172),'UTC+00:19:32');assert.equal(port.offsetLabel(-2670),'UTC-00:44:30');
// UTC carriers must preserve small years and offset seconds across UTC years.
const fieldMap=parts=>Object.fromEntries(parts.filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));
for(const year of [1,99]) {
 const at=port.resolveWall('Etc/GMT-14',{year,month:1,day:1});
 const parts=fieldMap(port.formatParts(at,'en-GB',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',era:'short',timeZoneName:'short'},'Etc/GMT-14'));
 assert.equal(parts.year,String(year));assert.equal(parts.era,'AD');assert.equal(parts.month,'01');assert.equal(parts.day,'01');assert.equal(parts.hour,'00');assert.equal(parts.timeZoneName,'UTC+14:00');
 assert.match(port.formatCivil({year,month:1,day:1},'en-GB',{year:'numeric',era:'short'}),new RegExp('^'+year+' AD$'));
}
for(const [id,year,month,day,hour,offset] of [['Europe/Paris',1910,1,15,0,561],['Africa/Monrovia',1971,1,15,12,-2670],['Etc/GMT+12',9999,12,31,23,-43200]]) {
 const at=port.resolveWall(id,{year,month,day,hour,minute:0,second:0});
 const parts=fieldMap(port.formatParts(at,'en-GB',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZoneName:'short'},id));
 assert.equal(port.offsetAt(id,at),offset);assert.equal(parts.year,String(year));assert.equal(parts.month,String(month).padStart(2,'0'));assert.equal(parts.day,String(day).padStart(2,'0'));assert.equal(parts.hour,String(hour).padStart(2,'0'));assert.equal(parts.minute,'00');assert.equal(parts.second,'00');assert.equal(parts.timeZoneName,port.offsetLabel(offset));
}
assert.ok(!port.formatCivil({year:2026,month:3,day:29,hour:2,minute:30},'en-GB',{timeStyle:'long'}).includes('UTC'),'floating civil time has no invented UTC label');
const worker=vm.runInNewContext(port.workerPrelude()+'MagnolieTime',{Intl});
assert.equal(worker.identity.payloadSHA256,manifest.payloadSHA256);assert.equal(worker.resolveWall('Asia/Gaza',{year:2074,month:7,day:15,hour:12,minute:30}),+utc('2074-07-15T09:30'));
const generated=assets(read),sandbox={Intl};vm.createContext(sandbox);vm.runInContext(generated['normative-timezones.js'].toString(),sandbox);
assert.equal(vm.runInContext('MagnolieTime.identity.payloadSHA256',sandbox),manifest.payloadSHA256);
assert.equal(vm.runInContext('MagnolieTime.resolveWall("Asia/Gaza",{year:2074,month:7,day:15,hour:12,minute:30})',sandbox),+utc('2074-07-15T09:30'));
assert.equal(Object.getOwnPropertyDescriptor(sandbox,'MagnolieTime').writable,false);
for(const target of ['tzdb-2026egtz.json','LICENSE-tzdb.txt']) {
 assert.throws(()=>assets(name=>{const b=read(name);if(name===target){const copy=Buffer.from(b);copy[0]^=1;return copy;}return b;}),/source\/identity\/license mismatch/);
}
assert.throws(()=>assets(name=>name==='bootstrap.template.js'?Buffer.from(read(name).toString().replace('/*NORMATIVE_TZDB_TEXT*/null','null')):read(name)),/bootstrap anchor changed/);
// The actual Python Mac projector helper must emit exactly the same bytes.
const repo=path.resolve(__dirname,'../..');
const python=`import sys,importlib.util,pathlib\nsys.dont_write_bytecode=True\nroot=pathlib.Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('projection',root/'Magnolie-Organizer-macOS-Beta/tools/project_ui.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\nprefix='port-adapters/timezones/';folder=root/'port-adapters/timezones';snapshot={prefix+p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}\nif len(sys.argv)>2:snapshot[prefix+sys.argv[2]]=b'x'+snapshot[prefix+sys.argv[2]][1:]\nsys.stdout.buffer.write(m.timezone_assets(snapshot)['normative-timezones.js'])\n`;
const mac=cp.execFileSync('python3',['-c',python,repo],{maxBuffer:2*1024*1024});assert.deepEqual(mac,generated['normative-timezones.js']);
for(const target of ['tzdb-2026egtz.json','LICENSE-tzdb.txt']){const bad=cp.spawnSync('python3',['-c',python,repo,target],{encoding:'utf8'});assert.notEqual(bad.status,0);assert.match(bad.stderr,/source\/identity\/license mismatch/);}
if(process.argv.includes('--projection')) {
 const web=path.join(repo,'Magnolie-Organizer-Android-Tablet-Beta/app/build/generated/projection/assets/web');
 assert.deepEqual(fs.readFileSync(path.join(web,'normative-timezones.js')),mac);
 const html=fs.readFileSync(path.join(web,'index.html'),'utf8');assert.ok(html.indexOf('normative-timezones.js')<html.indexOf('<script src="tablet.js"'));
 assert.ok(html.indexOf('normative-timezones.js')<html.indexOf('<script src="anwendung.js"'));
 for(const name of ['tzdb-2026egtz.json','provenance.json','LICENSE-tzdb.txt'])assert.deepEqual(fs.readFileSync(path.join(web,'timezones',name)),read(name));
}
console.log(JSON.stringify({checkpoint:'bootstrap/runtime only; app time hooks unchanged',externalClocks:clocks,localeFormats:formats,byteIdenticalProjectors:true,workerPreludeSyntax:true,actualBrowserWorkerProof:false,nativeDeviceProof:false}));
