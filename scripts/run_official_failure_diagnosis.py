#!/usr/bin/env python3
"""Freeze evidence snapshots; explicitly run one diagnostic review per case version.

Research only. The CLI's read-only sandbox and evidence-only container are an
operational boundary, not a claim that arbitrary hostile tool programs are safe.
No original solver, evaluator, spreadsheet application, or attempt is invoked.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.llm import CodexCLI
from sheets_factory.resume import ProducerLease

PROMPT = ROOT / 'prompts/official_failure_diagnosis.md'
KIND = 'prepared_official_failure_diagnosis_snapshot'
VERSION = 1
MODEL = 'gpt-6-sol'
REGISTRY = ROOT / 'outputs/research/official_failure_diagnosis_once_v1'
INVENTORY_SHA = '654e7ab5c78ceba2293f046456cd8eaef57114725a994a44bdb03a900aadd684'
POLICY = {'model': MODEL, 'reasoning_effort': 'high', 'timeout_seconds': 900,
          'concurrency': 4, 'outer_retries': 0, 'request_retries': 0,
          'stream_retries': 0, 'review_version': VERSION, 'research_only': True}
REF_KEYS = {'path', 'sha256', 'bytes'}


def now(): return datetime.now(timezone.utc).isoformat()
def canonical(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
def digest(value): return hashlib.sha256(canonical(value)).hexdigest()
def require(value, message):
    if not value: raise ValueError(message)
def reference(path):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink(), 'Expected a regular non-symlink evidence file')
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
def checked(ref):
    require(isinstance(ref, dict) and set(ref) == REF_KEYS, 'An exact three-key artifact reference is required')
    path = Path(ref['path'])
    require(path.is_absolute() and not any(p.is_symlink() for p in [path, *path.parents]), 'Evidence paths must be absolute and have no symlinks')
    require(reference(path) == ref, 'Changed or missing evidence: ' + str(path))
    return path
def read(value): return json.loads((checked(value) if isinstance(value, dict) else Path(value)).read_text())
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream: stream.write(canonical(value) + b'\n')
    return reference(path)
def artifact(value): return value if isinstance(value, dict) else reference(value)
def recipes():
    import sheets_factory.core.audit as audit
    import sheets_factory.llm.codex as client
    import sheets_factory.dashboard as dashboard
    import sheets_factory.dashboard.server as dashboard_server
    import dirhash
    import yaml
    config = yaml.safe_load((ROOT / 'config/llm.yaml').read_text())
    return {str(Path(p).absolute()): reference(p) for p in
            (__file__, PROMPT, ROOT / 'tests/test_official_failure_diagnosis.py', audit.__file__,
             client.__file__, dashboard.__file__, dashboard_server.__file__, dirhash.__file__,
             ROOT / 'config/llm.yaml', config['binary'])}
def same_bytes(a, b): return a['sha256'] == b['sha256'] and a['bytes'] == b['bytes']


def _indexed(rows, field):
    require(isinstance(rows, list), 'Expected an ordered row inventory')
    values = {r[field]: r for r in rows}
    require(len(values) == len(rows), 'Duplicate case identities are forbidden')
    return values


def _offline(scan):
    require(scan.get('kind') == 'incremental_offline_spreadsheet_failure_analysis_scan' and scan.get('version') == 1,
            'Use the original offline scan receipt')
    result = {}
    for entry in scan['reports']:
        if entry.get('evidence_stage') not in ('official_case_terminal', 'retained_original_case_terminal'): continue
        receipt = read(entry['receipt']); report_ref = receipt.get('report')
        require(report_ref is not None, 'Offline receipt is missing its report')
        report = read(report_ref)
        key = entry['case_id']
        require(report.get('case_id') == key and key not in result, 'Duplicate or mismatched offline case')
        result[key] = (report_ref, report)
    return result


def _raw(terminal):
    for name in ('official_raw_accuracy', 'official_primary_accuracy'):
        if name in terminal: return terminal[name]
    return (terminal.get('official_primary') or {}).get('result', {}).get('accuracy')


def _summary(case, terminal, row):
    official = terminal.get('official_primary') or {}
    raw = _raw(terminal)
    return {'case_key': case['case_key'], 'task_id': case['task_id'],
            'public_instruction': case['official_record']['instruction'],
            'official_answer_position': case['official_record']['answer_position'],
            'original_raw_score': raw, 'original_protocol_state': terminal.get('protocol_state'),
            'original_effective_score': terminal.get('protocol_effective_accuracy'),
            'original_disposition': terminal.get('disposition'),
            'original_official_metrics': official.get('result'),
            'coverage': row.get('summary'), 'business_error_inferred_from_score': False}


def _instruction(case, terminal_ref, terminal):
    original = case['official_record']['instruction'].encode()
    if terminal.get('disposition') == 'reused_original_completed_attempt':
        retained = case['existing_attempt']
        require(checked(retained['original_instruction']).read_bytes() == original, 'Retained public instruction differs')
        rendered = retained['rendered_instruction']
        require(checked(rendered).read_bytes().startswith(original), 'Retained rendered instruction prefix differs')
        return {'original_instruction.md': retained['original_instruction'], 'actual_instruction.md': rendered}
    transport_ref = terminal['instruction_transport']; transport = read(transport_ref)
    rendered = reference(checked(terminal_ref).parent / 'export/instruction.md')
    expected = original + transport['appended_bytes_utf8'].encode()
    require(transport.get('original_prefix_byte_identical') is True
            and transport.get('business_or_target_hint_added') is False
            and transport['original_instruction_sha256'] == hashlib.sha256(original).hexdigest()
            and transport['rendered_instruction_sha256'] == hashlib.sha256(expected).hexdigest() == rendered['sha256']
            and checked(rendered).read_bytes() == expected, 'Actual original-plus-IO instruction differs')
    return {'instruction_transport.json': transport_ref, 'actual_instruction.md': rendered}


def _material_artifacts(case, terminal_ref, terminal, evidence, evaluator_ref):
    require(evidence['case_terminal'] == terminal_ref, 'Evidence must bind this exact actual terminal')
    require(evidence['source'] == case['input'] and evidence['reference'] == case['goal'],
            'Evidence input/gold must equal the frozen original inventory')
    require(evidence['official_evaluator'] == evaluator_ref, 'Official evaluator differs')
    scoring = terminal['official_primary']
    artifacts = {'case_terminal.json': terminal_ref}
    artifacts.update(_instruction(case, terminal_ref, terminal))
    if terminal.get('disposition') == 'reused_original_completed_attempt':
        retained = read(terminal['original_postscore'])
        require(retained.get('kind') == 'fixed_external_pair_original_official_postscore'
                and retained.get('status') == 'completed', 'Wrong original retained score receipt')
        matches = [e for e in retained['results'] if e['task_id'] == case['task_id']]
        require(len(matches) == 1 and matches[0]['official_scores']['original_official'] == scoring,
                'Retained original score differs from this terminal')
        scoring_output, scoring_evaluator = scoring['same_submitted_alias'], retained['pinned_evaluator']
        artifacts['original_postscore.json'] = terminal['original_postscore']
    else:
        scoring_output, scoring_evaluator = scoring['output'], scoring['evaluator']
    for name, alias in (('source', 'input'), ('reference', 'reference'), ('output', 'output')):
        require(same_bytes(evidence[name], scoring_output if alias == 'output' else scoring[alias]), 'Official scorer used different workbook bytes')
    require(same_bytes(evidence['official_evaluator'], scoring_evaluator), 'Official scorer used different evaluator bytes')
    for name, filename in (('source', 'input.xlsx'), ('reference', 'gold.xlsx'), ('output', 'output.xlsx'),
                           ('trajectory', 'trajectory.json'), ('result', 'original_result.json'),
                           ('official_evaluator', 'official_evaluator.py')):
        artifacts[filename] = evidence[name]
    for ref in artifacts.values(): checked(ref)
    return artifacts


def _ready(case, terminal_ref, terminal, off, region, evaluator_ref):
    require(region.get('status') == 'complete', 'Full-region census is not complete')
    region_ref = region['report']; census = read(region_ref)
    report_ref, report = off
    require(census.get('kind') == 'complete_official_comparison_region_case_census' and census.get('version') == 1,
            'Wrong full-region census kind')
    require(census['case_key'] == report['case_id'] == case['case_key'], 'Wrong evidence case')
    require(not census.get('holds') and census.get('official_score_consistency') is True,
            'A census inconsistency is an evidence hold, not a business failure')
    a, b = report['evidence'], census['evidence']
    require(report.get('public_instruction') == case['official_record']['instruction'], 'Offline public instruction differs')
    for name in ('source', 'reference', 'output', 'trajectory', 'result', 'case_terminal', 'official_evaluator'):
        require(a.get(name) is not None and a[name] == b.get(name), 'Offline/census artifact mismatch: ' + name)
    artifacts = _material_artifacts(case, terminal_ref, terminal, a, evaluator_ref)
    artifacts.update({'offline_report.json': report_ref, 'region_census.json': region_ref})
    require(census.get('original_official_score') == terminal['official_primary']['result'], 'Census original score differs')
    summary = census['summary']
    require(type(summary['region_position_count']) is int and summary['region_position_count'] >= 0
            and type(summary['miss_count']) is int and summary['miss_count'] >= 0, 'Invalid full-region counts')
    return artifacts, summary


def _evaluator_error(case, terminal_ref, terminal, region, evaluator_ref):
    census_ref = region['report']; census = read(census_ref); score = terminal['official_primary']['result']
    message = score.get('error_message', '')
    require(region['status'] == census.get('status') == 'hold'
            and census.get('kind') == 'complete_official_comparison_region_case_census' and census.get('version') == 1
            and census['case_key'] == case['case_key'] and region['case_terminal'] == terminal_ref
            and census.get('original_official_score') == score
            and all(score.get(k) == 0 for k in ('accuracy', 'regression_accuracy', 'modification_accuracy'))
            and re.fullmatch(r'unbound prefix: line [1-9][0-9]*, column [0-9]+', message) is not None
            and census.get('holds') == [{'reason': 'offline_comparison_exception', 'exception': 'ParseError', 'message': message}]
            and census.get('official_score_consistency') is None
            and census.get('summary') == {'region_position_count': None, 'miss_count': None}
            and not census.get('all_misses'), 'Only an exact original parser failure may use error-only diagnosis')
    artifacts = _material_artifacts(case, terminal_ref, terminal, census['evidence'], evaluator_ref)
    with zipfile.ZipFile(checked(case['input'])) as archive: metadata = archive.read('docProps/core.xml')
    observed = None
    try: ET.fromstring(metadata)
    except ET.ParseError as error: observed = str(error)
    require(observed == message, 'Original source metadata does not reproduce the same parser error')
    artifacts['region_census.json'] = census_ref
    return artifacts, {'kind': 'original_evaluator_loading_error_only', 'original_error': message,
        'original_raw_score': score['accuracy'], 'source_part': 'docProps/core.xml',
        'source_part_sha256': hashlib.sha256(metadata).hexdigest(), 'miss_count': None,
        'region_position_count': None, 'financial_error_established': False}


def _infra(case, terminal_ref, terminal):
    artifacts = {'case_terminal.json': terminal_ref, 'input.xlsx': case['input'], 'gold.xlsx': case['goal']}
    retained = terminal.get('retained_records', {})
    for name in ('redacted_error', 'model_process_terminal.json', 'model_process_started.json'):
        if name in retained:
            artifacts['retained_' + name.replace('/', '_') + ('' if name.endswith('.json') else '.json')] = retained[name]
    require(len(artifacts) > 3, 'Infrastructure diagnosis needs retained error/process evidence')
    folder = checked(terminal_ref).parent
    trials = list((folder / 'evaluation/harbor_jobs').glob('*/*/result.json'))
    require(len(trials) <= 1, 'Multiple actual trials require an explicit evidence hold')
    if trials:
        from dirhash import dirhash
        trial = trials[0].parent; result = read(trials[0]); task = folder / 'evaluation/snapshot/SpreadsheetEval' / case['task_id']
        require(result['task_name'] == 'sheetsfactory/' + case['task_id']
                and result['trial_name'] == result['config']['trial_name'] == trial.name
                and trial.name.startswith(case['task_id'] + '__')
                and Path(result['task_id']['path']) == Path(result['config']['task']['path']) == task
                and re.fullmatch(r'[a-f0-9]{64}', result['task_checksum']) is not None
                and dirhash(task, 'sha256') == result['task_checksum'], 'Actual infrastructure trial task identity/hash differs')
        require(same_bytes(reference(task / 'environment/input.xlsx'), case['input'])
                and same_bytes(reference(task / 'tests/reference.xlsx'), case['goal']), 'Infrastructure trial input/gold bytes differ')
        artifacts.update({'original_result.json': reference(trials[0]),
            'verifier_diagnostics.json': reference(trial / 'verifier/diagnostics.json'),
            'actual_instruction.md': reference(task / 'instruction.md')})
        for name, relative in (('trajectory.json', 'agent/trajectory.json'), ('output.xlsx', 'artifacts/app/output.xlsx')):
            if (trial / relative).is_file(): artifacts[name] = reference(trial / relative)
    for ref in artifacts.values(): checked(ref)
    return artifacts


def prepare(inventory, execution_census, deep_ledger, offline_scan, region_index, output, *, _toy=False):
    output = Path(output).absolute(); require(not output.exists(), 'Use a fresh snapshot directory')
    refs = {k: artifact(v) for k, v in {'inventory': inventory, 'execution_census': execution_census,
            'deep_ledger': deep_ledger, 'offline_scan': offline_scan, 'region_index': region_index}.items()}
    inv, census, ledger, scan, regions = [read(refs[k]) for k in refs]
    cases = inv['cases']; keys = [c['case_key'] for c in cases]
    require(len(set(keys)) == len(keys), 'Inventory case identities must be unique')
    if not _toy:
        require(refs['inventory']['sha256'] == INVENTORY_SHA and len(cases) == 200 and sum(c['category'] == 'Financial_Model' for c in cases) == 100
                and sum(c['category'] == 'Debugging' for c in cases) == 100, 'Use the complete original 200-case inventory')
    require(census['inventory'] == refs['inventory'] == scan['inventory'] == regions['inventory'], 'Inventory bindings differ')
    require(ledger['census'] == refs['execution_census'], 'Manual ledger must bind this exact execution snapshot')
    require(regions.get('kind') == 'complete_official_comparison_region_census_batch' and regions.get('version') == 1,
            'Use the complete region-index schema, including pending cases')
    require(regions['case_order'] == keys, 'Region inventory order differs')
    cr = _indexed(census['rows'], 'case_key'); lr = _indexed(ledger['rows'], 'case_key'); rr = _indexed(regions['cases'], 'case_key')
    require(set(cr) == set(lr) == set(rr) == set(keys), 'Retain every original case, including holds/pending')
    offline = _offline(scan); prepared = []
    for case in cases:
        key = case['case_key']; row = {'case_key': key, 'task_id': case['task_id'], 'status': 'not_a_failure',
                'terminal': cr[key].get('terminal'), 'holds': [], 'artifacts': {}}
        terminal_ref = row['terminal']
        if terminal_ref is None:
            row['status'] = 'pending_original_attempt'
        else:
            terminal = read(terminal_ref)
            require(terminal['case_key'] == key and terminal['task_id'] == case['task_id'], 'Actual terminal case identity differs')
            raw = _raw(terminal)
            require(cr[key].get('official_raw') == raw, 'Execution census original raw score differs')
            require(lr[key].get('original_terminal') == terminal_ref, 'Manual ledger binds a different original terminal')
            row.update(original_raw_score=raw, original_protocol_state=terminal.get('protocol_state'))
            row['summary'] = _summary(case, terminal, rr[key])
            if lr[key].get('deep_review_completed'):
                require(raw == 0 and lr[key].get('receipt'), 'Existing deep analysis must bind an actual failed case')
                checked(lr[key]['receipt']); row.update(status='reused_manual_review', manual_review=lr[key]['receipt'])
            elif terminal.get('disposition') == 'infrastructure_or_driver_hold':
                try: row.update(status='ready_infrastructure', artifacts=_infra(case, terminal_ref, terminal))
                except (ValueError, KeyError) as error: row.update(status='evidence_hold', holds=[str(error)])
            elif raw == 0:
                try:
                    require(rr[key]['case_terminal'] == terminal_ref, 'Missing exact-terminal full-region evidence')
                    if rr[key]['status'] == 'hold':
                        artifacts, summary = _evaluator_error(case, terminal_ref, terminal, rr[key], inv['official_evaluator'])
                        row.update(status='ready_evaluator_error', artifacts=artifacts)
                    else:
                        require(key in offline, 'Missing exact-terminal offline evidence')
                        artifacts, summary = _ready(case, terminal_ref, terminal, offline[key], rr[key], inv['official_evaluator'])
                        row.update(status='ready', artifacts=artifacts)
                    row['summary']['coverage'] = summary
                except (ValueError, KeyError) as error:
                    row.update(status='evidence_hold', holds=[str(error)])
            elif raw is None:
                row.update(status='evidence_hold', holds=['Original score is unknown; do not invent a business failure'])
        if row['status'].startswith('ready'):
            prior_path = REGISTRY / (reservation_id(row) + '.json')
            if prior_path.exists():
                prior = read(prior_path)
                require(prior['case_key'] == key and prior['original_terminal'] == terminal_ref
                        and prior['version'] == VERSION, 'Previous reservation identity differs')
                prior_prep = read(prior['preparation'])
                require(any(r['case_key'] == key and r['context_id'] == prior['context_id'] for r in prior_prep['cases']),
                        'Previous reservation has no bound context')
                row.update(status='prior_review_reserved', previous_reservation=reference(prior_path))
                prior_terminal = checked(prior['preparation']).parent / 'cases' / case['task_id'] / 'terminal.json'
                if prior_terminal.exists():
                    previous = read(prior_terminal)
                    require(previous['case_key'] == key and previous['context_id'] == prior['context_id'],
                            'Previous review terminal identity differs')
                    row['previous_review_terminal'] = reference(prior_terminal)
        row['context_id'] = digest({k: v for k, v in row.items() if k != 'context_id'})
        prepared.append(row)
    output.mkdir(parents=True)
    return write(output / 'preparation.json', {'kind': KIND, 'version': VERSION, 'at': now(), 'inputs': refs,
            'policy': POLICY, 'recipes': recipes(), 'case_order': keys, 'cases': prepared,
            'actual_model_calls': 0, 'qualification_inherited': False, 'production_eligible': False})


def validate_prepared(output, *, case_key=None):
    value = read(Path(output) / 'preparation.json')
    require(value['kind'] == KIND and value['version'] == VERSION and value['policy'] == POLICY, 'Wrong diagnosis protocol')
    require(value['recipes'] == recipes(), 'Changed diagnosis code/prompt/client/config')
    for ref in value['inputs'].values(): checked(ref)
    for row in value['cases']:
        expected = digest({k: v for k, v in row.items() if k != 'context_id'})
        require(row['context_id'] == expected, 'Changed case context')
        if case_key is None or row['case_key'] == case_key:
            if row['terminal']: checked(row['terminal'])
            if row.get('manual_review'): checked(row['manual_review'])
            for name in ('previous_reservation', 'previous_review_terminal'):
                if name in row: checked(row[name])
            for ref in row['artifacts'].values(): checked(ref)
    return value


def reservation_id(row):
    return digest({'case_key': row['case_key'], 'terminal': row['terminal'], 'version': VERSION})


def _failure(folder, error):
    text = ''.join(traceback.format_exception(error))
    for name, value in os.environ.items():
        if re.search(r'KEY|TOKEN|SECRET|PASSWORD', name, re.I) and len(value) >= 8:
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'(?i)(bearer\s+)[^\s\"\x27]+', r'\1[REDACTED]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', text)
    text = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', text)
    return write(folder / 'private/diagnosis_error.json', {'error_type': type(error).__name__, 'traceback': text})


def stage(row, folder):
    workspace = folder / 'evidence'; workspace.mkdir(parents=True)
    copied = {}
    for name, ref in row['artifacts'].items():
        require(Path(name).name == name and not name.startswith('.'), 'Evidence aliases must be plain filenames')
        source = checked(ref); target = workspace / name
        shutil.copyfile(source, target)
        require(same_bytes(reference(target), ref) and reference(source) == ref, 'Evidence changed while staging')
        target.chmod(0o444); copied[name] = ref
    write(workspace / 'case_summary.json', row['summary'])
    write(workspace / 'public_instruction.json', {'instruction': row['summary']['public_instruction']})
    write(workspace / 'evidence_manifest.json', {'case_key': row['case_key'], 'context_id': row['context_id'],
            'status': row['status'], 'artifacts': copied, 'raw_score': row['summary']['original_raw_score'],
            'protocol': row['summary']['original_protocol_state'], 'only_local_aliases_are_readable': True})
    return workspace


def output_schema(row):
    text = {'type': 'string'}
    evidence = {'type': 'object', 'additionalProperties': False,
        'properties': {k: text for k in ('artifact', 'pointer', 'cell', 'trace_step', 'public_rule', 'observed', 'expected', 'arithmetic')},
        'required': ['artifact', 'pointer', 'cell', 'trace_step', 'public_rule', 'observed', 'expected', 'arithmetic']}
    cause = {'type': 'object', 'additionalProperties': False, 'properties': {
        'cause_id': text, 'certainty': {'type': 'string', 'enum': ['confirmed', 'hypothesis', 'unknown']},
        'classification': {'type': 'string', 'enum': ['financial_error', 'completeness', 'extra_change', 'formatting',
            'gold_or_cache_conflict', 'policy_ambiguity', 'representation', 'infrastructure', 'unknown']},
        'statement': text, 'miss_count': {'type': 'integer', 'minimum': 0},
        'evidence': {'type': 'array', 'items': evidence}, 'limits': text},
        'required': ['cause_id', 'certainty', 'classification', 'statement', 'miss_count', 'evidence', 'limits']}
    return {'type': 'object', 'additionalProperties': False, 'properties': {
        'case_key': {'type': 'string', 'const': row['case_key']}, 'context_id': {'type': 'string', 'const': row['context_id']},
        'case_summary': text, 'all_misses_accounted_for': {'type': 'boolean'},
        'causes': {'type': 'array', 'minItems': 1, 'items': cause},
        'transfers': {'type': 'array', 'maxItems': 3, 'items': {'type': 'object', 'additionalProperties': False,
            'properties': {k: text for k in ('cause_id', 'dimension', 'amplification', 'unvalidated_limits')},
            'required': ['cause_id', 'dimension', 'amplification', 'unvalidated_limits']}},
        'unknowns': {'type': 'array', 'items': text}},
        'required': ['case_key', 'context_id', 'case_summary', 'all_misses_accounted_for', 'causes', 'transfers', 'unknowns']}


def validate_review(row, value):
    from jsonschema import Draft202012Validator
    Draft202012Validator(output_schema(row)).validate(value)
    ids = [c['cause_id'] for c in value['causes']]
    require(ids == [f"{row['case_key']}:C{i:02d}" for i in range(1, len(ids) + 1)], 'Use sequential case-bound cause numbers')
    if row['status'] == 'ready':
        require(value['all_misses_accounted_for'] and sum(c['miss_count'] for c in value['causes']) == row['summary']['coverage']['miss_count'],
                'Diagnostic groups must account for the whole mismatch census')
    else:
        require(not value['all_misses_accounted_for'] and all(c['classification'] == 'infrastructure' and c['miss_count'] == 0 for c in value['causes']),
                'Infrastructure-null cannot become a measured business failure')
    for cause in value['causes']:
        if cause['certainty'] == 'confirmed' and cause['classification'] in ('financial_error', 'completeness', 'extra_change'):
            require(cause['evidence'] and all(e['cell'] and e['trace_step'] and e['public_rule'] for e in cause['evidence']),
                    'Confirmed task error requires cells, trajectory steps and public rules')
            if cause['classification'] == 'financial_error':
                require(any(e['arithmetic'].strip() for e in cause['evidence']), 'Financial claims need grounded arithmetic')
        for evidence in cause['evidence']:
            require(evidence['artifact'] in row['artifacts'], 'Citations must name mounted bound evidence')
    require(all(t['cause_id'] in ids and t['unvalidated_limits'].strip() for t in value['transfers']), 'Transfer must bind cause and limits')
    return value


class ResearchCodex(CodexCLI):
    def _build_command(self, workspace, endpoint, isolated, name, **kwargs):
        require(isolated, 'Diagnostic reviewer requires the evidence-only container')
        command = super()._build_command(workspace, endpoint, True, name, **kwargs)
        flag = command.index('--dangerously-bypass-approvals-and-sandbox')
        command[flag:flag+1] = ['--sandbox', 'read-only', '-c', 'approval_policy="never"',
            '-c', 'web_search="disabled"', '-c', f'model_providers.{self.provider}.request_max_retries=0',
            '-c', f'model_providers.{self.provider}.stream_max_retries=0']
        mount = str(workspace) + ':/workspace:rw'
        require(command.count(mount) == 1, 'Expected exactly one evidence workspace mount')
        command[command.index(mount)] = str(workspace) + ':/workspace:ro'
        command[2:2] = ['--read-only', '--tmpfs', '/root:rw,nosuid,nodev,size=128m']
        return command


def _internal_review(request):
    req = read(request); folder = Path(request).parent
    row = req['case']; output = Path(req['snapshot'])
    frozen = validate_prepared(output, case_key=row['case_key'])
    require(row in frozen['cases'] and row['status'].startswith('ready'), 'Unknown frozen reviewer case')
    require(folder == output / 'cases' / row['task_id'], 'Internal request has an unexpected case directory')
    reservation = read(checked(req['reservation']))
    require(reservation['context_id'] == row['context_id'] and reservation['preparation'] == reference(output / 'preparation.json'),
            'Case reservation differs')
    write(folder / 'review_started.json', {'at': now(), 'request': reference(request), 'no_retry': True})
    audit = AuditStore(folder / 'audit', {'id': row['task_id'], 'status': 'running', 'research_only': True})
    start = time.monotonic(); result = None
    try:
        workspace = stage(row, folder)
        import yaml
        config = yaml.safe_load((ROOT / 'config/llm.yaml').read_text())
        config.update(model=MODEL, reasoning_effort='high', timeout_seconds=900, max_parallel_calls=1, roles={})
        client = ResearchCodex(ROOT, folder, audit, config)
        value = client.complete(PROMPT.read_text() + '\n\nCase: ' + row['case_key'] + '\nContext: ' + row['context_id'],
                'official_failure_diagnosis', task_id=row['task_id'], stage='research_diagnosis',
                workspace=workspace, isolated=True, timeout=900, output_schema=output_schema(row))
        result = {'status': 'diagnosed', 'review': write(folder / 'review.json', validate_review(row, value))}
    except Exception as error:
        # Provider details remain in the existing redacted private call records.
        result = {'status': 'unknown', 'error_type': type(error).__name__,
                  'reason': 'Inspect retained private call records; no retry performed', 'error': _failure(folder, error)}
    finally:
        audit.update_run(status=result['status'] if result else 'unknown', elapsed_seconds=time.monotonic()-start)
        audit.export(); audit.db.close()
    return write(folder / 'terminal.json', {'kind': 'official_case_diagnostic_review', 'version': VERSION,
        'case_key': row['case_key'], 'context_id': row['context_id'], 'original_terminal': row['terminal'],
        **result, 'elapsed_seconds': time.monotonic()-start, 'actual_calls': len(list((folder / 'llm_calls/private').glob('*/result.json'))),
        'independent_financial_verification_passed': False, 'qualification_or_difficulty_granted': False,
        'original_score_modified': False, 'no_retry': True})


def _launch(output, row, reservation, audit):
    folder = output / 'cases' / row['task_id']; folder.mkdir(parents=True)
    request = write(folder / 'request.json', {'snapshot': str(output), 'case': row, 'reservation': reservation})
    audit.task(row['task_id'], status='review_running', node='single_research_diagnosis', started_at=now())
    proc = None; error_ref = None
    try:
        with (folder / 'child.log').open('xb') as log:
            proc = subprocess.Popen([sys.executable, '-B', str(Path(__file__).absolute()), '--internal-review', request['path']],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            audit.emit('diagnosis.child_started', task_id=row['task_id'], pid=proc.pid)
            proc.wait()  # Child Codex owns the fixed 900-second call timeout.
    except Exception as error: error_ref = _failure(folder, error)
    path = folder / 'terminal.json'
    if not path.exists():
        return write(path, {'kind': 'official_case_diagnostic_review', 'version': VERSION, 'case_key': row['case_key'],
            'context_id': row['context_id'], 'status': 'unknown', 'reason': 'Review child did not retain a terminal',
            'child_returncode': proc.returncode if proc else None, 'error': error_ref,
            'no_retry': True, 'qualification_or_difficulty_granted': False})
    return reference(path)


def _copy_calls(output, audit, seen):
    with audit.lock:
        for path in (output / 'cases').glob('*/audit/run.sqlite'):
            try:
                db = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
                db.execute('PRAGMA query_only=ON')
                rows = db.execute('SELECT rowid,payload FROM calls ORDER BY rowid').fetchall(); db.close()
                for index, payload in rows:
                    identity = (str(path), index)
                    if identity not in seen: audit.record('calls', json.loads(payload)); seen.add(identity)
            except sqlite3.Error: continue


def execute_prepared(output):
    output = Path(output).absolute(); frozen = validate_prepared(output)
    require(not (output / 'started.json').exists(), 'This snapshot has already been spent')
    lease = ProducerLease(output).acquire(); audit = server = thread = None; stop = threading.Event()
    start = time.monotonic(); completed = {}; seen = set()
    try:
        audit = AuditStore(output / 'audit', {'id': output.name, 'status': 'running', 'research_only': True,
            'producer_pid': os.getpid(), 'target_count': 0, 'official_case_count': len(frozen['cases'])})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        audit.update_run(dashboard_url=url)
        print(json.dumps({'dashboard_url': url, 'pid': os.getpid()}), flush=True)
        ready = [r for r in frozen['cases'] if r['status'].startswith('ready')]
        REGISTRY.mkdir(parents=True, exist_ok=True); reservations = {}
        # Exclusive global creates are permanent even if launch/parse/provider fails.
        # Check all names first; partial reservations from an actual collision stay.
        require(all(not (REGISTRY / (reservation_id(r) + '.json')).exists() for r in ready),
                'A case/version is already reserved in another snapshot; never resample')
        for row in ready:
            reservations[row['case_key']] = write(REGISTRY / (reservation_id(row) + '.json'), {
                'case_key': row['case_key'], 'context_id': row['context_id'], 'version': VERSION,
                'original_terminal': row['terminal'], 'preparation': reference(output / 'preparation.json'),
                'at': now(), 'no_retry': True})
        write(output / 'started.json', {'at': now(), 'preparation': reference(output / 'preparation.json'),
              'reservations': reservations, 'model': MODEL, 'retries': 0})
        for row in frozen['cases']: audit.task(row['task_id'], case_key=row['case_key'], status=row['status'])
        def heartbeat():
            while not stop.wait(10):
                _copy_calls(output, audit, seen)
                audit.update_run(elapsed_seconds=time.monotonic()-start, completed_reviews=len(completed)); audit.export()
        thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_launch, output, r, reservations[r['case_key']], audit): r for r in ready}
            for future in as_completed(futures):
                row = futures[future]; ref = future.result(); completed[row['case_key']] = ref
                value = read(ref)
                audit.task(row['task_id'], status=value['status'], terminal=ref, elapsed_seconds=value.get('elapsed_seconds'))
                audit.emit('diagnosis.case_completed', task_id=row['task_id'], terminal=ref)
                _copy_calls(output, audit, seen); audit.export()
        rows = [{**r, 'diagnosis': completed.get(r['case_key'])} for r in frozen['cases']]
        return write(output / 'terminal.json', {'kind': 'complete_official_failure_diagnosis_snapshot', 'version': VERSION,
            'preparation': reference(output / 'preparation.json'), 'cases': rows, 'every_original_case_retained': True,
            'actual_diagnostic_calls': len(audit.snapshot()['llm_calls']), 'retries': 0,
            'all_failures_deeply_verified': False, 'independent_financial_verification_passed': False,
            'qualification_or_difficulty_granted': False, 'original_scores_modified': False})
    finally:
        stop.set()
        if thread: thread.join(timeout=2)
        if audit:
            _copy_calls(output, audit, seen)
            audit.update_run(status='completed' if (output / 'terminal.json').exists() else 'unknown',
                             elapsed_seconds=time.monotonic()-start); audit.export()
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path); parser.add_argument('--execution-census', type=Path)
    parser.add_argument('--deep-ledger', type=Path); parser.add_argument('--offline-scan', type=Path)
    parser.add_argument('--region-index', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true')
    parser.add_argument('--internal-review', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    inputs = [args.inventory, args.execution_census, args.deep_ledger, args.offline_scan, args.region_index, args.output]
    if args.internal_review:
        require(not any(inputs) and not args.prepared and not args.run, 'Internal review accepts one frozen request only')
        result = _internal_review(args.internal_review)
    elif args.prepared:
        require(not any(inputs), 'Do not replace prepared evidence')
        result = execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(all(inputs) and not args.run, 'Supply all evidence inputs for prepare; run is a separate explicit step')
        result = prepare(*inputs)
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
