#!/usr/bin/env python3
"""Freeze one raw 240-project scenario; do not calculate finance or optimize."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_portfolio import catalog,spec


def reference(path):
    p=Path(path).resolve(strict=True)
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}


def prepare(output,*,seed=catalog.SEED):
    output=Path(output).absolute()
    spec.require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh output directory and preserve all prior primitives')
    raw=catalog.build_spec(seed)
    recipes={str(p.resolve()):reference(p)['sha256'] for p in (
        Path(__file__),Path(catalog.__file__),Path(spec.__file__),ROOT/'docs/linear_capital_portfolio_contract.md')}
    output.mkdir(parents=True)
    source=output/'specification.json'
    with source.open('x') as stream:json.dump(raw,stream,ensure_ascii=False,indent=2);stream.write('\n')
    record={'kind':'prepared_linear_240_project_raw_assumptions','version':1,
        'created_at':datetime.now(timezone.utc).isoformat(),'profile_id':catalog.PROFILE_ID,
        'seed':seed,'specification':reference(source),'specification_sha256':spec.canonical_sha256(raw),
        'recipe_sha256':recipes,'selection_density_admission':{'minimum':80,'maximum':160,'public_cardinality_constraint':False},
        'diagnostic_plans':catalog.diagnostic_plans(raw,seed=seed),
        'reference_policy':{'independent_financial_implementations':['Fraction_A','Decimal_B'],
            'all_candidate_scenarios_must_be_feasible':True,'all_financial_fields_and_reduced_coefficients_must_agree':True,
            'best_and_excluded_winner_runner_must_be_OPTIMAL':True,'unique_posted_objective_gap_at_least_pence':1,
            'solver_status_is_not_independently_verified_formal_proof':True},
        'capacity_design_uses_project_NPV_or_optimized_plan':False,
        'financial_forward_implementation_calls':0,'optimizer_calls':0,'workbooks':0,'LO_calls':0,
        'model_calls':0,'qualified':False,'task_count':0}
    path=output/'preparation.json'
    with path.open('x') as stream:json.dump(record,stream,ensure_ascii=False,indent=2);stream.write('\n')
    return reference(path)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=catalog.SEED);args=parser.parse_args()
    print(json.dumps(prepare(args.output,seed=args.seed)))
