'use strict';
// #447: bounded projector compatibility, no product/UI build or native claims.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const repo=path.resolve(__dirname,'../..'),read=name=>fs.readFileSync(path.join(__dirname,name)),apply=require('./projection-patches.cjs');
const python=`import sys,pathlib,importlib.util
sys.dont_write_bytecode=True
r=pathlib.Path(sys.argv[1]);s=importlib.util.spec_from_file_location('p',r/'Magnolie-Organizer-macOS-Beta/tools/project_ui.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
p='port-adapters/timezones/';snap={p+f.name:f.read_bytes() for f in (r/p).iterdir() if f.is_file()}
sys.stdout.buffer.write(m.apply_timezone_patches(sys.stdin.buffer.read().decode(),snap).encode())
`;
function mac(source){return cp.spawnSync('python3',['-B','-c',python,repo],{input:source,encoding:'utf8',maxBuffer:8*1024*1024});}
let checks=0;
for(const relative of ['magnolie-organizer/web/anwendung.js','magnolie-organizer-windows/app/web/anwendung.js']) {
 const canonical=fs.readFileSync(path.join(repo,relative),'utf8'),promoted=apply(canonical,read);
 assert.equal(apply(promoted,read,true,canonical),canonical);checks++;
 assert.equal(apply(promoted,read),promoted);checks++;
 assert.equal(apply(promoted,read,true,promoted),promoted);checks++;
 const result=mac(promoted);assert.equal(result.status,0,result.stderr);assert.equal(result.stdout,promoted);checks++;
 const marker='/*TZ_PORT:validate-zone:BEGIN*/';
 for(const bad of [promoted.replace(marker,''),promoted.replace(marker,marker+'\n/* altered */'),promoted+marker,
                  promoted.replace('return MagnolieTime.has(zone) ? zone : "";','return "UTC";')]) {
  assert.throws(()=>apply(bad,read),/projection match changed/);
  assert.throws(()=>apply(bad,read,true,promoted),/projection match changed/);
  const rejected=mac(bad);assert.notEqual(rejected.status,0);assert.match(rejected.stderr,/projection match changed/);checks+=3;
 }
}
console.log(JSON.stringify({promotedHookCompatibilityChecks:checks,bothCanonicalGUIs:true,pythonAndJavaScriptProjectors:true,nativeProof:false}));
