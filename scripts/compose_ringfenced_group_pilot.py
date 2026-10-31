#!/usr/bin/env python3
"""Prepare or run ONE fixed-four pure goal emission; no native calculations."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import resource
import sys
import threading
import time
import traceback
from xml.etree import ElementTree as X
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as c, composition, stream_composition as core

CERTIFICATE_SHA256 = '50659f111b5913f3187ba8f8f8a3ad59a76cb71892f5b9f24e7bce98838cad2c'
PROSPECTIVE_SHA256 = '77f5f5b99145e0b537813761a9717f9f95824020d1e16875caf9e6479ec3a43a'
CONTRACT_SHA256 = '7bad4869b94b550ca34693ca49b26c453563c278c6b656fe4897e5af4e53deda'
CORE_SHA256 = '7f0ff72c9a8a9cd6de949b9824d821174643453c740e8856117446cdec1094bb'
KIND = 'prepared_fixed_four_ringfenced_pure_goal_emission'
TERMINAL = 'complete_fixed_four_ringfenced_pure_goal_emission'
EXPECTED = {'sheets': 1480, 'formulas': 4989312, 'nonempty': 7094264}
TARGETS = 6088752
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PHASE_LABELS = {
    'genuine_four_reference_and_source_cold_replay': '复核四份完整证明与原来源',
    'complete_four_mandate_OOXML_emission': '合并四资金池完整工作簿',
    'independent_physical_caches_census_and_given_literals': '逐表检查公式缓存、规模和给定事实',
}


def now(): return datetime.now(timezone.utc).isoformat()


def recipes():
    c.require(c.reference(core.__file__)['sha256'] == CORE_SHA256, 'The frozen streaming composer changed')
    return {**c.recipes(), **{str(Path(p).resolve()): c.reference(p) for p in
        (__file__, core.__file__, core.syntax.__file__, sys.modules[AuditStore.__module__].__file__,
         sys.modules[DashboardServer.__module__].__file__, sys.modules[ProducerLease.__module__].__file__)}}


def _fixed_certificate(record):
    c.require(c.reference(c.checked(record))['sha256'] == CERTIFICATE_SHA256, 'Use the exact fixed first-four certificate')
    value = c.read(record)
    c.require(value['prospective']['sha256'] == PROSPECTIVE_SHA256
              and value['contract']['sha256'] == CONTRACT_SHA256, 'The fixed quartet prospective or business contract changed')
    c.validate_prospective(value['prospective'])
    c.require([(d['id'], d['prefix']) for d in value['donors']] == core.FIXED, 'Keep all four original mandates')
    return value


def prepare(certificate, output):
    output = Path(output).absolute()
    c.require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs') and not output.exists(), 'Use a fresh private emission directory')
    record = certificate if isinstance(certificate, dict) else c.reference(certificate)
    _fixed_certificate(record)  # Metadata checks only: no cold replay or emission.
    value = {'kind': KIND, 'version': 1, 'created_at': now(), 'certificate': record, 'recipe': recipes(),
        'expected_census': EXPECTED, 'target_count_including_completion_gates': TARGETS,
        'output_filename': 'locals_uncalculated.xlsx', 'required_genuine_cold_validation_at_run': True,
        'one_pure_emission': True, 'retry': 0, 'native_solver_LO_model_Harbor_calls': 0,
        'workbooks_written': 0, 'new_group_source_admitted': False, 'qualified': False}
    output.mkdir(parents=True); return c.write(output / 'preparation.json', value)


def validate_prepared(output):
    value = c.read(Path(output) / 'preparation.json')
    c.require(value['kind'] == KIND and value['version'] == 1 and value['recipe'] == recipes()
        and value['expected_census'] == EXPECTED and value['target_count_including_completion_gates'] == TARGETS
        and value['output_filename'] == 'locals_uncalculated.xlsx'
        and value['required_genuine_cold_validation_at_run'] is value['one_pure_emission'] is True
        and value['retry'] == value['native_solver_LO_model_Harbor_calls'] == value['workbooks_written'] == 0
        and value['new_group_source_admitted'] is value['qualified'] is False, 'The frozen pure pilot scope changed')
    _fixed_certificate(value['certificate']); return value


def audit_workbook(receipt, expected=EXPECTED, progress=None):
    """Stream the emitted XML: exact census, zero caches, unchanged given values."""
    path = c.checked(receipt['output']); before = c.reference(path)
    wanted = {sheet['mapped_sheet']: sheet for donor in receipt['donors'] for sheet in donor['worksheets']}
    count = {'sheets': 0, 'formulas': 0, 'nonempty': 0}; given_cells = 0
    with ZipFile(path) as book:
        wb = X.fromstring(book.read('xl/workbook.xml'))
        relationships = {r.get('Id'): r for r in X.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            for node in X.fromstring(book.read('xl/sharedStrings.xml')):
                strings.append((X.canonicalize(X.tostring(node, encoding='unicode')),
                                bool(''.join(t.text or '' for t in node.iter(S + 't')))))
        sheets = list(wb.find(S + 'sheets'))
        c.require(len(sheets) == len(wanted) and {x.get('name') for x in sheets} == set(wanted), 'The complete sheet union changed')
        for sheet in sheets:
            original = wanted[sheet.get('name')]; digest = hashlib.sha256()
            relation = relationships[sheet.get(R + 'id')]
            c.require(relation.get('Type', '').endswith('/worksheet') and relation.get('TargetMode') is None, 'A worksheet relationship changed')
            target = relation.get('Target'); part = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            with book.open(part) as handle:
                parents = []
                for event, node in X.iterparse(handle, events=('start', 'end')):
                    if event == 'start': parents.append(node); continue
                    if node.tag == S + 'c':
                        formula, value, inline = node.find(S + 'f'), node.find(S + 'v'), node.find(S + 'is')
                        if formula is not None:
                            c.require(value is None and inline is None and bool(formula.text), 'Every physical formula cache must be absent')
                            count['formulas'] += 1; count['nonempty'] += 1
                        else:
                            typ = node.get('t', 'n'); semantic = value.text if value is not None else None; nonempty = bool(semantic)
                            if typ == 's':
                                index = int(semantic); c.require(0 <= index < len(strings), 'A shared-string index changed')
                                semantic, nonempty = strings[index]
                            elif inline is not None:
                                semantic = X.canonicalize(X.tostring(inline, encoding='unicode'))
                                nonempty = bool(''.join(t.text or '' for t in inline.iter(S + 't')))
                            if semantic is not None:
                                digest.update(json.dumps([original['original_sheet'], node.get('r'), typ, semantic], ensure_ascii=False).encode() + b'\n')
                                given_cells += 1; count['nonempty'] += int(nonempty)
                        parents[-2].remove(node); node.clear()
                    elif node.tag == S + 'row': parents[-2].remove(node); node.clear()
                    parents.pop()
            c.require(digest.hexdigest() == original['given_literal_semantic_sha256'], 'A supplied literal, NA or Boolean changed')
            count['sheets'] += 1
            if progress: progress(dict(count))
    c.require(count == expected and c.reference(path) == before, 'The full physical census or immutable output changed')
    return {'kind': 'complete_physical_ringfenced_goal_cache_and_literal_audit', 'version': 1,
        'output': before, 'census': count, 'all_formula_caches_physically_empty': True,
        'all_donor_given_semantic_digests_match': True, 'given_cells_checked': given_cells,
        'source_classification': False, 'native_solver_LO_model_Harbor_calls': 0}


def execute_prepared(output, *, port=0):
    output = Path(output).absolute(); f = validate_prepared(output)
    lease = ProducerLease(output).acquire()
    try: c.require(not (output / 'attempt_reserved.json').exists(), 'No retries; preserve the original full pilot')
    except BaseException: lease.release(); raise
    c.write(output / 'attempt_reserved.json', {'at': now(), 'pid': os.getpid(), 'preparation': c.reference(output / 'preparation.json')})
    audit = server = pulse = None; stop = threading.Event(); clock = time.monotonic()
    state = {'phase': '准备运行', 'phase_index': 0, 'verified_formulas': None, 'verified_sheets': None}; records = {}; failure = None; export_errors = []
    def export():
        try: audit.export()
        except Exception as error: export_errors.append({'at': now(), 'type': type(error).__name__, 'message': str(error)})
    def heartbeat():
        while not stop.wait(15):
            try:
                pending = [p for p in output.glob('.ringfenced-compose-*/pending.xlsx') if p.is_file()]
                checked = '待逐表检查' if state['verified_formulas'] is None else f"{state['verified_formulas']:,}/{EXPECTED['formulas']:,}"
                written = sum(p.stat().st_size for p in pending)
                message = state['phase'] + f"；计划 {EXPECTED['formulas']:,} 个公式；公式核验 " + checked
                if written: message += f'；已写数据约 {written / 1024**2:.1f} MiB'
                audit.update_run(elapsed_seconds=time.monotonic() - clock, current_node=message,
                    planned_formula_count=EXPECTED['formulas'], verified_formula_count=state['verified_formulas'],
                    verified_sheet_count=state['verified_sheets'], pending_output_bytes=written,
                    cumulative_process_peak_rss_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                export()
            except Exception as error: export_errors.append({'at': now(), 'type': type(error).__name__, 'message': str(error)})
    @contextmanager
    def stage(name):
        index = state['phase_index']; state['phase_index'] += 1
        state['phase'] = PHASE_LABELS[name]; started = time.monotonic(); start = now()
        node = audit.record('nodes', {'node_id': name, 'name': PHASE_LABELS[name], 'status': 'running', 'started_at': start, 'total_tokens': 0})
        c.write(output / f'{index:02d}_{name}_started.json', {'at': start, 'phase': name})
        error = None
        try: yield
        except BaseException as caught: error = {'type': type(caught).__name__, 'message': str(caught)}; raise
        finally:
            value = {'phase': name, 'passed': error is None, 'failure': error, 'elapsed_seconds': time.monotonic() - started}
            records[name] = c.write(output / f'{index:02d}_{name}_terminal.json', value)
            audit.update_record('nodes', node, {'status': 'complete' if error is None else 'failed', 'duration_ms': value['elapsed_seconds'] * 1000})
            audit.emit('pure_phase_terminal', message=PHASE_LABELS[name], **value); export()
    try:
        audit = AuditStore(output / 'audit', {'id': output.name, 'name': '四资金池完整合并 · 纯文件处理（0模型调用）',
            'status': 'running', 'target_count': 0, 'pure_workbook_target_count': 1, 'producer_pid': os.getpid(),
            'producer_active': True, 'qualified': False, 'operation': 'pure_goal_emission_not_source_admission',
            'planned_formula_count': EXPECTED['formulas'], 'verified_formula_count': None})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port); url = server.start()
        c.write(output / 'started.json', {'at': now(), 'pid': os.getpid(), 'dashboard_url': url, 'preparation': c.reference(output / 'preparation.json')})
        print(json.dumps({'dashboard_url': url, 'pid': os.getpid(), 'native_solver_LO_model_Harbor_calls': 0}), flush=True)
        pulse = threading.Thread(target=heartbeat, daemon=True); pulse.start(); export()
        with stage('genuine_four_reference_and_source_cold_replay'):
            proof = composition.validate_certificate(f['certificate'])
            c.require(proof == c.read(f['certificate']), 'The genuine cold result must be the exact frozen certificate')
        with stage('complete_four_mandate_OOXML_emission'):
            c.require([(d['id'], d['prefix']) for d in proof['donors']] == core.FIXED, 'The quartet changed after cold validation')
            result = core._compose(proof['donors'], output / f['output_filename'], mode='goal', target_count=TARGETS,
                ancestry={'composition_certificate': f['certificate'], 'native_source_or_quality_inherited': False}, expected_census=EXPECTED)
            records['composition_receipt'] = c.write(output / 'composition_receipt.json', result)
        def progress(count):
            state.update(verified_formulas=count['formulas'], verified_sheets=count['sheets'])
            if count['sheets'] % 50 == 0: audit.update_run(verified_formula_count=count['formulas'], verified_sheet_count=count['sheets'])
        with stage('independent_physical_caches_census_and_given_literals'):
            records['physical_audit'] = c.write(output / 'physical_audit.json', audit_workbook(result, progress=progress))
        c.require(validate_prepared(output) == f, 'The frozen pure recipe changed while running')
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
    finally:
        stop.set()
        if pulse: pulse.join(timeout=5)
        if audit:
            try: audit.update_run(status='passed' if failure is None else 'failed', producer_active=False,
                current_node='pure_goal_emitted_not_source_admitted' if failure is None else 'failed_retained',
                elapsed_seconds=time.monotonic()-clock, verified_formula_count=state['verified_formulas'], verified_sheet_count=state['verified_sheets']); export()
            except Exception as error: export_errors.append({'type': type(error).__name__, 'message': str(error)})
        for closer in ([server.stop] if server else []) + ([audit.db.close] if audit else []) + [lease.release]:
            try: closer()
            except Exception as error:
                failure = failure or {'type': type(error).__name__, 'message': str(error)}
    terminal = c.write(output / 'terminal.json', {'kind': TERMINAL, 'version': 1, 'passed': failure is None,
        'failure': failure, 'preparation': c.reference(output / 'preparation.json'), 'certificate': f['certificate'],
        'records': records, 'elapsed_seconds': time.monotonic() - clock, 'audit_export_errors': export_errors,
        'host_process_peak_rss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'memory_measurement_is_host_process_not_container': True, 'native_solver_LO_model_Harbor_calls': 0,
        'model_input_tokens': 0, 'model_output_tokens': 0, 'retry': 0, 'source_classification': False,
        'new_group_source_admitted': False, 'normal_quality_or_difficulty_inherited': False, 'qualified': False})
    if failure: raise RuntimeError('Pure goal emission failed; retain the attempt and do not retry')
    return terminal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--certificate', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true'); parser.add_argument('--port', type=int, default=0); args = parser.parse_args(argv)
    c.require(0 <= args.port <= 65535, 'Use a valid local dashboard port')
    if args.prepared:
        c.require(args.certificate is None and args.output is None, 'Use the exact frozen preparation')
        result = execute_prepared(args.prepared, port=args.port) if args.run else validate_prepared(args.prepared)
    else:
        c.require(args.certificate is not None and args.output is not None, 'Supply the fixed certificate and fresh output')
        result = prepare(args.certificate, args.output)
        if args.run: result = execute_prepared(args.output, port=args.port)
    print(json.dumps(result), flush=True); return 0


if __name__ == '__main__': raise SystemExit(main())
