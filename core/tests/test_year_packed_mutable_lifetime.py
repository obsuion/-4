"""Late saved-parent accounting uses only its original persistent three names."""
from pathlib import Path
import pytest

from ops_sim.v5 import lifetime_physical_storage as storage
from test_year_packed_capacity import policy,binding,write,seal


JID='1'*32


def reserve_job(owner):
    producer=dict(kind='SEGMENT',job_id=JID,intent_sha256='2'*64,request_sha256='3'*64)
    operation='d'*64;scope=owner.binding['store_name']+'/jobs/'+JID
    owner.reserve(operation,'RETAINED',2**20,producer,scope=scope,maximum_files=storage.PACKED_SEGMENT_FILES)
    return operation,producer,scope


def ledger_producer(leaf):return dict(kind='PARENT_APPEND_LEDGER',job_id=JID,leaf=leaf)


def append(owner,scope,leaf,data=b'paid'):
    name=scope+'/'+leaf
    reservation=owner.reserve_mutable(name,len(data),ledger_producer(leaf))
    path=owner.root/name
    with path.open('ab')as stream:stream.write(data);stream.flush()
    return reservation


@pytest.fixture
def closed(tmp_path):
    with storage.PhysicalStorage(tmp_path,policy(),binding(),create=True)as owner:
        operation,producer,scope=reserve_job(owner)
        anchor=write(owner,scope+'/scientific-prefix.bin',b'proved-scientific-prefix')
        append(owner,scope,storage.PACKED_MUTABLE_LEAVES[0])
        append(owner,scope,storage.PACKED_MUTABLE_LEAVES[1])
        seal(owner,operation,producer,tip=dict(clock=17))
        yield owner,operation,scope,anchor


def occupied(namespace):
    return namespace['cumulative_file_names']+namespace['mutable_names']+namespace['unused_unsettled_file_slots']


def test_closed_parent_append_and_first_late_validation_conserve_original_escrow(closed):
    owner,operation,scope,anchor=closed;before=owner.namespace_snapshot();charge=owner.snapshot()['mutable_reserved_bytes']
    assert before['unused_persistent_mutable_file_slots']==1
    assert before['protected_metadata_pages_for_mutations']==storage.PACKED_SEGMENT_METADATA_PAGES
    append(owner,scope,storage.PACKED_MUTABLE_LEAVES[0],b'more-paid')
    assert owner.namespace_snapshot()['mutable_names']==2
    late=append(owner,scope,storage.PACKED_MUTABLE_LEAVES[2],b'validation-paid')
    after=owner.namespace_snapshot()
    assert late['reserved_logical_bytes']==len(b'validation-paid')
    assert occupied(after)==occupied(before)==4
    assert after['mutable_names']==3 and after['unused_persistent_mutable_file_slots']==0
    assert after['protected_metadata_pages_for_mutations']==0
    assert owner.snapshot()['mutable_reserved_bytes']>=charge
    assert owner.snapshot()['tip']==dict(clock=17)and anchor.read_bytes()==b'proved-scientific-prefix'
    assert owner.db.execute('SELECT state FROM grants WHERE operation=?',(operation,)).fetchone()==('SEALED',)
    assert owner.db.execute('SELECT COUNT(*) FROM files').fetchone()==(1,)
    # Mutable appends never become another immutable file or pool credit.
    assert owner.db.execute('SELECT COUNT(*) FROM packed_pool_seals').fetchone()==(1,)


def test_fresh_owner_reopen_can_pay_closed_parent_read_without_new_job(closed):
    owner,operation,scope,anchor=closed
    with storage.PhysicalStorage(owner.root,policy(),binding())as reopened:
        first=append(reopened,scope,storage.PACKED_MUTABLE_LEAVES[2])
        second=append(reopened,scope,storage.PACKED_MUTABLE_LEAVES[2])
        assert(second['reserved_logical_bytes'],first['reserved_logical_bytes'])==(8,4)
        assert reopened.snapshot()['tip']==dict(clock=17)
        assert reopened.namespace_snapshot()['unused_persistent_mutable_file_slots']==0


