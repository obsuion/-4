"""Prepare only, without dispatch. Input bytes remain the original authority."""
from pathlib import Path
import argparse
from ops_sim.v5.lifecycle_document import loads_root
from ops_sim.v5.portable_job import prepare

def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);p.add_argument('--key',required=True);a=p.parse_args()
    print(prepare(a.output,loads_root(a.input.read_bytes()),Path(__file__).resolve().parents[1],key=a.key))

if __name__=='__main__':main()
