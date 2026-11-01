#!/usr/bin/env python3
"""Compose fixed certified donors; calculate each new pair exactly three times."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import subprocess
import threading
import time
from types import FunctionType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
from sheets_factory.workbook.linear_capital_ringfenced_pairs import contract, composition, stream_composition, group_report

PROSPECTIVE = ROOT/'outputs/research/ringfenced_pair_zero_service_preparation_20261101T010044Z/pool/prospective.json'
PARSE_CACHE = ROOT/'outputs/research/ringfenced_pair_completed_parse_cache_20261101T014754Z/cache_envelope.json'
PARSE_CACHE_SHA = 'c5fc5423fad62b36f6f72d27f7cfc54fb5b2773d7d4e67997e69d32efa8ae40e'
OLD_SOURCE = ROOT/'outputs/research/ringfenced_pair_R2_01_same_process_source_revision3_20261101T024100Z/source/terminal.json'
DESIGN = ROOT/'outputs/research/ringfenced_first5_retained10_design_20261101T074000Z/freeze.json'
DESIGN_SHA = 'fa8ec5498c45d561570e4c1ba41f3fa9687b969386af74b5cfb1fe3a45326312'
FIRST_FIVE = ('R2-01', 'R2-02', 'R2-03', 'R2-04', 'R2-05')
KIND = 'prepared_cached_ringfenced_pair_source_v1'
TERMINAL_KIND = 'completed_cached_ringfenced_pair_source_v1'
GEOMETRY = {'formulas': 2494958, 'nonempty': 3547571, 'targets': 3044678}
LOCAL_GEOMETRY = composition.LOCAL_GEOMETRY
SOURCE_FIELDS = ('financial_audits', 'actual_engine_calls', 'stability', 'geometry', 'bindings',
                 'independent_A_expected', 'independent_B_expected', 'source_preparation', 'financial_crosscheck')
ARITHMETIC_PROOF_FIELDS = {'npv_exact', 'npv_unrounded_decimal', 'arithmetic_safety', 'arithmetic_bounds', 'financial_implementation'}


def module(path, sha, name):
    require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha, 'A frozen source dependency changed')
    loader = importlib.util.spec_from_file_location(name, path); value = importlib.util.module_from_spec(loader); loader.loader.exec_module(value)
    return value


ref, read, require = contract.reference, contract.read, contract.require


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    return contract.write(path, value)


helpers = module(ROOT/'scripts/resume_ringfenced_pair_task8_remaining_revision2.py',
    '8a5c88d53f80dfdbff9936f50c40257cbec71759d2747871cf1e852943c6f145', '_cached_pair_complete_native_helpers')
dual = helpers.v1
session3 = module(ROOT/'scripts/run_ringfenced_pair_session_revision3.py',
    'b3cc7cc25c667a997614f81c3411810e2bea30f8a5d1cd346f9e8d92e892d3af', '_cached_pair_prior_format_fix')
PROFILE = dual.PROFILE


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def same_business_values(a, b):
    """Compare all posted financial fields; the two arithmetic proofs differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        left = set(a)-ARITHMETIC_PROOF_FIELDS; right = set(b)-ARITHMETIC_PROOF_FIELDS
        return left == right and all(same_business_values(a[key], b[key]) for key in left)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_business_values(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def exact_matrix(model, plan, expected_objective):
    ids = model['project_ids']
    require(len(ids) == len(set(ids)) == 360 and set(plan) == set(ids)
            and all(type(plan[key]) is int and plan[key] in (0, 1) for key in ids), 'The complete binary plan changed')
    require(len(model['rows']) == 941 and len(model['objective_pence']) == 360, 'The complete integer matrix inventory changed')
    bits = [plan[key] for key in ids]
    for row in model['rows']:
        coefficients = row['coefficients']
        require(len(coefficients) == 360 and all(type(v) is int for v in coefficients) and type(row['limit']) is int,
                'All original constraints must remain exact integers')
        require(sum(a*b for a, b in zip(coefficients, bits)) <= row['limit'], 'A certified plan violates an original integer row')
    require(all(type(value) is int for value in model['objective_pence']) and type(expected_objective) is int
            and sum(a*b for a, b in zip(model['objective_pence'], bits)) == expected_objective, 'The exact posted objective changed')
    return {'rows_checked': 941, 'coefficients_checked': 338760, 'objective_pence': expected_objective, 'passed': True}


def formula_rename(formula, sheets, local_sheet=None, defined_name=False):
    """Rename only local sheet qualifiers, with a byte-exact inverse witness."""
    require(type(formula) is str and all(type(k) is type(v) is str for k, v in sheets.items())
            and len(set(sheets.values())) == len(sheets), 'Use a bijective worksheet map')
    token = re.compile(r"'(?:[^']|'')+'!|[A-Za-z_][A-Za-z0-9_.]*!")
    strings = re.compile(r'"(?:[^"]|"")*"')
    changes = []
    def segment(text):
        def change(match):
            raw = match.group(); qualifier = raw[:-1]
            if match.start():
                require(text[match.start()-1] not in ':[]', 'External or three-dimensional sheet references are not local')
            name = qualifier[1:-1].replace("''", "'") if qualifier.startswith("'") else qualifier
            require(name in sheets, 'A formula refers outside its certified local mandate')
            replaced = "'" + sheets[name].replace("'", "''") + "'!"
            changes.append((replaced, raw)); return replaced
        return token.sub(change, text)
    pieces = []; cursor = 0
    for match in strings.finditer(formula):
        pieces += [segment(formula[cursor:match.start()]), match.group()]; cursor = match.end()
    pieces.append(segment(formula[cursor:])); result = ''.join(pieces)
    restored = []; cursor = index = 0
    for match in strings.finditer(result):
        text = result[cursor:match.start()]
        def undo(item):
            nonlocal index
            require(index < len(changes) and item.group() == changes[index][0], 'The renamed qualifier does not have an exact inverse')
            raw = changes[index][1]; index += 1; return raw
        restored += [token.sub(undo, text), match.group()]; cursor = match.end()
    def undo_last(item):
        nonlocal index
        require(index < len(changes) and item.group() == changes[index][0], 'The renamed qualifier does not have an exact inverse')
        raw = changes[index][1]; index += 1; return raw
    restored.append(token.sub(undo_last, result[cursor:]))
    require(''.join(restored) == formula and index == len(changes), 'The worksheet rename is not byte reversible')
    return result


def parse_evidence(prospective=PROSPECTIVE):
    frozen = contract.validate_prospective(prospective)
    require(ref(PARSE_CACHE)['sha256'] == PARSE_CACHE_SHA, 'The witnessed full-ten grammar cache changed')
    cache = read(PARSE_CACHE); old = session3._N
    require(cache['identity'] == old['_parse_identity'](ref(prospective), frozen), 'The grammar proof belongs to another whole inventory')
    execution = cache['execution']
    report = old['_completed_parse'](cache['preflight'], ref(prospective), frozen, execution['log'], execution['summary'],
                                     execution['database'], execution['observed_process_exit_code'])
    require(report['passed'] and report['total_physical_formulas'] == 12473280, 'The original complete syntax execution is incomplete')
    return frozen, cache['preflight'], {'cache': ref(PARSE_CACHE), 'execution': execution, 'report': cache['preflight']}


def cached_local(context, alias_rows):
    """Verify retained whole evidence and exact matrices, without new forwards."""
    source = read(context['source_manifest']); result = read(context['reference']); public = read(context['specification'])
    require(source['workbook'] == context['workbook'] and source['independent_reference'] == context['reference']
            and source['winner_plan_private'] == result['winner_plan'] and source['winner_objective_pence_private'] == result['winner_objective_pence']
            and source['source_financially_verified'] and result['passed'] and result['unique_best'], 'The immutable local lineage changed')
    for field in SOURCE_FIELDS:
        value = source[field]
        if isinstance(value, dict) and set(value) == {'path', 'sha256', 'bytes'}: contract.checked(value)
        elif field == 'financial_audits':
            for record in value: contract.checked(record)
    for path, sha in source['source_recipe_sha256'].items():
        require(ref(path)['sha256'] == sha, 'A source recipe differs from its completed proof')
    require(len(source['actual_engine_calls']) == len(source['financial_audits']) == 3
            and source['LO_calls'] == 3 and source['source_copy']['same_bytes'] is True
            and source['source_copy']['from']['sha256'] == source['workbook']['sha256']
            and source['source_copy']['to'] == source['workbook'], 'The local three-call source chain is incomplete')
    expected_a, expected_b = read(source['independent_A_expected']), read(source['independent_B_expected'])
    require(same_business_values(expected_a['projects'], expected_b['projects']) and same_business_values(expected_a['group'], expected_b['group']),
            'Complete retained A/B financial outputs disagree')
    expected_shas = canonical(expected_a), canonical(expected_b)
    del expected_a, expected_b
    previous = None
    for call, report_ref in zip(source['actual_engine_calls'], source['financial_audits'], strict=True):
        report = read(report_ref); actual = read(call['actual_resource_evidence']['terminal'])
        require(call['completed'] is True and actual['status'] == 'completed' and actual['actual_resources_verified'] is True
                and actual['source'] == call['input'] and actual['output'] == call['output']
                and report['audited_file'] == call['output'] and report['passed'] is True
                and report['expected_A_sha256'] == expected_shas[0] and report['expected_B_sha256'] == expected_shas[1]
                and report['all_physical_formulas_checked'] == 1247328 and report['all_financial_locators_checked'] == 1521827
                and report['all_expected_values_checked'] == 1773566 and report['mismatch_count'] == report['native_error_count'] == 0
                and report['all_values_checked'] is True and report['differences_truncated'] is False,
                'The retained complete native/A/B audit no longer binds the actual source')
        for record in (call['input'], call['output'], call['started_receipt']): contract.checked(record)
        if previous: require(call['input'] == previous, 'The original native source chain was reordered')
        previous = call['output']
    stability = read(source['stability'])
    require(stability.get('passed') is True, 'The retained whole-source stability proof failed')
    matrix_checks = {}
    for side in ('A', 'B'):
        model = read(result['model_'+side]); require(model['specification_sha256'] == result['specification_sha256'], 'A matrix belongs to another public case')
        matrix_checks[side] = {label: exact_matrix(model, result[plan], result[objective]) for label, plan, objective in
            (('best', 'winner_plan', 'winner_objective_pence'), ('runner', 'runner_plan', 'runner_objective_pence'))}
    for phase in ('best', 'runner'):
        validation = read(result['solver_validations'][phase]); solver = validation['solver']
        require(validation['checked_optimal'] is True and solver['checked_optimal'] is True
                and validation['terminal'] == result['solver_receipts'][phase], 'The original optimal/excluded-winner proof changed')
    for row in alias_rows:
        contract.checked(row['host'])
    geometry = read(source['geometry'])
    require(geometry['physical_formula_count'] == 1247328 and geometry['nonempty_cells'] == 1773566,
            'The entire local native geometry changed')
    # The remaining original hydrator is pure schema/report extraction. Its two
    # expensive providers are replaced by the complete checks above, not flags.
    local = composition._N['_hydrate'](context, SimpleNamespace(validate_completed=lambda record: result),
        SimpleNamespace(validate_source=lambda record: source))
    local['cached_hydration_seconds'] = local.pop('cold_validation_seconds')
    local['cached_evidence_validation'] = {'source': context['source_manifest'], 'reference': context['reference'],
        'source_A_B_expected': [source['independent_A_expected'], source['independent_B_expected']],
        'complete_native_audits': source['financial_audits'], 'exact_matrix_checks': matrix_checks,
        'retained_solver_host_artifacts': alias_rows, 'new_financial_forwards': 0, 'new_optimizer_calls': 0}
    return local


def preflight(pair, prospective=PROSPECTIVE):
    require(pair in FIRST_FIVE, 'Only the predeclared first five pairs may enter this cohort')
    require(ref(DESIGN)['sha256'] == DESIGN_SHA and read(DESIGN)['original_whole_pair_pool'] == ref(prospective),
            'The first-five design must retain its original frozen whole pool')
    frozen, parsed, parse_proof = parse_evidence(prospective)
    contexts = contract.pair_contexts(frozen['contexts'], pair)
    aliases = session3._P['selected_metadata'](ref(prospective), pair)
    locals_ = []
    for context in contexts:
        local_aliases = [value for value in aliases if value['native_terminal'] in list(read(context['reference'])['solver_receipts'].values())]
        locals_.append(cached_local(context, local_aliases))
    a, b = composition.compose_values_a(locals_), composition.compose_values_b(locals_)
    require(a == b, 'Two independent exact group compositions disagree')
    return frozen, locals_, {'kind': 'cached_composed_two_ringfenced_capital_best_runner_certificate_v1', 'version': 1,
        'pair_id': pair, 'contract': frozen['contracts'][pair], 'composition': a,
        'local_whole_evidence': [{key: value for key, value in local.items() if key not in ('best', 'runner')} for local in locals_],
        'donors': [{'id': value['id'], 'display_name': mandate['display_name'], 'prefix': mandate['sheet_prefix'],
                    'workbook': value['workbook'], 'source_manifest': value['source_manifest'], 'reference': value['reference']}
                   for value, mandate in zip(locals_, read(frozen['contracts'][pair])['mandates'], strict=True)],
        'geometry_before_global_header_and_reports': {key: sum(value['geometry'][key] for value in locals_) for key in LOCAL_GEOMETRY},
        'FM_mask_projection_including_two_completion_gates': 3044376, 'all_ten_pure_preflight': read(parsed),
        'retained_full_ten_parse_evidence': parse_proof, 'mathematical_composition_certified': True,
        'cached_complete_local_reference_count': 2, 'cached_complete_local_source_count': 2,
        'cold_local_reference_count': 0, 'cold_original_source_count': 0, 'independent_group_arithmetic_implementations': 2,
        'new_financial_universe_forwards': 0, 'new_solver_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'new_group_source_admitted': False, 'qualified': False, 'prospective': ref(prospective),
        'coupled_720_project_MIP_claimed': False, 'cohort_design': ref(DESIGN), 'recipe': recipes()}


def recipes():
    return [ref(path) for path in (__file__, helpers.__file__, dual.__file__, session3.__file__, contract.__file__, composition.__file__,
        stream_composition.__file__, group_report.__file__, PROFILE)]


def composer():
    original = stream_composition._N; namespace = dict(original)
    syntax = SimpleNamespace(**{**vars(original['syntax']), '__file__': __file__, 'rewrite_formula': formula_rename})
    namespace.update(syntax=syntax, MERGER_SHA256=ref(__file__)['sha256'])
    for name, value in original.items():
        if isinstance(value, FunctionType) and value.__globals__ is original:
            function = FunctionType(value.__code__, namespace, name, value.__defaults__, value.__closure__)
            function.__kwdefaults__ = value.__kwdefaults__; namespace[name] = function
    return namespace['_compose']


def raw_cell(cell):
    if cell is None or cell['value'] is None or cell['value'] == '': return ('empty', None)
    value = cell['value']
    if type(value) in (int, float): return ('number', str(Decimal(str(value)).normalize()))
    return cell['data_type'], value


def audit_source(path, frozen, *, cold=False):
    local = read(frozen['local_composition']); plan = read(frozen['report_plan']); expected = read(frozen['report_expected'])
    count = formulas = 0; raw_digest = hashlib.sha256(); typed_digest = hashlib.sha256()
    with ExitStack() as stack:
        def opened(value):
            result = load_workbook(value, read_only=True, data_only=True, keep_links=False); stack.callback(result.close)
            return result, {sheet.title: sheet for sheet in result.worksheets}
        wb, sheets = opened(path)
        names = [name for donor in local['donors'] for name in donor['sheet_map'].values()]+[group_report.SHEET]
        require(wb.sheetnames == names and wb.calculation.iterate is not True and not list(wb.defined_names),
                'The complete composed structure or defined names changed')
        for donor, mapped in zip(frozen['donors'], local['donors'], strict=True):
            baseline, source_sheets = opened(donor['workbook']['path'])
            require(list(source_sheets) == list(mapped['sheet_map']) and baseline.epoch == wb.epoch, 'A whole local worksheet map changed')
            for old, new in mapped['sheet_map'].items():
                before, merges = dual.sheet_cells(source_sheets[old]); after, actual_merges = dual.sheet_cells(sheets[new])
                require(set(before) == set(after) and merges == actual_merges, 'A local physical cell scope or merged layout changed')
                for point, wanted in before.items():
                    actual = after[point]; require(actual['data_type'] != 'e', 'The composed native source has an error')
                    count += 1
                    if wanted['formula'] is not None:
                        formulas += 1; target = formula_rename(wanted['formula'], mapped['sheet_map'], local_sheet=old)
                        require(dual.same_formula(actual['formula'], target), 'A financial formula is no longer its bijective source translation')
                        require(actual['value'] is None if cold else dual.grader._normalized_cell(actual, wanted['value'], wb.epoch)
                                == dual.grader._normalized_cell(wanted, wanted['value'], baseline.epoch), 'A complete local financial native value differs')
                        if not cold:
                            require(raw_cell(actual) == raw_cell(wanted), 'A retained raw local financial value differs')
                    else:
                        require(actual['formula'] is None and raw_cell(actual) == raw_cell(wanted), 'A supplied fact, policy, NA field or label changed')
                    raw_digest.update(json.dumps((new, point, raw_cell(actual)), separators=(',', ':'), default=str).encode()+b'\n')
                    typed_digest.update(json.dumps((new, point, dual.grader._normalized_cell(actual, wanted['value'], wb.epoch)), separators=(',', ':'), default=str).encode()+b'\n')
        report, _ = dual.sheet_cells(sheets[group_report.SHEET]); located = {get_column_letter(p[1])+str(p[0]): value for p, value in report.items()}
        require(set(located) == set(plan['formulas']) | set(plan['literals']), 'The complete group report scope changed')
        for point, value in located.items():
            count += 1; require(value['data_type'] != 'e', 'A group report value is an error')
            if point in plan['formulas']:
                formulas += 1; require(dual.same_formula(value['formula'], plan['formulas'][point]), 'A group report formula changed')
                want = expected[point]
                require(value['value'] is None if cold else ((type(value['value']) is bool and value['value'] == want['value'])
                        if want['type'] == 'boolean' else Decimal(str(value['value'])) == Decimal(want['value'])), 'Independent A/B group finance differs')
            else:
                require(value['formula'] is None and type(value['value']) is type(plan['literals'][point]) and value['value'] == plan['literals'][point], 'A public group label/policy changed')
            raw_digest.update(json.dumps((group_report.SHEET, point, raw_cell(value)), separators=(',', ':'), default=str).encode()+b'\n')
            typed_digest.update(json.dumps((group_report.SHEET, point, dual.grader._normalized_cell(value, value['value'], wb.epoch)), separators=(',', ':'), default=str).encode()+b'\n')
    require((count, formulas) == (GEOMETRY['nonempty'], GEOMETRY['formulas']), 'A source audit did not cover every cell and formula')
    return {'kind': 'complete_cached_pair_financial_formula_literal_native_audit_v1', 'passed': True, 'audited_file': ref(path), 'cells_checked': count,
        'formulas_checked': formulas, 'native_error_count': 0, 'mismatch_count': 0, 'provided_literals_exact': True,
        'all_local_financial_values_checked_against_retained_AB_native_sources': True,
        'all_new_group_fields_checked_against_two_independent_compositions': True, 'cold_formula_caches_empty': cold,
        'raw_value_sha256': raw_digest.hexdigest(), 'typed_value_sha256': typed_digest.hexdigest(), 'new_financial_forwards': 0}


def prepare(pair, output, prospective=PROSPECTIVE):
    require(pair in FIRST_FIVE[1:], 'R2-01 must reuse its existing completed source, never rebuild it')
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Use a new fixed-pair source directory')
    _, _, certificate = preflight(pair, prospective); output.mkdir(parents=True)
    cert_ref = write(output/'certificate.json', certificate)
    local = composer()(certificate['donors'], output/'locals_uncalculated.xlsx', mode='goal', target_count=3044376,
        expected_census={'sheets': 740, 'formulas': 2494656, 'nonempty': 3547132},
        ancestry={'composition_certificate': cert_ref, 'native_source_or_quality_inherited': False})
    local_ref = write(output/'composition.json', local)
    report = session3._report_namespace(group_report)
    plan = report.plan(certificate['contract'], local); expected = report.expectations(certificate, plan)
    folder = output/'source'; folder.mkdir()
    emission = report.append_report(local, certificate['contract'], folder/'cold_start.xlsx')
    import yaml
    frozen = {'kind': KIND, 'version': 1, 'pair_id': pair, 'certificate': cert_ref, 'local_composition': local_ref,
        'donors': certificate['donors'], 'public_contract': certificate['contract'], 'cold_start': emission['output'],
        'report_plan': write(folder/'report_plan.json', plan), 'report_expected': write(folder/'expected.private.json', expected),
        'report_emission': write(folder/'report_emission.json', emission), 'geometry': emission['geometry'],
        'defined_names': [], 'runtime_profile': ref(PROFILE), 'runtime_profile_value': yaml.safe_load(PROFILE.read_text()),
        'recipe': recipes(), 'stage_order': ['source1', 'source2', 'source3'], 'required_actual_calls': 3,
        'retry': 0, 'new_group_source_admitted': False, 'local_cached_proofs_reused': True,
        'local_optimizer_or_financial_forward_or_native_replays': 0}
    require(frozen['geometry'] == GEOMETRY, 'The complete new pair geometry changed')
    cold = audit_source(emission['output']['path'], frozen, cold=True)
    frozen['cold_audit'] = write(folder/'cold_audit.json', cold)
    return write(folder/'preparation.json', frozen)


def run(preparation, *, port=0):
    f = read(preparation); folder = Path(preparation['path'] if isinstance(preparation, dict) else preparation).parent
    require(f['kind'] == KIND and f['pair_id'] in FIRST_FIVE[1:] and f['recipe'] == recipes()
            and f['geometry'] == GEOMETRY and not (folder/'started.json').exists(), 'Preserve the exact first new pair source attempt')
    cold = read(f['cold_audit'])
    require(cold['passed'] and cold['audited_file'] == f['cold_start'] and cold['cold_formula_caches_empty'] is True
            and cold['cells_checked'] == GEOMETRY['nonempty'] and cold['formulas_checked'] == GEOMETRY['formulas'],
            'The complete newly composed cold input audit is missing')
    reservation = ROOT/'outputs/research/.cached_ringfenced_pair_source_reservations_v1'/(f['pair_id']+'.json')
    write(reservation, {'pair': f['pair_id'], 'preparation': ref(preparation['path'] if isinstance(preparation, dict) else preparation), 'retry': 0})
    audit = dual.AuditStore(folder/'audit', {'id': f['pair_id'], 'status': 'running', 'name': 'Complete cached pair source3', 'target_count': 0})
    server = dual.DashboardServer(audit.snapshot, audit.events, port=port); url = server.start(); started = time.monotonic()
    print(json.dumps({'dashboard_url': url}), flush=True)
    engine = None; calls_started = 0; daemon_before = None
    calls = []; records = {}; observations = []; previous = f['cold_start']; stop = threading.Event()
    def pulse():
        while not stop.wait(15):
            audit.update_run(elapsed_seconds=time.monotonic()-started, actual_calls_started=calls_started, actual_calls_completed=len(calls)); audit.export()
    thread = threading.Thread(target=pulse, daemon=True); thread.start()
    failure = None
    try:
        daemon_before = subprocess.run(['docker', 'info', '--format', '{{.ID}}'], capture_output=True, text=True, check=True).stdout.strip()
        require(bool(daemon_before), 'The actual Docker daemon identity is unavailable')
        write(folder/'started.json', {'dashboard_url': url, 'pid': __import__('os').getpid(), 'retry': 0,
            'daemon_before_id': daemon_before, 'preparation': ref(folder/'preparation.json'), 'recipe': recipes()})
        engine = helpers.engine_class()(ROOT, PROFILE, role='source', receipt_directory=folder/'engine_resources')
        for index in (1, 2, 3):
            name = 'source'+str(index); audit.update_run(stage=name); audit.export()
            tick = time.monotonic(); calls_started += 1
            actual = engine.recalculate(previous['path'], folder/(name+'.xlsx')); output = ref(actual)
            receipt = engine.metadata()['actual_resource_receipts'][-1]; observations.append(dual.resource_check(receipt, source=previous, output=output))
            call = {'index': index, 'role': name, 'input': previous, 'output': output, 'completed': True,
                    'elapsed_seconds': time.monotonic()-tick, 'actual_resource_evidence': {'terminal': receipt,
                    'container_id': observations[-1]['container_id']}}
            calls.append(call); records[name+'_call'] = write(folder/(name+'_terminal.json'), call)
            value = audit_source(output['path'], f); records[name+'_audit'] = write(folder/(name+'_audit.json'), value)
            if index > 1:
                before = read(records['source'+str(index-1)+'_audit'])
                require(value['raw_value_sha256'] == before['raw_value_sha256'] and value['typed_value_sha256'] == before['typed_value_sha256'],
                        'The complete raw/typed native source is not stable')
                records['source'+str(index-1)+'_to_'+name] = write(folder/('source'+str(index-1)+'_to_'+name+'.json'),
                    {'passed': True, 'raw_and_primary_complete_stability': True, 'left': calls[-2]['output'], 'right': output,
                     'raw_sha256': value['raw_value_sha256'], 'typed_sha256': value['typed_value_sha256']})
            previous = output; print(json.dumps({'source_call_completed': index, 'whole_cells_checked': value['cells_checked']}), flush=True)
        cleanup = dual.owned_cleanup(observations)
        require(cleanup['daemon_id'] == daemon_before, 'The owned absence observation belongs to another Docker daemon')
        records['cleanup'] = write(folder/'owned_absence.json', {**cleanup, 'same_daemon_before_after': True})
        require(f['recipe'] == recipes(), 'A frozen source implementation changed')
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
        try:
            if engine is not None:
                for receipt in engine.metadata()['actual_resource_receipts']:
                    value = read(receipt)
                    if value.get('container_id') and receipt not in [item['receipt'] for item in observations]:
                        require(re.fullmatch('[0-9a-f]{64}', value['container_id']), 'An owned failed container ID is incomplete')
                        observations.append({'receipt': receipt, 'container_id': value['container_id']})
            cleanup = dual.owned_cleanup(observations)
            require(daemon_before is not None and cleanup['daemon_id'] == daemon_before, 'Failed cleanup daemon identity is unknown')
            records['failure_cleanup'] = write(folder/'failure_owned_absence.json', {**cleanup, 'same_daemon_before_after': True})
        except BaseException as cleanup_error:
            records['cleanup_unknown'] = write(folder/'cleanup_unknown.json', {'passed': False,
                'type': type(cleanup_error).__name__, 'message': str(cleanup_error), 'owned_absence_proven': False})
    finally:
        stop.set(); thread.join(timeout=1); audit.update_run(status='failed' if failure else 'passed', producer_active=False); audit.export(); server.stop(); audit.db.close()
    terminal = write(folder/'terminal.json', {'kind': TERMINAL_KIND, 'version': 1, 'passed': failure is None, 'failure': failure,
        'pair_id': f['pair_id'], 'preparation': ref(folder/'preparation.json'), 'actual_calls': calls, 'records': records,
        'source': previous, 'actual_calls_started': calls_started, 'actual_calls_completed': len(calls),
        'LO_calls': len(calls), 'source_financially_verified': failure is None, 'elapsed_seconds': time.monotonic()-started,
        'certificate': f['certificate'], 'specification': f['public_contract'], 'local_composition': f['local_composition'],
        'new_local_optimizer_financial_forward_or_native_replays': 0, 'qualified': False, 'model_solver_Harbor_calls': 0, 'retry': 0})
    if failure: raise RuntimeError('Preserve the failed first source; no automatic repeat')
    return terminal


def validate_completed(terminal):
    """Consume the complete new source evidence once; do not replay local sources."""
    value = read(terminal); frozen = read(value['preparation'])
    require(value['kind'] == TERMINAL_KIND and value['version'] == 1 and value['passed'] is True and value['failure'] is None
            and value['source_financially_verified'] is True and value['pair_id'] in FIRST_FIVE[1:]
            and value['actual_calls_started'] == value['actual_calls_completed'] == value['LO_calls'] == 3
            and value['retry'] == value['new_local_optimizer_financial_forward_or_native_replays'] == value['model_solver_Harbor_calls'] == 0,
            'The cached source has not completed its one permitted source3 attempt')
    require(frozen['kind'] == KIND and frozen['pair_id'] == value['pair_id'] and frozen['geometry'] == GEOMETRY
            and frozen['recipe'] == recipes() and frozen['runtime_profile'] == ref(PROFILE)
            and frozen['stage_order'] == ['source1', 'source2', 'source3'] and frozen['required_actual_calls'] == 3
            and frozen['retry'] == frozen['local_optimizer_or_financial_forward_or_native_replays'] == 0,
            'The completed source preparation or implementation binding changed')
    import yaml
    require(frozen['runtime_profile_value'] == yaml.safe_load(PROFILE.read_text()), 'The source profile value changed')
    certificate = read(frozen['certificate']); public = read(frozen['public_contract'])
    require(certificate['pair_id'] == value['pair_id'] == public['pair_id'] and certificate['contract'] == frozen['public_contract']
            and certificate['prospective'] == ref(PROSPECTIVE) and certificate['cohort_design'] == ref(DESIGN)
            and ref(DESIGN)['sha256'] == DESIGN_SHA and certificate['recipe'] == recipes()
            and certificate['mathematical_composition_certified'] is True and certificate['independent_group_arithmetic_implementations'] == 2
            and certificate['cached_complete_local_reference_count'] == certificate['cached_complete_local_source_count'] == 2,
            'The complete pair evidence belongs to another public contract or cohort')
    require(value['certificate'] == frozen['certificate'] and value['specification'] == frozen['public_contract']
            and value['local_composition'] == frozen['local_composition'], 'The source terminal direct lineage changed')
    for key in ('cold_start', 'local_composition', 'report_plan', 'report_expected', 'report_emission', 'cold_audit'):
        contract.checked(frozen[key])
    for donor in frozen['donors']:
        for key in ('workbook', 'source_manifest', 'reference'): contract.checked(donor[key])
    records = value['records']; calls = value['actual_calls']; previous = frozen['cold_start']; observations = []
    require(len(calls) == 3, 'The source terminal must contain exactly three calls')
    cold = read(frozen['cold_audit'])
    require(cold['passed'] is True and cold['cold_formula_caches_empty'] is True and cold['audited_file'] == previous
            and cold['cells_checked'] == GEOMETRY['nonempty'] and cold['formulas_checked'] == GEOMETRY['formulas'],
            'The complete new cold-source audit changed')
    audits = []
    for index, call in enumerate(calls, 1):
        name = 'source'+str(index)
        require(call['index'] == index and call['role'] == name and call['input'] == previous and call['completed'] is True
                and read(records[name+'_call']) == call, 'The actual complete source call chain changed')
        contract.checked(call['output'])
        observation = dual.resource_check(call['actual_resource_evidence']['terminal'], source=call['input'], output=call['output'])
        require(call['actual_resource_evidence']['container_id'] == observation['container_id'], 'A source resource observation belongs to another container')
        observations.append(observation); audit = read(records[name+'_audit']); audits.append(audit)
        require(audit['passed'] is True and audit['audited_file'] == call['output'] and audit['cold_formula_caches_empty'] is False
                and audit['cells_checked'] == GEOMETRY['nonempty'] and audit['formulas_checked'] == GEOMETRY['formulas']
                and audit['native_error_count'] == audit['mismatch_count'] == 0 and audit['provided_literals_exact'] is True
                and audit['all_local_financial_values_checked_against_retained_AB_native_sources'] is True
                and audit['all_new_group_fields_checked_against_two_independent_compositions'] is True,
                'The actual complete native financial/source audit is missing')
        if index > 1:
            stability = read(records['source'+str(index-1)+'_to_'+name]); before = audits[-2]
            require(stability['passed'] is True and stability['raw_and_primary_complete_stability'] is True
                    and stability['left'] == calls[index-2]['output'] and stability['right'] == call['output']
                    and stability['raw_sha256'] == before['raw_value_sha256'] == audit['raw_value_sha256']
                    and stability['typed_sha256'] == before['typed_value_sha256'] == audit['typed_value_sha256'],
                    'The two complete raw/typed source stability comparisons changed')
        previous = call['output']
    require(value['source'] == previous, 'The final source is not the third completed native output')
    started = read(Path(value['preparation']['path']).parent/'started.json'); cleanup = read(records['cleanup'])
    require(started['preparation'] == value['preparation'] and started['recipe'] == recipes()
            and cleanup['passed'] is True and cleanup['all_owned_containers_absent'] is True
            and cleanup['same_daemon_before_after'] is True and cleanup['daemon_id'] == started['daemon_before_id']
            and len(cleanup['owned']) == 3 and len({item['container_id'] for item in observations}) == 3
            and {(item['container_id'], canonical(item['receipt'])) for item in cleanup['owned']}
                == {(item['container_id'], canonical(item['receipt'])) for item in observations}
            and all(item['absent'] is True for item in cleanup['owned']), 'Actual owned source cleanup is incomplete or unknown')
    return value


@contextmanager
def admission_monitor(output, pair):
    """Start visible progress before any preparation or retained-proof reads."""
    folder = Path(str(Path(output).absolute())+'_admission_monitor')
    require(not folder.exists(), 'Use a fresh admission monitor directory')
    audit = dual.AuditStore(folder, {'id': pair, 'status': 'running', 'name': 'Cached pair source preparation', 'target_count': 0})
    server = dual.DashboardServer(audit.snapshot, audit.events, port=0); url = server.start(); tick = time.monotonic()
    stop = threading.Event()
    def pulse():
        while not stop.wait(15):
            audit.update_run(elapsed_seconds=time.monotonic()-tick); audit.export()
    thread = threading.Thread(target=pulse, daemon=True); thread.start()
    write(folder/'started.json', {'dashboard_url': url, 'pid': __import__('os').getpid(), 'pair': pair})
    print(json.dumps({'dashboard_url': url, 'stage': 'preparation'}), flush=True)
    audit.update_run(stage='preparation', producer_active=True); audit.export()
    try:
        yield audit
    except BaseException:
        audit.update_run(status='failed'); raise
    else:
        audit.update_run(status='completed')
    finally:
        stop.set(); thread.join(timeout=1); audit.update_run(elapsed_seconds=time.monotonic()-tick, producer_active=False)
        audit.export(); server.stop(); audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--pair', choices=FIRST_FIVE, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--preflight-only', action='store_true'); parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    with admission_monitor(args.output, args.pair) as audit:
        if args.preflight_only:
            _, _, certificate = preflight(args.pair); result = write(args.output, certificate)
        elif args.pair == 'R2-01':
            actual = read(OLD_SOURCE); require(actual['passed'] and actual['LO_calls'] == 3, 'The original first pair source is not complete'); result = ref(OLD_SOURCE)
        else:
            result = prepare(args.pair, args.output)
            if args.run:
                audit.update_run(stage='source3'); audit.export(); result = run(result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
