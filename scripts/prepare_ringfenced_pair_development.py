#!/usr/bin/env python3
"""Freeze both genuine R2-01 views for independent single native-v6 attempts."""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'scripts/prepare_operating_reports_200_development.py'
FROZEN_SHA='d6cd3b7aebedfb7aebe632217585951838eb28e0fe38d03fab4277fe47f0e6f3'
TASK=ROOT/'scripts/validate_ringfenced_pair_tasks_revision2.py'
TASK_SHA='f84955cff53e4d62a01da7956ab670192d5301b27b9cc269a14400e6cc020a9a'
PROFILE=ROOT/'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
PROFILE_SHA='20fc02fec3aaf4918ece50d18ef9e315ffee9fccce088863f044ebac301a026a'
SOURCE_KIND='completed_two_ringfenced_pair_source_same_process_session_revision3'
COUNTS={'sheets':741,'formulas':2494958,'targets':3044678,'nonempty':3547571,
        'choices':720,'DBG_formula_roots':172800}
PAIR_ID='R2-01'


def adapted_ast():
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest()!=FROZEN_SHA:
        raise ValueError('The frozen two-mode single-attempt v6 implementation changed')
    substitutions={
        'scripts/validate_operating_reports_200_tasks.py':str(TASK.relative_to(ROOT)),
        'b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5':TASK_SHA,
        'prequality_fixed_operating_reports_200_development_pair_v6':'prequality_ringfenced_capital_pair_development_v6',
        'fixed_hypothetical_operating_reports_200':'synthetic_two_ringfenced_capital_mandates',
        'fixed_operating_reports_200_prequality_development_source_v6':'ringfenced_capital_pair_prequality_development_source_v6',
        'prequality_fixed_operating_reports_200_native_first_attempt_terminal_v6':'prequality_ringfenced_capital_pair_native_first_attempt_terminal_v6',
        'fixed_operating_reports_200_permanent_material_first_attempt_reservation_v6':'ringfenced_capital_pair_permanent_material_first_attempt_reservation_v6',
        'operating-reports-200-':'ringfenced-capital-pair-',
        'fixed200_two_process_first_attempt_dispatch_v6':'ringfenced_capital_pair_two_process_first_attempt_dispatch_v6',
        'fixed200_two_process_dispatch_terminal_v6':'ringfenced_capital_pair_two_process_dispatch_terminal_v6',
    }
    counts={key:0 for key in substitutions};removed={'engineering_hook':0,'old_specification_hash':0,'main_call':0}
    class Adapt(ast.NodeTransformer):
        def visit_FunctionDef(self,node):
            if node.name=='_checked_engineering':removed['engineering_hook']+=1;return None
            return self.generic_visit(node)
        def visit_Assign(self,node):
            if [ast.unparse(t)for t in node.targets]==['_SPECIFICATION_SHA']:
                removed['old_specification_hash']+=1;return None
            return self.generic_visit(node)
        def visit_If(self,node):
            if ast.unparse(node.test)=="__name__ == '__main__'":removed['main_call']+=1;return None
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if type(node.value)is str and node.value in substitutions:
                counts[node.value]+=1;node.value=substitutions[node.value]
            return node
    tree=Adapt().visit(ast.parse(FROZEN.read_bytes()))
    expected={key:2 if key=='fixed_operating_reports_200_permanent_material_first_attempt_reservation_v6'else 1 for key in substitutions}
    if counts!=expected or removed!=dict.fromkeys(removed,1):
        raise ValueError('The exact pair family/provider adaptation sites changed: '+str((counts,removed)))
    return ast.fix_missing_locations(tree)


_N={'__name__':'_isolated_ringfenced_capital_pair_first_v6','__file__':__file__}
exec(compile(adapted_ast(),__file__,'exec'),_N)
_N.update(PROFILE=PROFILE,__doc__=__doc__)
_old_recipes=_N['recipes']
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer


