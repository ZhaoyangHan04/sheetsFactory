#!/usr/bin/env python3
"""Freeze the first declared scaled source; --prepared --run builds it.

Preparation verifies the already completed independent searches. It neither
enumerates plans nor emits a workbook. Gold remains private and is not a task.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import openpyxl
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.capital_allocation_scaled import catalog, excel, ledger, search_a, search_b, spec, validate
from sheets_factory.workbook.capital_allocation import excel as original_excel, ledger as original_ledger, spec as original_spec
from sheets_factory.workbook import resource_engine
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine, load_runtime_profile
from sheets_factory.task_adapters.lease_family import compare_exact_typed

KIND = 'prepared_first_scaled_capital_financial_source'
PROFILE_ID = '30-D01'
COUNT = 1 << 30
RECORD_BYTES = COUNT * spec.RECORD_BYTES
FORMULAS = 77513
DEFAULT_RUNTIME = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
CATALOG_SHA256 = '10e566ab80ba8e862f52a474b2a4276524c40d7995a8b364f664f03fc109940c'
DRIVER_SHA256 = 'd160221feba1699dcecf56d19ee8a15730a8d64234ea0e89a3569b824d6f061e'
RANK_FIELDS = ('feasible_count', 'best_count', 'best_mask', 'objective_pence', 'runnerup_mask',
               'runnerup_objective_pence', 'gap_pence', 'unique_best', 'best_full_mask', 'best_plan')
PUBLIC_ARTIFACTS = ('spec', 'public_summary', 'candidate_contract', 'candidate_contract_markdown')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'An artifact must be a regular file without symlink components')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate evidence JSON key')
        result[key] = value
    return result


class Evidence:
    """Hash a referenced artifact once per validation; never load binaries as JSON."""
    def __init__(self):
        self.checked = {}

    def check(self, record):
        require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}, 'A complete artifact reference is required')
        path = record['path']
        if path in self.checked:
            require(self.checked[path] == record, 'Conflicting evidence references')
        else:
            require(reference(path) == record, 'A bound artifact changed: ' + str(path))
            self.checked[path] = dict(record)
        return Path(path)

    def read(self, record):
        value = json.loads(self.check(record).read_text(), object_pairs_hook=_unique)
        require(isinstance(value, dict), 'A JSON evidence object is required')
        return value

    def graph(self, value):
        if isinstance(value, dict):
            if set(value) == {'path', 'sha256', 'bytes'}:
                self.check(value)
            else:
                for child in value.values():
                    self.graph(child)
        elif isinstance(value, list):
            for child in value:
                self.graph(child)


def recipes():
    paths = [Path(__file__).resolve(), Path(resource_engine.__file__).with_name('engine.py'),
        Path(resource_engine.__file__).with_name('uno_recalculate.py'), Path(resource_engine.__file__),
        ROOT / 'src/sheets_factory/core/audit.py', ROOT / 'src/sheets_factory/dashboard/server.py',
        ROOT / 'src/sheets_factory/resume.py', ROOT / 'src/sheets_factory/task_adapters/lease_family.py']
    paths += [Path(module.__file__).resolve() for module in (catalog, excel, ledger, spec, search_a, search_b, validate,
                                                           original_excel, original_ledger, original_spec)]
    paths += [Path(search_a.SOURCE), Path(search_b.KERNEL), catalog.DEFAULT_CATALOG,
              ROOT / 'scripts/prepare_capital_allocation_scaled_specs.py']
    return {str(path): reference(path)['sha256'] for path in paths}


def _catalog_context(specification, catalog_manifest, evidence):
    specification, catalog_manifest = reference(specification), reference(catalog_manifest)
    require(catalog_manifest['sha256'] == CATALOG_SHA256, 'Use the prospectively frozen complete thirteen-profile catalog')
    manifest = evidence.read(catalog_manifest)
    require(manifest.get('kind') == 'generated_scaled_capital_allocation_public_specs'
        and type(manifest.get('version')) is int and manifest['version'] == 1
        and manifest.get('status') == 'completed_public_primitives_only'
        and manifest.get('prospective_first_strong_profile') == PROFILE_ID
        and manifest.get('profile_order') == list(catalog.PROFILE_ORDER)
        and manifest.get('requested_profiles') == list(catalog.PROFILE_ORDER)
        and manifest.get('generated_count') == 13 and manifest.get('failure') is None
        and manifest.get('selection_uses_model_outcomes') is False,
        'The entire prospective catalog and its first development role must remain frozen')
    config = catalog.load_catalog(evidence.check(manifest['catalog']))
    rows = manifest.get('specifications', [])
    require([row.get('profile_id') for row in rows] == list(catalog.PROFILE_ORDER), 'A catalog profile is missing, reordered or duplicated')
    row = next(row for row in rows if row['profile_id'] == PROFILE_ID)
    require(row['spec'] == specification, 'Only the declared first development source may be built')
    public = spec.load_spec(evidence.read(specification))
    require(len(public['projects']) == 30 and public == catalog.build_spec(PROFILE_ID, config), 'The raw thirty-project public specification differs')
    require(evidence.read(row['public_summary']) == catalog.describe_profile(PROFILE_ID, config)
        and evidence.read(row['candidate_contract']) == catalog.public_contract(PROFILE_ID, config)
        and evidence.check(row['candidate_contract_markdown']).read_text()
            == catalog.contract_markdown(catalog.public_contract(PROFILE_ID, config)),
        'The complete public candidate, Annual, vintage or Summary dictionary differs')
    inventory = evidence.read(manifest['prospective_inventory'])
    require(inventory.get('profile_order') == list(catalog.PROFILE_ORDER)
        and [item.get('profile_id') for item in inventory.get('profiles', [])] == list(catalog.PROFILE_ORDER)
        and inventory.get('selection_uses_model_outcomes') is False,
        'The complete prospective inventory differs')
    for item, source in zip(inventory['profiles'], rows):
        candidate = spec.load_spec(evidence.read(source['spec']))
        require(item['spec_sha256'] == spec.canonical_sha(candidate), 'A prospective public specification changed')
    evidence.graph(manifest)
    evidence.graph(inventory)
    return public, specification, catalog_manifest, manifest, {name: row[name] for name in PUBLIC_ARTIFACTS}


def stream_records(record, chunks, expected_count=COUNT, progress=None):
    """Re-hash every byte and every complete chunk, not a sample or summary.

