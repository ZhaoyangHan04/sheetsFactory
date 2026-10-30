"""Public bundle/toy native search/resource contracts; no full search, LO or model."""
import ast
import base64
from copy import deepcopy
import dis
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.workbook.capital_allocation_scaled import public_recovery as recovery
from sheets_factory.workbook.capital_allocation_scaled import excel, ledger, spec, validate
from sheets_factory.workbook import entity_group_public_recovery as upstream
from sheets_factory.workbook.resource_engine import load_runtime_profile

ROOT = Path(__file__).resolve().parents[1]
hand_spec = importlib.util.spec_from_file_location('_scaled_public_toy', ROOT / 'tests/test_capital_allocation_scaled_ledger.py')
hand = importlib.util.module_from_spec(hand_spec); hand_spec.loader.exec_module(hand)


@pytest.fixture(scope='module')
def kernel(tmp_path_factory):
    directory = tmp_path_factory.mktemp('scaled_public_static_kernel') / 'explicit_compilation'
    return recovery.prepare_public_kernel(directory)  # compiler only; zero financial search


@pytest.fixture(scope='module')
def public(tmp_path_factory):
    directory = tmp_path_factory.mktemp('scaled_public_input')
    public = hand.public(30); public['tax_rate_p12'] = spec.SCALE // 4
    book = openpyxl.Workbook(); book.remove(book.active)
    binding = excel.emit_capital_allocation_workbook(book, public, {p['id']: 0 for p in public['projects']})
    for item in binding['financial_bindings'] + binding['decision_bindings']:
        book[item['sheet']][item['cell']] = None
    path = directory / 'input.xlsx'; book.save(path); book.close()
    instruction = directory / 'instruction.md'; instruction.write_text('Complete the common plan.\n\n' + recovery._contract_markdown())
    return path, instruction, public, binding


def _copy_public(public, directory):
    directory.mkdir()
    shutil.copy2(public[0], directory / 'input.xlsx'); shutil.copy2(public[1], directory / 'instruction.md')
    return directory / 'input.xlsx', directory / 'instruction.md'


def test_explicit_static_compilation_has_code_identity_and_no_execution_claim(kernel):
    frozen = recovery.validate_kernel_preparation(kernel)
    assert frozen['source_cpp']['sha256'] == recovery.SOURCE_SHA256
    assert '-static' in frozen['command'] and frozen['returncode'] == 0
    assert frozen['same_image_execution_compatibility_verified'] is False
    assert frozen['enumerations'] == frozen['LO_calls'] == frozen['model_calls'] == 0
    assert recovery._static_elf(frozen['binary']['path'])


@pytest.mark.parametrize('change', ['binary', 'source', 'command', 'log', 'claim', 'count'])
def test_kernel_preparation_refuses_changed_or_fabricated_evidence(kernel, tmp_path, change):
    source = Path(kernel['path']).parent
    value = json.loads((source / 'receipt.json').read_text())
    # A fresh modified receipt in the SAME directory ensures rejection comes
    # from the named changed evidence, not an unrelated binary-location error.
    if change == 'binary': value['binary']['sha256'] = '0' * 64
    elif change == 'source': value['source_cpp']['sha256'] = '0' * 64
    elif change == 'command': value['command'].remove('-static')
    elif change == 'log': value['compile.stdout']['sha256'] = '0' * 64
    elif change == 'claim': value['same_image_execution_compatibility_verified'] = True
    else: value['enumerations'] = 1
    fake = source / ('altered_' + change + '.json'); fake.write_text(json.dumps(value))
    with pytest.raises(ValueError): recovery.validate_kernel_preparation(fake)


