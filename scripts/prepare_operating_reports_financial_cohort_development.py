#!/usr/bin/env python3
"""Freeze one predeclared new FM case for a single native clock-v6 attempt."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'scripts/prepare_operating_reports_200_development.py'
FROZEN_SHA='d6cd3b7aebedfb7aebe632217585951838eb28e0fe38d03fab4277fe47f0e6f3'
TASK=ROOT/'scripts/validate_operating_reports_financial_cohort_tasks.py'
TASK_SHA='8188d2add6e96660f8b7401114d4d6af6bc46ffd6f01647971daa50eefd77b91'
RAW_INVENTORY_SHA='941f0eb27291d1a84c1980797d969355a14a8476604a8cec6d77b707b007345d'
BRIEF_SHA='5d9f8922d806cb3d25ef8bca7355b5061dda372d39da8cc453168ca96894f077'
SCHEMA=ROOT/'src/sheets_factory/workbook/operating_reports_financial_cohort_v1/schema.py'
SCHEMA_SHA='cf5732f4e2a8a17ec3d9e339791c3f372ed04a22665815951c79f6a31ed53be4'
CASE_IDS=tuple('FM-C'+str(i).zfill(2) for i in range(1,10))


def adapted_ast():
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest()!=FROZEN_SHA:
        raise ValueError('The frozen single-attempt v6 implementation changed')
    counts={'validator':0,'validator_sha':0,'engineering_hook':0,'pair_dispatch':0,'main':0}
    class Adapt(ast.NodeTransformer):
        def visit_FunctionDef(self,node):
            if node.name=='_checked_engineering':counts['engineering_hook']+=1;return None
            if node.name=='run_pair':counts['pair_dispatch']+=1;return None
            return self.generic_visit(node)
        def visit_If(self,node):
            if ast.unparse(node.test)=="__name__ == '__main__'":counts['main']+=1;return None
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if type(node.value)is str:
                if node.value=='scripts/validate_operating_reports_200_tasks.py':
                    counts['validator']+=1;node.value='scripts/validate_operating_reports_financial_cohort_tasks.py'
                elif node.value=='b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5':
                    counts['validator_sha']+=1;node.value=TASK_SHA
                else:
                    node.value=node.value.replace('fixed_hypothetical_operating_reports_200','hypothetical_operating_reports_financial_cohort_v1').replace('fixed_operating_reports_200','operating_reports_financial_cohort').replace('operating-reports-200-','operating-reports-financial-cohort-')
            return node
    tree=Adapt().visit(ast.parse(FROZEN.read_bytes()))
    if counts!={'validator':1,'validator_sha':1,'engineering_hook':1,'pair_dispatch':1,'main':1}:
        raise ValueError('The exact single-mode v6 admission seams changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_N={'__name__':'_isolated_financial_cohort_FM_first_v6','__file__':__file__}
exec(compile(adapted_ast(),__file__,'exec'),_N)
_N['MODES']=('financial_modeling',)
_N['KIND']='prequality_operating_reports_financial_cohort_single_development_v6'
_old_recipes=_N['recipes']
from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema,raw


def _checked_engineering(value):
    require,read,checked=_N['require'],_N['read'],_N['checked']
    require(_N['ref'](SCHEMA)['sha256']==SCHEMA_SHA,'The frozen real cohort schema changed')
    driver=_N['validation_driver']();actual=driver.validate_completed(value)
    require(actual['kind']=='complete_operating_reports_financial_cohort_FM_task_engineering'
        and actual['version']==1 and actual['passed'] is True
        and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==5
        and actual['source_LO_calls_reused']==3
        and actual['qualified'] is actual['normal_all12_QA_passed'] is actual['difficulty_claimed'] is False
        and set(actual['records']['modes'])=={'financial_modeling'},
        'Require genuine complete five-call new-cohort FM engineering')
    frozen=read(actual['preparation']);public=read(frozen['specification']);schema.validate_spec(public)
    identity=schema.candidate(public['seed'])['candidate_id']
    require(identity in CASE_IDS and public['dimension_mode']=='production'
        and frozen['kind']=='prepared_operating_reports_financial_cohort_FM_task_engineering'
        and frozen['version']==1 and frozen['case_id']==identity
        and frozen['mode_order']==['financial_modeling']
        and frozen['independent_business_field_count']==93510 and frozen['formula_count']==88676
        and frozen['financial_target_count']==frozen['forecast_mask_count']==62322 and frozen['report_NA_count']==4834,
        'Only the nine predeclared real new raw cases and complete FM scope are allowed')
    require(frozen['raw_inventory']['sha256']==RAW_INVENTORY_SHA,'The original jointly frozen all-nine raw inventory changed')
    inventory=raw.validate_all(frozen['raw_inventory'])
    require(set(inventory['specifications'])==set(CASE_IDS) and inventory['specifications'][identity]==public,
        'The current complete public specification differs from its original all-nine raw case')
    source=read(actual['source_manifest']);sf=read(frozen['source_preparation']);candidate=read(frozen['candidate_preparation'])
    require(source['kind']=='independently_checked_operating_reports_financial_cohort_source_v1'
        and source['version']==1 and source['passed'] is True and source['actual_LO_calls_started']==source['actual_LO_calls_completed']==3
        and source['preparation']==frozen['source_preparation'] and source['source']==frozen['genuine_goal']
        and source['source']==source['actual_calls'][-1]['output']
        and source['specification']==sf['specification']==frozen['specification']
        and checked(candidate['specification']).read_bytes()==checked(frozen['specification']).read_bytes()
        and sf['case_id']==candidate['candidate_id']==identity and sf['raw_inventory']==frozen['raw_inventory']
        and sf['candidate_manifest']==frozen['candidate_preparation']
        and candidate['kind']=='prepared_unverified_operating_reports_financial_cohort_fm_emission' and candidate['version']==1,
        'Keep the genuine current-case source3, raw facts and uncalculated emission lineage')
    mode=actual['records']['modes']['financial_modeling'];brief=mode['instruction'];brief_path=checked(brief)
    require(mode['goal']==frozen['genuine_goal'] and mode['complete_D_count']==62322
        and mode['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
        and mode['instruction']==frozen['instruction_bytes']['financial_modeling']
        and brief['bytes']==403 and brief['sha256']==BRIEF_SHA and len(brief_path.read_bytes())==403
        and checked(candidate['views']['financial_modeling']['instruction']).read_bytes()==brief_path.read_bytes(),
        'Keep all forecast outputs, five controls and the exact original 403-byte business brief')
    return actual,{'specification':frozen['specification'],'views':{'financial_modeling':{'instruction':brief}},
        'instructions':{'financial_modeling':brief}}


def recipes():
    _N['require'](_N['ref'](SCHEMA)['sha256']==SCHEMA_SHA,'The frozen real cohort schema changed')
    return {**_old_recipes(),**schema.recipes(),str(FROZEN):_N['ref'](FROZEN)}


_N.update(_checked_engineering=_checked_engineering,recipes=recipes)
for _name,_value in _N.items():
    if not _name.startswith('__'):globals().setdefault(_name,_value)


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--validation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('validate');p.add_argument('--prepared',type=Path,required=True)
    p=commands.add_parser('run-development');p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--mode',choices=['financial_modeling'],required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    result=prepare(args.validation,args.output) if args.command=='prepare' else validate_prepared(args.prepared) if args.command=='validate' else run_development(args.prepared,args.mode,args.output,port=args.port)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
