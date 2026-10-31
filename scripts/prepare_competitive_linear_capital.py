#!/usr/bin/env python3
"""Freeze both competitive raw profiles together before financial execution."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_portfolio import catalog, catalog_competitive, catalog_correlated, spec

KIND = 'prepared_linear_capital_competitive_raw_pair'


def reference(path):
    p=Path(path).resolve(strict=True);h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024**2),b''):h.update(block)
    return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}


def write(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    return reference(path)


def recipes():
    return {str(p.resolve()):reference(p)['sha256'] for p in (Path(__file__),Path(catalog_competitive.__file__),
        Path(catalog_correlated.__file__),Path(catalog.__file__),Path(spec.__file__),ROOT/'docs/linear_capital_portfolio_contract.md')}


def prepare(output):
    output=Path(output).absolute()
    spec.require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh real output directory; preserve prior profiles')
    recipe=recipes();public={p:catalog_competitive.build_spec(p) for p in catalog_competitive.PROFILE_ORDER}
    output.mkdir(parents=True)
    specifications={}
    for profile in catalog_competitive.PROFILE_ORDER:
        folder=output/profile;folder.mkdir()
        specifications[profile]=write(folder/'specification.json',public[profile])
    preparations={}
    for profile in catalog_competitive.PROFILE_ORDER:
        policy=catalog_competitive.PROFILES[profile];raw=public[profile]
        preparations[profile]=write(output/profile/'preparation.json',{
            'kind':'prepared_linear_240_project_raw_assumptions','version':1,
            'created_at':datetime.now(timezone.utc).isoformat(),'profile_id':profile,'seed':policy['seed'],
            'specification':specifications[profile],'specification_sha256':spec.canonical_sha256(raw),
            'recipe_sha256':recipe,'prospective_profile_order':list(catalog_competitive.PROFILE_ORDER),
            'paired_specifications_frozen_before_finance':specifications,
            'raw_assumption_policy':policy,
            'selection_density_admission':{'minimum':80,'maximum':160,'public_cardinality_constraint':False},
            'diagnostic_plans':catalog.diagnostic_plans(raw,seed=policy['seed']),
            'reference_policy':{'independent_financial_implementations':['Fraction_A','Decimal_B'],
                'all_candidate_scenarios_must_be_feasible':True,
                'all_financial_fields_and_reduced_coefficients_must_agree':True,
                'best_and_excluded_winner_runner_must_be_OPTIMAL':True,
                'unique_posted_objective_gap_at_least_pence':1,
                'solver_status_is_not_independently_verified_formal_proof':True},
            'capacity_design_uses_project_NPV_or_optimized_plan':False,
            'financial_forward_implementation_calls':0,'optimizer_calls':0,'workbooks':0,'LO_calls':0,
            'model_calls':0,'qualified':False,'task_count':0})
    spec.require(recipe==recipes(),'The raw recipe changed during generation')
    return write(output/'catalog_manifest.json',{'kind':KIND,'version':1,
        'created_at':datetime.now(timezone.utc).isoformat(),'profile_order':list(catalog_competitive.PROFILE_ORDER),
        'profiles':[{ 'profile_id':p,'specification':specifications[p],'raw_preparation':preparations[p],
            'assumption_policy':catalog_competitive.PROFILES[p]} for p in catalog_competitive.PROFILE_ORDER],
        'recipe_sha256':recipe,'both_profiles_frozen_before_financial_execution':True,
        'financial_forward_implementation_calls':0,'optimizer_calls':0,'workbooks':0,'LO_calls':0,
        'model_calls':0,'qualified':False,'task_count':0})


def validate_prepared(output):
    output=Path(output).resolve(strict=True);manifest=json.loads((output/'catalog_manifest.json').read_text())
    spec.require(manifest['kind']==KIND and type(manifest['version']) is int and manifest['version']==1
        and manifest['profile_order']==list(catalog_competitive.PROFILE_ORDER)
        and manifest['recipe_sha256']==recipes() and manifest['both_profiles_frozen_before_financial_execution'] is True,
        'The complete paired raw catalog changed')
    spec.require([r['profile_id'] for r in manifest['profiles']]==list(catalog_competitive.PROFILE_ORDER),
        'Neither prospective profile may be omitted or reordered')
    specs={r['profile_id']:r['specification'] for r in manifest['profiles']}
    for row in manifest['profiles']:
        profile=row['profile_id'];policy=catalog_competitive.PROFILES[profile]
        for key in ('specification','raw_preparation'):
            spec.require(reference(row[key]['path'])==row[key],'A frozen raw artifact changed')
        public=spec.load_spec(row['specification']['path']);raw=json.loads(Path(row['raw_preparation']['path']).read_text())
        spec.require(raw['kind']=='prepared_linear_240_project_raw_assumptions' and raw['profile_id']==profile
            and raw['seed']==policy['seed'] and raw['raw_assumption_policy']==row['assumption_policy']==policy
            and raw['specification']==row['specification'] and raw['specification_sha256']==spec.canonical_sha256(public)
            and raw['recipe_sha256']==manifest['recipe_sha256'] and raw['paired_specifications_frozen_before_finance']==specs
            and raw['prospective_profile_order']==manifest['profile_order']
            and raw['diagnostic_plans']==catalog.diagnostic_plans(public,seed=policy['seed']),
            'A complete raw source, policy or diagnostic plan inventory changed')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.output)))
