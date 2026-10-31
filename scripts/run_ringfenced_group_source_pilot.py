#!/usr/bin/env python3
"""Prepare, then explicitly run one three-calculation four-mandate source pilot."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import posixpath
import resource
import sys
import threading
import time
from types import ModuleType
from xml.etree import ElementTree as E
from zipfile import ZipFile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
import openpyxl
from openpyxl.utils import get_column_letter
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook import resource_engine as resource_base, thread_capped_resource_engine as cap_base
from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature
from sheets_factory.evaluation import streaming_verifier as sparse
from sheets_factory.workbook.linear_capital_ringfenced_group import contract, composition, stream_composition, group_report

PROFILE = ROOT/'config/runtime_profiles/ringfenced_group_source_pilot_v1.yaml'
BASE_PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
KIND = 'prepared_four_ringfenced_group_source_engineering_pilot'
TERMINAL_KIND = 'completed_four_ringfenced_group_source_engineering_pilot'
STAGES = ('source1', 'source2', 'source3')
PINS = {
    ROOT/'src/sheets_factory/workbook/resource_engine.py': 'cc4fb863740a0fc403a5947a52fa1c2e644b81b75c358e2a3cbf47e7d33a9c8d',
    ROOT/'src/sheets_factory/workbook/thread_capped_resource_engine.py': '82c2e2d5f0ca5c68973f893a66de5d3455e76e67235e462f1d76351a05044361',
    ROOT/'scripts/build_equity_income_group_source.py': '1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690',
}
require, reference = contract.require, contract.reference
read, checked, write = contract.read, contract.checked, contract.write


def now(): return datetime.now(timezone.utc).isoformat()


def support():
    path = ROOT/'scripts/build_equity_income_group_source.py'
    require(reference(path)['sha256'] == PINS[path], 'Frozen source lifecycle support changed')
    spec = importlib.util.spec_from_file_location('_ringfenced_source_pilot_lifecycle_support', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def load_profile(value=PROFILE):
    data = yaml.safe_load(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    expected = resource_base.load_runtime_profile(BASE_PROFILE)
    expected['id'] = 'ringfenced_group_source_pilot_v1'
    expected['limits'] = {'source_physical_formulas': 5200000, 'max_profile_cells': 7500000,
        'max_dependency_closure_cells': 7500000, 'full_target_cells': 6400000, 'truncate': False}
    require(json.dumps(data, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False),
        'Only the prospectively fixed geometry and profile identity may differ; hardware/time/budget unchanged')
    return data


def runtime(): return reference(PROFILE), load_profile(PROFILE)


def engines():
    """Isolate the exact two old resource classes; bind only the new loader."""
    for path, digest in PINS.items(): require(reference(path)['sha256'] == digest, 'A frozen resource/lifecycle ancestor changed')
    def selected(path, wanted):
        tree = ast.parse(path.read_bytes()); found = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in wanted]
        require({n.name for n in found} == wanted and len(found) == len(wanted), 'Frozen resource class inventory changed')
        return ast.Module(body=found, type_ignores=[])
    base = ModuleType('_ringfenced_resource'); vars(base).update(vars(resource_base))
    vars(base).update(load_runtime_profile=load_profile)
    exec(compile(selected(Path(resource_base.__file__), {'ResourceLibreOfficeEngine'}), resource_base.__file__, 'exec'), vars(base))
    cap = ModuleType('_ringfenced_cap'); vars(cap).update(vars(cap_base)); vars(cap)['base'] = base
    exec(compile(selected(Path(cap_base.__file__), {'ThreadCappedResourceLibreOfficeEngine', 'validate_capped_call'}), cap_base.__file__, 'exec'), vars(cap))
    return cap


def recipes():
    modules = (resource_base, cap_base, sparse, contract, composition, stream_composition, group_report)
    paths = [Path(__file__), PROFILE, BASE_PROFILE, *PINS, *[Path(m.__file__) for m in modules]]
    for row in contract.recipes().values(): paths.append(Path(row['path']))
    for row in support().recipes().values(): paths.append(Path(row['path']))
    return {str(p.resolve()): reference(p) for p in paths}


def defined_names(path):
    """Keep every complete scoped name, including formula tokens and flags."""
    with ZipFile(path) as archive:
        root = E.fromstring(archive.read('xl/workbook.xml'))
    inventories = root.findall('{'+stream_composition.S+'}definedNames')
    require(len(inventories) <= 1, 'Duplicate complete defined-name inventories are unsupported')
    names = inventories[0] if inventories else None
    return [{'attributes': dict(sorted(n.attrib.items())), 'formula': n.text or ''}
        for n in names] if names is not None else []


def cold_cache_census(path):
    """Inspect every physical formula, including a forbidden empty v/is node."""
    prefix = '{'+stream_composition.S+'}'
    count = 0
    with ZipFile(path) as archive:
        workbook = E.fromstring(archive.read('xl/workbook.xml'))
        relationships = {r.get('Id'): r for r in E.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        for sheet in workbook.find(prefix+'sheets'):
            relation = relationships[sheet.get('{'+stream_composition.R+'}id')]
            require(relation.get('Type') == stream_composition.R+'/worksheet' and relation.get('TargetMode') is None,
                'A complete cold worksheet relationship changed')
            target = relation.get('Target'); part = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            with archive.open(part) as handle:
                parents = []
                for event, node in E.iterparse(handle, events=('start', 'end')):
                    if event == 'start': parents.append(node); continue
                    if node.tag == prefix+'c':
                        formula = node.find(prefix+'f')
                        if formula is not None:
                            require(bool(formula.text) and node.find(prefix+'v') is None and node.find(prefix+'is') is None,
                                'Every physical cold formula cache must be absent')
                            count += 1
                        parents[-2].remove(node); node.clear()
                    elif node.tag == prefix+'row': parents[-2].remove(node); node.clear()
                    parents.pop()
    return count


def _typed(cell, *, financial=False):
    if cell is None or cell['value'] is None or cell['value'] == '': return ('empty', '')
    value = cell['value']
    if cell['data_type'] == 'e': return ('error', str(value))
    if type(value) is bool: return ('boolean', value)
    if type(value) in (int, float):
        require(math.isfinite(value), 'Native result must be finite')
        number = Decimal(str(value))
        if financial: number = number.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        return ('number', '0' if not number else format(number.normalize(), 'f'))
    require(type(value) is str, 'Unexpected native value type')
    return ('text', value)


def _merge(streams):
    heads = [next(s, None) for s in streams]
    while any(h is not None for h in heads):
        point = min(h[0] for h in heads if h is not None); cells = []
        for i, stream in enumerate(streams):
            if heads[i] is not None and heads[i][0] == point:
                cells.append(heads[i][1]); heads[i] = next(stream, None)
            else: cells.append(None)
        yield point, cells


def audit_workbook(path, frozen, *, cold=False):
    """All local cached values, formulas and given literals; no binding expansion."""
    composition_receipt = read(frozen['local_composition'])
    plan, expected = read(frozen['report_plan']), read(frozen['report_expected'])
    source_donors = frozen['donors']; mismatches = []; count = errors = formulas = 0; bad = 0
    def reject(sheet, point, claim):
        nonlocal bad
        bad += 1
        if len(mismatches) < 20: mismatches.append({'sheet': sheet, 'point': point, 'claim': claim})
    # JSON round-tripping turns token tuples into lists.
    names = json.loads(json.dumps(defined_names(path)))
    if names != frozen['defined_names']: reject(None, None, 'Complete scoped defined names changed')
    with ExitStack() as stack:
        def book(value, data):
            wb = openpyxl.load_workbook(value, read_only=True, data_only=data, keep_links=False); stack.callback(wb.close); return wb
        output_f, output_v = book(path, False), book(path, True)
        wanted_names = [name for d in composition_receipt['donors'] for name in d['sheet_map'].values()]+[group_report.SHEET]
        require(output_f.sheetnames == output_v.sheetnames == wanted_names, 'Whole native worksheet order differs')
        for donor, mapping in zip(source_donors, composition_receipt['donors'], strict=True):
            original_f, original_v = book(checked(donor['workbook']), False), book(checked(donor['workbook']), True)
            require(original_f.sheetnames == list(mapping['sheet_map']), 'A complete local workbook changed')
            require(not defined_names(checked(donor['workbook'])), 'Named local formulas require a separately reviewed pilot')
            for sheet in original_f.sheetnames:
                mapped = mapping['sheet_map'][sheet]
                streams = [iter(sparse._sparse_cells(wb[name])) for wb, name in
                    ((original_f, sheet), (original_v, sheet), (output_f, mapped), (output_v, mapped))]
                try:
                    for point, (sf, sv, of, ov) in _merge(streams):
                        count += 1; errors += int(any(c is not None and c['data_type'] == 'e' for c in (of, ov)))
                        if sf is not None and sf['data_type'] == 'f':
                            formulas += 1
                            want = stream_composition.syntax.rewrite_formula(sf['value'], mapping['sheet_map'], local_sheet=sheet)
                            if of is None or of['data_type'] != 'f' or formula_signature(of['value']) != formula_signature(want):
                                reject(mapped, point, 'Financial formula definition changed')
                            wanted = ('empty', '') if cold else _typed(sv, financial=True)
                            if _typed(ov, financial=True) != wanted: reject(mapped, point, 'Independent original financial cached value differs')
                        else:
                            if _typed(of) != _typed(sf) or _typed(ov) != _typed(sf): reject(mapped, point, 'Given literal or input changed')
                finally:
                    for stream in streams: stream.close()
        rows = list(_merge([iter(sparse._sparse_cells(output_f[group_report.SHEET])), iter(sparse._sparse_cells(output_v[group_report.SHEET]))]))
        observed = {get_column_letter(p[1])+str(p[0]): cells for p, cells in rows}
        wanted_points = set(plan['formulas']) | set(plan['literals'])
        if set(observed) != wanted_points: reject(group_report.SHEET, None, 'Complete public report cell scope differs')
        for point in wanted_points:
            of, ov = observed.get(point, (None, None)); count += 1
            errors += int(any(c is not None and c['data_type'] == 'e' for c in (of, ov)))
            if point in plan['formulas']:
                formulas += 1
                if of is None or of['data_type'] != 'f' or formula_signature(of['value']) != formula_signature(plan['formulas'][point]): reject(group_report.SHEET, point, 'Report formula changed')
                wanted = ('empty', '') if cold else (expected[point]['type'], expected[point]['value'])
                if not cold and wanted[0] == 'number': wanted = ('number', str(Decimal(wanted[1]).normalize()))
                # Normalize exponent notation in expected integer values.
                if not cold and wanted[0] == 'number': wanted = ('number', format(Decimal(wanted[1]), 'f'))
                if _typed(ov, financial=True) != wanted: reject(group_report.SHEET, point, 'Independent composed report expectation differs')
            else:
                wanted = _typed({'value': plan['literals'][point], 'data_type': 'n' if type(plan['literals'][point]) is int else 's'})
                if _typed(of) != wanted or _typed(ov) != wanted: reject(group_report.SHEET, point, 'Public group policy/label changed')
    geometry = frozen['geometry']
    require(count == geometry['nonempty'] and formulas == geometry['formulas'], 'Whole native audit did not cover the exact complete source census')
    if cold: require(cold_cache_census(path) == formulas, 'Cold physical formula coverage changed')
    return {'kind': 'complete_ringfenced_group_streamed_financial_and_given_audit', 'version': 1,
        'passed': bad == errors == 0, 'cells_checked': count, 'formulas_checked': formulas,
        'mismatch_count': bad, 'mismatch_examples': mismatches, 'native_error_count': errors,
        'cold_formula_caches_required_empty': cold, 'local_finance_from_genuine_independent_A_B_source_goals': True,
        'cold_formula_caches_physically_absent': cold,
        'group_finance_from_independent_composition_certificate': True, 'provided_literals_exact': True,
        'financial_numeric_primary': 'half-up two decimals', 'boolean_text_types_exact': True,
        'new_financial_forwards': 0, 'qualified': False}


def checked_local(cert, certificate_ref, local_ref):
    local = read(local_ref)
    require(local['kind'] == 'uncalculated_ringfenced_group_stream_composition' and local['prototype_toy_only'] is False
        and local['sheet_count'] == 1480 and local['geometry'] == {'formulas': 4989312, 'nonempty': 7094264, 'targets': 6088752}
        and local['ancestry']['composition_certificate'] == certificate_ref, 'Use the complete actual first-four emission bound to this genuine certificate')
    require([(d['id'], d['workbook']) for d in local['donors']] == [(d['id'], d['workbook']) for d in cert['donors']], 'Local donor lineage changed')
    checked(local['output'])
    return local


def prepare(certificate, local_composition, output):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(), 'Use a fresh private pilot preparation')
    certificate_ref = certificate if isinstance(certificate, dict) else reference(certificate)
    # Exactly one genuine cold validation in this command, never a stored pass shim.
    cert = composition.validate_certificate(certificate_ref)
    local_ref = local_composition if isinstance(local_composition, dict) else reference(local_composition)
    local = checked_local(cert, certificate_ref, local_ref)
    plan = group_report.plan(cert['contract'], local); expected = group_report.expectations(cert, plan)
    output.mkdir(parents=True)
    reported = group_report.append_report(local, cert['contract'], output/'cold_start.xlsx')
    frozen = {'kind': KIND, 'version': 1, 'certificate': certificate_ref, 'local_composition': local_ref,
        'donors': cert['donors'], 'public_contract': cert['contract'], 'cold_start': reported['output'],
        'report_plan': write(output/'report_plan.json', plan), 'report_expected': write(output/'expected.private.json', expected),
        'report_emission': write(output/'report_emission.json', reported), 'geometry': reported['geometry'],
        'defined_names': json.loads(json.dumps(defined_names(checked(reported['output'])))),
        'runtime_profile': reference(PROFILE), 'runtime_profile_value': load_profile(), 'recipe': recipes(),
        'stage_order': list(STAGES), 'required_actual_calls': 3, 'retry': 0, 'new_group_source_admitted': False}
    cold = audit_workbook(checked(frozen['cold_start']), frozen, cold=True)
    frozen['cold_audit'] = write(output/'cold_audit.json', cold); require(cold['passed'], 'Complete cold-source caches/values/definitions audit failed')
    return write(output/'preparation.json', frozen)


def validate_prepared(output):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs'), 'Use the exact private pilot preparation')
    frozen = read(output/'preparation.json')
    require(frozen['kind'] == KIND and frozen['version'] == 1 and frozen['recipe'] == recipes()
        and frozen['stage_order'] == list(STAGES) and frozen['retry'] == 0
        and frozen['required_actual_calls'] == 3 and frozen['new_group_source_admitted'] is False, 'Frozen complete pilot protocol changed')
    # A fresh command actually repeats the genuine validator; no persisted cache.
    cert = composition.validate_certificate(frozen['certificate'])
    require(cert['donors'] == frozen['donors'] and frozen['runtime_profile_value'] == load_profile(checked(frozen['runtime_profile'])), 'Pilot source/profile lineage changed')
    for key in ('cold_start', 'local_composition', 'report_plan', 'report_expected', 'report_emission', 'cold_audit'): checked(frozen[key])
    local = checked_local(cert, frozen['certificate'], frozen['local_composition'])
    plan = group_report.plan(cert['contract'], local)
    emitted = read(frozen['report_emission'])
    require(frozen['public_contract'] == cert['contract'] and read(frozen['report_plan']) == plan
        and read(frozen['report_expected']) == group_report.expectations(cert, plan)
        and emitted['local_composition'] == local and emitted['output'] == frozen['cold_start']
        and emitted['report_plan'] == plan and emitted['geometry'] == frozen['geometry']
        and frozen['geometry'] == {'formulas': 4989614, 'nonempty': 7094703, 'targets': 6089054}
        and emitted['sheet_count'] == 1481 and emitted['report_formulas_uncached'] is True
        and emitted['all_local_sheet_parts_byte_identical'] is True
        and emitted['private_expected_values_embedded'] is False, 'Report definition, independent expectation or whole geometry changed')
    require(audit_workbook(checked(frozen['cold_start']), frozen, cold=True) == read(frozen['cold_audit'])
        and read(frozen['cold_audit'])['passed'], 'Complete original cold audit changed')
    return frozen


def execute_prepared(output):
    output = Path(output).absolute(); frozen = validate_prepared(output)
    require(not (output/'started.json').exists(), 'Preserve the first pilot; zero retries')
    lease = ProducerLease(output).acquire(); audit = server = pulse = engine = None
    try: require(not (output/'started.json').exists(), 'Preserve the first pilot; zero retries')
    except BaseException: lease.release(); raise
    stop = threading.Event(); calls = []; records = {}; failure = None; clock = time.monotonic()
    helper = cap = None
    try:
        helper = support(); cap = engines()
        write(output/'started.json', {'at': now(), 'pid': os.getpid(), 'preparation': reference(output/'preparation.json'), 'retry': 0})
        audit = AuditStore(output/'audit', {'id': output.name, 'status': 'running', 'target_count': 0, 'qualified': 0,
            'producer_pid': os.getpid(), 'name': 'Four-mandate whole-source engineering pilot'})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        audit.update_run(dashboard_url=url, producer_active=True); audit.export()
        print(json.dumps({'dashboard_url': url, 'pid': os.getpid()}), flush=True)
        def heartbeat():
            while not stop.wait(15):
                audit.update_run(elapsed_seconds=time.monotonic()-clock, actual_calls_started=len(calls), actual_calls_completed=sum(c['completed'] for c in calls)); audit.export()
        pulse = threading.Thread(target=heartbeat, daemon=True); pulse.start()
        engine = cap.ThreadCappedResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=output/'engine_resources')
        with helper.stage(audit, 'pinned_image_check'): engine.ensure_image()
        previous = frozen['cold_start']
        for index, name in enumerate(STAGES, 1):
            call = {'index': index, 'role': name, 'input': previous, 'started_at': now(), 'completed': False}; calls.append(call)
            call['started_receipt'] = write(output/(name+'_started.json'), dict(call))
            with helper.stage(audit, name):
                try:
                    tick = time.monotonic(); result = engine.recalculate(checked(previous), output/(name+'.xlsx'))
                    call.update(output=reference(result), completed=True, elapsed_seconds=time.monotonic()-tick)
                    history = engine.metadata()['actual_resource_receipts']; require(len(history) == index, 'Extra or missing native calculation')
                    call['actual_resource_evidence'] = cap.validate_capped_call(call, history[-1], frozen, resource_validator=helper.resource_support().validate_actual_call)
                finally: call['finished_at'] = now(); call['terminal_receipt'] = write(output/(name+'_terminal.json'), dict(call))
            with helper.stage(audit, name+'_whole_financial_and_given_audit'):
                value = audit_workbook(result, frozen); records[name+'_audit'] = write(output/(name+'_audit.json'), value)
                require(value['passed'], 'Complete independent local/group typed-value or definition audit failed')
            previous = call['output']
        for left, right in zip(calls, calls[1:]):
            with helper.stage(audit, left['role']+'_to_'+right['role']+'_full_typed_stability'):
                value = sparse.compare_files(left['output']['path'], left['output']['path'], right['output']['path'])
                records[left['role']+'_to_'+right['role']] = write(output/(left['role']+'_to_'+right['role']+'.json'), value)
                require(value['reward'] == 1, 'Complete source typed stability failed')
        records['cleanup'] = write(output/'owned_absence.json', helper.owned_absence(calls))
        clean = read(records['cleanup']); require(clean['all_owned_containers_absent'] and clean['daemon_reachable'], 'Owned container cleanup is incomplete or unknown')
        require(recipes() == frozen['recipe'], 'Frozen code/profile changed')
        for donor in frozen['donors']: checked(donor['workbook'])
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
        if engine is not None:
            try:
                owned = []
                for row in engine.metadata()['actual_resource_receipts']:
                    native = read(row); require(any(native.get('source') == c['input'] for c in calls), 'Unowned cleanup observation')
                    if native.get('container_id'): owned.append({'actual_resource_evidence': {'container_id': native['container_id']}})
                if owned: records['failure_cleanup'] = write(output/'failure_owned_absence.json', helper.owned_absence(owned))
            except Exception as cleanup_error: records['failure_cleanup'] = write(output/'cleanup_unknown.json', {'state': 'unknown', 'error_type': type(cleanup_error).__name__})
    finally:
        stop.set()
        finalization = []
        operations = [lambda: pulse.join(timeout=1)] if pulse else []
        if audit:
            operations += [lambda: audit.update_run(status='passed' if failure is None else 'failed', producer_active=False), audit.export]
        if server: operations.append(server.stop)
        if audit: operations.append(audit.db.close)
        operations.append(lease.release)
        for operation in operations:
            try: operation()
            except Exception as error: finalization.append({'type': type(error).__name__, 'message': str(error)})
        if finalization and failure is None: failure = {'type': 'FinalizationFailure', 'details': finalization}
    terminal = write(output/'terminal.json', {'kind': TERMINAL_KIND, 'version': 1, 'passed': failure is None, 'failure': failure,
        'preparation': reference(output/'preparation.json'), 'actual_calls': calls, 'records': records,
        'actual_calls_started': len(calls), 'actual_calls_completed': sum(c['completed'] for c in calls),
        'source': calls[-1].get('output') if calls else None, 'elapsed_seconds': time.monotonic()-clock,
        'finalization_errors': finalization,
        'host_peak_rss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, 'container_peak_rss_measured': False,
        'retry': 0, 'LO_calls': len(calls), 'model_solver_Harbor_calls': 0, 'new_financial_forwards': 0,
        'new_group_source_admitted': False, 'source_classification_pending': True, 'qualified': False, 'normal_quality_inherited': False})
    if failure is not None: raise RuntimeError('Pilot failed; preserve terminal and do not retry')
    return terminal


def validate_completed(value):
    """Recheck genuine ancestry, all three calls, full audits and owned cleanup."""
    terminal = read(value)
    require(terminal['kind'] == TERMINAL_KIND and terminal['version'] == 1 and terminal['passed'] is True
        and terminal['failure'] is None and terminal['finalization_errors'] == []
        and terminal['actual_calls_started'] == terminal['actual_calls_completed'] == terminal['LO_calls'] == 3
        and terminal['retry'] == terminal['model_solver_Harbor_calls'] == terminal['new_financial_forwards'] == 0
        and terminal['new_group_source_admitted'] is terminal['qualified'] is terminal['normal_quality_inherited'] is False
        and terminal['source_classification_pending'] is True, 'Require a complete engineering-only three-call pilot')
    frozen = validate_prepared(checked(terminal['preparation']).parent)
    cap, helper = engines(), support()
    calls = terminal['actual_calls']; require(len(calls) == 3, 'Exactly three retained actual calls are required')
    previous = frozen['cold_start']
    for index, (name, call) in enumerate(zip(STAGES, calls, strict=True), 1):
        require(call['index'] == index and call['role'] == name and call['input'] == previous
            and call['completed'] is True, 'The original source calculation chain changed')
        checked(call['output'])
        require(read(call['started_receipt']) == {'index': index, 'role': name, 'input': previous,
            'started_at': call['started_at'], 'completed': False}, 'Actual call started receipt changed')
        require(read(call['terminal_receipt']) == {k: v for k, v in call.items() if k != 'terminal_receipt'}, 'Actual call terminal changed')
        evidence = cap.validate_capped_call(call, call['actual_resource_evidence']['terminal'], frozen,
            resource_validator=helper.resource_support().validate_actual_call)
        require(evidence == call['actual_resource_evidence'], 'Actual resource/thread-cap proof changed')
        report = audit_workbook(checked(call['output']), frozen)
        require(report['passed'] and read(terminal['records'][name+'_audit']) == report, 'Complete independent financial/given audit changed')
        previous = call['output']
    for left, right in zip(calls, calls[1:]):
        report = sparse.compare_files(left['output']['path'], left['output']['path'], right['output']['path'])
        require(report['reward'] == 1 and read(terminal['records'][left['role']+'_to_'+right['role']]) == report,
            'Complete typed stability evidence changed')
    clean = read(terminal['records']['cleanup'])
    require(clean['all_owned_containers_absent'] is True and clean['daemon_reachable'] is True
        and len(clean['owned']) == 3 and all(row['absent'] is True for row in clean['owned'])
        and {row['full_id'] for row in clean['owned']} == {c['actual_resource_evidence']['container_id'] for c in calls}
        and len({c['actual_resource_evidence']['container_id'] for c in calls}) == 3, 'Cleanup must cover exactly the three distinct owned containers')
    require(terminal['source'] == previous, 'Final pilot workbook changed')
    return terminal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--certificate', type=Path); parser.add_argument('--local-composition', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if args.prepared:
        require(args.certificate is None and args.local_composition is None and args.output is None, 'Use the unchanged existing pilot preparation')
        result = execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(not args.run, 'Freeze and review preparation in a separate command before the first actual call')
        require(args.certificate is not None and args.local_composition is not None and args.output is not None, 'Supply all exact pilot inputs')
        result = prepare(args.certificate, args.local_composition, args.output)
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
