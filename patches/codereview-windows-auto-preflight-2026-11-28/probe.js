function probe(preflight) {
 const chunk=180000, png="image/png", pdf="application/pdf";
 const source=(actual,declared=actual,mime=png,declaredMime=mime)=>({actual,declared,mime,declaredMime});
 const cases=[
 ["no_attachments",[],true],
 ["valid_small",[source(8)],true],
 ["valid_boundary",[source(chunk)],true],
 ["valid_final_byte",[source(chunk+1)],true],
 ["declared_too_short",[source(8,7)],false],
 ["declared_too_long",[source(8,9)],false],
 ["missing_last_chunk",[source(chunk,chunk+1)],false],
 ["extra_chunk",[source(chunk+1,chunk)],false],
 ["wrong_mime",[source(8,8,png,pdf)],false],
 ["second_attachment_invalid",[source(8),source(9,10)],false],
 ];
 return cases.map(([name,sources,valid])=>{
  let requested=0,staged=0,batches=0,complete=false,error="";
  try{
   // This is an explicit control-flow model of the bridge and store.
   // Sources have already passed individual format/hash checks.
   if(preflight&&sources.some(s=>s.actual!==s.declared||s.mime!==s.declaredMime))throw Error("preflight");
   requested=1;
   for(const s of sources){
    const count=Math.ceil(s.actual/chunk), expected=Math.ceil(s.declared/chunk);
    for(let i=0;i<count;i++){
     const actualLength=Math.min(chunk,s.actual-i*chunk);
     const expectedLength=i+1<expected?chunk:s.declared-i*chunk;
     if(i>=expected||actualLength!==expectedLength)throw Error("stage_chunk");
    }
    staged++;
   }
   batches=1;
   // A missing last chunk or wrong MIME is detected at verification, not by StageAttachment.
   if(sources.some(s=>s.actual!==s.declared||s.mime!==s.declaredMime))throw Error("verify");
   complete=true;
  }catch(e){error=e.message}
  return {name,pass:valid?complete&&requested===1&&batches===1:!complete&&requested===0&&staged===0&&batches===0,requested,staged,batches,complete,error};
 });
}
const mode=process.argv[2];
if(!['before','after'].includes(mode)) throw Error('Use before or after');
const result=probe(mode==='after');
console.log(JSON.stringify(result,null,2));
console.log(result.filter(x=>x.pass).length+'/'+result.length);
process.exitCode=result.every(x=>x.pass)?0:1;
