"""Portable input-only codec checks, including predecode hostile fields."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import json
import pytest

from test_environment_forcing import fixture, T
from ops_sim.v5 import environment_forcing_document as d
from ops_sim.v5 import orbit_sun_zonotope_local_v2 as light


def test_input_document_roundtrip_rational_time_and_no_result_authority(tmp_path,monkeypatch):
    r,q=fixture();q=replace(q,start_seconds=T(Q(1,3)),end_seconds=T(Q(17,3)))
    def forbidden(*a,**k):raise AssertionError("loading cannot evaluate orbit")
    monkeypatch.setattr(light,"evaluate_zonotope_local_illumination_v2",forbidden)
    text=d.environment_forcing_to_json(q);digest=d.environment_forcing_digest(q)
    loaded=d.environment_forcing_from_json(text,expected_digest=digest)
    assert d.environment_forcing_to_json(loaded)==text
    assert loaded.start_seconds==T(Q(1,3)) and loaded.end_seconds==T(Q(17,3))
    path=tmp_path/"input.json";d.save_environment_forcing(path,q)
    assert d.environment_forcing_to_json(d.load_environment_forcing(path))==text
    with pytest.raises(FileExistsError):d.save_environment_forcing(path,q)
    assert "coverage_complete" not in text and "final_proposal" not in text
    with pytest.raises(TypeError):d.environment_forcing_to_json(r)


@pytest.mark.parametrize("kind", ["root_unknown", "inputs_unknown", "profile_unknown", "node_unknown",
    "loads_unknown", "policy_unknown", "bool_version", "bool_policy", "negative_heat", "nonfinite",
    "duplicate_node", "missing_node", "false_binding", "bad_digest", "bad_fraction", "fraction_budget",
    "deep", "foreign_source", "nested_identity", "many_entries", "eps_losses", "sink_double_count"])
def test_every_unsafe_input_rejected_before_nested_physical_decoder(kind,monkeypatch):
    _,q=fixture();raw=json.loads(d.environment_forcing_to_json(q));v=raw["inputs"]
    if kind=="root_unknown":raw["result"]={}
    elif kind=="inputs_unknown":v["class"]="os.system"
    elif kind=="profile_unknown":v["profile"][0]["hook"]="eval"
    elif kind=="node_unknown":v["profile"][0]["nodes"][0]["certificate"]={}
    elif kind=="loads_unknown":v["profile"][0]["loads"]["battery_losses_w"]=1
    elif kind=="policy_unknown":v["policy"]["bypass"]=True
    elif kind=="bool_version":raw["version"]=True
    elif kind=="bool_policy":v["policy"]["max_cells"]=True
    elif kind=="negative_heat":v["profile"][0]["nodes"][0]["absorbed_albedo_w"]=-1.
    elif kind=="nonfinite":v["profile"][0]["nodes"][0]["absorbed_solar_w"]=float("inf")
    elif kind=="duplicate_node":v["profile"][0]["nodes"].append(v["profile"][0]["nodes"][0])
    elif kind=="missing_node":v["profile"][0]["nodes"].pop()
    elif kind=="false_binding":v["source_request_digest"]="0"*64
    elif kind=="bad_digest":raw["digest"]="0"*64
    elif kind=="bad_fraction":v["start_seconds"]=["2","6"]
    elif kind=="fraction_budget":v["end_seconds"]=["6",str(2**64+1)]
    elif kind=="deep":
        x=0
        for _ in range(70):x=[x]
        raw["inputs"]["deep"]=x
    elif kind=="foreign_source":v["source_request"]["inputs"]={"kind":"record","type":"subprocess.Popen","fields":{}}
    elif kind=="nested_identity":v["source_request"]["version"]=True
    elif kind=="many_entries":v["profile"]=v["profile"]*129
    elif kind=="eps_losses":v["profile"][0]["internal_includes_eps_losses"]=True
    elif kind=="sink_double_count":v["profile"][0]["nodes"][0]["sink_includes"]=["solar"]
    def forbidden(*a,**k):raise AssertionError("unsafe fields reached physical decoder")
    monkeypatch.setattr(d.source_doc,"zonotope_local_request_from_json_v2",forbidden)
    with pytest.raises((TypeError,ValueError)):
        d.environment_forcing_from_json(json.dumps(raw))


def test_duplicate_json_keys_and_text_budget_rejected():
    with pytest.raises(ValueError,match="duplicate"):
        d.environment_forcing_from_json('{"format":"x","format":"x"}')
    with pytest.raises(ValueError,match="budget"):
        d.environment_forcing_from_json(" "*(d.MAX_TEXT_BYTES+1))


def test_expected_digest_detects_valid_foreign_document():
    _,q=fixture()
    with pytest.raises(ValueError,match="digest"):
        d.environment_forcing_from_json(d.environment_forcing_to_json(q),expected_digest="f"*64)
