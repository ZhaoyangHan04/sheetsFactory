"""Opaque reuse and unchanged complete protocols; all financial/engine calls mocked."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from types import FunctionType, SimpleNamespace

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    descriptor = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(descriptor)
    descriptor.loader.exec_module(module)
    return module


entry = load(ROOT/'scripts/prepare_linear_capital_scaled_cached_view_pair.py', '_cached_pair_tests')
pool_fixture = load(ROOT/'tests/test_linear_capital_scaled_pool_view_pair.py', '_cached_pool_fixture')
dump = pool_fixture.base_tests.dump


def book(path, values):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Model'
    sheet['A1'] = 'Provided business title / GBP pence'
    for name, value in values.items():
        sheet[name] = value
    workbook.save(path)
    workbook.close()
    return entry.quality.reference(path)


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    root, manifest, source, events, state, config, select = pool_fixture.boundary.__wrapped__(tmp_path, monkeypatch)
    select('L360-P01')
    source['workbook'] = book(root/'source.xlsx', {'A2': 20, 'A3': 30, 'A4': 40, 'B2': 1})
    source['bindings'] = dump(root/'bindings.json', {'specification_sha256': 's'*64})
    recipe = root/'explicit_mock_financial_recipe.py'
    recipe.write_text('# Explicit unit financial boundary, never executed.\n')
    source['source_recipe_sha256'] = {str(recipe): entry.quality.reference(recipe)['sha256']}
    manifest.clear()
    manifest.update(dump(root/'source_manifest.json', source))
    helper = pool_fixture.entry.support('source')
    real_load = entry.quality.SourceProviders.load
    def provider(self, identity):
        row, _ = real_load(self, identity)
        return row, helper  # Explicit mocked financial provider; real opaque admission/guards.
    monkeypatch.setattr(entry.quality.SourceProviders, 'load', provider)
    entry._SESSIONS.clear()
    session = entry.PairSession(manifest)
    pair = session.pair.prepare.__globals__
    validator = session.validator.prepare.__globals__
    pair['policy'] = pool_fixture.entry.policy
    class Dashboard:
        def __init__(self, *args, **kwargs):
            events.append('dashboard_created')
        def start(self):
            events.append('dashboard_started')
            return 'mock://no-http-service'
        def stop(self):
            events.append('dashboard_stopped')
    pair['DashboardServer'] = validator['DashboardServer'] = Dashboard
    calls = []
    class Engine:
        def __init__(self, *args, receipt_directory, **kwargs):
            self.directory = Path(receipt_directory)
            self.directory.mkdir()
            self.history = []
        def ensure_image(self):
            return 'TEST_MOCK_NO_DOCKER'
        def recalculate(self, original, destination):
            if state.get('failure') == 'engine':
                raise ValueError('Explicit unit engine failure; no actual LO')
            calls.append(Path(destination).stem)
            before = helper.reference(original)
            workbook = openpyxl.load_workbook(original)
            for sheet in workbook:
                for row in sheet:
                    for cell in row:
                        if cell.data_type == 'f':
                            terms = cell.value[1:].split('+')
                            assert all(value.isdigit() for value in terms)
                            cell.value = sum(map(int, terms))
            workbook.save(destination)
            workbook.close()
            if state.get('failure') == 'mutate_source':
                Path(source['bindings']['path']).write_text('{}')
            self.history.append(dump(self.directory/(str(len(self.history))+'.json'),
                {'kind': 'TEST_MOCK_NO_ACTUAL_LO', 'input': before, 'output': helper.reference(destination)}))
            return Path(destination)
        def metadata(self):
            return {'actual_resource_receipts': self.history}
    def actual(call, terminal, frozen):
        value = helper.read(terminal)
        helper.require(value['kind'] == 'TEST_MOCK_NO_ACTUAL_LO'
            and value['input'] == call['input'] and value['output'] == call['output'], 'Mock resource binding changed')
        return {'terminal': terminal, 'test_mock_no_actual_resources': True}
    monkeypatch.setattr(helper, 'ResourceLibreOfficeEngine', Engine)
    monkeypatch.setattr(helper, 'validate_actual_call', actual)
    monkeypatch.setattr(entry.quality, 'DEFAULT_PROVIDERS', entry.quality.DEFAULT_PROVIDERS)
    # The complete source financial and task-plan compiler boundaries are mocks.
    # The frozen _view, role inventory, value comparisons, controls and terminals run.
    def check_plan(plan):
        helper.require(plan['source'] == source['workbook'], 'Wrong unit plan source')
    monkeypatch.setattr(pair['task_views'], '_check_plan', check_plan)
    def plan(source_path, specification, bindings, *, mode):
        assert source_path == source['workbook']['path']
        assert specification == source['public_specification']['path'] and bindings == source['bindings']['path']
        events.append('plan_'+mode)
        return {'source': source['workbook'], 'mode': mode}
    def materialize(initial, destination):
        mode = initial['mode']
        events.append('materialize_'+mode)
        folder = Path(destination)
        folder.mkdir(parents=True)
        instruction = 'Complete the business model; retain all provided facts.\n'
        brief = folder/'instruction.md'
        brief.write_text(instruction)
        goal = folder/'goal.xlsx'
        goal.write_bytes(Path(source['workbook']['path']).read_bytes())
        families, temporary = {}, None
        if mode == 'financial_modeling':
            public = book(folder/'input.xlsx', {'A2': None, 'A3': None, 'A4': None, 'B2': None})
            targets = [{'sheet': 'Model', 'cell': name} for name in ('A2', 'A3', 'A4', 'B2')]
            edits = []
        else:
            public = book(folder/'input.xlsx', {'A2': 25, 'A3': 37, 'A4': 49, 'B2': 0})
            targets, edits = [], [{'sheet': 'Model', 'cell': name} for name in ('A2', 'A3', 'A4')]
            temporary = book(folder/'same_plan.xlsx', {'A2': 20, 'A3': 30, 'A4': 40, 'B2': 0})
            for name, cell, wrong in zip(pair['task_views'].FAMILIES, ('A2', 'A3', 'A4'), (25, 37, 49)):
                values = {'A2': 20, 'A3': 30, 'A4': 40, 'B2': 0}
                values[cell] = wrong
                families[name] = book(folder/(name+'.xlsx'), values)
        plan = {'source': source['workbook'], 'bindings_canonical_sha256': helper.canonical(helper.read(source['bindings'])),
            'sheetnames': ['Model'], 'specification_sha256': 's'*64, 'mode': mode,
            'plan_sha256': 'p'*64, 'recipe': pair['task_views']._recipe(), 'instruction': instruction,
            'masked_targets': targets, 'formula_edits': edits}
        plan_ref = dump(folder/'plan.json', plan)
        return dump(folder/'private/view_manifest.json', {'kind': 'materialized_unverified_linear_capital_scaled_task_view',
            'version': 1, 'mode': mode, 'source': source['workbook'], 'specification_sha256': 's'*64,
            'plan': plan_ref, 'plan_sha256': plan['plan_sha256'], 'recipe': plan['recipe'],
            'input': public, 'goal': helper.reference(goal), 'instruction': helper.reference(brief),
            'family_inputs': families, 'temporary_plan_only': temporary, 'sheetnames': ['Model']})
    monkeypatch.setattr(pair['task_views'], 'plan_task_view', plan)
    monkeypatch.setattr(pair['task_views'], 'materialize_view', materialize)
    return SimpleNamespace(root=root, manifest=manifest, source=source, events=events, state=state,
        config=config, helper=helper, session=session, pair=pair, validator=validator, calls=calls)


def test_frozen_callable_census_and_unmodified_global_namespaces():
    entry.frozen_dependencies()
    for path, names, imported in [(entry.POOL, entry.PAIR_FUNCTIONS, {}),
            (entry.VALIDATOR, entry.VALIDATOR_FUNCTIONS, entry.VALIDATOR_IMPORTS)]:
        module = entry._module(path)
        original = dict(vars(module))
        private = entry._isolate(module, names, imported)
        assert vars(module) == original
        for name in names:
            assert private[name].__code__ is original[name].__code__
            assert private[name].__globals__ is private
            assert original[name].__globals__ is vars(module)


def test_one_cold_source_for_prepare_run_and_complete_both_protocols(boundary):
    b = boundary
    output = b.root/'cached'
    frozen_ref = entry.prepare(b.manifest, output, session=b.session)
    frozen = b.helper.read(frozen_ref)
    assert frozen['kind'] == entry.PREPARED and frozen['profile_id'] == 'L360-P01'
    assert frozen['source_reuse_policy']['pool_policy_version'] == 2
    assert frozen['source_reuse_policy']['first_development_profile'] == 'L360-P01'
    assert all(frozen[key] == 0 for key in ('LO_calls', 'model_calls', 'solver_calls', 'Harbor_calls', 'workbooks_emitted'))
    for _ in range(2):
        entry.validate_prepared(output, session=b.session)
    terminal_ref = entry.execute_prepared(output, session=b.session)
    terminal = b.helper.read(terminal_ref)
    assert terminal['kind'] == entry.KIND and terminal['passed']
    assert terminal['LO_call_count_exact'] == 18 and not terminal['qualified']
    assert terminal['actual_source_cold_validation_count_in_process'] == 1
    assert b.events.count('cold_source') == b.session.admission.cold_source_validation_count == 1
    assert b.calls == b.session.validator.required_roles('financial_modeling') + b.session.validator.required_roles(
        'debugging', b.pair['task_views'].FAMILIES)
    both = b.helper.read(output/'both_validator_preparations_before_LO.json')
    assert set(both['validator_preparations']) == {'financial_modeling', 'debugging'}
    for mode, count in [('financial_modeling', 7), ('debugging', 11)]:
        result = b.helper.read(terminal['validation_terminals'][mode])
        assert len(result['actual_LO_calls']) == count
        assert result['local_controls'] == b.session.validator.REWARDS
        assert b.helper.read(result['complete_D'])['expected_change_count'] > 0
        assert b.session.validator.validate_completed(terminal['validation_terminals'][mode]) == result
    assert b.helper.read(output/'producer.lock')['status'] == 'released'
    assert 'dashboard_started' in b.events and b.events[-1] == 'dashboard_stopped'
    assert b.events.count('cold_source') == 1
    with pytest.raises(ValueError, match='first pair attempt'):
        entry.execute_prepared(output, session=b.session)


def test_new_cold_session_admits_again_and_cannot_rehydrate_metadata(boundary):
    b = boundary
    output = b.root/'cached'
    entry.prepare(b.manifest, output, session=b.session)
    # Simulate a fresh CLI's new opaque object; the preparation's count is only metadata.
    fresh = entry.PairSession(b.manifest)
    fresh.pair.prepare.__globals__['policy'] = b.pair['policy']
    entry.validate_prepared(output, session=fresh)
    assert fresh is not b.session and b.events.count('cold_source') == 2
    assert fresh.admission.cold_source_validation_count == 1


def test_combined_cli_creates_one_admission_and_reuses_it(boundary, monkeypatch):
    b = boundary
    before = b.events.count('cold_source')
    original_build = entry.PairSession._build
    def build(self):
        original_build(self)
        self.pair.prepare.__globals__['policy'] = b.pair['policy']
        self.pair.prepare.__globals__['DashboardServer'] = b.pair['DashboardServer']
        self.validator.prepare.__globals__['DashboardServer'] = b.validator['DashboardServer']
    monkeypatch.setattr(entry.PairSession, '_build', build)
    assert entry.main(['--source-manifest', b.manifest['path'], '--output', str(b.root/'cli'), '--run']) == 0
    assert b.events.count('cold_source') == before+1 and len(b.calls) == 18


@pytest.mark.parametrize('bad', ['json', 'fabricated', 'old_namespace', 'foreign_pid', 'other_source'])
def test_no_fabricated_cross_namespace_or_mismatched_source_cache(boundary, bad, monkeypatch):
    b = boundary
    value = b.session
    source = b.manifest
    if bad == 'json':
        value = {'passed': True, 'source_manifest': source}
    elif bad == 'fabricated':
        value = object.__new__(entry.PairSession)
    elif bad == 'old_namespace':
        value = b.session.admission
    elif bad == 'foreign_pid':
        monkeypatch.setattr(b.session, 'owner_pid', os.getpid()+1)
    else:
        source = dump(b.root/'other_source.json', b.source)
    with pytest.raises(ValueError):
        entry.prepare(source, b.root/'must_not_emit', session=value)
    failed = b.helper.read(b.root/'must_not_emit/source_admission_failure.json')
    assert failed['LO_calls'] == failed['model_calls'] == failed['solver_calls'] == 0
    assert not (b.root/'must_not_emit/preparation.json').exists() and b.calls == []


@pytest.mark.parametrize('attack', ['source_child', 'source_recipe', 'reuse_policy', 'count_bool', 'pool_identity', 'pair_recipe'])
def test_late_guard_or_preparation_drift_blocks_every_calculation(boundary, attack):
    b = boundary
    output = b.root/'cached'
    entry.prepare(b.manifest, output, session=b.session)
    frozen = b.helper.read(output/'preparation.json')
    if attack == 'source_child':
        Path(b.source['bindings']['path']).write_text('{}')
    elif attack == 'source_recipe':
        Path(next(iter(b.source['source_recipe_sha256']))).write_text('# changed\n')
    else:
        if attack == 'reuse_policy':
            frozen['source_reuse_policy']['first_development_profile'] = 'L360-P02'
        elif attack == 'count_bool':
            frozen['actual_source_cold_validation_count_in_process'] = True
        elif attack == 'pool_identity':
            frozen['pool_identity']['seed'] += 1
        else:
            frozen['recipe_sha256'].pop(str(Path(entry.__file__).resolve()))
        dump(output/'preparation.json', frozen)
    with pytest.raises(ValueError):
        entry.execute_prepared(output, session=b.session)
    assert b.calls == [] and 'dashboard_started' not in b.events


@pytest.mark.parametrize('attack', ['missing_call', 'bad_control', 'full_D_pair', 'missing_family', 'wrong_resource'])
def test_reused_source_does_not_relax_completed_protocol(boundary, attack):
    b = boundary
    output = b.root/'cached'
    entry.prepare(b.manifest, output, session=b.session)
    terminal = b.helper.read(entry.execute_prepared(output, session=b.session))
    mode = 'debugging' if attack == 'missing_family' else 'financial_modeling'
    result = b.helper.read(terminal['validation_terminals'][mode])
    directory = Path(terminal['validation_terminals'][mode]['path']).parent
    if attack == 'missing_call':
        result['actual_LO_calls'].pop()
    elif attack == 'bad_control':
        result['local_controls']['missed_root'] = 1
    elif attack == 'full_D_pair':
        delta = b.helper.read(result['complete_D'])
        delta['workbook_binding']['input'] = result['goal']
        result['complete_D'] = dump(directory/'false_D.json', delta)
    elif attack == 'missing_family':
        result['individual_effects'].pop(next(iter(result['individual_effects'])))
    else:
        call = result['actual_LO_calls'][1]
        call['actual_resource_evidence']['terminal'] = result['complete_D']
    wrong = dump(directory/'rebound_terminal.json', result)
    with pytest.raises((ValueError, KeyError)):
        b.session.validator.validate_completed(wrong)
    assert b.events.count('cold_source') == 1


def test_failed_actual_api_preserves_partial_terminal_and_releases_lease(boundary):
    b = boundary
    output = b.root/'cached'
    entry.prepare(b.manifest, output, session=b.session)
    b.state['failure'] = 'engine'
    with pytest.raises(RuntimeError, match='Preserved failed first pair'):
        entry.execute_prepared(output, session=b.session)
    terminal = b.helper.read(output/'terminal.json')
    assert not terminal['passed'] and terminal['LO_call_count_exact'] is None
    assert terminal['partial_validation_terminals'] and not terminal['qualified']
    assert b.helper.read(output/'producer.lock')['status'] == 'released'
    assert b.events[-1] == 'dashboard_stopped' and b.events.count('cold_source') == 1


def test_mid_run_source_guard_failure_cannot_suppress_failure_or_terminal_writes(boundary):
    b = boundary
    output = b.root/'mid_run_mutation'
    entry.prepare(b.manifest, output, session=b.session)
    b.state['failure'] = 'mutate_source'
    with pytest.raises(RuntimeError, match='Preserved failed first pair'):
        entry.execute_prepared(output, session=b.session)
    terminal = b.helper.read(output/'terminal.json')
    assert not terminal['passed'] and terminal['failure']
    assert terminal['partial_validation_terminals'] and terminal['LO_call_count_exact'] is None
    assert terminal['actual_source_cold_validation_count_in_process'] == 1 and not terminal['qualified']
    assert b.helper.read(terminal['failure'])['error_type'] == 'RuntimeError'
    partial = b.helper.read(terminal['partial_validation_terminals']['financial_modeling'])
    assert not partial['passed'] and len(partial['actual_LO_calls']) > 0
    assert b.helper.read(output/'producer.lock')['status'] == 'released'
    assert not (output/'debugging/actual_validation/started.json').exists()
    assert b.events[-1] == 'dashboard_stopped'
    with pytest.raises(ValueError):
        b.session.guard()


def test_unknown_function_or_closure_fails_closed():
    module = entry._module(entry.POOL)
    with pytest.raises(ValueError, match='census'):
        entry._isolate(module, entry.PAIR_FUNCTIONS-{'prepare'}, {})
    fake = SimpleNamespace()
    namespace = vars(fake)
    exec('def extra(): return 1', namespace)
    with pytest.raises(ValueError, match='census'):
        entry._isolate(fake, set(), {})
    def outer():
        value = 1
        return lambda: value
    original = outer()
    namespace.clear()
    namespace['closed'] = FunctionType(original.__code__, namespace, 'closed', None, original.__closure__)
    with pytest.raises(ValueError, match='closure'):
        entry._isolate(fake, {'closed'}, {})


def test_existing_output_is_rejected_before_another_cold_call(boundary):
    b = boundary
    output = b.root/'already_exists'
    output.mkdir()
    (output/'retain.txt').write_text('retain')
    before = b.events.count('cold_source')
    with pytest.raises(ValueError):
        entry.prepare(b.manifest, output)
    assert b.events.count('cold_source') == before
    assert (output/'retain.txt').read_text() == 'retain'


def test_failed_genuine_cold_admission_is_retained_without_preparation(boundary):
    b = boundary
    invalid = {**b.source, 'source_financially_verified': False}
    source = dump(b.root/'invalid_source.json', invalid)
    output = b.root/'invalid_cold'
    with pytest.raises(ValueError, match='complete financial source'):
        entry.prepare(source, output)
    failure = b.helper.read(output/'source_admission_failure.json')
    assert failure['completed_source_cold_validation_count'] == 0
    assert failure['LO_calls'] == failure['model_calls'] == failure['solver_calls'] == 0
    assert not (output/'preparation.json').exists() and b.calls == []
    with pytest.raises(ValueError):
        entry.prepare(source, output)


def test_failure_after_successful_cold_source_preserves_exact_completed_count(boundary, monkeypatch):
    b = boundary
    def fail(self):
        raise ValueError('Explicit namespace fixture failure after genuine source admission')
    monkeypatch.setattr(entry.PairSession, '_build', fail)
    output = b.root/'namespace_failure'
    with pytest.raises(ValueError, match='namespace fixture failure'):
        entry.prepare(b.manifest, output)
    failure = b.helper.read(output/'source_admission_failure.json')
    assert failure['completed_source_cold_validation_count'] == 1
    assert failure['LO_calls'] == failure['model_calls'] == failure['solver_calls'] == 0
    assert not (output/'preparation.json').exists()


def test_frozen_dependency_drift_fails_before_admission(monkeypatch):
    monkeypatch.setitem(entry.FROZEN, str(entry.POOL), '0'*64)
    with pytest.raises(ValueError, match='frozen paired-session'):
        entry.PairSession('/not/a/source')


def test_production_policy_retains_all20_original_members_and_exact_resources():
    pool = entry._module(entry.POOL)
    _, config = pool.policy()
    assert config['profile_order'] == [f'L360-P{i:02d}' for i in range(1, 21)]
    assert config['first_development_profile'] == 'L360-P01'
    assert len(pool._pool_evidence(config)) == 20
    assert config['required_actual_LO_calls'] == {'financial_modeling': 7, 'debugging': 11}
    assert config['resources'] == {'cpus': 2, 'memory_bytes': 32*1024**3, 'pids_limit': 256}