def test_bundle_is_deterministic_and_never_compiles_implicitly(kernel, monkeypatch):
    monkeypatch.setattr(recovery.subprocess, 'run', lambda *a, **k: pytest.fail('No implicit compiler or kernel process'))
    first = recovery.compile_public_scaled_capital_recovery(kernel)
    assert first == recovery.compile_public_scaled_capital_recovery(kernel)
    assert 'active_project_ids=None' in first
    compile(first, 'recovery.py', 'exec')
    encoded = next(node.value for node in ast.walk(ast.parse(first)) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and len(node.value) > 10000)
    with ZipFile(io.BytesIO(base64.b64decode(encoded))) as archive:
        names = archive.namelist()
        assert any(name.endswith('/search_a.cpp') for name in names)
        assert any(name.endswith('/public_search_a') for name in names)
        assert not any(name.endswith(('.xlsx', '.bin', 'receipt.json')) for name in names)
        assert not any('source_admission' in name or 'bindings' in name or 'winner' in name for name in names)


def test_public_parser_restores_input_order_and_requires_complete_dictionary(public):
    book = openpyxl.load_workbook(public[0])
    try:
        actual = recovery.read_public_spec(book, public[1].read_text().strip())
        assert actual == public[2] and list(actual) == list(public[2])
        with pytest.raises(ValueError, match='complete candidate'):
            recovery.read_public_spec(book, 'Summary only; the rest was privately bound.')
    finally: book.close()


@pytest.mark.parametrize('change', ['rule', 'boolean', 'zero', 'duplicate', 'missing', 'calculated'])
def test_public_parser_rejects_ambiguous_or_incomplete_primitives(public, change):
    book = openpyxl.load_workbook(public[0])
    try:
        sheet = book['Capital Inputs']
        if change == 'rule': book['Capital Rules']['A4'] = 'Choose independently by scenario.'
        elif change == 'boolean': sheet['B3'] = True
        elif change == 'zero':
            row = next(r for r in range(3, sheet.max_row + 1) if type(sheet.cell(r, 2).value) is int and sheet.cell(r, 2).value == 0)
            sheet.cell(row, 2, '0')
        elif change == 'duplicate': sheet.cell(4, 1, sheet.cell(3, 1).value)
        elif change == 'missing': sheet.delete_rows(4)
        else: sheet['B3'] = '=1'
        with pytest.raises(ValueError): recovery.read_public_spec(book, public[1].read_text())
    finally: book.close()


def test_fresh_native_toy_uses_last_project_and_matches_all_decimal_candidates(public, kernel, tmp_path):
    directory = tmp_path / 'native'; directory.mkdir()
    compiled = recovery.validate_kernel_preparation(kernel)
    plan, result = recovery._native_search(public[2], directory, compiled['binary']['path'], ['P01', 'P30'])
    candidates = []
    for mask in range(4):
        proposed = {p['id']: int(bool((p['id'] == 'P01' and mask & 1) or (p['id'] == 'P30' and mask & 2))) for p in public[2]['projects']}
        candidates.append(ledger.simulate(public[2], proposed)['objective_pence'])
    assert candidates == [0, 30, 30, 60]
    assert result['plan_count'] == 4 and result['scenario_evaluations'] == 12
    assert result['objective_pence'] == max(candidates) == 60 and result['gap_pence'] == 30
    assert result['best_mask'] == 3 and plan['P01'] == plan['P30'] == 1
    assert result['full_enumeration'] is False and result['toy_only'] is True
    assert result['records_destination'] == '/dev/null' and result['independent_record_stream_scan_performed'] is False
    assert not list(directory.glob('*.bin'))


@pytest.mark.parametrize('change', ['partial', 'tie', 'gap', 'dimension', 'feasible'])
def test_native_result_requires_actual_complete_unique_statistics(public, tmp_path, monkeypatch, change):
    result = {'kind': 'capital_scaled_kernel_a_result', 'version': 1, 'project_count': 30, 'active_count': 2,
        'plan_count': 4, 'scenario_evaluations': 12, 'unique_best': True, 'best_count': 1,
        'best_mask': 3, 'runnerup_mask': 1, 'objective_pence': 60, 'runnerup_objective_pence': 30,
        'gap_pence': 30, 'feasible_count': 4}
    if change == 'partial': result['plan_count'] = 3
    elif change == 'tie': result.update(unique_best=False, best_count=2, gap_pence=0)
    elif change == 'gap': result['gap_pence'] = 1
    elif change == 'dimension': result['active_count'] = 18
    else: result['feasible_count'] = 5
    def fake(command, stdout, **kwargs):
        stdout.write(json.dumps(result)); return SimpleNamespace(returncode=0)
    monkeypatch.setattr(recovery.subprocess, 'run', fake)
    with pytest.raises(ValueError, match='genuinely complete'):
        recovery._native_search(public[2], tmp_path, tmp_path / 'fake', ['P01', 'P30'])


