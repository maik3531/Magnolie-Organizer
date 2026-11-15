"use strict";
// #658: existing canonical duplicate-helper semantics, not a new mail policy.
const fs=require("node:fs"),path=require("node:path"),Module=require("node:module"),assert=require("node:assert/strict");
const file=path.join(__dirname,"desktop-state-regressions.js"),host=new Module(file,module);
host.filename=file;host.paths=Module._nodeModulePaths(__dirname);
host._compile(fs.readFileSync(file,"utf8").split("async function run(web)")[0]+"\nmodule.exports={boot,roots};",file);
(async()=>{
 assert.equal(host.exports.roots.length,2,"Both canonical GUI sources are required");
 let cases=0;
 for(const web of host.exports.roots){
  const b=await host.exports.boot(web);
  try{
   for(const variant of ["MAILBOX@EXAMPLE.ORG","mailto:Mailbox@Example.ORG","Mailbox Person <MailBox@Example.ORG>"]){
    const left={id:"case-left",uid:"case-left@example.org",vorname:"Synthetic",nachname:"Mailbox",notiz:"Left note",
     email:"mailbox@example.org",emails:["mailbox@example.org"],
     emailEintraege:[{wert:"mailbox@example.org",typen:["HOME"],label:"Home",vcardParameter:["X-SYNTHETIC=left"]}],
     vcardRoundtrip:["EMAIL;TYPE=HOME:mailbox@example.org","X-SYNTHETIC-LEFT:keep"]};
    const right={id:"case-right",uid:"case-right@example.org",vorname:"Synthetic",nachname:"Mailbox",firma:"Synthetic company",notiz:"Right note",
     email:variant,emails:[variant,"other@example.org"],
     emailEintraege:[{wert:variant,typen:["WORK"],label:"Work",vcardParameter:["X-SYNTHETIC=right"]}],
     vcardRoundtrip:["EMAIL;TYPE=WORK:MailBox@Example.ORG","X-SYNTHETIC-RIGHT:keep"]};
    const raw=[...right.vcardRoundtrip,...left.vcardRoundtrip];
    const result=b.t.fuehreZusammen([left,right]);
    assert.equal(result.bleibt,right);assert.equal(result.entfernt[0],left);
    assert.equal(right.id,"case-right");assert.equal(right.uid,"case-right@example.org");
    assert.equal(right.email,"mailbox@example.org");
    assert.deepEqual(Array.from(right.emails),["mailbox@example.org","other@example.org"]);
    assert.equal(right.emailEintraege.length,2);
    const entry=right.emailEintraege[0];assert.equal(entry.wert,"mailbox@example.org");
    assert.deepEqual(new Set(entry.typen),new Set(["HOME","WORK"]));assert.equal(entry.label,"Work");
    assert.deepEqual(new Set(entry.vcardParameter),new Set(["X-SYNTHETIC=left","X-SYNTHETIC=right"]));
    assert.deepEqual(Array.from(right.vcardRoundtrip),raw,"Opaque source spelling/parameters must not be rewritten");
    assert.ok(right.notiz.includes("Left note")&&right.notiz.includes("Right note"));cases++;
   }
  }finally{b.close();}
 }
 console.log(JSON.stringify({canonicalEmailDuplicateCases:cases,bothGUIs:true,productionChanged:false,nativeProviderMergeAcceptance:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
