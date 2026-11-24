'use strict';
const $=id=>document.getElementById(id), token=document.querySelector('meta[name=csrf]').content;
let state=null,current=null,selectedJob=null,preview=null,selectedComponent=null,view=[-.5,.5],zoom=1,drag=null,picks=[],formDirty=false,formRevision=null;
let jsonDirty=false,editorTarget=null;
const draft=new KazControls.Draft(),intents=new KazControls.Intents(localStorage);let refreshSerial=0;
function form(){return {title:$('title').value,placement:$('placement').value,payload_area_m2:Number($('area').value),requirements:{...current.requirements,minimum_credited_products:Number($('required-products').value),minimum_priority_score:Number($('required-score').value)}};}
function applied(){if(jsonDirty)throw Error('Есть неприменённый JSON design draft; примените или перечитайте сохранённую revision.');draft.requireApplied();if(draft.revision!==current.revision)throw Error('Изменилась applied revision; загрузите актуальный проект.');}
const num=(v,n=6)=>typeof v==='number'?v.toLocaleString('ru-RU',{maximumSignificantDigits:n}):String(v);
async function api(path,body){const r=await fetch(path,body===undefined?{cache:'no-store',headers:{'X-CSRF-Token':token}}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d;}
function error(e){$('error').hidden=false;$('error').textContent=String(e.message||e);}
function clearError(){$('error').hidden=true;}
function activeJob(){return current?.jobs.find(j=>['QUEUED','ADMITTED','RUNNING','STOP_REQUESTED','UNKNOWN'].includes(j.status));}
function metric(container,value,label){const box=document.createElement('div');box.className='metric';const strong=document.createElement('strong');strong.textContent=value;const span=document.createElement('span');span.textContent=label;box.append(strong,span);container.append(box);}
function render(){
  const p=current;const disabled=!p;
  for(const n of ['apply','preview','save','run'])$(n).disabled=disabled;
  if(!p){preview=null;draw();return;}
  for(const name of ['placement','area','title','required-products','required-score'])$(name).disabled=!!p.general_design;
  if(draft.project!==p.project_id)draft.select(p);
  draft.poll(p);formDirty=draft.dirty;
  if(!formDirty){$('title').value=p.title;$('placement').value=p.placement;$('area').value=String(p.payload_area_m2);
    $('required-products').value=p.requirements.minimum_credited_products;$('required-score').value=p.requirements.minimum_priority_score;formRevision=p.revision;formDirty=false;}
  preview=p.preview;const running=activeJob(),longRunning=!!window.kazLifecycle?.active;$('run').disabled=!!p.general_design||!preview||!!running||longRunning||draft.dirty||jsonDirty||intents.busy;
  $('apply').disabled=!!p.general_design;$('preview').disabled=draft.dirty||jsonDirty;$('save').disabled=draft.dirty||jsonDirty;
  $('design-read').disabled=!p.general_design;$('design-bind').disabled=!p.general_design||!preview||jsonDirty||draft.dirty||!!running||longRunning;
  $('draft-status').textContent=draft.dirty||jsonDirty?'Неприменённый draft. Run / Preview / Save / Resume заблокированы.':`Applied revision ${p.revision.slice(0,12)} · ${p.general_design?'V2: полный пользовательский design specification; миссия из immutable common':p.placement+' · '+p.payload_area_m2+' m²'}`;
  selectedJob=p.jobs.find(j=>j.job_id===selectedJob?.job_id)||p.jobs.at(-1)||null;
  $('stop').disabled=!running||running.status==='UNKNOWN';$('resume').disabled=draft.dirty||intents.busy||longRunning||!selectedJob?.checkpoint||!!running||!selectedJob.is_current_revision||selectedJob.ownership_valid!==true;
  const choices=selectedJob?.snapshots||[],oldChoice=$('snapshot').value;$('snapshot').replaceChildren();
  for(const c of choices){const o=document.createElement('option');o.value=c.sha256;o.textContent=`${c.clock} s · ${c.pending.join(', ')} · ${c.partial_bits.join(', ')} bits`;$('snapshot').append(o);}
  if(choices.some(c=>c.sha256===oldChoice))$('snapshot').value=oldChoice;else if(choices.length)$('snapshot').value=choices.at(-1).sha256;
  $('direct-resume').disabled=draft.dirty||intents.busy||longRunning||!choices.length||!!running||!selectedJob?.is_current_revision||selectedJob?.ownership_valid!==true;
  $('export').disabled=selectedJob?.status!=='COMPLETED';
  $('status').textContent=running?({QUEUED:'В очереди',ADMITTED:'Допущен',RUNNING:'Расчёт выполняется',STOP_REQUESTED:'Останавливаем только owned job',UNKNOWN:'Ownership неизвестен; новый запуск заблокирован'}[running.status]):selectedJob?selectedJob.status:'Preview готов? Затем запустите миссию.';
  const progress=(running||selectedJob)?.progress;
  $('progress').textContent=progress?`Последняя валидная граница: ${num(progress.clock)} с; решений ${progress.completed_decisions}; ожидается ${progress.pending.join(', ')||'нет'}; частично передано ${progress.partial_bits.map(x=>num(x)).join(', ')||0} bits. Полученное наблюдение: ${num(progress.received_at)} с.`:'';
  $('hardware').replaceChildren();
  if(preview){const m=preview.mass_properties;metric($('hardware'),num(m.total_mass_kg),'Полная масса, kg');metric($('hardware'),num(preview.added_harness_mass_kg*1000),'Добавленный harness, g');metric($('hardware'),m.center_body_m.map(x=>num(x,4)).join(' / '),'COM x / y / z, m');$('technical').textContent=JSON.stringify(preview,null,2);}
  else{$('technical').textContent='Для новой revision требуется реальный constructor preview.';}
  $('result').replaceChildren();const job=selectedJob;
  if(job?.result){const m=job.result.metrics;metric($('result'),num(m.credited_products),'Фактические кредиты этого запуска');metric($('result'),num(m.priority_weighted_delivery_score),'Priority score');metric($('result'),`${num(m.minimum_energy_wh)} / ${num(m.final_energy_wh)}`,'E min / final, Wh');metric($('result'),num(m.actual_slew_seconds),'Выполненный POINT, s');metric($('result'),num(m.wire_loss_wh),'Wire losses, Wh');metric($('result'),num(m.actual_refusals),'Actual refusals');metric($('result'),num(m.rejected_requests),'Некредитованные requests');metric($('result'),Object.entries(m.maximum_temperature_k).map(([n,t])=>n+': '+num(t)).join(' / '),'Максимальные returned T, K');const text=document.createElement('p');text.className='muted';text.textContent=(job.is_current_revision?'Текущий actual run. ':'История иной revision; не текущий результат. ')+`Acquired ${m.acquired}, receipts ${m.receipts}, unmet ${num(m.unmet_load_wh)} Wh. Forecast/estimate не являются actual credit.`;$('result').append(text);}
  else $('result').textContent='Завершённого actual результата выбранного job пока нет. Последняя граница не заменяет endpoint.';
  const requirements=job?.result?.requirements_evaluation;
  $('requirements-result').textContent=requirements?`Requirements: ${requirements.satisfied?'satisfied':'NOT satisfied'}; ${requirements.reasons.join(', ')||'нет отказов'}. ${job.is_current_revision&&!draft.dirty?'Applied result':'История applied revision; draft ещё не запускался'}. ${job.intent?.mode||'MAIN'}`:'';
  $('summary').textContent=job?.result?.report?.totals?JSON.stringify({cumulative_scope:'Накопительный restored state; includes retained prefix',cumulative:job.result.report.totals,window:job.result.window_report?.totals||null,window_scope:job.result.window_report?.scope||null},null,2):'Потоковая сводка появится после фактического выполнения; summary не является state seed.';
  $('details-link').hidden=!job?.result;$('details-link').href=job?.result?'/api/details/'+job.job_id:'#';
  $('history').replaceChildren();for(const j of p.jobs){const tr=document.createElement('tr'),m=j.result?.metrics;for(const value of [j.job_id.slice(0,8)+(j.is_current_revision?' · current':' · history'),j.status,m?.credited_products??'—',m?.priority_weighted_delivery_score??'—',m?num(m.minimum_energy_wh)+' / '+num(m.final_energy_wh):'—',m?.actual_slew_seconds??'—',m?num(m.wire_loss_wh):'—']){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}tr.onclick=()=>{selectedJob=j;render();};$('history').append(tr);}
  for(const h of state.historical||[]){const tr=document.createElement('tr');for(const value of ['B49 · HISTORICAL',h.scope,h.metrics.credited_products,h.metrics.priority_weighted_delivery_score,num(h.metrics.minimum_energy_wh)+' / '+num(h.metrics.final_energy_wh),h.metrics.actual_slew_seconds,num(h.metrics.wire_loss_wh)]){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}$('history').append(tr);}
  draw();
}
async function refresh(){const pid=current?.project_id,serial=++refreshSerial;const incoming=await api('/api/state');if(serial!==refreshSerial||current?.project_id!==pid)return;state=incoming;current=state.projects.find(p=>p.project_id===pid)||state.projects.at(-1)||null;const select=$('projects');select.replaceChildren();for(const p of state.projects){const o=document.createElement('option');o.value=p.project_id;o.textContent=p.title;select.append(o);}if(current)select.value=current.project_id;render();}
async function action(f){clearError();try{return await f();}catch(e){error(e);throw e;}}
const local=(name,f)=>{$(name).onclick=()=>action(f).catch(()=>{});};
local('create',async()=>{const r=await api('/api/project',{title:$('title').value||'Мой KazEOSat',placement:$('placement').value,payload_area_m2:Number($('area').value)});current={project_id:r.project_id};await refresh();});
function showDesign(document,target){$('design-json').value=JSON.stringify(document,null,2);editorTarget=target;jsonDirty=false;$('design-editor-status').textContent=target?'Сохранённый immutable JSON; изменения требуют нового Apply.':'Новый V2 input template; отредактируйте и создайте проект.';}
local('design-new',async()=>{const r=await api('/api/design/template',{title:'Мой пользовательский спутник'});showDesign(r.document,null);jsonDirty=true;$('design-editor-status').textContent='Новый V2 template: '+r.mission_origin+'. Указанные ASSUMED физические модели не являются flight calibration.';});
local('design-read',async()=>{const r=await api('/api/save',{project_id:current.project_id,revision:current.revision});showDesign(r.document,{project_id:current.project_id,revision:current.revision});render();});
local('design-apply',async()=>{const text=$('design-json').value;if(!text.trim())throw Error('Сначала создайте template или импортируйте JSON.');
  const target=editorTarget,body={document:text,rebuild_outer_digest:true},r=target?await api('/api/design/apply',{...target,...body}):await api('/api/design/create',body);
  showDesign(r.input,{project_id:r.project_id,revision:r.revision});current={project_id:r.project_id};await refresh();});
local('design-bind',async()=>{applied();const r=await api('/api/design/lifecycle',{project_id:current.project_id,revision:current.revision});await window.kazLifecycle.refresh();window.kazLifecycle.selectRoot(r.root_identity);$('design-editor-status').textContent='Actual root '+r.root_identity+' зафиксирован. Начать / Stop / direct resume — в разделе хронологической миссии; common policy не пересоздана.';});
$('design-json').addEventListener('input',()=>{jsonDirty=true;$('design-editor-status').textContent='Неприменённый JSON draft. Проверяется строгий schema/input contract; пересчитывается только внешний digest.';render();});
local('apply',async()=>{const t=draft.token(),body={project_id:current.project_id,revision:draft.revision,...form()};const r=await api('/api/edit',body);draft.appliedResponse(t,{...body,revision:r.revision});await refresh();});
local('preview',async()=>{applied();await api('/api/preview',{project_id:current.project_id,revision:current.revision});await refresh();});
local('save',async()=>{applied();const r=await api('/api/save',{project_id:current.project_id,revision:current.revision});const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(r.document)],{type:'application/json'}));a.download='kazeosat-project.json';a.click();URL.revokeObjectURL(a.href);});
$('load').onclick=()=>$('load-file').click();$('load-file').onchange=()=>action(async()=>{const file=$('load-file').files[0];if(!file)return;if(file.size>16*1024*1024)throw new Error('Размер project input превышает 16 MiB');const r=await api('/api/load',{document:await file.text()});current={project_id:r.project_id};await refresh();if(current?.general_design)showDesign(r.input,{project_id:r.project_id,revision:r.revision});}).catch(()=>{});
async function submitIntent(method){applied();const retained=intents.current(),key=retained?.idempotency_key||crypto.randomUUID().replaceAll('-','');
  const cp=method==='B51_DIRECT'?selectedJob?.snapshots?.find(s=>s.sha256===$('snapshot').value):selectedJob?.checkpoint;
  const body={format:'M8_DURABLE_JOB_INTENT_V1',action_id:key,idempotency_key:key,project_id:current.project_id,revision:current.revision,parent_job_id:method==='INITIAL'?null:selectedJob.job_id,snapshot_sha256:method==='INITIAL'?null:cp.sha256,method,mode:method==='B51_DIRECT'?$('detail-mode').value:'MAIN',window_end_seconds:method==='B51_DIRECT'?Number($('window-end').value):null};
  $('run').disabled=true;$('resume').disabled=true;$('direct-resume').disabled=true;
  selectedJob=await intents.send(body,b=>api('/api/submit',b),async b=>{const r=await api('/api/intent/'+b.idempotency_key);if(r.intent&&KazControls.canonical(r.intent)!==KazControls.canonical(b))throw Error('Server intent mismatch');return r.job;});await refresh();}
