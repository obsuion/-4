from dataclasses import asdict,replace
import pytest
from ops_sim.v5.lifetime_policy import *

@pytest.mark.parametrize('field,value',[('maximum_primary_segments',True),('maximum_primary_segments',1),('reserved_diagnostic_slots',0),('hard_seconds',float('inf')),('soft_seconds',0),('cleanup_seconds',3),('backup_copies',0),('maximum_metadata_bytes',2**20),('method','B59'),('mode','fake')])
def test_strict_finite_policy(field,value):
    with pytest.raises(ValueError):LifetimeCampaignPolicy(**{field:value})

def test_explicit_local_mode_and_backup_reservations():
    p=LifetimeCampaignPolicy();assert admit_policy(asdict(p))==p
    assert p.maximum_jobs==4100 and p.pool_commitment_bytes==2*p.maximum_reserved_job_output_bytes
    with pytest.raises(ValueError):replace(p,mode=QUALIFICATION)
    q=replace(p,mode=QUALIFICATION,maximum_primary_segments=4,reserved_diagnostic_slots=2,hard_seconds=60,soft_seconds=8,finalization_seconds=52)
    assert q.mode==QUALIFICATION and q.identity!=p.identity

def test_no_initial_rewind_after_paid_primary():
    from ops_sim.v5.lifecycle_application import make_intent
    p=LifetimeCampaignPolicy();intent=make_intent('a'*64,key='a'*32)
    j=dict(job_id='b'*32,intent=intent,resume=None,result={'checkpoint':{'sha256':'c'*64},'clock':400})
    with pytest.raises(ValueError,match='latest forward'):admit_roles(p,intent,None,None,[j],1800)
