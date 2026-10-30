"""Public toy replay and explicit resource witnesses. No Docker, LO or model."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest
import yaml

from sheets_factory.workbook import entity_group_public_recovery as recovery
from sheets_factory.workbook.entity_group import excel
from sheets_factory.workbook.entity_group.validate import expected_values
from sheets_factory.workbook.resource_engine import load_runtime_profile

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_entity_public_hand', ROOT / 'tests/test_entity_group_ledger.py')
hand = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hand)


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))


def _synthetic_cache(path, definitions, ledger):
    """Test-only XML cache; this never represents an actual engine receipt."""
    checked = expected_values(definitions['public_spec'], ledger, definitions)
    with ZipFile(path) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    namespace = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    for index, sheet in enumerate(definitions['worksheet_order'], 1):
        name = f'xl/worksheets/sheet{index}.xml'
        root = ET.fromstring(content[name])
        for cell in root.iter(namespace + 'c'):
            key = "'" + sheet.replace("'", "''") + "'!$" + __import__('re').sub(r'([A-Z]+)([0-9]+)', r'\1$\2', cell.attrib['r'])
            if cell.find(namespace + 'f') is None:
                continue
            expected = checked['values'][key]
            for value in list(cell):
                if value.tag in (namespace + 'v', namespace + 'is'):
                    cell.remove(value)
            if type(expected) is str:
                cell.set('t', 'str')
            else:
                cell.attrib.pop('t', None)
            ET.SubElement(cell, namespace + 'v').text = str(expected)
        content[name] = ET.tostring(root)
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name, data in content.items():
            archive.writestr(name, data)


@pytest.fixture
def public(tmp_path):
    spec = hand.specification()
    book = openpyxl.Workbook()
    book.remove(book.active)
    bindings = excel.emit_entity_group_workbook(book, spec)
    target = next(item for item in bindings['formula_bindings'] if item['label'] == 'S01/E02/2024-03-01/current_tax')
    assert book[target['sheet']][target['cell']].data_type == 'f'
    book[target['sheet']][target['cell']] = '=0'
    path = tmp_path / 'input.xlsx'
    book.save(path)
    book.close()
    (tmp_path / 'instruction.md').write_text('Repair the fixed-plan financial formulas under the complete Group Rules.')
    return path, spec, target


def test_public_sorted_json_reconstructs_original_primitive_row_order(public):
    path, spec, _ = public
    book = openpyxl.load_workbook(path)
    try:
        text = ''.join(book['Group Contract'].cell(row, 2).value for row in range(2, book['Group Contract'].max_row + 1))
        assert list(json.loads(text)) != list(spec)
        actual = recovery.read_public_spec(book)
        assert list(actual) == list(spec)
        assert list(actual['entities'][0]) == list(spec['entities'][0])
        assert actual == spec
    finally:
        book.close()


def test_public_recovery_complete_field_audit_and_fixed_plan_without_goal(public, tmp_path):
    source, spec, target = public
    before = source.read_bytes()
    output = tmp_path / 'output.xlsx'
    report = recovery.recover_public(source, output, tmp_path / 'public_recovery_report.json')
    assert source.read_bytes() == before
    assert report['public_information_only'] is True
    assert report['fixed_plan'] == spec['fixed_plan']
    assert report['different_formula_definitions_reconstructed'] == 1
    assert report['independent_field_audit']['all_independent_journal_fields_covered'] is True
    assert report['independent_field_audit']['logical_fields_checked'] == 2376
    assert report['shared_excel_compiler'] is True
    assert report['independent_second_formula_engine'] is False
    assert report['private_goal_source_bindings_or_fault_list_read'] is False
    assert report['actual_LO_cache_audit_pending'] is True
    restored = openpyxl.load_workbook(output)
    try:
        assert restored[target['sheet']][target['cell']].value == target['formula']
    finally:
        restored.close()
    assert not list(tmp_path.glob('**/goal.xlsx'))


@pytest.mark.parametrize('mutation', ['primitive', 'boolean_type', 'rule', 'duplicate_json', 'label', 'formula_literal', 'extra_cell'])
def test_invalid_public_inputs_fail_without_producing_recovery(public, tmp_path, mutation):
    path, _, target = public
    book = openpyxl.load_workbook(path)
    if mutation == 'primitive':
        book['Group Inputs']['B2'] = 'wrong public value'
    elif mutation == 'boolean_type':
        for row in book['Group Inputs']:
            if str(row[0].value).endswith('/opening_trap'):
                row[1].value = False
                break
    elif mutation == 'rule':
        book['Group Rules']['B2'] = 'Different financial phase'
    elif mutation == 'duplicate_json':
        cell = book['Group Contract']['B2']
        cell.value = cell.value.replace('"schema_version":1', '"schema_version":1,"schema_version":1')
    elif mutation == 'label':
        book[target['sheet']].cell(book[target['sheet']][target['cell']].row, 1, 'unlabelled alternate output')
    elif mutation == 'formula_literal':
        book[target['sheet']][target['cell']] = 0
    else:
        book['S01 Close']['Z9999'] = 'unapproved helper'
    book.save(path)
    book.close()
    with pytest.raises(ValueError):
        recovery.recover_public(path, tmp_path / 'output.xlsx')
    assert not (tmp_path / 'output.xlsx').exists()


def test_public_instruction_required_and_input_never_overwritten(public, tmp_path):
    path, _, _ = public
    with pytest.raises(ValueError, match='overwrite'):
        recovery.recover_public(path, path)
    (tmp_path / 'instruction.md').unlink()
    with pytest.raises(ValueError, match='instruction'):
        recovery.recover_public(path, tmp_path / 'output.xlsx')


def test_exact_compiled_public_bundle_runs_isolated_and_contains_no_task_answers(public, tmp_path):
    program = recovery.compile_public_entity_group_recovery()
    assert program == recovery.compile_public_entity_group_recovery()
    assert str(tmp_path) not in program
    script = tmp_path / 'recovery.py'
    script.write_text(program)
    command = [sys.executable, '-I', str(script)]
    completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((tmp_path / 'public_recovery_report.json').read_text())
    assert report['different_formula_definitions_reconstructed'] == 1
    assert report['independent_field_audit']['logical_fields_checked'] == 2376
    assert report['shared_excel_compiler'] is True
    assert (tmp_path / 'output.xlsx').is_file()


def _context(tmp_path, memory_gib=8):
    profile = load_runtime_profile()
    if memory_gib != 8:
        profile['id'] = 'entity_group_large_v2'
        for role in profile['docker_resources'].values():
            role['memory_bytes'] = memory_gib * 1024**3
    profile_path = tmp_path / 'runtime.yaml'
    profile_path.write_text(yaml.safe_dump(profile))
    revision = tmp_path / 'revisions/000'
    (revision / 'private').mkdir(parents=True)
    ctx = SimpleNamespace(revision_dir=revision, task_id='dbg-unit-public-only', revision=0,
        config={'entity_group_task': {'runtime_profile': recovery._reference(profile_path)},
            'recovery': {'compiler_backend': recovery.BACKEND, 'replay_timeout_seconds': 7200},
            'diagnosis': {'reference_evidence_policy': 'independent_public_recovery'}}, data={})
    def save(name, value):
        _write(revision / 'private' / name, value)
    ctx.save = save
    return ctx, profile


def _host(profile, replay, container='a' * 64):
    r = profile['docker_resources']['agent']
    return {'Id': container, 'Image': profile['image']['id'], 'NanoCpus': r['cpus'] * 10**9,
        'Memory': r['memory_bytes'], 'PidsLimit': r['pids_limit'], 'NetworkMode': 'none',
        'Cmd': ['/workspace/recovery.py'], 'Entrypoint': ['/usr/bin/python3'], 'WorkingDir': '/workspace', 'User': '0',
        'Mounts': [{'Type': 'bind', 'RW': True, 'Source': str(replay.resolve()), 'Destination': '/workspace'}]}


@pytest.mark.parametrize('memory_gib', [8, 32])
def test_explicit_profile_dynamically_controls_replay_and_actual_hostconfig(tmp_path, memory_gib):
    ctx, profile = _context(tmp_path, memory_gib)
    replay = ctx.revision_dir / 'replay'
    replay.mkdir()
    command = recovery._replay_command(ctx, replay, 'b' * 32)
    assert command[command.index('--cpus') + 1] == '2'
    assert command[command.index('--memory') + 1] == str(memory_gib * 1024**3)
    assert command[command.index('--network') + 1] == 'none'
    assert command[-2] == profile['image']['id']
    assert recovery._host_resources_valid(_host(profile, replay), profile, replay, 'a' * 64)
    wrong = _host(profile, replay)
    wrong['Memory'] = 2 * 1024**3
    assert not recovery._host_resources_valid(wrong, profile, replay, 'a' * 64)
    assert profile['solver_tool_budget']['seconds'] == 1800


@pytest.mark.parametrize('change', ['memory', 'network', 'private_mount', 'image', 'fractional_cpu'])
def test_actual_container_mismatch_rejected(tmp_path, change):
    ctx, profile = _context(tmp_path)
    replay = ctx.revision_dir / 'replay'
    actual = _host(profile, replay)
    if change == 'private_mount':
        actual['Mounts'].append({'Type': 'bind', 'Source': '/private', 'Destination': '/private', 'RW': False})
    else:
        key, value = {'memory': ('Memory', 2 * 1024**3), 'network': ('NetworkMode', 'bridge'),
                      'image': ('Image', 'sha256:' + 'b' * 64), 'fractional_cpu': ('NanoCpus', 2e9)}[change]
        actual[key] = value
    assert not recovery._host_resources_valid(actual, profile, replay, 'a' * 64)


@pytest.mark.parametrize('failure', [None, 'resource_mismatch', 'timeout'])
def test_replay_inspects_before_start_and_always_cleans_owned_container(tmp_path, monkeypatch, failure):
    ctx, profile = _context(tmp_path, 32)
    replay, attempt = ctx.revision_dir / 'replay', ctx.revision_dir / 'private/attempt'
    replay.mkdir(); attempt.mkdir()
    result = {'replay': {'nonce': 'b' * 32}}
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['capture_output'] and kwargs['text']
        if command[:2] == ['docker', 'create']:
            return SimpleNamespace(returncode=0, stdout='a' * 64 + '\n', stderr='')
        if command[:2] == ['docker', 'inspect']:
            host = _host(profile, replay)
            if failure == 'resource_mismatch':
                host['Memory'] = 2 * 1024**3
            return SimpleNamespace(returncode=0, stdout=json.dumps(host), stderr='')
        if command[:2] == ['docker', 'start']:
            assert kwargs['timeout'] == 7200
            if failure == 'timeout':
                raise subprocess.TimeoutExpired(command, 7200, output=b'partial result', stderr=b'partial error')
            return SimpleNamespace(returncode=0, stdout='public complete', stderr='')
        assert command[:3] == ['docker', 'rm', '--force']
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(recovery.subprocess, 'run', run)
    if failure:
        with pytest.raises(subprocess.TimeoutExpired if failure == 'timeout' else ValueError):
            recovery._execute_replay(ctx, replay, attempt, result)
    else:
        recovery._execute_replay(ctx, replay, attempt, result)
        assert result['replay']['actual_resources_verified'] is True
    assert calls[-1][:3] == ['docker', 'rm', '--force']
    assert calls[-1][-1] == 'a' * 64  # only the returned, owned full ID
    if failure == 'resource_mismatch':
        assert not any(command[:2] == ['docker', 'start'] for command in calls)
    if failure == 'timeout':
        assert (attempt / 'replay.stdout.txt').read_text() == 'partial result'
        assert (attempt / 'replay.stderr.txt').read_text() == 'partial error'


@pytest.mark.parametrize('failure', ['name_conflict', 'untrusted_id'])
def test_failed_create_never_removes_an_unowned_container(tmp_path, monkeypatch, failure):
    ctx, _ = _context(tmp_path)
    replay, attempt = ctx.revision_dir / 'replay', ctx.revision_dir / 'private/attempt'
    replay.mkdir(); attempt.mkdir()
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert command[:2] == ['docker', 'create'], 'No inspect/start/rm without established ownership'
        return SimpleNamespace(returncode=1 if failure == 'name_conflict' else 0,
            stdout='' if failure == 'name_conflict' else 'not-a-full-id', stderr='existing name conflict')
    monkeypatch.setattr(recovery.subprocess, 'run', run)
    result = {'replay': {'nonce': 'b' * 32}}
    with pytest.raises(ValueError):
        recovery._execute_replay(ctx, replay, attempt, result)
    assert len(calls) == 1
    assert result['replay']['cleanup_skipped_no_owned_container'] is True


def _fake_resource_replay(ctx, replay, attempt, result):
    """Explicit test double; creates only public toy outputs, never a container."""
    assert {file.name for file in replay.iterdir()} == set(recovery.PUBLIC_FILES)
    recovery.recover_public(replay / 'input.xlsx', replay / 'output.xlsx', replay / 'public_recovery_report.json',
                           instruction_path=replay / 'instruction.md')
    profile, profile_binding = recovery._profile(ctx)
    _write(attempt / 'replay_host_config.json', _host(profile, replay))
    result['replay'].update(command=recovery._replay_command(ctx, replay, result['replay']['nonce']),
        returncode=0, actual_resources_verified=True, runtime_profile=profile_binding,
        container_id='a' * 64, cleanup_returncode=0,
        host_config=recovery._reference(attempt / 'replay_host_config.json'))


@pytest.fixture
def witnessed(public, tmp_path, monkeypatch):
    source, _, _ = public
    ctx, profile = _context(tmp_path, 32)
    ctx.data.update(input=source, instruction=(tmp_path / 'instruction.md').read_text(),
        revision_hash='c' * 64, public_profile={}, finance_evidence={'financial_seed_verified': True,
            'audited_source_binding': {'test_double': True}})
    # The private goal exists only outside the replay and is never consumed by
    # public recovery. Its synthetic caches are unit fixtures, not LO evidence.
    reference_dir = tmp_path / 'private_test_reference'
    reference_dir.mkdir()
    recovery.recover_public(source, reference_dir / 'goal.xlsx', instruction_path=tmp_path / 'instruction.md')
    definitions = json.loads((reference_dir / 'public_definitions.json').read_text())
    ledger = json.loads((reference_dir / 'public_forward_ledger.json').read_text())
    _synthetic_cache(reference_dir / 'goal.xlsx', definitions, ledger)
    ctx.data['goal'] = reference_dir / 'goal.xlsx'
    monkeypatch.setattr(recovery, '_execute_replay', _fake_resource_replay)
    from sheets_factory.pipelines import entity_group_admission
    monkeypatch.setattr(entity_group_admission, 'verify_admitted_proof',
        lambda value: {'runtime_profile': ctx.config['entity_group_task']['runtime_profile']})
    receipts = []
    class Engine:
        def recalculate(self, raw, output):
            output.write_bytes(raw.read_bytes())
            local_defs = json.loads(raw.with_name('public_definitions.json').read_text())
            local_ledger = json.loads(raw.with_name('public_forward_ledger.json').read_text())
            _synthetic_cache(output, local_defs, local_ledger)
            r = profile['docker_resources']['source']
            record = {'test_double': True, 'status': 'completed', 'actual_resources_verified': True,
                'source': recovery._reference(raw), 'output': recovery._reference(output),
                'profile': ctx.config['entity_group_task']['runtime_profile'],
                'profile_canonical_sha256': hashlib.sha256(json.dumps(profile, sort_keys=True,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                'requested_resources': r, 'image_id': profile['image']['id'], 'workbook_file_timeout_seconds': 600,
                'actual_resources': {'cpus_nanoseconds': r['cpus'] * 10**9, 'memory_bytes': r['memory_bytes'], 'pids_limit': r['pids_limit']}}
            from sheets_factory.workbook import resource_engine
            record['implementation'] = recovery._reference(resource_engine.__file__)
            path = output.with_name('test_double_resource.json')
            _write(path, record)
            receipts.append(recovery._reference(path))
            return output
        def metadata(self):
            return {'actual_resource_receipts': receipts}
    ctx.engine = Engine()
    result = recovery.EntityGroupRecoveryNode().execute(ctx)['recovery']
    assert result['verified'] is True, result.get('error')
    assert recovery.valid_entity_group_recovery_witness(ctx, result)
    return ctx, result


def test_complete_node_witness_is_bound_immutable_and_reusable(witnessed):
    ctx, result = witnessed
    assert result['compiler']['shared_excel_compiler'] is True
    assert result['compiler']['independent_second_formula_engine'] is False
    assert result['usage_calls'] == [] and result['usage_attribution'] == 'not_applicable_programmatic'
    assert Path(result['attempt_record_path']).stat().st_mode & 0o222 == 0
    assert result['replay_timeout_seconds'] == 7200
    assert recovery.EntityGroupRecoveryNode().execute(ctx)['recovery'] == result


@pytest.mark.parametrize('mutation', ['verified_only', 'program', 'nonce', 'instruction', 'goal', 'resource', 'record'])
def test_witness_never_accepts_boolean_or_changed_artifacts(witnessed, mutation):
    ctx, result = witnessed
    result = deepcopy(result)
    if mutation == 'verified_only':
        result = {'verified': True}
    elif mutation == 'program':
        Path(result['replay']['directory'], 'recovery.py').write_text('print("invented answer")')
    elif mutation == 'nonce':
        Path(result['replay']['directory'], 'public_nonce.txt').write_text('other nonce')
    elif mutation == 'instruction':
        ctx.data['instruction'] += ' changed after execution'
    elif mutation == 'goal':
        ctx.data['goal'] = ctx.data['input']
    elif mutation == 'resource':
        path = Path(result['resource_recalculation']['path'])
        record = json.loads(path.read_text())
        record['actual_resources']['memory_bytes'] = 2 * 1024**3
        _write(path, record)
    else:
        Path(result['attempt_record_path']).chmod(0o644)
        Path(result['attempt_record_path']).write_text('{}')
    assert not recovery.valid_entity_group_recovery_witness(ctx, result)


def test_failure_keeps_fresh_immutable_attempt_and_next_retry_history(public, tmp_path, monkeypatch):
    path, _, _ = public
    ctx, _ = _context(tmp_path)
    ctx.data.update(input=path, instruction='Public repair', revision_hash='d' * 64,
        public_profile={}, finance_evidence={'financial_seed_verified': True, 'audited_source_binding': {}})
    from sheets_factory.pipelines import entity_group_admission
    monkeypatch.setattr(entity_group_admission, 'verify_admitted_proof',
        lambda value: {'runtime_profile': ctx.config['entity_group_task']['runtime_profile']})
    def failure(*args):
        raise subprocess.TimeoutExpired('unit-only Docker stub', 7200)
    monkeypatch.setattr(recovery, '_execute_replay', failure)
    first = recovery.EntityGroupRecoveryNode().execute(ctx)['recovery']
    original = Path(first['attempt_record_path']).read_bytes()
    second = recovery.EntityGroupRecoveryNode().execute(ctx)['recovery']
    assert first['verified'] is False and first['error_type'] == 'TimeoutExpired'
    assert second['attempt_id'] != first['attempt_id']
    assert Path(first['attempt_record_path']).read_bytes() == original
    assert not recovery.valid_entity_group_recovery_witness(ctx, first)
