"""Prepare only by default; explicit execution of independent integer kernel A.

Binary candidate records replace per-year path hashes and CSV. This receipt is
one implementation's result, never a two-implementation admission certificate.
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
import uuid

from . import spec as schema

SOURCE = Path(__file__).with_suffix('.cpp')
RANK_FIELDS = ('feasible_count', 'best_count', 'best_mask', 'objective_pence',
    'runnerup_mask', 'runnerup_objective_pence', 'gap_pence', 'unique_best')


def reference(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def checked(ref):
    path = Path(ref['path'])
    schema.require(reference(path) == ref, 'Frozen artifact changed: ' + str(path))
    return path


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def _fresh(path):
    path = Path(path).absolute()
    schema.require(not path.exists() and not path.is_symlink(), 'Use a fresh immutable output directory')
    path.mkdir(parents=True)
    return path.resolve()


def _environment(output):
    temporary = Path(output) / 'temporary'
    temporary.mkdir(exist_ok=True)
    schema.require(not temporary.is_symlink() and temporary.resolve().is_relative_to(Path(output).resolve()),
                   'Temporary files must stay in the current output directory')
    return {**os.environ, 'TMPDIR': str(temporary.resolve())}


def recipe():
    return [reference(Path(__file__)), reference(Path(schema.__file__)), reference(SOURCE)]


def raw_primitives(public, indices):
    """Serialize raw integers only; no project schedule or financing calculation."""
    lines = ['CAPITAL_SCALED_A_RAW_V1', f'{len(public["projects"])} {len(indices)}', ' '.join(map(str, indices)),
        ' '.join(str(public[k]) for k in ('opening_cash_pence', 'minimum_cash_pence', 'lp_commitment_pence',
            'facility_limit_pence', 'advance_rate_p12', 'tax_rate_p12', 'tax_loss_carry_years')),
        ' '.join(str(public['discount_factors_p12'][str(y)]) for y in schema.YEARS)]
    for p in public['projects']:
        lines.append(' '.join(str(p[k]) for k in ('commission_year', 'sale_year', 'acquisition_cost_pence',
                                                'depreciation_years', 'sale_proceeds_pence')))
        lines.extend(' '.join(str(p[k][str(y)]) for y in schema.YEARS) for k in ('annual_revenue_pence', 'annual_opex_pence'))
    for s in public['scenarios']:
        lines.extend(' '.join(str(s[k][str(y)]) for y in schema.YEARS)
                     for k in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
                               'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12'))
    return '\n'.join(lines) + '\n'


def compile_kernel(output):
    output = _fresh(output)
    compiler = shutil.which('g++')
    schema.require(compiler is not None, 'Kernel compilation requires g++')
    command = [compiler, '-std=c++17', '-O3', '-Wall', '-Wextra', str(SOURCE), '-o', str(output / 'search_a')]
    started = datetime.now(timezone.utc).isoformat()
    with (output / 'stdout.txt').open('x') as stdout, (output / 'stderr.txt').open('x') as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, env=_environment(output), timeout=120)
    receipt = {'kind': 'capital_scaled_A_compilation', 'version': 1, 'started_at': started,
        'completed_at': datetime.now(timezone.utc).isoformat(), 'command': command, 'returncode': result.returncode,
        'implementation': reference(SOURCE), 'stdout': reference(output / 'stdout.txt'), 'stderr': reference(output / 'stderr.txt')}
    if result.returncode == 0:
        receipt['binary'] = reference(output / 'search_a')
    write(output / 'compilation.json', receipt)
    schema.require(result.returncode == 0, 'Compilation failed; original logs and receipt are preserved')
    return reference(output / 'compilation.json')


def inspect_records(path, expected_count):
    """Check every ordinal/status/null encoding and bind all bytes by chunks.

    Global ranking is produced by the frozen A kernel. A second independent
    implementation is still required before any financial-source admission.
    """
    path = Path(path)
    schema.require(path.stat().st_size == expected_count * schema.RECORD_BYTES, 'Incomplete binary candidate record count')
    digest, chunks, seen = hashlib.sha256(), [], 0
    with path.open('rb') as stream:
        while block := stream.read(schema.CHUNK_RECORDS * schema.RECORD_BYTES):
            start = seen
            schema.require(len(block) % schema.RECORD_BYTES == 0, 'Partial candidate record')
            for mask, flags, *values in struct.iter_unpack(schema.RECORD_FORMAT, block):
                schema.require(mask == seen and 0 <= flags <= 7, 'Candidate records must cover exact ordinal masks once')
                schema.require(all((value != schema.NULL_NPV) == bool(flags & (1 << si)) for si, value in enumerate(values)),
                               'Scenario feasibility and absent NPV encoding disagree')
                seen += 1
            digest.update(block)
            chunks.append({'start_mask': start, 'end_mask_exclusive': seen, 'record_count': seen - start,
                           'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
    schema.require(seen == expected_count, 'Missing candidate masks')
    return {'path': str(path.resolve()), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}, chunks


def read_records(path):
    with Path(path).open('rb') as stream:
        while block := stream.read(schema.CHUNK_RECORDS * schema.RECORD_BYTES):
            yield from struct.iter_unpack(schema.RECORD_FORMAT, block)


def enumerate_plans(public_spec, output, *, active_project_ids=None, compilation=None,
                    allow_full=False, timeout_seconds=14400):
    public = schema.load_spec(public_spec)
    indices = schema.active_indices(public, active_project_ids)
    full = len(indices) == len(public['projects'])
    schema.require(not full or allow_full is True, 'Full enumeration needs explicit execution authorization')
    schema.require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 14400, 'Bound the execution guard')
    output = _fresh(output)
    write(output / 'public_spec.json', public)
    (output / 'raw_primitives.txt').write_text(raw_primitives(public, indices))
    started = {'kind': 'capital_scaled_A_execution_attempt', 'version': 1,
        'started_at': datetime.now(timezone.utc).isoformat(), 'public_spec': reference(output / 'public_spec.json'),
        'spec_sha256': schema.canonical_sha(public), 'recipe': recipe(),
        'active_project_ids': [public['projects'][i]['id'] for i in indices],
        'full_enumeration': full, 'toy_only': not full, 'expected_plan_count': 1 << len(indices),
        'LO_calls': 0, 'model_calls': 0, 'qualified': False}
    write(output / 'started.json', started)
    clock = time.monotonic()
    try:
        compilation = compile_kernel(output / 'compilation') if compilation is None else compilation
        compiled = json.loads(checked(compilation).read_text())
        schema.require(compiled['kind'] == 'capital_scaled_A_compilation' and compiled['returncode'] == 0
            and compiled['implementation'] == reference(SOURCE), 'A compiled binary must bind this exact implementation')
        binary = checked(compiled['binary'])
        command = [str(binary), str(output / 'raw_primitives.txt'), str(output / 'candidate_records.bin')]
        with (output / 'stdout.txt').open('x') as stdout, (output / 'stderr.txt').open('x') as stderr:
            process = subprocess.run(command, stdout=stdout, stderr=stderr, env=_environment(output), timeout=timeout_seconds)
        schema.require(process.returncode == 0, 'Kernel A failed; retain its raw artifacts')
        result = json.loads((output / 'stdout.txt').read_text())
        expected = 1 << len(indices)
        schema.require(result['kind'] == 'capital_scaled_kernel_a_result'
            and result['plan_count'] == expected and result['project_count'] == len(public['projects'])
            and result['active_count'] == len(indices) and result['scenario_evaluations'] == expected * 3,
            'Kernel report does not cover the complete declared set')
        records, chunks = inspect_records(output / 'candidate_records.bin', expected)
        best = result['best_mask']
        full_mask = None if best is None or not result['unique_best'] else sum(((best >> bit) & 1) << index for bit, index in enumerate(indices))
        best_plan = None if not result['unique_best'] else {p['id']: (full_mask >> i) & 1 for i, p in enumerate(public['projects'])}
        receipt = {**started, **{k: result[k] for k in RANK_FIELDS},
            'kind': 'capital_scaled_A_complete_enumeration', 'finished_at': datetime.now(timezone.utc).isoformat(),
            'status': 'completed', 'plan_count': expected, 'project_count': len(public['projects']),
            'best_full_mask': full_mask, 'best_plan': best_plan, 'records': records,
            'record_format': schema.RECORD_FORMAT, 'record_bytes': schema.RECORD_BYTES,
            'null_npv': schema.NULL_NPV, 'chunk_records': schema.CHUNK_RECORDS, 'chunks': chunks,
            'raw_primitives': reference(output / 'raw_primitives.txt'), 'compilation': compilation,
            'kernel_result': result, 'stdout': reference(output / 'stdout.txt'), 'stderr': reference(output / 'stderr.txt'),
            'elapsed_seconds': time.monotonic() - clock, 'independent_comparison_completed': False,
            'all_candidate_55field_paths_hashed': False, 'source_admission_certified': False,
            'quality_or_difficulty_certified': False}
        write(output / 'receipt.json', receipt)
        return reference(output / 'receipt.json')
    except BaseException as error:
        write(output / 'failed.json', {**started, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'status': 'failed', 'error_type': type(error).__name__, 'error': str(error),
            'elapsed_seconds': time.monotonic() - clock,
            'retained_files': [reference(p) for p in sorted(output.iterdir()) if p.is_file()]})
        raise


def prepare(public_spec, output):
    public = schema.load_spec(public_spec)
    output = _fresh(output)
    write(output / 'public_spec.json', public)
    write(output / 'prepared.json', {'kind': 'prepared_capital_scaled_A', 'version': 1,
        'public_spec': reference(output / 'public_spec.json'), 'spec_sha256': schema.canonical_sha(public),
        'recipe': recipe(), 'project_count': len(public['projects']), 'enumeration_performed': False,
        'LO_calls': 0, 'model_calls': 0, 'qualified': False})
    return reference(output / 'prepared.json')


def execute_prepared(output):
    output = Path(output).resolve()
    prepared = json.loads((output / 'prepared.json').read_text())
    schema.require(prepared['kind'] == 'prepared_capital_scaled_A' and prepared['recipe'] == recipe(),
                   'The prospective prepared recipe changed')
    public = schema.load_spec(checked(prepared['public_spec']))
    schema.require(schema.canonical_sha(public) == prepared['spec_sha256'], 'The public specification changed')
    schema.require(not (output / 'attempts').exists(), 'Preserve the first actual attempt; do not silently repeat it')
    attempt = output / 'attempts' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12])
    return enumerate_plans(public, attempt, allow_full=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if args.run:
        if args.prepared is None or args.spec is not None or args.output is not None:
            parser.error('Use --prepared DIR --run for explicit complete execution')
        result = execute_prepared(args.prepared)
    else:
        if args.spec is None or args.output is None or args.prepared is not None:
            parser.error('Preparation requires --spec FILE --output NEW_DIR')
        result = prepare(args.spec, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