@pytest.fixture(scope='module')
def recovered(public, kernel, tmp_path_factory):
    directory = tmp_path_factory.mktemp('scaled_public_replay')
    output = directory / 'output.xlsx'
    report = recovery.recover_public(public[0], output, directory / 'public_recovery_report.json',
        instruction_path=public[1], kernel_path=recovery.validate_kernel_preparation(kernel)['binary']['path'],
        active_project_ids=['P01', 'P30'])
    return directory, output, report


def test_public_recovery_covers_all_thirty_candidates_and_all_financial_fields(public, recovered):
    directory, output, report = recovered
    assert report['financial_and_decision_cells_reconstructed'] == 25541
    assert report['expected_all_formula_values_derived'] == 77513
    assert report['private_goal_source_bindings_or_search_proof_read'] is False
    assert report['shared_source_A_optimizer'] is report['shared_source_Decimal_forward_implementation'] is True
    assert report['shared_excel_layout_and_support_compiler'] is True and report['independent_second_search_claimed'] is False
    assert report['enumeration']['toy_only'] is True
    book = openpyxl.load_workbook(output)
    original = openpyxl.load_workbook(public[0])
    try:
        binding = json.loads((directory / 'public_definitions.json').read_text())
        assert sum(c.data_type == 'f' for s in book for c in s._cells.values()) == 51972
        assert book['Investment Plan']['B3'].value == book['Investment Plan']['B32'].value == 1
        for item in binding['arithmetic_bindings']:
            assert book[item['sheet']][item['cell']].value == original[item['sheet']][item['cell']].value
        values = validate.expected_cells(public[2], json.loads((directory / 'public_forward_ledger.json').read_text())['plan'],
            json.loads((directory / 'public_forward_ledger.json').read_text()), binding)
        for item in binding['financial_bindings'] + binding['decision_bindings']:
            assert book[item['sheet']][item['cell']].value == values[validate._reference(item['sheet'], item['cell'])]
    finally: book.close(); original.close()


def test_exact_bundled_standalone_program_runs_public_only_toy(public, kernel, tmp_path):
    replay = tmp_path / 'isolated'; source, instruction = _copy_public(public, replay)
    program = recovery.compile_public_scaled_capital_recovery(kernel, active_project_ids=['P01', 'P30'])
    (replay / 'recovery.py').write_text(program)
    # A new Python process receives only the public files and public code. It
    # cannot import this repo via its cwd; no private financial evidence exists.
    result = subprocess.run([sys.executable, '-I', str(replay / 'recovery.py')], cwd=replay,
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-4000:]
    report = json.loads((replay / 'public_recovery_report.json').read_text())
    assert report['enumeration']['plan_count'] == 4 and report['enumeration']['toy_only'] is True
    assert report['financial_and_decision_cells_reconstructed'] == 25541
    assert report['source_sha256'] == recovery._sha(source)
    assert not list(replay.glob('*.bin'))


