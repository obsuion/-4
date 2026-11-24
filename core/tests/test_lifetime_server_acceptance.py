import pytest
from ops_sim.v5.lifetime_server_acceptance import admit_acceptance

def test_manually_asserted_booleans_are_not_an_acceptance_gate(tmp_path):
    p=tmp_path/'SERVER-PILOT-PASS.json';p.write_text('{"full_science_linux_day_completed":true,"native_resume_checked":true}')
    with pytest.raises(ValueError):admit_acceptance(p,'a'*64)
