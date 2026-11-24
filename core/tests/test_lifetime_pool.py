from dataclasses import replace
import pytest,json
from ops_sim.v5.lifetime_pool import reserve,measure
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy,QUALIFICATION

def policy():return LifetimeCampaignPolicy(mode=QUALIFICATION,maximum_primary_segments=2,reserved_diagnostic_slots=1,hard_seconds=60,soft_seconds=8,finalization_seconds=52)

def test_all_designs_share_one_pool_and_reopen_does_not_double_count(tmp_path):
    p=policy();one=reserve(tmp_path,'a'*64,p,pool_bytes=p.pool_commitment_bytes,windows=True)
    again=reserve(tmp_path,'a'*64,p,windows=True)
    assert one['pool']==again['pool'] and len(again['pool']['reservations'])==1
    with pytest.raises(ValueError,match='all-design'):reserve(tmp_path,'b'*64,p,windows=True)
    assert len(json.loads((tmp_path/'LIFETIME-POOL.json').read_bytes())['reservations'])==1
    assert one['pool']['pool_bytes']==p.pool_commitment_bytes

def test_same_identity_cannot_change_policy_and_measure_is_separate(tmp_path):
    p=policy();reserve(tmp_path,'a'*64,p,windows=True)
    (tmp_path/'data.bin').write_bytes(b'x'*100)
    assert measure(tmp_path)['measured_bytes']>=100
    with pytest.raises(ValueError,match='drift'):reserve(tmp_path,'a'*64,replace(p,backup_copies=2),windows=True)


# V1 tests above remain historical API checks.  V2 never credits measure(root).
from hashlib import sha256
from types import SimpleNamespace
from ops_sim.v5 import lifetime_pool as pool


def owner(path='one.store',token='1',role='STORE',kind='DIRECTORY'):
    return dict(owner=token*64,role=role,path=path,identity='e'*64,kind=kind)


def item(path,token='1'):
    return dict(owner=token*64,path=path.name,sha256=sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)


def inventory(root,path,token='1'):
    result=item(path,token);result['path']=path.relative_to(root).as_posix();return result


def free_space(monkeypatch,value):
    monkeypatch.setattr(pool.shutil,'disk_usage',lambda path:SimpleNamespace(free=value))


def test_v2_foreign_consumption_inside_pool_does_not_credit_itself(tmp_path,monkeypatch):
    p=policy();cap=p.pool_commitment_bytes
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES)
    pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],pool_bytes=cap,windows=True)
    before=(tmp_path/pool.POOL_V2).read_bytes()
    foreign=tmp_path/'unrelated.bin';foreign.write_bytes(b'x'*100)
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES-50)
    with pytest.raises(ValueError,match='unattributed'):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],windows=True)
    assert foreign.read_bytes()==b'x'*100
    assert (tmp_path/pool.POOL_V2).read_bytes()==before


def test_v2_materialized_own_bytes_not_double_charged_and_no_refund(tmp_path,monkeypatch):
    p=policy();cap=p.pool_commitment_bytes
    path=tmp_path/'one.store'/'owned.bin';path.parent.mkdir();path.write_bytes(b'x'*4096)
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES)
    monkeypatch.setattr(pool,'_v2_physical_credit',lambda info:info.st_size)
    own=[inventory(tmp_path,path)]
    first=pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=own,pool_bytes=cap,windows=True)
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES-4096)
    again=pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=own,windows=True)
    assert first['pool']==again['pool']
    assert again['credited_physical_bytes']==4096
    assert again['outstanding_reserved_bytes']==cap-4096
    with pytest.raises(ValueError,match='no dropped'):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],windows=True)
    assert again['pool']['reservations']['a'*64]['total_reserved_bytes']==cap


def test_v2_all_stores_and_backups_share_full_prospective_sum(tmp_path,monkeypatch):
    p=policy();cap=2*p.pool_commitment_bytes
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES)
    a=[owner(),owner('one.backup','2','BACKUP')]
    b=[owner('two.store','3'),owner('two.backup','4','BACKUP')]
    pool.reserve_v2(tmp_path,'a'*64,p,owners=a,pool_bytes=cap,windows=True)
    result=pool.reserve_v2(tmp_path,'b'*64,p,owners=b,windows=True)
    assert result['total_reserved_bytes']==cap and result['capacity_devices']==1
    before=(tmp_path/pool.POOL_V2).read_bytes()
    with pytest.raises(ValueError,match='all-design'):
        pool.reserve_v2(tmp_path,'c'*64,p,owners=[owner('three.store','5')],windows=True)
    assert (tmp_path/pool.POOL_V2).read_bytes()==before


@pytest.mark.parametrize('owners',[
    [owner(),owner('one.store/nested','2','BACKUP')],
    [owner(),owner('ONE.STORE','2','BACKUP')],
    [owner(),owner('other','1','BACKUP')],
    [owner('../outside')],[owner('/absolute')],[owner('one\\bad')],
    [owner('CON')],[owner('aux.txt')],[owner('COM1.data')],
    [owner('one./file')],[owner('one /file')],[owner('one\nfile')],
    [owner('e\u0301.store')],
])
def test_v2_overlapping_traversal_or_duplicate_claims_refuse(tmp_path,monkeypatch,owners):
    p=policy();free_space(monkeypatch,p.pool_commitment_bytes+pool.POOL_SAFETY_BYTES)
    with pytest.raises(ValueError):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=owners,pool_bytes=p.pool_commitment_bytes,windows=True)
    assert not (tmp_path/pool.POOL_V2).exists()


