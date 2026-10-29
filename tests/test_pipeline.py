"""Pipeline correctness tests without an API or a simulated passing engine.

Workbook caches are explicit fixture data. These tests validate orchestration and
contracts; they do not claim to exercise LibreOffice's calculation semantics.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

from openpyxl import Workbook
import pytest

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes.construction import InstructionNode, validate_plan
from sheets_factory.nodes.quality import RecoveryNode, TrajectoryNode


ROOT = Path(__file__).resolve().parents[1]
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def model_fixture(path):
    workbook = Workbook()
    forecast = workbook.active
    forecast.title = "Forecast"
    for row in range(1, 7):
        forecast.cell(row, 1, f"Period {row} revenue")
        forecast.cell(row, 2, f"=Inputs!B1*{row}")
    inputs = workbook.create_sheet("Inputs")
    inputs["A1"], inputs["B1"] = "Revenue per period", 10
    workbook.create_sheet("Budget")["A1"] = "Budget context"
    workbook.create_sheet("Notes")["A1"] = "Forecast assumptions"
    workbook.save(path)
    # These are known fixture caches, not an assertion that openpyxl calculated.
    with ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    for cell in sheet.findall(".//s:c", NS):
        if cell.find("s:f", NS) is not None:
            cell.find("s:v", NS).text = str(10 * int(cell.attrib["r"][1:]))
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def plan(mode="financial_modeling"):
    return {"title": "Restore the six-period revenue forecast", "public_instruction": "Complete the missing forecast formulas.",
            "public_rules": ["Period n revenue equals Inputs!B1 multiplied by the period number n."],
            "reference_evidence": ["Forecast row labels identify periods one through six."],
            "edits": [{"sheet": "Forecast", "cell": f"B{row}", "before": f"=Inputs!B1*{row}",
                       "after": None if mode == "financial_modeling" else f"=Inputs!B1*{row}+1"}
                      for row in range(1, 7 if mode == "financial_modeling" else 3)]}


class QuietAudit:
    def emit(self, *args, **kwargs):
        pass

    def task(self, *args, **kwargs):
        pass


class CopyEngine:
    """Only a file transport for control-flow tests, never a calculation engine."""

    def recalculate(self, source, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination


def context(tmp_path, llm=None):
    source = model_fixture(tmp_path / "baseline.xlsx")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    ctx = TaskContext("run-test", "fm-test", "financial_modeling", source, task_dir,
                      {"project_root": str(ROOT), "engine": {"image": "fixture-no-real-engine"},
                       "agents": {"timeout_seconds": 10, "trajectory_timeout_seconds": 10}},
                      QuietAudit(), llm, CopyEngine())
    (ctx.revision_dir / 'public').mkdir(parents=True)
    ctx.data.update(input=source, goal=source, instruction="Use public rules.", plan=plan())
    return ctx


def test_valid_source_backed_cross_sheet_mask_plan(tmp_path):
    source = model_fixture(tmp_path / "model.xlsx")
    result = validate_plan(plan(), source, "financial_modeling")
    assert result["edit_count"] == 6
    assert result["dependency_sheets"] == ["Forecast", "Inputs"]


@pytest.mark.parametrize("change", ["wrong_before", "duplicate", "nonexistent_sheet", "constant_target", "mask_not_clear"])
def test_invalid_edits_cannot_reach_construction(tmp_path, change):
    source = model_fixture(tmp_path / "model.xlsx")
    proposed = plan()
    if change == "wrong_before":
        proposed["edits"][0]["before"] = "=123"
    elif change == "duplicate":
        proposed["edits"][1] = deepcopy(proposed["edits"][0])
    elif change == "nonexistent_sheet":
        proposed["edits"][0]["sheet"] = "Invented"
    elif change == "constant_target":
        proposed["edits"][0].update(sheet="Inputs", cell="B1", before=10)
    else:
        proposed["edits"][0]["after"] = "=0"
    with pytest.raises(TaskRejected):
        validate_plan(proposed, source, "financial_modeling")


def test_missing_public_rule_or_reference_evidence_rejected(tmp_path):
    source = model_fixture(tmp_path / "model.xlsx")
    for field in ("public_instruction", "public_rules", "reference_evidence"):
        proposed = plan()
        proposed[field] = [] if field != "public_instruction" else ""
        with pytest.raises(TaskRejected):
            validate_plan(proposed, source, "financial_modeling")


def test_debugging_requires_real_formula_mutation(tmp_path):
    source = model_fixture(tmp_path / "model.xlsx")
    proposed = plan("debugging")
    proposed["edits"][0]["after"] = proposed["edits"][0]["before"]
    with pytest.raises(TaskRejected):
        validate_plan(proposed, source, "debugging")


@pytest.mark.parametrize("reply", ["partial result", "completed successfully"])
def test_every_natural_attempt_proceeds_with_ungraded_trace(tmp_path, reply):
    class Attempt:
        def attempt(self, *args, **kwargs):
            return {"events": [{"type": "tool.read", "cell": "Inputs!B1"}], "reply": reply,
                    "call_id": "call-x", "duration_ms": 5}

    ctx = context(tmp_path, Attempt())
    result = TrajectoryNode().execute(ctx)
    assert len(result["traces"]) == 1
    assert result["traces"][0]["reply"] == reply
    assert "reward" not in result["traces"][0]
    assert "solved" not in result["traces"][0]


def test_infrastructure_fault_is_preserved_as_evidence_not_solver_failure(tmp_path):
    class Broken:
        def attempt(self, *args, **kwargs):
            raise RuntimeError("container unavailable")

    ctx = context(tmp_path, Broken())
    result = TrajectoryNode().execute(ctx)
    assert result["traces"][0]["infrastructure_error"] == "container unavailable"


def test_recovery_without_program_is_not_verified(tmp_path):
    class ManualOutput:
        def complete(self, *args, **kwargs):
            return {"code": "", "assumptions_added": [], "unresolved_questions": []}

    ctx = context(tmp_path, ManualOutput())
    result = RecoveryNode().execute(ctx)
    assert not result["recovery"]["verified"]


def test_public_contract_rules_are_actually_visible_to_solver(tmp_path):
    ctx = context(tmp_path)
    result = InstructionNode().execute(ctx)
    assert ctx.data["plan"]["public_rules"][0] in result["instruction"]


def test_unrelated_recovery_program_cannot_certify_manual_output(tmp_path, monkeypatch):
    class EmptyProgram:
        def complete(self, *args, **kwargs):
            return {"code": "# This script produces no output.\npass\n",
                    "assumptions_added": [], "unresolved_questions": []}

    ctx = context(tmp_path, EmptyProgram())
    calls = []
    def replay_without_output(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr('sheets_factory.nodes.quality.subprocess.run', replay_without_output)
    result = RecoveryNode().execute(ctx)
    assert not result["recovery"]["verified"]
    assert calls and calls[0][calls[0].index('--network') + 1] == 'none'


def test_templates_and_registered_node_implementations_are_loadable(tmp_path):
    from sheets_factory.pipelines.factory import FactoryPipeline
    config = {'project_root': str(ROOT), 'run': {'targets': {'financial_modeling': 1, 'debugging': 1}}}
    pipeline = FactoryPipeline(config, QuietAudit(), None, None)
    assert pipeline.templates['financial_modeling']['phases']['revision'][-1] == 'diagnose'
    assert pipeline.load_node('construct').node_id == 'construct'


def test_numbered_routes_separate_evidence_infrastructure_and_content():
    from sheets_factory.pipelines.factory import diagnostic_action
    def report(kind, certainty='confirmed'):
        return {'releasable': False, 'issues': [{'issue_id': 'i', 'certainty': certainty}],
                'routes': [{'issue_id': 'i', 'route_class': kind}]}
    assert diagnostic_action(report('evidence_collection', 'suspected'))[0] == 'evidence'
    assert diagnostic_action(report('infrastructure_retry'))[0] == 'infrastructure_retry'
    assert diagnostic_action(report('repair'))[0] == 'repair'
    assert diagnostic_action(report('repair', 'suspected'))[0] == 'evidence'
    assert diagnostic_action({'releasable': True, 'issues': [], 'routes': []})[0] == 'export'


@pytest.mark.parametrize('route_class,phase,budget_key,error_label', [
    ('evidence_collection', 'evidence', 'max_evidence_rounds_per_revision', 'UNRESOLVED'),
    ('infrastructure_retry', 'infrastructure_retry', 'infrastructure_retries_per_stage', 'INFRA_FAILED'),
])
def test_same_revision_retries_never_call_content_repair(tmp_path, route_class, phase, budget_key, error_label):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.pipelines.factory import FactoryPipeline
    source = model_fixture(tmp_path / 'model.xlsx')
    config = {'project_root': str(ROOT), 'run_dir': str(tmp_path / 'run'),
              'run': {'targets': {'financial_modeling': 1}, 'max_steps': 0, budget_key: 2}}
    audit = AuditStore(tmp_path / 'run', {'id': 'r'})
    pipeline = FactoryPipeline(config, audit, None, None)
    observed = []

    def run_phase(ctx, current):
        observed.append((current, ctx.revision))
        if current == 'preparation':
            ctx.data.update(plan=plan(), source_id='a' * 64)
        elif current in {'revision', phase}:
            ctx.data['diagnosis'] = {'releasable': False,
                'issues': [{'issue_id': 'i', 'certainty': 'confirmed'}],
                'routes': [{'issue_id': 'i', 'route_class': route_class}]}
        else:
            pytest.fail('Unknown/infra evidence must not trigger content repair or export')

    pipeline.run_phase = run_phase
    pipeline.process_task({'local_path': str(source), 'sha256': 'a' * 64}, 'financial_modeling')
    assert observed.count((phase, 0)) == 2
    assert all(revision == 0 for _, revision in observed)
    task = audit.snapshot()['tasks'][0]
    assert task['status'] == 'rejected'
    assert error_label in task['error']


def test_variants_keep_source_identity_and_reject_duplicate_modules(tmp_path):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.pipelines.factory import FactoryPipeline
    source = model_fixture(tmp_path / 'model.xlsx')
    config = {'project_root': str(ROOT), 'run_dir': str(tmp_path / 'run'),
              'run': {'targets': {'financial_modeling': 20, 'debugging': 20}, 'max_steps': 1}}
    audit = AuditStore(tmp_path / 'run', {'id': 'r'})
    pipeline = FactoryPipeline(config, audit, None, None)
    seed = {'local_path': str(source), 'sha256': 'a' * 64,
            'finance_evidence': {'financial_modeling_eligible': True}}
    first = pipeline._context(seed, 'financial_modeling')
    first.data.update(plan=plan(), source_id=seed['sha256'])
    pipeline._claim_targets(first)
    second = pipeline._context({**seed, 'variant': 1}, 'financial_modeling')
    second.data.update(plan=plan(), source_id=seed['sha256'])
    with pytest.raises(TaskRejected, match='duplicate'):
        pipeline._claim_targets(second)
    assert second.task_id.endswith('-v1')
    assert len({task['source_id'] for task in audit.snapshot()['tasks']}) == 1
    variants = pipeline.variant_candidates([seed, {**seed, 'sha256': 'b' * 64,
                            'finance_evidence': {'financial_modeling_eligible': False}}], 1)
    assert len(variants) == 1
    assert variants[0]['modes'] == ['financial_modeling']


def test_variant_modes_are_opt_in_and_use_mode_specific_productivity_and_quota(tmp_path):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.pipelines.factory import FactoryPipeline
    config = {'project_root': str(ROOT), 'run_dir': str(tmp_path / 'run'),
        'run': {'targets': {'financial_modeling': 2, 'debugging': 2}, 'max_steps': 3,
                'variant_modes': ['financial_modeling', 'debugging']}}
    audit = AuditStore(tmp_path / 'run', {'id': 'r'})
    audit.task('debug-good', source_id='b' * 64, mode='debugging', status='qualified')
    audit.task('debug-bad', source_id='c' * 64, mode='debugging', status='rejected')
    factory = FactoryPipeline(config, audit, None, None)
    seeds = [{'sha256': 'a' * 64, 'finance_evidence': {'financial_modeling_eligible': True}},
             {'sha256': 'b' * 64, 'finance_evidence': {'financial_modeling_eligible': False}},
             {'sha256': 'c' * 64, 'finance_evidence': {'financial_modeling_eligible': False}},
             {'sha256': 'd' * 64, 'debugging_eligible': True,
              'finance_evidence': {'financial_modeling_eligible': False}}]
    candidates = {seed['sha256']: seed['modes'] for seed in factory.variant_candidates(seeds, 1)}
    assert candidates == {'a' * 64: ['financial_modeling'], 'b' * 64: ['debugging'], 'd' * 64: ['debugging']}
    audit.task('debug-second', source_id='d' * 64, mode='debugging', status='ready')
    assert [seed['modes'] for seed in factory.variant_candidates(seeds, 1)] == [['financial_modeling']]
    del config['run']['variant_modes']
    assert all(seed['modes'] == ['financial_modeling'] for seed in factory.variant_candidates(seeds, 1))
    audit.task('financial-structurally-invalid', source_id='a' * 64, mode='financial_modeling',
               status='rejected', error='Source contains no genuine cross-sheet formula dependency')
    assert factory.variant_candidates(seeds, 1) == []
