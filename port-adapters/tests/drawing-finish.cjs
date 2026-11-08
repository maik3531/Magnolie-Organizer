'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createHash}=require('node:crypto');
module.exports=function run({web}) {
  const repo=path.resolve(__dirname,'../..');
  const canonical=fs.readFileSync(path.join(repo,'magnolie-organizer/web/zeichenblatt.js'),'utf8');
  const patch=JSON.parse(fs.readFileSync(path.join(repo,'port-adapters/drawing-finish-patch.json')));
  const source=fs.readFileSync(path.join(web,'zeichenblatt.js'),'utf8');
  assert.equal(createHash('sha256').update(canonical).digest('hex'),patch.canonicalSHA256);
  assert.equal(source,canonical.replace(patch.before,patch.after),'only the reviewed finish block changes');
  // Execute the actual Android projector validation block with read-only,
  // disposable input maps; invalid inputs must fail before generated output.
  const projector=fs.readFileSync(path.join(repo,'Magnolie-Organizer-Android-Tablet-Beta/tools/project-web.cjs'),'utf8');
  const start=projector.indexOf('const drawingPatch = '),end=projector.indexOf('// Android does not provide',start);
  assert.ok(start>=0&&end>start);
  const validate=next=>vm.runInNewContext(projector.slice(start,end),{
    buffers:new Map([[path.join(repo,'port-adapters/drawing-finish-patch.json'),Buffer.from(JSON.stringify(next))]]),
    parent:repo,path,Buffer,generated:new Map([['assets/web/zeichenblatt.js',Buffer.from(canonical)]]),
    sha:value=>createHash('sha256').update(value).digest('hex')
  });
  for(const invalid of [{...patch,schema:2},{...patch,canonicalSHA256:'0'.repeat(64)},{...patch,before:patch.before+' changed'}])
    assert.throws(()=>validate(invalid),/Canonical drawing finish anchor changed/);
  const manifestPath=path.join(web,'../projection.json');
  if(fs.existsSync(manifestPath)) {
    const manifest=JSON.parse(fs.readFileSync(manifestPath));
    assert.equal(manifest.inputs['port-adapters/drawing-finish-patch.json'],
      createHash('sha256').update(fs.readFileSync(path.join(repo,'port-adapters/drawing-finish-patch.json'))).digest('hex'));
    assert.equal(manifest.outputs['assets/web/zeichenblatt.js'],createHash('sha256').update(source).digest('hex'));
  }
  const defaults=()=>({globalCompositeOperation:'source-over',globalAlpha:1,lineWidth:1});
  function canvas() {
    let state=defaults(),stack=[],width=0,height=0;
    const value={style:{},trace:[],resets:0,addEventListener(){},removeEventListener(){}};
    const context={};
    for(const name of ['save','restore','clearRect','setTransform','beginPath','arc','fill','moveTo','lineTo','stroke','closePath','bezierCurveTo','drawImage']) {
      context[name]=(...args)=>{
        if(name==='save')stack.push({...state});
        else if(name==='restore')state=stack.pop()||defaults();
        value.trace.push([name,args.map(arg=>typeof arg==='object'?'canvas':arg),{...state}]);
      };
    }
    for(const key of ['globalCompositeOperation','globalAlpha','lineWidth','strokeStyle','fillStyle','lineCap','lineJoin'])
      Object.defineProperty(context,key,{get:()=>state[key],set:v=>{state[key]=v;}});
    const reset=()=>{value.trace=[];state=defaults();stack=[];};
    Object.defineProperties(value,{width:{get:()=>width,set:v=>{width=v;value.resets++;reset();}},height:{get:()=>height,set:v=>{height=v;reset();}}});
    value.getContext=()=>context;return value;
  }
  const sandbox={window:{addEventListener(){},removeEventListener(){}},document:{createElement:canvas}};
  vm.runInNewContext(source,sandbox,{filename:'projected-zeichenblatt.js'});
  const drawing=sandbox.window.MagnolieZeichnen;
  for(const tool of ['pen','eraser','highlighter','quill','brush','rectangle','ellipse','triangle','line','fill']) {
    const target=canvas(),sheet={version:4,width:540,height:236,autoSize:false,strokes:[]};let notifications=0;
    const editor=drawing.attach(target,sheet,()=>notifications++);
    editor.setTool(tool);editor.begin(.2,.3,.7);editor.move(.4,.5,.8);editor.move(.6,.4,.9);
    const model=JSON.stringify(sheet),notified=notifications,resets=target.resets;
    editor.finish();
    assert.equal(target.resets,resets+1,tool+': exactly one canonical render at completion');
    assert.equal(JSON.stringify(sheet),model,tool+': completion preserves all model fields and precision');
    assert.equal(notifications,notified,tool+': completion adds no save notification');
    const direct=canvas();drawing.render(direct,sheet);
    assert.deepEqual(target.trace,direct.trace,tool+': completed primitive commands match direct replay');
    if(tool==='eraser')assert.ok(target.trace.some(x=>x[0]==='stroke'&&x[2].globalCompositeOperation==='destination-out'));
    const completed=target.resets;editor.finish();editor.finish();
    assert.equal(target.resets,completed,tool+': repeated idle finish does not repaint');
    editor.undo();assert.equal(sheet.strokes.length,0);editor.redo();
    assert.equal(JSON.stringify(sheet),model,tool+': Undo/Redo retains exact stroke');
    assert.deepEqual(target.trace,direct.trace,tool+': Redo uses identical primitive commands');
    editor.destroy();assert.equal(JSON.stringify(sheet),model);
  }
  console.log('PASS drawing completion: 10 tools, exact model/direct commands, erasure, Undo/Redo, idle-finish bounds (mock canvas; native pixels remain required)');
  return 1;
};
if(require.main===module)module.exports({web:process.argv[2]});
