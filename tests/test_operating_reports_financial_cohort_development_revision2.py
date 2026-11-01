"""Test the C02-only v6 entry without cold admission or external services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
import zipfile

import openpyxl
import pytest

from test_operating_reports_financial_cohort_development import material as original_material

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry():
    loader = importlib.util.spec_from_file_location('_test_C02_precision_first_v6',
        ROOT / 'scripts/prepare_operating_reports_financial_cohort_development_revision2.py')
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


@pytest.fixture
def material(entry, monkeypatch, tmp_path):
    real_read = entry._N['read']
    f = original_material.__wrapped__(entry, monkeypatch, tmp_path)
    e = entry
    fixture_read = e._N['read']
    monkeypatch.setitem(e._N, 'read', lambda row: fixture_read(row) if isinstance(row, dict) else real_read(row))
    f.public.update(seed=202711202)
    f.public_path.write_text(json.dumps(f.public))
    f.copy_path.write_bytes(f.public_path.read_bytes())
    f.publics['FM-C02'] = f.public
    f.frozen.update(kind='prepared_operating_reports_financial_cohort_FM_task_engineering_revision2',
                    version=2, case_id='FM-C02')
    f.sf.update(case_id='FM-C02', source_only_policy_sha256=e.POLICY_SHA,
                expected={'path': 'TEST_ONLY/unchanged_independent_93510.json'})
    f.candidate['candidate_id'] = 'FM-C02'
    f.actual.update(kind='complete_operating_reports_financial_cohort_FM_task_engineering_revision2',
                    version=2, failure=None)
    f.source.update(kind='independently_checked_operating_reports_financial_cohort_source_precision_revision2',
                    version=2, failure=None, reused_native_calls=1, new_native_calls_started=2,
                    new_native_calls_completed=2, cold_start_is_unseeded=True, new_financial_forwards=0,
                    old_failure_reclassified=False, E05_E06_grader_changed=False, policy_sha256=e.POLICY_SHA)
    f.actual['source_manifest']['sha256'] = e.SOURCE_SHA
    f.frozen['source_manifest'] = f.actual['source_manifest']

    def book(name, value):
        path = tmp_path / name
        workbook = openpyxl.Workbook()
        workbook.active.title = 'Report'
        workbook.active['A1'] = 'Given policy'
        workbook.active['B1'] = value
        workbook.save(path)
        workbook.close()
        return e._N['ref'](path)

    inp = book('input.xlsx', None)
    goal = book('goal.xlsx', 100)
    f.mode.update(input=inp, goal=goal)
    f.frozen.update(genuine_goal=goal, source_independent_expected=f.sf['expected'],
                    actual_primary_expected_from_genuine_goal_ref=goal, source_precision_policy_sha256=e.POLICY_SHA)
    f.source.update(source=goal, actual_calls=[{'output': goal} for _ in range(3)])
    monkeypatch.setattr(e, 'INPUT_SHA', inp['sha256'])
    monkeypatch.setattr(e, 'GOAL_SHA', goal['sha256'])
    # The retained fixture writes this public JSON before these C02-only changes.
    f.frozen['specification'] = f.source['specification'] = f.sf['specification'] = e._N['ref'](f.public_path)
    f.candidate['specification'] = e._N['ref'](f.copy_path)
    terminal = tmp_path / 'terminal.json'
    terminal.write_text(json.dumps(f.actual))
    f.terminal = e._N['ref'](terminal)
    monkeypatch.setattr(e, 'TERMINAL_SHA', f.terminal['sha256'])
    calls = []

    def cold(value):
        calls.append(value)
        if f.actual.get('TEST_ONLY_cold_failure'):
            raise ValueError('Mocked genuine cold validator rejection')
        return f.actual

    monkeypatch.setitem(e._N, 'validation_driver', lambda: SimpleNamespace(validate_completed=cold))
    f.cold_calls = calls
    return f


def test_real_final_provider_and_private_v6_lifecycle_are_bound(entry):
    e = entry
    driver = e.validation_driver()
    assert e.TASK_SHA == '51c2c4467bd9252e94bad4f98c6d5eecf7dab0721a25e719d45d0f3ba155a031'
    assert e._N['ref'](e.TASK)['sha256'] == e.TASK_SHA
    assert driver.TERMINAL_KIND == 'complete_operating_reports_financial_cohort_FM_task_engineering_revision2'
    assert driver.VERSION == 2 and driver.STAGES == ('FM_input1', 'FM_input2', 'equivalent', 'FM_missed_root', 'extra_change')
    assert e._N['VALIDATOR'] == e.TASK and e._N['VALIDATOR_SHA'] == e.TASK_SHA
    assert e._N['KIND'] == e.KIND and e.MODES == ('financial_modeling',)
    assert not hasattr(e, 'run_pair')
    assert e.runner.POLICY_V6['strict_less_than'] is True
    assert e.runner.POLICY_V6['budget_seconds'] == 1800
    assert e.runner.POLICY_V6['parallel_executions'] == 'sum'
    assert e.BUDGET['elapsed_guard_seconds'] == 14400
    assert e._N['PROFILE'] == ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'


def test_full_pinned_C02_metadata_is_read_only_and_uses_the_genuine_gate(material):
    f = material
    before = deepcopy((f.actual, f.frozen, f.source, f.sf, f.candidate))
    actual, candidate = f.e._checked_engineering(f.terminal)
    assert actual is f.actual and f.cold_calls == [f.terminal]
    assert (f.actual, f.frozen, f.source, f.sf, f.candidate) == before
    assert candidate['specification'] == f.frozen['specification']
    assert candidate['instructions'] == {'financial_modeling': f.mode['instruction']}


@pytest.mark.parametrize('problem', [
    'terminal', 'cold', 'task_kind', 'version', 'calls', 'normal_clear', 'case', 'source_kind',
    'source_hash', 'source_calls', 'reused_calls', 'policy', 'independent', 'primary_goal',
    'scope', 'D', 'raw_inventory', 'missing_case', 'input', 'goal', 'brief', 'controls',
])
def test_wrong_legacy_or_changed_evidence_cannot_admit(material, problem):
    f = material
    if problem == 'terminal':
        f.e.TERMINAL_SHA = '0' * 64
    elif problem == 'cold':
        f.actual['TEST_ONLY_cold_failure'] = True
    elif problem == 'task_kind':
        f.actual['kind'] = 'complete_operating_reports_financial_cohort_FM_task_engineering'
    elif problem == 'version':
        f.actual['version'] = 1
    elif problem == 'calls':
        f.actual['actual_LO_calls_completed'] = 4
    elif problem == 'normal_clear':
        f.actual['normal_all12_QA_passed'] = True
    elif problem == 'case':
        f.public['seed'] = 202711201
    elif problem == 'source_kind':
        f.source['kind'] = 'independently_checked_operating_reports_financial_cohort_source_v1'
    elif problem == 'source_hash':
        f.actual['source_manifest']['sha256'] = '0' * 64
    elif problem == 'source_calls':
        f.source['new_native_calls_completed'] = 1
    elif problem == 'reused_calls':
        f.source['reused_native_calls'] = 0
    elif problem == 'policy':
        f.source['policy_sha256'] = '0' * 64
    elif problem == 'independent':
        f.frozen['source_independent_expected'] = {'path': 'TEST_ONLY/other_answer_map'}
    elif problem == 'primary_goal':
        f.frozen['actual_primary_expected_from_genuine_goal_ref'] = {'path': 'TEST_ONLY/other_goal'}
    elif problem == 'scope':
        f.frozen['forecast_mask_count'] = 62321
    elif problem == 'D':
        f.mode['complete_D_count'] = 62321
    elif problem == 'raw_inventory':
        f.frozen['raw_inventory']['sha256'] = '0' * 64
    elif problem == 'missing_case':
        f.publics.pop('FM-C09')
    elif problem == 'input':
        Path(f.mode['input']['path']).write_bytes(b'changed workbook')
    elif problem == 'goal':
        f.e.GOAL_SHA = '0' * 64
    elif problem == 'brief':
        f.brief.write_bytes(b'changed brief')
    else:
        f.mode['controls']['missed_root'] = 1
    with pytest.raises((ValueError, KeyError)):
        f.e._checked_engineering(f.terminal)


@pytest.fixture
def isolated_history(material, monkeypatch, tmp_path):
    e = material.e
    original = e.history_helper()
    private = dict(vars(original))
    roots = (tmp_path / 'history/difficulty', tmp_path / 'history/research')
    for root in roots:
        root.mkdir(parents=True)
    private['HISTORY_ROOTS'] = roots
    for name, value in list(private.items()):
        if isinstance(value, FunctionType) and value.__globals__ is vars(original):
            clone = FunctionType(value.__code__, private, name, value.__defaults__, value.__closure__)
            clone.__kwdefaults__ = deepcopy(value.__kwdefaults__)
            private[name] = clone
    helper = SimpleNamespace(**private)
    monkeypatch.setitem(e._N, 'history_helper', lambda: helper)
    monkeypatch.setitem(e._N, 'recipes', lambda: {'TEST_ONLY/test_recipe': {'sha256': 'a' * 64}})
    monkeypatch.setitem(e._N, 'verify_local_base_image', lambda *a: pytest.fail('No Docker in preparation'))
    monkeypatch.setattr(e.runner, 'run_evaluation', lambda *a, **k: pytest.fail('No model in preparation'))
    return material


def test_real17file_export_preserves_C02_bytes_and_no_qualification(isolated_history, tmp_path):
    f = isolated_history
    output = tmp_path / 'prepared'
    frozen = f.e._N['read'](f.e.prepare(f.terminal, output))
    record = frozen['modes']['financial_modeling']
    export = Path(record['export_directory'])
    assert len([p for p in export.rglob('*') if p.is_file()]) == 17
    assert (export / 'environment/input.xlsx').read_bytes() == Path(f.mode['input']['path']).read_bytes()
    assert (export / 'tests/reference.xlsx').read_bytes() == Path(f.mode['goal']['path']).read_bytes()
    appendix = b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
    assert (export / 'instruction.md').read_bytes() == f.brief.read_bytes() + appendix
    assert frozen['kind'] == f.e.KIND and frozen['mode_order'] == ['financial_modeling']
    assert frozen['model'] == 'gpt-6.1-sol' and frozen['reasoning_effort'] == 'xhigh'
    assert frozen['effective_outer_retries'] == 0
    assert frozen['model_calls_during_preparation'] == frozen['LO_calls_during_preparation'] == 0
    assert not frozen['qualified'] and not frozen['normal_all12_QA_passed']
    assert f.e.validate_prepared(output) == frozen


def test_global_reservation_survives_rename_and_zip_repack(isolated_history, tmp_path):
    f = isolated_history
    e = f.e
    output = tmp_path / 'prepared'
    frozen = e._N['read'](e.prepare(f.terminal, output))
    repacked = tmp_path / 'renamed_input.xlsx'
    with zipfile.ZipFile(f.mode['input']['path']) as src:
        with zipfile.ZipFile(repacked, 'w', zipfile.ZIP_STORED) as dst:
            dst.comment = b'Equivalent material in another archive'
            for member in src.infolist():
                dst.writestr(member, src.read(member.filename))
    _, candidate = e._checked_engineering(f.terminal)
    _, rendered = e._instruction(candidate, 'financial_modeling')
    identity = e.content_identity('financial_modeling', e._N['ref'](repacked), f.mode['goal'], rendered)
    assert identity == frozen['modes']['financial_modeling']['material_task_version']
    started = e.reserve(output, frozen, 'financial_modeling', tmp_path / 'first')
    assert e._N['read'](started)['outer_retries'] == 0
    renamed = tmp_path / 'renamed_preparation'
    renamed.mkdir()
    with pytest.raises(ValueError, match='permanent first attempt'):
        e.reserve(renamed, frozen, 'financial_modeling', tmp_path / 'second')


def test_original_runner_history_and_reservation_code_stay_unchanged(entry):
    loader = importlib.util.spec_from_file_location('_original_FM_first_v6_compare', entry.BASE)
    old = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(old)
    for name in ('reserve', 'content_identity', 'run_development', 'effective_score'):
        current, prior = getattr(entry, name), getattr(old, name)
        assert current.__code__.co_code == prior.__code__.co_code
        assert current.__globals__ is entry._N and current.__globals__ is not prior.__globals__
    assert old._N['VALIDATOR'] != entry._N['VALIDATOR']