def _checked_engineering(value):
    require,read,checked=_N['require'],_N['read'],_N['checked']
    driver=_N['validation_driver']();actual=driver.validate_completed(value)
    require(actual['kind']=='complete_ringfenced_pair_task_engineering_revision2'
        and type(actual['version'])is int and actual['version']==1 and actual['passed']is True
        and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==8
        and actual['source_LO_calls_reused']==3
        and actual['qualified']is actual['normal_all12_QA_passed']is actual['difficulty_claimed']is False
        and set(actual['records']['modes'])==set(_N['MODES']),
        'Require genuine complete R3-source/R2-task eight-call pair engineering')
    frozen=read(actual['preparation']);source=read(actual['source_manifest']);sf=read(frozen['source_preparation'])
    require(frozen['kind']=='prepared_complete_ringfenced_pair_task_engineering_revision2'
        and type(frozen['version'])is int and frozen['version']==1 and frozen['pair_id']==PAIR_ID
        and frozen['source_manifest']==actual['source_manifest']
        and frozen['mode_order']==list(_N['MODES']) and frozen['required_actual_LO_calls']==8
        and frozen['financial_target_count']==COUNTS['targets'] and frozen['source_formula_count']==COUNTS['formulas']
        and frozen['DBG_formula_root_count']==COUNTS['DBG_formula_roots'] and frozen['provisional_choice_count']==720
        and frozen['all720choices_and_two_completion_gates_masked']is True
        and frozen['candidate_preparation']==frozen['whole_views_contract'],
        'Keep the complete fixed R2-01 masks, faults, choices and both completion gates')
    require(source['kind']==SOURCE_KIND and type(source['version'])is int and source['version']==1
        and source['passed']is True and source['actual_calls_started']==source['actual_calls_completed']==source['LO_calls']==3
        and source['preparation']==frozen['source_preparation'] and source['source']==frozen['genuine_goal']
        and source['source']==source['actual_calls'][-1]['output']
        and sf['geometry']=={k:COUNTS[k]for k in ('formulas','nonempty','targets')}
        and sf['runtime_profile']==frozen['runtime_profile'] and sf['runtime_profile_value']==frozen['runtime_profile_value']
        and checked(frozen['runtime_profile'])==PROFILE and frozen['runtime_profile']['sha256']==PROFILE_SHA,
        'Keep the genuine whole-source3 output and unchanged two-CPU pair resource profile')
    public_ref=sf['public_contract'];public=read(public_ref);certificate=read(sf['certificate'])
    require(public['kind']=='synthetic_two_ringfenced_capital_mandates' and public['version']==1 and public['pair_id']==PAIR_ID
        and public['group_projects']==720 and public['group_local_integer_rows']==1882
        and public['local_projects']==360 and public['local_integer_rows']==941
        and [(row['id'],row['local_profile_id'])for row in public['mandates']]==[('M01','L360-P01'),('M02','L360-P02')]
        and public['coupled_720_project_MIP_claimed']is False
        and certificate['kind']=='cold_composed_two_ringfenced_capital_best_runner_certificate'
        and certificate['version']==1 and certificate['pair_id']==PAIR_ID and certificate['contract']==public_ref,
        'Bind the actual separate-mandate business contract and original whole certificates')
    briefs={}
    for mode in _N['MODES']:
        material=actual['records']['modes'][mode];brief=frozen['instruction_bytes'][mode]
        require(material['goal']==frozen['genuine_goal'] and material['instruction']==brief
            and material['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
            and type(material['complete_D_count'])is int and material['complete_D_count']>0
            and (mode!='financial_modeling'or material['complete_D_count']==COUNTS['targets'])
            and checked(brief).read_text()==(driver.views.FM_BRIEF if mode=='financial_modeling'else driver.views.DBG_BRIEF),
            'Keep both original public requests and genuine full-D/five-control evidence')
        briefs[mode]=brief
    return actual,{'specification':public_ref,'views':{mode:{'instruction':brief}for mode,brief in briefs.items()},'instructions':briefs}


def recipes():
    _N['require'](_N['ref'](PROFILE)['sha256']==PROFILE_SHA,'The frozen pair geometry/resource profile changed')
    return {**_old_recipes(),str(FROZEN):_N['ref'](FROZEN)}


_N.update(_checked_engineering=_checked_engineering,recipes=recipes)
for _name,_value in _N.items():
    if not _name.startswith('__'):globals().setdefault(_name,_value)


@contextmanager
def admission_monitor(phase):
    """Keep a separate fresh panel active before the first cold provider read."""
    folder=ROOT/'outputs/research/ringfenced_pair_development_monitors'/uuid4().hex
    audit=AuditStore(folder,{'id':folder.name,'name':'Ringfenced pair first native-v6 admission',
        'status':'running','phase':phase,'producer_pid':os.getpid(),'producer_active':True,'qualified':False})
    server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0)
    stop=threading.Event();started=time.monotonic();pulse=None;passed=False
    def heartbeat():
        while not stop.wait(15):audit.update_run(elapsed_seconds=time.monotonic()-started);audit.export()
    try:
        url=server.start();audit.update_run(dashboard_url=url);audit.export()
        print(json.dumps({'admission_dashboard_url':url,'phase':phase,'producer_pid':os.getpid()}),flush=True)
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        yield
        passed=True
    finally:
        stop.set()
        if pulse:pulse.join(timeout=1)
        audit.update_run(status='completed'if passed else'failed',producer_active=False,elapsed_seconds=time.monotonic()-started)
        audit.export();server.stop();audit.db.close()


def main():
    if any(value in sys.argv[1:]for value in ('-h','--help')):return _N['main']()
    with admission_monitor(sys.argv[1]if len(sys.argv)>1 else'arguments'):
        return _N['main']()


if __name__=='__main__':raise SystemExit(main())
