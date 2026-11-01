#!/usr/bin/env python3
"""Append a strict SG4000 normal certificate without changing prior artifacts."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from types import FunctionType

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.pipelines.linear_capital_quality import References,reference,require
from sheets_factory.evaluation.resource_observer import validate_trial_observations
from sheets_factory.evaluation.resource_harbor import inspect_resource_export

FRONTEND=ROOT/'scripts/run_operating_reports_debug_classes_quality.py'
FRONTEND_SHA='3895a2a9d57df3a3db7728def1543e42657a1f2e826c547a69f2c9bf392e56c5'
NORMAL=ROOT/'outputs/research/SG4000_normal_quality_first_20261101T033000Z/prepared'
STRONG=ROOT/'outputs/difficulty/operating_reports_debug_SG4000_first_development_v6_20261101T023000Z/prepared/debugging_development_terminal.json'
STRONG_SHA='9457d853d6d7c5374963edd79266e7f0b1d3156bb2c1550b7763e0215e062088'
DEFECT=NORMAL.parent/'reporter_flat_goal_transport_failure/receipt.json'
DEFECT_SHA='893a55bc68027f6cd316e359ef2d0ef08e5e144ecf10fd7291daefc6886fb9fd'
require(reference(FRONTEND)['sha256']==FRONTEND_SHA,'The actual SG normal frontend changed')
loader=importlib.util.spec_from_file_location('_retained_SG_normal_verification',FRONTEND)
normal=importlib.util.module_from_spec(loader);loader.loader.exec_module(normal)


def read(record):
    return References().read(record)


def _bound_native_goal_digest(native,binding,base):
    """Only missing redundant metadata may use its exact original full REF."""
    expected=binding['goal_sha256']
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}',expected),'A complete bound goal digest is required')
    if 'goal_sha256' in native:
        require(type(native['goal_sha256']) is str and native['goal_sha256']==expected,
            'A present flat goal digest must match; nested evidence cannot override it')
    else:
        require('goal' in native,'A missing flat digest requires the exact full current goal reference')
    if 'goal' in native:
        full=native['goal'];path=References().check(full)
        require(path==Path(base).resolve()/'private/goal.xlsx' and full==reference(path)
            and full['sha256']==expected,'The nested goal reference is not the exact current material')
    return expected


def _reporter():
    namespace={**normal._reporting,'_bound_native_goal_digest':_bound_native_goal_digest}
    for name,function in tuple(namespace.items()):
        if isinstance(function,FunctionType) and function.__globals__ is normal._reporting:
            copied=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
            copied.__kwdefaults__=deepcopy(function.__kwdefaults__);namespace[name]=copied
    source=Path(normal.reporting.__file__)
    function=next(node for node in ast.parse(source.read_bytes()).body if isinstance(node,ast.FunctionDef) and node.name=='_reference_review')
    # Preserve the already-tested full-artifact/producer-compaction correction.
    original=ast.dump(ast.parse("private.get('reference_review_context') == context",mode='eval').body,include_attributes=False)
    getter=ast.dump(ast.parse("native.get('goal_sha256')",mode='eval').body,include_attributes=False)
    counts={'existing_complete_context':0,'missing_flat_goal_digest':0}
    class Bound(ast.NodeTransformer):
        def visit_Compare(self,node):
            if ast.dump(node,include_attributes=False)==original:
                counts['existing_complete_context']+=1
                return ast.copy_location(ast.parse('_bound_audited_context(evidence, private, context)',mode='eval').body,node)
            return self.generic_visit(node)
        def visit_Call(self,node):
            if ast.dump(node,include_attributes=False)==getter:
                counts['missing_flat_goal_digest']+=1
                return ast.copy_location(ast.parse('_bound_native_goal_digest(native, binding, base)',mode='eval').body,node)
            return self.generic_visit(node)
    function=Bound().visit(function)
    require(counts=={'existing_complete_context':1,'missing_flat_goal_digest':1},'The exact two isolated reporter transport seams changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(source),'exec'),namespace)
    return namespace,counts


_reporting,ADAPTATION_COUNTS=_reporter()
generate_report=_reporting['generate_report']


def _owned_absence(validations):
    owned={}
    for validation in validations:
        require(validation['passed'] is validation['complete'] is True and set(validation['roles_observed'])=={'agent','verifier'},
            'Both actual roles and complete pinned-image resource proof are required')
        for record in validation['observations']:
            observed=read(record);container=observed['container'];cid=container['Id']
            require(re.fullmatch('[0-9a-f]{64}',cid) and cid==observed['queried_container_id'], 'Only exact observed owned IDs may be queried')
            owned.setdefault(cid,{'full_id':cid,'role':observed['role'],'image':container['Image'],'ownership':record})
    daemon=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=20)
    require(daemon.returncode==0 and bool(daemon.stdout.strip()),'A reachable daemon is required; unknown cleanup is not passed')
    rows=[]
    for cid,owner in sorted(owned.items()):
        result=subprocess.run(['docker','inspect','--type','container',cid],capture_output=True,text=True,timeout=20)
        absent=result.returncode!=0 and cid in result.stderr and bool(re.search(r'no such (?:object|container)',result.stderr,re.I))
        require(absent,'An exact owned container remains present or its absence is unknown')
        rows.append({**owner,'absent':True,'read_only_inspection':True})
    return {'daemon_reachable':True,'all_owned_containers_absent':True,'owned':rows,
        'observed_at':datetime.now(timezone.utc).isoformat(),'no_containers_created_changed_or_removed':True}


def certify(output):
    out=Path(output).absolute();require(out==out.resolve() and not out.exists(),'Use one fresh real sibling certificate directory')
    out.mkdir(parents=True)
    write=lambda name,value:normal.write(out/name,value)
    require(reference(DEFECT)['sha256']==DEFECT_SHA and reference(STRONG)['sha256']==STRONG_SHA,'The original failure or first model changed')
    prospective=write('prospective.json',{'kind':'prospective_SG4000_missing_flat_goal_transport_verification','version':1,
        'implementation':reference(__file__),'frontend':reference(FRONTEND),'normal_preflight':reference(NORMAL/'preflight_manifest.json'),
        'retained_original_reporter_failure':reference(DEFECT),'first_model':reference(STRONG),
        'new_models':0,'new_LO_calls':0,'new_Harbor_jobs':0,'new_financial_forwards':0,'old_artifacts_or_statuses_mutated':False})
    before=reference(NORMAL/'run.sqlite')
    try:
        # This genuinely replays the current source/task proof; it starts no
        # engine and never recomputes either financial implementation.
        frozen,config,admissions=normal.validate_prepared(NORMAL)
        require(len(admissions)==1,'The one original SG4000 material is required')
        proof=normal.pipeline.admission(admissions[0])
        report=generate_report(NORMAL,project_root=ROOT)
        require(report['yield']['reported_qualified']==report['yield']['verified_qualified']==1
            and len(report['tasks'])==1 and report['tasks'][0]['reference_validation']['verified'] is True,
            'All original supported reference-review checks must remain decisive')
        report_ref=write('strict_reference_quality_report.json',report)
        task_id=report['tasks'][0]['task_id'];export=NORMAL/'SpreadsheetEval'/task_id
        binding=inspect_resource_export(export)
        require(sum(q.is_file() for q in export.rglob('*'))==17,'The complete original seventeen-file export is required')
        source=read(normal.pipeline.DEV_PROBE)['modes']['debugging'];joins={}
        for name,key in [('environment/input.xlsx','input'),('tests/original_input.xlsx','input'),
            ('solution/reference.xlsx','goal'),('tests/reference.xlsx','goal'),('instruction.md','rendered_instruction')]:
            actual=reference(export/name);wanted=source[key]
            require((actual['sha256'],actual['bytes'])==(wanted['sha256'],wanted['bytes']), 'The normal export differs from the original spent material')
            joins[name]={'normal':actual,'first_development':wanted}
        require(source['material_task_version']['sha256']==normal.pipeline.FIRST_MATERIAL
            and proof['input']==source['input'] and proof['goal']==source['goal']
            and proof['instruction']==source['rendered_instruction'],'The exact original material identity must remain unchanged')
        gate_ref=reference(NORMAL/'normal_actual_control_resource_gate.json');gate=read(gate_ref)
        require(gate['passed'] is True and gate['qualified_tasks_checked']==1 and gate['infrastructure_task_ids']==[],
            'The original actual Harbor resource gate must pass')
        require(len(gate['task_validations'])==1,'Exactly one normal task resource proof is required')
        resources=read(gate['task_validations'][0]);require(resources['passed'] is True,'The actual normal role resources failed')
        validations=[];roles={}
        for row in resources['trials']:
            agent=row['agent'];require(agent in ('oracle','nop') and agent not in roles,'One actual oracle and nop trial are required')
            result=read(row['result']);thin=read(row['config']);staged=Path(result['config']['task']['path'])
            require(normal._namespace['_trial_agent_identity'](thin,result,Path(row['config']['path']),staged,agent)==agent,
                'The thin/rich role identity differs')
            require(result['verifier_result']['rewards']['reward']==(1 if agent=='oracle' else 0)
                and inspect_resource_export(staged)==binding,'The actual role reward or complete staged export changed')
            checked=validate_trial_observations(row['config'],row['result'],receipts=[gate['observer']],
                expected_profile=normal.pipeline.PROFILE,expected_task_directory=staged)
            require(checked['passed'] is checked['complete'] is True,'An actual normal role lacks complete resource/ancestry evidence')
            roles[agent]={'result':row['result'],'config':row['config'],'reward':result['verifier_result']['rewards']['reward']}
            validations.append(checked)
        require(set(roles)=={'oracle','nop'},'Both actual normal roles are mandatory')
        strong=read(reference(STRONG));require(strong['score']['raw_verifier_reward']==strong['score']['effective_reward']==0
            and strong['resources']['passed'] is strong['resources']['complete'] is True and strong['outer_retries']==0,
            'The original valid zero and resource proof must remain unchanged')
        require(len(strong['resources']['trials'])==1,'Exactly one original strong model trial is required')
        trial=strong['resources']['trials'][0]
        strong_resources=validate_trial_observations(trial['trial_config'],trial['result'],
            receipts=strong['resources']['observation_receipts'],expected_profile=normal.pipeline.PROFILE)
        require(strong_resources['passed'] is strong_resources['complete'] is True,'The original strong roles need complete actual resource/image proof')
        validations.append(strong_resources)
        resource_ref=write('independently_rechecked_role_resources.json',{'normal':validations[:2],'first_strong':strong_resources})
        cleanup_ref=write('owned_container_absence.json',_owned_absence(validations))
        after=reference(NORMAL/'run.sqlite');require(before==after,'The original normal database changed')
        require(reference(STRONG)['sha256']==STRONG_SHA,'The original strong terminal changed')
        return write('certificate.json',{'kind':'append_only_verified_SG4000_normal_candidate','version':1,'passed':True,
            'prospective':prospective,'report':report_ref,'all12_original_supported':True,'Q08_not_applicable_by_original_reference_policy':True,
            'normal_resource_gate':gate_ref,'normal_roles':roles,'seventeen_file_export':binding,'same_material_byte_joins':joins,
            'original_first_model':reference(STRONG),'original_first_model_effective_reward':0,
            'independent_role_resources':resource_ref,'owned_cleanup':cleanup_ref,
            'genuine_current_admission':proof,'original_normal_database_before':before,'original_normal_database_after':after,
            'old_artifacts_statuses_and_scores_modified':False,'raw_first_model_repeated':False,
            'new_models':0,'new_LO_calls':0,'new_Harbor_jobs':0,'new_financial_forwards':0,
            'normal_candidate_evidence_complete':True,'formal_release_qualified':False,'whole20_confirmation_complete':False})
    except BaseException as error:
        write('failure.json',{'error_type':type(error).__name__,'error':str(error),'prospective':prospective,
            'old_artifacts_statuses_or_scores_modified':False,'new_service_calls':0,'qualified':False})
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args(argv)
    with normal.admission_monitor(args.output,'append_only_verify',declared_count=1) as state:
        result=certify(args.output);state['passed']=True
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