Ordinal/status validation and complete ranking are the two SHA-bound wrappers'
already completed scans. This read does not run a third financial enumeration.
The expected_count argument is used for tiny protocol unit tests only.
"""
    path = Path(record['path']).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'The complete record stream is not a regular file')
    before = path.stat()
    require(type(record['bytes']) is int and record['bytes'] == before.st_size == expected_count * spec.RECORD_BYTES,
        'The complete record stream is truncated or has extra bytes')
    require(isinstance(chunks, list) and len(chunks) == (expected_count + spec.CHUNK_RECORDS - 1) // spec.CHUNK_RECORDS,
        'Every complete binary chunk must be recorded')
    digest, seen = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in chunks:
            count = min(spec.CHUNK_RECORDS, expected_count - seen)
            block = stream.read(count * spec.RECORD_BYTES)
            require(chunk == {'start_mask': seen, 'end_mask_exclusive': seen + count, 'record_count': count,
                             'bytes': count * spec.RECORD_BYTES, 'sha256': hashlib.sha256(block).hexdigest()}
                    and len(block) == count * spec.RECORD_BYTES, 'A complete binary chunk changed or coverage is not contiguous')
            digest.update(block)
            seen += count
            if progress is not None:
                progress(path, seen * spec.RECORD_BYTES, before.st_size)
        require(not stream.read(1), 'Extra binary records follow the complete coverage')
    after = path.stat()
    require(seen == expected_count and digest.hexdigest() == record['sha256']
        and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'The complete binary stream changed during validation')
    return dict(record)


def _rank_fields(result, public):
    for key in RANK_FIELDS:
        require(key in result, 'An optimum rank field is missing')
    integer_fields = set(RANK_FIELDS) - {'unique_best', 'best_plan'}
    require(all(type(result[key]) is int for key in integer_fields)
        and 2 <= result['feasible_count'] <= COUNT and result['best_count'] == 1
        and result['unique_best'] is True and result['gap_pence'] >= 1
        and 0 <= result['best_mask'] < COUNT and 0 <= result['runnerup_mask'] < COUNT
        and result['runnerup_mask'] != result['best_mask'] == result['best_full_mask']
        and result['gap_pence'] == result['objective_pence'] - result['runnerup_objective_pence'],
        'A unique non-toy best and distinct runner-up with a real one-penny gap are required')
    plan = ledger.validate_plan(public, result['best_plan'])
    require(plan == {project['id']: (result['best_mask'] >> index) & 1 for index, project in enumerate(public['projects'])},
        'The complete common plan does not match its ordinal mask')
    return {key: result[key] for key in RANK_FIELDS}


def _dual_recipe(started, terminal, proof_path, evidence):
    driver = Path(proof_path).parent / 'run_dual.py'
    require(reference(driver)['sha256'] == DRIVER_SHA256, 'The actual dual-search driver changed')
    paths = [driver, Path(search_a.__file__), Path(search_a.SOURCE), Path(search_b.__file__), Path(search_b.KERNEL),
             Path(spec.__file__), Path(ledger.__file__), Path(original_ledger.__file__), Path(catalog.__file__), Path(original_spec.__file__)]
    expected = {str(path.resolve()): reference(path) for path in paths}
    require(started.get('recipe') == terminal.get('recipe') == expected, 'The complete dual search financial code or driver recipe differs')
    evidence.graph(expected)


def _selected_record(path, mask):
    with Path(path).open('rb') as stream:
        stream.seek(mask * spec.RECORD_BYTES)
        raw = stream.read(spec.RECORD_BYTES)
    require(len(raw) == spec.RECORD_BYTES, 'A selected complete record is missing')
    ordinal, flags, *npvs = struct.unpack(spec.RECORD_FORMAT, raw)
    require(ordinal == mask and flags & ~7 == 0 and all(
        (value != spec.NULL_NPV) == bool(flags & (1 << index)) for index, value in enumerate(npvs)),
        'The selected record has invalid ordinal/status/null encoding')
    return flags, npvs


def validate_dual_proof(public, specification, catalog_manifest, artifacts, proof_ref, progress=None):
    """Bind the two complete actual independent kernels and selected-plan checks."""
    # A stable proof artifact set must not depend on its caller's local copies
    # or preparation manifest, which do not exist during the first validation.
    evidence = Evidence()
    terminal = evidence.read(proof_ref)
    require(terminal.get('kind') == 'complete_scaled_capital_dual_search'
        and type(terminal.get('version')) is int and terminal['version'] == 1
        and terminal.get('status') == 'completed' and terminal.get('passed') is True
        and terminal.get('records_equal_complete') is True and terminal.get('full_enumeration') is True
        and terminal.get('toy_only') is False and terminal.get('count') == terminal.get('plan_count') == COUNT
        and terminal.get('scenario_evaluations_per_kernel') == COUNT * 3,
        'Both actual complete thirty-decision searches must be terminal and successful')
    require(terminal.get('public_specification') == specification and terminal.get('catalog_manifest') == catalog_manifest
        and terminal.get('public_contract_artifacts') == artifacts,
        'The dual proof belongs to another public specification or prospective catalog')
    started = evidence.read(terminal['started'])
    require(started.get('kind') == 'frozen_first_30_D01_dual_search_attempt'
        and started.get('profile_id') == started.get('first_development_profile') == PROFILE_ID
        and started.get('public_specification') == specification and started.get('catalog_manifest') == catalog_manifest
        and started.get('public_contract_artifacts') == artifacts
        and started.get('canonical_spec_sha256') == spec.canonical_sha(public)
        and started.get('plan_count_per_kernel') == COUNT and started.get('record_bytes_per_kernel') == RECORD_BYTES
        and started.get('confirmation_profiles_not_enumerated') == list(catalog.CONFIRMATION_ORDER),
        'The search was not frozen prospectively for exactly the first development profile')
    _dual_recipe(started, terminal, proof_ref['path'], evidence)
    a, b = evidence.read(terminal['kernel_A_result']), evidence.read(terminal['kernel_B_result'])
    require(a.get('kind') == 'capital_scaled_A_complete_enumeration'
        and b.get('kind') == 'capital_allocation_scaled_independent_B_execution', 'Two distinct known independent kernels are required')
    rank = _rank_fields(terminal, public)
    for result in (a, b):
        require(result.get('status') == 'completed' and result.get('plan_count') == COUNT
            and result.get('project_count') == 30 and result.get('full_enumeration') is True
            and result.get('toy_only') is False and result.get('active_project_ids') == list(spec.project_ids(30))
            and result.get('spec_sha256') == spec.canonical_sha(public)
            and (result.get('record_format'), result.get('record_bytes'), result.get('chunk_records'), result.get('null_npv'))
                == (spec.RECORD_FORMAT, spec.RECORD_BYTES, spec.CHUNK_RECORDS, spec.NULL_NPV)
            and _rank_fields(result, public) == rank
            and spec.load_spec(evidence.read(result['public_spec'])) == public,
            'An independent result is partial, toy, tied or bound to another specification')
    require(a.get('recipe') == search_a.recipe() and b.get('recipe_sha256') == search_b._recipe()
        and b.get('kernel_implementation') == reference(search_b.KERNEL)
        and b.get('wrapper_implementation') == reference(search_b.__file__)
        and b.get('shared_financial_calculation_helper') is False
        and b.get('independent_raw_public_primitives_precompilation') is True,
        'The independently authored A/B kernels or raw-spec precompilation changed')
    require(evidence.check(a['raw_primitives']).read_text() == search_a.raw_primitives(public, list(range(30))),
        'The A execution wire differs from the complete raw public primitives')
    b_preparation, b_public = search_b.validate_prepared(b['preparation'])
    require(b_public == public and b_preparation['full_enumeration'] is True
        and b_preparation['toy_only'] is False
        and b_preparation['active_project_ids'] == list(spec.project_ids(30))
        and b.get('kernel_command') == [b['compiled_binary']['path'], b_preparation['raw_wire']['path'], b['records']['path']],
        'The B execution must bind its complete exact raw-spec preparation and binary')
    require(Path(a['records']['path']) != Path(b['records']['path'])
        and a['records']['sha256'] == b['records']['sha256'] and a['records']['bytes'] == b['records']['bytes'] == RECORD_BYTES
        and a.get('chunks') == b.get('chunks'), 'The two complete independent record streams or chunks differ')
    for result in (a, b):
        stream_records(result['records'], result['chunks'], COUNT, progress)
        evidence.checked[result['records']['path']] = dict(result['records'])
    compilation = evidence.read(a['compilation'])
    require(compilation.get('kind') == 'capital_scaled_A_compilation' and compilation.get('returncode') == 0
        and compilation.get('implementation') == reference(search_a.SOURCE), 'The A compilation does not bind its independent source')
    require(a['kernel_result'].get('plan_count') == COUNT and a['kernel_result'].get('scenario_evaluations') == COUNT * 3
        and all(a['kernel_result'].get(key) == rank[key] for key in search_a.RANK_FIELDS)
        and b['kernel_statistics'].get('plan_count') == COUNT
        and b['kernel_statistics'].get('scenario_evaluations') == COUNT * 3
        and b['kernel_statistics'].get('feasible_count') == rank['feasible_count'], 'The actual kernel statistics differ from their complete scans')
    comparison = evidence.read(terminal['complete_record_comparison'])
    require(comparison.get('kind') == 'complete_independent_ordinal_record_equality'
        and comparison.get('records_equal_complete') is True and comparison.get('rankings_equal') is True
        and comparison.get('all_chunk_hashes_equal') is True
        and comparison.get('plan_count') == comparison.get('record_count_per_kernel') == COUNT
        and comparison.get('record_bytes_per_kernel') == RECORD_BYTES
        and comparison.get('chunk_count_per_kernel') == COUNT // spec.CHUNK_RECORDS
        and comparison.get('A_records') == a['records'] and comparison.get('B_records') == b['records']
        and comparison.get('kernel_A_result') == terminal['kernel_A_result']
        and comparison.get('kernel_B_result') == terminal['kernel_B_result']
        and comparison.get('rank_fields') == rank, 'The complete ordinal/ranking equality proof differs')
    selected = evidence.read(terminal['independent_decimal_validation'])
    require(selected.get('kind') == 'independent_forward_journal_selected_plan_checks' and selected.get('passed') is True
        and selected.get('not_an_independent_global_optimum_claim') is True and selected.get('optimisation_performed') is False
        and selected.get('complete_search_evidence') == terminal['complete_record_comparison'],
        'Selected-plan Decimal checks must not be relabelled as another global search')
    plans = {'best': rank['best_plan'], 'runnerup': {p['id']: (rank['runnerup_mask'] >> i) & 1 for i, p in enumerate(public['projects'])},
             **catalog.fixed_plans(PROFILE_ID)}
    rows = selected.get('checks', [])
    require([row.get('name') for row in rows] == list(plans), 'A predeclared selected-plan Decimal check is missing or reordered')
    for row in rows:
        plan = plans[row['name']]
        mask = sum(plan[p['id']] << i for i, p in enumerate(public['projects']))
        forward = evidence.read(row['ledger'])
        flags, npvs = _selected_record(a['records']['path'], mask)
        require(row.get('mask') == mask and row.get('complete_record_npvs_match') is True
            and row.get('all_journals_balance') is True and forward.get('plan') == plan
            and all(item.get('all_journals_balance') is True for item in forward['scenarios'].values())
            and row.get('objective_pence') == forward.get('objective_pence')
            and row.get('feasible') == forward.get('feasible')
            and row.get('scenario_npvs_pence') == {sid: forward['scenarios'][sid]['npv_pence'] for sid in spec.SCENARIO_IDS}
            and flags == sum(1 << i for i, sid in enumerate(spec.SCENARIO_IDS) if forward['scenarios'][sid]['feasible'])
            and npvs == [forward['scenarios'][sid]['npv_pence'] if forward['scenarios'][sid]['feasible'] else spec.NULL_NPV
                         for sid in spec.SCENARIO_IDS], 'A selected-plan independent journal differs from the complete records')
    require(next(row for row in rows if row['name'] == 'best')['objective_pence'] == rank['objective_pence']
        and next(row for row in rows if row['name'] == 'runnerup')['objective_pence'] == rank['runnerup_objective_pence'],
        'The winning or runner-up Decimal objective differs')
    evidence.graph([terminal, started, a, b, compilation, comparison, selected])
    return {'rank': rank, 'terminal': terminal, 'best_ledger': next(row['ledger'] for row in rows if row['name'] == 'best'),
        'verified_artifacts': dict(evidence.checked), 'records_rehashed': [a['records'], b['records']],
        'global_optimum_method': 'two_independent_full_exhaustive_cpp_record_streams',
        'selected_plan_decimal_checks_are_not_an_independent_global_search': True}


@contextmanager
def data_temporary(output):
    output = Path(output).absolute()
    directory = output / 'temporary'
    require(output == output.resolve() and output.is_relative_to(ROOT) and output.is_relative_to(Path('/data'))
        and directory == directory.resolve(), 'Temporary files must stay in this real source run under /data')
    directory.mkdir(exist_ok=True)
    previous, present, cache = os.environ.get('TMPDIR'), 'TMPDIR' in os.environ, tempfile.tempdir
    try:
        os.environ['TMPDIR'] = str(directory)
        tempfile.tempdir = str(directory)
        with tempfile.TemporaryFile(dir=directory) as stream:
            stream.write(b'scaled-source-write-check')
        yield directory
    finally:
        if present:
            os.environ['TMPDIR'] = previous
        else:
            os.environ.pop('TMPDIR', None)
        tempfile.tempdir = cache


def _runtime(runtime_profile):
    binding = reference(runtime_profile)
    profile = load_runtime_profile(runtime_profile)
    require(profile['id'] == 'entity_group_large_v2' and profile['docker_resources']['source']['memory_bytes'] == 32 * 1024**3,
        'This prospective source explicitly uses the same 32-GiB profile for all three roles')
    return binding, profile


def prepare(specification, catalog_manifest, dual_proof, output, *, runtime_profile=DEFAULT_RUNTIME):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT) and not output.exists(), 'Use a fresh source directory under the project /data root')
    runtime_ref, runtime = _runtime(runtime_profile)
    evidence = Evidence()
    public, source_ref, catalog_ref, manifest, artifacts = _catalog_context(specification, catalog_manifest, evidence)
    proof_ref = reference(dual_proof)
    checked = validate_dual_proof(public, source_ref, catalog_ref, artifacts, proof_ref)
    recipe = recipes()
    output.mkdir(parents=True)
    copied = {}
    for name, source in artifacts.items():
        destination = output / 'public' / Path(source['path']).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evidence.check(source), destination)
        copied[name] = reference(destination)
    validation_ref = write_new(output / 'private/validated_dual_proof.json', checked)
    return write_new(output / 'preparation.json', {'kind': KIND, 'version': 1, 'profile_id': PROFILE_ID,
        'public_specification': source_ref, 'catalog_manifest': catalog_ref, 'public_contract_artifacts': artifacts,
        'copied_public_contract_artifacts': copied, 'dual_search_proof': proof_ref,
        'validated_dual_proof': validation_ref, 'recipe_sha256': recipe,
        'runtime_profile': runtime_ref, 'runtime_profile_value': runtime,
        'expected_physical_formulas': FORMULAS, 'project_count': 30, 'plan_count_per_kernel': COUNT,
        'raw_ancestors': dict(spec.RAW_ANCESTORS), 'raw_ancestry_is_provenance_only': True,
        'hypothetical_forecasts_and_policy': True, 'workbook_emitted': False, 'winning_plan_written_to_public_files': False,
        'actual_LO_calls': 0, 'actual_new_enumerations': 0, 'model_calls': 0,
        'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0})


def validate_prepared(output, progress=None):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT), 'A source preparation must stay in its real project directory')
    evidence = Evidence()
    frozen = evidence.read(reference(output / 'preparation.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
        and frozen.get('profile_id') == PROFILE_ID and frozen.get('recipe_sha256') == recipes()
        and frozen.get('workbook_emitted') is False and frozen.get('winning_plan_written_to_public_files') is False
        and frozen.get('actual_LO_calls') == frozen.get('actual_new_enumerations') == frozen.get('model_calls') == 0,
        'The immutable zero-call source preparation changed')
    require(frozen.get('expected_physical_formulas') == FORMULAS and frozen.get('project_count') == 30
        and frozen.get('plan_count_per_kernel') == COUNT and frozen.get('raw_ancestors') == spec.RAW_ANCESTORS
        and frozen.get('raw_ancestry_is_provenance_only') is True and frozen.get('hypothetical_forecasts_and_policy') is True
        and frozen.get('quality_or_difficulty_certified') is False and frozen.get('qualified') is False
        and frozen.get('task_count') == 0, 'The complete source scope or honest provenance claims changed')
    runtime_ref, runtime = _runtime(frozen['runtime_profile']['path'])
    require(runtime_ref == frozen['runtime_profile'] and runtime == frozen['runtime_profile_value'], 'The explicit source resource profile changed')
    public, source_ref, catalog_ref, _, artifacts = _catalog_context(frozen['public_specification']['path'], frozen['catalog_manifest']['path'], evidence)
    require(source_ref == frozen['public_specification'] and catalog_ref == frozen['catalog_manifest']
        and artifacts == frozen['public_contract_artifacts'], 'The frozen original public contract changed')
    require(set(frozen['copied_public_contract_artifacts']) == set(PUBLIC_ARTIFACTS), 'All four copied public contract artifacts are required')
    for key, record in frozen['copied_public_contract_artifacts'].items():
        evidence.check(record)
        require(record['sha256'] == artifacts[key]['sha256'] and record['bytes'] == artifacts[key]['bytes']
            and Path(record['path']) == output / 'public' / Path(artifacts[key]['path']).name,
            'A copied public contract differs or escaped its public directory')
    require({str(path) for path in (output / 'public').rglob('*') if path.is_file()}
        == {record['path'] for record in frozen['copied_public_contract_artifacts'].values()},
        'The public source preparation contains an unexpected artifact')
    checked = validate_dual_proof(public, source_ref, catalog_ref, artifacts, frozen['dual_search_proof'], progress)
    require(evidence.read(frozen['validated_dual_proof']) == checked, 'The original complete dual validation changed')
    return frozen


@contextmanager
def phase(audit, name):
    clock = time.monotonic()
    audit.task(PROFILE_ID, mode='source_build', status='running', node=name)
    identity = audit.record('nodes', {'task_id': PROFILE_ID, 'node_id': name, 'status': 'running', 'started_at': utcnow()})
    audit.emit('source.phase.started', node_id=name, model_calls=0)
    try:
        yield
    except BaseException as error:
        audit.update_record('nodes', identity, {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error),
            'duration_ms': (time.monotonic() - clock) * 1000})
        raise
    else:
        audit.update_record('nodes', identity, {'status': 'completed', 'duration_ms': (time.monotonic() - clock) * 1000})


def execute_prepared(output, *, port=0):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT) and (output / 'preparation.json').is_file(),
        'An existing source preparation under the real project root is required')
    lease = ProducerLease(output).acquire()
    audit = server = None
    attempt = output / 'private/build_attempts' / uuid.uuid4().hex
    status, clock, calls = 'failed', time.monotonic(), []
    try:
        with data_temporary(output):
            require(not (output / 'seed_manifest.json').exists(), 'Never overwrite an already built source')
            attempt.mkdir(parents=True)
            write_new(attempt / 'started.json', {'kind': 'scaled_capital_source_attempt', 'started_at': utcnow(),
                'preparation': reference(output / 'preparation.json'), 'profile_id': PROFILE_ID,
                'model_calls': 0, 'new_search_calls': 0, 'quality_or_difficulty_certified': False})
            audit = AuditStore(attempt / 'audit', {'id': attempt.name, 'name': 'Scaled capital source engineering',
                'status': 'running', 'target_count': 0, 'producer_pid': os.getpid(), 'producer_active': True,
                'model_calls': 0, 'tokens': 0, 'qualified': 0})
            server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            audit.update_run(dashboard_url=url)
            print(json.dumps({'dashboard_url': url, 'source_attempt': str(attempt), 'model_calls': 0, 'LO_calls': 0}), flush=True)
            last_progress = [0.0]
            def progress(path, observed, total):
                now = time.monotonic()
                if observed == total or now - last_progress[0] >= 1:
                    audit.update_run(active_record_stream=str(path), record_bytes_rehashed=observed, record_bytes_expected=total)
                    last_progress[0] = now
            with phase(audit, 'verify_complete_frozen_dual_search'):
                frozen = validate_prepared(output, progress)
                public = spec.load_spec(json.loads(Path(frozen['public_specification']['path']).read_text()))
                proof = json.loads(Path(frozen['validated_dual_proof']['path']).read_text())
                plan = ledger.validate_plan(public, proof['rank']['best_plan'])
            with phase(audit, 'independent_complete_winner_journal'):
                forward = ledger.simulate(public, plan)
                expected = Evidence().read(proof['best_ledger'])
                require(forward == expected and forward['feasible'] is True
                    and forward['objective_pence'] == proof['rank']['objective_pence'],
                    'Every independently computed winning financial field must match the dual-proof journal')
                ledger_ref = write_new(attempt / 'independent_winner_ledger.json', forward)
            with phase(audit, 'emit_private_full_financial_goal'):
                book = openpyxl.Workbook()
                book.remove(book.active)
                try:
                    bindings = excel.emit_capital_allocation_workbook(book, public, plan)
                    require(bindings['formula_count'] == FORMULAS and len(bindings['decision_bindings']) == 30
                        and bindings.get('gold_plan_supplied') is True and bindings.get('public_rules') == list(excel.PUBLIC_RULES),
                        'The complete thirty-project formula or public-schema scope changed')
                    raw = attempt / 'raw_goal.xlsx'
                    book.save(raw)
                finally:
                    book.close()
                bindings_ref = write_new(attempt / 'bindings.json', bindings)
            engine = ResourceLibreOfficeEngine(ROOT, frozen['runtime_profile']['path'], role='source',
                                              receipt_directory=attempt / 'engine_resources')
            engine.ensure_image()
            current, versions, audits = raw, [], []
            for index in range(3):
                destination = attempt / ('calculated_pass' + str(index + 1) + '.xlsx')
                call = {'index': index + 1, 'input': reference(current), 'destination': str(destination),
                    'started_at': utcnow(), 'completed': False}
                calls.append(call)
                write_new(attempt / ('LO_pass' + str(index + 1) + '_started.json'), call)
                with phase(audit, 'actual_LO_pass' + str(index + 1)):
                    try:
                        actual = engine.recalculate(current, destination)
                        call.update(output=reference(actual), completed=True)
                    except BaseException as error:
                        call.update(error_type=type(error).__name__, error=str(error))
                        raise
                    finally:
                        call['finished_at'] = utcnow()
                        write_new(attempt / ('LO_pass' + str(index + 1) + '_terminal.json'), call)
                        audit.update_run(actual_LO_calls_completed=sum(item['completed'] for item in calls),
                                         actual_LO_calls_started=len(calls))
                with phase(audit, 'independent_all_formula_cache_audit' + str(index + 1)):
                    result = validate.audit_capital_allocation_workbook(actual, public, plan, forward, bindings)
                    audits.append(write_new(attempt / ('financial_audit_pass' + str(index + 1) + '.json'),
                                            {'workbook': reference(actual), **result}))
                    require(result.get('passed') is True and result.get('checked_cells') == result.get('formula_count') == FORMULAS
                        and result.get('all_formula_cells_independently_covered') is True
                        and result.get('all_scenarios_feasible') is True and result.get('all_journals_balance') is True
                        and result.get('mismatches') == [] and result.get('control_mismatches') == [],
                        'An actual financial field, exact arithmetic helper, provided input or public contract failed audit')
                versions.append(actual)
                current = actual
            with phase(audit, 'complete_two_further_pass_stability'):
                stability = {'first_against_goal': compare_exact_typed(versions[0], versions[1]),
                             'second_against_goal': compare_exact_typed(versions[0], versions[2])}
                stability['stable'] = all(item['passed'] is True for item in stability.values())
                stability_ref = write_new(attempt / 'stability.json', stability)
                require(stability['stable'], 'The full financial goal is not stable over both further actual passes')
            with phase(audit, 'recheck_frozen_proof_and_publish_private_source_receipt'):
                require(validate_prepared(output, progress) == frozen, 'Source construction changed the frozen preparation or complete search proof')
                runtime = engine.metadata()
                require(runtime.get('runtime_profile') == frozen['runtime_profile_value']
                    and len(runtime.get('actual_resource_receipts', [])) == 3, 'All three actual source resource receipts are required')
                evidence = Evidence()
                for call, record in zip(calls, runtime['actual_resource_receipts']):
                    actual_resource = evidence.read(record)
                    r = frozen['runtime_profile_value']['docker_resources']['source']
                    require(actual_resource.get('status') == 'completed' and actual_resource.get('actual_resources_verified') is True
                        and actual_resource.get('source') == call['input'] and actual_resource.get('output') == call['output']
                        and actual_resource.get('image_id') == frozen['runtime_profile_value']['image']['id']
                        and actual_resource.get('profile') == frozen['runtime_profile']
                        and actual_resource.get('implementation') == reference(resource_engine.__file__)
                        and actual_resource.get('requested_resources') == r
                        and actual_resource.get('workbook_file_timeout_seconds') == 600
                        and actual_resource.get('actual_resources') == {'cpus_nanoseconds': r['cpus'] * 10**9,
                            'memory_bytes': r['memory_bytes'], 'pids_limit': r['pids_limit']},
                        'A source calculation lacks its exact actual resource enforcement evidence')
                    call['resource_receipt'] = record
                manifest = {'kind': 'independently_verified_scaled_capital_allocation_source', 'version': 1,
                    'source_kind': 'derived_scaled_capital_allocation_source', 'profile_id': PROFILE_ID,
                    'status': 'source_verified_not_task_quality_or_difficulty_qualified',
                    'local_path': str(versions[0]), 'workbook': reference(versions[0]),
                    'derived_workbook_sha256': reference(versions[0])['sha256'],
                    'public_specification': frozen['copied_public_contract_artifacts']['spec'],
                    'public_contract_artifacts': frozen['copied_public_contract_artifacts'],
                    'source_preparation': reference(output / 'preparation.json'), 'dual_search_proof': frozen['dual_search_proof'],
                    'validated_dual_proof': frozen['validated_dual_proof'], 'bindings': bindings_ref,
                    'independent_ledger': ledger_ref, 'financial_audits': audits, 'financial_audit_passed': True,
                    'stability': stability_ref, 'engine_calls': calls, 'actual_LO_recalculations': 3,
                    'runtime_profile': frozen['runtime_profile'], 'runtime': runtime,
                    'agent_and_verifier_resources_actually_verified': False,
                    'source_recipe_sha256': frozen['recipe_sha256'], 'project_count': 30, 'physical_formula_count': FORMULAS,
                    'raw_ancestors': frozen['raw_ancestors'], 'raw_ancestry_is_provenance_only': True,
                    'hypothetical_forecasts_and_policy': True, 'source_original_ancestors': 2,
                    'model_calls': 0, 'new_enumeration_calls': 0,
                    'task_input_and_complete_D_not_built': True,
                    'gold_decisions_and_financials_require_normal_task_masking': True,
                    'plan_dependent_helper_caches_require_clearing_and_actual_input_recalculation': True,
                    'complete_required_D_must_include_changed_arithmetic_helpers': True,
                    'full_public_sidecar_contract_must_be_transferred_to_task': True,
                    'five_controls_recovery_all12_quality_Harbor_and_difficulty_pending': True,
                    'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
                receipt = write_new(output / 'seed_manifest.json', manifest)
                status = 'source_verified'
                write_new(attempt / 'terminal.json', {'status': status, 'manifest': receipt, 'calls': calls,
                    'elapsed_seconds': time.monotonic() - clock, 'engineering_time_excluded_from_solver_trial': True,
                    'model_calls': 0, 'quality_or_difficulty_certified': False})
                return receipt
    except BaseException as error:
        if attempt.is_dir() and not (attempt / 'terminal.json').exists():
            write_new(attempt / 'terminal.json', {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error),
                'calls': calls, 'all_partial_artifacts_preserved': True, 'model_calls': 0, 'qualified': False, 'task_count': 0})
        raise
    finally:
        try:
            if audit is not None:
                audit.update_run(status=status, producer_active=False, finished_at=utcnow(), elapsed_seconds=time.monotonic() - clock)
                audit.export()
        finally:
            try:
                if server is not None:
                    server.stop()
            finally:
                try:
                    if audit is not None:
                        audit.db.close()
                finally:
                    lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('spec', 'catalog-manifest', 'dual-proof', 'output', 'prepared', 'runtime-profile'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared is not None:
        require(not any((args.spec, args.catalog_manifest, args.dual_proof, args.output, args.runtime_profile)),
                'An existing preparation cannot acquire new arguments')
        if args.run:
            result = execute_prepared(args.prepared, port=args.port)
        else:
            validate_prepared(args.prepared)
            result = {'validated': str(args.prepared), 'LO_calls': 0, 'model_calls': 0, 'new_enumeration_calls': 0}
    else:
        require(not args.run and all((args.spec, args.catalog_manifest, args.dual_proof, args.output)),
                'Prepare first; actual source construction requires explicit --prepared --run')
        result = prepare(args.spec, args.catalog_manifest, args.dual_proof, args.output,
                         runtime_profile=args.runtime_profile or DEFAULT_RUNTIME)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
