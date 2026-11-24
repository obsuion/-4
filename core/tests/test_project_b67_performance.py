"""Independent retained wire oracles for the two B67 caller-path changes."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
import json
import pytest

from test_spacecraft_design import common,specification
from ops_sim.v5.spacecraft_project_v2 import SpacecraftProjectV2
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5 import spacecraft_project_v2_document as doc
from ops_sim.v5.lifecycle_document import dumps_root,canonical
from ops_sim.v5.prepared_input_codec import PreparedInputCodec


@pytest.fixture(scope='module')
def project(common,specification):
    return SpacecraftProjectV2(common,specification,project_source_identity(),'B67 codec oracle')


def legacy_document(project):
    # Existing reference encoders remain unmodified and unscoped.
    body=dict(format=doc.FORMAT,version=2,inputs=dict(
        common=json.loads(dumps_root(project.common)),
        specification=doc.specification_data(project.specification),
        source_identity=project.source_identity,title=project.title,
        requirements=asdict(project.requirements),limits=asdict(project.limits),method=project.method))
    body['digest']=sha256(canonical(body).encode()).hexdigest()
    return canonical(body)


def test_complete_general_document_and_roundtrip_match_retained_unscoped_wire(project):
    reference=legacy_document(project)
    assert doc.dumps_project(project)==reference
    assert doc.dumps_project(doc.loads_project(reference))==reference
    scope=PreparedInputCodec()
    with scope:
        decoded=doc._loads_project(reference,expected_identity=project.identity,input_codec=scope)
        assert doc._dumps_project(decoded,scope)==reference
    receipt=scope.receipt()
    assert receipt['counters']['full_schema_scans']==2
    assert receipt['counters']['typed_roundtrips']>0
    assert receipt['phase']=='CLOSED' and receipt['secondary_errors']==[]


def test_unused_general_owner_mutation_is_rejected_at_scope_exit():
    owner=doc.PVModule;original=owner.__post_init__
    try:
        with pytest.raises(ValueError,match='drift'):
            with PreparedInputCodec():
                owner.__post_init__=lambda self:None
    finally:
        owner.__post_init__=original


def test_general_codec_function_mutation_is_rejected_at_exit():
    original=doc._decode
    try:
        with pytest.raises(ValueError,match='drift'):
            with PreparedInputCodec():doc._decode=lambda *a,**k:None
    finally:doc._decode=original


@pytest.mark.parametrize('duration',(Q(1),Q(1,3),Q(1,8)))
def test_unprepared_selected_fold_matches_old_complete_wire(physical,duration):
    from test_lifecycle_native_state import arguments
    from test_lifecycle_prepared_report import row_for,exact
    from ops_sim.v5.integration_time import RationalSeconds
    from ops_sim.v5.construction_service import service_physical_substep
    from ops_sim.v5.lifecycle_prepared_report import _consume_selected_part
    from ops_sim.v5.lifecycle_report import _part
    from ops_sim.v5.long_mission_continuation import _scientific
    from ops_sim.v5.design_repair_study import _plain_output
    args,kwargs=arguments(physical)
    args=(args[0],RationalSeconds.from_fraction(duration),*args[2:])
    kwargs['end_seconds']=kwargs['start_seconds']+duration
    part,_=service_physical_substep(*args,**kwargs)
    expected=deepcopy(row_for(physical));actual=deepcopy(expected)
    _part(expected,_plain_output(_scientific(part)))
    _consume_selected_part(actual,part)
    assert exact(actual)==exact(expected)


from test_lifecycle_native_state import template,physical