def _cache_helpers(output, directory):
    """Synthetic unit-test caches, not actual LO evidence."""
    bindings = json.loads((directory / 'public_definitions.json').read_text())
    forward = json.loads((directory / 'public_forward_ledger.json').read_text())
    public = json.loads((directory / 'public_specification.json').read_text())
    expected = validate.expected_cells(public, forward['plan'], forward, bindings)
    with ZipFile(output) as archive: content = {name: archive.read(name) for name in archive.namelist()}
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    for i, sheet in enumerate(bindings['sheet_names'], 1):
        name = 'xl/worksheets/sheet' + str(i) + '.xml'; root = ET.fromstring(content[name])
        for cell in root.iter(ns + 'c'):
            if cell.find(ns + 'f') is None: continue
            value = expected[validate._reference(sheet, cell.attrib['r'])]
            for child in list(cell):
                if child.tag in (ns + 'v', ns + 'is'): cell.remove(child)
            cell.attrib.pop('t', None); ET.SubElement(cell, ns + 'v').text = str(value)
        content[name] = ET.tostring(root)
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, data in content.items(): archive.writestr(name, data)
    return public, forward, bindings


def test_value_only_cache_audit_is_complete_and_rejects_a_changed_financial_cell(recovered, tmp_path):
    directory, original, _ = recovered; output = tmp_path / 'synthetic_unit_cache.xlsx'; shutil.copy2(original, output)
    public, forward, bindings = _cache_helpers(output, directory)
    result = recovery.audit_public_recovered(output, public, forward['plan'], forward, bindings)
    assert result['passed'] and result['checked_cells'] == 77513
    assert result['formula_helper_count'] == 51972 and result['gold_formula_auditor_claimed'] is False
    book = openpyxl.load_workbook(output); item = bindings['financial_bindings'][-1]
    book[item['sheet']][item['cell']] = 999999; book.save(output); book.close()
    assert recovery.audit_public_recovered(output, public, forward['plan'], forward, bindings)['passed'] is False


def _ctx(tmp_path, kernel):
    profile_path = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
    return SimpleNamespace(config={recovery.SETTING: {'runtime_profile': recovery._reference(profile_path)},
        'recovery': {'compiler_backend': recovery.BACKEND, 'replay_timeout_seconds': 7200, 'public_kernel_preparation': kernel}},
        revision_dir=tmp_path, data={'revision_hash': 'a' * 64}, task_id='fm-unit', revision=0)


@pytest.mark.parametrize('stage', ['create_fail', 'inspect_fail', 'wrong_memory', 'start_fail', 'okay'])
def test_docker_ownership_and_actual_profile_contract(tmp_path, kernel, monkeypatch, stage):
    ctx = _ctx(tmp_path, kernel); replay = tmp_path / 'replay'; replay.mkdir(); attempt = tmp_path / 'attempt'; attempt.mkdir()
    profile = load_runtime_profile(ctx.config[recovery.SETTING]['runtime_profile']['path']); owned = 'a' * 64
    actual = {'Id': owned, 'Image': profile['image']['id'], 'NanoCpus': 2 * 10**9,
        'Memory': 32 * 1024**3, 'PidsLimit': 256, 'NetworkMode': 'none',
        'Cmd': ['/workspace/recovery.py'], 'Entrypoint': ['/usr/bin/python3'], 'WorkingDir': '/workspace', 'User': '0',
        'Mounts': [{'Type': 'bind', 'RW': True, 'Source': str(replay), 'Destination': '/workspace'}]}
    commands = []
    def fake(command, **kwargs):
        commands.append(command)
        if command[1] == 'create': return SimpleNamespace(returncode=1 if stage=='create_fail' else 0, stdout=owned, stderr='unit failure')
        if command[1] == 'inspect':
            if stage == 'wrong_memory': actual['Memory'] = 8 * 1024**3
            return SimpleNamespace(returncode=1 if stage=='inspect_fail' else 0, stdout=json.dumps(actual), stderr='unit failure')
        return SimpleNamespace(returncode=1 if command[1]=='start' and stage=='start_fail' else 0, stdout='', stderr='unit failure')
    monkeypatch.setattr(recovery.subprocess, 'run', fake)
    result = {'replay': {'nonce': 'b' * 32}}
    if stage == 'okay': recovery._execute_replay(ctx, replay, attempt, result)
    else:
        with pytest.raises(ValueError): recovery._execute_replay(ctx, replay, attempt, result)
    if stage == 'create_fail': assert [c[1] for c in commands] == ['create']
    else: assert commands[-1] == ['docker', 'rm', '--force', owned]
    if stage in ('inspect_fail', 'wrong_memory'): assert not any(c[1] == 'start' for c in commands)
    if stage == 'okay': assert result['replay']['actual_resources_verified'] is True


