"""Independent B raw-primitive wire, two-half search and complete record audit.

Preparation makes no executable calls. Execution is explicit. This module
shares only the typed public schema and fixed record protocol with search A.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

from . import spec as schema

ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / 'search_b.cpp'
RECORD = struct.Struct(schema.RECORD_FORMAT)


def _require(value, message):
    if not value: raise ValueError(message)


def _ref(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file(), 'B artifacts must be regular absolute files')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def _read(record):
    _require(isinstance(record, dict) and _ref(record['path']) == record, 'B artifact identity changed')
    value = json.loads(Path(record['path']).read_text())
    _require(isinstance(value, dict), 'A B JSON artifact must be an object')
    return value


def _write(path, value):
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return _ref(path)


def _recipe():
    return {str(path): _ref(path)['sha256'] for path in (Path(__file__).resolve(), KERNEL, Path(schema.__file__).resolve())}


def _check_recipe(recipe):
    _require(recipe == _recipe(), 'The frozen independent B code or public schema changed')


def raw_wire(public, active):
    """Serialize raw primitives; no project schedule or finance state exists."""
    public = schema.load_spec(public)
    indices = schema.active_indices(public, active)
    rows = ['CAPITAL_TWO_HALF_B_RAW_V1', f'{len(public["projects"])} {len(indices)}', ' '.join(map(str, indices))]
    rows.append(' '.join(str(public[field]) for field in ('opening_cash_pence', 'minimum_cash_pence',
        'lp_commitment_pence', 'facility_limit_pence', 'advance_rate_p12', 'tax_rate_p12', 'tax_loss_carry_years')))
    def annual(value): rows.append(' '.join(str(value[str(year)]) for year in schema.YEARS))
    annual(public['discount_factors_p12'])
    for project in public['projects']:
        rows.append(' '.join(map(str, (project['commission_year'] - schema.YEARS[0],
            project['sale_year'] - schema.YEARS[0], project['acquisition_cost_pence'],
            project['depreciation_years'], project['sale_proceeds_pence']))))
        annual(project['annual_revenue_pence']); annual(project['annual_opex_pence'])
    for scenario in public['scenarios']:
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
                      'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12'): annual(scenario[field])
    return '\n'.join(rows) + '\n'


def prepare(specification, output, *, active_project_ids=None):
    """Freeze raw input, protocol and B recipe; zero compiler/kernel calls."""
    public = schema.load_spec(specification)
    indices = schema.active_indices(public, active_project_ids)
    ids = [public['projects'][index]['id'] for index in indices]
    output = Path(output).absolute(); output.mkdir(parents=True)
    public_ref = _write(output / 'public_spec.json', public)
    wire = output / 'B_raw_primitives.txt'; wire.write_text(raw_wire(public, ids if active_project_ids is not None else None))
    return _write(output / 'preparation.json', {'kind': 'capital_allocation_scaled_B_preparation', 'version': 1,
        'public_spec': public_ref, 'spec_sha256': schema.canonical_sha(public), 'raw_wire': _ref(wire),
        'project_count': len(public['projects']), 'active_project_ids': ids,
        'toy_only': active_project_ids is not None, 'full_enumeration': active_project_ids is None,
        'expected_plan_count': 1 << len(ids), 'record_format': schema.RECORD_FORMAT,
        'record_bytes': schema.RECORD_BYTES, 'chunk_records': schema.CHUNK_RECORDS,
        'null_sentinel': schema.NULL_NPV, 'recipe_sha256': _recipe(),
        'compiler_calls': 0, 'kernel_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'qualification_claimed': False, 'task_count': 0})


def validate_prepared(preparation):
    if isinstance(preparation, (str, Path)):
        path = Path(preparation); preparation = _ref(path / 'preparation.json' if path.is_dir() else path)
    frozen = _read(preparation); public = schema.load_spec(_read(frozen['public_spec']))
    _require(frozen.get('kind') == 'capital_allocation_scaled_B_preparation' and frozen.get('version') == 1,
             'An independent B preparation is required')
    _check_recipe(frozen['recipe_sha256'])
    active = frozen['active_project_ids']; full = frozen['full_enumeration'] is True
    indices = schema.active_indices(public, None if full else active)
    _require(active == [public['projects'][index]['id'] for index in indices]
        and frozen['toy_only'] is (not full) and frozen['project_count'] == len(public['projects'])
        and frozen['expected_plan_count'] == 1 << len(indices)
        and frozen['spec_sha256'] == schema.canonical_sha(public), 'B dimension, source or choice mapping differs')
    _require(_ref(frozen['raw_wire']['path']) == frozen['raw_wire']
        and Path(frozen['raw_wire']['path']).read_text() == raw_wire(public, None if full else active),
        'The B wire differs from the complete raw public primitives')
    _require((frozen['record_format'], frozen['record_bytes'], frozen['chunk_records'], frozen['null_sentinel'])
        == (schema.RECORD_FORMAT, schema.RECORD_BYTES, schema.CHUNK_RECORDS, schema.NULL_NPV),
        'The complete B record protocol changed')
    return frozen, public


def scan_records(path, public, active_project_ids, *, full_enumeration=False):
    """Verify every explicit ordinal record and recompute complete ranking."""
    public = schema.load_spec(public)
    ids = list(active_project_ids)
    indices = schema.active_indices(public, None if full_enumeration else ids)
    _require(ids == [public['projects'][index]['id'] for index in indices], 'B active-project order differs')
    path = Path(path).absolute(); plans = 1 << len(ids)
    _require(path.is_file() and path.stat().st_size == plans * RECORD.size,
             'B records must contain every mask exactly once, without a partial or extra row')
    digest = hashlib.sha256(); chunks = []
    best = second = best_mask = second_mask = None
    best_count = feasible = observed = 0
    with path.open('rb') as stream:
        while observed < plans:
            first = observed; count = min(schema.CHUNK_RECORDS, plans - first)
            block = stream.read(count * RECORD.size)
            _require(len(block) == count * RECORD.size, 'A B record chunk is truncated')
            digest.update(block)
            for ordinal, (mask, flags, *npvs) in enumerate(RECORD.iter_unpack(block), first):
                _require(mask == ordinal and flags & ~7 == 0, 'B records have a missing/repeated mask or unknown status bit')
                for scenario, value in enumerate(npvs):
                    _require((value != schema.NULL_NPV) == bool(flags & (1 << scenario)),
                             'B feasibility flags and null NPV sentinel disagree')
                if flags != 7: continue
                feasible += 1; objective = min(npvs)
                if best is None or objective > best:
                    second, second_mask = best, best_mask
                    best, best_mask, best_count = objective, mask, 1
                elif objective == best:
                    best_count += 1
                    if second != best: second, second_mask = objective, mask
                elif second is None or objective > second:
                    second, second_mask = objective, mask
            observed += count
            chunks.append({'start_mask': first, 'end_mask_exclusive': observed, 'record_count': count,
                'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
        _require(not stream.read(1), 'Extra B records follow complete coverage')
    unique = best_count == 1
    full_mask = sum(1 << index for bit, index in enumerate(indices) if best_mask is not None and best_mask & (1 << bit)) if unique else None
    plan = {project['id']: int(bool(full_mask & (1 << index))) for index, project in enumerate(public['projects'])} if unique else None
    return {'complete_coverage': True, 'plan_count': observed, 'feasible_count': feasible,
        'records_sha256': digest.hexdigest(), 'records_bytes': path.stat().st_size, 'chunks': chunks,
        'unique_best': unique, 'best_count': best_count,
        'best_mask': best_mask, 'best_full_mask': full_mask, 'best_plan': plan,
        'objective_pence': best, 'runnerup_mask': second_mask,
        'runnerup_objective_pence': second, 'gap_pence': best - second if best is not None and second is not None else None,
        'mask_order_does_not_break_economic_ties': True,
        'nonunique_best_mask_is_diagnostic_not_a_selected_plan': True}


def execute_prepared(preparation, *, timeout_seconds=None, allow_full=False):
    """Compile and execute B only; a full production call needs prior authorisation."""
    if isinstance(preparation, (str, Path)):
        path = Path(preparation); preparation = _ref(path / 'preparation.json' if path.is_dir() else path)
    frozen, public = validate_prepared(preparation)
    _require(type(allow_full) is bool and (not frozen['full_enumeration'] or allow_full),
             'Full B enumeration requires a separate explicit allow_full=True opt-in')
    if timeout_seconds is not None:
        _require(type(timeout_seconds) is int and timeout_seconds > 0, 'B execution timeout must be an explicit positive integer')
    directory = Path(preparation['path']).parent / 'execution'; directory.mkdir()
    started = {'kind': 'capital_allocation_scaled_independent_B_execution', 'version': 1,
        'started_at': datetime.now(timezone.utc).isoformat(), 'preparation': preparation,
        'public_spec': frozen['public_spec'], 'spec_sha256': frozen['spec_sha256'],
        'recipe_sha256': frozen['recipe_sha256'], 'active_project_ids': frozen['active_project_ids'],
        'project_count': frozen['project_count'], 'full_enumeration': frozen['full_enumeration'], 'toy_only': frozen['toy_only'],
        'record_format': schema.RECORD_FORMAT, 'record_bytes': schema.RECORD_BYTES,
        'chunk_records': schema.CHUNK_RECORDS, 'null_sentinel': schema.NULL_NPV, 'null_npv': schema.NULL_NPV,
        'LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0}
    _write(directory / 'started.json', started); clock = time.monotonic()
    try:
        compiler = shutil.which('g++')
        _require(compiler is not None, 'A C++17 compiler is required for independent B')
        binary = directory / 'search_b'; temporary = directory / 'temporary'; temporary.mkdir()
        environment = os.environ.copy(); environment['TMPDIR'] = str(temporary)
        command = [compiler, '-std=c++17', '-O3', '-Wall', '-Wextra', str(KERNEL), '-o', str(binary)]
        compilation = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=120)
        (directory / 'compile.stdout').write_text(compilation.stdout); (directory / 'compile.stderr').write_text(compilation.stderr)
        _require(compilation.returncode == 0, 'Independent B compilation failed: ' + compilation.stderr[-2000:])
        _check_recipe(frozen['recipe_sha256'])
        records = directory / 'plans.bin'; run_command = [str(binary), frozen['raw_wire']['path'], str(records)]
        kernel_started = time.monotonic()
        execution = subprocess.run(run_command, capture_output=True, text=True, env=environment, timeout=timeout_seconds)
        kernel_seconds = time.monotonic() - kernel_started
        (directory / 'kernel.stdout').write_text(execution.stdout); (directory / 'kernel.stderr').write_text(execution.stderr)
        _require(execution.returncode == 0, 'Independent B execution failed: ' + execution.stderr[-2000:])
        statistics = json.loads(execution.stdout)
        ranked = scan_records(records, public, frozen['active_project_ids'], full_enumeration=frozen['full_enumeration'])
        _require(statistics['plan_count'] == ranked['plan_count']
            and statistics['feasible_count'] == ranked['feasible_count']
            and statistics['scenario_evaluations'] == 3 * ranked['plan_count']
            and 3 * ranked['plan_count'] <= statistics['scenario_year_evaluations'] <= 60 * ranked['plan_count'],
            'B kernel statistics do not match its explicit complete records')
        _check_recipe(frozen['recipe_sha256'])
        result = {**started, **ranked, 'status': 'completed', 'finished_at': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': time.monotonic() - clock, 'kernel_elapsed_seconds': kernel_seconds,
            'compiler_command': command, 'kernel_command': run_command,
            'kernel_implementation': _ref(KERNEL), 'wrapper_implementation': _ref(__file__),
            'compiled_binary': _ref(binary), 'plans_binary': _ref(records), 'records': _ref(records), 'kernel_statistics': statistics,
            'shared_financial_calculation_helper': False,
            'independent_raw_public_primitives_precompilation': True,
            'second_implementation_complete_record_equality_still_required': True,
            'gold_or_workbook_financial_audit_claimed': False}
    except Exception as error:
        result = {**started, 'status': 'failed', 'finished_at': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': time.monotonic() - clock, 'error_type': type(error).__name__, 'error': str(error)}
        _write(directory / 'receipt.json', result)
        raise
    return _write(directory / 'receipt.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--active-projects', nargs='+'); parser.add_argument('--run', action='store_true')
    parser.add_argument('--allow-full', action='store_true')
    arguments = parser.parse_args()
    preparation = prepare(arguments.spec, arguments.output, active_project_ids=arguments.active_projects)
    print(json.dumps(execute_prepared(preparation, allow_full=arguments.allow_full) if arguments.run else preparation))


if __name__ == '__main__': main()
