#!/usr/bin/env python3
"""Freeze fresh v2 paired views including two declared text-alias caches."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from sheets_factory.workbook.heterogeneous_review_tasks_v2 import prepare_pair

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True);p.add_argument("--config",type=Path,default=ROOT/"config/heterogeneous_review_tasks_v2.json");a=p.parse_args()
    print(json.dumps(prepare_pair(a.output,a.config),sort_keys=True))

if __name__=="__main__":main()
