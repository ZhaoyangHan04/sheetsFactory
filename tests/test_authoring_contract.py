"""Planner/repair share unchanged executor limits and actual read-only artifacts."""
import json
import hashlib
from pathlib import Path

from openpyxl import Workbook
import pytest

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes.construction import PlanNode, construction_contract, validate_plan, authoring_source_context
from sheets_factory.nodes.quality import RepairNode

ROOT = Path(__file__).resolve().parents[1]


def context(tmp_path, backend):
    source = tmp_path / 'real source name.xlsx'
    book = Workbook()
    book.save(source)
    cache = tmp_path / 'source_cache'
    cache.mkdir()
    baseline = cache / 'baseline.xlsx'
    book.save(baseline)
    profile = {'sheet_count': 4, 'nonempty_sheet_count': 4, 'formula_count': 10,
               'errors': [], 'external_references': [], 'sheets': [],
               'full_profile_only_fact': 'This fact must be read from the full artifact, not guessed from the compact index.'}
    (cache / 'profile.json').write_text(json.dumps(profile))
    ctx = TaskContext('fixture', 'fm-fixture', 'financial_modeling', source, tmp_path / 'task',
        {'project_root': str(ROOT), 'run': {'max_steps': 3}, 'agents': {'timeout_seconds': 1}},
        None, backend, None)
    ctx.data.update(baseline=baseline, source_cache=cache, profile=profile, variant=0,
        plan={'public_instruction': 'Fixture instruction.', 'edits': []})
    return ctx


def test_plan_and_repair_share_contract_and_absolute_real_artifact_paths(tmp_path):
    captured = []
    class Backend:
        def complete(self, text, **kwargs):
            payload = json.loads(text.rsplit('\nINPUT JSON:\n', 1)[1])
            captured.append((kwargs['role'], payload, text))
            if kwargs['role'] == 'planner':
                return {'financial_modeling': {'title': 'Fixture authoring context only', 'edits': []},
                        'source_assessment': {}}
            return {'repaired_task': None, 'reason': 'No supported module in this fixture.'}
    ctx = context(tmp_path, Backend())
    PlanNode().execute(ctx)
    ctx.data.update(diagnosis={'issues': [{'issue_id': 'q06-a', 'problem_id': 'Q06', 'certainty': 'confirmed'}]},
                    repair_routes=[{'issue_id': 'q06-a', 'problem_id': 'Q06', 'route_class': 'repair'}])
    RepairNode().execute(ctx)
    assert [role for role, _, _ in captured] == ['planner', 'repair_planner']
    planner, repair = captured[0][1], captured[1][1]
    assert planner['construction_contract']['modes'] == repair['construction_contract']['modes']
    assert planner['construction_contract']['scenario_inputs'] == repair['construction_contract']['scenario_inputs']
    assert repair['construction_contract']['active_mode'] == 'financial_modeling'
    for payload in (planner, repair):
        assert payload['source_file'] == 'real source name.xlsx'
        assert Path(payload['source_path']) == ctx.source.resolve()
        assert payload['source_sha256'] == hashlib.sha256(ctx.source.read_bytes()).hexdigest()
        assert Path(payload['native_risk_registry_path']) == ROOT / 'data/manifests/native_risks.json'
        assert payload['native_risk_registry_available']
        assert Path(payload['baseline_path']) == ctx.data['baseline'].resolve()
        assert payload['baseline_is_immutable'] and payload['full_profile_available']
        full_path = Path(payload['full_profile_path'])
        assert full_path.is_absolute() and full_path.is_file()
        assert 'full_profile_only_fact' in json.loads(full_path.read_text())
        assert Path(payload['python_executable']).is_absolute() and Path(payload['python_executable']).is_file()
    assert 'compact source_profile is only an index' in captured[1][2]
    assert 'financial_modeling requires 6 through 80' in captured[1][2]  # Compatibility with older producers.


def test_author_context_respects_configured_risk_registry_without_inventing_files(tmp_path):
    ctx = context(tmp_path, None)
    ctx.config['native_risks'] = {'registry_path': str(tmp_path / 'absent_registry.json')}
    payload = authoring_source_context(ctx)
    assert payload['native_risk_registry_path'] == str(tmp_path / 'absent_registry.json')
    assert payload['native_risk_registry_available'] is False


@pytest.mark.parametrize('mode,actual,minimum', [('financial_modeling', 5, 6), ('financial_modeling', 81, 6),
                                               ('debugging', 1, 2), ('debugging', 81, 2)])
def test_count_rejection_reports_actionable_actual_minimum_and_maximum(mode, actual, minimum):
    with pytest.raises(TaskRejected) as error:
        validate_plan({'edits': [{} for _ in range(actual)]}, '/never-opened-because-count-invalid.xlsx', mode)
    message = str(error.value)
    assert f'actual={actual}' in message and f'min={minimum}' in message and 'max=80' in message
    assert f'mode={mode}' in message


def test_machine_contract_preserves_current_thresholds_and_distinguishes_preferences():
    contract = construction_contract()
    assert contract['modes']['financial_modeling']['edit_count'] == {'min': 6, 'max': 80}
    assert contract['modes']['debugging']['edit_count'] == {'min': 2, 'max': 80}
    assert contract['scenario_inputs']['max_count'] == 40
    assert contract['dependency_requirements']['max_dependency_closure_cells'] == 20000
    assert contract['source_requirements'] == {'min_nonempty_sheets': 4, 'min_formula_count': 6,
                                              'max_profile_cells': 200000}
    assert contract['planning_preferences_only']['financial_modeling_edit_count'] == [6, 20]
    assert contract['planning_preferences_only']['debugging_edit_count'] == [2, 4]
    contract['modes']['financial_modeling']['edit_count']['min'] = 0
    assert construction_contract()['modes']['financial_modeling']['edit_count']['min'] == 6
