"""Admit an existing sparse financial reference without search or recalculation.

One complete prefix proof plus the opposite core's forward on EVERY supplied
leaf establishes the reference. Decimal best/runner journals and three actual
workbook passes are separate mandatory evidence. This module grants no task,
recovery, Harbor, model difficulty, or two-search qualification.
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import weakref

import openpyxl

from ..workbook.capital_allocation_sparse import catalog, check_masks, excel, ledger, spec, streamed_native, validate
from ..workbook import resource_engine

KIND = 'admitted_sparse_capital_financial_source'
METHOD = 'complete_integer_prefix_opposite_all_leaf_Decimal_actual_three_pass_financial_source_v1'
DEFAULT_PROFILE = Path(resource_engine.__file__).resolve().parents[3] / 'config/runtime_profiles/entity_group_large_v2.yaml'
_SESSIONS = weakref.WeakKeyDictionary()


def require(condition, message):
    if not condition:
        raise ValueError(message)


class AdmissionSession:
    """Opaque live-process identity; no caller-populated JSON cache is accepted."""
    __slots__ = ('__weakref__',)

    def __init__(self):
        _SESSIONS[self] = {'references': {}, 'proofs': set()}


def _state(session):
    require(type(session) is AdmissionSession and session in _SESSIONS, 'Use an internal live admission session')
    return _SESSIONS[session]


def _identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'A real nonsymlink artifact is required')
    identity = _identity(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(block)
    require(identity == _identity(path), 'Artifact changed during complete streaming hash')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': identity[2]}


def _check(record, session):
    require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}
            and type(record['path']) is str and type(record['bytes']) is int and record['bytes'] >= 0
            and type(record['sha256']) is str and re.fullmatch('[0-9a-f]{64}', record['sha256']),
            'A complete literal SHA256/byte reference is required')
    path = Path(record['path']).absolute()
    require(path == path.resolve() and path.is_file(), 'Artifact path is not a real file')
    records = _state(session)['references']
    previous = records.get(str(path))
    require(previous is None or previous[0] == record, 'Conflicting artifact identity')
    identity = _identity(path)
    if previous is None or identity != previous[1] or record['bytes'] <= 16 * 1024**2:
        require(reference(path) == record, 'Bound artifact changed: ' + str(path))
        records[str(path)] = (deepcopy(record), identity)
    return path


def _ref(value, session):
    record = value if isinstance(value, dict) else reference(value)
    _check(record, session)
    return deepcopy(record)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate evidence JSON key')
        value[key] = item
    return value


def _read(record, session):
    with _check(record, session).open() as stream:
        return json.load(stream, object_pairs_hook=_unique,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite evidence JSON')))


def _same(left, right):
    """Actual workbook copies may use different paths; both refs are checked."""
    return all(left[key] == right[key] for key in ('sha256', 'bytes'))


def _walk_refs(value, session):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            _check(value, session)
        else:
            for item in value.values():
                _walk_refs(item, session)
    elif isinstance(value, list):
        for item in value:
            _walk_refs(item, session)


def _recipe():
    paths = [Path(__file__), Path(spec.__file__), Path(ledger.__file__), Path(excel.__file__), Path(validate.__file__),
             Path(catalog.__file__), catalog.DEFAULT_CATALOG,
             Path(streamed_native.__file__), streamed_native.KERNEL, Path(check_masks.__file__), check_masks.KERNEL,
             Path(resource_engine.__file__)]
    return {str(path): reference(path) for path in paths}


def _counts(n):
    spec.project_ids(n)
    return {'formula_count': 1981*n + 18083, 'financial_formula_count': 540*n + 9311,
            'provided_arithmetic_formula_count': 1440*n + 8772, 'decision_formula_count': n}


def _rank(public, claim, forward):
    require(type(claim) is dict and set(claim) == {'mask_hex', 'objective_pence', 'scenario_npvs_pence'}, 'Complete reference rank required')
    plan = spec.plan_from_mask_hex(public, claim['mask_hex'])
    require(forward['plan'] == plan and forward['feasible'] is True
            and forward['objective_pence'] is not None
            and claim['objective_pence'] == str(forward['objective_pence'])
            and claim['scenario_npvs_pence'] == {sid: str(forward['scenarios'][sid]['npv_pence']) for sid in spec.SCENARIO_IDS}
            and all(forward['scenarios'][sid]['feasible'] is True and forward['scenarios'][sid]['all_journals_balance'] is True
                    for sid in spec.SCENARIO_IDS), 'Independent Decimal rank or journal does not match')
    return plan


def _search_resources(proof, completion, profile, session):
    before = _read(proof['actual_A_resource_before'], session)
    after = _read(proof['actual_A_resource_after'], session)
    expected = profile['docker_resources']['source']
    for record in (before, after):
        require(re.fullmatch('[0-9a-f]{64}', record.get('container_id', '')) is not None
                and record['container_id'] == before['container_id']
                and record['image_id'] == profile['image']['id'] and record['user'] in ('0', '0:0'),
                'Actual A container/image identity differs')
        resources = record['resources']
        require(resources['NanoCpus'] == expected['cpus'] * 10**9
                and resources['Memory'] == expected['memory_bytes'] and resources['PidsLimit'] == expected['pids_limit']
                and all(type(resources[key]) is int for key in ('NanoCpus', 'Memory', 'PidsLimit'))
                and resources['NetworkMode'] == 'none', 'Actual A CPU/RAM/PID/network enforcement differs')
    require(before['state']['Status'] == 'created' and before['state']['Running'] is False
            and after['state']['Running'] is False and after['state']['ExitCode'] == 0
            and after['state']['OOMKilled'] is False and completion['native_exit_code'] == 0,
            'The actual A search did not complete successfully')


def _reference_proof(public, proof, profile, session):
    require(proof.get('kind') == 'complete_sparse_capital_semantic_reference_proof'
            and type(proof.get('version')) is int and proof['version'] == 1
            and proof.get('passed') is True and proof.get('complete') is True
            and proof.get('two_complete_independent_searches_claimed') is False,
            'A complete prospective semantic reference proof is required')
    canonical = spec.canonical_sha(public)
    n = len(public['projects'])
    require(proof['public_spec_sha256'] == canonical and proof['project_count'] == n
            and proof['complete_plan_count'] == str(1 << n), 'Reference public scope differs')
    # These frozen validators check real streams, not the outer passed flags.
    projection = streamed_native.validate_execution(_ref(proof['native_projection'], session))
    opposite = check_masks.validate_execution(_ref(proof['opposite_B_all_leaf_execution'], session),
        expected_core='B', expected_public_sha=canonical, expected_masks=projection['masks'])
    require(projection['public_spec_sha256'] == canonical and projection['project_count'] == n
            and opposite['checks_partition_backend'] == 'A'
            and opposite['row_count'] == projection['counts']['leaves']
            and _same(opposite['outcomes'], projection['claimed_outcomes']),
            'Every opposite-core 40B leaf result must match the complete ordered projection')
    require(proof['best'] == projection['best'] and proof['runnerup'] == projection['runnerup']
            and proof['actual_partition_regions'] == projection['counts']['regions']
            and proof['actual_financial_leaves'] == projection['counts']['leaves'], 'Reference ranks or complete counts differ')
    gap = int(proof['best']['objective_pence']) - int(proof['runnerup']['objective_pence'])
    require(proof['best']['mask_hex'] != proof['runnerup']['mask_hex'] and gap >= 1 and proof['gap_pence'] == str(gap),
            'One distinct best and an actual strictly lower runner are required')
    completion = _read(proof['actual_A_native_completion'], session)
    summary = completion['native_summary']
    require(completion['native_exit_code'] == 0 and summary['kind'] == 'sparse_capital_A_intermediate_search'
            and summary['status'] == 'completed_intermediate' and summary['partition_coverage_complete'] is True
            and summary['stop_reason'] == '' and summary['project_count'] == n
            and summary['covered_plan_count'] == summary['combinatorial_plan_count'] == str(1 << n)
            and summary['best'] == proof['best'] and summary['runnerup'] == proof['runnerup']
            and summary['emitted_regions'] == projection['counts']['regions']
            and summary['bound_regions'] == projection['counts']['bound']
            and summary['infeasible_regions'] == projection['counts']['infeasible']
            and _same(completion['partition'], projection['partition']), 'Actual full A partition completion differs')
    started = _read(proof['started'], session)
    require(started['public_spec_sha256'] == canonical and started['opposite_financial_core'] == 'B'
            and _same(started['complete_native_execution'], proof['actual_A_native_completion'])
            and _read(started['native_summary'], session) == summary, 'Before-verification identity differs')
    _search_resources(proof, completion, profile, session)
    decimals = {}
    for name in ('best', 'runnerup'):
        claimed = _read(proof['independent_Decimal'][name], session)
        plan = spec.plan_from_mask_hex(public, proof[name]['mask_hex'])
        independently_replayed = ledger.simulate(public, plan)
        require(claimed == independently_replayed, 'Independent full Decimal journal changed')
        _rank(public, proof[name], independently_replayed)
        decimals[name] = independently_replayed
    _walk_refs(proof, session)
    _walk_refs(projection, session)
    _walk_refs(opposite, session)
    return projection, opposite, decimals


def _normal_value(value):
    if isinstance(value, (datetime, date)):
        return ('date', value.date().isoformat() if isinstance(value, datetime) else value.isoformat())
    if type(value) in (int, float):
        require(math.isfinite(value), 'Non-finite actual cache')
        return ('number', Decimal(str(value)))
    return (type(value).__name__, value)


@lru_cache(maxsize=131072)
def _tokens(formula):
    return tuple(validate._formula_tokens(formula))


def _address(sheet, cell):
    return "'" + sheet.replace("'", "''") + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', cell)


def _audit_cache_pass(path, public, plan, bindings, expected, report, counts):
    """Read actual formula definitions/caches once; retain no loaded workbook."""
    require(all(type(report.get(key)) is int and report[key] == value for key, value in counts.items())
            and report.get('checked_cells') == counts['formula_count']
            and report.get('mismatches') == [] and report.get('control_mismatches') == [], 'Financial audit count or mismatch scope differs')
    require(all(report.get(key) is True for key in ('passed', 'workbook_structure_verified',
        'all_formula_cells_independently_covered', 'all_scenarios_feasible', 'all_journals_balance'))
        and report.get('optimality_or_uniqueness_certified') is False, 'Recorded financial audit boundary is inconsistent')
    formulas = bindings['financial_bindings'] + bindings['arithmetic_bindings']
    formulas += [{**row, 'formula': '=' + str(plan[row['project_id']])} for row in bindings['decision_bindings']]
    definitions = {(row['sheet'], row['cell']): row['formula'] for row in formulas}
    literals = {(row['sheet'], row['cell']): row for row in bindings['literal_bindings']}
    require(len(definitions) == len(formulas) == counts['formula_count'] and len(literals) == len(bindings['literal_bindings'])
            and not set(definitions) & set(literals), 'Duplicate or overlapping formula/literal bindings')
    records = {row['address']: row for row in report['cell_checks']}
    require(len(records) == len(report['cell_checks']) == counts['formula_count']
            and set(records) == set(expected), 'All distinct independent cell checks are required')
    actual_formulas, actual_literals, seen, literal_values = set(), set(), {}, {}
    formulas_book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    caches_book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        require(formulas_book.sheetnames == caches_book.sheetnames == bindings['sheet_names'], 'Actual worksheet scope differs')
        for sheet, cache_sheet in zip(formulas_book, caches_book, strict=True):
            for definition_row, cache_row in zip(sheet.iter_rows(), cache_sheet.iter_rows(), strict=True):
                for cell, cache in zip(definition_row, cache_row, strict=True):
                    if cell.value is None:
                        require(cache.value is None, 'An unbound cache appears in an empty definition')
                        continue
                    key = sheet.title, cell.coordinate
                    if cell.data_type == 'f':
                        actual_formulas.add(key)
                        require(key in definitions and (cell.value == definitions[key] or _tokens(cell.value) == _tokens(definitions[key])),
                                'Actual financial formula definition differs')
                        address = _address(*key)
                        value = expected[address]
                        matches = cache.value in (None, '') if value is None else type(cache.value) in (int, float) and math.isfinite(cache.value) and cache.value == value
                        require(matches, 'Actual cache differs from the independent financial journal')
                        record = records[address]
                        require(record.get('matched') is True and record.get('formula_matches') is True
                                and type(record['expected_independent']) is type(value) and record['expected_independent'] == value
                                and _normal_value(record['observed']) == _normal_value(cache.value), 'Recorded audit is not the actual checked cache')
                    else:
                        actual_literals.add(key)
                        require(key in literals, 'Actual unbound supplied literal')
                        declared = literals[key]
                        if declared['kind'] == 'date':
                            require(isinstance(cell.value, (datetime, date))
                                    and _normal_value(cell.value)[1] == declared['value'], 'Public calendar literal differs')
                        else:
                            require(type(cell.value).__name__ == declared['kind'] and cell.value == declared['value'], 'Public literal type/value differs')
                        require(_normal_value(cache.value) == _normal_value(cell.value), 'Literal cache differs')
                        literal_values[key] = cell.value
                    if cache.value not in (None, ''):
                        seen[key] = _normal_value(cache.value)
        require(actual_formulas == set(definitions) and actual_literals == set(literals), 'Complete actual formula/literal coverage differs')
        def value_at(item):
            return literal_values[item['sheet'], item['cell']]
        for row in bindings['input_bindings']:
            value = public
            for component in row['path']:
                value = value[component]
            actual = value_at(row)
            require(type(actual) is type(value) and actual == value, 'Labelled public primitive differs')
        text = ''.join(value_at(row) for row in bindings['public_spec_chunks'])
        require(spec.canonical_sha(json.loads(text, object_pairs_hook=_unique)) == spec.canonical_sha(public), 'Embedded public specification differs')
        require([value_at(row) for row in bindings['public_rule_cells']] == list(excel.PUBLIC_RULES)
                and bindings['public_rules'] == list(excel.PUBLIC_RULES), 'Public financial policy differs')
    finally:
        formulas_book.close()
        caches_book.close()
    return seen


def _resource_calls(prototype, profile_ref, profile, session):
    calls = prototype['actual_LO_calls']
    runtime = prototype['runtime']
    require(len(calls) == 3 and [row.get('index') for row in calls] == [1, 2, 3]
            and len(runtime['actual_resource_receipts']) == 3
            and runtime.get('image_id') == profile['image']['id']
            and runtime.get('runtime_profile') == profile and runtime.get('runtime_profile_binding') == profile_ref
            and runtime.get('backend') == 'libreoffice_uno_docker' and runtime.get('role') == 'source'
            and runtime.get('network') == 'none' and runtime.get('macro_execution') == 'never'
            and runtime.get('external_updates') == 'never' and runtime.get('actual_calculation_calls_recorded') == 3,
            'Three actual resource-bound source passes are required')
    require(_same(calls[0]['output'], prototype['workbook'])
            and all(_same(calls[i]['input'], calls[i-1]['output']) for i in (1, 2)), 'Actual LO input/output chain differs')
    for call, receipt_ref in zip(calls, runtime['actual_resource_receipts'], strict=True):
        require(call.get('completed') is True and type(call.get('elapsed_seconds')) in (int, float)
                and 0 < call['elapsed_seconds'] <= profile['timeouts']['workbook_file_seconds'], 'Actual LO call did not complete in its budget')
        receipt = _read(receipt_ref, session)
        requested = profile['docker_resources']['source']
        require(receipt.get('kind') == 'resource_bound_libreoffice_call' and type(receipt.get('version')) is int and receipt['version'] == 1
                and receipt.get('status') == 'completed' and receipt.get('role') == 'source'
                and receipt.get('profile') == profile_ref and receipt.get('profile_canonical_sha256') == spec.canonical_sha(profile)
                and receipt.get('image_id') == profile['image']['id'] and _same(receipt['source'], call['input'])
                and _same(receipt['output'], call['output']) and receipt['destination'] == receipt['output']['path']
                and receipt.get('implementation') == _ref(resource_engine.__file__, session)
                and receipt.get('requested_resources') == requested
                and receipt.get('actual_resources_verified') is True
                and receipt.get('actual_resources') == {'cpus_nanoseconds': requested['cpus']*10**9,
                    'memory_bytes': requested['memory_bytes'], 'pids_limit': requested['pids_limit']}
                and all(type(x) is int for x in receipt['actual_resources'].values())
                and re.fullmatch('[0-9a-f]{64}', receipt.get('container_id', '')) is not None
                and receipt['workbook_file_timeout_seconds'] == profile['timeouts']['workbook_file_seconds']
                and receipt['verifier_total_timeout_seconds'] == profile['timeouts']['verifier_total_seconds']
                and receipt['solver_tool_budget'] == profile['solver_tool_budget'], 'Actual LO resource/image/workbook enforcement differs')
        command = receipt['create_command']
        require(command[:2] == ['docker', 'create'] and command[-3:] == [profile['image']['id'], '/tmp/source.xlsx', '/tmp/result.xlsx']
                and all(command[command.index(flag)+1] == value for flag, value in (
                    ('--memory', str(requested['memory_bytes'])), ('--cpus', str(requested['cpus'])),
                    ('--pids-limit', str(requested['pids_limit'])), ('--network', 'none'))), 'Bound source create command differs')
        started = datetime.fromisoformat(receipt['started_at'])
        finished = datetime.fromisoformat(receipt['finished_at'])
        require(started.tzinfo is not None and finished.tzinfo is not None and started < finished, 'Actual LO timestamps differ')
        _walk_refs(receipt, session)
    _walk_refs(calls, session)
    _walk_refs(runtime, session)
    return calls


def _financial_source(public, prototype, reference_proof, decimals, profile_ref, profile, session):
    n = len(public['projects'])
    counts = _counts(n)
    require(prototype.get('kind') == 'sparse_capital_fixed_plan_financial_workbook_engineering_prototype'
            and type(prototype.get('version')) is int and prototype['version'] == 1
            and prototype['public_spec_sha256'] == spec.canonical_sha(public)
            and prototype['physical_formula_count'] == counts['formula_count']
            and prototype['profile_id'] == reference_proof['profile_id']
            and reference_proof['financial_formula_count'] == counts['formula_count']
            and _same(prototype['workbook'], reference_proof['financial_workbook']), 'Financial workbook prototype identity differs')
    require(spec.canonical_sha(catalog.build_spec(prototype['profile_id'])) == spec.canonical_sha(public),
            'Prospectively declared public catalog profile differs')
    require(spec.canonical_sha(_read(prototype['public_specification'], session)) == spec.canonical_sha(public), 'Financial source public specification differs')
    plan = spec.validate_plan(public, _read(prototype['prototype_plan'], session))
    require(plan == decimals['best']['plan'], 'Financial source uses a different common investment plan')
    for name, key in (('best', 'best_Decimal'), ('runnerup', 'runnerup_Decimal')):
        require(_read(prototype[key], session) == decimals[name], 'Prototype independent financial journal differs')
    require(prototype['emitter_upstream_binding'] == excel.assert_upstream_recipe(), 'Frozen financial emitter recipe differs')
    bindings = _read(prototype['bindings'], session)  # One parse; no repeated 60-MB binding traversal.
    require(bindings.get('formula_count') == counts['formula_count']
            and len(bindings['financial_bindings']) == counts['financial_formula_count']
            and len(bindings['decision_bindings']) == counts['decision_formula_count']
            and len(bindings['arithmetic_bindings']) == counts['provided_arithmetic_formula_count']
            and bindings.get('gold_plan_supplied') is True and bindings.get('optimisation_performed') is False
            and bindings.get('arithmetic_support_values_are_protected') is False
            and bindings.get('plan_dependent_caches_must_be_cleared_before_task_input') is True
            and bindings.get('task_input_requires_actual_recalculation_and_audit') is True
            and bindings.get('complete_required_D_includes_changed_arithmetic_helpers') is True,
            'Complete untruncated financial/decision/support bindings are required')
    all_values = validate.expected_cells(public, plan, decimals['best'], bindings)
    records = bindings['financial_bindings'] + bindings['arithmetic_bindings'] + bindings['decision_bindings']
    expected = {_address(row['sheet'], row['cell']): all_values[_address(row['sheet'], row['cell'])] for row in records}
    require(len(expected) == counts['formula_count'], 'Independent complete cache coverage differs')
    calls = _resource_calls(prototype, profile_ref, profile, session)
    require(len(prototype['financial_audits']) == 3, 'Every actual pass requires its entire audit')
    first = None
    stability = _read(prototype['stability'], session)
    require(set(stability) == {'pass1_vs_pass2', 'pass1_vs_pass3'}, 'Both exact further-pass stability checks are required')
    for index, (call, audit_ref) in enumerate(zip(calls, prototype['financial_audits'], strict=True)):
        observed = _audit_cache_pass(_check(call['output'], session), public, plan, bindings, expected, _read(audit_ref, session), counts)
        if first is None:
            first = observed
        else:
            report = stability[f'pass1_vs_pass{index+1}']
            require(observed == first and report.get('passed') is True and report.get('sheet_names_equal') is True
                    and report.get('checked_existing_value_cells') == len(first) and report.get('mismatches') == []
                    and report.get('public_note_only_metadata_exception') is None, 'Actual full source cache/literal stability differs')
    _tokens.cache_clear()
    _walk_refs(prototype, session)
    return counts


def admit_source(public_specification, reference_proof, financial_prototype, *, expected_profile=DEFAULT_PROFILE, session=None):
    """Perform complete read-only admission; never trust caller-populated caches."""
    require(session is None or type(session) is AdmissionSession, 'Use an internal live admission session')
    local = AdmissionSession()
    public_ref, reference_ref, source_ref, profile_ref = [_ref(value, local) for value in
        (public_specification, reference_proof, financial_prototype, expected_profile)]
    public = spec.load_spec(_read(public_ref, local))
    proof, prototype = _read(reference_ref, local), _read(source_ref, local)
    profile = resource_engine.load_runtime_profile(_check(profile_ref, local))
    require(profile['id'] == 'entity_group_large_v2' and all(profile['docker_resources'][role] == profile['docker_resources']['source']
            for role in ('source', 'agent', 'verifier')), 'Pinned consistent source/agent/verifier profile is required')
    require(_same(proof['financial_workbook_prototype'], source_ref) and _same(prototype['public_specification'], public_ref)
            and _same(prototype['runtime_profile'], profile_ref), 'Reference/prototype/public/profile cross-binding differs')
    projection, opposite, decimals = _reference_proof(public, proof, profile, local)
    counts = _financial_source(public, prototype, proof, decimals, profile_ref, profile, local)
    recipe = _recipe()
    _walk_refs(recipe, local)
    result = {'kind': KIND, 'version': 1, 'validation_method': METHOD, 'profile_id': proof['profile_id'],
        'project_count': len(public['projects']), 'physical_formula_count': counts['formula_count'],
        'source': deepcopy(prototype['workbook']), 'workbook': deepcopy(prototype['workbook']),
        'source_manifest': source_ref, 'reference_proof': reference_ref, 'public_specification': public_ref,
        'bindings': deepcopy(prototype['bindings']), 'best_plan': deepcopy(decimals['best']['plan']),
        'best': deepcopy(proof['best']), 'runnerup': deepcopy(proof['runnerup']), 'gap_pence': proof['gap_pence'],
        'native_projection': deepcopy(proof['native_projection']), 'opposite_all_leaf_execution': deepcopy(proof['opposite_B_all_leaf_execution']),
        'actual_partition_regions': projection['counts']['regions'], 'actual_financial_leaves': opposite['row_count'],
        'independent_Decimal': deepcopy(proof['independent_Decimal']), 'financial_audits': deepcopy(prototype['financial_audits']),
        'stability': deepcopy(prototype['stability']), 'runtime_profile': profile_ref, 'runtime': deepcopy(prototype['runtime']),
        'current_recipe': recipe, 'one_complete_prefix_and_opposite_all_leaf_reference_verified': True,
        'actual_three_pass_financial_source_verified': True, 'two_complete_independent_searches_claimed': False,
        'task_quality_certified': False, 'independent_public_recovery_certified': False, 'Harbor_certified': False,
        'difficulty_certified': False, 'qualified': False, 'task_count': 0}
    result['verified_artifacts'] = {path: deepcopy(value[0]) for path, value in _state(local)['references'].items()}
    result['artifact_sha256'] = {path: value['sha256'] for path, value in result['verified_artifacts'].items()}
    identity = spec.canonical_sha(result)
    _state(local)['proofs'].add(identity)
    if session is not None:
        target = _state(session)
        for path, value in _state(local)['references'].items():
            require(path not in target['references'] or target['references'][path][0] == value[0], 'Conflicting live session artifact')
        target['references'].update(_state(local)['references'])
        target['proofs'].add(identity)
    return result


def verify_admitted_source(admitted, *, session=None):
    """Fresh processes fully validate; live repeats recheck immutable identities."""
    session = AdmissionSession() if session is None else session
    state = _state(session)
    require(type(admitted) is dict and admitted.get('kind') == KIND
            and type(admitted.get('version')) is int and admitted['version'] == 1
            and admitted.get('validation_method') == METHOD, 'A complete sparse source admission is required')
    identity = spec.canonical_sha(admitted)
    if identity not in state['proofs']:
        actual = admit_source(admitted['public_specification'], admitted['reference_proof'], admitted['source_manifest'],
                              expected_profile=admitted['runtime_profile'], session=session)
        require(actual == admitted, 'Admitted source cannot be reproduced')
    _walk_refs(admitted, session)
    require(admitted['current_recipe'] == _recipe(), 'Current admission recipe differs')
    return deepcopy(admitted)