def test_global_file_full_uses_precharged_third_slot_but_admits_no_new_segment(closed,monkeypatch):
    owner,operation,scope,anchor=closed
    assert occupied(owner.namespace_snapshot())==4
    monkeypatch.setattr(storage,'MAX_FILES',4)
    # The original slot is consumed, not added to a full namespace.
    append(owner,scope,storage.PACKED_MUTABLE_LEAVES[2])
    assert occupied(owner.namespace_snapshot())==4
    append(owner,scope,storage.PACKED_MUTABLE_LEAVES[0])
    result=owner.admission_status(1)
    assert result['admitted']is False and result['reason']==storage.GLOBAL_NAMESPACE_EXHAUSTED
    assert owner.snapshot()['tip']==dict(clock=17)


@pytest.mark.parametrize('damage',('fourth_leaf','other_job','extra_claim','orphan','scientific_name'))
def test_closed_parent_never_adopts_unreserved_or_foreign_mutable_name(closed,damage):
    owner,operation,scope,anchor=closed;leaf=storage.PACKED_MUTABLE_LEAVES[2]
    name=scope+'/'+leaf;producer=ledger_producer(leaf);before=owner.snapshot()['mutable_reserved_bytes']
    if damage=='fourth_leaf':name=scope+'/parent-fourth-work.bin';producer=ledger_producer('parent-fourth-work.bin')
    elif damage=='other_job':producer=dict(producer,job_id='9'*32)
    elif damage=='extra_claim':producer=dict(producer,arbitrary='not-authority')
    elif damage=='orphan':(owner.root/name).write_bytes(b'foreign-orphan')
    else:
        owner.db.execute('INSERT INTO claims VALUES (?,?,?,0,1)',(name,operation,'FILE'))
    with pytest.raises(ValueError):owner.reserve_mutable(name,4,producer)
    assert owner.snapshot()['mutable_reserved_bytes']==before
    assert owner.snapshot()['tip']==dict(clock=17)and anchor.read_bytes()==b'proved-scientific-prefix'


@pytest.mark.parametrize('damage',('missing','partial','oversize','producer_drift'))
def test_existing_mutable_gap_or_identity_drift_preserves_charge_and_refuses(closed,damage):
    owner,operation,scope,anchor=closed;leaf=storage.PACKED_MUTABLE_LEAVES[0]
    path=owner.root/scope/leaf;producer=ledger_producer(leaf)
    if damage=='missing':path.unlink()
    elif damage=='partial':path.write_bytes(b'x')
    elif damage=='oversize':path.write_bytes(b'x'*5)
    else:producer=dict(producer,job_id='9'*32)
    before=owner.snapshot()['mutable_reserved_bytes']
    with pytest.raises(ValueError):owner.reserve_mutable(scope+'/'+leaf,4,producer)
    assert owner.snapshot()['mutable_reserved_bytes']==before
    assert owner.snapshot()['tip']==dict(clock=17)


def test_unknown_original_job_cannot_gain_or_append_mutable_authority(tmp_path):
    with storage.PhysicalStorage(tmp_path,policy(),binding(),create=True)as owner:
        operation,producer,scope=reserve_job(owner);write(owner,scope+'/anchor.bin')
        append(owner,scope,storage.PACKED_MUTABLE_LEAVES[0]);owner.mark_unknown(operation)
        before=owner.snapshot()['mutable_reserved_bytes']
        for leaf in(storage.PACKED_MUTABLE_LEAVES[0],storage.PACKED_MUTABLE_LEAVES[2]):
            with pytest.raises(ValueError,match='UNKNOWN'):owner.reserve_mutable(scope+'/'+leaf,4,ledger_producer(leaf))
        assert owner.snapshot()['mutable_reserved_bytes']==before
        assert owner.namespace_snapshot()['unused_persistent_mutable_file_slots']==2
