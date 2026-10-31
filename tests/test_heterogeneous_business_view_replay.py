"""Tiny host import/finance tests and mocked isolation; no Docker/LO/models."""
import ast
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import openpyxl
import pytest

from sheets_factory.workbook import heterogeneous_business_view_replay as replay
from sheets_factory.workbook.heterogeneous_contracts import validate
from sheets_factory.workbook import resource_engine


ROOT = Path(__file__).resolve().parents[1]
fixture_loader = importlib.util.spec_from_file_location('public_table_fixture_for_business_replay',
    ROOT / 'tests/test_heterogeneous_financial_view_public_recovery.py')
fixture = importlib.util.module_from_spec(fixture_loader)
fixture_loader.loader.exec_module(fixture)


def public_book(path, version=2):
    book = fixture.public_book()
    try:
        if version == 3:
            names = {replay.original._label(field) for field in replay._V3_EXCLUDED}
            for sheet in book:
                if sheet.title.startswith('S01 '):
                    for row in range(sheet.max_row, 3, -1):
                        if sheet.cell(row, 1).value == 'E01' and sheet.cell(row, 3).value in names:
                            sheet.delete_rows(row)
        book.save(path)
    finally:
        book.close()
    return path


def profile():
    return resource_engine.load_runtime_profile(ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml')


def context(tmp_path, version=2):
    revision = tmp_path / 'task/revisions/000'
    (revision / 'private').mkdir(parents=True)
    source = public_book(revision / 'input.xlsx', version)
    goal = revision / 'goal.xlsx'
    replay._scoped(version).recover_public(source, goal)
    setting = {'version': 1, 'enabled': True, 'view_version': version,
        'view_module': replay.reference(ROOT / f'src/sheets_factory/task_adapters/heterogeneous_financial_view_v{version}.py'),
        'runtime_profile': replay.reference(ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'),
        'recovery': replay.reference(replay.__file__),
        'excluded_entity_fields': ['cure_open', 'cure_next'] + (list(replay._V3_EXCLUDED) if version == 3 else [])}
    ctx = SimpleNamespace(task_id='UNIT-business', revision=0, revision_dir=revision,
        config={replay.SETTING: setting, 'reference_policy': 'independent_public_recovery',
            'recovery': {'compiler_backend': replay.BACKEND, 'replay_timeout_seconds': 7200}},
        data={'input': source, 'goal': goal, 'instruction': 'Complete the supplied financial business forecasts.',
            'revision_hash': 'UNIT-current-revision', 'public_profile': {},
            'finance_evidence': {'financial_seed_verified': True}})
    ctx.save = lambda name, value: (revision / 'private' / name).write_text(json.dumps(value))
    return ctx


def actual_shape(directory, cid='a' * 64, *, exited=False):
    return {'Id': cid, 'Image': replay.IMAGE, 'NanoCpus': 2 * 10**9,
        'Memory': 32 * 1024**3, 'PidsLimit': 256, 'NetworkMode': 'none', 'Privileged': False,
        'CapDrop': ['ALL'], 'CapAdd': ['CAP_DAC_OVERRIDE'], 'SecurityOpt': ['no-new-privileges'],
        'User': '0', 'Entrypoint': ['/usr/bin/python3'], 'Cmd': ['/app/run.py'], 'WorkingDir': '/app',
        'Mounts': [{'Type': 'bind', 'RW': True, 'Source': str(directory.resolve()), 'Destination': '/app'}],
        'State': {'Status': 'exited' if exited else 'created', 'ExitCode': 0, 'OOMKilled': False}}


@pytest.mark.parametrize('version', [2, 3])
def test_scoped_parser_ast_has_only_the_allowed_complete_field_exclusions(version):
    original = ast.parse(Path(replay.original.__file__).read_text())
    scoped = ast.parse(replay.scoped_public_source(version))
    if version == 3:
        selector = next(n for n in scoped.body if isinstance(n, ast.FunctionDef) and n.name == 'public_forecast_slots')
        changed = [n for n in ast.walk(selector) if isinstance(n, ast.Tuple)
            and all(isinstance(x, ast.Constant) for x in n.elts)
            and tuple(x.value for x in n.elts) == replay._BASE_EXCLUDED + replay._V3_EXCLUDED]
        assert len(changed) == 1
        changed[0].elts = changed[0].elts[:-2]
    assert ast.dump(scoped, include_attributes=False) == ast.dump(original, include_attributes=False)


@pytest.mark.parametrize('version', [2, 3])
def test_exact_eight_file_namespace_bundle_really_imports_in_a_fresh_host_process(tmp_path, version):
    source = public_book(tmp_path / 'input.xlsx', version)
    work = tmp_path / 'public'
    initial = replay.prepare_public_bundle(source, 'Complete business forecasts.', work, view_version=version, nonce='1' * 32)
    assert set(initial) == set(replay.PUBLIC_FILES) and len(initial) == 8
    assert not (work / 'public_recovery/heterogeneous_contracts/__init__.py').exists()
    env = dict(os.environ, PYTHONPATH='', PYTHONDONTWRITEBYTECODE='1')
    completed = subprocess.run([sys.executable, '-E', '-s', 'run.py'], cwd=work, env=env,
        capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    after = replay.inventory(work)
    assert set(after) == set(initial) | set(replay.GENERATED_FILES)
    assert all(after[name] == record for name, record in initial.items())
    report = json.loads((work / 'public_recovery_report.json').read_text())
    audit = replay.audit_public_output(source, work / 'recovered.xlsx', view_version=version)
    assert audit['passed'] and audit['all_labelled_business_slots_checked']
    assert audit['business_slots'] == report['declared_business_slots']
    assert audit['numeric_values_checked'] + audit['intentional_policy_blanks_checked'] == audit['business_slots']
    assert report['actual_isolated_replay_executed'] is False  # host test is not a container witness
    assert report['physical_public_only_mount_isolation_verified'] is False
    assert report['third_independent_financial_implementation'] is False
    assert audit['formula_targets_claimed'] is False
    # A hand-computable ACT/360 posting: GBP12 * 100% *31/360 = GBP1.03.
    book = openpyxl.load_workbook(work / 'recovered.xlsx')
    try:
        row = next(r for r in book['S01 Debt'].iter_rows() if r[0].value == 'L01' and r[2].value == 'Interest accrual')
        assert row[4].value == 1.03
    finally:
        book.close()


def test_v3_scope_removes_exactly_two_entity_fields_per_month_and_v2_refuses_missing_rows(tmp_path):
    a, b = public_book(tmp_path / 'v2.xlsx', 2), public_book(tmp_path / 'v3.xlsx', 3)
    parser2, parser3 = replay._scoped(2), replay._scoped(3)
    first, second = openpyxl.load_workbook(a), openpyxl.load_workbook(b)
    try:
        public = parser2._parse_book(first)
        before = parser2.public_forecast_slots(first, public)
        after = parser3.public_forecast_slots(second, public)
        assert len(before) - len(after) == 2 * len(public['months']) * len(public['entities'])
        assert not any(slot['field'] in replay._V3_EXCLUDED for slot in after if slot['domain'] == 'entities')
        assert not any(slot['field'] in ('cure_open', 'cure_next') for slot in before)
        with pytest.raises(ValueError, match='account set is missing'):
            parser2.public_forecast_slots(second, public)
    finally:
        first.close(); second.close()


@pytest.mark.parametrize('version', [True, 1, 4, None])
def test_unknown_or_boolean_scope_is_rejected_without_execution(version):
    with pytest.raises(ValueError):
        replay.public_program_files(version)


def test_bundle_cannot_embed_private_objects_and_refuses_reuse_or_symlink(tmp_path):
    source = public_book(tmp_path / 'input.xlsx')
    work = tmp_path / 'public'
    replay.prepare_public_bundle(source, 'Public instructions.', work, view_version=2, nonce='2' * 32)
    with pytest.raises(ValueError, match='fresh'):
        replay.prepare_public_bundle(source, 'Public instructions.', work, view_version=2, nonce='3' * 32)
    (work / 'hidden_goal.xlsx').symlink_to(source)
    with pytest.raises(ValueError, match='symlink'):
        replay.inventory(work)
    for content in replay.public_program_files(3).values():
        assert b'c597eef2c6a4' not in content and b'source_manifest.json' not in content
    tree = ast.parse(replay.scoped_public_source(3))
    assert not any(isinstance(n, ast.ImportFrom) and any(x in (n.module or '') for x in ('emitter', 'validate', 'task_adapters')) for n in ast.walk(tree))


@pytest.mark.parametrize('change', ['answer', 'provided', 'extra', 'formula', 'omitted'])
def test_literal_audit_rejects_wrong_values_scope_and_provided_changes(tmp_path, change):
    source = public_book(tmp_path / 'input.xlsx', 3)
    output = tmp_path / 'output.xlsx'
    replay._scoped(3).recover_public(source, output)
    book = openpyxl.load_workbook(output)
    try:
        row = next(r for r in book['S01 Debt'].iter_rows() if r[0].value == 'L01' and r[2].value == 'Interest accrual')
        if change == 'answer': row[4].value = 999
        elif change == 'provided': book['Opening Balances']['B2'] = 999
        elif change == 'extra': book['Contract Notes']['Z999'] = 'unrelated change'
        elif change == 'formula': row[4].value = '=1.03'
        elif change == 'omitted': book['S01 Debt'].delete_rows(row[0].row)
        book.save(output)
    finally:
        book.close()
    with pytest.raises(ValueError):
        replay.audit_public_output(source, output, view_version=3)


@pytest.mark.parametrize('field,value', [('NanoCpus', 10**9), ('Memory', 8*1024**3), ('PidsLimit', 0),
    ('Image', 'sha256:'+'0'*64), ('NetworkMode', 'default'), ('Privileged', True), ('User', '1000'),
    ('CapDrop', []), ('CapAdd', []), ('SecurityOpt', []), ('Entrypoint', []), ('Cmd', []), ('Mounts', [])])
def test_actual_resource_or_isolation_mismatch_is_never_accepted(tmp_path, field, value):
    actual = actual_shape(tmp_path)
    assert replay._host_valid(actual, 'a'*64, tmp_path, profile())
    actual[field] = value
    assert not replay._host_valid(actual, 'a'*64, tmp_path, profile())


def test_create_failure_never_starts_or_removes_an_unowned_container(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    work = tmp_path / 'public'; work.mkdir()
    attempt = tmp_path / 'attempt'; attempt.mkdir()
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        assert args[:2] == ['docker', 'create']
        return SimpleNamespace(returncode=1, stdout='', stderr='UNIT name conflict')
    monkeypatch.setattr(replay.subprocess, 'run', command)
    result = {'replay': {'nonce': '4'*32, 'initial_files': {}}}
    with pytest.raises(ValueError, match='owned container'):
        replay._execute_replay(ctx, work, attempt, result)
    assert len(calls) == 1 and result['replay']['cleanup_skipped_no_owned_container'] is True
    assert (attempt / 'replay_terminal.json').is_file()


def test_owned_container_is_cleaned_when_prestart_inspection_fails(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    work = tmp_path / 'public'; work.mkdir()
    attempt = tmp_path / 'attempt'; attempt.mkdir()
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        if args[1] == 'create': return SimpleNamespace(returncode=0, stdout='a'*64+'\n', stderr='')
        if args[1] == 'inspect':
            actual = actual_shape(work); actual['Memory'] = 8*1024**3
            return SimpleNamespace(returncode=0, stdout=json.dumps(actual), stderr='')
        assert args == ['docker', 'rm', '--force', 'a'*64]
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(replay.subprocess, 'run', command)
    with pytest.raises(ValueError, match='isolation differ'):
        replay._execute_replay(ctx, work, attempt, {'replay': {'nonce': '4'*32, 'initial_files': {}}})
    assert [c[1] for c in calls] == ['create', 'inspect', 'rm']


@pytest.mark.parametrize('outcome', ['success', 'timeout', 'bad_exit', 'extra_file', 'changed_input'])
def test_owned_runtime_terminal_exit_and_inventory_guards(tmp_path, monkeypatch, outcome):
    ctx = context(tmp_path, 3)
    work = ctx.revision_dir / ('recovery_replay-' + '5'*32)
    initial = replay.prepare_public_bundle(ctx.data['input'], ctx.data['instruction'], work, view_version=3, nonce='5'*32)
    attempt = tmp_path / 'attempt'; attempt.mkdir()
    result = {'replay': {'nonce':'5'*32, 'initial_files':initial}}
    commands, inspections = [], []
    def command(args, **kwargs):
        commands.append(args)
        if args[1] == 'create': return SimpleNamespace(returncode=0, stdout='a'*64+'\n', stderr='')
        if args[1] == 'inspect':
            actual = actual_shape(work, exited=bool(inspections)); inspections.append(actual)
            if outcome == 'bad_exit' and len(inspections) == 2: actual['State']['ExitCode'] = 1
            return SimpleNamespace(returncode=0, stdout=json.dumps(actual), stderr='')
        if args[1] == 'start':
            assert args == ['docker','start','--attach','a'*64] and kwargs['timeout'] == 7200
            if outcome == 'timeout': raise subprocess.TimeoutExpired(args, 7200)
            replay._scoped(3).recover_public(work/'input.xlsx', work/'recovered.xlsx', work/'public_recovery_report.json',
                instruction_path=work/'instruction.md')
            if outcome == 'extra_file': (work/'private_goal.xlsx').write_bytes(b'UNIT forbidden extra')
            if outcome == 'changed_input':
                with (work/'input.xlsx').open('ab') as stream: stream.write(b'UNIT mutated heldout input')
            return SimpleNamespace(returncode=1 if outcome == 'bad_exit' else 0)
        assert args == ['docker','rm','--force','a'*64]
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(replay.subprocess, 'run', command)
    if outcome == 'success':
        replay._execute_replay(ctx, work, attempt, result)
        assert result['replay']['completed'] is True
        assert len(inspections) == 2
    else:
        with pytest.raises((ValueError, subprocess.TimeoutExpired)):
            replay._execute_replay(ctx, work, attempt, result)
        assert result['replay']['completed'] is False
    assert commands[-1] == ['docker','rm','--force','a'*64]
    assert result['replay']['cleanup'] == {'owned_full_id':'a'*64,'returncode':0}
    assert (attempt/'replay_terminal.json').is_file()
    assert not (ctx.revision_dir/'private/recovered.xlsx').exists()


def mock_replay(ctx, directory, attempt, result):
    """Mock Docker only. Actual public finance is the tiny host implementation."""
    version, _, profile_ref = replay._settings(ctx)
    replay._scoped(version).recover_public(directory / 'input.xlsx', directory / 'recovered.xlsx',
        directory / 'public_recovery_report.json', instruction_path=directory / 'instruction.md')
    report_path = directory / 'public_recovery_report.json'
    report = json.loads(report_path.read_text())
    for field, name in [('input','input.xlsx'), ('instruction','instruction.md'), ('output','recovered.xlsx')]:
        report[field]['path'] = '/app/' + name
    report_path.write_text(json.dumps(report))
    result['replay'].update(command=replay._command(ctx, directory, result['replay']['nonce']),
        runtime_profile=profile_ref, actual_resources_verified=True, container_id='a'*64,
        host_before=replay._write(attempt/'host_before.json', actual_shape(directory)),
        host_after=replay._write(attempt/'host_after.json', actual_shape(directory, exited=True)),
        completed=True, returncode=0, final_files=replay.inventory(directory),
        cleanup={'owned_full_id':'a'*64, 'returncode':0}, operational_timeout_seconds=7200,
        operational_replay_budget_is_solver_tool_budget=False)
    result['replay']['terminal'] = replay._write(attempt/'replay_terminal.json', dict(result['replay']))


class MockEngine:
    def __init__(self, ctx):
        self.ctx, self.records = ctx, []

    def recalculate(self, source, destination):
        shutil.copyfile(source, destination)
        value = profile()
        record = {'kind':'resource_bound_libreoffice_call','version':1,'role':'source',
            'status':'completed','actual_resources_verified':True, 'source':replay.reference(source),
            'output':replay.reference(destination),'destination':str(destination.resolve()),'image_id':replay.IMAGE,
            'implementation':replay.reference(resource_engine.__file__),
            'upstream_engine':replay.reference(resource_engine.original_engine.__file__),
            'profile':self.ctx.config[replay.SETTING]['runtime_profile'],
            'profile_canonical_sha256':resource_engine._canonical(value), 'container_id':'b'*64,
            'requested_resources':value['docker_resources']['source'],'workbook_file_timeout_seconds':600,
            'actual_resources':{'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':256}}
        self.records.append(replay._write(destination.with_suffix('.UNIT-resource.json'), record))
        return destination

    def metadata(self):
        return {'actual_resource_receipts':self.records}


def execute_mock_node(tmp_path, monkeypatch, version=3):
    ctx = context(tmp_path, version)
    monkeypatch.setattr(replay, '_source_binding', lambda context: {'UNIT_mock_admission':True})
    from sheets_factory.nodes import quality
    monkeypatch.setattr(quality, 'validate_reference_policy_selection', lambda _: 'independent_public_recovery')
    monkeypatch.setattr(replay, '_execute_replay', mock_replay)
    ctx.engine = MockEngine(ctx)
    result = replay.HeterogeneousBusinessRecoveryNode().execute(ctx)['recovery']
    assert result['verified'] is True, result
    return ctx, result


@pytest.mark.parametrize('version', [2, 3])
def test_full_node_witness_mocked_runtime_keeps_all_scope_checks_and_no_false_implementation_claims(tmp_path, monkeypatch, version):
    ctx, result = execute_mock_node(tmp_path, monkeypatch, version)
    assert replay.valid_heterogeneous_business_recovery_witness(ctx, result)
    assert result['usage_calls'] == [] and result['usage_attribution'] == 'not_applicable_programmatic'
    assert len(result['resource_recalculations']) == 2
    assert result['compiler']['literal_business_targets'] is True
    assert result['compiler']['shared_Decimal_source_audit_implementation'] is True
    assert result['compiler']['third_independent_financial_implementation'] is False
    saved = replay.HeterogeneousBusinessRecoveryNode().execute(ctx)['recovery']
    assert saved == result and len(list((ctx.revision_dir/'private/recovery_attempts').iterdir())) == 1


@pytest.mark.parametrize('change', ['revision','instruction','input','canonical','attempt','missing_role'])
def test_strict_witness_rejects_current_identity_or_evidence_changes(tmp_path, monkeypatch, change):
    ctx, result = execute_mock_node(tmp_path, monkeypatch)
    if change == 'revision': ctx.data['revision_hash'] = 'another-revision'
    elif change == 'instruction': ctx.data['instruction'] += ' changed'
    elif change == 'input':
        with Path(ctx.data['input']).open('ab') as stream: stream.write(b'UNIT changed bytes')
    elif change == 'canonical':
        with (ctx.revision_dir/'private/recovered.xlsx').open('ab') as stream: stream.write(b'UNIT changed copy')
    elif change == 'attempt': Path(result['attempt_record_path']).chmod(0o600);Path(result['attempt_record_path']).write_text('{}')
    elif change == 'missing_role': Path(result['replay']['host_after']['path']).unlink()
    assert replay.valid_heterogeneous_business_recovery_witness(ctx, result) is False


def test_non_opted_in_family_delegates_original_recovery_node(monkeypatch):
    monkeypatch.setattr(replay.RecoveryNode, 'execute', lambda self,ctx: {'ordinary':'delegated'})
    assert replay.HeterogeneousBusinessRecoveryNode().execute(SimpleNamespace(config={})) == {'ordinary':'delegated'}


@pytest.mark.parametrize('field,value', [('role','verifier'), ('status','failed'), ('version',True),
    ('actual_resources_verified',False), ('image_id','sha256:'+'0'*64)])
def test_recalculation_requires_the_exact_current_source_engine_evidence(tmp_path, field, value):
    ctx = context(tmp_path)
    engine = MockEngine(ctx)
    source = ctx.data['goal']; destination = ctx.revision_dir/'private/recovered.xlsx'
    engine.recalculate(source, destination)
    identity = engine.records[0]
    assert replay._resource_valid(identity,source,destination,profile(),ctx.config[replay.SETTING]['runtime_profile'])
    path = Path(identity['path']); record = json.loads(path.read_text()); record[field] = value
    path.write_text(json.dumps(record))
    assert not replay._resource_valid(replay.reference(path),source,destination,profile(),ctx.config[replay.SETTING]['runtime_profile'])


def test_verified_flag_without_actual_evidence_is_rejected(tmp_path):
    ctx = context(tmp_path)
    assert not replay.valid_heterogeneous_business_recovery_witness(ctx, {'verified':True})


def test_failure_attempts_are_immutable_and_retry_gets_a_new_attempt_without_goal_scoring(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    from sheets_factory.nodes import quality
    from sheets_factory.evaluation import streaming_delta
    monkeypatch.setattr(quality, 'validate_reference_policy_selection', lambda _: 'independent_public_recovery')
    monkeypatch.setattr(replay, '_source_binding', lambda _: {'UNIT_mock_admission':True})
    monkeypatch.setattr(streaming_delta, 'compare_workbooks', lambda *_: pytest.fail('Failed public process was scored'))
    def fail(*_args):
        raise RuntimeError('UNIT public process failed before completion')
    monkeypatch.setattr(replay, '_execute_replay', fail)
    records = []
    for index in range(2):
        result = replay.HeterogeneousBusinessRecoveryNode().execute(ctx)['recovery']
        assert result['verified'] is False and result['status'] == 'unverified'
        assert result['error_type'] == 'RuntimeError'
        assert result['usage_calls'] == []
        assert not replay.valid_heterogeneous_business_recovery_witness(ctx, result)
        record = Path(result['attempt_record_path'])
        assert record.parent.name == f'attempt_{index:06d}' and record.stat().st_mode & 0o222 == 0
        records.append((record, replay.reference(record)))
    assert all(replay.reference(path) == identity for path,identity in records)
    assert not (ctx.revision_dir/'private/recovered.xlsx').exists()
