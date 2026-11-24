'use strict';
(function(){
  const app=window.kazWorkbench,$=id=>document.getElementById(id),canonical=KazControls.canonical;
  const ageingLabel=document.createElement('label');
  ageingLabel.textContent='Environment ageing '; const ageingSelect=document.createElement('select');
  ageingSelect.id='lc-environment-ageing';
  for(const [value,text] of [['LEGACY','Legacy solar law / fixed thermal'],['B61_ASSUMED_V1','Assumed exposure law (uncalibrated)'],['B61_ACCELERATED_ASSUMED_V1','Accelerated synthetic sensitivity']]){
    const o=document.createElement('option');o.value=value;o.textContent=text;ageingSelect.appendChild(o);
  }
  ageingLabel.appendChild(ageingSelect);$('lc-battery-policy').parentElement.after(ageingLabel);
  const ageingStatus=document.createElement('p');ageingStatus.id='lc-environment-status';ageingLabel.after(ageingStatus);
  const intents=new KazControls.Intents(localStorage,'kaz-b52-durable-intent-v1');
  let state={enabled:false,roots:[],active_job_id:null},rid=null,jid=null,configured=null,serial=0,page=[],before=null;
  const terminal=['COMPLETED','INCOMPLETE','CANCELLED','PROCESS_FAILED','REFUSED'];
  const root=()=>state.roots.find(r=>r.root_identity===rid)||null;
  const job=()=>root()?.jobs.find(j=>j.job_id===jid)||null;
  const api=(path,body)=>app.api('/api/lifecycle/'+path,body);
  function terminalView(r,j){
    const finite=r?.runner_policy?.method==='B59_TEN_JOB_EIGHT_PRIMARY_BATTERY_V1';
    const stop=j?.typed_stop||j?.result?.typed_terminal?.terminal||null;
    const unsettled=finite&&(['UNKNOWN','PROCESS_FAILED'].includes(j?.status)||['UNKNOWN','PROCESS_FAILURE'].includes(stop?.kind));
    const blocked=finite&&(unsettled||!!stop&&!['TARGET','RESOURCE_TIME','RESOURCE_OUTPUT','USER'].includes(stop.kind));
    return {stop,unsettled,blocked,coverageStatus:finite?(unsettled?'UNSETTLED_NO_ENDPOINT_LAST_OBSERVATION_ONLY':stop?.kind==='TARGET'?'FULL_BOUND_TARGET':stop?'BOUND_TERMINAL_PREFIX':'ACTUAL_PUBLISHED_PREFIX'):null};
  }
  function form(){const p=app.getProject(),mode=$('lc-policy').value;
    if(p?.general_design)return {project_id:p.project_id,revision:p.revision};
    const policy={quiet_step_seconds:60,detailed_step_seconds:2,lighting_step_seconds:60,contact_integration_level:2,latency_seconds:Number($('lc-latency').value)};
    if(mode==='adaptive')policy.quiet_solver={maximum_macro_seconds:Number($('lc-quiet-max').value),absolute_energy_wh:Number($('lc-energy-error').value),absolute_temperature_k:Number($('lc-temperature-error').value),absolute_retention:Number($('lc-retention-error').value),relative_tolerance:Number($('lc-relative-error').value)};
    else if(mode==='finer')Object.assign(policy,{quiet_step_seconds:30,detailed_step_seconds:1,contact_integration_level:3});
    else if(mode==='detailed')policy.quiet_step_seconds=2;
    return {project_id:p?.project_id,revision:p?.revision,duration_seconds:Number($('lc-duration').value),policy,
      scenario:{cadence_seconds:Number($('lc-cadence').value)},sun_mode:$('lc-sun').value,
      study_preset:$('lc-study').value,ageing_multiplier:Number($('lc-ageing').value),
      runner_store_policy:$('lc-runner-policy').value,
      service_policy:$('lc-service-policy').value,
      environment_ageing_policy:$('lc-environment-ageing').value,battery_port_policy:$('lc-battery-policy').value,energy_attitude_policy:$('lc-solar-policy').value,publication_profile:$('lc-publication-profile').value,
      output_policy:$('lc-study').value==='LEGACY'&&mode==='nominal'?null:{publication_minimum_wall_seconds:Number($('lc-status-cadence').value),working_checkpoint_every_events:Number($('lc-working-period').value)}};}
  function dirty(){return configured===null||canonical(form())!==configured;}
  function requireApplied(){app.requireApplied();const r=root(),p=app.getProject();if(dirty())throw Error('Сначала зафиксируйте long root из текущих полей.');
    if(!r||r.project?.project_id!==p.project_id||r.project?.revision!==p.revision)throw Error('Long root относится к другой applied revision. Выберите её или создайте новый root.');}
  function showError(e){$('lc-status').textContent=String(e.message||e);}
  function chooseRoot(id){rid=id;const r=root();jid=r?.jobs.at(-1)?.job_id||null;if(r){$('lc-duration').value=String(r.end_seconds-r.start_seconds);$('lc-cadence').value=String(r.scenario.cadence_seconds);$('lc-sun').value=r.sun_mode;
      $('lc-policy').value=r.policy.quiet_solver?'adaptive':r.policy.contact_integration_level===3?'finer':r.policy.quiet_step_seconds===2?'detailed':'nominal';$('lc-study').value=r.study?.preset||'LEGACY';$('lc-ageing').value=String(r.study?.ageing_multiplier||1);$('lc-latency').value=String(r.policy.latency_seconds);
      const q=r.policy.quiet_solver||{};$('lc-quiet-max').value=String(q.maximum_macro_seconds||60);$('lc-energy-error').value=String(q.absolute_energy_wh??.00002);$('lc-temperature-error').value=String(q.absolute_temperature_k??.002);$('lc-retention-error').value=String(q.absolute_retention??1e-9);$('lc-relative-error').value=String(q.relative_tolerance??1e-7);$('lc-status-cadence').value=String(r.output_policy?.publication_minimum_wall_seconds||1);$('lc-working-period').value=String(r.output_policy?.working_checkpoint_every_events||1024);
      $('lc-runner-policy').value=r.runner_policy?.method||'LEGACY';
      $('lc-battery-policy').value=r.battery_port_policy?.method||'LEGACY';
      $('lc-environment-ageing').value=r.environment_ageing_policy?(r.environment_ageing_policy.assumption==='SYNTHETIC_ACCELERATED_ASSUMED'?'B61_ACCELERATED_ASSUMED_V1':'B61_ASSUMED_V1'):'LEGACY';
      $('lc-service-policy').value=r.service_policy?.method||'LEGACY';$('lc-solar-policy').value=r.energy_attitude_policy?.method||'LEGACY';$('lc-publication-profile').value=r.publication_profile?.method||'LEGACY_RAW';
      page=[];before=null;$('lc-until').value=String(r.end_seconds);configured=canonical(form());}render();}
  function options(select,values,key,label,selected){select.replaceChildren();for(const v of values){const o=document.createElement('option');o.value=key(v);o.textContent=label(v);select.append(o);}if(values.some(v=>key(v)===selected))select.value=selected;}
  function render(){const r=root(),j=job(),terminalState=terminalView(r,j),running=!!state.active_job_id,foreign=!!app.getProject()?.jobs?.some(x=>['QUEUED','ADMITTED','RUNNING','STOP_REQUESTED','UNKNOWN'].includes(x.status));
    const general=!!app.getProject()?.general_design;
    for(const node of document.querySelectorAll('#lifecycle-panel input, #lifecycle-panel select')){
      if(!['lc-roots','lc-jobs','lc-checkpoints','lc-until','lc-logging','lc-execution'].includes(node.id))node.disabled=general;
    }
    options($('lc-roots'),state.roots,x=>x.root_identity,x=>`${x.root_identity.slice(0,10)} · ${x.end_seconds-x.start_seconds} physical s`,rid);
    if(r){options($('lc-jobs'),r.jobs,x=>x.job_id,x=>`${x.job_id.slice(0,8)} · ${x.intent.mode} · ${x.status}`,jid);
      const selected=$('lc-checkpoints').value,checkpoints=Array.from(new Map([...(j?.checkpoints||[]),...page.filter(x=>x.raw_available).map(x=>x.checkpoint)].map(c=>[c.sha256,c])).values());options($('lc-checkpoints'),checkpoints,x=>x.sha256,x=>`${x.clock} s · ${x.kind}`,selected);
      if(!selected&&j?.checkpoints?.length)$('lc-checkpoints').value=j.checkpoints.at(-1).sha256;}
    const p=app.getProject(),applied=p&&!app.hasDirtyDraft(),own=r&&r.project?.project_id===p?.project_id&&r.project?.revision===p?.revision;
    const reservedBytes=r?.reserved_job_output_bytes??r?.jobs.reduce((sum,j)=>sum+j.intent.maximum_output_bytes,0)??0;
    const slots=r?.remaining_job_slots??(4-(r?.jobs.length||0)),outputLimit=r?.runner_policy?.maximum_reserved_job_output_bytes??2147483648;
    const canDispatch=slots>0&&reservedBytes+(r?.energy_attitude_policy?128:r?.output_policy?256:128)*1024*1024<=outputLimit;
    $('lc-create').disabled=!state.enabled||!applied||running||foreign;
    $('lc-run').disabled=!state.enabled||!applied||!own||dirty()||running||foreign||intents.busy||!canDispatch;
    $('lc-stop').disabled=!running||!state.roots.some(x=>x.jobs.some(y=>y.job_id===state.active_job_id&&y.status!=='UNKNOWN'));
    const canResume=state.enabled&&applied&&own&&!dirty()&&!running&&!foreign&&!intents.busy&&canDispatch&&j?.ownership_valid===true&&j?.checkpoints?.length;
    $('lc-resume').disabled=!canResume||terminalState.blocked;$('lc-diagnostic').disabled=!canResume||terminalState.blocked;
    $('lc-export').disabled=!j||!terminal.includes(j.status)||j.ownership_valid!==true;
    $('lc-older').disabled=!j||running||before===0;
    const battery=j?.progress?.battery_port,pack=battery?.actual?.pack_measurements,bs=battery?.sampled_report;
    $('lc-battery-status').textContent=battery?`ASSUMED pack V sample ${pack?.last_voltage_v??'UNAVAILABLE'} V; selected min/max ${bs?.minimum_voltage_v??'UNAVAILABLE'}/${bs?.maximum_voltage_v??'UNAVAILABLE'} V; R ${pack?.last_resistance_ohm??'UNAVAILABLE'} Ohm; I ${pack?.last_current_a??'UNAVAILABLE'} A; limits charge/discharge ${bs?.limits?.maximum_charge_current_a}/${bs?.limits?.maximum_discharge_current_a} A; Ohmic ${bs?.ohmic_heat_wh} Wh; converter ${bs?.converter_loss_wh} Wh. Regulated bus is separate. Received at ${battery.received_at_seconds} s; sampled extrema, not continuous bounds.`:(r?.battery_port_policy?'B58 selected; no actual sample yet.':'Pack voltage: UNAVAILABLE (legacy Wh-only).');
    const solar=j?.progress?.solar_attitude;
    const ageing=j?.progress?.environment_ageing?.actual;
    $('lc-environment-status').textContent=ageing?`Actual calendar ${ageing.calendar_seconds} s; effective PV illumination ${ageing.pv_exposure_seconds} s; retention ${ageing.pv_retention}; emissivity ${JSON.stringify(ageing.emissivity)}; conductance ${JSON.stringify(ageing.conductance_w_per_k)} W/K. ${ageing.assumption}. Not radiation dose or calibrated lifetime.`:'No new environment-ageing sample.';
    $('lc-solar-status').textContent=solar?`ONBOARD actual ${solar.actual.phase} ? ${solar.actual.reason} ? paid Sun-point ${serviceEnergy(solar.actual.paid_point_seconds)} s / actuator requested ${serviceEnergy(solar.actual.actuator_requested_wh)} Wh ? charge-purpose hold ${serviceEnergy(solar.actual.charge_hold_seconds)} s ? last selected panel incidence ${solar.actual.last_incidence_deg??'UNAVAILABLE'} deg / ${solar.actual.last_illumination??'UNAVAILABLE'} ? received ${solar.received?.phase??'UNAVAILABLE'} ? last paid estimate ${solar.estimated?.phase??'UNAVAILABLE'}`:(r?.energy_attitude_policy?'B56 selected; no actual solar progress yet.':'Legacy stationary attitude; no automatic Sun turn.');
    const progress=j?.progress,last=j?.last_actual_refusal||progress?.last_action,service=progress?.power_service;
    $('lc-service-status').textContent=service?`ACTUAL ${service.mode} · ${service.last_reason} · essential ${service.essential_serviceable?'served':'UNAVAILABLE'} · low-rate TM ${service.low_rate_telemetry_serviceable?'available':'unavailable'} · high-rate TX ${service.tx_fully_served?'fully served':'not granted'} · selected essential deficit ${serviceEnergy(service.receiving_energy_wh?.essential_unserved_wh)} Wh`:'Operational policy: '+(r?.service_policy?.method||'LEGACY NORMAL-only')+'; current actual mode has not yet been published.';
    $('lc-refusal').textContent=last?.status==='refused'?`Actual ${last.kind}: ${last.reason||''}${last.refusal_detail?' · '+last.refusal_detail.stage+' / '+last.refusal_detail.code+' · '+last.refusal_detail.owner:''}`:'Последний опубликованный actual action не содержит отказа; история отказов хранится отдельно.';
    $('lc-status').textContent=!state.enabled?'Long workspace не подключён к этому экземпляру приложения.':
      dirty()?'Есть long draft: Apply проекта и «Зафиксировать long root» перед исполнением.':
      `${r?.method||'Нет immutable root'} · ${j?.status||'не запускался'}${progress?' · actual committed '+progress.clock+' s':''}`;
    $('lc-result').textContent=JSON.stringify({job_status:j?.status||null,job_reason:j?.reason||null,terminal_stop:terminalState.stop,root:r?{identity:r.root_identity,method:r.method,physical_start:r.start_seconds,physical_target:r.end_seconds,policy:r.policy,service_policy:r.service_policy||null,energy_attitude_policy:r.energy_attitude_policy||null,battery_port_policy:r.battery_port_policy||null,service_policy_identity:r.service_policy_identity||null,study:r.study,output_policy:r.output_policy,sun_mode:r.sun_mode,reduced_sun_policy:r.reduced_sun_policy||null,runner_store:{policy:r.runner_policy||'LEGACY',identity:r.runner_policy_identity||null,remaining_job_slots:slots,reserved_job_output_bytes:reservedBytes,reservation_limit_bytes:outputLimit}}:null,
      coverage:progress?{status:terminalState.coverageStatus||(progress.clock===r.end_seconds?'FULL_REQUESTED_HORIZON':'ACTUAL_PREFIX'),start:r.start_seconds,end:terminalState.unsettled?null:progress.clock,last_observed_clock:progress.clock,target:r.end_seconds}:null,actual_resources:progress?.publication?.resources||null,progress:j?.progress||null,actual_illumination_hours:lighting(j?.progress),checkpoint_page:page,actual:j?.result?{actual_start:j.result.start_clock,requested_end:j.result.target_seconds,actual_end:j.result.actual_end_seconds,typed_terminal:j.result.typed_terminal||null,
        wall_seconds:j.result.wall_seconds,worker_cpu_seconds:j.result.worker_cpu_seconds,cumulative:j.result.report,window:j.result.window_report,
        window_scope:'SEPARATE_SUFFIX_NOT_ADDED_TO_MAIN',published_bytes:j.result.output_published_bytes}:null},null,2);
  }
  async function refresh(){const ticket=++serial,incoming=await api('state');if(ticket!==serial)return;state=incoming;
    if(!state.roots.some(r=>r.root_identity===rid)){rid=state.roots.at(-1)?.root_identity||null;jid=root()?.jobs.at(-1)?.job_id||null;if(rid!==null){chooseRoot(rid);return;}}
    if(root()&&!root().jobs.some(j=>j.job_id===jid))jid=root().jobs.at(-1)?.job_id||null;
    render();}
  async function action(f){try{return await f();}catch(e){showError(e);}}
  function bind(name,f){$(name).onclick=()=>action(f);}
  bind('lc-create',async()=>{app.requireApplied();const result=app.getProject()?.general_design?await app.api('/api/design/lifecycle',form()):await api('create',form());await refresh();chooseRoot(result.root_identity);});
  async function submit(mode,parent){requireApplied();const r=root(),j=job(),cp=[...(j?.checkpoints||[]),...page.filter(x=>x.raw_available).map(x=>x.checkpoint)].find(c=>c.sha256===$('lc-checkpoints').value);
    if(parent&&!cp)throw Error('Выберите сохранённую immutable границу.');
    const retained=intents.current(),body={format:'B52_DURABLE_LIFECYCLE_INTENT_V1',idempotency_key:retained?.idempotency_key||crypto.randomUUID().replaceAll('-',''),
      root_identity:r.root_identity,mode,parent_job_id:parent?j.job_id:null,snapshot_sha256:parent?cp.sha256:null,
      window_end_seconds:mode==='MAIN'?null:Number($('lc-until').value),execution_seconds:Number($('lc-execution').value),maximum_output_bytes:(r.energy_attitude_policy?128:r.output_policy?256:128)*1024*1024};
    if(r.publication_profile)Object.assign(body,{format:'B57_PROFILE_BOUND_LIFECYCLE_INTENT_V3',execution_budget:null,execution_budget_identity:null,publication_profile:r.publication_profile,publication_profile_identity:r.publication_profile_identity});
    const result=await intents.send(body,b=>api('submit',b),async b=>{const saved=await api('intent/'+b.root_identity+'/'+b.idempotency_key);if(saved.intent&&canonical(saved.intent)!==canonical(b))throw Error('Сохранённое long намерение имеет другие параметры.');return saved.job;});
    jid=result.job_id;page=[];before=null;await refresh();}
  bind('lc-run',()=>submit('MAIN',false));bind('lc-resume',()=>submit('MAIN',true));bind('lc-diagnostic',()=>submit($('lc-logging').value,true));
  bind('lc-stop',async()=>{const active=state.roots.flatMap(r=>r.jobs.map(j=>({root:r.root_identity,job:j}))).find(x=>x.job.job_id===state.active_job_id);
    if(!active)throw Error('Нет собственного активного long handle.');await api('stop',{root_identity:active.root,job_id:active.job.job_id});await refresh();});
  function lighting(p){const x=p?.illumination;if(!x)return null;const q=v=>Number(BigInt(v[0]))/Number(BigInt(v[1]));return {scope:x.scope,qualification:x.qualification,units:'hours',covered:q(x.covered_seconds)/3600,illuminated:q(x.illuminated_seconds)/3600,occulted:q(x.occulted_seconds)/3600,unresolved:q(x.unresolved_seconds)/3600};}
  function serviceEnergy(value){if(!Array.isArray(value)||value.length!==2)return 'UNAVAILABLE';return String(Number(BigInt(value[0]))/Number(BigInt(value[1])));}
  bind('lc-older',async()=>{if(!root()||!job())return;const data=await api('checkpoints/'+rid+'/'+jid+(before===null?'':'?before='+before));page=data.entries;before=data.next_before===null?0:data.next_before;render();});
  bind('lc-new-intent',async()=>{const b=intents.current();if(!b)return;const saved=await api('intent/'+b.root_identity+'/'+b.idempotency_key);
    if(saved.intent&&canonical(saved.intent)!==canonical(b))throw Error('Server intent mismatch');
    intents.newAction(saved.intent===null||saved.job&&terminal.includes(saved.job.status)&&saved.job.ownership_valid===true);await refresh();});
  bind('lc-export',async()=>{const result=await api('export',{root_identity:rid,job_id:jid}),link=document.createElement('a');link.href=result.url;link.download='kazeosat-lifecycle.zip';link.textContent='Скачать pinned long result';$('lc-export-link').replaceChildren(link);});
  bind('lc-rows',async()=>{if(!root()||!job())return;const rows=await api('records/'+rid+'/'+jid+'/months?limit=32');$('lc-report-rows').textContent=JSON.stringify(rows,null,2);});
  $('lc-roots').onchange=()=>chooseRoot($('lc-roots').value);$('lc-jobs').onchange=()=>{jid=$('lc-jobs').value;page=[];before=null;render();};
  for(const name of ['lc-duration','lc-policy','lc-cadence','lc-sun','lc-study','lc-ageing','lc-latency','lc-quiet-max','lc-energy-error','lc-temperature-error','lc-retention-error','lc-relative-error','lc-status-cadence','lc-working-period','lc-runner-policy','lc-service-policy','lc-solar-policy','lc-publication-profile'])$(name).addEventListener('input',render);
  window.kazLifecycle={refresh,selectRoot:chooseRoot,get active(){return state.active_job_id;},getState:()=>state};
  // Additive finite-chain controls; legacy single-job intents keep their wire.
  const chainPanel=document.createElement('section');
  const title=document.createElement('p');title.textContent='Finite campaign: resource cuts may continue; User Stop pauses; physical/model boundaries stop. B59 uses its fixed 1550 s / eight-primary policy.';chainPanel.append(title);
  const chainStatus=document.createElement('pre');chainPanel.append(chainStatus);
  function selectedChain(){return (state.chains||[]).filter(c=>c.plan.root_identity===rid).at(-1);}
  function chainButton(label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>action(fn);chainPanel.append(b);return b;}
  chainButton('Create finite plan',async()=>{requireApplied();const named=root()?.runner_policy,finite=named?.method==='B59_TEN_JOB_EIGHT_PRIMARY_BATTERY_V1';const hard=finite?named.hard_seconds:Number($('lc-execution').value),reserve=finite?named.finalization_seconds:Math.min(300,Math.max(1,Math.floor(hard/4))),soft=finite?named.soft_seconds:hard-reserve;
    if(soft<1)throw Error('Execution allowance must exceed finalization reserve.');
    const p={method:'B55R2_WORKER_LOCAL_SOFT_BUDGET_V1',hard_execution_seconds:hard,soft_stop_seconds:soft,finalization_reserve_seconds:reserve};
    await api('chain/create',{root_identity:rid,chain_id:crypto.randomUUID().replaceAll('-',''),execution_budget:p,maximum_primary_segments:finite?named.maximum_primary_segments:root()?.energy_attitude_policy?5:6,maximum_output_bytes:finite?named.maximum_output_bytes:134217728,maximum_observed_seconds:finite?named.maximum_observed_primary_seconds:9600});await refresh();});
  chainButton('Run / Continue chain',async()=>{requireApplied();const c=selectedChain();if(!c)throw Error('Create or reopen a finite plan first.');
    const key='kaz-chain-command-'+c.plan.plan_identity,old=localStorage.getItem(key),command=old||crypto.randomUUID().replaceAll('-','');localStorage.setItem(key,command);
    const result=await api('chain/continue',{root_identity:rid,chain_id:c.plan.chain_id,command_key:command});
    if(result.state.command_keys.includes(command))localStorage.removeItem(key);await refresh();});
  chainButton('Pause chain (User Stop)',async()=>{const c=selectedChain();if(!c)throw Error('No finite plan.');await api('chain/stop',{root_identity:rid,chain_id:c.plan.chain_id});await refresh();});
  $('lc-result').parentNode.append(chainPanel);
  setInterval(()=>{const c=selectedChain();chainStatus.textContent=c?JSON.stringify({state:c.state.state,reason:c.state.reason,segments:c.state.segments,publication_profile:root()?.publication_profile,output_reserved_bytes:root()?.reserved_job_output_bytes,remaining_job_slots:root()?.remaining_job_slots,actual_envelope_seconds:c.state.observed_seconds,engineering_estimate:c.state.estimate,active_job:c.active_job_id},null,2):'No finite plan selected. Reopen never dispatches.';},1000);
  chainButton('Prepare portable initial job (no run)',async()=>{if(!root())throw Error('Select an immutable root.');
    const result=await api('portable/prepare',{root_identity:rid,strategy:'B60_SEALED_STATIC_V1',idempotency_key:crypto.randomUUID().replaceAll('-',''),execution_seconds:240});
    const link=document.createElement('a');link.href=result.url;link.download='kazeosat-initial-job.zip';link.textContent='Download offline initial-input job';$('lc-export-link').replaceChildren(link);});
  app.ready.then(()=>refresh()).catch(showError);setInterval(()=>refresh().catch(showError),1500);
})();
