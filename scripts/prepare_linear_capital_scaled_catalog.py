#!/usr/bin/env python3
"""Freeze a whole prospective N360 raw pool before financial execution."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_scaled import catalog, spec

DECLARATION_KIND = 'prospective_scaled_linear_raw_pool'
KIND = 'prepared_scaled_linear_complete_raw_pool'
RAW_KIND = 'prepared_linear_capital_scaled_raw_assumptions'
ZERO_FIELDS = ('financial_forward_implementation_calls','optimizer_calls','workbooks','LO_calls','model_calls','task_count')
PROPOSED_DECLARATION = {'kind':DECLARATION_KIND,'version':2,'count':20,
    'first_development_profile':'L360-P01',
    'profiles':[{'id':f'L360-P{i:02d}','seed':202701360+i,'revenue_jitter_pence':150000} for i in range(1,21)]}


def reference(path):
    path=Path(path).absolute()
    spec.require(path==path.resolve() and path.is_file() and not path.is_symlink(),'A real nonsymlink artifact is required')
    before=path.stat()
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    after=path.stat()
    spec.require((before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
        (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'Artifact changed during hashing')
    return {'path':str(path),'sha256':digest,'bytes':after.st_size}


def read(value):
    record=value if isinstance(value,dict) else reference(value)
    spec.require(reference(record['path'])==record,'An immutable artifact changed')
    return json.loads(Path(record['path']).read_text())


def write(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)


def validate_declaration(value):
    spec.require(type(value) is dict and set(value)=={'kind','version','count','first_development_profile','profiles'}
        and value['kind']==DECLARATION_KIND and type(value['version']) is int and value['version']==2
        and type(value['count']) is int and value['count']==20,'Declare the complete new twenty-profile pool')
    rows=value['profiles'];spec.require(type(rows) is list and len(rows)==20,'No prospective row may be omitted')
    ids=[];coordinates=[]
    for row in rows:
        spec.require(type(row) is dict and set(row)=={'id','seed','revenue_jitter_pence'}
            and type(row['id']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}',row['id'])
            and type(row['seed']) is int and 0<=row['seed']<2**32
            and type(row['revenue_jitter_pence']) is int and 0<=row['revenue_jitter_pence']<=catalog.MAX_REVENUE_JITTER_PENCE,
            'An explicit profile ID, bounded seed and revenue width are required')
        ids.append(row['id']);coordinates.append((row['seed'],row['revenue_jitter_pence']))
    spec.require(len(set(ids))==len(set(coordinates))==20 and value['first_development_profile']==ids[0],
        'Distinct profiles and the first development member must be fixed before generation')
    return deepcopy(value)


def recipes():
    paths=(Path(__file__),Path(catalog.__file__),Path(spec.__file__),spec.upstream_path())
    return {str(p.resolve()):reference(p)['sha256'] for p in paths}


def zero_claims(value):
    return value.get('qualified') is False and all(type(value.get(k)) is int and value[k]==0 for k in ZERO_FIELDS)


def prepare(output,declaration=None):
    declared=validate_declaration(deepcopy(PROPOSED_DECLARATION) if declaration is None else
        read(declaration) if isinstance(declaration,(str,Path)) else declaration)
    output=Path(output).absolute()
    spec.require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh raw pool directory and retain every previous candidate')
    output.mkdir(parents=True);recipe=recipes()
    declaration_ref=write(output/'declaration.json',declared)
    write(output/'started.json',{'created_at':datetime.now(timezone.utc).isoformat(),
        'declaration':declaration_ref,'recipe_sha256':recipe,'all_profiles_declared_before_generation':True,
        **{key:0 for key in ZERO_FIELDS},'qualified':False})
    try:
        publics={};specifications={}
        for row in declared['profiles']:
            pid=row['id'];public=catalog.build_competitive_spec(row['seed'],row['revenue_jitter_pence'])
            spec.require(public['dimension_mode']=='production' and len(public['project_ids'])==360,
                'Every declared source must retain the complete N360 scope')
            publics[pid]=public;(output/pid).mkdir()
            specifications[pid]=write(output/pid/'specification.json',public)
        preparations={};order=[r['id'] for r in declared['profiles']]
        for row in declared['profiles']:
            pid=row['id'];public=publics[pid];plans=catalog.diagnostic_plans(public,seed=row['seed'])
            spec.require(len(plans)==18 and len({p['id'] for p in plans})==18,'All eighteen fixed financial probes are required')
            preparations[pid]=write(output/pid/'preparation.json',{
                'kind':RAW_KIND,'version':2,'created_at':datetime.now(timezone.utc).isoformat(),
                'profile_id':pid,'seed':row['seed'],'revenue_jitter_pence':row['revenue_jitter_pence'],
                'specification':specifications[pid],'specification_sha256':spec.canonical_sha256(public),
                'declaration':declaration_ref,'prospective_profile_order':order,
                'all_specifications_frozen_before_finance':specifications,'recipe_sha256':recipe,
                'diagnostic_plans':plans,'selection_density_admission':{'minimum':120,'maximum':240,'public_cardinality_constraint':False},
                'capacity_design_uses_project_NPV_or_optimized_plan':False,
                **{key:0 for key in ZERO_FIELDS},'qualified':False})
        spec.require(recipe==recipes(),'The whole raw recipe changed during generation')
        return write(output/'catalog_manifest.json',{'kind':KIND,'version':2,'declaration':declaration_ref,
            'profile_order':order,'first_development_profile':declared['first_development_profile'],
            'profiles':[{'profile_id':r['id'],'seed':r['seed'],'revenue_jitter_pence':r['revenue_jitter_pence'],
                'specification':specifications[r['id']],'raw_preparation':preparations[r['id']]} for r in declared['profiles']],
            'all_profiles_frozen_before_financial_execution':True,'recipe_sha256':recipe,
            **{key:0 for key in ZERO_FIELDS},'qualified':False})
    except BaseException as error:
        write(output/'failure.json',{'error_type':type(error).__name__,'error':str(error),
            'all_partial_profiles_preserved':True,'selected_subset_produced':False,
            **{key:0 for key in ZERO_FIELDS},'qualified':False})
        raise


def validate_prepared(output):
    output=Path(output).resolve();manifest=read(output/'catalog_manifest.json')
    spec.require(manifest['kind']==KIND and type(manifest['version']) is int and manifest['version']==2
        and manifest['recipe_sha256']==recipes() and zero_claims(manifest)
        and manifest['all_profiles_frozen_before_financial_execution'] is True,'The complete zero-finance pool changed')
    declared=validate_declaration(read(manifest['declaration']));order=[r['id'] for r in declared['profiles']]
    spec.require(manifest['profile_order']==order and [r['profile_id'] for r in manifest['profiles']]==order
        and manifest['first_development_profile']==declared['first_development_profile'],'The full prospective order changed')
    specifications={r['profile_id']:r['specification'] for r in manifest['profiles']}
    for row,policy in zip(manifest['profiles'],declared['profiles']):
        public=spec.load_spec(read(row['specification']));raw=read(row['raw_preparation'])
        spec.require(raw['kind']==RAW_KIND and type(raw['version']) is int and raw['version']==2 and zero_claims(raw)
            and raw['profile_id']==row['profile_id']==policy['id'] and raw['seed']==row['seed']==policy['seed']
            and raw['revenue_jitter_pence']==row['revenue_jitter_pence']==policy['revenue_jitter_pence']
            and raw['specification']==row['specification'] and raw['specification_sha256']==spec.canonical_sha256(public)
            and raw['declaration']==manifest['declaration'] and raw['recipe_sha256']==manifest['recipe_sha256']
            and raw['all_specifications_frozen_before_finance']==specifications and raw['prospective_profile_order']==order
            and public['dimension_mode']=='production' and len(public['project_ids'])==360
            and raw['diagnostic_plans']==catalog.diagnostic_plans(public,seed=policy['seed']),
            'A complete raw profile, width, financial-free recipe or fixed plan inventory changed')
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path);parser.add_argument('--declaration',type=Path)
    parser.add_argument('--validate',type=Path);parser.add_argument('--print-proposal',action='store_true')
    args=parser.parse_args(argv)
    if args.print_proposal:
        spec.require(not any((args.output,args.declaration,args.validate)),'Choose one explicit action')
        print(json.dumps(validate_declaration(PROPOSED_DECLARATION),indent=2));return 0
    if args.validate:
        spec.require(not any((args.output,args.declaration)),'Choose validation or a fresh pool')
        validate_prepared(args.validate);print(json.dumps({'validated':str(args.validate),'financial_calls':0}));return 0
    spec.require(args.output is not None,'Provide a fresh output directory')
    print(json.dumps(prepare(args.output,args.declaration)));return 0


if __name__=='__main__':raise SystemExit(main())
