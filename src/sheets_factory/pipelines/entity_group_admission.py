"""Read-only admission of a fully audited fixed-plan entity-group source.

An engineering source is not a qualified task. This module verifies the
existing complete receipts; it never emits a workbook or executes a ledger.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

from ..task_adapters.public_workbook_scope import checked_bytes, read, reference, require
from ..workbook.resource_engine import load_runtime_profile

ROOT = Path(__file__).resolve().parents[3]
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
SOURCE_KIND = 'independently_verified_hypothetical_fixed_plan_entity_group_source'
KIND = 'admitted_complete_fixed_plan_entity_group_financial_source'


def source_builder():
    location = ROOT / 'scripts/build_entity_group_source.py'
    loader = importlib.util.spec_from_file_location('_entity_group_admission_source_builder', location)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def verify_references(value, result=None):
    """Check all declared file identities without reopening arbitrary JSON."""
    result = {} if result is None else result
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            checked_bytes(value)
            require(value['path'] not in result or result[value['path']] == value['sha256'],
                    'Conflicting entity source artifact identities')
            result[value['path']] = value['sha256']
        for child in value.values():
            verify_references(child, result)
    elif isinstance(value, list):
        for child in value:
            verify_references(child, result)
    return result


def validate_source(value):
    """Require all actual source evidence; return its complete private binding."""
    record = value if isinstance(value, dict) else reference(value)
    manifest = read(record)
    require(manifest.get('kind') == SOURCE_KIND and type(manifest.get('version')) is int
            and manifest['version'] == 1 and manifest.get('profile_id') == 'G01'
            and manifest.get('status') == 'source_verified_not_task_or_difficulty_qualified'
            and manifest.get('provided_plan_is_protected') is True
            and manifest.get('optimisation_performed') is False
            and manifest.get('financial_audit_passed') is True
            and manifest.get('quality_or_difficulty_certified') is False
            and manifest.get('qualified') is False and type(manifest.get('task_count')) is int
            and manifest['task_count'] == 0,
            'A completed, financially audited entity source is required')
    require(all(type(manifest.get(key)) is int and manifest[key] == expected for key, expected in
                (('entity_count', 24), ('month_count', 120), ('scenario_count', 3),
                 ('actual_LO_recalculations', 3), ('model_calls', 0), ('ledger_executions_during_build', 0))),
            'Full production dimensions and all three actual source calculations are required')
    preparation = manifest['source_preparation']
    checked_bytes(preparation)
    builder = source_builder()
    frozen, public, ledger = builder.validate_prepared(Path(preparation['path']).parent)
    require(reference(Path(preparation['path'])) == preparation
            and manifest.get('source_recipe_sha256') == frozen['recipe_sha256']
            and manifest.get('public_specification') == frozen['public_specification']
            and manifest.get('forward_execution') == frozen['evidence']['forward']
            and manifest.get('independent_ledger') == frozen['evidence']['forward']['result']
            and manifest.get('resource_count_receipt') == frozen['evidence']['count_receipt']
            and manifest.get('count') == frozen['resource_count'],
            'The source must retain the exact complete preparation, financial report and count')
    require(ledger.get('feasible') is True and public['fixed_plan'] == ledger['fixed_plan'],
            'The supplied fixed plan must be feasible in all complete financial scenarios')
    mechanism_evidence = read(frozen['evidence']['forward']['reachability'])
    require(mechanism_evidence.get('passed') is True and mechanism_evidence.get('feasible') is True
            and set(mechanism_evidence.get('scenarios', {})) == {'S01', 'S02', 'S03'}
            and all(row.get('entity_months_checked') == 2880
                    and row.get('all_entities_economically_active') is True
                    and row.get('all_mechanisms_with_dated_economic_evidence') is True
                    and len(row.get('mechanisms', {})) == 14
                    and all(item.get('active') is True and type(item.get('count')) is int
                            and item['count'] > 0 and item.get('witnesses')
                            for item in row['mechanisms'].values())
                    for row in mechanism_evidence['scenarios'].values()),
            'Every scenario must retain the audited dated evidence for all fourteen economic mechanisms')
    profile_ref = frozen['evidence'].get('runtime_profile')
    require(isinstance(profile_ref, dict) and manifest.get('runtime_profile') == profile_ref,
            'The large family requires its explicit runtime profile')
    profile = load_runtime_profile(frozen['runtime_profile'])
    require(profile['id'] == 'entity_group_large_v2'
            and profile == builder.load_profile(profile_ref),
            'The new entity task family requires the explicit approved v2 resource profile')
    runtime = manifest['runtime']
    builder.validate_resources(runtime, profile, completed_calls=3)
    workbook = manifest['workbook']
    require(manifest.get('local_path') == workbook['path']
            and manifest.get('derived_workbook_sha256') == workbook['sha256'],
            'The actual source workbook identity differs')
    calls = manifest['engine_calls']
    require(len(calls) == 3 and len(manifest['financial_audits']) == 3,
            'Every actual source pass needs its complete independent financial audit')
    previous = None
    audits = []
    encodings = frozen['resource_count']['binding_encodings']
    require(set(encodings) == {'scalar', 'exact_integer_pair', 'queues'}
            and all(type(value) is int and value > 0 for value in encodings.values())
            and sum(encodings.values()) == frozen['resource_count']['logical_output_binding_count'],
            'The complete logical binding inventory differs')
    expected_logical_fields = encodings['scalar'] + encodings['exact_integer_pair'] + 6 * encodings['queues']
    for index, (call, audit_ref) in enumerate(zip(calls, manifest['financial_audits']), 1):
        require(type(call.get('index')) is int and call['index'] == index
                and call.get('completed') is True and call.get('image_id') == IMAGE_ID
                and call.get('network') == 'none'
                and call.get('runtime_profile') == profile_ref
                and call.get('workbook_file_timeout_seconds') == profile['timeouts']['workbook_file_seconds']
                and call.get('requested_source_resources') == profile['docker_resources']['source'],
                'An actual source calculation or its resource contract is incomplete')
        started = read(call['started_receipt']); terminal = read(call['terminal_receipt'])
        require(started.get('completed') is False and started['input'] == call['input']
                and terminal == {key: item for key, item in call.items() if key != 'terminal_receipt'}
                and call['actual_resource_receipt'] == runtime['actual_resource_receipts'][index - 1],
                'The actual source started, terminal and inspected-resource receipts differ')
        resource = read(call['actual_resource_receipt'])
        require(resource['source'] == call['input'] and resource['output'] == call['output']
                and resource['destination'] == call['destination'],
                'The inspected container belongs to another workbook calculation')
        require(previous is None or call['input'] == previous, 'The actual source execution chain is broken')
        previous = call['output']
        audit = read(audit_ref)
        require(audit.get('workbook') == call['output'] and audit.get('passed') is True
                and audit.get('all_independent_journal_fields_covered') is True
                and audit.get('all_scenarios_feasible') is True
                and audit.get('provided_fixed_plan_verified') is True
                and audit.get('optimisation_performed') is False
                and audit.get('physical_formulas_checked') == frozen['resource_count']['physical_formula_count']
                and type(audit.get('logical_fields_checked')) is int
                and audit['logical_fields_checked'] == expected_logical_fields
                and audit.get('mismatches') == [] and audit.get('control_mismatches') == [],
                'The complete actual field, primitive, cache-type or formula audit failed')
        audits.append(audit)
    require(workbook == calls[0]['output']
            and len({audit['logical_fields_checked'] for audit in audits}) == 1,
            'The source or complete logical coverage differs between actual passes')
    stability = read(manifest['stability'])
    require(stability.get('stable') is True
            and all(stability.get(key, {}).get('passed') is True
                    and stability[key].get('sheet_names_equal') is True
                    and stability[key].get('mismatches') == []
                    and type(stability[key].get('checked_existing_value_cells')) is int
                    and stability[key]['checked_existing_value_cells'] == frozen['resource_count']['physical_nonempty_cells']
                    for key in ('first_against_goal', 'second_against_goal')),
            'Both further actual complete typed-value stability checks are required')
    # The complete source-builder receipt is authoritative for numerical audit
    # execution. Admission does not manufacture a fourth recalculation or audit.
    artifacts = verify_references([record, manifest, preparation, frozen, audits, stability])
    for path, digest in frozen['recipe_sha256'].items():
        require(reference(path)['sha256'] == digest, 'A numerical source dependency changed')
        artifacts[path] = digest
    return {'kind': KIND, 'version': 1, 'source_manifest': record, 'workbook': workbook,
        'public_specification': frozen['public_specification'], 'bindings': manifest['bindings'],
        'source_preparation': preparation, 'count_receipt': frozen['evidence']['count_receipt'],
        'complete_count': deepcopy(frozen['resource_count']), 'financial_audits': deepcopy(manifest['financial_audits']),
        'logical_fields_checked': audits[0]['logical_fields_checked'], 'stability': manifest['stability'],
        'independent_ledger': manifest['independent_ledger'], 'forward_execution': manifest['forward_execution'],
        'runtime_profile': profile_ref, 'runtime_profile_value': profile,
        'actual_source_runtime': deepcopy(runtime), 'artifact_sha256': artifacts,
        'admission_implementation': reference(__file__), 'financial_seed_verified': True,
        'fixed_plan_provided_and_protected': True, 'optimisation_performed': False,
        'all_five_controls_public_recovery_all12_diagnostics_Harbor_and_difficulty_pending': True,
        'qualified': False, 'task_count': 0}


def verify_admitted_proof(proof):
    require(isinstance(proof, dict) and proof.get('kind') == KIND
            and type(proof.get('version')) is int and proof['version'] == 1
            and proof.get('admission_implementation') == reference(__file__)
            and proof.get('financial_seed_verified') is True,
            'A complete current entity source admission is required')
    for path, digest in proof['artifact_sha256'].items():
        require(reference(path)['sha256'] == digest, 'A bound entity source artifact changed')
    verify_references([proof['source_manifest'], proof['workbook'], proof['bindings'], proof['runtime_profile']])
    require(validate_source(proof['source_manifest']) == proof,
            'The complete source admission cannot be replaced by a summary or caller-supplied verification flag')
    return proof
