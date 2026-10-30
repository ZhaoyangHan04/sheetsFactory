"""Offline mixed-mode routing. Mocks do not certify source financial admission."""
from copy import deepcopy
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.task_adapters import full_state_joint_cohort as cohort

ROOT = Path(__file__).resolve().parents[1]


def context(mode, backend='full_graph_v2'):
    saved = {}
    config = {cohort.SETTING: cohort.setting(debug_backend=backend),
        'construction': {'authoring_backend': 'composite_template', 'planning_scope': 'per_mode'},
        cohort.fm.POLICY: {'version': 1, 'policy': cohort.scope.reference(
            ROOT / 'config/task_adapters/composite_full_state_fm_v1.json')},
        cohort.joint_controls.SETTING: cohort.joint_controls.setting(),
        cohort.v2.JOINT_SETTING: {'enabled': True, 'contract': cohort.v2.JOINT_METHOD},
        cohort.v3.SETTING: {'enabled': True}}
    evidence = {'complete_source_evidence': {'private_reference': 'preserved'}}
    if mode == 'debugging':
        if backend == 'full_graph_v2': evidence['task_adapter'] = {'id': cohort.v2.ADAPTER}
        else: evidence['mutation_provider'] = {'id': cohort.v3.PROVIDER_ID}
    return SimpleNamespace(mode=mode, config=config, data={'source_id': 'offline-source', 'finance_evidence': evidence},
        save=lambda name, value: saved.setdefault(name, value), saved=saved)


def proposed(mode, *, mask_field=False):
    plan = {'public_instruction': 'Offline fixture. ' + cohort.scope.CLAUSES[mode],
        'public_rules': [cohort.fm.RULE], 'edits': [{'sheet': 'Model', 'cell': 'C3', 'before': '=1', 'after': '=2'}],
        'family_adapter': {'id': cohort.v2.ADAPTER}}
    if mask_field:
        plan['mask_ranges'] = [] if mode == 'debugging' else [{'sheet': 'Model', 'range': 'C3'}]
    return {'plan': plan, 'source_assessment': {'financial_evidence': {'all_private_paths': ['unchanged']}}}


@pytest.mark.parametrize('backend', cohort.BACKENDS)
def test_fm_plan_delegates_only_to_frozen_full_state_provider(monkeypatch, backend):
    ctx = context('financial_modeling', backend)
    result = proposed(ctx.mode, mask_field=True); before = deepcopy(result)
    called = []
    monkeypatch.setattr(cohort.fm.FullStateFMPlanNode, 'execute', lambda self, actual: called.append(actual) or result)
    monkeypatch.setattr(cohort.scope.ScopeFullGraphPlanNode, 'execute', lambda *a: pytest.fail('DBG provider called for FM'))
    monkeypatch.setattr(cohort.v3.SemanticGraphPlanNode, 'execute', lambda *a: pytest.fail('V3 provider called for FM'))
    assert cohort.FullStateJointPlanNode().execute(ctx) is result
    assert result == before and called == [ctx]
    assert ctx.saved['full_state_joint_plan_dispatch.json']['quality_or_difficulty_certified'] is False


def test_v2_removes_only_empty_fm_metadata_and_preserves_complete_evidence(monkeypatch):
    ctx = context('debugging'); result = proposed(ctx.mode, mask_field=True); before = deepcopy(result)
    monkeypatch.setattr(cohort.scope.ScopeFullGraphPlanNode, 'execute', lambda self, actual: result)
    output = cohort.FullStateJointPlanNode().execute(ctx)
    assert result == before and 'mask_ranges' not in output['plan']
    assert output['source_assessment'] is result['source_assessment']
    assert {k: v for k, v in before['plan'].items() if k != 'mask_ranges'} == output['plan']
    assert output['plan']['edits'] == before['plan']['edits']
    assert ctx.saved['full_state_joint_plan_dispatch.json']['removed_empty_FM_only_range_field'] is True


def test_v2_result_passes_actual_factory_target_claim_path(monkeypatch):
    ctx = context('debugging'); result = proposed(ctx.mode, mask_field=True)
    monkeypatch.setattr(cohort.scope.ScopeFullGraphPlanNode, 'execute', lambda self, actual: result)
    ctx.data['plan'] = cohort.FullStateJointPlanNode().execute(ctx)['plan']
    ctx.task_id = 'offline-dbg'; ctx.config['run'] = {}
    pipeline = object.__new__(FactoryPipeline)
    pipeline.config, pipeline.lock, pipeline.target_claims = ctx.config, RLock(), {}
    pipeline.audit = SimpleNamespace(snapshot=lambda: {'tasks': []}, task=lambda *a, **kw: None)
    pipeline._claim_targets(ctx)
    assert len(pipeline.target_claims) == 1 and ctx.data['target_fingerprint']


def test_v3_plan_uses_its_separate_frozen_provider(monkeypatch):
    ctx = context('debugging', 'semantic_graph_v3'); result = proposed(ctx.mode)
    monkeypatch.setattr(cohort.v3.SemanticGraphPlanNode, 'execute', lambda self, actual: result)
    monkeypatch.setattr(cohort.scope.ScopeFullGraphPlanNode, 'execute', lambda *a: pytest.fail('V2 provider called for V3'))
    assert cohort.FullStateJointPlanNode().execute(ctx) is result


