from pathlib import Path
from functools import lru_cache
from ops_sim.v5.lifetime_admission import derive_duration,derive_accounting

SOURCE=Path(__file__).resolve().parents[1]
RAW=(SOURCE/'tests/fixtures/lifetime_v7_initial.json').read_bytes()

@lru_cache(maxsize=4)
def root_for(duration=1800):
    _,raw,_=derive_duration(RAW,duration)
    return derive_accounting(raw)[0]
