'use strict';
const assert=require('node:assert/strict'),{Draft,Intents}=require('../ops_sim/v5/workbench_assets/control.js');
const p={project_id:'p',revision:'r',title:'one',placement:'compact',payload_area_m2:1e-8,requirements:{minimum_credited_products:2,minimum_priority_score:.5}};
for(const [field,value] of [['title','two'],['placement','outboard'],['payload_area_m2',1e-7],['requirements',{minimum_credited_products:3,minimum_priority_score:.5}]]){
  const d=new Draft();d.select(p);const t=d.token();d.edit({...p,[field]:value});assert(d.dirty);assert.throws(()=>d.requireApplied());
  d.poll(p);assert(d.dirty);assert.equal(d.appliedResponse(t,{...p,revision:'stale'}),false);
  assert.equal(d.value[field],field==='requirements'?JSON.stringify(value,Object.keys(value).sort()):value);
}
const storage=new Map(),s={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
(async()=>{
  let jobs=0,settled=null;const a={idempotency_key:'same',revision:'r',parent:'cp'};
  let i=new Intents(s);await assert.rejects(i.send(a,async()=>{jobs++;settled={job_id:'one',status:'COMPLETED'};throw Error('response lost');},async()=>null));
  i=new Intents(s);const result=await i.send(a,async()=>{jobs++;},async()=>settled);assert.equal(result.job_id,'one');assert.equal(jobs,1);
  assert.throws(()=>i.begin({...a,parent:'other'}));assert.throws(()=>i.newAction(false));
  let release;settled=null;const first=i.send(a,()=>new Promise(r=>{release=r}),async()=>null);await new Promise(r=>setImmediate(r));
  await assert.rejects(i.send(a,async()=>{},async()=>null),/отправляется/);release({job_id:'one'});await first;
  i.newAction(true);assert.equal(i.current(),null);
  console.log('PASS: draft/stale/poll/failed-apply protection and durable response-loss/reload/body-delay/duplicate-click intent checks; no DOM evidence');
})().catch(e=>{console.error(e);process.exitCode=1;});
