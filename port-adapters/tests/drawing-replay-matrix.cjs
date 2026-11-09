// Lifecycle/guard tests only. Fake pixels do not prove native canvas rendering.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
module.exports=function run() {
 const source=fs.readFileSync(path.join(__dirname,'domain-scenarios.js'),'utf8');
 const block=source.slice(source.indexOf('  function drawingReplayDiff('),source.indexOf('  async function drawingProof()'));
 assert(block.includes('function drawingReplayMatrix('));
 assert.match(source,/if\(afterRedo\.png!==after\) \{\s*try \{window\.__domainReplayDiagnostics\.matrix=drawingReplayMatrix/);
 assert.match(source,/catch\(error\) \{window\.__domainReplayDiagnostics\.matrix=\{error:[\s\S]*?assert\(afterRedo\.png===after,'Drawing Redo did not restore rendered pixels'\);await save\(\);/);
 let count=2;
 function execute({failure=false,failAt=1,points=3,mutate=false,width=2,height=2,budgetPixels=null}={}) {
  const nodes=[],controllers=[],book={unknown:{keep:'exact'},drawing:'actual native book'},initial=JSON.stringify(book);
  const fixture={version:4,width,height,autoSize:true,strokes:[{tool:'pen',color:'#1d2433',width:4,points:Array.from({length:points},(_,i)=>[i/(points||1),.5,1]),renderVersion:4}]};
  let reads=0;
  const document={createElement(){const node={width:0,height:0,style:{},toDataURL(){return 'data:image/png;base64,synthetic';},setAttribute(){},remove(){this.removed=true;},getContext(){return {getImageData(){reads++;if(failure&&reads===failAt)throw Error('synthetic read failure');return {data:new Uint8ClampedArray(16)};},drawImage(){}}}};nodes.push(node);return node;},body:{append(node){node.attached=true;}}};
  const engine={render(node){node.width=width;node.height=height;},attach(node,sheet){node.width=width;node.height=height;let saved;
   const controller={setTool(){},setWidth(){},setColor(){},begin(...p){sheet.strokes=[{...fixture.strokes[0],points:[p]}];},move(...p){sheet.strokes[0].points.push(p);},finish(){},undo(){saved=sheet.strokes;sheet.strokes=[];},redo(){sheet.strokes=saved;if(mutate)book.drawing='corrupted';},destroy(){this.destroyed=true;}};
   controllers.push(controller);return controller;}};
  const context={T:{daten:()=>book},clone:value=>JSON.parse(JSON.stringify(value)),assert:(value,message)=>{if(!value)throw Error(message);},document,MagnolieZeichnen:engine,performance:{now:()=>0},TextEncoder,Uint8ClampedArray,$:()=>({getBoundingClientRect:()=>({left:1,top:2,width:2,height:2})})};
  vm.createContext(context);vm.runInContext((budgetPixels===null?block:block.replace('readbackLimitPixels=4000000',`readbackLimitPixels=${budgetPixels}`))+'\nthis.matrix=drawingReplayMatrix;',context);
  const result=context.matrix(new Uint8ClampedArray(16),new Uint8ClampedArray(16),fixture);
  return {result,nodes,controllers,reads,bookUnchanged:initial===JSON.stringify(book)};
 }
 const good=execute();assert.equal(good.result.bookUnchanged,true);assert.equal(good.result.fixtureUnchanged,true);
 assert.equal(Object.keys(good.result.comparisons).length,13);assert(good.nodes.every(node=>node.removed));assert(good.controllers.every(controller=>controller.destroyed));
 assert.equal(good.nodes.filter(node=>node.attached).length,1);assert.equal(good.bookUnchanged,true);count++;
 assert.deepEqual(JSON.parse(JSON.stringify(good.result.readback)),{unit:'pixels',limit:4000000,used:72,reads:18,nativeReadsReserved:5});
 assert.equal(good.result.readbackSequences.pngOnly.pngReads,6);assert.equal(good.result.readbackSequences.pngOnly.rgbaReads,0);
 assert.equal(good.result.readbackSequences.getImageDataBeforeEachPNG.rgbaReads,6);count++;
 const android=execute({width:794,height:236});assert(!android.result.error,android.result.error);assert.equal(android.result.readback.used,3372912);count++;
 for(const [width,height] of [[795,236],[793,236],[794,235],[540,237]]) {const rejected=execute({width,height});assert.match(rejected.result.error,/approved pen fixture bounds/);assert.equal(rejected.reads,0);}count++;
 const budget=execute({budgetPixels:40});assert.match(budget.result.error,/readback pixel budget exceeded/);assert(budget.result.readback.used<=40);assert(budget.nodes.every(node=>node.removed));assert(budget.controllers.every(controller=>controller.destroyed));count++;
 const failed=execute({failure:true});assert.match(failed.result.error,/synthetic read failure/);assert.equal(failed.result.bookUnchanged,true);assert(failed.nodes.every(node=>node.removed));count++;
 const late=execute({failure:true,failAt:7});assert.match(late.result.error,/synthetic read failure/);assert.equal(late.controllers.length,2);assert(late.controllers.every(controller=>controller.destroyed));assert(late.nodes.every(node=>node.removed));count++;
 const oversized=execute({points:26});assert.match(oversized.result.error,/approved pen fixture bounds/);assert.equal(oversized.nodes.length,0);assert.equal(oversized.reads,0);count++;
 const mutated=execute({mutate:true});assert.equal(mutated.result.bookUnchanged,false);assert(mutated.nodes.every(node=>node.removed));assert(mutated.controllers.every(controller=>controller.destroyed));count++;
 return count;
};
if(require.main===module)console.log(`Drawing matrix lifecycle/guard checks: ${module.exports()} passed; native rendering not claimed.`);