local('run',()=>submitIntent('INITIAL'));
local('stop',async()=>{await api('/api/stop',{job_id:activeJob().job_id});await refresh();});
local('resume',()=>submitIntent('B48_CAUSAL'));
local('direct-resume',()=>submitIntent('B51_DIRECT'));
local('new-action',async()=>{const b=intents.current();if(!b)return;const r=await api('/api/intent/'+b.idempotency_key);if(r.intent&&KazControls.canonical(r.intent)!==KazControls.canonical(b))throw Error('Server intent mismatch');intents.newAction(r.intent===null||r.job&&['COMPLETED','REFUSED','INCOMPLETE','CANCELLED','PROCESS_FAILED'].includes(r.job.status)&&r.job.ownership_valid===true);await refresh();});
local('export',async()=>{const r=await api('/api/export',{job_id:selectedJob.job_id});const a=document.createElement('a');a.href=r.url;a.download='kazeosat-result.zip';a.textContent='Скачать self-contained результат';$('export-link').replaceChildren(a);});
local('shutdown',async()=>{await api('/api/shutdown',{});clearInterval(pollTimer);$('status').textContent='Приложение закрыто. Другие окна и процессы не изменены.';});
for(const name of ['title','placement','area','required-products','required-score'])$(name).addEventListener('input',()=>{if(!current)return;draft.edit(form());formDirty=draft.dirty;render();});
$('projects').onchange=()=>{current=state.projects.find(p=>p.project_id===$('projects').value);selectedJob=null;render();};
const canvas=$('assembly'),ctx=canvas.getContext('2d');
function projectPoint(v){const [a,b]=view,ca=Math.cos(a),sa=Math.sin(a),cb=Math.cos(b),sb=Math.sin(b);const x=ca*v[0]+sa*v[2],z=-sa*v[0]+ca*v[2],y=cb*v[1]-sb*z,depth=sb*v[1]+cb*z;return [canvas.width/2+x*260*zoom,canvas.height/2-y*260*zoom,depth];}
function line(points,color,width=1.5){ctx.beginPath();points.forEach((v,i)=>{const p=projectPoint(v);i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);picks=[];if(!preview){ctx.fillStyle='#94aabd';ctx.font='18px Segoe UI';ctx.fillText('Пересчитайте сборку — здесь появятся реальные component poses',40,270);return;}
  for(const [v,c] of [[[.8,0,0],'#eb7379'],[[0,.8,0],'#6bc88f'],[[0,0,.8],'#70a6e3']])line([[0,0,0],v],c,2);
  for(const route of preview.routes)line(route.points_body_m,'#5edbd0');
  const colors=['#5a82a0','#d1af56','#789fd0','#b893bc','#73ad99'];
  preview.components.forEach((c,index)=>{const p=projectPoint(c.center_body_m);picks.push({p,c});ctx.globalAlpha=.85;const vertices=c.vertices_body_m;for(let i=0;i<8;i++)for(let j=i+1;j<8;j++)if([1,2,4].includes(i^j))line([vertices[i],vertices[j]],c.id===selectedComponent?'#fff':colors[index%colors.length],c.id===selectedComponent?3:1.8);ctx.fillStyle='#dce9f3';ctx.font='12px Segoe UI';ctx.fillText(c.id,p[0]+7,p[1]-7);ctx.globalAlpha=1;});
  const com=preview.mass_properties.center_body_m,p=projectPoint(com);ctx.fillStyle='white';ctx.beginPath();ctx.arc(p[0],p[1],5,0,Math.PI*2);ctx.fill();
  for(const mount of preview.mount_vectors)line([mount.origin_body_m,mount.origin_body_m.map((x,i)=>x+mount.direction_body[i]*.35)],mount.role==='camera'?'#e6a5cf':'#e7cd72',3);
}
canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};canvas.onpointermove=e=>{if(!drag)return;view[0]+=(e.clientX-drag[0])*.008;view[1]+=(e.clientY-drag[1])*.008;drag=[e.clientX,e.clientY];draw();};canvas.onpointerup=e=>{drag=null;const r=canvas.getBoundingClientRect(),p=[(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];const nearest=picks.map(x=>({...x,d:Math.hypot(x.p[0]-p[0],x.p[1]-p[1])})).sort((a,b)=>a.d-b.d)[0];if(nearest?.d<80){selectedComponent=nearest.c.id;$('component').textContent=JSON.stringify(nearest.c);draw();}};canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.3,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));draw();};
window.kazWorkbench={api,refresh,getState:()=>state,getProject:()=>current,requireApplied:applied,hasDirtyDraft:()=>draft.dirty||jsonDirty,selectProject:pid=>{current=state.projects.find(p=>p.project_id===pid);render();},ready:refresh()};
const pollTimer=setInterval(()=>refresh().catch(error),1500);
