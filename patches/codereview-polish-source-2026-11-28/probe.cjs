"use strict";
function audit(csv,subdivisions){
  const split=s=>s.replace(/^\uFEFF/,"").trimEnd().split(/\r?\n/).map(l=>l.split(";"));
  const rows=split(csv).slice(1), mapRows=split(subdivisions).slice(1), isoMap=new Map(mapRows.map(r=>[r[2],r[3]]));
  const regionKeys=["02","04","06","08","10","12","14","16","18","20","22","24","26","28","30","32"].map(x=>"PL-"+x);
  const official=[
    ["2026-01-19","2026-02-01",["14","20","22","26","28"]],
    ["2026-02-02","2026-02-15",["02","04","10","12","16","32"]],
    ["2026-02-16","2026-03-01",["06","08","18","24","30"]],
    ["2027-01-18","2027-01-31",["02","10","16","18","20","24"]],
    ["2027-02-01","2027-02-14",["06","14","22","26"]],
    ["2027-02-15","2027-02-28",["04","08","12","28","30","32"]]
  ];
  const national=[["2026-12-23","2026-12-31"],["2027-03-25","2027-03-30"],["2027-06-26","2027-08-31"]];
  const out=[];
  const add=(name,ok,actual)=>out.push({name,ok:Boolean(ok),actual});
  add("16 distinct ISO/provider mappings",isoMap.size===16&&regionKeys.every(k=>isoMap.has(k))&&new Set(isoMap.values()).size===16,[...isoMap]);
  add("unique valid IDs",new Set(rows.map(r=>r[0])).size===rows.length&&rows.every(r=>/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(r[0])),rows.length);
  const regional=rows.filter(r=>r[1]==="PL"&&r[4]==="School"&&r[5]==="Regional"&&r[6].includes("PL Ferie zimowe"));
  for(const year of ["2026","2027"]){
    for(const iso of regionKeys){
      const expected=official.find(g=>g[0].startsWith(year)&&g[2].includes(iso.slice(3)));
      const actual=regional.filter(r=>r[2].startsWith(year)&&r[7].split(",").includes(isoMap.get(iso))).map(r=>[r[2],r[3]]);
      add(year+" winter "+iso,actual.length===1&&actual[0][0]===expected[0]&&actual[0][1]===expected[1],actual);
    }
  }
  for(const [start,end] of national){
    for(const iso of regionKeys){
      const actual=rows.filter(r=>r[1]==="PL"&&r[4]==="School"&&r[5]==="National"&&r[2]===start&&r[3]===end&&r[7].split(",").includes(isoMap.get(iso)));
      add("national "+start+" "+iso,actual.length===1,actual.length);
    }
  }
  add("all targeted scopes use known distinct provider codes",rows.filter(r=>r[2]>="2026-01-01").every(r=>{const codes=r[7].split(",");return codes.every(c=>[...isoMap.values()].includes(c))&&new Set(codes).size===codes.length}),null);
  return out;
}
const fs=require("node:fs");
if(process.argv.length!==4)throw Error("usage: node probe.cjs holidays.school.csv subdivisions.csv");
const r=audit(fs.readFileSync(process.argv[2],"utf8"),fs.readFileSync(process.argv[3],"utf8"));
console.log(JSON.stringify({total:r.length,passed:r.filter(x=>x.ok).length,failed:r.filter(x=>!x.ok)},null,2));
process.exitCode=r.every(x=>x.ok)?0:1;
