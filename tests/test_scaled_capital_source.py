"""Source orchestration and strict proof contracts; no full search or real LO.

Huge completed binary files are explicit test doubles in the orchestration
fixtures. The real byte/chunk verifier is separately tested on small records.
No fixture is production search, financial-source or container evidence.
"""
from copy import deepcopy
import builtins
import dis
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
_module = importlib.util.spec_from_file_location('scaled_source_entry_test', ROOT / 'scripts/build_scaled_capital_source.py')
builder = importlib.util.module_from_spec(_module)
_module.loader.exec_module(builder)
CATALOG = ROOT / 'outputs/research/capital_scaled_public_specs_20261030T224900Z/catalog_manifest.json'
DRIVER = ROOT / 'outputs/research/capital_scaled_30_D01_dual_actual_20261030T224835Z/run_dual.py'


def write(path, value):
    return builder.write_new(path, value)


def read(record):
    return json.loads(Path(record['path']).read_text())


def raw_records(tmp_path, count=8):
    path = tmp_path / 'small_records.bin'
    with path.open('wb') as stream:
        for mask in range(count):
            stream.write(struct.pack(builder.spec.RECORD_FORMAT, mask, 7, 100 + mask, 200 + mask, 300 + mask))
    record = builder.reference(path)
    chunks = []
    with path.open('rb') as stream:
        seen = 0
        while block := stream.read(builder.spec.CHUNK_RECORDS * builder.spec.RECORD_BYTES):
            n = len(block) // builder.spec.RECORD_BYTES
            chunks.append({'start_mask': seen, 'end_mask_exclusive': seen + n, 'record_count': n,
                'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
            seen += n
    return record, chunks


def test_complete_byte_and_all_chunk_hashes_are_recomputed(tmp_path):
    count = builder.spec.CHUNK_RECORDS + 1  # protocol bytes only, no financial enumeration
    record, chunks = raw_records(tmp_path, count)
    observed = []
    assert builder.stream_records(record, chunks, count, lambda *args: observed.append(args[1])) == record
    assert observed == [builder.spec.CHUNK_RECORDS * 32, count * 32]


@pytest.mark.parametrize('mutation', ['middle_byte', 'truncated', 'extra', 'whole_sha', 'chunk_sha', 'coverage', 'missing_chunk'])
def test_real_binary_validation_rejects_changed_partial_or_fake_summaries(tmp_path, mutation):
    record, chunks = raw_records(tmp_path)
    path = Path(record['path'])
    if mutation == 'middle_byte':
        data = bytearray(path.read_bytes()); data[40] ^= 1; path.write_bytes(data)
    elif mutation == 'truncated':
        path.write_bytes(path.read_bytes()[:-1])
    elif mutation == 'extra':
        with path.open('ab') as stream: stream.write(b'\0')
    elif mutation == 'whole_sha':
        record['sha256'] = '0' * 64
    elif mutation == 'chunk_sha':
        chunks[0]['sha256'] = '0' * 64
    elif mutation == 'coverage':
        chunks[0]['start_mask'] = 1
    else:
        chunks.clear()
    with pytest.raises(ValueError):
        builder.stream_records(record, chunks, 8)


def catalog_context():
    manifest = json.loads(CATALOG.read_text())
    source = next(row['spec']['path'] for row in manifest['specifications'] if row['profile_id'] == '30-D01')
    return builder._catalog_context(source, CATALOG, builder.Evidence())


def test_original_catalog_binds_first_role_all13_and_complete_public_dictionary():
    public, source, catalog_ref, manifest, artifacts = catalog_context()
    assert len(public['projects']) == 30 and catalog_ref['sha256'] == builder.CATALOG_SHA256
    assert manifest['profile_order'] == list(builder.catalog.PROFILE_ORDER)
    assert artifacts['spec'] == source
    contract = read(artifacts['candidate_contract'])
    assert set(contract['summary_fields']) and set(contract['annual_fields']) and set(contract['vintage_fields'])
    assert 'including candidates with choice 0' in contract['candidate_schedule_policy']


def test_different_profile_or_changed_catalog_cannot_be_substituted(tmp_path):
    manifest = json.loads(CATALOG.read_text())
    wrong = next(row['spec']['path'] for row in manifest['specifications'] if row['profile_id'] == '30-G01')
    with pytest.raises(ValueError, match='first development'):
        builder._catalog_context(wrong, CATALOG, builder.Evidence())
    changed = tmp_path / 'catalog.json'
    manifest['prospective_first_strong_profile'] = '30-G01'
    write(changed, manifest)
    with pytest.raises(ValueError, match='prospectively frozen'):
        builder._catalog_context(wrong, changed, builder.Evidence())


@pytest.fixture
def proof(tmp_path, monkeypatch):
    public, source, catalog_ref, _, artifacts = catalog_context()
    root = tmp_path / 'unit_dual_proof'
    root.mkdir()
    shutil.copy2(DRIVER, root / 'run_dual.py')
    b_preparation = builder.search_b.prepare(public, root / 'B')  # raw primitives only, zero compiler/kernel calls
    b_frozen = read(b_preparation)
    driver_recipe_paths = [root / 'run_dual.py', Path(builder.search_a.__file__), Path(builder.search_a.SOURCE),
        Path(builder.search_b.__file__), Path(builder.search_b.KERNEL), Path(builder.spec.__file__),
        Path(builder.ledger.__file__), Path(builder.original_ledger.__file__), Path(builder.catalog.__file__), Path(builder.original_spec.__file__)]
    recipe = {str(path.resolve()): builder.reference(path) for path in driver_recipe_paths}
    rank = {'feasible_count': builder.COUNT, 'best_count': 1, 'best_mask': 3, 'objective_pence': 1000,
        'runnerup_mask': 1, 'runnerup_objective_pence': 900, 'gap_pence': 100,
        'unique_best': True, 'best_full_mask': 3,
        'best_plan': {p['id']: (3 >> i) & 1 for i, p in enumerate(public['projects'])}}
    chunks = [{'start_mask': i, 'end_mask_exclusive': i + builder.spec.CHUNK_RECORDS,
        'record_count': builder.spec.CHUNK_RECORDS, 'bytes': builder.spec.CHUNK_RECORDS * 32,
        'sha256': 'd' * 64} for i in range(0, builder.COUNT, builder.spec.CHUNK_RECORDS)]
    native, rows, selected_npvs = {}, [], {}
    plans = {'best': rank['best_plan'], 'runnerup': {p['id']: (1 >> i) & 1 for i, p in enumerate(public['projects'])},
             **builder.catalog.fixed_plans(builder.PROFILE_ID)}
    best_ledger = None
    for name, plan in plans.items():
        mask = sum(plan[p['id']] << i for i, p in enumerate(public['projects']))
        value = 1000 if mask == 3 else 900 if mask == 1 else 100 - mask % 50
        npvs = [value + 2, value + 1, value]
        selected_npvs[mask] = (7, npvs)
        forward = {'test_fixture_only': True, 'schema_version': 1, 'plan': plan, 'feasible': True,
            'objective_pence': value, 'scenarios': {sid: {'feasible': True, 'all_journals_balance': True,
                'npv_pence': npvs[i]} for i, sid in enumerate(builder.spec.SCENARIO_IDS)}}
        ref = write(root / 'decimal' / (name + '.json'), forward)
        if name == 'best': best_ledger = forward
        rows.append({'name': name, 'mask': mask, 'ledger': ref, 'complete_record_npvs_match': True,
            'feasible': True, 'objective_pence': value,
            'scenario_npvs_pence': {sid: npvs[i] for i, sid in enumerate(builder.spec.SCENARIO_IDS)},
            'all_journals_balance': True})
    binary = root / 'explicit_test_double_binary'
    binary.write_text('A unit test stub, not an executed financial kernel')
    compilation = write(root / 'compilation.json', {'kind': 'capital_scaled_A_compilation', 'returncode': 0,
        'implementation': builder.reference(builder.search_a.SOURCE), 'binary': builder.reference(binary), 'test_fixture_only': True})
    raw = root / 'a_raw.txt'
    raw.write_text(builder.search_a.raw_primitives(public, list(range(30))))
    for name, kind in (('A', 'capital_scaled_A_complete_enumeration'), ('B', 'capital_allocation_scaled_independent_B_execution')):
        path = root / (name + '_test_double_records.bin')
        path.write_text('Explicit tiny stand-in; real full-byte validator is mocked in this fixture.')
        records = {'path': str(path), 'sha256': 'f' * 64, 'bytes': builder.RECORD_BYTES}
        result = {'kind': kind, 'test_fixture_only': True, 'version': 1, 'status': 'completed', **rank,
            'plan_count': builder.COUNT, 'project_count': 30, 'full_enumeration': True, 'toy_only': False,
            'active_project_ids': list(builder.spec.project_ids(30)), 'spec_sha256': builder.spec.canonical_sha(public),
            'public_spec': b_frozen['public_spec'], 'record_format': builder.spec.RECORD_FORMAT,
            'record_bytes': 32, 'chunk_records': builder.spec.CHUNK_RECORDS, 'null_npv': builder.spec.NULL_NPV,
            'records': records, 'chunks': chunks}
        if name == 'A':
            result.update(recipe=builder.search_a.recipe(), raw_primitives=builder.reference(raw), compilation=compilation,
                kernel_result={**{k: rank[k] for k in builder.search_a.RANK_FIELDS}, 'plan_count': builder.COUNT,
                    'scenario_evaluations': builder.COUNT * 3})
        else:
            result.update(recipe_sha256=builder.search_b._recipe(), preparation=b_preparation,
                kernel_implementation=builder.reference(builder.search_b.KERNEL),
                wrapper_implementation=builder.reference(builder.search_b.__file__),
                shared_financial_calculation_helper=False, independent_raw_public_primitives_precompilation=True,
                compiled_binary=builder.reference(binary), kernel_command=[str(binary), b_frozen['raw_wire']['path'], records['path']],
                kernel_statistics={'plan_count': builder.COUNT, 'scenario_evaluations': builder.COUNT * 3,
                    'feasible_count': rank['feasible_count']})
        native[name] = write(root / (name + '_receipt.json'), result)
    comparison = write(root / 'comparison.json', {'kind': 'complete_independent_ordinal_record_equality',
        'records_equal_complete': True, 'rankings_equal': True, 'all_chunk_hashes_equal': True,
        'plan_count': builder.COUNT, 'record_count_per_kernel': builder.COUNT, 'record_bytes_per_kernel': builder.RECORD_BYTES,
        'chunk_count_per_kernel': builder.COUNT // builder.spec.CHUNK_RECORDS,
        'A_records': read(native['A'])['records'], 'B_records': read(native['B'])['records'],
        'kernel_A_result': native['A'], 'kernel_B_result': native['B'], 'rank_fields': rank})
    decimal = write(root / 'decimal_checks.json', {'kind': 'independent_forward_journal_selected_plan_checks',
        'passed': True, 'not_an_independent_global_optimum_claim': True, 'optimisation_performed': False,
        'complete_search_evidence': comparison, 'checks': rows})
    started = write(root / 'started.json', {'kind': 'frozen_first_30_D01_dual_search_attempt', 'version': 1,
        'profile_id': builder.PROFILE_ID, 'first_development_profile': builder.PROFILE_ID,
        'public_specification': source, 'catalog_manifest': catalog_ref, 'public_contract_artifacts': artifacts,
        'canonical_spec_sha256': builder.spec.canonical_sha(public), 'plan_count_per_kernel': builder.COUNT,
        'record_bytes_per_kernel': builder.RECORD_BYTES,
        'confirmation_profiles_not_enumerated': list(builder.catalog.CONFIRMATION_ORDER), 'recipe': recipe})
    terminal = write(root / 'receipt.json', {'kind': 'complete_scaled_capital_dual_search', 'version': 1,
        'test_fixture_only': True, 'status': 'completed', 'passed': True,
        'records_equal_complete': True, 'full_enumeration': True, 'toy_only': False,
        'count': builder.COUNT, 'plan_count': builder.COUNT, 'scenario_evaluations_per_kernel': builder.COUNT * 3,
        'public_specification': source, 'catalog_manifest': catalog_ref, 'public_contract_artifacts': artifacts,
        'started': started, 'recipe': recipe, 'kernel_A_result': native['A'], 'kernel_B_result': native['B'],
        'complete_record_comparison': comparison, 'independent_decimal_validation': decimal, **rank})
    scanned = []
    def mock_huge_records(record, chunks, expected_count, progress=None):
        # This mock substitutes only the unavailable 64GiB evidence read.
        # It cannot pass the actual stream_records implementation above.
        assert expected_count == builder.COUNT and len(chunks) == 16384
        assert record['bytes'] == builder.RECORD_BYTES
        scanned.append(record['path'])
        return record
    monkeypatch.setattr(builder, 'stream_records', mock_huge_records)
    monkeypatch.setattr(builder, '_selected_record', lambda path, mask: selected_npvs[mask])
    return SimpleProof(public=public, specification=source, catalog=catalog_ref, artifacts=artifacts, terminal=terminal,
        root=root, rank=rank, native=native, scanned=scanned, best_ledger=best_ledger)


class SimpleProof:
    def __init__(self, **values): self.__dict__.update(values)


def validate_proof(proof):
    return builder.validate_dual_proof(proof.public, proof.specification, proof.catalog, proof.artifacts, proof.terminal)


def test_complete_actual_protocol_contract_accepts_both_independent_proofs(proof):
    result = validate_proof(proof)
    assert result['rank'] == proof.rank and len(proof.scanned) == 2
    assert result['selected_plan_decimal_checks_are_not_an_independent_global_search'] is True
    assert len(result['records_rehashed']) == 2


@pytest.mark.parametrize('field,value', [('status', 'running'), ('passed', False), ('full_enumeration', False),
    ('toy_only', True), ('plan_count', 2**18), ('unique_best', False), ('gap_pence', 0),
    ('best_count', 2), ('best_mask', True)])
def test_partial_tied_toy_or_malformed_terminal_never_qualifies(proof, field, value):
    value_json = read(proof.terminal); value_json[field] = value
    proof.terminal = write(proof.root / 'bad_terminal.json', value_json)
    with pytest.raises(ValueError): validate_proof(proof)


@pytest.mark.parametrize('which', ['B_spec', 'B_raw_wire', 'A_raw_wire', 'comparison_rank', 'missing_decimal_plan', 'wrong_driver'])
def test_exact_raw_input_recipe_and_comparison_bindings_cannot_drift(proof, which):
    terminal = read(proof.terminal)
    if which.startswith('B_'):
        result = read(proof.native['B'])
        if which == 'B_spec': result['spec_sha256'] = '0' * 64
        else:
            preparation = read(result['preparation'])
            Path(preparation['raw_wire']['path']).write_text('bad raw public primitives')
        terminal['kernel_B_result'] = write(proof.root / 'bad_B.json', result)
    elif which == 'A_raw_wire':
        result = read(proof.native['A'])
        Path(result['raw_primitives']['path']).write_text('wrong raw source')
    elif which == 'comparison_rank':
        comparison = read(terminal['complete_record_comparison']); comparison['rank_fields']['gap_pence'] += 1
        terminal['complete_record_comparison'] = write(proof.root / 'bad_comparison.json', comparison)
    elif which == 'missing_decimal_plan':
        decimal = read(terminal['independent_decimal_validation']); decimal['checks'].pop()
        terminal['independent_decimal_validation'] = write(proof.root / 'bad_decimal.json', decimal)
    else:
        (proof.root / 'run_dual.py').write_text('print("unapproved receipt writer")')
    proof.terminal = write(proof.root / 'bad_terminal.json', terminal)
    with pytest.raises(ValueError): validate_proof(proof)


def prepare_proof(proof, output):
    return builder.prepare(proof.specification['path'], proof.catalog['path'], proof.terminal['path'], output)


def test_preparation_is_zero_book_zero_ledger_zero_search_zero_engine_and_public_has_no_winner(proof, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('Preparation must not execute financial or workbook engines')
    monkeypatch.setattr(builder.openpyxl, 'Workbook', forbidden)
    monkeypatch.setattr(builder.ledger, 'simulate', forbidden)
    monkeypatch.setattr(builder.search_a, 'execute_prepared', forbidden)
    monkeypatch.setattr(builder.search_b, 'execute_prepared', forbidden)
    monkeypatch.setattr(builder, 'ResourceLibreOfficeEngine', forbidden)
    output = tmp_path / 'source'
    record = prepare_proof(proof, output)
    frozen = builder.validate_prepared(output)
    assert frozen == read(record)
    assert frozen['actual_LO_calls'] == frozen['actual_new_enumerations'] == frozen['model_calls'] == 0
    assert not list(output.rglob('*.xlsx'))
    assert len(list((output / 'public').iterdir())) == 4
    for path in (output / 'public').iterdir(): assert '"best_plan"' not in path.read_text()
    assert read(frozen['validated_dual_proof'])['rank']['best_plan'] == proof.rank['best_plan']
    assert frozen['winning_plan_written_to_public_files'] is False


@pytest.mark.parametrize('mutation', ['public_answer', 'recipe', 'private_rank', 'missing_dictionary', 'wrong_scope'])
def test_frozen_preparation_rejects_public_leaks_and_proof_mutation(proof, tmp_path, mutation):
    output = tmp_path / 'source'
    record = prepare_proof(proof, output)
    frozen = read(record)
    if mutation == 'public_answer':
        (output / 'public/answer.json').write_text(json.dumps(proof.rank['best_plan']))
    elif mutation == 'private_rank':
        path = Path(frozen['validated_dual_proof']['path']); value = json.loads(path.read_text())
        value['rank']['objective_pence'] += 1; path.write_text(json.dumps(value))
    elif mutation == 'missing_dictionary':
        Path(frozen['copied_public_contract_artifacts']['candidate_contract']['path']).unlink()
    else:
        if mutation == 'recipe': frozen['recipe_sha256'] = {}
        else: frozen['project_count'] = 18
        Path(record['path']).write_text(json.dumps(frozen))
    with pytest.raises((ValueError, FileNotFoundError)): builder.validate_prepared(output)


def test_temporary_scope_is_current_data_run_and_restores_environment_and_cache(tmp_path):
    output = tmp_path / 'source'; output.mkdir()
    original = os.environ.get('TMPDIR'), 'TMPDIR' in os.environ, tempfile.tempdir
    with builder.data_temporary(output) as directory:
        assert tempfile.gettempdir() == str(output / 'temporary')
        with tempfile.NamedTemporaryFile() as created: assert Path(created.name).parent == directory
    assert (os.environ.get('TMPDIR'), 'TMPDIR' in os.environ, tempfile.tempdir) == original
    (output / 'temporary').rmdir(); (output / 'temporary').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        with builder.data_temporary(output): pass


def fake_pipeline(proof, monkeypatch, *, failure=None):
    state = {'calls': 0, 'audits': 0, 'server_stopped': False}
    profile = builder.load_runtime_profile(builder.DEFAULT_RUNTIME)
    monkeypatch.setattr(builder.ledger, 'simulate', lambda public, plan: deepcopy(proof.best_ledger))
    def emit(book, public, plan):
        # Explicit tiny orchestration stand-in, not a production source graph.
        book.create_sheet('Unit fixture')['A1'] = '=1'
        return {'formula_count': builder.FORMULAS, 'decision_bindings': [{'project_id': p['id']} for p in public['projects']],
            'gold_plan_supplied': True, 'public_rules': list(builder.excel.PUBLIC_RULES), 'test_fixture_only': True}
    monkeypatch.setattr(builder.excel, 'emit_capital_allocation_workbook', emit)
    def audit(*args):
        state['audits'] += 1
        passed = failure != 'audit2' or state['audits'] != 2
        count = builder.FORMULAS - int(failure == 'truncated_audit')
        return {'test_fixture_only': True, 'passed': passed, 'checked_cells': count, 'formula_count': count,
            'all_formula_cells_independently_covered': True, 'all_scenarios_feasible': True, 'all_journals_balance': True,
            'mismatches': [] if passed else ['unit failure'], 'control_mismatches': []}
    monkeypatch.setattr(builder.validate, 'audit_capital_allocation_workbook', audit)
    class Engine:
        def __init__(self, root, runtime, *, role, receipt_directory):
            assert role == 'source' and Path(os.environ['TMPDIR']).name == 'temporary'
            self.directory = receipt_directory; self.directory.mkdir(); self.receipts = []
            self.runtime = builder.reference(runtime)
        def ensure_image(self): return profile['image']['id']
        def recalculate(self, source, destination):
            state['calls'] += 1
            if failure == 'engine2' and state['calls'] == 2: raise RuntimeError('unit transient engine failure')
            shutil.copy2(source, destination)
            r = profile['docker_resources']['source']
            self.receipts.append(write(self.directory / (str(state['calls']) + '.json'), {
                'test_fixture_only': True, 'status': 'completed', 'actual_resources_verified': True,
                'source': builder.reference(source), 'output': builder.reference(destination), 'image_id': profile['image']['id'],
                'profile': self.runtime, 'implementation': builder.reference(builder.resource_engine.__file__),
                'requested_resources': r, 'workbook_file_timeout_seconds': 600,
                'actual_resources': {'cpus_nanoseconds': 2 * 10**9, 'memory_bytes': r['memory_bytes'], 'pids_limit': r['pids_limit']}}))
            return destination
        def metadata(self): return {'runtime_profile': profile, 'actual_resource_receipts': self.receipts}
    monkeypatch.setattr(builder, 'ResourceLibreOfficeEngine', Engine)
    original_server = builder.DashboardServer
    class Server(original_server):
        def stop(self):
            state['server_stopped'] = True
            return super().stop()
    monkeypatch.setattr(builder, 'DashboardServer', Server)
    if failure == 'stability': monkeypatch.setattr(builder, 'compare_exact_typed', lambda *a: {'passed': False})
    return state


def test_explicit_execution_real_audit_lease_panel_setup_and_three_calls_no_actual_external_engine(proof, tmp_path, monkeypatch):
    output = tmp_path / 'source'; prepare_proof(proof, output)
    state = fake_pipeline(proof, monkeypatch)
    record = builder.execute_prepared(output, port=0)
    manifest = read(record)
    assert state['calls'] == state['audits'] == 3 and state['server_stopped'] is True
    assert manifest['actual_LO_recalculations'] == 3 and len(manifest['financial_audits']) == 3
    assert manifest['physical_formula_count'] == 77513 and manifest['project_count'] == 30
    assert manifest['quality_or_difficulty_certified'] is False and manifest['task_count'] == 0
    assert manifest['agent_and_verifier_resources_actually_verified'] is False
    assert not list((output / 'public').glob('*.xlsx'))
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'
    with pytest.raises(ValueError, match='overwrite'): builder.execute_prepared(output)


@pytest.mark.parametrize('failure,expected_calls', [('engine2', 2), ('audit2', 2), ('truncated_audit', 1), ('stability', 3)])
def test_actual_stage_failure_retains_artifacts_and_never_issues_verified_source(proof, tmp_path, monkeypatch, failure, expected_calls):
    output = tmp_path / 'source'; prepare_proof(proof, output)
    state = fake_pipeline(proof, monkeypatch, failure=failure)
    with pytest.raises((ValueError, RuntimeError)): builder.execute_prepared(output, port=0)
    assert not (output / 'seed_manifest.json').exists()
    assert state['calls'] == expected_calls and state['server_stopped'] is True
    terminals = list((output / 'private/build_attempts').glob('*/terminal.json'))
    assert len(terminals) == 1
    failed = json.loads(terminals[0].read_text())
    assert failed['status'] == 'failed' and failed['all_partial_artifacts_preserved'] is True
    assert failed['model_calls'] == 0 and failed['qualified'] is False
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'


def test_cleanup_failure_still_stops_server_closes_db_and_releases_lease(proof, tmp_path, monkeypatch):
    output = tmp_path / 'source'; prepare_proof(proof, output)
    state = fake_pipeline(proof, monkeypatch)
    original_audit = builder.AuditStore
    audits = []
    class Audit(original_audit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); audits.append(self)
        def export(self): raise OSError('unit final projection failure')
    monkeypatch.setattr(builder, 'AuditStore', Audit)
    with pytest.raises(OSError, match='projection'): builder.execute_prepared(output, port=0)
    assert state['server_stopped'] is True
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'
    with pytest.raises(Exception): audits[0].db.execute('SELECT 1')


def test_cli_never_executes_without_explicit_prepared_run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(builder, 'validate_prepared', lambda output: calls.append(('validate', output)) or {})
    monkeypatch.setattr(builder, 'execute_prepared', lambda output, **kw: calls.append(('run', output)) or {'test_fixture': True})
    assert builder.main(['--prepared', str(tmp_path)]) == 0
    assert [name for name, _ in calls] == ['validate']
    assert builder.main(['--prepared', str(tmp_path), '--run']) == 0
    assert [name for name, _ in calls] == ['validate', 'run']
    with pytest.raises(ValueError): builder.main(['--run', '--output', str(tmp_path / 'new')])


def test_all_startup_and_nested_global_names_are_bound():
    def check(code):
        for instruction in dis.get_instructions(code):
            if instruction.opname in ('LOAD_GLOBAL', 'LOAD_NAME'):
                assert instruction.argval in vars(builder) or hasattr(builtins, instruction.argval), instruction.argval
        for value in code.co_consts:
            if inspect.iscode(value): check(value)
    for value in vars(builder).values():
        if inspect.isfunction(value) and value.__module__ == builder.__name__:
            # contextmanager uses wraps() on a contextlib function whose globals
            # belong to contextlib. Inspect the actual builder implementation.
            check(inspect.unwrap(value).__code__)
