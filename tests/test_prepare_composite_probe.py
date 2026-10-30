"""Offline routing checks; fixture nodes do not execute LibreOffice or models."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

from openpyxl import Workbook
import pytest

from sheets_factory.core.node import BaseNode, TaskRejected
from sheets_factory.workbook.composite_finance import activity, debugging, tasks


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('prepare_composite_probe_fixture', ROOT / 'scripts/prepare_composite_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / 'source'
    directory.mkdir()
    baseline = directory / 'baseline.xlsx'
    book = Workbook()
    book.active.title = 'Financial'
    for i in range(1, 226):
        book.active.cell(i, 1, '=1+2')
    book.save(baseline)
    book.close()
    refs = {}
    for name in ('financial_audit', 'stability', 'public_scenarios'):
        path = directory / (name + '.json')
        path.write_text(json.dumps({'stable': True, 'fixture_only': True}))
        refs[name] = {'path': str(path), 'sha256': probe.sha(path)}
    manifest = directory / 'seed_manifest.json'
    manifest.write_text(json.dumps({'status': 'independently_verified_composed_financial_seed',
        'financial_audit_passed': True, 'financial_audits': {'fixture': {'passed': True}},
        **refs, 'selected': [{'sha256': probe.sha(baseline), 'local_path': str(baseline),
            'finance_evidence': {'financial_seed_verified': True}}]}))
    return manifest


@pytest.fixture
def offline(monkeypatch):
    observed = {'proposals': [], 'screens': [], 'constructs': [], 'controls': dict(probe.CONTROL_REWARDS),
                'blocked': False}

    class Engine:
        def __init__(self, *args, **kwargs):
            pass

        def metadata(self):
            return {'image_id': probe.RUNTIME_ID, 'backend': 'offline_fixture_not_libreoffice'}

    class Profile(BaseNode):
        node_id = 'profile'

        def execute(self, ctx):
            return {'profile': {'fixture_only': True}}

    class Construct(BaseNode):
        node_id = 'construct'

        def execute(self, ctx):
            observed['constructs'].append({'plan': deepcopy(ctx.data['plan']), 'config': deepcopy(ctx.config)})
            public, private = ctx.revision_dir / 'public', ctx.revision_dir / 'private'
            public.mkdir(parents=True, exist_ok=True)
            private.mkdir(parents=True, exist_ok=True)
            goal, input_file = private / 'goal.xlsx', public / 'input.xlsx'
            shutil.copy2(ctx.data['baseline'], goal)
            shutil.copy2(ctx.data['baseline'], input_file)
            return {'goal': goal, 'input': input_file,
                    'delta': {'expected_change_count': len(ctx.data['plan']['edits'])}}

    class Controls(BaseNode):
        node_id = 'precheck'

        def execute(self, ctx):
            return {'controls': {name: {'reward': reward, 'fixture_only': True}
                                 for name, reward in observed['controls'].items()}}

    def propose(path, mode):
        observed['proposals'].append((str(path), mode))
        return {'title': 'Explicit test fixture', 'public_instruction': 'Restore the financial model.',
            'public_rules': ['Use the stated policies.'], 'reference_evidence': ['Fixture source'],
            'edits': [{'sheet': 'Financial', 'cell': 'A' + str(i), 'before': '=1+2',
                       'after': '=1+3' if mode == 'debugging' else None} for i in range(1, 226)]}

    def screen(path, proposal, *, engine, directory, **options):
        observed['screens'].append(deepcopy(proposal))
        directory.mkdir(parents=True)
        plan = deepcopy(proposal)
        plan['edits'] = plan['edits'][:150]
        receipt = {'passed': not observed['blocked'], 'blocking': observed['blocked'],
            'state': 'rejected' if observed['blocked'] else 'screened', 'reason': 'fixture activity outcome',
            'baseline_sha256': probe.sha(path), 'before_plan_sha256': canonical(proposal),
            'after_plan_sha256': canonical(plan), 'implementation_sha256': probe.sha(activity.__file__),
            'engine': engine.metadata(), 'actual_LO_execution_count': 0,
            'authoring_attempts_used': 1, 'engine_calls': [], 'fixture_only': True}
        (directory / 'screened_plan.json').write_text(json.dumps(plan))
        receipt_path = directory / 'activity_receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        return {'plan': plan, 'receipt': receipt, 'receipt_path': str(receipt_path)}

    monkeypatch.setattr(probe, 'LibreOfficeEngine', Engine)
    monkeypatch.setattr(probe, 'ProfileNode', Profile)
    monkeypatch.setattr(probe, 'ConstructNode', Construct)
    monkeypatch.setattr(probe, 'ControlsNode', Controls)
    monkeypatch.setattr(probe, 'propose_task', propose)
    monkeypatch.setattr(tasks, 'propose_task', propose)
    monkeypatch.setattr(activity, 'screen_composite_activity', screen)
    monkeypatch.setattr(debugging, 'suggest_root_impact_batches', lambda path, edits, **kw: {
        'root_impact_batches': [list(range(len(edits)))], 'planning_only': True})
    return observed


@pytest.mark.parametrize('mode', ['financial_modeling', 'debugging'])
def test_default_preparation_preserves_direct_proposal_and_strict_controls(tmp_path, source, offline, mode):
    before = {path: path.read_bytes() for path in source.parent.iterdir()}
    result = probe.prepare(source, tmp_path / 'prepared', mode)
    assert not offline['screens'] and len(offline['proposals']) == 1
    assert len(offline['constructs'][0]['plan']['edits']) == 225
    assert offline['constructs'][0]['config']['construction']['root_impact_validation'] == 'strict'
    assert offline['constructs'][0]['config']['construction']['authoring_backend'] == 'llm'
    assert result['planning_origin']['path'].endswith('task_plans_v0_' + mode + '.json')
    assert result['local_controls'] == probe.CONTROL_REWARDS and result['qualified'] is False
    assert result['task_count'] == result['llm_calls'] == 0
    assert 'activity_origin' not in result and 'root_impact_validation' not in result
    assert all(path.read_bytes() == data for path, data in before.items())


def test_explicit_debugging_activity_uses_normal_plan_node_and_freezes_screened_origin(tmp_path, source, offline):
    progress = []
    result = probe.prepare(source, tmp_path / 'prepared', 'debugging',
        root_impact_validation='shadow_roots', composite_activity=True,
        progress=lambda **event: progress.append(event))
    assert len(offline['proposals']) == len(offline['screens']) == 1
    assert len(offline['screens'][0]['edits']) == 225
    construct = offline['constructs'][0]
    assert len(construct['plan']['edits']) == 150
    assert construct['config']['construction']['authoring_backend'] == 'composite_template'
    assert construct['config']['construction']['planning_scope'] == 'per_mode'
    assert construct['config']['construction']['root_impact_validation'] == 'shadow_roots'
    assert result['planning_origin']['kind'] == 'final_screened_composite_template_plan'
    final = json.loads(Path(result['planning_origin']['path']).read_text())['debugging']
    raw = json.loads(Path(result['proposal_origin']['path']).read_text())['debugging']
    assert final == construct['plan'] and len(raw['edits']) == 225
    assert probe.sha(result['planning_origin']['path']) == result['planning_origin']['sha256']
    assert Path(result['activity_origin']['path']).is_file()
    assert [event['node'] for event in progress if event['status'] == 'running'] == [
        'profile', 'plan', 'construct', 'instruction', 'precheck']
    assert result['qualified'] is False and result['model_evaluation_performed'] is False
    assert result['llm_calls'] == 0


@pytest.mark.parametrize('options', [
    {'mode': 'financial_modeling', 'composite_activity': True},
    {'mode': 'financial_modeling', 'root_impact_validation': 'shadow_roots'},
    {'mode': 'debugging', 'composite_activity': 1},
    {'mode': 'debugging', 'root_impact_validation': 'pretend'}, {'mode': 'unknown'},
])
def test_invalid_or_modeling_activity_options_reject_before_work(tmp_path, source, offline, options):
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError):
        probe.prepare(source, output, **options)
    assert not output.exists() and not offline['proposals'] and not offline['constructs']


def test_failed_screen_preserves_receipt_and_prevents_construction_or_export(tmp_path, source, offline):
    offline['blocked'] = True
    output = tmp_path / 'prepared'
    with pytest.raises(TaskRejected, match='fixture activity outcome'):
        probe.prepare(source, output, 'debugging', composite_activity=True, root_impact_validation='shadow_roots')
    assert not offline['constructs'] and not (output / 'SpreadsheetEval').exists()
    assert (output / 'preparation_failure.json').is_file()
    assert next(output.rglob('composite_activity_result.json')).is_file()
    assert len(json.loads(next(output.rglob('task_plans_v0_debugging_composite_template.json')).read_text())['debugging']['edits']) == 225


def test_failed_actual_control_cannot_create_export_or_success_manifest(tmp_path, source, offline):
    offline['controls']['nop'] = 1
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='controls failed'):
        probe.prepare(source, output)
    assert not (output / 'SpreadsheetEval').exists() and not (output / 'probe_manifest.json').exists()
    assert (output / 'preparation_failure.json').is_file()


def test_existing_output_is_not_overwritten(tmp_path, source, offline):
    output = tmp_path / 'prepared'
    output.mkdir()
    (output / 'keep').write_text('existing evidence')
    with pytest.raises(FileExistsError):
        probe.prepare(source, output)
    assert (output / 'keep').read_text() == 'existing evidence'
    assert not offline['proposals']