def test_v2_foreign_hash_size_and_policy_drift_refuse_without_repair(tmp_path,monkeypatch):
    p=policy();cap=p.pool_commitment_bytes
    path=tmp_path/'one.store'/'owned.bin';path.parent.mkdir();path.write_bytes(b'x'*100)
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES)
    own=[inventory(tmp_path,path)]
    pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=own,pool_bytes=cap,windows=True)
    before=(tmp_path/pool.POOL_V2).read_bytes()
    path.write_bytes(b'y'*100)
    with pytest.raises(ValueError,match='hash'):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=own,windows=True)
    with pytest.raises(ValueError,match='ownership drift'):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner('other')],windows=True)
    with pytest.raises(ValueError,match='ownership drift'):
        pool.reserve_v2(tmp_path,'a'*64,replace(p,backup_copies=2),owners=[owner()],windows=True)
    assert (tmp_path/pool.POOL_V2).read_bytes()==before
    assert path.read_bytes()==b'y'*100


def test_v2_unregistered_file_inside_owned_directory_is_not_owned_credit(tmp_path,monkeypatch):
    p=policy();cap=p.pool_commitment_bytes
    folder=tmp_path/'one.store';folder.mkdir();(folder/'foreign.bin').write_bytes(b'x'*1000)
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES)
    result=pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],pool_bytes=cap,windows=True)
    assert result['credited_physical_bytes']==0 and result['unregistered_files_credit_bytes']==0
    assert result['owned']['a'*64]['owned_files']==0


def test_v2_current_mutable_head_can_shrink_without_refunding_commitment(tmp_path,monkeypatch):
    p=policy();cap=p.pool_commitment_bytes
    path=tmp_path/'one.store'/'head.json';path.parent.mkdir();path.write_bytes(b'x'*100)
    free_space(monkeypatch,cap+pool.POOL_SAFETY_BYTES)
    monkeypatch.setattr(pool,'_v2_physical_credit',lambda info:info.st_size)
    pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=[inventory(tmp_path,path)],pool_bytes=cap,windows=True)
    path.write_bytes(b'y'*10)
    result=pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=[inventory(tmp_path,path)],windows=True)
    assert result['total_reserved_bytes']==cap
    assert result['outstanding_reserved_bytes']==cap-10


def test_v2_unknown_sparse_compressed_and_allocated_semantics():
    assert pool._v2_physical_credit(SimpleNamespace(st_size=100))==0
    assert pool._v2_physical_credit(SimpleNamespace(st_size=100,st_file_attributes=0x200))==0
    assert pool._v2_physical_credit(SimpleNamespace(st_size=100,st_file_attributes=0x800))==0
    assert pool._v2_physical_credit(SimpleNamespace(st_size=100,st_file_attributes=0x20))==100
    assert pool._v2_physical_credit(SimpleNamespace(st_size=1024,st_blocks=1))==512
    assert pool._v2_physical_credit(SimpleNamespace(st_size=100,st_blocks=1))==100


def test_v2_hardlinked_claim_is_rejected(tmp_path,monkeypatch):
    import os
    p=policy();folder=tmp_path/'one.store';folder.mkdir()
    path=folder/'owned.bin';path.write_bytes(b'x'*100)
    try:os.link(path,folder/'alias.bin')
    except (OSError,NotImplementedError):pytest.skip('filesystem cannot create fixture hardlink')
    free_space(monkeypatch,p.pool_commitment_bytes+pool.POOL_SAFETY_BYTES)
    with pytest.raises(ValueError,match='single-link'):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=[inventory(tmp_path,path)],
                        pool_bytes=p.pool_commitment_bytes,windows=True)


def test_v2_foreign_file_cannot_be_claimed_by_other_owner(tmp_path,monkeypatch):
    p=policy();path=tmp_path/'unrelated.bin';path.write_bytes(b'x')
    free_space(monkeypatch,p.pool_commitment_bytes+pool.POOL_SAFETY_BYTES)
    with pytest.raises(ValueError,match='outside declared'):
        pool.reserve_v2(tmp_path,'a'*64,p,owners=[owner()],inventory=[inventory(tmp_path,path)],
                        pool_bytes=p.pool_commitment_bytes,windows=True)
    assert path.read_bytes()==b'x'


def test_v2_does_not_rewrite_or_import_historical_v1_pool(tmp_path,monkeypatch):
    p=policy();free_space(monkeypatch,2*p.pool_commitment_bytes+2**30)
    reserve(tmp_path,'a'*64,p,pool_bytes=p.pool_commitment_bytes,windows=True)
    before=(tmp_path/'LIFETIME-POOL.json').read_bytes()
    with pytest.raises(ValueError,match='V1 unowned'):
        pool.reserve_v2(tmp_path,'b'*64,p,owners=[owner()],windows=True)
    assert (tmp_path/'LIFETIME-POOL.json').read_bytes()==before
    assert not (tmp_path/pool.POOL_V2).exists()
