"""Native export/history contracts with explicit fake cold, image and model boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
descriptor = importlib.util.spec_from_file_location('_native_development_tests',
    ROOT/'scripts/prepare_heterogeneous_native_development.py')
entry = importlib.util.module_from_spec(descriptor)
descriptor.loader.exec_module(entry)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')
    return entry.reference(path)


def workbook(path, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = openpyxl.Workbook()
    book.remove(book.active)
    for index in range(8):
        sheet = book.create_sheet('Business'+str(index))
        sheet['A1'] = 'Provided business label'
        sheet['B1'] = None if mode == 'financial_modeling' else 0 if mode == 'debugging' else 12+index
    book.save(path)
    book.close()
    return entry.reference(path)


def test_frozen_corrected_native_namespace_and_real_recipe_bindings_need_no_services():
    driver = entry.validation_driver()
    assert driver.ACTUAL_KIND == entry.ACTUAL_KIND and driver.task.VERSION == 2
    bindings = entry.recipes()
    entry.verify_mapping(bindings)
    assert bindings[str(entry.VALIDATOR)] == entry.VALIDATOR_SHA256
    assert all(Path(path).is_absolute() and type(digest) is str for path, digest in bindings.items())


def test_native_three_key_recipe_refs_become_absolute_digest_bindings(tmp_path):
    path = tmp_path/'native_recipe.py'
    path.write_text('# Pure test recipe\n')
    record = entry.reference(path)
    result = entry._native_recipe_bindings({str(path): record})
    assert result == {str(path): record['sha256']}
    entry.verify_mapping(result)
    relative = ROOT/'scripts/prepare_heterogeneous_native_development.py'
    assert entry._native_recipe_bindings({'scripts/prepare_heterogeneous_native_development.py': entry.reference(relative)}) == {
        str(relative): entry.reference(relative)['sha256']}
    with pytest.raises(ValueError): entry._native_recipe_bindings({str(tmp_path/'wrong.py'): record})
    path.write_text('# Changed recipe\n')
    with pytest.raises(ValueError): entry._native_recipe_bindings({str(path): record})


@pytest.fixture
def factory(tmp_path, monkeypatch):
    calls = []
    def validate_completed(record):
        calls.append(record)
        value = entry.read(record)
        if value.get('offline_validator_failure'):
            raise ValueError('Explicit mocked genuine native validator rejection')
        return value
    monkeypatch.setattr(entry, 'validation_driver', lambda: SimpleNamespace(validate_completed=validate_completed))
    monkeypatch.setattr(entry, 'recipes', lambda: {str(Path(entry.__file__)): entry.reference(entry.__file__)['sha256']})
    monkeypatch.setattr(entry, 'HISTORY_ROOTS', (tmp_path/'history/difficulty', tmp_path/'history/research'))
    monkeypatch.setattr(entry, 'verify_local_base_image', lambda path: {'kind': 'explicit_unit_mock_no_actual_image_inspection'})
    def make(mode='financial_modeling', name='case'):
        root = tmp_path/name
        source = workbook(root/'source_presentation.xlsx')
        public = workbook(root/'actual/input1.xlsx', mode)
        raw = workbook(root/'raw_input.xlsx', mode)
        goal = workbook(root/'actual/goal1.xlsx')
        instruction = root/'instruction.md'
        instruction.write_text('Repair the labelled existing business model. Save it to /app/output.xlsx.\n')
        instruction_ref = entry.reference(instruction)
        points = [['Business'+str(i%8), 'C'+str(i//8+1)] for i in range(758)]
        points += [['Business'+str(i), 'B1'] for i in range(8)]
        plan = dump(root/'plan.json', {'mode': mode, 'financial_scope': points,
            'faults': [] if mode == 'financial_modeling' else [{'sheet': 'Business0', 'cell': 'B1', 'replacement': '=0'}]})
        coverage = dump(root/'coverage.json', {'passed': True,
            'expected_typed_values': [{'sheet': sheet, 'cell': cell, 'expected': {'type': 'empty'}} for sheet, cell in points]})
        pending = dump(root/'pending_D.json', {'kind': 'prospective_pending_actual_full_D', 'actual_D_computed': False})
        lineage = dump(root/'native_source_lineage.json', {'kind': 'explicit_mock_native_source_boundary'})
        material = {'kind': entry.MATERIAL_KIND, 'version': entry.NATIVE_VERSION, 'mode': mode, 'qualified': False,
            'source_presentation': source, 'source_lineage': lineage, 'module_count': 8,
            'public_input': raw, 'instruction': instruction_ref, 'private_goal': source,
            'expected_delta': pending, 'review_scope': plan, 'source_admitted': False}
        raw_material = dump(root/'raw_material.json', material)
        profile = entry.reference(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
        alias_proof = dump(root/'text_alias_cache_proof.json', {
            'kind': 'declared_two_direct_text_alias_cache_transfers', 'version': entry.NATIVE_VERSION,
            'source': source, 'presentation': source, 'numeric_caches_changed': 0,
            'all_other_cell_subtrees_unchanged_except_six_literals_and_two_caches': True,
            'prior_failure_lineage': {'explicit_fake_previous_failure': True},
            'aliases': [{'sheet': 'DCF - Valuation as picture', 'cell': cell,
                'source_sheet': 'DCF - Stories to Numbers', 'source_cell': target,
                'unchanged_direct_formula': "'DCF - Stories to Numbers'!"+target,
                'original_typed_cache': {'type': 'string', 'value': old},
                'expected_typed_cache': {'type': 'string', 'value': new},
                'outside_financial_scope766': True, 'formula_preserved': True}
                for cell, target, old, new in [
                    ('H6', 'G10', 'Margins improve, aided by cloud business & continued economies of scale.',
                     'Operating margin remains at the stated base-year level.'),
                    ('K6', 'G12', "Maintained at Amazon's current level",
                     'Given industry sales / capital; terminal reinvestment rate.')]]})
        preparation = dump(root/'preparation.json', {'kind': entry.PREPARED_KIND, 'version': entry.NATIVE_VERSION,
            'phase': 'development', 'maximum_external_LO_calls': 7, 'outer_retries': 0,
            'mode': mode, 'material': raw_material, 'input': raw, 'instruction': instruction_ref,
            'goal': source, 'plan': plan, 'source_presentation': source, 'source': source,
            'text_alias_cache_proof': alias_proof, 'independent_scope_coverage': coverage})
        delta = dump(root/'complete_actual_D.json', {'kind': 'complete_heterogeneous_review_task_actual_D',
            'version': entry.NATIVE_VERSION, 'mode': mode, 'actual_change_count': 8,
            'expected_changes': [{'sheet': 'Business'+str(i), 'cell': 'B1'} for i in range(8)],
            'all_independently_covered': True, 'all_eight_families_nonempty': True,
            'family_effect_counts': {'Business'+str(i): 1 for i in range(8)},
            'known_protected_points_disjoint': True, 'full_sparse_union_compared': True})
        material.update(public_input=public, private_goal=goal, expected_delta=delta,
            raw_public_input=raw, actual_validation_completed=True)
        completed_material = dump(root/'completed_material.json', material)
        controls = dump(root/'controls.json', {'kind': 'heterogeneous_review_five_actual_controls',
            'version': entry.NATIVE_VERSION, 'passed': True, 'rewards': deepcopy(entry.CONTROL_REWARDS)})
        stability = dump(root/'stability.json', {'passed': True, 'explicit_fake_engine_boundary': True})
        stages = ['input1', 'input2', 'goal1', 'goal2', 'equivalent', 'missed_root', 'extra_change']
        actual = dump(root/'terminal.json', {'kind': entry.ACTUAL_KIND, 'version': entry.NATIVE_VERSION, 'status': 'passed', 'passed': True,
            'mode': mode, 'qualified': False, 'material': completed_material, 'preparation': preparation,
            'source_presentation': source, 'text_alias_cache_proof': alias_proof, 'raw_input': raw, 'input': public, 'goal': goal, 'instruction': instruction_ref,
            'expected_delta': delta, 'complete_actual_D': delta, 'independent_scope_coverage': coverage,
            'controls': controls, 'stability': stability, 'runtime_profile': profile,
            'actual_LO_calls': [{'index': i+1, 'stage': stage, 'completed': True,
                'output': public if stage.startswith('input') else goal} for i, stage in enumerate(stages)],
            'source_admitted': False, 'normal_12QA_passed': False, 'public_recovery_passed': False,
            'Harbor_passed': False, 'final20_qualified': False, 'model_calls': 0, 'solver_calls': 0,
            'Harbor_calls': 0, 'outer_retries': 0})
        return SimpleNamespace(root=root, mode=mode, actual=actual, source=source, public=public,
            raw=raw, goal=goal, instruction=instruction_ref, delta=delta, output=root/'snapshot', calls=calls)
    return SimpleNamespace(make=make, calls=calls, root=tmp_path)


@pytest.mark.parametrize('mode', ['financial_modeling', 'debugging'])
def test_complete_seventeen_file_native_export_and_frozen_contract(factory, mode):
    case = factory.make(mode)
    frozen = entry.read(entry.prepare(case.actual, case.output))
    assert frozen['kind'] == entry.KIND and frozen['family'] == 'heterogeneous_native_review'
    assert frozen['schema_version'] == 2 and frozen['phase'] == 'development'
    assert len(case.calls) == 1
    assert frozen['actual_validation_LO_calls_retained'] == 7 and frozen['independent_financial_scope_count'] == 766
    assert frozen['complete_changed_value_set_count'] == 8
    assert frozen['quality_gates_pending'] == entry.PENDING and not frozen['qualified']
    assert frozen['native_transport_profile'] == entry.transport_profile()
    assert frozen['model'] == 'gpt-6.1-sol' and frozen['reasoning_effort'] == 'xhigh'
    assert frozen['tool_time_policy_version'] == 3 and frozen['execution_budget'] == entry.BUDGET
    assert len(frozen['resource_task_inventory']) == 17 and set(frozen['resource_task_inventory']) == set(entry.TASK_FILES)
    task = Path(frozen['tasks'][0]['task_directory'])
    assert (task/'instruction.md').read_bytes() == Path(case.instruction['path']).read_bytes()
    assert (task/'environment/input.xlsx').read_bytes() == Path(case.public['path']).read_bytes()
    assert (task/'tests/reference.xlsx').read_bytes() == Path(case.goal['path']).read_bytes()
    assert Path(frozen['thread_cap_export_audit']['path']).parent == case.output
    for name in ('environment/Dockerfile', 'tests/Dockerfile'):
        assert (task/name).read_text().splitlines()[1] == 'ENV MAX_CONCURRENCY=2'
    assert entry.validate_prepared(case.output) == frozen and len(case.calls) == 2


@pytest.mark.parametrize('fault', ['old_actual', 'bool_version', 'failed_v1_actual', 'v1_material', 'v1_prepared', 'old_material', 'failed_cold', 'missing_call',
    'wrong_order', 'raw_input_export', 'bad_controls', 'coverage', 'full_D', 'source', 'qualified', 'normal_quality'])
def test_native_admission_and_stable_fullD_fail_closed(factory, fault):
    case = factory.make()
    value = entry.read(case.actual)
    if fault == 'old_actual': value['kind'] = 'linear_capital_scaled_task_view_actual_validation'
    elif fault == 'bool_version': value['version'] = True
    elif fault == 'failed_v1_actual': value['version'] = 1
    elif fault == 'v1_material':
        material = entry.read(value['material']); material['version'] = 1
        value['material'] = dump(Path(value['material']['path']), material)
    elif fault == 'v1_prepared':
        prepared = entry.read(value['preparation']); prepared['version'] = 1
        value['preparation'] = dump(Path(value['preparation']['path']), prepared)
    elif fault == 'old_material':
        material = entry.read(value['material']); material['kind'] = 'materialized_unverified_linear_capital_scaled_task_view'
        value['material'] = dump(Path(value['material']['path']), material)
    elif fault == 'failed_cold': value['offline_validator_failure'] = True
    elif fault == 'missing_call': value['actual_LO_calls'].pop()
    elif fault == 'wrong_order': value['actual_LO_calls'][0]['stage'] = 'goal1'
    elif fault == 'raw_input_export':
        material = entry.read(value['material']); material['public_input'] = case.raw
        value['material'] = dump(Path(value['material']['path']), material); value['input'] = case.raw
    elif fault == 'bad_controls':
        controls = entry.read(value['controls']); controls['rewards']['oracle'] = True
        value['controls'] = dump(Path(value['controls']['path']), controls)
    elif fault == 'coverage':
        coverage = entry.read(value['independent_scope_coverage']); coverage['expected_typed_values'].pop()
        changed = dump(Path(value['independent_scope_coverage']['path']), coverage); value['independent_scope_coverage'] = changed
        prepared = entry.read(value['preparation']); prepared['independent_scope_coverage'] = changed
        value['preparation'] = dump(Path(value['preparation']['path']), prepared)
    elif fault == 'full_D':
        delta = entry.read(value['complete_actual_D']); delta['expected_changes'][0]['cell'] = 'A1'
        changed = dump(Path(value['complete_actual_D']['path']), delta)
        value['complete_actual_D'] = value['expected_delta'] = changed
        material = entry.read(value['material']); material['expected_delta'] = changed
        value['material'] = dump(Path(value['material']['path']), material)
    elif fault == 'source': value['source_presentation'] = case.raw
    elif fault == 'qualified': value['qualified'] = True
    else: value['normal_12QA_passed'] = True
    changed = dump(Path(case.actual['path']), value)
    with pytest.raises((ValueError, KeyError)):
        entry.prepare(changed, case.output)
    assert not (case.output/'probe_manifest.json').exists()


@pytest.mark.parametrize('fault', ['missing_alias', 'formula', 'text', 'numeric', 'bool_numeric', 'v1', 'binding', 'financial_scope'])
def test_only_two_declared_text_alias_caches_can_enter_v2(factory, fault):
    case = factory.make()
    actual = entry.read(case.actual)
    proof = entry.read(actual['text_alias_cache_proof'])
    if fault == 'missing_alias': proof['aliases'].pop()
    elif fault == 'formula': proof['aliases'][0]['unchanged_direct_formula'] = '=0'
    elif fault == 'text': proof['aliases'][0]['expected_typed_cache']['value'] = 'Undeclared replacement'
    elif fault == 'numeric': proof['numeric_caches_changed'] = 1
    elif fault == 'bool_numeric': proof['numeric_caches_changed'] = False
    elif fault == 'v1': proof['version'] = 1
    elif fault == 'financial_scope': proof['aliases'][0]['outside_financial_scope766'] = False
    changed = dump(Path(actual['text_alias_cache_proof']['path']), proof)
    actual['text_alias_cache_proof'] = changed
    if fault != 'binding':
        preparation = entry.read(actual['preparation']); preparation['text_alias_cache_proof'] = changed
        actual['preparation'] = dump(Path(actual['preparation']['path']), preparation)
    else:
        preparation = entry.read(actual['preparation']); preparation.pop('text_alias_cache_proof')
        actual['preparation'] = dump(Path(actual['preparation']['path']), preparation)
    with pytest.raises((ValueError, KeyError)):
        entry.prepare(dump(Path(case.actual['path']), actual), case.output)
    assert not (case.output/'probe_manifest.json').exists()


def history(factory, identity, *, name='prior', mode=None):
    folder = factory.root/'history/research'/name
    source = dump(folder/'probe_manifest.json', {'material_task_version': identity})
    return dump(folder/'selection_manifest.json', {'phase': 'development', 'source_manifest': source,
        'tasks': [{'task_id': 'renamed', 'mode': mode or identity['mode'], 'task_checksum': 'c'*64}]})


def other_identity(mode='financial_modeling'):
    value = {'mode': mode, 'instruction_sha256': 'f'*64}
    return {**value, 'sha256': entry.canonical(value)}


def nonmodel_history(factory):
    folder = factory.root/'history/research/raw_preparation'
    book = workbook(folder/'raw.xlsx')
    source = dump(folder/'source.json', {'explicit_mock': True})
    batch = dump(folder/'batch.json', {'explicit_mock': True})
    task_id = 'fm-'+book['sha256'][:12]
    return dump(folder/'selection_manifest.json', {'kind': 'composite_preparation_selection', 'schema_version': 1,
        'mode': 'financial_modeling', 'model_results_consulted': False, 'qualified': False, 'task_count': 0, 'llm_calls': 0,
        'source_batch_manifest': batch, 'source_selected_order': ['raw'], 'selected_task_ids': [task_id],
        'sources': [{'index': 0, 'profile_id': 'raw', 'source_id': book['sha256'], 'task_id': task_id,
            'source_manifest': source, 'workbook': book, 'verification': {'explicit_mock': True}}]})


def test_full_history_retains_exact_nonmodel_classifier_and_unrelated_appends(factory):
    case = factory.make()
    nonmodel = nonmodel_history(factory)
    prior = history(factory, other_identity(), name='prior')
    frozen = entry.read(entry.prepare(case.actual, case.output))
    assert frozen['nonmodel_preparation_inventory'] == [nonmodel]
    assert frozen['prior_model_selection_inventory'] == [prior]
    appended = history(factory, other_identity('debugging'), name='later', mode='debugging')
    assert entry.validate_prepared(case.output) == frozen
    assert set(row['path'] for row in entry.selection_history(frozen['material_task_version'])) == {row['path'] for row in [nonmodel, prior, appended]}
    Path(prior['path']).write_text('{}')
    with pytest.raises(ValueError): entry.validate_prepared(case.output)


@pytest.mark.parametrize('fault', ['malformed', 'changed_other_mode'])
def test_full_history_checks_declared_source_references_even_for_other_mode(factory, fault):
    case = factory.make()
    prior = history(factory, other_identity('debugging'), name='other', mode='debugging')
    value = entry.read(prior)
    if fault == 'malformed':
        value['source_manifest'] = {'path': value['source_manifest']['path']}
        dump(Path(prior['path']), value)
    else:
        Path(value['source_manifest']['path']).write_text('{}')
    with pytest.raises(ValueError):
        entry.prepare(case.actual, case.output)
    assert not (case.output/'probe_manifest.json').exists()


def test_renamed_and_reversioned_equivalent_material_cannot_resample(factory):
    case = factory.make()
    frozen = entry.read(entry.prepare(case.actual, case.output))
    identity = deepcopy(frozen['material_task_version'])
    identity['version'] = 99
    identity['scope_sha256'] = 'd'*64
    identity['sha256'] = entry.canonical({key: value for key, value in identity.items() if key != 'sha256'})
    history(factory, identity)
    with pytest.raises(ValueError, match='do not resample or rename'):
        entry.validate_prepared(case.output)


@pytest.mark.parametrize('fault', ['export', 'extra_file', 'recipe', 'normal_quality', 'history_roots', 'stream_retries', 'budget'])
def test_snapshot_mutation_blocks_launch(factory, fault):
    case = factory.make()
    reference = entry.prepare(case.actual, case.output)
    frozen = entry.read(reference)
    task = Path(frozen['tasks'][0]['task_directory'])
    if fault == 'export': (task/'instruction.md').write_text('Changed')
    elif fault == 'extra_file': (task/'unexpected').write_text('Extra')
    elif fault == 'recipe': frozen['recipe_sha256'] = {}
    elif fault == 'normal_quality': frozen['normal_ExportNode_executed'] = True
    elif fault == 'history_roots': frozen['history_roots'] = []
    elif fault == 'stream_retries': frozen['native_transport_profile']['provider_overrides']['stream_max_retries'] = 9
    else: frozen['execution_budget']['tool_budget_seconds'] = 1801
    if fault not in ('export', 'extra_file'): dump(Path(reference['path']), frozen)
    with pytest.raises(ValueError): entry.validate_prepared(case.output)


@pytest.fixture
def model_boundary(monkeypatch):
    import sheets_factory.evaluation.native_transport_frontier as frontier
    import sheets_factory.evaluation.resource_observer as observations
    state = SimpleNamespace(calls=[], barrier=None, failure=False)
    class Observer:
        receipt = None
        finalization_error = None
        def __init__(self, directory): pass
        def __enter__(self): return self
        def __exit__(self, *error): pass
    def run(source, destination, **kwargs):
        state.calls.append({'source': source, 'destination': destination, **kwargs})
        if state.barrier is not None: state.barrier.wait(timeout=15)
        if state.failure: raise RuntimeError('Explicit offline model-boundary failure; no actual call')
        destination.mkdir(parents=True)
        dump(destination/'selection_manifest.json', {'tasks': [], 'explicit_fake_model_boundary': True})
        dump(destination/'evaluation_manifest.json', {'status': 'completed', 'explicit_fake_model_boundary': True})
        return {'status': 'completed', 'score': {'explicit_fake_model_boundary': True}}
    monkeypatch.setattr(frontier, 'run_evaluation', run)
    monkeypatch.setattr(observations, 'ResourceObserver', Observer)
    return state


def test_single_native_dispatch_binds_full_current_launch_history_and_never_retries(factory, model_boundary):
    case = factory.make()
    nonmodel = nonmodel_history(factory)
    entry.prepare(case.actual, case.output)
    appended = history(factory, other_identity(), name='new')
    terminal = entry.read(entry.run_development(case.output, case.root/'evaluation'))
    assert not terminal['qualified'] and terminal['effective_infrastructure_retries'] == 0
    assert len(model_boundary.calls) == 1
    call = model_boundary.calls[0]
    assert call['phase'] == 'development' and call['concurrency'] == 1
    assert call['backend_config']['model'] == 'gpt-6.1-sol' and call['backend_config']['reasoning_effort'] == 'xhigh'
    assert call['prior_selections'] == [appended['path']]
    started = entry.read(case.output/'development_started.json')
    reservation = entry.read(started['material_reservation'])
    assert started['selection_history_inventory'] == reservation['selection_history_inventory']
    assert started['nonmodel_preparation_inventory'] == [nonmodel]
    assert started['prior_model_selection_inventory'] == [appended]
    with pytest.raises(ValueError): entry.run_development(case.output, case.root/'again')


def test_two_modes_prepare_before_calls_then_dispatch_concurrently(factory, model_boundary):
    fm, dbg = factory.make('financial_modeling', 'fm'), factory.make('debugging', 'dbg')
    entry.prepare(fm.actual, fm.output)
    entry.prepare(dbg.actual, dbg.output)
    assert model_boundary.calls == []
    model_boundary.barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(entry.run_development, case.output, case.root/'evaluation') for case in (fm, dbg)]
        results = [future.result(timeout=30) for future in futures]
    assert len(results) == len(model_boundary.calls) == 2
    directory = factory.root/'history/difficulty/.native_development_material_reservations'
    assert len(list(directory.glob('*.json'))) == 2


def test_cross_snapshot_same_material_and_failed_reservation_are_durable(factory, model_boundary):
    case = factory.make()
    other = case.root/'other_snapshot'
    entry.prepare(case.actual, case.output)
    entry.prepare(case.actual, other)
    model_boundary.failure = True
    with pytest.raises(RuntimeError): entry.run_development(case.output, case.root/'failed')
    assert entry.read(case.output/'development_failure.json')['failure_is_not_model_zero']
    with pytest.raises(ValueError, match='reserved first attempt'):
        entry.run_development(other, case.root/'different')
    assert len(model_boundary.calls) == 1
    assert len(list((factory.root/'history/difficulty/.native_development_material_reservations').glob('*.json'))) == 1


def test_snapshot_lock_and_unsupported_cli_routes_precede_model_boundary(factory, model_boundary):
    case = factory.make()
    entry.prepare(case.actual, case.output)
    with (case.output/'.development.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='active launcher'):
            entry.run_development(case.output, case.root/'evaluation')
    assert model_boundary.calls == []
    for arguments in (['resume'], ['confirmation'], ['run-development', '--model', 'other']):
        with pytest.raises(SystemExit): entry.main(arguments)
