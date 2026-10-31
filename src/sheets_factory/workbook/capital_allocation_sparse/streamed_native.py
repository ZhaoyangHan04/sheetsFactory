"""Explicit native integer-prefix verification; no search/financial forward.

All rational public bounds are rounded conservatively here once. The native
program checks the entire ordered partition and projects every leaf. Money
outcomes remain claims until the separate opposite-core supplied-mask check.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from . import bounds, coverage, spec, check_masks

KERNEL = Path(__file__).with_suffix('.cpp')
LIMIT_FIELDS = frozenset(('max_regions', 'max_leaves', 'max_line_bytes', 'max_partition_bytes', 'max_elapsed_seconds'))
PREPARED_KIND = 'prepared_sparse_native_integer_partition_verification'
EXECUTION_KIND = 'sparse_native_integer_partition_projection_execution'
reference = check_masks.reference
checked = check_masks.checked


def _write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def _load(value):
    return json.loads(checked(value).read_text())


def _limits(value):
    spec.require(isinstance(value, dict) and set(value) == LIMIT_FIELDS
                 and all(type(x) is int and 0 < x < 1 << 63 for x in value.values())
                 and value['max_line_bytes'] <= 512 and value['max_elapsed_seconds'] * 1000 < 1 << 63,
                 'Independent bounded region/leaf/line/byte/time caps are required; line cap is at most 512')
    return dict(value)


def _rank(public, value):
    spec.require(type(value) is dict and set(value) == {'mask_hex', 'objective_pence', 'scenario_npvs_pence'}, 'Complete rank claim required')
    spec.plan_from_mask_hex(public, value['mask_hex'])
    npvs = value['scenario_npvs_pence']
    spec.require(type(npvs) is dict and set(npvs) == set(spec.SCENARIO_IDS), 'All rank scenarios required')
    def integer(text):
        spec.require(type(text) is str and text == str(int(text)) and check_masks.NULL_NPV < int(text) < 1 << 63,
                     'Canonical signed64 feasible rank values required')
        return int(text)
    values = [integer(npvs[sid]) for sid in spec.SCENARIO_IDS]
    spec.require(integer(value['objective_pence']) == min(values), 'Rank objective differs')
    return deepcopy(value)


def _envelope(public, branch_order, best, runnerup):
    model = bounds.prepare_bounds(public)
    coverage.describe_prefix(len(public['projects']), '', branch_order=branch_order)
    best, runnerup = _rank(public, best), _rank(public, runnerup)
    spec.require(best['mask_hex'] != runnerup['mask_hex']
                 and int(best['objective_pence']) > int(runnerup['objective_pence']), 'Distinct strictly ranked claims required')
    ceil = lambda f: -((-f.numerator) // f.denominator)
    floor = lambda f: f.numerator // f.denominator
    constants = [ceil(x) for x in model.constants]
    coefficients = [[ceil(model.coefficients[s][j]) for s in range(3)] for j in range(len(model.project_ids))]
    cuts = [{'id': cut.id, 'capacity': ceil(cut.capacity), 'weights': [floor(x) for x in cut.weights]} for cut in model.cuts]
    spec.require(all(abs(constants[s]) + sum(abs(row[s]) for row in coefficients) < 1 << 62 for s in range(3))
                 and all(abs(cut['capacity']) + sum(abs(x) for x in cut['weights']) < 1 << 62 for cut in cuts),
                 'Full integer expression aggregates exceed signed64 safe envelope')
    return {'bound_model': model.binding(), 'branch_project_order': list(branch_order), 'constants': constants,
            'coefficients_by_project': coefficients, 'necessary_cuts': cuts, 'best': best, 'runnerup': runnerup}


def _wire(public, envelope):
    ids = list(spec.project_ids(len(public['projects'])))
    rows = ['CAPITAL_SPARSE_STREAM_INTEGER_V1', str(len(ids)),
            ' '.join(str(ids.index(pid)) for pid in envelope['branch_project_order']),
            ' '.join(map(str, envelope['constants']))]
    rows.extend(' '.join(map(str, row)) for row in envelope['coefficients_by_project'])
    rows.append(str(len(envelope['necessary_cuts'])))
    rows.extend(cut['id'] + ' ' + str(cut['capacity']) + ' ' + ' '.join(map(str, cut['weights'])) for cut in envelope['necessary_cuts'])
    for field in ('best', 'runnerup'):
        rank = envelope[field]
        rows.append(' '.join([rank['mask_hex'], rank['objective_pence'], *[rank['scenario_npvs_pence'][sid] for sid in spec.SCENARIO_IDS]]))
    return '\n'.join(rows) + '\n'


def _recipe():
    return {name: reference(path) for name, path in {'wrapper': __file__, 'native': KERNEL,
        'public_bounds': bounds.__file__, 'public_schema': spec.__file__, 'coverage_schema': coverage.__file__,
        'stream_reference_helper': check_masks.__file__}.items()}


def _claims():
    return {'financial_forward_calls': 0, 'optimizer_runs': 0, 'model_calls': 0, 'LO_calls': 0,
            'all_financial_leaves_independently_checked': False, 'unique_optimum_certified': False,
            'source_quality_or_difficulty_certified': False}


def prepare_inputs(public, directory, *, branch_order, best, runnerup, limits):
    """Freeze public-derived integer envelope only; no compiler or process."""
    public = spec.load_spec(public)
    limits = _limits(limits)
    envelope = _envelope(public, branch_order, best, runnerup)
    directory = Path(directory).absolute()
    spec.require(directory == directory.resolve() and not directory.exists(), 'Fresh real preparation directory required')
    recipe = _recipe()
    directory.mkdir(parents=True)
    _write(directory / 'public.json', public)
    _write(directory / 'integer_envelope.json', envelope)
    with (directory / 'integer_envelope.txt').open('x') as stream:
        stream.write(_wire(public, envelope))
    value = {'kind': PREPARED_KIND, 'version': 1, 'public_spec_sha256': spec.canonical_sha(public),
             'project_count': len(public['projects']), 'public': reference(directory / 'public.json'),
             'integer_envelope': reference(directory / 'integer_envelope.json'),
             'bound_wire': reference(directory / 'integer_envelope.txt'), 'limits': limits,
             'recipe': recipe, 'compiler_runs': 0, **_claims()}
    spec.require(recipe == _recipe(), 'Verification recipe changed during preparation')
    _write(directory / 'preparation.json', value)
    return value


def validate_prepared(preparation):
    if not isinstance(preparation, dict) and Path(preparation).is_dir():
        preparation = Path(preparation) / 'preparation.json'
    value = _load(preparation)
    spec.require(value.get('kind') == PREPARED_KIND and type(value.get('version')) is int and value['version'] == 1
                 and value['recipe'] == _recipe(), 'Prepared native integer verifier recipe differs')
    _limits(value['limits'])
    public = spec.load_spec(checked(value['public']))
    envelope = _load(value['integer_envelope'])
    expected = _envelope(public, envelope['branch_project_order'], envelope['best'], envelope['runnerup'])
    spec.require(envelope == expected and checked(value['bound_wire']).read_text() == _wire(public, envelope)
                 and value['public_spec_sha256'] == spec.canonical_sha(public) and value['project_count'] == len(public['projects']),
                 'Public exact bound envelope differs')
    spec.require(value['compiler_runs'] == 0 and all(type(value.get(k)) is type(v) and value[k] == v for k, v in _claims().items()),
                 'Preparation makes unsupported claims')
    return value, public, envelope


def execute_prepared(preparation, partition):
    """Compile and check all regions; preserve every failed attempt artifact."""
    if not isinstance(preparation, dict) and Path(preparation).is_dir():
        preparation = Path(preparation) / 'preparation.json'
    preparation = reference(checked(preparation))
    frozen, public, envelope = validate_prepared(preparation)
    partition_path = checked(partition)
    spec.require(partition_path.stat().st_size <= frozen['limits']['max_partition_bytes'], 'Partition exceeds byte cap')
    directory = Path(preparation['path']).parent / 'attempts' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    began = time.monotonic_ns()
    def budget():
        spec.require(time.monotonic_ns() - began < frozen['limits']['max_elapsed_seconds'] * 10**9, 'Whole verification execution time cap expired')
    result = {'kind': EXECUTION_KIND, 'version': 1, 'preparation': preparation, 'started_at': datetime.now(timezone.utc).isoformat(),
              'public_spec_sha256': frozen['public_spec_sha256'], 'project_count': len(public['projects']),
              'limits': frozen['limits'], 'recipe': frozen['recipe'], 'complete': False, 'passed': False,
              'status': 'started', **_claims()}
    _write(directory / 'started.json', result)
    result['started'] = reference(directory / 'started.json')
    try:
        budget()
        result['partition'] = reference(partition_path)
        budget()
        compiler = shutil.which('g++')
        spec.require(compiler is not None, 'g++ is required; never installed automatically')
        compiler = str(Path(compiler).resolve())
        version = subprocess.run([compiler, '--version'], capture_output=True, text=True, timeout=10, check=True)
        binary = directory / 'streamed_native'
        command = [compiler, '-O3', '-std=c++17', '-static', str(KERNEL), '-o', str(binary)]
        env = dict(os.environ, TMPDIR=str(directory))
        with (directory / 'compile.stdout').open('xb') as stdout, (directory / 'compile.stderr').open('xb') as stderr:
            done = subprocess.run(command, stdout=stdout, stderr=stderr, env=env, timeout=min(60, frozen['limits']['max_elapsed_seconds']))
        result['compilation'] = {'compiler': reference(compiler), 'version': version.stdout, 'command': command,
            'exit_code': done.returncode, 'stdout': reference(directory / 'compile.stdout'), 'stderr': reference(directory / 'compile.stderr')}
        spec.require(done.returncode == 0, 'Native verifier compilation failed')
        result['compilation']['binary'] = reference(binary)
        budget()
        masks, outcomes, summary = directory / 'masks.u64le', directory / 'claimed_outcomes.bin', directory / 'native_summary.json'
        limits = frozen['limits']
        native = [str(binary), frozen['bound_wire']['path'], str(partition_path), str(masks), str(outcomes), str(summary),
            *[str(limits[name]) for name in ('max_regions', 'max_leaves', 'max_line_bytes', 'max_partition_bytes')],
            str(limits['max_elapsed_seconds'] * 1000)]
        result['native_command'] = native
        remaining = (limits['max_elapsed_seconds'] * 10**9 - (time.monotonic_ns() - began)) / 10**9
        spec.require(remaining > 0, 'Whole verification execution time cap expired')
        with (directory / 'native.stdout').open('xb') as stdout, (directory / 'native.stderr').open('xb') as stderr:
            done = subprocess.run(native, stdout=stdout, stderr=stderr, env=env, timeout=remaining)
        result.update(exit_code=done.returncode, native_stdout=reference(directory / 'native.stdout'), native_stderr=reference(directory / 'native.stderr'))
        for name, path in (('masks', masks), ('claimed_outcomes', outcomes), ('native_summary', summary)):
            if path.exists(): result[name] = reference(path)
        spec.require(reference(partition_path) == result['partition'], 'Partition changed during native verification')
        spec.require(done.returncode == 0, 'Native projection did not complete')
        observed = _load(result['native_summary'])
        result['counts'] = {key: observed[key] for key in ('regions', 'leaves', 'bound', 'infeasible', 'partition_bytes')}
        result['covered_plan_count'] = observed['covered_plan_count']
        result.update(best=envelope['best'], runnerup=envelope['runnerup'], branch_project_order=envelope['branch_project_order'],
                      bound_model=envelope['bound_model'], complete=True, passed=True, status='completed')
        _validate(result)
        budget()
    except Exception as error:
        result.update(complete=False, passed=False, status='incomplete', error_type=type(error).__name__, error=str(error))
        for name in ('masks.u64le', 'claimed_outcomes.bin', 'native_summary.json', 'native.stdout', 'native.stderr'):
            if (directory / name).exists(): result.setdefault('retained_partial_artifacts', {})[name] = reference(directory / name)
    result['elapsed_nanoseconds'] = str(time.monotonic_ns() - began)
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    _write(directory / 'receipt.pending.json', result)
    try:
        if result['complete']: budget()
        (directory / 'receipt.pending.json').rename(directory / 'receipt.json')
        final = reference(directory / 'receipt.json')
        if result['complete']: budget()
        return final
    except Exception as error:
        for name in ('receipt.pending.json', 'receipt.json'):
            if (directory / name).exists(): (directory / name).rename(directory / 'receipt.incomplete_candidate.json')
        result.update(complete=False, passed=False, status='incomplete', error_type=type(error).__name__, error=str(error),
                      elapsed_nanoseconds=str(time.monotonic_ns() - began))
        _write(directory / 'receipt.json', result)
        return reference(directory / 'receipt.json')


def _validate(value):
    spec.require(value.get('kind') == EXECUTION_KIND and type(value.get('version')) is int and value['version'] == 1
                 and value.get('complete') is True and value.get('passed') is True and value.get('status') == 'completed'
                 and value.get('exit_code') == 0, 'Incomplete native projection is not proof evidence')
    frozen, public, envelope = validate_prepared(value['preparation'])
    for name in ('public_spec_sha256', 'project_count', 'limits', 'recipe'):
        spec.require(value[name] == frozen[name], 'Projection identity differs')
    spec.require(all(type(value.get(k)) is type(v) and value[k] == v for k, v in _claims().items()), 'Unsupported projection claim')
    for name in ('best', 'runnerup', 'branch_project_order', 'bound_model'):
        spec.require(value[name] == envelope[name], 'Projection rank/order/bound binding differs')
    started = _load(value['started'])
    spec.require(started.get('status') == 'started' and started.get('complete') is False
                 and all(started[k] == value[k] for k in ('kind', 'version', 'preparation', 'started_at', 'public_spec_sha256', 'project_count', 'limits', 'recipe')),
                 'Immutable before-start record differs')
    for name in ('partition', 'masks', 'claimed_outcomes', 'native_stdout', 'native_stderr'):
        checked(value[name])
    compilation = value['compilation']
    for name in ('compiler', 'binary', 'stdout', 'stderr'): checked(compilation[name])
    spec.require(compilation['exit_code'] == 0 and type(compilation['version']) is str and compilation['version']
                 and compilation['command'] == [compilation['compiler']['path'], '-O3', '-std=c++17', '-static', str(KERNEL), '-o', compilation['binary']['path']], 'Compilation binding differs')
    limits = frozen['limits']
    expected_command = [compilation['binary']['path'], frozen['bound_wire']['path'], value['partition']['path'],
        value['masks']['path'], value['claimed_outcomes']['path'], value['native_summary']['path'],
        *[str(limits[name]) for name in ('max_regions', 'max_leaves', 'max_line_bytes', 'max_partition_bytes')], str(limits['max_elapsed_seconds'] * 1000)]
    spec.require(value['native_command'] == expected_command, 'Native command differs')
    native = _load(value['native_summary'])
    spec.require(native.get('kind') == 'sparse_integer_partition_native_projection' and type(native.get('version')) is int
                 and native['version'] == 1 and native.get('complete') is True and native['stop_reason'] == ''
                 and native['project_count'] == frozen['project_count'] and native['best_leaf_present'] is True
                 and native['runnerup_leaf_present'] is True, 'Native projection did not complete')
    counts = {key: check_masks._count(native[key]) for key in ('regions', 'leaves', 'bound', 'infeasible', 'partition_bytes')}
    spec.require(counts['leaves'] >= 2 and counts['regions'] == counts['leaves'] + counts['bound'] + counts['infeasible']
                 and counts['regions'] <= limits['max_regions'] and counts['leaves'] <= limits['max_leaves']
                 and counts['partition_bytes'] == value['partition']['bytes'] <= limits['max_partition_bytes']
                 and native['covered_plan_count'] == native['complete_plan_count'] == value['covered_plan_count'] == str(1 << frozen['project_count'])
                 and value['counts'] == {key: native[key] for key in counts}
                 and check_masks._count(native['elapsed_nanoseconds']) < limits['max_elapsed_seconds'] * 10**9,
                 'Native counts or caps differ')
    for name, claim in _claims().items():
        if name in native: spec.require(type(native[name]) is type(claim) and native[name] == claim, 'Unsupported native claim')
    check_masks.validate_output(value['claimed_outcomes'], value['masks'], project_count=len(public['projects']), expected_count=counts['leaves'])
    return value


def validate_execution(receipt):
    """Read-only execution/stream identity checks, not financial verification."""
    value = _validate(_load(receipt))
    spec.require(check_masks._count(value['elapsed_nanoseconds']) < value['limits']['max_elapsed_seconds'] * 10**9,
                 'Whole execution exceeded its independent time cap')
    return value
