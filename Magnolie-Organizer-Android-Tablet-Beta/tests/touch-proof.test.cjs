const assert=require('node:assert/strict');
const {create}=require('../app/src/androidTest/assets/touch-proof.js');
const target={}, other={};
const expected={documentId:'renderer-1',token:'token-1',step:13,target,node:4,label:'Calendar',section:'kalender',before:'notizen',armedAt:100,sourceHash:'frozen-source'};
const event=(type,overrides={})=>({type,target,documentId:'renderer-1',token:'token-1',step:13,node:4,trusted:true,connected:true,stamp:140,at:150,pointerId:7,pointerType:'touch',button:0,...overrides});
const finish=p=>p.finish('kalender',true,'Calendar','register:kalender',null);
function pair(p,override={}) {p.observe(event('pointerdown',{stamp:100,...override}));p.observe(event('pointerup',override));p.observe(event('click',override));}
let cases=0;
function test(name,fn){fn();cases++;console.log('PASS '+name);}
test('real matching sequence requires an actual state transition and acknowledges once',()=>{
 const p=create(expected);pair(p);assert.equal(p.finish('notizen',true,'Calendar','register:kalender',null),null);
 const ack=finish(p);assert.equal(ack.step,13);assert.equal(ack.sourceHash,'frozen-source');assert.equal(ack.trusted,true);assert.equal(finish(p),null);
});
for(const [name,change] of Object.entries({untrusted:{trusted:false},wrongTarget:{target:other},wrongNode:{node:5},wrongStep:{step:12},wrongToken:{token:'old-token'},oldRenderer:{documentId:'renderer-0'},staleTime:{stamp:99},detached:{connected:false},mouse:{pointerType:'mouse'}}))
 test(name+' cannot pass even when DOM already reports the expected section',()=>{const p=create(expected);pair(p,change);assert.equal(finish(p),null);});
test('click without native pointer pair fails',()=>{const p=create(expected);p.observe(event('click'));assert.equal(finish(p),null);});
test('different UP pointer identity fails',()=>{const p=create(expected);p.observe(event('pointerdown'));p.observe(event('pointerup',{pointerId:8}));p.observe(event('click'));assert.equal(finish(p),null);});
test('different click pointer identity fails',()=>{const p=create(expected);p.observe(event('pointerdown'));p.observe(event('pointerup'));p.observe(event('click',{pointerId:8}));assert.equal(finish(p),null);});
for(const type of ['contextmenu','pointercancel']) test(type+' invalidates the gesture',()=>{const p=create(expected);p.observe(event('pointerdown'));p.observe(event(type));p.observe(event('pointerup'));p.observe(event('click'));assert.equal(finish(p),null);});
test('mismatched visible label or section identity fails',()=>{const p=create(expected);pair(p);assert.equal(p.finish('kalender',true,'Notes','register:kalender',null),null);assert.equal(p.finish('kalender',true,'Calendar','register:notizen',null),null);});
test('already-active section cannot count as a user switch',()=>{const p=create({...expected,before:'kalender'});pair(p);assert.equal(finish(p),null);});
test('Planner pending jobs cannot pass',()=>{const p=create({...expected,section:'planer',label:'Planner'});pair(p);assert.equal(p.finish('planer',true,'Planner','register:planer',1),null);assert.ok(p.finish('planer',true,'Planner','register:planer',0));});
test('captured native Notes click inside one-millisecond uncertainty is accepted',()=>{
 const p=create({...expected,armedAt:11680,label:'Notes',section:'notizen',before:'adressen'});
 p.observe(event('pointerdown',{stamp:11679.8,at:11694}));
 p.observe(event('pointerup',{stamp:11719.8,at:12156}));
 assert.equal(p.observe(event('click',{stamp:11719.8,at:12232.3})),true);
 const ack=p.finish('notizen',true,'Notes','register:notizen',null);
 assert.equal(ack.trusted,true);assert.equal(ack.armedAt,11680);assert.equal(ack.clockPrecisionMs,1);
});
test('old timestamp beyond precision cannot pass merely because receipt is after arm',()=>{
 const p=create(expected);pair(p,{stamp:98.999,at:500});assert.equal(finish(p),null);
});
test('a full millisecond before arm is outside the half-open uncertainty interval',()=>{
 const p=create(expected);pair(p,{stamp:99,at:500});assert.equal(finish(p),null);
});
for(const [name,change] of Object.entries({oldRenderer:{documentId:'old'},oldStep:{step:1},oldNode:{node:9},oldToken:{token:'old'}}))
 test('precision overlap does not excuse '+name,()=>{
  const p=create(expected);pair(p,{stamp:99.8,at:101,...change});assert.equal(finish(p),null);
 });
for(const field of ['stamp','at']) for(const value of [-1,NaN,Infinity,-Infinity,Number.MAX_VALUE,'100',null])
 test('reject malformed '+field+' '+String(value),()=>{const p=create(expected);pair(p,{[field]:value});assert.equal(finish(p),null);});
test('receipt before arm rejects even when the coarse timestamp overlaps',()=>{
 const p=create(expected);pair(p,{stamp:99.8,at:99.9});assert.equal(finish(p),null);
});
test('nonsensical future event timestamp rejects',()=>{const p=create(expected);pair(p,{stamp:999999,at:150});assert.equal(finish(p),null);});
test('UP before DOWN cannot be salvaged by later valid-looking events',()=>{
 const p=create(expected);p.observe(event('pointerup'));pair(p);assert.equal(finish(p),null);
});
test('duplicate DOWN cannot replace the original sequence',()=>{
 const p=create(expected);p.observe(event('pointerdown'));pair(p);assert.equal(finish(p),null);
});
test('backwards UP timestamp rejects',()=>{
 const p=create(expected);p.observe(event('pointerdown',{stamp:140}));p.observe(event('pointerup',{stamp:139}));p.observe(event('click'));assert.equal(finish(p),null);
});
test('backwards receipt order rejects',()=>{
 const p=create(expected);p.observe(event('pointerdown',{at:150}));p.observe(event('pointerup',{at:149}));p.observe(event('click'));assert.equal(finish(p),null);
});
for(const value of [-1,NaN,Infinity]) test('invalid arming time '+value,()=>{
 const p=create({...expected,armedAt:value});pair(p);assert.equal(finish(p),null);
});
console.log(`${cases} functional touch-proof cases passed`);