def test_bare_verified_or_wrong_revision_cannot_become_a_witness(tmp_path, kernel):
    ctx = _ctx(tmp_path, kernel)
    assert recovery.valid_scaled_capital_recovery_witness(ctx, {'verified': True}) is False
    assert recovery.valid_scaled_capital_recovery_witness(ctx, {'verified': True, 'task_revision_hash': 'wrong',
        'usage_calls': [], 'usage_attribution': 'not_applicable_programmatic'}) is False


def test_failed_replay_attempts_are_immutable_public_only_and_keep_session(tmp_path, kernel, public, monkeypatch):
    """Exercise the real node up to a mocked failed replay, without Docker/LO."""
    context = _ctx(tmp_path, kernel)
    session = object()
    context.data.update(input=public[0], goal=tmp_path / 'private_goal_not_mounted.xlsx',
        instruction=public[1].read_text(), public_profile={}, _scaled_admission_session=session,
        finance_evidence={'financial_seed_verified': True, 'audited_source_binding': {'test_fixture_only': True}})
    context.engine = SimpleNamespace(recalculate=lambda *a: pytest.fail('A failed replay must not call LO'))
    (tmp_path / 'private').mkdir()
    def save(name, value): (tmp_path / 'private' / name).write_text(json.dumps(value))
    context.save = save
    def sourceproof(value, *, session=None):
        assert value == {'test_fixture_only': True} and session is context.data['_scaled_admission_session']
        return {'runtime_profile': context.config[recovery.SETTING]['runtime_profile']}
    monkeypatch.setitem(sys.modules, 'sheets_factory.pipelines.scaled_capital_admission', SimpleNamespace(verify_admitted_proof=sourceproof))
    def failed(ctx, replay, attempt, result):
        assert {p.name for p in replay.iterdir()} == set(recovery.PUBLIC_FILES)
        assert not (replay / 'private_goal_not_mounted.xlsx').exists()
        assert (replay / 'input.xlsx').read_bytes() == public[0].read_bytes()
        raise ValueError('explicit unit replay failure; not a production result')
    monkeypatch.setattr(recovery, '_execute_replay', failed)
    first = recovery.ScaledCapitalAllocationRecoveryNode().execute(context)['recovery']
    assert first['verified'] is False and first['status'] == 'unverified'
    record = Path(first['attempt_record_path']); preserved = record.read_bytes()
    assert hashlib.sha256(preserved).hexdigest() == first['attempt_record_sha256']
    second = recovery.ScaledCapitalAllocationRecoveryNode().execute(context)['recovery']
    assert second['attempt_id'] != first['attempt_id'] and second['verified'] is False
    assert record.read_bytes() == preserved and (record.stat().st_mode & 0o222) == 0
    assert first['compiler']['independent_second_search_claimed'] is False


