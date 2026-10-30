"""Explicit independent C++ enumeration and read-only two-implementation admission.

Importing this module never compiles, enumerates, invokes LibreOffice, or starts a
model.  The C++ program receives raw public primitives.  The separately owned
Python verifier independently expands those same primitives for every plan.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .spec import ANNUAL_FIELDS, PROJECT_IDS, SCENARIO_IDS, YEARS, load_spec

VERSION = 1
METHOD = 'independent_cpp_integer_pence_complete_paths_v1'
CERTIFICATE_KIND = 'capital_allocation_two_implementation_complete_enumeration'
VERIFICATION_KIND = 'capital_allocation_independent_integer_verification'
DIRECTORY = Path(__file__).resolve().parent
CPP = DIRECTORY / 'search.cpp'
HEADER = ['mask', 'full_mask'] + [
    scenario + suffix for scenario in SCENARIO_IDS
    for suffix in ('_feasible', '_npv_pence', '_path_sha256',
                   '_first_violation_year', '_violation_mask')
] + ['feasible', 'objective_pence']
PATH_ENCODING = '20FY(year,ANNUAL_FIELDS,20closingLossVintages)_signed64_little_endian_v1'
RANK_FIELDS = (
    'plan_count', 'scenario_year_evaluations', 'feasible_count', 'best_mask',
    'best_full_mask', 'best_plan', 'objective_pence', 'runnerup_mask',
    'runnerup_objective_pence', 'gap_pence', 'best_count', 'unique_best',
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_spec_sha256(spec):
    """Hash validated JSON primitives independently of public file whitespace."""
    return hashlib.sha256(_canonical(load_spec(spec))).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def reference(path):
    path = Path(path).resolve(strict=True)
    _require(path.is_file(), 'Artifact is not a regular file')
    return {'path': str(path), 'sha256': _sha(path), 'bytes': path.stat().st_size}


def _checked(ref):
    _require(isinstance(ref, dict) and set(ref) == {'path', 'sha256', 'bytes'},
             'Artifact reference requires path, sha256 and bytes')
    _require(isinstance(ref['path'], str) and Path(ref['path']).is_absolute()
             and isinstance(ref['sha256'], str) and re.fullmatch('[0-9a-f]{64}', ref['sha256'])
             and type(ref['bytes']) is int and ref['bytes'] >= 0,
             'Malformed artifact reference')
    path = Path(ref['path'])
    _require(path.is_file() and path.stat().st_size == ref['bytes']
             and _sha(path) == ref['sha256'], 'Artifact content differs: ' + str(path))
    return path


def _json_ref(ref):
    return json.loads(_checked(ref).read_text())


def _write(path, value):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False).encode() + b'\n')
    return reference(path)


def _fresh(directory):
    path = Path(directory).absolute()
    _require(not path.exists() and not path.is_symlink(), 'Output directory must be fresh')
    # All host/compiler temporary files for this task stay on the data volume.
    _require(path.resolve().is_relative_to(Path('/data')), 'Output must be on the /data volume')
    for ancestor in (path, *path.parents):
        _require(not ancestor.is_symlink(), 'Output path contains a symbolic link')
    path.mkdir(parents=True, exist_ok=False)
    return path.resolve()


def _active(value):
    active = list(PROJECT_IDS) if value is None else list(value)
    _require(active and all(type(p) is str and p in PROJECT_IDS for p in active)
             and active == [p for p in PROJECT_IDS if p in active],
             'Active project IDs must be unique and retain public order')
    return active


def _wire(spec, active):
    """Serialize raw integers only; do not perform financial calculations here."""
    tokens = [18, 3, 20, len(active), *[PROJECT_IDS.index(p) for p in active]]
    tokens.extend(spec[key] for key in (
        'opening_cash_pence', 'minimum_cash_pence', 'lp_commitment_pence',
        'facility_limit_pence', 'advance_rate_p12', 'tax_rate_p12', 'tax_loss_carry_years'))
    tokens.extend(spec['discount_factors_p12'][str(year)] for year in YEARS)
    for project in spec['projects']:
        tokens.extend((project['commission_year'] - YEARS[0], project['sale_year'] - YEARS[0],
                       project['acquisition_cost_pence'], project['depreciation_years'],
                       project['sale_proceeds_pence']))
        for field in ('annual_revenue_pence', 'annual_opex_pence'):
            tokens.extend(project[field][str(year)] for year in YEARS)
    for scenario in spec['scenarios']:
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
                      'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12'):
            tokens.extend(scenario[field][str(year)] for year in YEARS)
    return ('CAPITAL_ALLOCATION_RAW_V1\n' + '\n'.join(map(str, tokens)) + '\n').encode()


def compile_search(directory):
    """Compile only this independent C++ implementation; never evaluate a plan."""
    output = _fresh(directory)
    temporary = output / 'temporary'
    temporary.mkdir()
    implementation = reference(CPP)
    snapshot = output / 'search.cpp'
    snapshot.write_bytes(CPP.read_bytes())
    binary = output / 'capital_allocation_search'
    command = ['/usr/bin/g++', '-std=c++17', '-O2', '-Wall', '-Wextra',
               '-Werror', str(snapshot), '-o', str(binary)]
    environment = dict(os.environ)
    environment['TMPDIR'] = str(temporary)
    result = subprocess.run(command, cwd=output, env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    (output / 'compiler.stdout').write_bytes(result.stdout)
    (output / 'compiler.stderr').write_bytes(result.stderr)
    _require(result.returncode == 0, 'Independent C++ compilation failed; inspect compiler.stderr')
    _checked(implementation)
    _require(reference(snapshot)['sha256'] == implementation['sha256'],
             'C++ implementation changed during compilation')
    return _write(output / 'compilation.json', {
        'kind': 'capital_allocation_cpp_compilation', 'version': VERSION,
        'implementation': implementation, 'snapshot': reference(snapshot),
        'binary': reference(binary), 'command': command,
        'stdout': reference(output / 'compiler.stdout'),
        'stderr': reference(output / 'compiler.stderr'),
        'temporary_directory': str(temporary), 'external_financial_calls': 0,
    })


def _compilation(ref):
    data = _json_ref(ref)
    _require(data['kind'] == 'capital_allocation_cpp_compilation'
             and type(data['version']) is int and data['version'] == VERSION,
             'Unsupported compilation receipt')
    _require(data['implementation'] == reference(CPP), 'C++ implementation binding changed')
    _require(_checked(data['snapshot']).read_bytes() == CPP.read_bytes(), 'C++ snapshot differs')
    _checked(data['stdout']); _checked(data['stderr'])
    return _checked(data['binary'])


def _integer(text, label, *, nullable=False):
    if nullable and text == '':
        return None
    _require(isinstance(text, str) and re.fullmatch(r'0|-?[1-9][0-9]*', text) is not None,
             'Noncanonical integer in ' + label)
    return int(text)


def _plan(full_mask):
    return {project: (full_mask >> bit) & 1 for bit, project in enumerate(PROJECT_IDS)}


def inspect_plans(plans_csv, *, active_project_ids=None):
    """Stream the entire retained CSV and check dimensions, objectives and rank.

    This checks the proof's coverage and ranking.  It is deliberately not the
    independent financial interpreter; verify.py performs that second execution.
    """
    active = _active(active_project_ids)
    count = 1 << len(active)
    best = runner = None
    feasible_count = best_count = seen = 0
    path = Path(plans_csv)
    with path.open(newline='') as stream:
        reader = csv.reader(stream)
        _require(next(reader, None) == HEADER, 'Complete enumeration CSV header differs')
        for mask, values in enumerate(reader):
            _require(mask < count and len(values) == len(HEADER), 'Extra or malformed enumeration row')
            full_mask = sum(((mask >> bit) & 1) << PROJECT_IDS.index(p) for bit, p in enumerate(active))
            _require(_integer(values[0], 'mask') == mask
                     and _integer(values[1], 'full_mask') == full_mask,
                     'Enumeration masks are missing, reordered or inconsistent')
            scenario_npvs = []
            for c in range(3):
                offset = 2 + c * 5
                feasible = _integer(values[offset], 'scenario feasible')
                npv = _integer(values[offset + 1], 'scenario NPV', nullable=True)
                _require(feasible in (0, 1) and bool(feasible) == (npv is not None),
                         'Infeasible scenarios must have no NPV')
                _require(re.fullmatch('[0-9a-f]{64}', values[offset + 2]) is not None,
                         'Missing complete scenario path hash')
                first = _integer(values[offset + 3], 'first violation', nullable=True)
                violations = _integer(values[offset + 4], 'violation mask')
                _require(0 <= violations <= 15 and (violations == 0) == bool(feasible)
                         and ((first is None) == bool(feasible))
                         and (first is None or first in YEARS)
                         and (violations & 1 or first in (None, YEARS[-1])),
                         'Scenario violation evidence is inconsistent')
                scenario_npvs.append(npv)
            feasible = _integer(values[-2], 'plan feasible')
            objective = _integer(values[-1], 'objective', nullable=True)
            expected_feasible = all(value is not None for value in scenario_npvs)
            _require(feasible in (0, 1) and bool(feasible) == expected_feasible
                     and objective == (min(scenario_npvs) if expected_feasible else None),
                     'Plan objective must be the feasible maximin LP value')
            if feasible:
                feasible_count += 1
                candidate = (objective, mask, full_mask)
                if best is None or objective > best[0]:
                    runner, best, best_count = best, candidate, 1
                else:
                    if objective == best[0]:
                        best_count += 1
                    if runner is None or objective > runner[0]:
                        runner = candidate
            seen += 1
    _require(seen == count, 'Complete enumeration row count differs')
    # Enforce the shared byte-level format as well as its CSV semantics.
    with path.open('rb') as stream:
        tail = b''
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            _require(b'\r' not in block, 'Enumeration CSV must use Unix newlines')
            tail = block[-1:]
        _require(tail == b'\n', 'Enumeration CSV must have its final newline')
    return {
        'plan_count': count, 'scenario_year_evaluations': count * 3 * 20,
        'feasible_count': feasible_count,
        'best_mask': None if best is None else best[1],
        'best_full_mask': None if best is None else best[2],
        'best_plan': _plan(best[2]) if best_count == 1 else None,
        'objective_pence': None if best is None else best[0],
        'runnerup_mask': None if runner is None else runner[1],
        'runnerup_objective_pence': None if runner is None else runner[0],
        'gap_pence': None if runner is None else best[0] - runner[0],
        'best_count': best_count, 'unique_best': best_count == 1,
    }


def enumerate_cpp(spec, output_directory, *, active_project_ids=None, compilation=None):
    """Execute explicit C++ enumeration, retaining every candidate's full paths.

    A project subset is a labelled toy experiment.  It cannot support a production
    source.  All scenarios and all twenty years still execute for every toy mask.
    """
    primitives = load_spec(spec)
    active = _active(active_project_ids)
    recipe = {name: reference(path) for name, path in (
        ('implementation', CPP), ('wrapper_implementation', Path(__file__)),
        ('schema_implementation', DIRECTORY / 'spec.py'))}
    original_public = reference(spec) if isinstance(spec, (str, Path)) else None
    output = _fresh(output_directory)
    public = output / 'public_spec.json'
    public.write_bytes(_canonical(primitives) + b'\n')
    raw = output / 'raw_primitives.txt'
    raw.write_bytes(_wire(primitives, active))
    if compilation is None:
        compilation = compile_search(output / 'compilation')
    binary = _compilation(compilation)
    plans = output / 'all_plans.csv'
    started = datetime.now(timezone.utc).isoformat()
    # The executable uses bounded memory; no forward ledger or best-plan hint is supplied.
    result = subprocess.run([str(binary), str(raw), str(plans)], cwd=output,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output / 'search.stdout').write_bytes(result.stdout)
    (output / 'search.stderr').write_bytes(result.stderr)
    execution = _write(output / 'execution.json', {
        'kind': 'capital_allocation_cpp_execution', 'version': VERSION,
        'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'command': [str(binary), str(raw), str(plans)], 'returncode': result.returncode,
        'binary': reference(binary), 'raw_primitives': reference(raw),
        'stdout': reference(output / 'search.stdout'), 'stderr': reference(output / 'search.stderr'),
        'complete_enumeration_claimed': result.returncode == 0,
    })
    _require(result.returncode == 0, 'Independent enumeration failed; inspect search.stderr')
    summary = json.loads(result.stdout)
    _require(summary.pop('method') == METHOD, 'Unexpected C++ enumeration method')
    ranking = inspect_plans(plans, active_project_ids=active)
    _require(_canonical(summary) == _canonical({key: value for key, value in ranking.items() if key != 'best_plan'}),
             'C++ summary differs from the complete retained enumeration')
    for ref in recipe.values():
        _checked(ref)
    if original_public is not None:
        _checked(original_public)
    return _write(output / 'cpp_enumeration.json', {
        'kind': 'capital_allocation_cpp_complete_enumeration', 'version': VERSION,
        'method': METHOD, 'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'public_spec': reference(public), 'spec_sha256': hashlib.sha256(_canonical(primitives)).hexdigest(),
        'original_public_spec': original_public,
        'active_project_ids': active, 'full_enumeration': active == list(PROJECT_IDS),
        'toy_only': active != list(PROJECT_IDS), 'path_encoding': PATH_ENCODING,
        'annual_fields': list(ANNUAL_FIELDS), 'closing_loss_years': list(YEARS),
        'raw_primitives': reference(raw), 'compilation': compilation, 'execution': execution,
        **recipe,
        'plans_csv': reference(plans), 'stdout': reference(output / 'search.stdout'),
        'stderr': reference(output / 'search.stderr'), **ranking,
        'external_financial_calls': 0, 'model_calls': 0,
        'quality_or_difficulty_certified': False,
    })


def enumerate_capital_plans(spec, output_directory, *, active_project_ids=None):
    """Run both independent integer implementations and retain a bound certificate.

    This function explicitly performs the requested enumeration.  It does not
    create a source or invoke workbook engines, controls, quality checks or models.
    A certificate may truthfully record a non-unique result; admission rejects it.
    """
    cpp_ref = enumerate_cpp(spec, output_directory, active_project_ids=active_project_ids)
    cpp = _json_ref(cpp_ref)
    from .verify import verify_search
    verification = verify_search(spec, cpp['plans_csv']['path'],
                                 Path(output_directory) / 'independent_verification',
                                 active_project_ids=cpp['active_project_ids'])
    verified = _json_ref(verification)
    _require(cpp['wrapper_implementation'] == reference(__file__)
             and cpp['implementation'] == reference(CPP)
             and cpp['schema_implementation'] == reference(DIRECTORY / 'spec.py'),
             'Search recipe changed while independent verification was running')
    _checked(cpp['public_spec'])
    if cpp['original_public_spec'] is not None:
        _checked(cpp['original_public_spec'])
    certificate = {
        'kind': CERTIFICATE_KIND, 'version': VERSION,
        'methods': [METHOD, 'independent_python_raw_spec_integer_pence_v1'],
        'public_spec': cpp['public_spec'], 'spec_sha256': cpp['spec_sha256'],
        'active_project_ids': cpp['active_project_ids'],
        'full_enumeration': cpp['full_enumeration'], 'toy_only': cpp['toy_only'],
        'cpp_enumeration': cpp_ref, 'verification': verification,
        'plans_csv': cpp['plans_csv'], 'python_plans': verified['python_plans'],
        'cpp_implementation': cpp['implementation'],
        'search_implementation': reference(__file__),
        'verifier_implementation': verified['implementation'],
        'schema_implementation': reference(DIRECTORY / 'spec.py'),
        'path_encoding': PATH_ENCODING,
        **{key: cpp[key] for key in RANK_FIELDS},
        'passed': verified.get('passed') is True,
        'quality_or_difficulty_certified': False,
        'workbook_financial_audit_claimed': False,
        'admissible': (cpp['full_enumeration'] and cpp['unique_best']
                       and cpp['gap_pence'] is not None and cpp['gap_pence'] >= 1
                       and verified.get('passed') is True),
    }
    return _write(Path(output_directory) / 'certificate.json', certificate)


def validate_certificate(certificate, spec, *, require_full=True):
    """Read and validate both complete proofs without running either evaluator.

    Production always uses the default.  ``require_full=False`` permits a toy
    certificate to be checked in tests, while retaining its explicit toy labels.
    Unique best and a finite next-plan gap of at least one penny remain required.
    """
    _require(type(require_full) is bool, 'require_full must be Boolean')
    if isinstance(certificate, (str, Path)):
        certificate = reference(certificate)
    data = _json_ref(certificate)
    _require(data.get('kind') == CERTIFICATE_KIND and type(data.get('version')) is int
             and data['version'] == VERSION and data.get('passed') is True,
             'Unsupported or incomplete enumeration certificate')
    primitives = load_spec(spec)
    digest = hashlib.sha256(_canonical(primitives)).hexdigest()
    _require(data['spec_sha256'] == digest and load_spec(_checked(data['public_spec'])) == primitives,
             'Certificate is for different public primitives')
    active = _active(data['active_project_ids'])
    full = active == list(PROJECT_IDS)
    _require(data['full_enumeration'] is full and data['toy_only'] is (not full),
             'False full-enumeration or toy declaration')
    _require(not require_full or full, 'A toy subset cannot certify an eighteen-project source')
    _require(data['methods'] == [METHOD, 'independent_python_raw_spec_integer_pence_v1']
             and data['path_encoding'] == PATH_ENCODING
             and data['quality_or_difficulty_certified'] is False
             and data['workbook_financial_audit_claimed'] is False,
             'Unsupported enumeration methods or claims')
    for field, path in (('cpp_implementation', CPP), ('search_implementation', Path(__file__)),
                        ('verifier_implementation', DIRECTORY / 'verify.py'),
                        ('schema_implementation', DIRECTORY / 'spec.py')):
        _require(data[field] == reference(path), 'Enumeration implementation binding changed: ' + field)
    cpp = _json_ref(data['cpp_enumeration'])
    _require(cpp['kind'] == 'capital_allocation_cpp_complete_enumeration'
             and type(cpp['version']) is int and cpp['version'] == VERSION and cpp['method'] == METHOD
             and cpp['spec_sha256'] == digest and cpp['active_project_ids'] == active
             and cpp['public_spec'] == data['public_spec']
             and cpp['implementation'] == data['cpp_implementation']
             and cpp['wrapper_implementation'] == data['search_implementation']
             and cpp['schema_implementation'] == data['schema_implementation']
             and cpp['plans_csv'] == data['plans_csv']
             and cpp['full_enumeration'] is full and cpp['toy_only'] is (not full)
             and cpp['path_encoding'] == PATH_ENCODING
             and cpp['annual_fields'] == list(ANNUAL_FIELDS)
             and cpp['closing_loss_years'] == list(YEARS)
             and cpp['quality_or_difficulty_certified'] is False
             and cpp['external_financial_calls'] == 0 and type(cpp['external_financial_calls']) is int
             and cpp['model_calls'] == 0 and type(cpp['model_calls']) is int,
             'C++ enumeration evidence does not match the certificate')
    if cpp['original_public_spec'] is not None:
        _require(load_spec(_checked(cpp['original_public_spec'])) == primitives,
                 'Original public specification differs')
    _require(_checked(cpp['raw_primitives']).read_bytes() == _wire(primitives, active),
             'C++ raw primitive input differs from the public specification')
    binary = _compilation(cpp['compilation'])
    execution = _json_ref(cpp['execution'])
    _require(execution['kind'] == 'capital_allocation_cpp_execution'
             and type(execution['version']) is int and execution['version'] == VERSION
             and execution['returncode'] == 0 and type(execution['returncode']) is int
             and execution['complete_enumeration_claimed'] is True
             and execution['binary'] == reference(binary)
             and execution['raw_primitives'] == cpp['raw_primitives']
             and execution['stdout'] == cpp['stdout'] and execution['stderr'] == cpp['stderr']
             and execution['command'] == [str(binary), cpp['raw_primitives']['path'], data['plans_csv']['path']],
             'C++ completed execution chain differs')
    summary = json.loads(_checked(cpp['stdout']).read_text())
    _checked(cpp['stderr'])
    _require(summary.pop('method') == METHOD, 'C++ output method differs')
    ranking = inspect_plans(_checked(data['plans_csv']), active_project_ids=active)
    _require(_canonical(summary) == _canonical({key: value for key, value in ranking.items() if key != 'best_plan'}),
             'C++ execution summary differs from complete CSV')
    verification = _json_ref(data['verification'])
    _require(verification['kind'] == VERIFICATION_KIND and type(verification['version']) is int
             and verification['version'] == VERSION and verification['passed'] is True
             and verification['spec_sha256'] == digest
             and verification['active_project_ids'] == active
             and verification['full_enumeration'] is full and verification['toy_only'] is (not full)
             and verification['cpp_plans'] == data['plans_csv']
             and verification['python_plans'] == data['python_plans']
             and verification['implementation'] == data['verifier_implementation']
             and verification['schema_implementation'] == data['schema_implementation']
             and verification['expected_plan_count'] == (1 << len(active))
             and verification['all_scenario_year_states_checked'] is True
             and verification['shared_financial_calculation_helper'] is False
             and verification['LO_calls'] == 0 and type(verification['LO_calls']) is int
             and verification['model_calls'] == 0 and type(verification['model_calls']) is int
             and verification['qualified'] is False
             and verification['task_count'] == 0 and type(verification['task_count']) is int
             and verification['error'] is None,
             'Independent interpreter evidence is incomplete or bound to a different enumeration')
    _require(load_spec(_checked(verification['public_spec'])) == primitives,
             'Independent interpreter public primitives differ')
    python_plans = _checked(data['python_plans'])
    _require(reference(python_plans)['sha256'] == data['plans_csv']['sha256']
             and python_plans.stat().st_size == data['plans_csv']['bytes'],
             'Independent complete paths differ from C++ paths')
    for key in RANK_FIELDS:
        _require(data[key] == ranking[key] and type(data[key]) is type(ranking[key])
                 and cpp[key] == ranking[key] and type(cpp[key]) is type(ranking[key])
                 and verification[key] == ranking[key] and type(verification[key]) is type(ranking[key]),
                 'Complete enumeration ranking differs: ' + key)
    for proof in (data, cpp, verification):
        chosen = proof['best_plan']
        _require(chosen is None or (isinstance(chosen, dict) and set(chosen) == set(PROJECT_IDS)
                 and all(type(value) is int and value in (0, 1) for value in chosen.values())),
                 'Best plan requires eighteen literal integer binary choices')
    _require(ranking['unique_best'] is True and ranking['best_count'] == 1
             and type(ranking['gap_pence']) is int and ranking['gap_pence'] >= 1,
             'Source requires a unique best plan and a finite gap of at least one penny')
    _require(data['admissible'] is full,
             'Certificate admission declaration differs from its proven scope')
    _require(verification['source_admissible_unique_optimum'] is full,
             'Independent verification admission declaration differs')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--active-projects', nargs='+', help='Explicit toy-only subset in public order')
    args = parser.parse_args(argv)
    print(json.dumps(enumerate_capital_plans(args.spec, args.output,
                                           active_project_ids=args.active_projects)))


if __name__ == '__main__':
    main()
