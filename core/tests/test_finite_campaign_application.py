from dataclasses import replace
from copy import deepcopy
import pytest
from examples.m8_battery_port import make_inputs
from ops_sim.v5.finite_campaign import FiniteCampaignPolicy
from ops_sim.v5.lifecycle_application import LifecycleStore,make_intent
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection
from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,restore_checkpoint,make_bindings
from ops_sim.v5.lifecycle_document import dumps_root
from hashlib import sha256

def test_ten_job_new_store_no_migration_and_ninth_primary_refused(tmp_path):
 root=make_inputs(duration=600);s=LifecycleStore(tmp_path/'store',root,create=True,runner_policy=FiniteCampaignPolicy())
 for i in range(8):
  job,new=s.prepare_job(make_intent(root.identity,key=f'{i+1:032x}'))
  job.update(status='REFUSED',ownership_valid=True);s.update_job(job)
 with pytest.raises(ValueError,match='ninth primary'):s.prepare_job(make_intent(root.identity,key='f'*32))
 assert len(s.jobs())==8 and LifecycleStore(s.directory).maximum_jobs==10

def test_no_progress_negative_service_is_native_typed_and_not_resumable():
 root=make_inputs(duration=600,energy=45.)
 root=replace(root,battery_port_policy=replace(root.battery_port_policy,maximum_discharge_current_a=.001))
 state=start_lifecycle(root)
 for i in range(20):
  state,event,row=step_lifecycle(state)
  if state.status!='ACTIVE':break
 # This is real allocation/physics, not a synthetic returned outcome. Depending
 # on solar geometry a short real survival prefix may precede the boundary.
 assert state.status!='ACTIVE' and state.terminal is not None
 assert state.terminal['kind']in ('PHYSICAL','UNSUPPORTED') and not state.terminal['automatic_resume']
 assert state.physical.battery_port_work.reserved>0
 b=make_bindings(root,state.clock);raw=checkpoint_bytes(state,b)
 restored,proof=restore_checkpoint(raw,root,sha256(raw).hexdigest(),b)
 assert restored.terminal==state.terminal and scientific_projection(restored)==scientific_projection(state)


def test_solar_refusal_saved_parent_reader_uses_explicit_root_policy(tmp_path):
 root=make_inputs(duration=600);s=LifecycleStore(tmp_path/'store',root,create=True,runner_policy=FiniteCampaignPolicy())
 j,new=s.prepare_job(make_intent(root.identity,key='c'*32))
 j.update(status='REFUSED',ownership_valid=True,last_actual_refusal=dict(action_id='solar-0',kind='SOLAR_POINT',status='refused',reason='UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY',refusal_detail=None))
 s.update_job(j)
 assert s.job(j['job_id'])['last_actual_refusal']['kind']=='SOLAR_POINT'
 assert LifecycleStore(s.directory).job(j['job_id'])['last_actual_refusal']==j['last_actual_refusal']


@pytest.mark.parametrize('streamed',[False,True])
def test_new_finite_unsettled_reopen_is_typed_unknown_readonly_and_blocks_dispatch(tmp_path,streamed):
 from ops_sim.v5.lifecycle_application import LifecycleWorkspace
 from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
 from ops_sim.v5.lifecycle_compact import PublicationProfile
 root=make_inputs(duration=600)
 if streamed:root=replace(root,output_policy=LifecycleStreamPolicy())
 directory=tmp_path/'workspace';ws=LifecycleWorkspace(directory)
 ws.create(root,runner_policy=FiniteCampaignPolicy(),publication_profile=PublicationProfile()if streamed else None)
 store=ws.store(root.identity);j,new=store.prepare_job(make_intent(root.identity,key='e'*32,publication_profile=store.publication_profile))
 store.close_publications()
 before={p.relative_to(directory).as_posix():p.read_bytes()for p in directory.rglob('*')if p.is_file()}
 reopened=LifecycleWorkspace(directory);saved=reopened.store(root.identity).job(j['job_id'])
 assert saved['status']=='UNKNOWN'and saved['ownership_valid']is False and saved['result']is None
 assert saved['typed_stop']['kind']=='UNKNOWN'and saved['typed_stop']['clock']is None and not saved['typed_stop']['automatic_resume']
 with pytest.raises(ValueError,match='population/unknown ownership'):
  reopened.store(root.identity).prepare_job(make_intent(root.identity,key='f'*32,publication_profile=store.publication_profile))
 after={p.relative_to(directory).as_posix():p.read_bytes()for p in directory.rglob('*')if p.is_file()}
 assert after==before and reopened.active is None
