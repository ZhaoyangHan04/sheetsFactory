#!/usr/bin/env python3
"""Freeze both genuine scoped heterogeneous views; no calculation or model call."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from sheets_factory.workbook.heterogeneous_review_tasks import prepare_pair

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=ROOT/"config/heterogeneous_review_tasks_v1.json")
    args=parser.parse_args()
    print(json.dumps(prepare_pair(args.output,args.config),sort_keys=True))

if __name__=="__main__":main()
