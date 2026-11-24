"""Portable input boundaries and actual independent-process reconstruction."""
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from examples.m2_orbit_sun_demo import demo_query, summary
from ops_sim.v5.experiment_codec import canonical_content, decode_content
from ops_sim.v5.orbit_sun import evaluate_orbit_sun
from ops_sim.v5.orbit_sun_document import (
    query_to_json, query_from_json, query_digest, save_query, load_query,
)


@pytest.mark.parametrize("kind",["two-body","j2","unresolved","rotated"])
def test_roundtrip_and_fresh_process(tmp_path,kind):
    q=demo_query(kind); original=query_to_json(q)
    p=tmp_path/(kind+".json")
    save_query(p,q)
    assert load_query(p,expected_digest=query_digest(q))==q
    assert query_to_json(query_from_json(original))==original
    result=subprocess.run([sys.executable,"-B","-m","examples.m2_orbit_sun_demo",
                           "--inputs",str(p),"--expected-digest",query_digest(q)],
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PYTHONUTF8="1"),
        capture_output=True,text=True,check=True)
    expected=json.loads(json.dumps(summary(evaluate_orbit_sun(q))))
    assert json.loads(result.stdout)["evidence"]==expected
    with pytest.raises(FileExistsError): save_query(p,q)


@pytest.mark.parametrize("field,value",[
    ("format","wrong"),("version",True),("version",2),("canonical_version",2),
    ("digest","0"*64),("digest","A"*64),("digest",None),("derived_geometry",{}),
])
def test_strict_envelope(field,value):
    p=json.loads(query_to_json(demo_query()))
    p[field]=value
    with pytest.raises((TypeError,ValueError)):query_from_json(json.dumps(p))


@pytest.mark.parametrize("field",["format","version","canonical_version","inputs","digest"])
def test_missing_envelope_fields(field):
    p=json.loads(query_to_json(demo_query()));del p[field]
    with pytest.raises((TypeError,ValueError)):query_from_json(json.dumps(p))


def test_duplicate_json_keys():
    with pytest.raises(ValueError,match="duplicate"):
        query_from_json('{"version":1,"version":1}')


@pytest.mark.parametrize("field",["coast","instant","sun"])
def test_missing_input_fields(field):
    p=json.loads(query_to_json(demo_query()));data=decode_content(p["inputs"]);del data[field]
    p["inputs"]=canonical_content(data)
    with pytest.raises((TypeError,ValueError)):query_from_json(json.dumps(p))


@pytest.mark.parametrize("path",["sun","direction"])
def test_unknown_nested_fields(path):
    p=json.loads(query_to_json(demo_query()));data=decode_content(p["inputs"])
    node=data["sun"] if path=="sun" else data["sun"]["direction"]
    node["qualified"]="ILLUMINATED"
    p["inputs"]=canonical_content(data)
    with pytest.raises(ValueError,match="unknown"):query_from_json(json.dumps(p))


def test_wrong_direction_record_and_noncanonical_components():
    q=demo_query();p=json.loads(query_to_json(q));data=decode_content(p["inputs"])
    data["sun"]["direction"]["components"]=[-1.,0.,0.]
    p["inputs"]=canonical_content(data)
    with pytest.raises(TypeError):query_from_json(json.dumps(p))
    data["sun"]["direction"]["components"]=(-1,0,0)
    p["inputs"]=canonical_content(data)
    with pytest.raises(ValueError,match="noncanonical"):query_from_json(json.dumps(p))


def test_stale_bindings_and_input_changes():
    q=demo_query();old=query_digest(q)
    changed=replace(q,sun=replace(q.sun,rationale=q.sun.rationale+" changed"))
    assert query_digest(changed)!=old
    with pytest.raises(ValueError,match="expected"):
        query_from_json(query_to_json(changed),expected_digest=old)
    changed=replace(q,coast=replace(q.coast,enclosure_policy=replace(q.coast.enclosure_policy,max_steps=31)))
    assert query_digest(changed)!=old
    p=json.loads(query_to_json(q));data=decode_content(p["inputs"])
    data["sun"]["rationale"]="tampered without new digest"
    p["inputs"]=canonical_content(data)
    with pytest.raises(ValueError,match="digest"):query_from_json(json.dumps(p))


def test_query_is_not_a_derived_output_document():
    output=summary(evaluate_orbit_sun(demo_query("unresolved")))
    with pytest.raises(ValueError,match="fields"):query_from_json(json.dumps(output))
