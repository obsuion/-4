"""Offline portable authority checks, including fresh Python network denial."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from examples.m2_sun_table_demo import example_query,summary,block_network
from ops_sim.v5.experiment_codec import canonical_content,decode_content
from ops_sim.v5.sun_table import evaluate_sun_position,evaluate_table_orbit_sun
from ops_sim.v5.sun_table_document import (
    table_to_json,table_from_json,table_digest,table_query_to_json,table_query_from_json,
    table_query_digest,save_table,save_table_query,load_table,load_table_query,
)


@pytest.mark.parametrize("kind",["two-body","j2","unresolved","external"])
def test_roundtrip_offline_fresh_process(kind,tmp_path):
    q=example_query(kind);t=q.table
    assert table_from_json(table_to_json(t),expected_digest=table_digest(t))==t
    assert table_query_from_json(table_query_to_json(q),expected_digest=table_query_digest(q))==q
    p=tmp_path/"query.json";save_table_query(p,q)
    # Loading has no access to source fixture: the entire table is in this input.
    command=[sys.executable,"-B","-m","examples.m2_sun_table_demo","--inputs",str(p),
             "--expected-digest",table_query_digest(q),"--offline"]
    result=subprocess.run(command,capture_output=True,text=True,check=True,
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PYTHONUTF8="1"))
    output=json.loads(result.stdout)
    assert output["python_network_disabled"] is True
    assert output["evidence"]==json.loads(json.dumps(summary(evaluate_table_orbit_sun(q))))
    with pytest.raises(FileExistsError):save_table_query(p,q)
    p2=tmp_path/"table.json";save_table(p2,t)
    assert load_table(p2)==t
    with pytest.raises(FileExistsError):save_table(p2,t)


def test_network_guard_actually_rejects_socket_calls():
    code="from examples.m2_sun_table_demo import block_network; import socket; block_network(); socket.getaddrinfo('example.com',443)"
    p=subprocess.run([sys.executable,"-B","-c",code],capture_output=True,text=True,
                     env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode!=0 and "network disabled" in p.stderr


@pytest.mark.parametrize("field,value",[
    ("version",True),("version",2),("canonical_version",2),("format","wrong"),
    ("digest","0"*64),("digest","F"*64),("digest",None),("derived_result",{}),
])
@pytest.mark.parametrize("query",[False,True])
def test_strict_envelope(field,value,query):
    q=example_query("two-body")
    writer=table_query_to_json if query else table_to_json
    reader=table_query_from_json if query else table_from_json
    p=json.loads(writer(q if query else q.table));p[field]=value
    with pytest.raises((TypeError,ValueError)):reader(json.dumps(p))


@pytest.mark.parametrize("field",["epoch","frame","domain_seconds","interpolation","samples","provenance"])
def test_missing_table_fields(field):
    p=json.loads(table_to_json(example_query("two-body").table))
    data=decode_content(p["inputs"]);del data[field];p["inputs"]=canonical_content(data)
    with pytest.raises(ValueError):table_from_json(json.dumps(p))


@pytest.mark.parametrize("location",["root","sample","provenance"])
def test_unknown_input_fields(location):
    p=json.loads(table_to_json(example_query("two-body").table));data=decode_content(p["inputs"])
    target=data if location=="root" else data["samples"][0] if location=="sample" else data["provenance"]
    target["verified_position"]=True;p["inputs"]=canonical_content(data)
    with pytest.raises(ValueError,match="fields"):table_from_json(json.dumps(p))


@pytest.mark.parametrize("value",[[1.,2.,3.],(1,2,3),(True,2.,3.),(float("nan"),2.,3.)])
def test_malformed_wire_components(value):
    p=json.loads(table_to_json(example_query("two-body").table));data=decode_content(p["inputs"])
    data["samples"][0]["position_m"]=value
    with pytest.raises((TypeError,ValueError)):
        p["inputs"]=canonical_content(data);table_from_json(json.dumps(p))


def test_duplicates_digest_changes_and_tampering():
    with pytest.raises(ValueError,match="duplicate"):table_from_json('{"a":1,"a":2}')
    q=example_query("two-body");old=table_digest(q.table)
    changed=replace(q.table,provenance=replace(q.table.provenance,accuracy_statement="Other declared unknown"))
    assert table_digest(changed)!=old
    with pytest.raises(ValueError,match="expected"):table_from_json(table_to_json(changed),expected_digest=old)
    p=json.loads(table_to_json(q.table));data=decode_content(p["inputs"])
    data["samples"][0]["position_m"]=(101.,0.,0.);p["inputs"]=canonical_content(data)
    with pytest.raises(ValueError,match="digest"):table_from_json(json.dumps(p))


def test_external_header_binding_and_actual_time_dependence():
    t=example_query("external").table;p=t.provenance
    assert (p.source_timescale,p.axes,p.reference_plane,p.correction,p.ephemeris_id)==("TT","ICRF","FRAME","GEOMETRIC","DE441")
    assert t.domain_seconds==(0.,21600.)
    assert len(t.samples)==7
    assert len({s.position_m for s in t.samples})==7
    assert p.response_sha256=="421642fcb686c33e37a3c78ad8eef4fa4aafaf3bc52add81fe4ebc3c9002b3c5"
    assert (t.epoch.julian_day,t.epoch.fractional_day)==(2461314,.5)
    assert t.samples[0].position_m==(-148525716609.0804,-17863083419.12222,-7741887444.779336)
    assert p.accuracy_policy=="UNQUANTIFIED"


@pytest.mark.parametrize("field,value",[
    ("retrieved_utc",None),("retrieved_utc","2026-10-01T00:00:00"),
    ("retrieved_utc","2026-10-01T00:00:00+03:00"),("request_sha256","bad"),
    ("response_sha256",None),("ephemeris_id",""),("source_ids",()),
    ("axes","J2000"),("reference_plane","ECLIPTIC"),("alignment","VERIFIED_EOP"),
])
def test_external_metadata_not_optional(field,value):
    with pytest.raises((TypeError,ValueError)):replace(example_query("external").table.provenance,**{field:value})


def test_no_new_codec_registration_or_scenario_import():
    with pytest.raises(TypeError):canonical_content(example_query("two-body").table)
    assert "ops_sim.v5.scenario_inputs" not in sys.modules
