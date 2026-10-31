#!/usr/bin/env python3
"""Prepare one D02 source from completed dual evidence; build only with --run.

All source calculations use unchanged frozen financial implementations. The
new catalogue and actual dual envelope remain explicit and are never relabelled
as D01 evidence. No task quality or difficulty is certified here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import openpyxl
from sheets_factory.core.audit import AuditStore,utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.capital_allocation_scaled import constrained_catalog as catalog
from sheets_factory.workbook.capital_allocation_scaled import excel,ledger,search_a,search_b,spec,validate
from sheets_factory.workbook import resource_engine
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine,load_runtime_profile
from sheets_factory.task_adapters.lease_family import compare_exact_typed

BASE_PATH=ROOT/'scripts/build_scaled_capital_source.py'
BASE_SHA256='c864e88708ed4a492917457d8dc74a2b613215b576d688ec87e403987f94ebf0'
DRIVER_PATH=ROOT/'scripts/run_constrained_capital_dual.py'
DRIVER_SHA256='0c5b75bf821109d1cd3974a8fd6731af459ff6a3736f1c197f7671c4853ad700'
CATALOG_SHA256='dc3f5baaf1a5b254155349af45142cc6d0e2521f14b540b610fb191cefeb59ca'
PROFILE_ID='30-D02'
KIND='prepared_first_constrained_capital_financial_source'
COUNT=1<<30
RECORD_BYTES=COUNT*spec.RECORD_BYTES
FORMULAS=77513
DEFAULT_RUNTIME=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
PUBLIC_ARTIFACTS=('spec','public_summary','candidate_contract','candidate_contract_markdown')


def _frozen_module(name,path,digest):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(2**20),b''):h.update(block)
    if h.hexdigest()!=digest:raise ValueError('A frozen source helper changed: '+str(path))
    definition=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module)
    return module


base=_frozen_module('_constrained_frozen_source_helpers',BASE_PATH,BASE_SHA256)
require=base.require
reference=base.reference
write_new=base.write_new
Evidence=base.Evidence
stream_records=base.stream_records
_rank_fields=base._rank_fields
_selected_record=base._selected_record
data_temporary=base.data_temporary
_runtime=base._runtime
phase=base.phase
RANK_FIELDS=base.RANK_FIELDS


def recipes():
    _frozen_module('_rechecked_constrained_source_helpers',BASE_PATH,BASE_SHA256)
    result=base.recipes()
    paths=[Path(__file__),BASE_PATH,DRIVER_PATH,Path(catalog.__file__),catalog.DEFAULT_CATALOG,
           ROOT/'scripts/prepare_constrained_capital_specs.py']
    for path in paths:result[str(path.resolve())]=reference(path)['sha256']
    require(result[str(DRIVER_PATH)]==DRIVER_SHA256,'The prospective D02 dual driver changed')
    return result


def _driver():
    return _frozen_module('_checked_constrained_dual_driver',DRIVER_PATH,DRIVER_SHA256)


def _catalog_context(specification,catalog_manifest,evidence):
    specification,catalog_manifest=reference(specification),reference(catalog_manifest)
    require(catalog_manifest['sha256']==CATALOG_SHA256,'Use the prospectively frozen complete eleven-profile constrained catalogue')
    driver=_driver()
    manifest,record,public,inventory=driver._catalogue(catalog_manifest,PROFILE_ID)
    require(record['spec']==specification,'Only the declared D02 development source may be built')
    require(evidence.read(record['public_summary'])==catalog.describe_profile(PROFILE_ID),
            'The complete D02 public summary changed')
    prospective=evidence.read(manifest['prospective_inventory'])
    require(prospective.get('profile_order')==list(catalog.PROFILE_ORDER)
        and [r.get('profile_id') for r in prospective.get('profiles',[])]==list(catalog.PROFILE_ORDER)
        and prospective.get('financial_execution_or_model_outcome_selection') is False,
        'Keep every original development and confirmation raw profile')
    for row,item in zip(manifest['specifications'],prospective['profiles']):
        raw=spec.load_spec(evidence.read(row['spec']))
        require(item['spec_sha256']==spec.canonical_sha(raw),'A prospective raw profile changed')
    evidence.graph([manifest,prospective,record,inventory])
    return public,specification,catalog_manifest,manifest,{key:record[key] for key in PUBLIC_ARTIFACTS}


def validate_dual_proof(public,specification,catalog_manifest,artifacts,proof_ref,progress=None):
    """Check the actual D02 envelope and both complete existing record streams."""
    evidence=Evidence();terminal=evidence.read(proof_ref);driver=_driver()
    require(terminal.get('kind')==driver.TERMINAL_KIND and type(terminal.get('version')) is int and terminal['version']==1
        and terminal.get('profile_id')==PROFILE_ID and terminal.get('status')=='completed' and terminal.get('passed') is True
        and terminal.get('complete_independent_search_finished') is True and terminal.get('records_equal_complete') is True
        and terminal.get('full_enumeration') is True and terminal.get('toy_only') is False
        and terminal.get('count')==terminal.get('plan_count')==COUNT,
        'The complete actual D02 dual search must finish successfully')
    frozen,prepared_public,inventory=driver.validate_prepared(terminal['preparation'])
    require(prepared_public==public and frozen['public_specification']==specification
        and frozen['catalog_manifest']==catalog_manifest and terminal.get('public_specification')==specification
        and terminal.get('catalog_manifest')==catalog_manifest
        and terminal.get('public_contract_artifacts')==frozen['public_contract_artifacts']
        and {key:terminal['public_contract_artifacts'][key] for key in PUBLIC_ARTIFACTS}==artifacts
        and terminal.get('engineering_provenance')==frozen['engineering_provenance']
        and terminal.get('engineering_provenance_summary')==frozen['engineering_provenance_summary'],
        'The actual search, its prior engineering history or four public sidecars belong to another profile')
    started=evidence.read(terminal['started'])
    require(started.get('kind')=='started_constrained_capital_dual_search'
        and started.get('preparation')==terminal['preparation']
        and started.get('expected_plan_count_per_kernel')==COUNT
        and started.get('concurrent_kernels')==2 and started.get('timeout_seconds_per_kernel')==14400
        and started.get('recipe')==terminal.get('recipe')==frozen['recipe']==driver.recipe(),
        'The complete search was not frozen before actual execution')
    a,b=evidence.read(terminal['kernel_A_result']),evidence.read(terminal['kernel_B_result'])
    require(a.get('kind')=='capital_scaled_A_complete_enumeration'
        and b.get('kind')=='capital_allocation_scaled_independent_B_execution','Two distinct known independent kernels are required')
    rank=_rank_fields(terminal,public)
    for result in (a,b):
        require(result.get('status')=='completed' and result.get('plan_count')==COUNT and result.get('project_count')==30
            and result.get('full_enumeration') is True and result.get('toy_only') is False
            and result.get('active_project_ids')==list(spec.project_ids(30))
            and result.get('spec_sha256')==spec.canonical_sha(public)
            and (result.get('record_format'),result.get('record_bytes'),result.get('chunk_records'),result.get('null_npv'))
                ==(spec.RECORD_FORMAT,spec.RECORD_BYTES,spec.CHUNK_RECORDS,spec.NULL_NPV)
            and _rank_fields(result,public)==rank and spec.load_spec(evidence.read(result['public_spec']))==public,
            'An independent result is partial, toy, tied or bound to another specification')
    require(a.get('recipe')==search_a.recipe() and b.get('recipe_sha256')==search_b._recipe()
        and b.get('kernel_implementation')==reference(search_b.KERNEL)
        and b.get('wrapper_implementation')==reference(search_b.__file__)
        and b.get('shared_financial_calculation_helper') is False
        and b.get('independent_raw_public_primitives_precompilation') is True,
        'The independent A/B implementations or their raw-spec precompilation changed')
    require(evidence.check(a['raw_primitives']).read_text()==search_a.raw_primitives(public,list(range(30))),
        'A executed another raw primitive wire')
    b_prepared,b_public=search_b.validate_prepared(b['preparation'])
    require(b_public==public and b_prepared['full_enumeration'] is True and b_prepared['toy_only'] is False
        and b_prepared['active_project_ids']==list(spec.project_ids(30))
        and b.get('kernel_command')==[b['compiled_binary']['path'],b_prepared['raw_wire']['path'],b['records']['path']],
        'B execution does not bind its complete raw primitives and binary')
    require(Path(a['records']['path'])!=Path(b['records']['path'])
        and a['records']['sha256']==b['records']['sha256'] and a['records']['bytes']==b['records']['bytes']==RECORD_BYTES
        and a.get('chunks')==b.get('chunks'),'Both complete independent records and all chunks must agree')
    for result in (a,b):
        stream_records(result['records'],result['chunks'],COUNT,progress)
        evidence.checked[result['records']['path']]=dict(result['records'])
    compilation=evidence.read(a['compilation'])
    require(compilation.get('kind')=='capital_scaled_A_compilation' and compilation.get('returncode')==0
        and compilation.get('implementation')==reference(search_a.SOURCE),'A compilation does not bind the frozen independent source')
    require(a['kernel_result'].get('plan_count')==COUNT and a['kernel_result'].get('scenario_evaluations')==COUNT*3
        and all(a['kernel_result'].get(key)==rank[key] for key in search_a.RANK_FIELDS)
        and b['kernel_statistics'].get('plan_count')==COUNT and b['kernel_statistics'].get('scenario_evaluations')==COUNT*3
        and b['kernel_statistics'].get('feasible_count')==rank['feasible_count'],
        'Actual kernel statistics disagree with their complete records')
    comparison=evidence.read(terminal['complete_record_comparison'])
    require(comparison.get('kind')=='complete_constrained_independent_ordinal_record_equality'
        and comparison.get('records_equal_complete') is True and comparison.get('rankings_equal') is True
        and comparison.get('all_chunk_hashes_equal') is True and comparison.get('plan_count')==COUNT
        and comparison.get('record_bytes_per_kernel')==RECORD_BYTES
        and comparison.get('chunk_count_per_kernel')==COUNT//spec.CHUNK_RECORDS
        and comparison.get('A_records')==a['records'] and comparison.get('B_records')==b['records']
        and comparison.get('kernel_A_result')==terminal['kernel_A_result'] and comparison.get('kernel_B_result')==terminal['kernel_B_result']
        and comparison.get('rank_fields')==rank,'The actual D02 complete record/rank comparison differs')
    selected=evidence.read(terminal['independent_decimal_validation'])
    require(selected.get('kind')=='constrained_forward_best_runnerup_and_complete_declared_fixed_inventory'
        and selected.get('passed') is True and selected.get('declared_fixed_plan_count')==44
        and selected.get('all_declared_fixed_plans_preserved') is True and selected.get('optimisation_performed') is False
        and selected.get('independent_global_optimality_claimed') is False,
        'The actual46 forward checks must not become a fabricated third global search')
    plans=[{'id':'best_mask','plan':rank['best_plan']},
        {'id':'runnerup_mask','plan':{p['id']:(rank['runnerup_mask']>>i)&1 for i,p in enumerate(public['projects'])}},*inventory['plans']]
    rows=selected.get('checks',[])
    require(len(rows)==46 and [r.get('id') for r in rows]==[r['id'] for r in plans],
        'Preserve best, runner-up and every one of the original44 fixed plans in order')
    for row,declared in zip(rows,plans):
        plan=declared['plan'];mask=sum(plan[p['id']]<<i for i,p in enumerate(public['projects']))
        forward=evidence.read(row['ledger']);flags,npvs=_selected_record(a['records']['path'],mask)
        require(row.get('mask')==mask and row.get('record_matches') is True and row.get('all_journals_balance') is True
            and forward.get('plan')==plan and all(s.get('all_journals_balance') is True for s in forward['scenarios'].values())
            and row.get('objective_pence')==forward.get('objective_pence') and row.get('feasible')==forward.get('feasible')
            and flags==sum(1<<i for i,sid in enumerate(spec.SCENARIO_IDS) if forward['scenarios'][sid]['feasible'])
            and npvs==[forward['scenarios'][sid]['npv_pence'] if forward['scenarios'][sid]['feasible'] else spec.NULL_NPV for sid in spec.SCENARIO_IDS],
            'An existing Decimal journal differs from its declared fixed mask and complete record')
    require(rows[0]['objective_pence']==rank['objective_pence'] and rows[1]['objective_pence']==rank['runnerup_objective_pence'],
        'Winner or runner-up Decimal objective differs')
    evidence.graph([terminal,started,frozen,a,b,compilation,comparison,selected])
    return {'rank':rank,'terminal':terminal,'best_ledger':rows[0]['ledger'],'verified_artifacts':dict(evidence.checked),
        'records_rehashed':[a['records'],b['records']], 'global_optimum_method':'two_independent_full_exhaustive_cpp_record_streams',
        'selected_plan_decimal_checks_are_not_an_independent_global_search':True}



def prepare(specification, catalog_manifest, dual_proof, output, *, runtime_profile=DEFAULT_RUNTIME):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT) and not output.exists(), 'Use a fresh source directory under the project /data root')
    runtime_ref, runtime = _runtime(runtime_profile)
    evidence = Evidence()
    public, source_ref, catalog_ref, manifest, artifacts = _catalog_context(specification, catalog_manifest, evidence)
    proof_ref = reference(dual_proof)
    checked = validate_dual_proof(public, source_ref, catalog_ref, artifacts, proof_ref)
    recipe = recipes()
    output.mkdir(parents=True)
    copied = {}
    for name, source in artifacts.items():
        destination = output / 'public' / Path(source['path']).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evidence.check(source), destination)
        copied[name] = reference(destination)
    validation_ref = write_new(output / 'private/validated_dual_proof.json', checked)
    return write_new(output / 'preparation.json', {'kind': KIND, 'version': 1, 'profile_id': PROFILE_ID,
        'public_specification': source_ref, 'catalog_manifest': catalog_ref, 'public_contract_artifacts': artifacts,
        'copied_public_contract_artifacts': copied, 'dual_search_proof': proof_ref,
        'validated_dual_proof': validation_ref, 'recipe_sha256': recipe,
        'runtime_profile': runtime_ref, 'runtime_profile_value': runtime,
        'expected_physical_formulas': FORMULAS, 'project_count': 30, 'plan_count_per_kernel': COUNT,
        'raw_ancestors': dict(spec.RAW_ANCESTORS), 'raw_ancestry_is_provenance_only': True,
        'hypothetical_forecasts_and_policy': True, 'workbook_emitted': False, 'winning_plan_written_to_public_files': False,
        'actual_LO_calls': 0, 'actual_new_enumerations': 0, 'model_calls': 0,
        'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0})


def validate_prepared(output, progress=None):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT), 'A source preparation must stay in its real project directory')
    evidence = Evidence()
    frozen = evidence.read(reference(output / 'preparation.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
        and frozen.get('profile_id') == PROFILE_ID and frozen.get('recipe_sha256') == recipes()
        and frozen.get('workbook_emitted') is False and frozen.get('winning_plan_written_to_public_files') is False
        and frozen.get('actual_LO_calls') == frozen.get('actual_new_enumerations') == frozen.get('model_calls') == 0,
        'The immutable zero-call source preparation changed')
    require(frozen.get('expected_physical_formulas') == FORMULAS and frozen.get('project_count') == 30
        and frozen.get('plan_count_per_kernel') == COUNT and frozen.get('raw_ancestors') == spec.RAW_ANCESTORS
        and frozen.get('raw_ancestry_is_provenance_only') is True and frozen.get('hypothetical_forecasts_and_policy') is True
        and frozen.get('quality_or_difficulty_certified') is False and frozen.get('qualified') is False
        and frozen.get('task_count') == 0, 'The complete source scope or honest provenance claims changed')
    runtime_ref, runtime = _runtime(frozen['runtime_profile']['path'])
    require(runtime_ref == frozen['runtime_profile'] and runtime == frozen['runtime_profile_value'], 'The explicit source resource profile changed')
    public, source_ref, catalog_ref, _, artifacts = _catalog_context(frozen['public_specification']['path'], frozen['catalog_manifest']['path'], evidence)
    require(source_ref == frozen['public_specification'] and catalog_ref == frozen['catalog_manifest']
        and artifacts == frozen['public_contract_artifacts'], 'The frozen original public contract changed')
    require(set(frozen['copied_public_contract_artifacts']) == set(PUBLIC_ARTIFACTS), 'All four copied public contract artifacts are required')
    for key, record in frozen['copied_public_contract_artifacts'].items():
        evidence.check(record)
        require(record['sha256'] == artifacts[key]['sha256'] and record['bytes'] == artifacts[key]['bytes']
            and Path(record['path']) == output / 'public' / Path(artifacts[key]['path']).name,
            'A copied public contract differs or escaped its public directory')
    require({str(path) for path in (output / 'public').rglob('*') if path.is_file()}
        == {record['path'] for record in frozen['copied_public_contract_artifacts'].values()},
        'The public source preparation contains an unexpected artifact')
    checked = validate_dual_proof(public, source_ref, catalog_ref, artifacts, frozen['dual_search_proof'], progress)
    require(evidence.read(frozen['validated_dual_proof']) == checked, 'The original complete dual validation changed')
    return frozen


def execute_prepared(output, *, port=0):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT) and (output / 'preparation.json').is_file(),
        'An existing source preparation under the real project root is required')
    lease = ProducerLease(output).acquire()
    audit = server = None
    attempt = output / 'private/build_attempts' / uuid.uuid4().hex
    status, clock, calls = 'failed', time.monotonic(), []
    try:
        with data_temporary(output):
            require(not (output / 'seed_manifest.json').exists(), 'Never overwrite an already built source')
            attempt.mkdir(parents=True)
            write_new(attempt / 'started.json', {'kind': 'constrained_capital_source_attempt', 'started_at': utcnow(),
                'preparation': reference(output / 'preparation.json'), 'profile_id': PROFILE_ID,
                'model_calls': 0, 'new_search_calls': 0, 'quality_or_difficulty_certified': False})
            audit = AuditStore(attempt / 'audit', {'id': attempt.name, 'name': 'Constrained capital source engineering',
                'status': 'running', 'target_count': 0, 'producer_pid': os.getpid(), 'producer_active': True,
                'model_calls': 0, 'tokens': 0, 'qualified': 0})
            server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            audit.update_run(dashboard_url=url)
            print(json.dumps({'dashboard_url': url, 'source_attempt': str(attempt), 'model_calls': 0, 'LO_calls': 0}), flush=True)
            last_progress = [0.0]
            def progress(path, observed, total):
                now = time.monotonic()
                if observed == total or now - last_progress[0] >= 1:
                    audit.update_run(active_record_stream=str(path), record_bytes_rehashed=observed, record_bytes_expected=total)
                    last_progress[0] = now
            with phase(audit, 'verify_complete_frozen_dual_search'):
                frozen = validate_prepared(output, progress)
                public = spec.load_spec(json.loads(Path(frozen['public_specification']['path']).read_text()))
                proof = json.loads(Path(frozen['validated_dual_proof']['path']).read_text())
                plan = ledger.validate_plan(public, proof['rank']['best_plan'])
            with phase(audit, 'independent_complete_winner_journal'):
                forward = ledger.simulate(public, plan)
                expected = Evidence().read(proof['best_ledger'])
                require(forward == expected and forward['feasible'] is True
                    and forward['objective_pence'] == proof['rank']['objective_pence'],
                    'Every independently computed winning financial field must match the dual-proof journal')
                ledger_ref = write_new(attempt / 'independent_winner_ledger.json', forward)
            with phase(audit, 'emit_private_full_financial_goal'):
                book = openpyxl.Workbook()
                book.remove(book.active)
                try:
                    bindings = excel.emit_capital_allocation_workbook(book, public, plan)
                    require(bindings['formula_count'] == FORMULAS and len(bindings['decision_bindings']) == 30
                        and bindings.get('gold_plan_supplied') is True and bindings.get('public_rules') == list(excel.PUBLIC_RULES),
                        'The complete thirty-project formula or public-schema scope changed')
                    raw = attempt / 'raw_goal.xlsx'
                    book.save(raw)
                finally:
                    book.close()
                bindings_ref = write_new(attempt / 'bindings.json', bindings)
            engine = ResourceLibreOfficeEngine(ROOT, frozen['runtime_profile']['path'], role='source',
                                              receipt_directory=attempt / 'engine_resources')
            engine.ensure_image()
            current, versions, audits = raw, [], []
            for index in range(3):
                destination = attempt / ('calculated_pass' + str(index + 1) + '.xlsx')
                call = {'index': index + 1, 'input': reference(current), 'destination': str(destination),
                    'started_at': utcnow(), 'completed': False}
                calls.append(call)
                write_new(attempt / ('LO_pass' + str(index + 1) + '_started.json'), call)
                with phase(audit, 'actual_LO_pass' + str(index + 1)):
                    try:
                        actual = engine.recalculate(current, destination)
                        call.update(output=reference(actual), completed=True)
                    except BaseException as error:
                        call.update(error_type=type(error).__name__, error=str(error))
                        raise
                    finally:
                        call['finished_at'] = utcnow()
                        write_new(attempt / ('LO_pass' + str(index + 1) + '_terminal.json'), call)
                        audit.update_run(actual_LO_calls_completed=sum(item['completed'] for item in calls),
                                         actual_LO_calls_started=len(calls))
                with phase(audit, 'independent_all_formula_cache_audit' + str(index + 1)):
                    result = validate.audit_capital_allocation_workbook(actual, public, plan, forward, bindings)
                    audits.append(write_new(attempt / ('financial_audit_pass' + str(index + 1) + '.json'),
                                            {'workbook': reference(actual), **result}))
                    require(result.get('passed') is True and result.get('checked_cells') == result.get('formula_count') == FORMULAS
                        and result.get('all_formula_cells_independently_covered') is True
                        and result.get('all_scenarios_feasible') is True and result.get('all_journals_balance') is True
                        and result.get('mismatches') == [] and result.get('control_mismatches') == [],
                        'An actual financial field, exact arithmetic helper, provided input or public contract failed audit')
                versions.append(actual)
                current = actual
            with phase(audit, 'complete_two_further_pass_stability'):
                stability = {'first_against_goal': compare_exact_typed(versions[0], versions[1]),
                             'second_against_goal': compare_exact_typed(versions[0], versions[2])}
                stability['stable'] = all(item['passed'] is True for item in stability.values())
                stability_ref = write_new(attempt / 'stability.json', stability)
                require(stability['stable'], 'The full financial goal is not stable over both further actual passes')
            with phase(audit, 'recheck_frozen_proof_and_publish_private_source_receipt'):
                require(validate_prepared(output, progress) == frozen, 'Source construction changed the frozen preparation or complete search proof')
                runtime = engine.metadata()
                require(runtime.get('runtime_profile') == frozen['runtime_profile_value']
                    and len(runtime.get('actual_resource_receipts', [])) == 3, 'All three actual source resource receipts are required')
                evidence = Evidence()
                for call, record in zip(calls, runtime['actual_resource_receipts']):
                    actual_resource = evidence.read(record)
                    r = frozen['runtime_profile_value']['docker_resources']['source']
                    require(actual_resource.get('status') == 'completed' and actual_resource.get('actual_resources_verified') is True
                        and actual_resource.get('source') == call['input'] and actual_resource.get('output') == call['output']
                        and actual_resource.get('image_id') == frozen['runtime_profile_value']['image']['id']
                        and actual_resource.get('profile') == frozen['runtime_profile']
                        and actual_resource.get('implementation') == reference(resource_engine.__file__)
                        and actual_resource.get('requested_resources') == r
                        and actual_resource.get('workbook_file_timeout_seconds') == 600
                        and actual_resource.get('actual_resources') == {'cpus_nanoseconds': r['cpus'] * 10**9,
                            'memory_bytes': r['memory_bytes'], 'pids_limit': r['pids_limit']},
                        'A source calculation lacks its exact actual resource enforcement evidence')
                    call['resource_receipt'] = record
                manifest = {'kind': 'independently_verified_constrained_capital_allocation_source', 'version': 1,
                    'source_kind': 'derived_constrained_capital_allocation_source', 'profile_id': PROFILE_ID,
                    'status': 'source_verified_not_task_quality_or_difficulty_qualified',
                    'local_path': str(versions[0]), 'workbook': reference(versions[0]),
                    'derived_workbook_sha256': reference(versions[0])['sha256'],
                    'public_specification': frozen['copied_public_contract_artifacts']['spec'],
                    'public_contract_artifacts': frozen['copied_public_contract_artifacts'],
                    'source_preparation': reference(output / 'preparation.json'), 'dual_search_proof': frozen['dual_search_proof'],
                    'validated_dual_proof': frozen['validated_dual_proof'], 'bindings': bindings_ref,
                    'independent_ledger': ledger_ref, 'financial_audits': audits, 'financial_audit_passed': True,
                    'stability': stability_ref, 'engine_calls': calls, 'actual_LO_recalculations': 3,
                    'runtime_profile': frozen['runtime_profile'], 'runtime': runtime,
                    'agent_and_verifier_resources_actually_verified': False,
                    'source_recipe_sha256': frozen['recipe_sha256'], 'project_count': 30, 'physical_formula_count': FORMULAS,
                    'raw_ancestors': frozen['raw_ancestors'], 'raw_ancestry_is_provenance_only': True,
                    'hypothetical_forecasts_and_policy': True, 'source_original_ancestors': 2,
                    'model_calls': 0, 'new_enumeration_calls': 0,
                    'task_input_and_complete_D_not_built': True,
                    'gold_decisions_and_financials_require_normal_task_masking': True,
                    'plan_dependent_helper_caches_require_clearing_and_actual_input_recalculation': True,
                    'complete_required_D_must_include_changed_arithmetic_helpers': True,
                    'full_public_sidecar_contract_must_be_transferred_to_task': True,
                    'five_controls_recovery_all12_quality_Harbor_and_difficulty_pending': True,
                    'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
                receipt = write_new(output / 'seed_manifest.json', manifest)
                status = 'source_verified'
                write_new(attempt / 'terminal.json', {'status': status, 'manifest': receipt, 'calls': calls,
                    'elapsed_seconds': time.monotonic() - clock, 'engineering_time_excluded_from_solver_trial': True,
                    'model_calls': 0, 'quality_or_difficulty_certified': False})
                return receipt
    except BaseException as error:
        if attempt.is_dir() and not (attempt / 'terminal.json').exists():
            write_new(attempt / 'terminal.json', {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error),
                'calls': calls, 'all_partial_artifacts_preserved': True, 'model_calls': 0, 'qualified': False, 'task_count': 0})
        raise
    finally:
        try:
            if audit is not None:
                audit.update_run(status=status, producer_active=False, finished_at=utcnow(), elapsed_seconds=time.monotonic() - clock)
                audit.export()
        finally:
            try:
                if server is not None:
                    server.stop()
            finally:
                try:
                    if audit is not None:
                        audit.db.close()
                finally:
                    lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('spec', 'catalog-manifest', 'dual-proof', 'output', 'prepared', 'runtime-profile'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared is not None:
        require(not any((args.spec, args.catalog_manifest, args.dual_proof, args.output, args.runtime_profile)),
                'An existing preparation cannot acquire new arguments')
        if args.run:
            result = execute_prepared(args.prepared, port=args.port)
        else:
            validate_prepared(args.prepared)
            result = {'validated': str(args.prepared), 'LO_calls': 0, 'model_calls': 0, 'new_enumeration_calls': 0}
    else:
        require(not args.run and all((args.spec, args.catalog_manifest, args.dual_proof, args.output)),
                'Prepare first; actual source construction requires explicit --prepared --run')
        result = prepare(args.spec, args.catalog_manifest, args.dual_proof, args.output,
                         runtime_profile=args.runtime_profile or DEFAULT_RUNTIME)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
