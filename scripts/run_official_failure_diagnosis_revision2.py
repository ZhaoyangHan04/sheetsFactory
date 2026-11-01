#!/usr/bin/env python3
"""Research-only transport revision: read-only container, native inner tools.

V1's sixteen inaccessible-evidence replies remain unknown. This namespace does
not rerun benchmark solutions, alter scores, or inherit any diagnosis/quality.
No container or API is started by import or preparation.
"""
from __future__ import annotations

import argparse
import ast
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'scripts/run_official_failure_diagnosis.py'
FROZEN_SHA = 'ed9de5583b4f297826e0623c337178d758f0820c4c9931868d3a967771571fc8'
require = lambda value, message: None if value else (_ for _ in ()).throw(ValueError(message))
require(hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_SHA, 'Changed frozen V1 diagnosis implementation')
_N = {'__file__': str(FROZEN), '__name__': '_private_official_diagnosis_v2'}
exec(compile(FROZEN.read_bytes(), str(FROZEN), 'exec'), _N)
_N.update(__file__=str(Path(__file__).absolute()), VERSION=2,
          KIND='prepared_official_failure_diagnosis_snapshot_revision2',
          REGISTRY=ROOT / 'outputs/research/official_failure_diagnosis_once_v2')
_N['POLICY'] = {**deepcopy(_N['POLICY']), 'review_version': 2,
                'evidence_transport': 'read_only_container_native_inner_tools_v2'}
read, write, reference, checked, now = (_N[n] for n in ('read', 'write', 'reference', 'checked', 'now'))
_LIMIT = ContextVar('diagnosis_fixed_dispatch_limit', default=1)


def _retain_case(prepared, row):
    if row['status'].startswith('ready') and sum(r['status'].startswith('ready') for r in prepared) >= _LIMIT.get():
        row['status'] = 'deferred_by_frozen_dispatch_limit'
        row['context_id'] = _N['digest']({k: v for k, v in row.items() if k != 'context_id'})
    prepared.append(row)


tree = ast.parse(FROZEN.read_bytes())
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare')
class _LimitPrepare(ast.NodeTransformer):
    count = 0
    def visit_Call(self, n):
        n = self.generic_visit(n)
        if ast.unparse(n.func) == 'prepared.append' and len(n.args) == 1 and ast.unparse(n.args[0]) == 'row':
            self.count += 1
            return ast.Call(ast.Name('_retain_case', ast.Load()), [ast.Name('prepared', ast.Load()), n.args[0]], [])
        return n
transform = _LimitPrepare(); node = transform.visit(node)
require(transform.count == 1, 'Unknown frozen preparation append sites')
module = ast.Module(body=[node], type_ignores=[]); ast.fix_missing_locations(module)
_N['_retain_case'] = _retain_case
exec(compile(module, str(FROZEN), 'exec'), _N)
_prepare, _validate, _execute, _recipes = (_N[n] for n in ('prepare', 'validate_prepared', 'execute_prepared', 'recipes'))


def recipes():
    return {**_recipes(), str(FROZEN): reference(FROZEN),
            str(ROOT / 'tests/test_official_failure_diagnosis_revision2.py'):
                reference(ROOT / 'tests/test_official_failure_diagnosis_revision2.py')}
_N['recipes'] = recipes


class ResearchCodex(_N['ResearchCodex']):
    def _build_command(self, workspace, endpoint, isolated, name, **kwargs):
        command = super()._build_command(workspace, endpoint, isolated, name, **kwargs)
        require(command.count('--sandbox') == 1, 'Unknown frozen inner sandbox switches')
        index = command.index('--sandbox')
        require(command[index:index+2] == ['--sandbox', 'read-only'], 'Unexpected inner permission mode')
        command[index:index+2] = ['--dangerously-bypass-approvals-and-sandbox']
        require('--read-only' in command and str(workspace) + ':/workspace:ro' in command
                and '--cap-drop' in command and command[command.index('--cap-drop')+1] == 'ALL',
                'Physical container/evidence protection changed')
        return command
_N['ResearchCodex'] = ResearchCodex


_schema = _N['output_schema']
def output_schema(row):
    value = _schema(row)
    properties = value['properties']['causes']['items']['properties']
    properties['cause_id'] = {'type': 'string', 'pattern': '^' + re.escape(row['case_key']) + r':C[0-9]{2,}$',
        'description': 'Sequential case-bound identifiers, starting ' + row['case_key'] + ':C01, then :C02, :C03.'}
    value['properties']['all_misses_accounted_for']['const'] = row['status'] == 'ready'
    if row['status'] != 'ready':
        properties['classification']['enum'] = ['infrastructure']
        properties['miss_count']['const'] = 0
    return value
