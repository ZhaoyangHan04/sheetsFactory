"""Fixed200 FM nodes over unchanged normal-quality and receipt machinery."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import time
from types import FunctionType
from uuid import uuid4

from ..core.node import TaskRejected
from ..nodes import quality
from ..pipelines import operating_reports_200_quality as pipeline
from . import heterogeneous_native_quality as base, reference_receipt_diagnosis as receipt
from .linear_capital_scaled_reference_review import validate_reference_export

ROOT, SETTING, PROFILE = pipeline.ROOT, pipeline.SETTING, pipeline.PROFILE
reference, require, admission, setting = pipeline.reference, pipeline.require, pipeline.admission, pipeline.setting
BASE_SHA = '7e9ea8f0ba72b7e91297d3c4a8646ac0d63348a8feb59e6d1c4b5b54a1d991fc'
RECEIPT_SHA = '076089b9f473bde64b5749b81d0459b8c97e00121553789c57afb605098953dc'
REGISTRY = pipeline.REGISTRY
REWARDS = base.REWARDS


def context(ctx):
    require(ctx.config.get(SETTING) == setting(), 'The exact fixed200 normal route changed')
    value = ctx.data.get('_native_scope_admission'); proof = admission(value)
    require(ctx.mode == proof['mode'] == 'financial_modeling' and reference(ctx.source) == proof['workbook'],
        'Only the fixed exact FM task is admitted')
    for key in ('input', 'goal', 'baseline'):
        if ctx.data.get(key):
            observed, wanted = reference(ctx.data[key]), proof['goal' if key == 'baseline' else key]
            require((observed['sha256'], observed['bytes']) == (wanted['sha256'], wanted['bytes']),
                'An unchanged first-v6 task workbook was replaced: '+key)
    return value, proof


def canonical_plan(value):
    proof = admission(value); helper = value.helper; frozen = value.evidence['preparation']
    definition = helper.read(frozen['definition'])
    points = definition['FM_mask_points']
    require(len(points) == len(set(points)) == 62322, 'Keep the complete declared forecast mask')
    edits = []
    for point in points:
        sheet, cell = point.rsplit('!', 1)
        require(point in definition['formulas'] and point not in definition['literals'], 'A forecast root cannot be a provided field')
        edits.append({'sheet': sheet, 'cell': cell, 'before': definition['formulas'][point], 'after': None,
            'reason': 'Complete the forecast management reports.'})
    public = helper.read(frozen['specification'])
    return {'title': 'Complete the forecast management reports', 'mode': 'financial_modeling',
        'public_instruction': Path(proof['instruction']['path']).read_text(),
        'public_rules': [public['public_policy']],
        'scenario_inputs': [], 'edits': edits,
        'reference_evidence': [{'kind': 'complete_independent_fixed200_business_fields',
            'expected': proof['independent_expected'], 'actual_validation': proof['actual_validation'],
            'specification': proof['specification'], 'independent_business_fields': 93510}],
        'family_adapter': {'id': SETTING, 'complete_D_count': 62322, 'independent_business_fields': 93510,
            'physical_edit_count': 62322, 'first_development_material_identity': pipeline.FIRST_MATERIAL,
            'normal_quality_or_score_inherited': False}}


def independent_evidence(value, proof, goal, labels, revision):
    helper = value.helper; frozen = value.evidence['preparation']
    expected = helper.read(frozen['expected']); definition = helper.read(frozen['source_definition'])
    require(len(expected) == 93510 and set(labels) <= set(expected), 'The full actual task must be independently covered')
    audited = helper.source.audit_workbook(goal, definition, expected)
    require(audited['passed'] and audited['all_financial_fields_checked'] == 93510
        and not audited['native_errors'], 'Complete independent financial/type/given audit failed')
    return {'version': 1, 'state': 'independently_validated_task_values', 'blocking': False,
        'classification': 'complete_independent_fixed200_business_scope', 'revision': revision,
        'source_sha256': proof['workbook']['sha256'], 'goal': reference(goal),
        'actual_validation': proof['actual_validation'], 'independent_expected': proof['independent_expected'],
        'required_delta': sorted(labels), 'independent_fields_checked': 93510, 'audit': audited,
        'candidates': [], 'probes': [], 'complete_syntactic_dependency_exclusion_claimed': False,
        'source_quality_inherited': False, 'new_LO_calls': 0}


class PlanNode(base.normal.PlanNode):
    def execute(self, ctx):
        value, proof = context(ctx)
        return {'plan': canonical_plan(value), 'source_assessment': {
            'actual_task_validation': proof['actual_validation'], 'independent_expected': proof['independent_expected'],
            'specification': proof['specification'], 'independent_business_fields': 93510,
            'source_manifest': proof['source_manifest'], 'business_scope': 'The complete declared hypothetical200-entity specification.',
            'source_business_issues': ctx.data.get('source_business_issues', []), 'prior_normal_clear_inherited': False}}


class ConstructNode(base.normal.ConstructNode):
    def execute(self, ctx):
        value, proof = context(ctx); plan = canonical_plan(value)
        require(ctx.data['plan'] == plan, 'Preserve the original task and brief; any content repair requires an explicit new revision')
        public, private = ctx.revision_dir/'public', ctx.revision_dir/'private'
        public.mkdir(parents=True, exist_ok=True); private.mkdir(parents=True, exist_ok=True)
        source, goal = public/'input.xlsx', private/'goal.xlsx'
        shutil.copyfile(proof['input']['path'], source); shutil.copyfile(proof['goal']['path'], goal)
        delta = base.compare_workbooks(source, goal, goal)
        definition = value.helper.read(value.evidence['preparation']['definition'])
        labels = sorted(definition['FM_mask_points'])
        require(delta['reward'] == 1 and delta['expected_changes'] == labels and len(labels) == 62322,
            'The complete actual changed-value set differs from the predeclared forecast scope')
        require(not set(labels) & set(definition['literals']), 'A task output intersects a supplied field')
        guard = base.evaluate_native_risk_guard(labels, proof['workbook']['sha256'], project_root=ctx.config['project_root'],
            sheet_names=definition['sheetnames'], legacy_risks=ctx.data.get('source_business_issues', []))
        require(not guard['blocking'], 'A registered source risk intersects the current complete task')
        probe = independent_evidence(value, proof, goal, labels, ctx.revision)
        validation = {'edit_count': 62322, 'before_assertions_passed': True,
            'physical_edits_checked_by_actual_view_validation': proof['actual_validation'],
            'independent_expected': proof['independent_expected'], 'full_D_count': 62322,
            'reference_values_not_modified': True, 'native_error_candidates': [], 'native_error_probe': probe,
            'all_given_facts_protected_by_exact_immutable_bytes': True, 'new_LO_calls': 0}
        for name, data in [('plan.json', plan), ('edit_validation.json', validation), ('expected_delta.json', delta),
            ('root_impacts.json', []), ('native_risk_guard.json', guard), ('native_error_probe.json', probe)]: ctx.save(name, data)
        profile = base.profile_workbook(source, max_cells=3000000, per_formula_reference_cells=5000)
        require(not profile['truncated'], 'The complete actual public task profile is required')
        return {'input': source, 'goal': goal, 'delta': delta, 'construction_validation': validation,
            'root_impacts': [], 'native_risk_guard': guard, 'public_profile': profile}


class ControlsNode(base.normal.ControlsNode):
    def execute(self, ctx):
        value, proof = context(ctx); helper = value.helper; frozen = value.evidence['preparation']
        source, goal = Path(ctx.data['input']), Path(ctx.data['goal'])
        folder = ctx.revision_dir/'private/controls'/('attempt_'+uuid4().hex); folder.mkdir(parents=True)
        reports = {name: base.compare_files(source, goal, output) for name, output in [('oracle', goal), ('nop', source)]}
        calls = []; completed = False
        try:
            for index, (name, key) in enumerate([('equivalent', 'equivalent'), ('missed_root', 'FM_missed_root'), ('extra_change', 'extra_change')], 1):
                raw = helper.checked(frozen['planned_inputs'][key]); output = folder/(name+'.xlsx')
                # These are the genuine cache-cleared controls of this same
                # immutable goal. A new actual calculation binds the current QA revision.
                call = {'index': index, 'stage': 'normal_control_'+name, 'input': reference(raw), 'completed': False}
                calls.append(call); before = len(ctx.engine.metadata()['actual_resource_receipts']); tick = time.monotonic()
                ctx.engine.recalculate(raw, output)
                call.update(completed=True, output=reference(output), elapsed_seconds=time.monotonic()-tick)
                receipts = ctx.engine.metadata()['actual_resource_receipts']
                require(len(receipts) == before+1, 'A current normal control has an extra or missing native calculation')
                call['actual_resource_evidence'] = helper.source.validate_call(call, receipts[-1], frozen)
                ctx.save('normal_control_'+name+'.json', call); reports[name] = base.compare_files(source, goal, output)
            require(all(type(reports[name]['reward']) is int and reports[name]['reward'] == target for name, target in REWARDS.items()),
                'The five actual positive/negative control requirements failed')
            clean = helper.source.owned_absence(calls)
            require(clean['all_owned_containers_absent'] is True and clean['daemon_reachable'] is True
                and len(clean['owned']) == 3 and all(row['absent'] is True for row in clean['owned'])
                and {row['full_id'] for row in clean['owned']} == {row['actual_resource_evidence']['container_id'] for row in calls}
                and len({row['actual_resource_evidence']['container_id'] for row in calls}) == 3,
                'The three current normal control containers need exact owned-cleanup proof')
            ctx.save('normal_control_owned_absence.json', clean)
            completed = True; ctx.save('local_controls.json', reports)
            return {'controls': reports}
        finally:
            helper.write(folder/'attempt.json', {'completed': completed, 'reports': reports, 'actual_LO_calls': calls,
                'revision_hash': ctx.data['revision_hash'], 'actual_prequality_controls_are_not_normal_clear_flags': True})


class DiagnoseNode(quality.DiagnoseNode):
    def execute(self, ctx):
        context(ctx)
        require(quality.validate_reference_policy_selection(ctx.config) == 'reference_review'
            and ctx.config['diagnosis']['execution']['reference_evidence_transport'] == 'audited_summary',
            'Use the complete strict reference-review receipt protocol')
        receipt.verify_dependencies()
        return receipt.ReferenceReceiptDiagnosisNode._execute_diagnose(self, ctx)


class RepairNode(quality.RepairNode):
    def execute(self, ctx):
        context(ctx)
        raise TaskRejected('The fixed first-v6 task bytes cannot change during QA; a content repair requires an explicitly new checked revision')


class NormalizeNode(base.NativeNormalizeNode): pass
class ProfileNode(base.NativeProfileNode): pass
class InstructionNode(base.NativeInstructionNode): pass


class ExportNode(base.NativeExportNode):
    def execute(self, ctx):
        _, proof = context(ctx)
        require(ctx.data['plan']['public_instruction'].encode() == Path(proof['instruction']['path']).read_bytes(),
            'The first-v6 rendered public instruction changed')
        validate_reference_export(ctx)
        result = _export(self, ctx)
        destination = result['export_dir']
        for relative, key in [('environment/input.xlsx', 'input'), ('tests/original_input.xlsx', 'input'),
            ('solution/reference.xlsx', 'goal'), ('tests/reference.xlsx', 'goal'), ('instruction.md', 'instruction')]:
            observed, expected = reference(destination/relative), proof[key]
            require((observed['sha256'], observed['bytes']) == (expected['sha256'], expected['bytes']),
                'The normal export changed the spent first-v6 task material: '+key)
        return result


require(reference(base.__file__)['sha256'] == BASE_SHA and reference(receipt.__file__)['sha256'] == RECEIPT_SHA,
    'The frozen normal nodes or repaired receipt protocol changed')
_namespace = {**vars(base), **globals()}
for _new, _old in ((NormalizeNode, base.NativeNormalizeNode), (ProfileNode, base.NativeProfileNode), (InstructionNode, base.NativeInstructionNode)):
    _function = _old.execute
    _new.execute = FunctionType(_function.__code__, _namespace, _function.__name__, _function.__defaults__, _function.__closure__)
_function = base.NativeExportNode.execute
_export = FunctionType(_function.__code__, _namespace, _function.__name__, _function.__defaults__, _function.__closure__)