@pytest.mark.parametrize('value', [None, {}, True, ['C3'], [{'sheet': 'Model', 'range': 'C3'}]])
def test_v2_cannot_drop_nonempty_or_malformed_mask_metadata(monkeypatch, value):
    ctx = context('debugging'); result = proposed(ctx.mode)
    result['plan']['mask_ranges'] = value
    monkeypatch.setattr(cohort.scope.ScopeFullGraphPlanNode, 'execute', lambda self, actual: result)
    with pytest.raises(ValueError, match='cannot declare FM mask ranges'):
        cohort.FullStateJointPlanNode().execute(ctx)


def test_v3_cannot_return_any_fm_mask_field(monkeypatch):
    ctx = context('debugging', 'semantic_graph_v3'); result = proposed(ctx.mode, mask_field=True)
    monkeypatch.setattr(cohort.v3.SemanticGraphPlanNode, 'execute', lambda self, actual: result)
    with pytest.raises(ValueError, match='FM-only mask field'):
        cohort.FullStateJointPlanNode().execute(ctx)


@pytest.mark.parametrize('mode,backend,expected', [
    ('financial_modeling', 'full_graph_v2', 'normal'), ('financial_modeling', 'semantic_graph_v3', 'normal'),
    ('debugging', 'full_graph_v2', 'v2'), ('debugging', 'semantic_graph_v3', 'v3')])
def test_construct_delegates_exactly_one_existing_body(monkeypatch, mode, backend, expected):
    ctx = context(mode, backend); called = []
    for cls, label in [(cohort.construction.ConstructNode, 'normal'),
                       (cohort.scc_activity.SCCConstructNode, 'v2'),
                       (cohort.v3.SemanticGraphConstructNode, 'v3')]:
        monkeypatch.setattr(cls, 'execute', lambda self, actual, label=label: called.append(label) or {'selected': label})
    assert cohort.FullStateJointConstructNode().execute(ctx) == {'selected': expected}
    assert called == [expected]


@pytest.mark.parametrize('mode,expected', [('financial_modeling', 'normal'), ('debugging', 'joint')])
def test_controls_keep_fm_original_and_dbg_observable(monkeypatch, mode, expected):
    ctx = context(mode); called = []
    monkeypatch.setattr(cohort.construction.ControlsNode, 'execute',
        lambda self, actual: called.append('normal') or {'selected': 'normal'})
    monkeypatch.setattr(cohort.joint_controls.JointObservableControlsNode, 'execute',
        lambda self, actual: called.append('joint') or {'selected': 'joint'})
    assert cohort.FullStateJointControlsNode().execute(ctx) == {'selected': expected}
    assert called == [expected]


@pytest.mark.parametrize('case', ['missing_optin', 'boolean_version', 'backend', 'implementation', 'dependency',
    'ordinary_DBG_seed', 'wrong_provider', 'missing_fullstate', 'FM_with_DBG_provider', 'missing_joint_controls', 'legacy_planning'])
def test_missing_or_changed_explicit_routing_fails_before_provider(case):
    mode = 'financial_modeling' if case in {'missing_fullstate', 'FM_with_DBG_provider'} else 'debugging'
    ctx = context(mode)
    if case == 'missing_optin': ctx.config.pop(cohort.SETTING)
    elif case == 'boolean_version': ctx.config[cohort.SETTING]['version'] = True
    elif case == 'backend': ctx.config[cohort.SETTING]['debug_backend'] = 'automatic'
    elif case == 'implementation': ctx.config[cohort.SETTING]['implementation']['sha256'] = '0' * 64
    elif case == 'dependency': ctx.config[cohort.SETTING]['dependencies']['normal_factory']['sha256'] = '0' * 64
    elif case == 'ordinary_DBG_seed': ctx.data['finance_evidence'].pop('task_adapter')
    elif case == 'wrong_provider': ctx.data['finance_evidence']['task_adapter']['id'] = cohort.v3.PROVIDER_ID
    elif case == 'missing_fullstate': ctx.config.pop(cohort.fm.POLICY)
    elif case == 'FM_with_DBG_provider': ctx.data['finance_evidence']['task_adapter'] = {'id': cohort.v2.ADAPTER}
    elif case == 'missing_joint_controls': ctx.config.pop(cohort.joint_controls.SETTING)
    elif case == 'legacy_planning': ctx.config['construction']['planning_scope'] = 'both_modes'
    with pytest.raises(ValueError):
        cohort.route(ctx)
    assert not ctx.saved


def test_registry_changes_only_the_three_explicit_mode_dispatch_nodes():
    base = yaml.safe_load((ROOT / 'config/task_adapters/composite_full_state_fm_nodes.yaml').read_text())['nodes']
    new = yaml.safe_load((ROOT / 'config/task_adapters/full_state_joint_cohort_nodes.yaml').read_text())['nodes']
    assert len(new) == len(base) == 11
    assert {name for name in base if base[name] != new[name]} == {'plan', 'construct', 'precheck'}
    assert all(new[name] == base[name] for name in ('normalize', 'profile', 'instruction',
        'independent_recovery', 'trajectory', 'diagnose', 'repair', 'export'))