_N['output_schema'] = output_schema


def _checked_failure(value, *, toy=False):
    path = checked(value) if isinstance(value, dict) else checked(reference(value)); result = read(path)
    require(result.get('kind') == 'stopped_official_failure_diagnosis_access_failure_v1'
            and result.get('version') == 1 and result.get('semantic_reviews_completed') == 0
            and result.get('original_scores_modified') is False and result.get('parent_alive_observed') is False,
            'Bind the retained V1 transport failure, not a prior business diagnosis')
    if not toy:
        require(result.get('actual_API_completed_calls') == result.get('diagnostic_unknown_terminals') == 16
                and result.get('reserved_not_dispatched') == 1
                and result.get('all16_raw_replies_report_missing_bubblewrap') is True
                and result['frozen_implementation']['sha256'] == FROZEN_SHA,
                'Wrong original stopped failure inventory')
        for name in ('preparation', 'started', 'frozen_implementation', 'frozen_prompt', 'calls_and_reservations'):
            checked(result[name])
        custody = read(result['calls_and_reservations'])
        for row in custody['rows']:
            for name in ('reservation', 'original_terminal', 'model_call', 'raw_reply', 'events', 'case_terminal'):
                if name in row: checked(row[name])
    return reference(path)


def prepare(inventory, execution_census, deep_ledger, offline_scan, region_index, output, *,
            prior_failure, dispatch_limit=1, _toy=False):
    require(type(dispatch_limit) is int and 1 <= dispatch_limit <= 200, 'Freeze a dispatch limit from 1 to 200')
    previous = _checked_failure(prior_failure, toy=_toy)
    token = _LIMIT.set(dispatch_limit)
    try: result = _prepare(inventory, execution_census, deep_ledger, offline_scan, region_index, output, _toy=_toy)
    finally: _LIMIT.reset(token)
    write(Path(output) / 'revision2_provenance.json', {'kind': 'official_diagnosis_transport_revision2_provenance',
        'version': 2, 'preparation': result, 'prior_stopped_diagnosis': previous,
        'frozen_v1_implementation': reference(FROZEN), 'implementation': reference(__file__),
        'dispatch_limit': dispatch_limit, 'prototype_toy_only': _toy,
        'old_unknowns_not_promoted_to_causes': True, 'benchmark_solution_repeated': False})
    return result


def validate_prepared(output, *, case_key=None):
    result = _validate(output, case_key=case_key); sidecar = read(Path(output) / 'revision2_provenance.json')
    require(sidecar['kind'] == 'official_diagnosis_transport_revision2_provenance' and sidecar['version'] == 2
            and sidecar['preparation'] == reference(Path(output) / 'preparation.json')
            and sidecar['frozen_v1_implementation'] == reference(FROZEN)
            and sidecar['implementation'] == reference(__file__)
            and type(sidecar['dispatch_limit']) is int and 1 <= sidecar['dispatch_limit'] <= 200
            and sum(r['status'].startswith('ready') for r in result['cases']) <= sidecar['dispatch_limit'],
            'Changed V2 transport provenance or fixed dispatch selection')
    _checked_failure(sidecar['prior_stopped_diagnosis'], toy=sidecar['prototype_toy_only'])
    return result
_N['validate_prepared'] = validate_prepared


PROBE_PROGRAM = r'''
import errno,hashlib,json
from pathlib import Path
data=Path('/workspace/nonce.txt').read_bytes()
given=Path('/workspace/input.xlsx').read_bytes()
def attempt(path):
    try:
        Path(path).write_bytes(b'controlled permission probe')
        return {'written':True,'errno':None}
    except OSError as error:
        return {'written':False,'errno':error.errno}
denied={k:attempt(p) for k,p in [('workspace','/workspace/blocked'),('input','/workspace/input.xlsx'),('rootfs','/diagnosis_rootfs_probe')]}
allowed={k:attempt(p) for k,p in [('tmp','/tmp/diagnosis_probe'),('root','/root/diagnosis_probe')]}
print(json.dumps({'nonce':data.decode('ascii'),'sha256':hashlib.sha256(data).hexdigest(),
 'input_sha256':hashlib.sha256(given).hexdigest(),'denied':denied,'allowed':allowed}))
'''


def prepare_access_probe(output):
    out = Path(output); out.mkdir(parents=True, exist_ok=False); work = out / 'evidence'; work.mkdir()
    nonce = os.urandom(32).hex().encode('ascii'); (work / 'nonce.txt').write_bytes(nonce)
    (work / 'input.xlsx').write_bytes(b'nonfinancial permission-probe bytes')
    expected = write(out / 'expected.private.json', {'nonce': nonce.decode(), 'sha256': hashlib.sha256(nonce).hexdigest(),
        'input_sha256': reference(work / 'input.xlsx')['sha256'], 'files': [reference(work / 'nonce.txt'), reference(work / 'input.xlsx')]})
    return work, expected


