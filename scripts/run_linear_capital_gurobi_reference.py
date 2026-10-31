#!/usr/bin/env python3
"""Explicit research-only preparation / first-attempt Gurobi matrix job."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sheets_factory.workbook.linear_capital_gurobi_reference import runtime


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('--model-a',required=True);q.add_argument('--model-b',required=True);q.add_argument('--output',required=True);q.add_argument('--seconds',type=int,default=3600);q.add_argument('--exclude-plan');q.add_argument('--warm-start');q.add_argument('--known-feasible-plans');q.add_argument('--scaling',choices=('none','integer_gcd'),default='none')
    q=sub.add_parser('validate');q.add_argument('--prepared',required=True)
    q=sub.add_parser('run');q.add_argument('--prepared',required=True);q.add_argument('--run',action='store_true',required=True)
    q=sub.add_parser('validate-completed');q.add_argument('--terminal',required=True)
    a=p.parse_args()
    def read(path):return None if path is None else runtime._read(path)
    if a.action=='prepare':r=runtime.prepare(a.model_a,a.model_b,a.output,time_limit_seconds=a.seconds,exclude_plan=read(a.exclude_plan),warm_start=read(a.warm_start),known_feasible_plans=read(a.known_feasible_plans),scaling=a.scaling)
    elif a.action=='validate':r={'kind':runtime.validate_prepared(a.prepared)['kind'],'passed':True,'solver_calls':0,'reference_admission':False}
    elif a.action=='run':r=runtime.execute_prepared(a.prepared)
    else:r={'kind':runtime.validate_completed(a.terminal)['kind'],'cold_validation_passed':True,'reference_admission':False}
    print(json.dumps(r),flush=True)


if __name__=='__main__':main()
