'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),readline=require('node:readline');
const provider=require('./resolver.js')(JSON.parse(fs.readFileSync(process.env.TIMEZONE_PAYLOAD || __dirname+'/tzdb-2026egtz.json','utf8')));
readline.createInterface({input:process.stdin}).on('line',line=>{
 try {
  const rows=JSON.parse(line);
  const failures=[];
  for(const row of rows) {
   try {
   if(row[0]==='o') {
    const [,id,at,offset,wall]=row;
    assert.equal(provider.offsetAt(id,at),offset,id+' '+at);
    const p=provider.wallParts(id,at);assert.deepEqual([p.year,p.month,p.day,p.hour,p.minute,p.second,p.millisecond],wall,id+' wall '+at);
   } else {
    const [,id,p,valid,forward]=row;
    const parts={year:p[0],month:p[1],day:p[2],hour:p[3],minute:p[4],second:p[5],millisecond:p[6]};
    if(valid.length) {
     assert.equal(provider.resolveWall(id,parts,{fold:'earlier'}),valid[0],id+' earlier '+p);
     assert.equal(provider.resolveWall(id,parts,{fold:'later'}),valid[valid.length-1],id+' later '+p);
     if(valid.length>1) assert.throws(()=>provider.resolveWall(id,parts,{fold:'reject'}),{code:'ambiguous-timezone-wall'});
    } else {
     assert.throws(()=>provider.resolveWall(id,parts),{code:'nonexistent-timezone-wall'},id+' gap '+p);
     assert.equal(provider.resolveWall(id,parts,{gap:'omit'}),null);
     assert.equal(provider.resolveWall(id,parts,{gap:'forward'}),forward,id+' forward '+p);
    }
   }
   }catch(error){failures.push({identifier:row[1],sample:row,error:String(error)});}
  }
  process.stdout.write(JSON.stringify({checked:rows.length,failures})+'\n');
 }catch(error){process.stdout.write(JSON.stringify({error:error.stack})+'\n');process.exitCode=1;process.stdin.destroy();}
});
