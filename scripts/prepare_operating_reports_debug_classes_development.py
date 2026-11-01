#!/usr/bin/env python3
"""Freeze a single whole-class debugging first attempt under native clock v6."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'scripts/prepare_operating_reports_200_development.py'
FROZEN_SHA='d6cd3b7aebedfb7aebe632217585951838eb28e0fe38d03fab4277fe47f0e6f3'
TASK=ROOT/'scripts/validate_operating_reports_debug_classes_tasks.py'
TASK_SHA='9021c1613f41efb13be3f300016886eed2cbd41a76e07a20015cb6efb9325f09'
ENVELOPE_SHA='de584267929f5d9f3d7abd71efb566a97b69aa191f7814266f6fd7a6eee5b95b'
SOURCE_SHA='beee954067fa061616a65b045ff176bc3e052726931f5788c93ea71deb032fca'
GOAL_SHA='5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'


def adapted_ast():
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest()!=FROZEN_SHA:
        raise ValueError('The frozen single-attempt v6 implementation changed')
    counts={'validator':0,'validator_sha':0,'engineering_hook':0,'main':0}
    class Adapt(ast.NodeTransformer):
        def visit_FunctionDef(self,node):
            if node.name=='_checked_engineering':counts['engineering_hook']+=1;return None
            return self.generic_visit(node)
        def visit_If(self,node):
            if ast.unparse(node.test)=="__name__ == '__main__'":counts['main']+=1;return None
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if type(node.value)is str:
                if node.value=='scripts/validate_operating_reports_200_tasks.py':
                    counts['validator']+=1;node.value='scripts/validate_operating_reports_debug_classes_tasks.py'
                elif node.value=='b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5':
                    counts['validator_sha']+=1;node.value=TASK_SHA
                else:
                    node.value=node.value.replace('fixed_hypothetical_operating_reports_200','hypothetical_operating_reports_200_debug_classes').replace('fixed_operating_reports_200','operating_reports_200_debug_classes').replace('operating-reports-200-','operating-reports-debug-classes-')
            return node
    tree=Adapt().visit(ast.parse(FROZEN.read_bytes()))
    if counts!={'validator':1,'validator_sha':1,'engineering_hook':1,'main':1}:
        raise ValueError('The exact single-mode v6 admission seams changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_N={'__name__':'_isolated_whole_class_DBG_first_v6','__file__':__file__}
exec(compile(adapted_ast(),__file__,'exec'),_N)
_N['MODES']=('debugging',)
_N['KIND']='prequality_operating_reports_200_debug_classes_single_development_v6'
_old_recipes=_N['recipes']


def _checked_engineering(value):
    driver=_N['validation_driver']();actual=driver.validate_completed(value)
    require,read=_N['require'],_N['read']
    require(actual['kind']=='complete_operating_reports_200_debug_classes_task_engineering'
        and actual['version']==1 and actual['passed'] is True
        and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==5
        and actual['qualified'] is actual['normal_all12_QA_passed'] is False
        and set(actual['records']['modes'])=={'debugging'},
        'Require the genuine complete five-call debugging engineering')
    frozen=read(actual['preparation']);mode=actual['records']['modes']['debugging']
    require(frozen['kind']=='prepared_operating_reports_200_debug_classes_task_engineering'
        and frozen['version']==1 and frozen['variant_id'] in ('S800','SG4000')
        and frozen['variant_envelope']['sha256']==ENVELOPE_SHA
        and frozen['source_manifest']==actual['source_manifest']
        and frozen['source_manifest']['sha256']==SOURCE_SHA
        and frozen['genuine_goal']==mode['goal'] and mode['goal']['sha256']==GOAL_SHA
        and _N['canonical'](read(frozen['specification']))==_N['_SPECIFICATION_SHA'],
        'Keep both predeclared variants, original source, raw assumptions and genuine goal')
    require(mode['complete_D_count']=={'S800':800,'SG4000':4000}[frozen['variant_id']]
        and mode['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
        and mode['instruction']==frozen['instruction_bytes']['debugging'],
        'Keep every declared fault, full modified-value set and all five actual controls')
    return actual,{'specification':frozen['specification'],
        'views':{'debugging':{'instruction':mode['instruction']}},
        'instructions':{'debugging':mode['instruction']}}


def recipes():
    _N['require'](len(TASK_SHA)==64,'Pin the final genuine whole-class task5 feature before any preparation')
    return {**_old_recipes(),str(FROZEN):_N['ref'](FROZEN)}


_N.update(_checked_engineering=_checked_engineering,recipes=recipes)
for _name,_value in _N.items():
    if not _name.startswith('__'):globals().setdefault(_name,_value)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--validation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('validate');p.add_argument('--prepared',type=Path,required=True)
    p=commands.add_parser('run-development');p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--mode',choices=['debugging'],required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    result=prepare(args.validation,args.output) if args.command=='prepare' else validate_prepared(args.prepared) if args.command=='validate' else run_development(args.prepared,args.mode,args.output,port=args.port)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