def verify_probe(expected, observed):
    value = read(expected)
    for r in value['files']: checked(r)
    require(set(observed) == {'nonce', 'sha256', 'input_sha256', 'denied', 'allowed'}
            and all(observed[k] == value[k] for k in ('nonce', 'sha256', 'input_sha256'))
            and set(observed['denied']) == {'workspace', 'input', 'rootfs'}
            and set(observed['allowed']) == {'tmp', 'root'}
            and all(v == {'written': False, 'errno': 30} or v == {'written': False, 'errno': 13}
                    for v in observed['denied'].values())
            and all(v == {'written': True, 'errno': None} for v in observed['allowed'].values()),
            'The actual zero-API read/write container probe did not pass')
    return observed


def _probe_command(workspace):
    import yaml
    config = yaml.safe_load((ROOT / 'config/llm.yaml').read_text())
    return ['docker', 'run', '--rm', '--read-only', '--network', 'none', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
        '--security-opt', 'no-new-privileges', '--user', '0:0', '--memory', str(config.get('container_memory', '2g')),
        '--cpus', str(config.get('container_cpus', 2)), '--pids-limit', '256',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=1g', '--tmpfs', '/root:rw,nosuid,nodev,size=128m',
        '--volume', str(workspace) + ':/workspace:ro', '--workdir', '/workspace', '--entrypoint', 'python3',
        config.get('container_image', 'sheetsfactory-lo:24.2'), '-c', PROBE_PROGRAM]


def container_access_probe(output):
    out = Path(output); work, expected = prepare_access_probe(out); command = _probe_command(work)
    process = subprocess.run(command, capture_output=True, text=True, timeout=60)
    stdout = write(out / 'process.json', {'command': command, 'returncode': process.returncode,
        'stdout': process.stdout, 'stderr': process.stderr, 'actual_API_calls': 0})
    require(process.returncode == 0, 'Zero-API container access probe failed; no review may start')
    value = verify_probe(expected, json.loads(process.stdout))
    return write(out / 'receipt.json', {'kind': 'actual_zero_API_diagnosis_container_access_probe', 'version': 2,
        'implementation': reference(__file__), 'expected': expected, 'process': stdout, 'result': value,
        'passed': True, 'actual_API_calls': 0, 'no_business_material_or_quality_claim': True})


def validate_access_probe(value):
    receipt = read(value); process = read(receipt['process'])
    require(receipt['kind'] == 'actual_zero_API_diagnosis_container_access_probe' and receipt['version'] == 2
            and receipt['implementation'] == reference(__file__) and receipt['passed'] is True
            and process['returncode'] == 0 and process['actual_API_calls'] == 0
            and process['command'] == _probe_command(checked(receipt['expected']).parent / 'evidence'), 'Wrong access-probe receipt')
    require(verify_probe(receipt['expected'], json.loads(process['stdout'])) == receipt['result'], 'Changed access-probe result')
    return receipt


def execute_prepared(output):
    output = Path(output); validate_prepared(output)
    require(not (output / 'started.json').exists(), 'This V2 snapshot has already been spent')
    require(read(output / 'revision2_provenance.json')['prototype_toy_only'] is False, 'Toy preparation may not call a provider')
    probe = output / 'access_probe/receipt.json'
    if not probe.exists(): container_access_probe(output / 'access_probe')
    validate_access_probe(reference(probe))
    return _execute(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inventory', 'execution-census', 'deep-ledger', 'offline-scan', 'region-index', 'output', 'prior-failure', 'prepared'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--dispatch-limit', type=int, default=1)
    parser.add_argument('--run', action='store_true'); parser.add_argument('--internal-review', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(); inputs = [args.inventory, args.execution_census, args.deep_ledger, args.offline_scan, args.region_index, args.output]
    if args.internal_review:
        require(not any(inputs) and not args.prepared and not args.run and not args.prior_failure, 'One frozen internal request only')
        result = _N['_internal_review'](args.internal_review)
    elif args.prepared:
        require(not any(inputs) and args.prior_failure is None, 'Do not replace frozen evidence')
        result = execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(all(inputs) and args.prior_failure and not args.run, 'Prepare first, then explicitly run a reviewed snapshot')
        result = prepare(*inputs, prior_failure=args.prior_failure, dispatch_limit=args.dispatch_limit)
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
