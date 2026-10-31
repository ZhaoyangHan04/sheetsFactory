#!/usr/bin/env python3
"""Prepare or explicitly run one P01 unseeded HiGHS engineering screen."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_scaled import highs_runtime, highs_engineering, reference as reference_support

KIND = 'fixed_L360_P01_scaled_highs2_early_answer_engineering'
FINANCE_ROOT = ROOT/'outputs/research/linear_scaled_N360_finance_actual_20261031T121400Z'
INVENTORY = FINANCE_ROOT/'completed_finance_inventory.json'
P01_TERMINAL_SHA256 = '58afc16298b4bc65aaf3bf04da5a80b4bdad046a584b30fb8cffbb98a7c47209'
P01_MODEL_SHA256 = '4eb747bc7a4f05f6c14f1806aae1a04484da29f2e1d25e5879398355848e4559'
P01_SPECIFICATION_SHA256 = '4a0a18552b265017e161193db2897eeedfcb8eda409cee7fa95d06051263169c'
PROFILE_ORDER = ['L360-P'+str(index).zfill(2) for index in range(1,21)]
TINY_ROOT = ROOT/'outputs/research/linear_scaled_N360_tiny_transport_revision2_actual_20261031T122700Z'
TINY_MODEL_SHA256 = 'a8d24c4a94187bc35d2eaf7f9addf1a021ceb76fa90b44e6dc3d5c76fed4f06d'
TINY_PARENT_SHA256 = '931c6f1ac6abcd6079d5c7b254ceaa37dcb31036d5175117a372f585199c7fa2'
TINY_KIND = 'fixed_scaled_highs2_three_project_api_smoke'


def require(value, message):
    if not value: raise ValueError(message)


def reference(path): return reference_support.reference(path)
def read(value): return reference_support.read(value)
def write(path, value): return reference_support.write(path, value)


def recipes():
    files = [Path(__file__), Path(highs_runtime.__file__), highs_runtime.UPSTREAM,
        *highs_runtime._source_files().values(), Path(reference_support.__file__),
        ROOT/'src/sheets_factory/core/audit.py', ROOT/'src/sheets_factory/dashboard/__init__.py',
        ROOT/'src/sheets_factory/dashboard/server.py', ROOT/'src/sheets_factory/resume.py']
    return {str(path.resolve()): reference(path) for path in files}


def checked_input():
    inventory_ref = reference(INVENTORY); inventory = read(inventory_ref)
    require(inventory.get('kind') == 'completed_scaled_linear_finance_terminal_inventory'
        and type(inventory.get('version')) is int and inventory['version'] == 2
        and inventory.get('profile_order') == PROFILE_ORDER
        and [row['profile_id'] for row in inventory['profiles']] == PROFILE_ORDER,
        'The complete fixed twenty-profile finance inventory is required')
    terminal_ref = inventory['profiles'][0]['terminal']
    require(terminal_ref == reference(FINANCE_ROOT/'L360-P01/terminal.json')
        and terminal_ref['sha256'] == P01_TERMINAL_SHA256, 'Use only the completed frozen L360-P01 finance evidence')
    reference_support._checked_finance(terminal_ref)
    terminal = read(terminal_ref)
    require(terminal['model_B']['sha256'] == P01_MODEL_SHA256
        and terminal['specification']['sha256'] == P01_SPECIFICATION_SHA256,
        'The P01 specification or canonical integer model changed')
    model = read(terminal['model_B']); highs_engineering.validate_model(model)
    require(len(model['project_ids']) == 360 and len(model['rows']) == 941,
        'The P01 screen requires every production project and original business row')
    return inventory_ref, terminal_ref, terminal, model


def prepare(output, *, vendor_lock, dependency_probe, tiny_prepared):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real screen preparation directory')
    inventory_ref, terminal_ref, terminal, model = checked_input()
    runtime = highs_runtime.build_runtime(vendor_lock, dependency_probe)
    tiny, _, _ = checked_tiny_prospective(tiny_prepared)
    require(tiny['vendor_lock'] == runtime.dependency_lock and tiny['dependency_import_probe'] == runtime.dependency_probe,
        'The API smoke and P01 screen must use the same frozen dependency bytes')
    output.mkdir(parents=True)
    try:
        native = runtime.prepare(terminal['model_B']['path'], output/'native')
        ancestry = {key: terminal[key] for key in ('specification','raw_preparation','universe_A','universe_B',
            'model_A','model_B','complete_financial_comparison','all_predeclared_plan_comparison','complete_matrix_comparison')}
        prospective = {'kind': 'prepared_'+KIND, 'version': 1, 'profile_id': 'L360-P01',
            'finance_inventory': inventory_ref, 'finance_terminal': terminal_ref, 'ancestry': ancestry,
            'recipe': recipes(), 'native_preparation': native, 'vendor_lock': runtime.dependency_lock,
            'required_tiny_prospective':reference(Path(tiny_prepared)/'prospective.json'),
            'required_tiny_terminal_path':str(Path(tiny_prepared).resolve()/'tiny_terminal.json'),
            'dependency_import_probe': runtime.dependency_probe, 'dependency_versions': dict(highs_runtime.DISTRIBUTIONS),
            'dependency_version_equivalence_to_M02': 'unknown', 'image_id': runtime.IMAGE_ID,
            'resources': {'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}, 'network':'none',
            'native_time_limit_seconds':800, 'operational_timeout_seconds':920, 'optimizer_calls':0,
            'outer_retries':0, 'incumbent_seed':None, 'known_objective_cut':None, 'exclude_plan':None,
            'parameters':dict(highs_engineering.PARAMETERS), 'projects':360, 'original_rows':941,
            'input_mount_contains_only':'canonical matrix, frozen matrix-only code, exact dependency bytes',
            'private_reference_or_gold_incumbent_consumed':False, 'reference_admission':False,
            'formal_global_certificate_claimed':False, 'hardness_certified':False, 'qualified':False,
            'model_calls':0, 'LO_calls':0, 'Harbor_calls':0, 'agent_tool_budget_changed':False}
        require(checked_input()[0:2] == (inventory_ref, terminal_ref), 'The P01 input lineage changed during preparation')
        return write(output/'prospective.json', prospective)
    except BaseException as error:
        write(output/'preparation_failure.json', {'kind': KIND+'_preparation_failure', 'error_type':type(error).__name__,
            'error':str(error), 'optimizer_calls':0, 'qualified':False, 'partial_artifacts_preserved':True})
        raise


def _checked_prospective(output):
    output = Path(output).absolute(); require(output == output.resolve(), 'Use a real prepared screen directory')
    frozen = read(output/'prospective.json')
    require(frozen['kind'] == 'prepared_'+KIND and type(frozen['version']) is int and frozen['version'] == 1
        and frozen['profile_id'] == 'L360-P01' and frozen['recipe'] == recipes(), 'The frozen engineering implementation changed')
    inventory_ref, terminal_ref, terminal, model = checked_input()
    require(frozen['finance_inventory'] == inventory_ref and frozen['finance_terminal'] == terminal_ref
        and frozen['ancestry'] == {key:terminal[key] for key in frozen['ancestry']}
        and set(frozen['ancestry']) == {'specification','raw_preparation','universe_A','universe_B','model_A','model_B',
            'complete_financial_comparison','all_predeclared_plan_comparison','complete_matrix_comparison'},
        'The fixed P01 complete finance and matrix lineage changed')
    require(frozen['resources'] == {'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
        and frozen['native_time_limit_seconds'] == 800 and frozen['operational_timeout_seconds'] == 920
        and frozen['network'] == 'none' and frozen['projects'] == 360 and frozen['original_rows'] == 941
        and frozen['parameters'] == highs_engineering.PARAMETERS
        and all(frozen[key] is None for key in ('incumbent_seed','known_objective_cut','exclude_plan'))
        and all(frozen[key] is False for key in ('private_reference_or_gold_incumbent_consumed','reference_admission',
            'formal_global_certificate_claimed','hardness_certified','qualified','agent_tool_budget_changed'))
        and all(type(frozen[key]) is int and frozen[key] == 0 for key in ('optimizer_calls','outer_retries','model_calls','LO_calls','Harbor_calls'))
        and frozen['dependency_versions'] == highs_runtime.DISTRIBUTIONS
        and frozen['dependency_version_equivalence_to_M02'] == 'unknown', 'The bounded nonadmitting engineering contract changed')
    runtime = highs_runtime.build_runtime(frozen['vendor_lock']['path'], frozen['dependency_import_probe']['path'])
    require(runtime.dependency_lock == frozen['vendor_lock'] and runtime.dependency_probe == frozen['dependency_import_probe']
        and frozen['image_id'] == runtime.IMAGE_ID
        and frozen['native_preparation'] == reference(output/'native/preparation.json'), 'The exact native preparation or dependencies changed')
    tiny_path=Path(frozen['required_tiny_prospective']['path']).parent
    require(reference(tiny_path/'prospective.json')==frozen['required_tiny_prospective']
        and frozen['required_tiny_terminal_path']==str(tiny_path/'tiny_terminal.json'), 'The required API smoke ancestry changed')
    tiny,_,_=checked_tiny_prospective(tiny_path)
    require(tiny['vendor_lock']==frozen['vendor_lock'] and tiny['dependency_import_probe']==frozen['dependency_import_probe'],
        'The API smoke and P01 dependencies differ')
    return frozen, runtime, model


def validate_prepared(output):
    frozen, runtime, _ = _checked_prospective(output)
    runtime.validate_prepared(Path(output)/'native')
    return frozen


def execute_prepared(output):
    output = Path(output).absolute(); require(output == output.resolve(), 'Use a real screen preparation')
    lock_path = output/'screen.lock'; require(not lock_path.is_symlink(), 'The screen lease cannot be a symlink')
    with lock_path.open('a') as lock:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('This exact screen has an active launcher') from error
        frozen = validate_prepared(output)
        tiny_path = Path(frozen['required_tiny_prospective']['path']).parent
        require(reference(tiny_path/'prospective.json') == frozen['required_tiny_prospective']
            and frozen['required_tiny_terminal_path'] == str(tiny_path/'tiny_terminal.json'), 'The required API smoke preparation changed')
        tiny_receipt = checked_tiny_completed(tiny_path)
        require(not (output/'screen_started.json').exists(), 'Preserve the one engineering attempt; no retry is permitted')
        started = write(output/'screen_started.json', {'kind': KIND+'_started', 'prospective':reference(output/'prospective.json'),
            'optimizer_calls_authorized':1, 'outer_retries':0, 'reference_admission':False, 'qualified':False,
            'required_tiny_terminal':reference(tiny_path/'tiny_terminal.json')})
        try:
            runtime = highs_runtime.build_runtime(frozen['vendor_lock']['path'], frozen['dependency_import_probe']['path'])
            native = runtime.execute_prepared(output/'native')
            terminal = read(native)
            return write(output/'screen_terminal.json', {'kind':KIND, 'version':1, 'started':started,
                'native_terminal':native, 'status':terminal['status'], 'reference_admission':False,
                'formal_global_certificate_claimed':False, 'hardness_certified':False, 'qualified':False,
                'optimizer_calls':1, 'outer_retries':0, 'model_calls':0, 'LO_calls':0, 'Harbor_calls':0})
        except BaseException as error:
            write(output/'screen_failure.json', {'kind':KIND+'_failure', 'started':started, 'error_type':type(error).__name__,
                'error':str(error), 'retry_authorized':False, 'qualified':False, 'all_partial_artifacts_preserved':True})
            raise


def prepare_tiny(output, *, vendor_lock, dependency_probe):
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Use a fresh real tiny API smoke directory')
    model_ref, parent_ref = reference(TINY_ROOT/'model.json'), reference(TINY_ROOT/'terminal.json')
    require(model_ref['sha256'] == TINY_MODEL_SHA256 and parent_ref['sha256'] == TINY_PARENT_SHA256
        and read(parent_ref)['passed'] is True, 'Reuse only the unchanged passing three-project numeric fixture')
    runtime = highs_runtime.build_runtime(vendor_lock, dependency_probe)
    model = runtime.validate_model(read(model_ref))
    require(model['project_ids'] == ['P001','P002','P003'] and len(model['rows']) == 3,
        'The API smoke requires its exact three-project matrix')
    output.mkdir(parents=True)
    native = runtime.prepare(model_ref['path'], output/'native')
    return write(output/'prospective.json', {'kind':'prepared_'+TINY_KIND,'version':1,'recipe':recipes(),
        'original_model':model_ref,'passing_fixture_terminal':parent_ref,'native_preparation':native,
        'vendor_lock':runtime.dependency_lock,'dependency_import_probe':runtime.dependency_probe,
        'native_time_limit_seconds':800,'operational_timeout_seconds':920,
        'expected_plan':{'P001':0,'P002':1,'P003':1},'expected_objective_pence':13,
        'expected_all_integer_rows_checked':3,'expected_values_remain_host_only':True,
        'optimizer_calls':0,'outer_retries':0,'qualified':False,'reference_admission':False,
        'production_difficulty_certified':False,'dependency_version_equivalence_to_M02':'unknown'})


def checked_tiny_prospective(output):
    output = Path(output).absolute(); require(output == output.resolve(), 'Use a real tiny API smoke directory')
    frozen=read(output/'prospective.json')
    require(frozen['kind']=='prepared_'+TINY_KIND and type(frozen['version']) is int and frozen['version']==1
        and frozen['recipe']==recipes() and frozen['original_model']==reference(TINY_ROOT/'model.json')
        and frozen['original_model']['sha256']==TINY_MODEL_SHA256
        and frozen['passing_fixture_terminal']==reference(TINY_ROOT/'terminal.json')
        and frozen['passing_fixture_terminal']['sha256']==TINY_PARENT_SHA256
        and frozen['native_preparation']==reference(output/'native/preparation.json')
        and frozen['expected_plan']=={'P001':0,'P002':1,'P003':1} and frozen['expected_objective_pence']==13
        and frozen['expected_all_integer_rows_checked']==3 and frozen['expected_values_remain_host_only'] is True
        and frozen['native_time_limit_seconds']==800 and frozen['operational_timeout_seconds']==920
        and frozen['outer_retries']==0 and frozen['optimizer_calls']==0
        and frozen['qualified'] is frozen['reference_admission'] is frozen['production_difficulty_certified'] is False,
        'The frozen bounded three-project API smoke changed')
    runtime=highs_runtime.build_runtime(frozen['vendor_lock']['path'],frozen['dependency_import_probe']['path'])
    require(runtime.dependency_lock==frozen['vendor_lock'] and runtime.dependency_probe==frozen['dependency_import_probe'], 'The API smoke dependency references changed')
    return frozen,runtime,read(frozen['original_model'])


def checked_tiny_completed(output):
    output=Path(output).absolute();frozen,runtime,model=checked_tiny_prospective(output)
    require(not (output/'tiny_failure.json').exists(), 'A failed API smoke cannot permit the P01 run')
    result=read(output/'tiny_terminal.json')
    require(result['kind']==TINY_KIND and result['passed'] is True and result['prospective']==reference(output/'prospective.json')
        and result['qualified'] is result['reference_admission'] is False
        and result['native_terminal']==reference(output/'native/terminal.json'), 'A completed passing API smoke is required before P01')
    native=read(result['native_terminal']);solver=read(native['solver_result']);checked=runtime.check_result(model,solver)
    prep=read(frozen['native_preparation'])
    require(native['preparation']==frozen['native_preparation']
        and solver['model_sha256']==prep['model_canonical_sha256']
        and solver['specification_sha256']==model['specification_sha256']
        and solver['universe_sha256']==model['universe_sha256'], 'The completed API smoke belongs to another matrix')
    require(native['status']==checked['status']=='engineering_exact_feasible_incumbent'
        and solver['raw_status']=='HighsModelStatus.kOptimal' and solver['plan']==frozen['expected_plan']
        and solver['objective_pence']==13 and checked['exact_matrix_plan_check']['all_integer_rows_checked']==3,
        'The API smoke did not return the exact expected integer optimum and all original rows')
    runtime._check_highs_parameters(solver,prep)
    for name in ('host_before.json','host_after.json'):
        runtime.validate_resources(runtime._read(output/'native'/name),native['container_id'],output/'native/job_bundle')
    cleanup=read(native['cleanup'])
    require(native['cleanup']==reference(output/'native/owned_cleanup.json')
        and cleanup['owned_container_id']==native['container_id']
        and cleanup['removed_and_absent_with_daemon_reachable'] is True
        and runtime._inventory(output/'native/job_bundle')==native['complete_job_inventory'], 'The API smoke cleanup or complete retained job inventory changed')
    return result


def execute_tiny(output):
    output=Path(output).absolute();require(output==output.resolve(), 'Use a real tiny API smoke directory')
    require(not (output/'tiny.lock').is_symlink(), 'The tiny API smoke lock cannot be a symlink')
    with (output/'tiny.lock').open('a') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('This API smoke has an active launcher') from error
        frozen,runtime,model=checked_tiny_prospective(output);runtime.validate_prepared(output/'native')
        require(not (output/'tiny_started.json').exists(), 'Preserve the single tiny API smoke; no retries are permitted')
        started=write(output/'tiny_started.json',{'kind':TINY_KIND+'_started','prospective':reference(output/'prospective.json'),'outer_retries':0})
        try:
            native_ref=runtime.execute_prepared(output/'native');native=read(native_ref);solver=read(native['solver_result'])
            checked=runtime.check_result(model,solver)
            require(solver['raw_status']=='HighsModelStatus.kOptimal' and solver['plan']==frozen['expected_plan']
                and solver['objective_pence']==13 and checked['exact_matrix_plan_check']['all_integer_rows_checked']==3,
                'The tiny API transport did not return the exact expected plan/objective and all three rows')
            receipt=write(output/'tiny_terminal.json',{'kind':TINY_KIND,'version':1,'passed':True,'started':started,
                'prospective':reference(output/'prospective.json'),'native_terminal':native_ref,
                'reference_admission':False,'qualified':False,'optimizer_calls':1,'outer_retries':0})
            checked_tiny_completed(output);return receipt
        except BaseException as error:
            write(output/'tiny_failure.json',{'kind':TINY_KIND+'_failure','started':started,'error_type':type(error).__name__,
                'error':str(error),'retry_authorized':False,'qualified':False,'all_partial_artifacts_preserved':True});raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for command in ('prepare','prepare-tiny'):
        entry=sub.add_parser(command)
        for name in ('output','vendor-lock','dependency-probe'):entry.add_argument('--'+name,type=Path,required=True)
        if command=='prepare':entry.add_argument('--tiny-prepared',type=Path,required=True)
    for name in ('validate','run','validate-tiny','run-tiny'):
        entry=sub.add_parser(name);entry.add_argument('--prepared',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=='prepare':result=prepare(args.output,vendor_lock=args.vendor_lock,dependency_probe=args.dependency_probe,tiny_prepared=args.tiny_prepared)
    elif args.command=='prepare-tiny':result=prepare_tiny(args.output,vendor_lock=args.vendor_lock,dependency_probe=args.dependency_probe)
    elif args.command=='validate':result=validate_prepared(args.prepared)
    elif args.command=='validate-tiny':
        result,runtime,_=checked_tiny_prospective(args.prepared);runtime.validate_prepared(args.prepared/'native')
    elif args.command=='run-tiny':result=execute_tiny(args.prepared)
    else:result=execute_prepared(args.prepared)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
