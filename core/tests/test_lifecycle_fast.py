from dataclasses import dataclass
from fractions import Fraction
import pytest
from ops_sim.v5.lifecycle_fast import execution_strategy,FAST,REFERENCE,admit_policy,authority_identity,StaticSession,MAX_ENTRIES

@dataclass(frozen=True)
class Policy:
    number: float=1.
    offset: Fraction=Fraction(1,3)
    def __post_init__(self):
        if type(self.number)is not float or self.number<0:raise ValueError('policy')

def test_reference_and_fast_real_call_counts_and_separate_sessions():
    p=Policy()
    with execution_strategy(FAST,'a'*64)as s:
        for _ in range(8):admit_policy(p)
        assert s.work['full_operations']==1 and s.work['hits']==7
    with execution_strategy(FAST,'b'*64)as s:
        admit_policy(p);assert s.work['misses']==1
    with execution_strategy(REFERENCE,'a'*64)as s:assert s is None and admit_policy(p)is None

def test_static_tampering_detected_before_hit():
    p=Policy()
    with execution_strategy(FAST,'a'*64):
        admit_policy(p);object.__setattr__(p,'number',2.)
        with pytest.raises(ValueError,match='DRIFT'):admit_policy(p)

def test_fraction_internal_tampering_and_exact_ownership():
    p=Policy(offset=Fraction(2,7))
    with execution_strategy(FAST,'a'*64)as s:
        admit_policy(p);admit_policy(Policy())
        assert s.work['misses']==2
        p.offset._numerator=3
        with pytest.raises(ValueError,match='FRACTION'):admit_policy(p)

def test_no_mutable_authority():
    with execution_strategy(FAST,'a'*64):
        with pytest.raises(TypeError):authority_identity(([],),lambda:'x')

def test_identity_result_exact_and_bounded_retention():
    with execution_strategy(FAST,'a'*64)as s:
        values=[Policy(float(i))for i in range(MAX_ENTRIES+16)]
        for v in values:assert authority_identity((v,),lambda:'expected')=='expected'
        assert len(s.entries)==MAX_ENTRIES and s.work['evictions']==16
        assert s.retained_bytes<=64*2**20

@pytest.mark.parametrize('strategy',['',False,'fast'])
def test_unknown_strategy(strategy):
    with pytest.raises(ValueError):
        with execution_strategy(strategy,'a'*64):pass

def test_no_nested_or_leaked_context():
    with execution_strategy(FAST,'a'*64):
        with pytest.raises(ValueError):
            with execution_strategy(FAST,'a'*64):pass
    with execution_strategy(FAST,'a'*64):pass
