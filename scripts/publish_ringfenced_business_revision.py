#!/usr/bin/env python3
"""Stage immutable mixed materials, install with rollback, and certify evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
from dirhash import dirhash
from sheets_factory.evaluation.mixed_business_resources import inspect_resource_export
from sheets_factory.evaluation import mixed_business_resource_observer as observer
ENTRY = ROOT/'scripts/run_ringfenced_replacement_confirmation.py'
ENTRY_SHA = 'bde7c4963159ddeb5c7e11b3bd62dde992753d9c447b2e61583755dd6feaa04f'
CONTROLS = ROOT/'scripts/run_mixed_business_root_harbor_controls.py'
CONTROLS_SHA = '7d9849963ec89df2531d17668511ea20f534457b4efdbe4cdf228d4e027ca802'
REVIEW = ROOT/'scripts/run_ringfenced_shared_quality_review.py'
REVIEW_SHA = 'ffd81d0d48ba76c6d4ec699e0b7f05c24b0401c44d9c3f551592a31b099e6d66'
NATIVE_HELPER = ROOT/'scripts/resume_ringfenced_pair_task8_remaining_revision2.py'
NATIVE_HELPER_SHA = '8a5c88d53f80dfdbff9936f50c40257cbec71759d2747871cf1e852943c6f145'
BASELINE = ROOT/'outputs/research/business_revision_prototype_usage_baseline_20261101T083200Z/receipt.json'
BASELINE_SHA = '11dab8f0b6fa5196c5363403c47c5133a48d9165e77abde66cff5a8d99d67c5e'
MODES = {'financial_modeling': 10, 'debugging': 10}
GATE = {'version': 1, 'fixed_new_pairs': ['R2-01','R2-02','R2-03','R2-04','R2-05'],
    'fixed_retained_count': 10, 'new_confirmation_count': 10, 'combined_count': 20,
    'combined_primary_pass_at_1_max': '0.2', 'combined_conservative_nonboundary_pass_at_1_max': '0.2',
    'new_wave_pass_at_1_max_reported_separately': '0.2',
    'verified_cumulative_tool_budget_failure_reward': 0, 'strict_tool_seconds': 1800,
    'tool_clock_excludes_model_response': True, 'tool_parallel_time_is_sum': True,
    'complete_raw_one_reward': 1, 'pure_reporting_boolean_or_numeric_rounding_zero_conservative_reward': 1,
    'other_proven_business_value_or_coverage_failure_conservative_reward': 0,
    'unknown_evidence': 'HOLD', 'historical_results_retested_or_rescored': False,
    'twenty_fresh_attempts_claimed': False, 'selection_after_confirmation': False}


def require(value, message):
    if not value: raise ValueError(message)


def ref(path):
    p = Path(path).absolute()
    require(p == p.resolve() and p.is_file() and not p.is_symlink(), 'An exact real immutable evidence file is required')
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024**2), b''): h.update(chunk)
    return {'path': str(p), 'sha256': h.hexdigest(), 'bytes': p.stat().st_size}


def checked(value):
    record = ref(value) if not isinstance(value, dict) else value
    actual = ref(ROOT/record['path'] if not Path(record['path']).is_absolute() else record['path'])
    require(actual['sha256'] == record['sha256'] and actual['bytes'] == record['bytes'], 'A bound evidence artifact changed')
    return actual


def read(value): return json.loads(Path(checked(value)['path']).read_text())


def write(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as stream: json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return ref(p)


def load(path, digest, name):
    require(ref(path)['sha256'] == digest, 'A frozen release dependency changed')
    spec = importlib.util.spec_from_file_location(name, path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def entry(): return load(ENTRY, ENTRY_SHA, '_ring_business_release_confirmation')


@lru_cache(maxsize=1)
def controls(): return load(CONTROLS, CONTROLS_SHA, '_ring_business_release_controls').namespace


@lru_cache(maxsize=1)
def native_helper(): return load(NATIVE_HELPER,NATIVE_HELPER_SHA,'_ring_business_release_native_proof').v1


def recipes():
    for path,digest in ((ENTRY,ENTRY_SHA),(CONTROLS,CONTROLS_SHA),(REVIEW,REVIEW_SHA)):
        require(ref(path)['sha256']==digest,'A frozen release entry changed')
    return {'publisher': ref(__file__), 'confirmation': checked(ENTRY), 'controls': checked(CONTROLS),
        'shared_review': checked(REVIEW), 'native_receipt_checker': checked(NATIVE_HELPER),
        'mixed_inspector': ref(sys.modules[inspect_resource_export.__module__].__file__),
        'mixed_observer': ref(observer.__file__)}


@contextmanager
def root_lock(root):
    folder=Path(root)/'outputs';folder.mkdir(exist_ok=True)
    with (folder/'.ringfenced_business_publication.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def inventory(dataset):
    dataset = Path(dataset).absolute(); require(dataset == dataset.resolve() and dataset.is_dir(), 'Use a real complete dataset directory')
    manifest_ref = ref(dataset/'dataset_manifest.json'); manifest = read(manifest_ref); ids = manifest['selected_task_ids']
    require(manifest['task_count'] == 20 and len(ids) == len(set(ids)) == 20
        and {r['task_id'] for r in manifest['tasks']} == set(ids)
        and dict(Counter(r['mode'] for r in manifest['tasks'])) == manifest['counts_by_mode'] == MODES,
        'Require all twenty fixed tasks, ten in each mode')
    require({p.name for p in dataset.iterdir()} == set(ids)|{'dataset_manifest.json'}, 'The complete root inventory changed')
    files = {}; bindings = {}
    for task in manifest['tasks']:
        name = task['task_id']; require(Path(name).name == name and name not in ('.','..'), 'A task ID cannot escape the dataset')
        folder = dataset/name
        require(folder.is_dir() and not any(p.is_symlink() for p in folder.rglob('*')), 'Symlink payloads are forbidden')
        actual = {str(p.relative_to(folder)): ref(p)['sha256'] for p in sorted(folder.rglob('*')) if p.is_file()}
        require(set(actual) == controls()['FILES'] and actual == task['payload_files'], 'All seventeen exact task files are required')
        binding = inspect_resource_export(folder)
        require(binding == task['harbor_export_binding'], 'A complete resource export binding changed')
        files[name] = actual; bindings[name] = binding
    return {'manifest': manifest_ref, 'payload_files': files, 'bindings': bindings, 'task_ids': ids, 'counts_by_mode': MODES}


def inventory_key(value):
    return {**value, 'manifest': {k:v for k,v in value['manifest'].items() if k != 'path'}}


def prepared_immutable(record):
    """Bind the completed full identity witnesses; never replay workbook identity."""
    value=read(record);e=entry()
    require(value['kind']==e.KIND and value['phase']=='confirmation' and value['recipe']==e.recipes()
        and value['selection_frozen_before_model'] is True and value['attempts_per_task']==1
        and value['model']=='gpt-6.1-sol' and value['reasoning_effort']=='xhigh' and value['outer_retries']==0,
        'Use the unchanged completed prospective native preparation')
    batches,tasks,retained=e.cohort_tasks(value['batches'])
    require(tasks==value['tasks'] and retained==value['retained_results'] and len(value['logical_proofs'])==5,
        'The fixed five pairs or retained ten changed')
    materials={};inventories={};seen=[]
    for proof_ref in value['logical_proofs']:
        proof=read(proof_ref)
        require(proof['kind']=='completed_replacement_pair_logical_identity_v1' and proof['recipe']==value['recipe']
            and proof['original_full_identity_algorithm'] is True and proof['model_LO_solver_calls']==0,
            'A complete original logical-identity execution is missing')
        materials.update(proof['materials']);inventories.update(proof['export_files']);seen+=proof['tasks']
    require(len(seen)==len(set(seen))==10 and set(seen)=={t['task_id'] for t in tasks}
        and materials==value['materials'] and inventories==value['export_files'],'The full completed identity inventory differs')
    for task in tasks:
        payload=inventories[task['task_id']]
        require(set(payload)==controls()['FILES'],'All seventeen frozen payload files are required')
        for name,item in payload.items():
            require(checked(item)==ref(Path(task['task_directory'])/name),'A frozen material byte changed')
        core={k:v for k,v in materials[task['task_id']].items() if k!='sha256'}
        require(e.p.canonical(core)==materials[task['task_id']]['sha256'],'The complete logical identity hash changed')
    return value


def stage(prepared, output, *, root=ROOT):
    root = Path(root).absolute(); out = Path(output).absolute()
    require(root == root.resolve() and out == out.resolve() and out.is_relative_to(root/'outputs') and not out.exists(), 'Use a fresh owned staging directory')
    out.mkdir(parents=True)
    with entry().p._N['monitor'](out/'monitor', 'stage_fixed_twenty') as audit, root_lock(root):
        before = recipes(); prepared_ref = checked(prepared); f = prepared_immutable(prepared_ref)
        require(prepared_ref == ref(Path(prepared_ref['path']).parent/'prepared.json') and f['kind'] == entry().KIND,
            'Use the exact prospectively frozen ten-task confirmation preparation')
        require(not (Path(prepared_ref['path']).parent/'terminal.json').exists(), 'Stage the fixed cohort before confirmation results exist')
        old = inventory(root/'SpreadsheetEval'); old_manifest = read(old['manifest']); history = read(f['retained_results'])
        require(history['task_count'] == 10 and history['original_results_preserved'] is True
            and history['original_material_bytes_verified'] is True and history['materials_recalculated_or_rescored'] is False
            and old['manifest']['sha256'] == history['original_root_dataset_manifest']['sha256'], 'Preserve the complete original twenty and retained history')
        old_rows = {t['task_id']: t for t in old_manifest['tasks']}; tasks = []
        for retained in history['tasks']:
            name = retained['task_id']; row = old_rows[name]
            require(row['payload_files'] == retained['payload_files'] and row['mode'] == retained['mode']
                and row['revision_hash'] == retained['revision_hash'], 'A retained material differs from its immutable history')
            require(dirhash(root/'SpreadsheetEval'/name, 'sha256') == retained['original_release_result']['task_checksum'], 'A retained task checksum changed')
            tasks.append(deepcopy(row))
        require(len(tasks) == 10 and Counter(t['mode'] for t in tasks) == Counter({'financial_modeling':5,'debugging':5}), 'Retain exactly five tasks per mode')
        for task in f['tasks']:
            tasks.append({k: deepcopy(task[k]) for k in ('task_id','mode','variant_id','revision','revision_hash','harbor_export_binding')})
            tasks[-1]['payload_files'] = {k:v['sha256'] for k,v in f['export_files'][task['task_id']].items()}
        require(len({t['task_id'] for t in tasks}) == 20 and dict(Counter(t['mode'] for t in tasks)) == MODES, 'No aliases, omissions or post-result selection')
        # Keep an exact whole-dataset snapshot. It is never used as a new score.
        shutil.copytree(root/'SpreadsheetEval', out/'previous_SpreadsheetEval')
        previous = inventory(out/'previous_SpreadsheetEval')
        require(inventory_key(previous) == inventory_key(old), 'The original whole twenty snapshot differs')
        new = out/'SpreadsheetEval'; new.mkdir()
        old_ids = set(old_rows)
        new_by_id = {t['task_id']: t for t in f['tasks']}
        for row in tasks:
            source = root/'SpreadsheetEval'/row['task_id'] if row['task_id'] in old_ids else Path(new_by_id[row['task_id']]['task_directory'])
            shutil.copytree(source, new/row['task_id']); audit.task(row['task_id'], mode=row['mode'], status='staged'); audit.export()
        manifest = write(new/'dataset_manifest.json', {'kind':'frozen_ringfenced_business_revision_dataset','version':1,
            'task_count':20,'counts_by_mode':MODES,'selected_task_ids':[t['task_id'] for t in tasks],
            'cohort_freeze':prepared_ref,'retained_history':f['retained_results'],'goal_workbook_count':6,
            'source_provenance':{'retained_shared_goal_count':1,'new_composed_goal_count':5,'retained_local_source_donor_count':6,
                'independent_public_dataset_count_claimed':False}, 'selection_uses_confirmation_results':False,
            'qualification_report_is_external':True,'tasks':tasks})
        staged = inventory(new)
        require(recipes() == before, 'The staging implementation changed')
        result = write(out/'staged.json', {'kind':'staged_fixed_ringfenced_business_revision','version':1,
            'prepared':prepared_ref,'batches':f['batches'],'retained_history':f['retained_results'],
            'previous_inventory':old,'previous_snapshot':previous,'staged_inventory':staged,'gate':GATE,
            'recipe':before,'root':str(root),'owned_output':str(out),'qualified':False,
            'all_twenty_bytes_frozen':True,'confirmation_results_used_for_selection':False})
        audit.update_run(status='completed',stage='staged_not_installed',task_count=20)
        return result


def install(staged, *, root=ROOT):
    root = Path(root).absolute(); staged_ref = checked(staged); value = read(staged_ref); out = Path(value['owned_output'])
    require(value['kind'] == 'staged_fixed_ringfenced_business_revision' and value['root'] == str(root)
        and out.is_relative_to(root/'outputs') and value['recipe'] == recipes() and value['gate'] == GATE,
        'Use the unchanged owned staging transaction')
    with entry().p._N['monitor'](out/'install_monitor','install_fixed_twenty') as audit, root_lock(root):
        require(not (out/'install_started.json').exists() and not (out/'installed.json').exists()
            and not (out/'displaced_original_SpreadsheetEval').exists(), 'Never repeat an installation attempt')
        require(inventory_key(inventory(root/'SpreadsheetEval')) == inventory_key(value['previous_inventory'])
            and inventory_key(inventory(out/'previous_SpreadsheetEval')) == inventory_key(value['previous_snapshot'])
            and inventory(out/'SpreadsheetEval') == value['staged_inventory'], 'A source, backup or staged task changed')
        write(out/'install_started.json', {'staged':staged_ref,'at':datetime.now(timezone.utc).isoformat(),'qualified':False})
        displaced = out/'displaced_original_SpreadsheetEval'; moved = False
        try:
            os.replace(root/'SpreadsheetEval', displaced); moved = True
            os.replace(out/'SpreadsheetEval', root/'SpreadsheetEval')
            actual = inventory(root/'SpreadsheetEval')
            require(inventory_key(actual) == inventory_key(value['staged_inventory']), 'The installed fixed cohort differs')
        except BaseException as error:
            rollback_error=None;restored=False
            try:
                if moved:
                    if (root/'SpreadsheetEval').exists(): os.replace(root/'SpreadsheetEval', out/'failed_candidate_SpreadsheetEval')
                    os.replace(displaced, root/'SpreadsheetEval')
                restored=inventory_key(inventory(root/'SpreadsheetEval'))==inventory_key(value['previous_inventory'])
            except BaseException as secondary:
                rollback_error={'type':type(secondary).__name__,'error':str(secondary)}
            write(out/'install_failure.json', {'error_type':type(error).__name__,'error':str(error),
                'original_root_restored':restored,'rollback_error':rollback_error,'qualified':False})
            raise
        result = write(out/'installed.json', {'kind':'installed_fixed_ringfenced_business_revision','version':1,'staged':staged_ref,
            'dataset_inventory':actual,'previous_snapshot':value['previous_snapshot'],'displaced_original':str(displaced),
            'qualified':False,'manifest_bytes_remain_constant':True,'raw_scores_modified':False})
        audit.update_run(status='completed',stage='installed_controls_and_confirmation_pending'); return result


def effective(row):
    a = row['actual_attempt']; clock = a.get('tool_time') or {}; raw = a.get('raw_verifier_reward',a.get('reward'))
    require(row['resources'].get('passed') is row['resources'].get('complete') is True and a.get('status') == 'scored', 'HOLD: an actual resource or native result is incomplete')
    require(clock.get('budget_seconds')==1800 and clock.get('strict_less_than') is True
        and clock.get('model_response_time_included') is False and clock.get('parallel_executions')=='sum',
        'HOLD: the tool clock does not implement the declared strict sum policy')
    exact=clock.get('cumulative_tool_seconds');lower=exact if exact is not None else clock.get('cumulative_lower_bound_seconds')
    upper=exact if exact is not None else clock.get('cumulative_upper_bound_seconds')
    if a.get('failure_kind') == 'cumulative_tool_budget_exhausted' and clock.get('passed') is False:
        require(lower is not None and Decimal(str(lower))>=1800,'HOLD: budget exhaustion lacks a verified lower bound')
        reward, state = 0, 'known_tool_budget_failure'
    elif not a.get('failure_kind') and clock.get('passed') is True and type(raw) in (int,float) and raw in (0,1):
        require(upper is not None and Decimal(str(upper))<1800,'HOLD: completion lacks a strict tool-time upper bound')
        reward, state = raw, 'complete'
    else: raise ValueError('HOLD: unknown timing, infrastructure or incomplete native evidence')
    require(row['score']['effective_reward'] == reward and row['score']['state'] == state, 'The native primary score cannot be rewritten')
    return reward, state, raw


def conservative(row, analysis=None):
    primary, state, raw = effective(row)
    if state == 'known_tool_budget_failure': return 0, 'verified_tool_budget_failure'
    if raw == 1: return 1, 'complete_primary_success'
    require(analysis is not None, 'HOLD: a complete primary zero needs nonboundary or technical-only evidence')
    a = read(analysis); attempt = row['actual_attempt']; result = Path(attempt['result_file'])
    diagnostic = ref(result.parent/'verifier/diagnostics.json'); d = read(diagnostic)
    require(a['kind'] == 'native_confirmation_nonboundary_analysis_v1' and a['task_id'] == row['task_id']
        and a['result_sha256'] == attempt['result_sha256'] and a['diagnostics'] == diagnostic
        and a['complete'] is True and a.get('evidence') and d['reward'] == 0, 'HOLD: nonboundary evidence is incomplete or belongs to another result')
    for evidence in a['evidence']: checked(evidence)
    points = set(d.get('missing_changes',[])) | set(d.get('extra_changes',[])) | set(d.get('wrong_values',[]))
    differences = a.get('differences',[]); kind = a['classification']
    if kind == 'pure_reporting_boolean_only':
        require(points == {'Group reporting!B6'} and len(differences) == 1
            and differences[0]['coordinate'] == 'Group reporting!B6' and differences[0]['expected_type'] == 'boolean'
            and differences[0]['expected'] is True and differences[0]['actual_type'] == 'number'
            and type(differences[0]['actual']) in (int,float) and differences[0]['actual'] == 1,
            'HOLD: the sole numeric-one versus true reporting discrepancy is not established')
        return 1, kind
    if kind == 'pure_numeric_rounding_only':
        require(points and {v['coordinate'] for v in differences} == points and len(differences) == len(points), 'HOLD: complete rounding coverage is missing')
        require(all(v['expected_type'] == v['actual_type'] == 'number' and type(v['expected']) is not bool and type(v['actual']) is not bool
            and Decimal(0) < abs(Decimal(str(v['expected']))-Decimal(str(v['actual']))) <= Decimal('0.01') for v in differences), 'HOLD: a mismatch exceeds the conservative numeric boundary allowance')
        return 1, kind
    require(kind in ('material_business_value_failure','coverage_failure') and points,
        'HOLD: a business/value/coverage failure has no concrete native mismatch')
    require(any(v['coordinate'] in points and v['coordinate'] != 'Group reporting!B6' and
        (v.get('actual_type') in ('missing','invalid') or
         v.get('expected_type') == v.get('actual_type') == 'number' and abs(Decimal(str(v['expected']))-Decimal(str(v['actual']))) > Decimal('0.01'))
        for v in differences), 'HOLD: no witnessed nonboundary business value or coverage error')
    return 0, kind


def gate_rows(rows):
    require(len(rows)==20 and len({r['task_id'] for r in rows})==20 and dict(Counter(r['mode'] for r in rows))==MODES,
        'The release gate must use the unchanged whole twenty')
    require(Counter(r['scope'] for r in rows)==Counter({'retained_historical':10,'new_confirmation':10})
        and all(type(r['primary_reward']) in (int,float) and r['primary_reward'] in (0,1)
            and type(r['conservative_reward']) in (int,float) and r['conservative_reward'] in (0,1)
            and r['conservative_reward']>=r['primary_reward'] for r in rows),'The historical/new scopes or conservative binary rewards changed')
    primary = sum(r['primary_reward'] for r in rows); cautious = sum(r['conservative_reward'] for r in rows)
    return {'primary_successes':primary,'primary_overall_pass_at_1':primary/20,
        'conservative_nonboundary_successes':cautious,'conservative_nonboundary_overall_pass_at_1':cautious/20,
        'passed':primary<=4 and cautious<=4,'new_wave_primary_pass_at_1':sum(r['primary_reward'] for r in rows if r['scope']=='new_confirmation')/10,
        'new_wave_own_point_two_gate_passed':sum(r['primary_reward'] for r in rows if r['scope']=='new_confirmation')<=2}


def usage(attempts):
    result={'calls':len(attempts),'input_tokens':0,'output_tokens':0,'cached_input_tokens':0,'unknown_usage_calls':0}
    for a in attempts:
        r=a.get('agent_result') or {}; known=all(type(r.get(k)) is int for k in ('n_input_tokens','n_output_tokens'))
        result['unknown_usage_calls']+=not known
        for source,target in (('n_input_tokens','input_tokens'),('n_output_tokens','output_tokens'),('n_cache_tokens','cached_input_tokens')):
            if type(r.get(source)) is int: result[target]+=r[source]
    result['reported_total_tokens']=result['input_tokens']+result['output_tokens'];result['provider_paid_USD']=None
    return result


def validate_controls(record, dataset, ids):
    value=read(record);require(value['kind']=='complete_exact_twenty_root_controls' and value['passed'] is True
        and value['dataset_manifest']==dataset['manifest'] and value['oracle_all20_reward']==1 and value['nop_all20_reward']==0
        and value['actual_role_resources_checked'] is True,'HOLD: exact installed-root controls are missing')
    for role,reward in (('oracle',1),('nop',0)):
        command=read(value['command_receipts'][role]);audit=read(command['whole_job_audit']);resources=read(command['actual_resources'])
        require(command['argv']==['harbor','run','-p','SpreadsheetEval','-a',role] and command['cwd']==str(ROOT)
            and command['returncode']==0 and command['dataset_manifest']==dataset['manifest'] and audit['status']=='passed'
            and len(audit['trials'])==20 and {r['task_id'] for r in audit['trials']}==set(ids)
            and all(r['reward']==reward for r in audit['trials']),'HOLD: the whole actual root command is incomplete')
        require(resources['passed'] is True and len(resources['validations'])==20
            and all(v['passed'] is v['complete'] is True for v in resources['validations'])
            and resources['owned_cleanup']['all_owned_containers_absent'] is True
            and resources['owned_cleanup']['daemon_reachable'] is True
            and all(v['absent'] is True for v in resources['owned_cleanup']['owned']), 'HOLD: actual role resources or owned cleanup are unknown')
        for trial in audit['trials']:
            result=Path(trial['result_file'])
            proof=observer.validate_trial_observations(result.with_name('config.json'),result,
                receipts=command['resource_observation_receipts'],expected_task_directory=ROOT/'SpreadsheetEval'/trial['task_id'])
            require(proof['passed'] is proof['complete'] is True,'HOLD: actual mixed-role observations do not bind the installed payload')
    return value


def validate_quality(review_ref, prepared):
    require(ref(REVIEW)['sha256']==REVIEW_SHA,'The frozen shared-review entry changed')
    review=read(review_ref)
    require(review['kind']=='actual_five_ringfenced_pairs_shared_quality_review_v1' and review['shared_semantic_passed'] is True
        and review['ordinary_review_resources_passed'] is True and not review['failures'] and review['outer_retries']==0
        and set(review['all_enabled_check_ids'])=={f'Q{i:02d}' for i in range(1,13)}
        and {t['task_id'] for t in review['tasks']}=={t['task_id'] for t in prepared['tasks']},'HOLD: all-five shared semantic review is incomplete')
    dispatch=read(review['dispatch']);rp=read(dispatch['prepared'])
    require(rp['implementation']==ref(REVIEW) and rp['cohort_entry']==ref(ENTRY) and rp['all_five_pairs_in_both_role_views'] is True
        and rp['model']=='gpt-6-sol' and rp['reasoning_effort']=='high' and rp['model_calls_permitted']==4,
        'HOLD: the actual shared-review dispatch differs')
    require(len(review['ordinary_review_resources'])==len(review['ordinary_review_native_calls'])==4,'HOLD: four real review calls are required')
    for mode in MODES:
        value=review['modes'][mode]
        require(set(value['assessments'])==set(review['all_enabled_check_ids'])
            and all(value['assessments'][k]['state']=='clear' for k in ('Q01','Q02','Q03','Q04','Q07'))
            and value['assessments']['Q08']['state'] in ('clear','not_applicable')
            and not any(v.get('severity')=='blocker' for v in value['issues']), 'HOLD: a shared semantic or answer-exposure issue is unresolved')
    for record in review['ordinary_review_resources']:
        require(read(record)['passed'] is True,'HOLD: ordinary review resources are incomplete')
    for record in review['ordinary_review_native_calls']:
        call=read(record);require(call['status']=='completed' and call['model']=='gpt-6-sol' and call['reasoning_effort']=='high'
            and call['isolated'] is True,'HOLD: review model/visibility differs')
    return review


def engineering(prepared):
    proofs=[]
    for task in prepared['tasks']:
        value=read(task['individual_engineering']);require(value['passed'] is True and value['native_error_count']==0
            and value['given_literals_unchanged'] is value['sheet_structure_unchanged'] is True
            and value['full_source_formula_count']==2494958 and value['full_physical_union_count']==3547571
            and value['complete_primary_difference_count']==len(value['complete_primary_difference'])>0,
            'HOLD: full actual input/goal D or public facts/structure proof is incomplete')
        if task['mode']=='financial_modeling':require(value['complete_primary_difference_count']==3044678,'HOLD: FM full scope differs')
        source=read(value['source']);sf=read(source['preparation']);require(source['passed'] is True and source['LO_calls']==3
            and source['actual_calls_started']==source['actual_calls_completed']==3
            and source['source']['sha256']==task['source_id'],'HOLD: the exact complete source3 differs')
        native_ids=[];previous=sf['cold_start']
        for call in source['actual_calls']:
            require(call['input']==previous and call['completed'] is True,'HOLD: actual source3 calculation chain changed')
            proof=native_helper().resource_check(call['actual_resource_evidence']['terminal'],source=call['input'],output=call['output'])
            native_ids.append(proof['container_id']);previous=call['output']
        require(len(native_ids)==len(set(native_ids))==3 and previous==source['source'],'HOLD: the goal is not the actual third capped source result')
        for i in (1,2,3):
            a=read(source['records'][f'source{i}_audit']);require(a['passed'] and a['cells_checked']==3547571
                and a['formulas_checked']==2494958 and a['native_error_count']==a['mismatch_count']==0
                and a['provided_literals_exact'],'HOLD: an actual full source financial/fact audit is incomplete')
        for i in (1,2):
            a=read(source['records'][f'source{i}_to_source{i+1}']);require(a.get('passed') is True or a.get('reward')==1,
                'HOLD: complete native source stability is missing')
        cleanup=read(source['records']['cleanup']);require(cleanup['all_owned_containers_absent'] and all(r['absent'] for r in cleanup['owned']),
            'HOLD: owned source cleanup is unknown')
        require({r.get('container_id',r.get('full_id')) for r in cleanup['owned']}==set(native_ids),'HOLD: cleanup does not cover exact source owners')
        if 'native_call' in value:
            receipts=[value['native_call']['native_resource_receipt']]
        else:receipts=[r['receipt'] for r in value['actual_resources']]
        input_sha=task['harbor_export_binding']['resource_runtime']['source_artifacts']['input']['sha256']
        matching=[r for r in receipts if read(r).get('output',{}).get('sha256')==input_sha]
        require(matching,'HOLD: the individual input is not a completed actual native result')
        for record in matching:native_helper().resource_check(record)
        proofs.append({'task_id':task['task_id'],'individual_engineering':task['individual_engineering'],'source':value['source'],
            'D':value['complete_primary_difference_count'],'cell_styles_unchanged':value.get('cell_styles_unchanged'),
            'cell_style_scope':'measured' if value.get('cell_styles_unchanged') is True else 'not separately measured; primary values/D and facts/structure are checked'})
    return proofs


def finalize(installed, confirmation, review, actual_controls, output, *, analyses=(), development=()):
    installed_ref=checked(installed);installed_value=read(installed_ref);staged=read(installed_value['staged']);dataset=inventory(ROOT/'SpreadsheetEval')
    require(installed_value['kind']=='installed_fixed_ringfenced_business_revision' and staged['gate']==GATE and staged['recipe']==recipes()
        and dataset==installed_value['dataset_inventory'],'HOLD: the fixed installed twenty or gate changed')
    prepared=read(staged['prepared']);terminal=read(confirmation)
    require(terminal['kind']==entry().TERMINAL_KIND and terminal['phase']=='confirmation' and terminal['outer_retries']==0
        and terminal['prepared']==staged['prepared'],'HOLD: use the genuine fixed ten-task first confirmation')
    selection=read(terminal['selection']);evaluation=read(terminal['evaluation'])
    require(selection['model']==evaluation['model']=='gpt-6.1-sol' and selection['reasoning_effort']==evaluation['reasoning_effort']=='xhigh'
        and selection['phase']=='confirmation' and selection['n_attempts']==1 and selection['tool_time_policy_version']==6
        and not evaluation.get('infrastructure_retries'),'HOLD: native model, clock or retry contract differs')
    actual_resources=observer.validate_observation_receipt(Path(terminal['evaluation']['path']).parent,selection,evaluation)
    require(actual_resources['passed'] is actual_resources['complete'] is True and actual_resources==read(terminal['resources']),
        'HOLD: actual mixed-family confirmation resources are incomplete')
    actual={r['task_id']:r for r in terminal['results']};wanted={t['task_id']:t for t in prepared['tasks']}
    require(len(terminal['results'])==len(actual)==10 and set(actual)==set(wanted),'HOLD: confirm all fixed new ten exactly once')
    analysis_by_id={read(r)['task_id']:r for r in analyses};require(len(analysis_by_id)==len(analyses),'Duplicate failure evidence')
    rows=[]
    for task_id,task in wanted.items():
        r=actual[task_id];a=r['actual_attempt'];require(r['material_identity']==prepared['materials'][task_id]
            and a['harbor_export_binding']==task['harbor_export_binding']
            and a['task_checksum']==dirhash(ROOT/'SpreadsheetEval'/task_id,'sha256')
            and ref(a['result_file'])['sha256']==a['result_sha256'],'HOLD: actual confirmed bytes or logical material differs')
        primary,state,raw=effective(r);cautious,reason=conservative(r,analysis_by_id.get(task_id))
        rows.append({'task_id':task_id,'mode':task['mode'],'variant_id':task['variant_id'],'scope':'new_confirmation',
            'primary_reward':primary,'original_raw_reward':raw,'score_state':state,'conservative_reward':cautious,
            'conservative_reason':reason,'tool_time':a['tool_time'],'result_sha256':a['result_sha256'],
            'material_identity':r['material_identity'],'task_checksum':a['task_checksum']})
    retained=read(staged['retained_history']);previous=read(retained['previous_release']);old={r['task_id']:r for r in previous['tasks']}
    for task in retained['tasks']:
        result=task['original_release_result'];failure=task['original_failure_analysis']
        require(result==old[task['task_id']] and result['reward']==result['raw_verifier_reward']==0 and result['state']=='complete'
            and failure['boundary_only'] is False and failure['resources_passed'] is failure['tool_time_passed'] is True
            and failure['actual_result']['sha256']==result['result_sha256'],'HOLD: preserve the original proven nonboundary ten and scores')
        checked(failure['actual_result']);checked(failure['diagnostics'])
        rows.append({'task_id':task['task_id'],'mode':task['mode'],'variant_id':task['variant_id'],'scope':'retained_historical',
            'primary_reward':0,'original_raw_reward':0,'conservative_reward':0,'conservative_reason':'retained_observed_material_associate_income_error',
            'original_release_result':result,'original_failure_analysis':failure})
    gates=gate_rows(rows);require(gates['passed'],'The fixed combined primary or conservative pass rate exceeds 0.2; keep the whole failed cohort')
    quality=validate_quality(review,prepared);individual=engineering(prepared);validate_controls(actual_controls,dataset,dataset['task_ids'])
    require(ref(BASELINE)['sha256']==BASELINE_SHA,'The known prototype usage receipt changed')
    baseline=read(BASELINE);dev=[]
    require(baseline['kind']=='actual_business_revision_prototype_usage_baseline' and baseline['call_count']==len(baseline['calls'])==14
        and baseline['total_tokens']==baseline['input_tokens']+baseline['output_tokens']
        and baseline['total_tokens']==sum(c['total_tokens'] for c in baseline['calls']), 'The actual prototype usage baseline is inconsistent')
    for call in baseline['calls']:checked(call['actual_result'])
    for record in development:
        value=read(record);require(value['phase']=='development','Keep development usage separate from confirmation')
        dev += [r['actual_attempt'] for r in value['results'] if r.get('actual_attempt')]
    unique={}
    for attempt in dev:
        require(attempt.get('result_sha256') and ref(attempt['result_file'])['sha256']==attempt['result_sha256'],'Development usage must bind an actual result')
        unique.setdefault(attempt['result_sha256'],attempt)
    dev=list(unique.values())
    consumption={'prototype_baseline':ref(BASELINE),'prototype_baseline_reported_tokens':baseline['total_tokens'],
        'R2_development':usage(dev),'new_confirmation':usage([r['actual_attempt'] for r in terminal['results']]),
        'shared_semantic_review':quality['usage'],'paid_USD':None,'paid_USD_status':'not available; reported tokens are not invoices'}
    consumption['known_reported_total_tokens']=baseline['total_tokens']+consumption['R2_development']['reported_total_tokens']+consumption['new_confirmation']['reported_total_tokens']+quality['usage']['total_tokens']
    consumption['model_calls']=baseline['call_count']+consumption['R2_development']['calls']+consumption['new_confirmation']['calls']+quality['usage']['llm_calls']
    consumption['unknown_usage_calls']=baseline['unknown_usage_calls']+consumption['R2_development']['unknown_usage_calls']+consumption['new_confirmation']['unknown_usage_calls']+quality['usage']['unknown_usage_calls']
    result={'kind':'qualified_ringfenced_business_revision_release','version':1,'created_at':datetime.now(timezone.utc).isoformat(),
        'qualified':True,'task_count':20,'counts_by_mode':MODES,'gate':GATE,'gate_result':gates,'tasks':rows,
        'historical_retained_count':10,'fresh_new_confirmation_count':10,'twenty_fresh_attempts_claimed':False,
        'retained_scores_modified':False,'dataset_manifest':dataset['manifest'],'installed':installed_ref,
        'confirmation':checked(confirmation),'shared_quality':checked(review),'actual_root_controls':checked(actual_controls),
        'individual_engineering':individual,'quality_all12_enabled':True,
        'quality_evidence_join':{f'Q{i:02d}':{'state':'clear' if i!=8 else 'not_applicable',
            'evidence':[checked(review),checked(actual_controls),checked(confirmation),staged['prepared']]} for i in range(1,13)},
        'conversion':{'prior_candidate_scope':40,'retained_from_prior':10,'new_revision_prototype_materials':8,
            'new_ringfenced_materials':10,'new_revision_candidates':18,'qualified_new':10,'qualified_new_conversion':10/18},
        'source_provenance':{'retained_shared_goal_count':1,'new_composed_goal_count':5,'retained_local_source_donor_count':6,
            'independent_public_dataset_count_claimed':False},'consumption':consumption,'recipe':recipes()}
    return write(output,result)


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('stage');a.add_argument('--prepared',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a=s.add_parser('install');a.add_argument('--staged',type=Path,required=True)
    a=s.add_parser('finalize')
    for key in ('installed','confirmation','review','actual-controls','output'):a.add_argument('--'+key,type=Path,required=True)
    a.add_argument('--analysis',action='append',type=Path,default=[]);a.add_argument('--development',action='append',type=Path,default=[])
    a=p.parse_args()
    if a.command=='stage':result=stage(a.prepared,a.output)
    elif a.command=='install':result=install(a.staged)
    else:result=finalize(a.installed,a.confirmation,a.review,a.actual_controls,a.output,analyses=a.analysis,development=a.development)
    print(json.dumps(result))


if __name__=='__main__':main()
