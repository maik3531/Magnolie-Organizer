"use strict";
const fs=require("node:fs"),path=require("node:path"),Module=require("node:module"),assert=require("node:assert/strict");
const canonicalHarness=path.resolve(__dirname,"../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const source=fs.existsSync(canonicalHarness)?canonicalHarness:path.resolve(__dirname,"../../../tests/desktop-state-regressions.js");
const harness=new Module(source,module);harness.filename=source;harness.paths=Module._nodeModulePaths(path.dirname(source));
harness._compile(fs.readFileSync(source,"utf8").split("async function run(web)")[0]+"\nmodule.exports={boot,roots};",source);
const group={id:"waste-fixture",von:"2026-12-25",name:"Synthetic waste",intervallTage:7,art:"residual",farbe:"#4c4b47"};
const imported=extra=>({...group,importQuelle:"waste:ics:"+"a".repeat(64),importierteTermine:[{
 id:"municipal-fixture",uid:"municipal-uid",datum:"2026-12-25",titel:"Synthetic waste",zeit:"",
 icsRoundtrip:["BEGIN:VEVENT","DTSTART;VALUE=DATE:20261225","RRULE:FREQ=WEEKLY;COUNT=3","EXDATE;VALUE=DATE:20270101",...extra,"END:VEVENT"]
}]});
(async()=>{
 let passed=0;
 for(const web of harness.exports.roots) for(const kind of ["manual","municipal-replacement","municipal-no-replacement"]){
  const b=await harness.exports.boot(web,{einstellungen:{kalender:{muellkalenderAn:true}},
   feiertage:[{datum:"2027-01-01",name:"Synthetic New Year",typ:"public-holiday"}],
   muelltermine:[kind==="manual"?group:imported(kind==="municipal-replacement"?["RDATE;VALUE=DATE:20270102"]:[])]});
  try{
   const unchanged=JSON.stringify(b.t.daten());
   const dates=["2027-01-01","2027-01-02","2027-01-08"];
   const actual=dates.map(day=>b.t.muelltermineAm(day).length>0);
   assert.deepEqual(actual,kind==="manual"?[true,false,true]:kind==="municipal-replacement"?[false,true,true]:[false,false,true],kind);
   assert.equal(JSON.stringify(b.t.daten()),unchanged,"Holiday lookup changed source data");
   assert.equal(b.t.daten().termine.length,0,"Waste lookup created ordinary appointments");
   passed++;
  }finally{b.close();}
 }
 console.log(`${passed} dual-desktop waste holiday authority cases PASS`);
})().catch(error=>{console.error(error);process.exitCode=1;});
