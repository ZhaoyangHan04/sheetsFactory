"""Standard planning integration with explicit, non-engine test fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes.construction import PlanNode
from sheets_factory.workbook.composite_finance import activity, debugging, tasks


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class Audit:
    def __init__(self):
        self.events = []

    def emit(self, kind, **values):
        self.events.append((kind, values))


class NoModels:
    def complete(self, *args, **kwargs):
        raise AssertionError('Deterministic composite planning must not call a model')


class FixtureEngine:
    def metadata(self):
        return {'backend': 'libreoffice_uno_docker', 'network': 'none',
                'image_id': 'sha256:' + 'a' * 64}


@pytest.fixture
def planning(tmp_path, monkeypatch):
    baseline = tmp_path / 'baseline.xlsx'
    baseline.write_bytes(b'Explicit planning integration fixture; not an Excel execution')
    cache = tmp_path / 'source-cache'
    cache.mkdir()
    proposed = {'title': 'Semantic fixture', 'public_instruction': 'Fixture only',
        'edits': [{'sheet': 'Financial', 'cell': 'C' + str(i), 'before': '=1+2',
                   'after': '=1+3', 'mechanism': 'fixture_' + str(i)} for i in (3, 4, 5)]}
    observed = {'proposals': [], 'screen': [], 'groups': [], 'blocked': False}

    def propose(path, mode):
        observed['proposals'].append((path, mode))
        return deepcopy(proposed)

    def screen(path, proposal, *, engine, directory, **options):
        observed['screen'].append({'path': path, 'proposal': deepcopy(proposal), **options})
        directory.mkdir(parents=True, exist_ok=False)
        screened = deepcopy(proposal)
        screened['edits'] = screened['edits'][:2]
        screened['activity_authoring'] = {'authoring_attempts_used': 2,
                                        'max_authoring_attempts': options['max_authoring_attempts']}
        raw, output = directory / 'fixture_raw.xlsx', directory / 'fixture_output.xlsx'
        raw.write_bytes(b'Explicit test fixture raw; no LO performed')
        output.write_bytes(b'Explicit test fixture output; no LO performed')
        receipt = {'passed': not observed['blocked'], 'blocking': observed['blocked'],
            'state': 'rejected' if observed['blocked'] else 'passed',
            'reason': 'explicit fixture rejection' if observed['blocked'] else None,
            'baseline_sha256': _sha(path), 'before_plan_sha256': _canonical(proposal),
            'after_plan_sha256': _canonical(screened),
            'implementation_sha256': _sha(activity.__file__),
            'engine': engine.metadata(), 'actual_LO_execution_count': 3,
            'authoring_attempts_used': 2,
            'engine_calls': [{'raw_path': str(raw), 'raw_sha256': _sha(raw),
                             'output_path': str(output), 'output_sha256': _sha(output)}],
            'fixture_only': True}
        receipt_path = directory / 'activity_receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        (directory / 'screened_plan.json').write_text(json.dumps(screened))
        return {'receipt': receipt, 'plan': screened, 'receipt_path': str(receipt_path)}

    def group(path, edits, **options):
        observed['groups'].append({'path': path, 'edits': deepcopy(edits), **options})
        return {'root_impact_batches': [list(range(len(edits)))], 'planning_only': True,
                'actual_LO_executions': 0}

    monkeypatch.setattr(tasks, 'propose_task', propose)
    monkeypatch.setattr(activity, 'screen_composite_activity', screen)
    monkeypatch.setattr(debugging, 'suggest_root_impact_batches', group)
    config = {'construction': {'authoring_backend': 'composite_template', 'planning_scope': 'per_mode',
        'root_impact_validation': 'batched_separated_roots',
        'analysis_limits': {'max_dependency_closure_cells': 500000,
                            'per_formula_reference_cells': 50000}}}
    ctx = TaskContext('run', 'dbg-fixture', 'debugging', baseline, tmp_path / 'task',
        config, Audit(), NoModels(), FixtureEngine(), data={'baseline': baseline,
            'source_cache': cache, 'finance_evidence': {'financial_seed_verified': True}})
    return ctx, observed, proposed


def test_default_screen_regroups_retained_roots_without_changing_proposal_or_config(planning):
    ctx, observed, proposed = planning
    original_config = deepcopy(ctx.config)
    result = PlanNode().execute(ctx)
    plan = result['plan']
    assert plan['edits'] == proposed['edits'][:2]
    assert plan['root_impact_batches'] == [[0, 1]]
    assert plan['activity_authoring']['authoring_attempts_used'] == 2
    assert plan['root_impact_batch_planning']['planning_only'] is True
    assert len(observed['screen']) == len(observed['groups']) == 1
    call = observed['screen'][0]
    assert call['max_dependency_cells'] == 500000
    assert call['per_formula_reference_cells'] == 50000
    assert call['max_authoring_attempts'] == 3 and call['execute_fallback'] is False
    assert observed['groups'][0]['edits'] == plan['edits']
    raw = ctx.data['source_cache'] / 'task_plans_v0_debugging_composite_template.json'
    assert json.loads(raw.read_text())['debugging'] == proposed
    assert ctx.config == original_config
    assert ctx.config['construction']['root_impact_validation'] == 'batched_separated_roots'
    event = [item[1] for item in ctx.audit.events if item[0] == 'planning.composite_activity'][-1]
    assert event['cache_hit'] is False and event['llm_calls'] == 0
    assert event['actual_LO_calls_this_invocation'] == 3
    assert event['retained_roots'] == 2


def test_hash_bound_cached_screen_does_not_repeat_engine_or_grouping_calls(planning):
    ctx, observed, _ = planning
    first = PlanNode().execute(ctx)
    raw = next(ctx.data['source_cache'].glob('task_plans_v*.json'))
    original_bytes = raw.read_bytes()
    second = PlanNode().execute(ctx)
    assert second == first
    assert len(observed['proposals']) == len(observed['screen']) == len(observed['groups']) == 1
    assert raw.read_bytes() == original_bytes
    event = ctx.audit.events[-1][1]
    assert event['cache_hit'] is True
    assert event['actual_LO_calls_this_invocation'] == 0
    assert event['actual_LO_calls_in_evidence'] == 3


@pytest.mark.parametrize('artifact', ['receipt', 'activity_plan', 'grouped_plan', 'batch_planning'])
def test_cached_artifact_tampering_rejects_without_new_execution(planning, artifact):
    ctx, observed, _ = planning
    PlanNode().execute(ctx)
    cache = json.loads(next(ctx.data['source_cache'].glob('composite_activity_*.json')).read_text())
    Path(cache['files'][artifact]['path']).write_text('{}')
    with pytest.raises(TaskRejected, match='artifact changed'):
        PlanNode().execute(ctx)
    assert len(observed['screen']) == 1


@pytest.mark.parametrize('change', ['changed', 'missing'])
def test_executed_workbook_evidence_is_rechecked_on_cache_hit(planning, change):
    ctx, observed, _ = planning
    PlanNode().execute(ctx)
    path = next(ctx.revision_dir.rglob('fixture_output.xlsx'))
    path.write_bytes(b'changed') if change == 'changed' else path.unlink()
    with pytest.raises(TaskRejected, match='executed workbook changed'):
        PlanNode().execute(ctx)
    assert len(observed['screen']) == 1


def test_failed_activity_keeps_private_failure_and_raw_proposal_without_success_cache(planning):
    ctx, observed, proposed = planning
    observed['blocked'] = True
    with pytest.raises(TaskRejected, match='explicit fixture rejection'):
        PlanNode().execute(ctx)
    saved = json.loads((ctx.revision_dir / 'private/composite_activity_result.json').read_text())
    assert saved['blocking'] is True and saved['passed'] is False
    raw = next(ctx.data['source_cache'].glob('task_plans_v*.json'))
    assert json.loads(raw.read_text())['debugging'] == proposed
    assert not list(ctx.data['source_cache'].glob('composite_activity_*.json'))
    assert not observed['groups']


def test_explicit_disable_still_requires_normal_actual_root_proof(planning):
    ctx, observed, proposed = planning
    ctx.config['construction']['composite_activity'] = {'enabled': False}
    result = PlanNode().execute(ctx)
    assert result['plan']['edits'] == proposed['edits']
    assert not observed['screen'] and len(observed['groups']) == 1
    event = ctx.audit.events[-1][1]
    assert event['screening_certified'] is False
    assert 'mandatory' in event['required_next_step']


@pytest.mark.parametrize('settings', [[], {'skip_all': True}, {'enabled': 1},
    {'max_authoring_attempts': 4}, {'max_authoring_attempts': True}, {'execute_fallback': 'yes'}])
def test_invalid_activity_configuration_is_rejected(planning, settings):
    ctx, observed, _ = planning
    ctx.config['construction']['composite_activity'] = settings
    with pytest.raises(ValueError):
        PlanNode().execute(ctx)
    assert not observed['screen']


def test_financial_modeling_does_not_run_activity_or_grouping(planning):
    ctx, observed, proposed = planning
    ctx.mode = 'financial_modeling'
    assert PlanNode().execute(ctx)['plan'] == proposed
    assert not observed['screen'] and not observed['groups']


def test_debugging_dispatch_uses_semantic_adapter_before_loading_workbook(tmp_path, monkeypatch):
    # Restore the real dispatcher independently of the planning fixture above.
    calls = []
    monkeypatch.setattr(debugging, 'propose_task', lambda path, mode: calls.append((path, mode)) or {'edits': []})
    missing = tmp_path / 'no-workbook-needed.xlsx'
    assert tasks.propose_task(missing, mode='debugging') == {'edits': []}
    assert calls == [(missing, 'debugging')]