def test_outer_immutable_witness_binding_and_full_D_gate(tmp_path, kernel, monkeypatch):
    """The inner resource/program gate is an explicit stub in this unit test."""
    from sheets_factory.evaluation import streaming_delta
    ctx = _ctx(tmp_path, kernel)
    (tmp_path / 'private/recovery_attempts/attempt_000000').mkdir(parents=True)
    work = tmp_path / 'work'; work.mkdir(); replay = tmp_path / 'replay'; replay.mkdir()
    attempt = tmp_path / 'private/recovery_attempts/attempt_000000'
    for directory, names in [(work, ['input.xlsx', 'instruction.md', 'public_profile.json', 'recovery.py']),
                             (replay, ['input.xlsx', 'recovery.py', 'output.xlsx']),
                             (attempt, ['recovered.xlsx']), (tmp_path / 'private', ['recovered.xlsx'])]:
        for name in names: (directory / name).write_bytes(b'explicit unit artifact, not an actual workbook')
    ctx.data.update(input=work / 'input.xlsx', goal=tmp_path / 'unit_goal.xlsx')
    comparison = {'reward': 1, 'expected_changes': ['unit!A1'], 'test_fixture_only': True}
    candidate = {'verified': True, 'task_revision_hash': ctx.data['revision_hash'], 'usage_calls': [],
        'usage_attribution': 'not_applicable_programmatic', 'workspace': str(work),
        'replay': {'directory': str(replay)}, 'attempt_record_path': str(attempt / 'attempt.json'),
        'witness_binding': {'explicit_inner_gate_stub': True}, 'comparison': comparison}
    raw = json.dumps(candidate).encode(); (attempt / 'attempt.json').write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest(); (attempt / 'attempt.sha256').write_text(sha + '\n')
    candidate['attempt_record_sha256'] = sha
    monkeypatch.setattr(recovery, '_public_execution_valid', lambda *a: True)
    monkeypatch.setattr(recovery, '_witness_binding', lambda *a: {'explicit_inner_gate_stub': True})
    monkeypatch.setattr(streaming_delta, 'compare_workbooks', lambda *a: comparison)
    assert recovery.valid_scaled_capital_recovery_witness(ctx, candidate) is True
    (tmp_path / 'private/recovered.xlsx').write_bytes(b'changed artifact')
    assert recovery.valid_scaled_capital_recovery_witness(ctx, candidate) is False
    (tmp_path / 'private/recovered.xlsx').write_bytes((attempt / 'recovered.xlsx').read_bytes())
    monkeypatch.setattr(streaming_delta, 'compare_workbooks', lambda *a: {**comparison, 'reward': 0})
    assert recovery.valid_scaled_capital_recovery_witness(ctx, candidate) is False


def test_no_opt_in_delegates_to_the_original_recovery_node(monkeypatch):
    marker = {'ordinary_recovery': True}
    monkeypatch.setattr(recovery.RecoveryNode, 'execute', lambda self, ctx: marker)
    assert recovery.ScaledCapitalAllocationRecoveryNode().execute(SimpleNamespace(config={})) is marker


def test_failed_explicit_compilation_preserves_attempt_and_never_publishes_receipt(tmp_path, monkeypatch):
    commands = []
    def fake(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0 if '--version' in command else 1, stdout='test compiler', stderr='test compile failure')
    monkeypatch.setattr(recovery.subprocess, 'run', fake)
    directory = tmp_path / 'failed_public_code'
    with pytest.raises(ValueError, match='compilation failed'): recovery.prepare_public_kernel(directory)
    assert len(commands) == 2 and '--version' in commands[0] and '-static' in commands[1]
    assert (directory / 'started.json').is_file() and (directory / 'failed.json').is_file()
    assert (directory / 'compile.stderr').read_text() == 'test compile failure'
    assert not (directory / 'receipt.json').exists()


def test_resource_ownership_helpers_are_AST_identical_to_frozen_reviewed_upstream():
    assert recovery._sha(upstream.__file__) == recovery.RESOURCE_HELPER_SHA256
    for name in ('_host_resources_valid', '_execute_replay'):
        assert ast.dump(ast.parse(inspect.getsource(getattr(recovery, name))), include_attributes=False) == ast.dump(
            ast.parse(inspect.getsource(getattr(upstream, name))), include_attributes=False)


def test_all_startup_and_nested_global_names_are_bound():
    import builtins
    def check(code):
        for instruction in dis.get_instructions(code):
            if instruction.opname == 'LOAD_GLOBAL':
                assert instruction.argval in vars(recovery) or hasattr(builtins, instruction.argval), instruction.argval
        for child in code.co_consts:
            if inspect.iscode(child): check(child)
    for value in vars(recovery).values():
        if inspect.isfunction(value) and value.__module__ == recovery.__name__: check(inspect.unwrap(value).__code__)
    check(recovery.ScaledCapitalAllocationRecoveryNode.execute.__code__)
