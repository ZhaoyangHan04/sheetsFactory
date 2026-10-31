"""Normal nodes for a complete, independently scoped native business task."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import time
from uuid import uuid4

from openpyxl import load_workbook

from ..core.node import TaskRejected
from ..nodes import construction as normal, quality
from ..pipelines.heterogeneous_native_quality import (ROOT, SETTING, PROFILE,
    admission, reference, require, setting)
from ..evaluation.streaming_delta import compare_workbooks
from ..evaluation.streaming_verifier import compare_files
from ..evaluation.thread_capped_harbor_export import (
    export_resource_harbor, inspect_resource_export, verify_local_base_image)
from ..workbook.profile_indexed import profile_workbook
from ..workbook.thread_capped_resource_engine import validate_capped_call
from ..checkers.unsafe_regions import evaluate_native_risk_guard

REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}


def scoped_native_evidence(value, proof, goal, required_labels, revision):
    """Check every task value without certifying unrelated source calculations.

    The independent business calculations certify all possible task outputs.
    Existing off-scope errors remain visible to the ordinary Q04/Q09 review.
    This does not claim a complete syntactic dependency exclusion certificate.
    """
    task = value.helper.validation_driver().task
    snapshot = task.helper().snapshot(goal)
    coverage = task.read(proof['independent_scope'])
    rows = coverage['expected_typed_values']
    known = {(row['sheet'], row['cell']): row['expected'] for row in rows}
    if proof['mode'] == 'debugging':
        known['Budget - Summary', 'F12'] = task.helper().EMPTY
    for (sheet, address), expected in known.items():
        observed = snapshot['cells'].get(sheet, {}).get(address, {}).get('primary', task.helper().EMPTY)
        require(observed == expected, 'Q04: an independently expected task value differs at '+sheet+'!'+address)
    labels = {sheet+'!'+address for sheet, address in known}
    require(set(required_labels) <= labels, 'Q04: the actual task exceeds independent financial coverage')
    errors = sorted([sheet, address, cell['primary']['value']]
        for sheet, cells in snapshot['cells'].items() for address, cell in cells.items()
        if cell['primary']['type'] == 'error')
    require(errors == value.evidence['delta']['expected_fixed_errors'],
        'Q09: retained source errors differ from the actual validated task')
    require(not set(required_labels) & {s+'!'+a for s, a, _ in errors},
        'Q04: a required task value is a native error')
    return {'version': 1, 'state': 'independently_validated_task_values', 'blocking': False,
        'classification': 'complete_independent_financial_task_scope', 'revision': revision,
        'source_sha256': proof['workbook']['sha256'], 'goal': reference(goal),
        'goal_sha256': reference(goal)['sha256'],
        'actual_validation': proof['actual_validation'], 'independent_scope': proof['independent_scope'],
        'required_delta': sorted(required_labels), 'independent_fields_checked': len(known),
        'retained_offscope_errors': errors, 'candidates': [], 'probes': [],
        'requires_Q04_Q09_review': True, 'whole_source_business_correctness_certified': False,
        'complete_syntactic_dependency_exclusion_claimed': False, 'new_LO_calls': 0}


def context(ctx):
    require(ctx.config.get(SETTING) == setting(), 'The explicit scoped family configuration changed')
    value = ctx.data.get('_native_scope_admission')
    proof = admission(value)
    require(proof['mode'] == ctx.mode and proof['workbook'] == reference(ctx.source),
        'The source or task mode differs from the current opaque admission')
    for key in ('input', 'goal', 'baseline'):
        if ctx.data.get(key):
            observed = reference(ctx.data[key]); expected = proof['goal' if key == 'baseline' else key]
            require((observed['sha256'], observed['bytes']) == (expected['sha256'], expected['bytes']),
                'A copied admitted workbook changed: '+key)
    return value, proof


def canonical_plan(value):
    proof = admission(value); evidence = value.evidence
    raw = evidence['plan']
    book = load_workbook(proof['goal']['path'], read_only=False, data_only=False)
    try:
        points = raw['financial_scope'] if proof['mode'] == 'financial_modeling' else [
            (row['sheet'], row['cell']) for row in raw['faults']]
        faults = {(row['sheet'], row['cell']): row for row in raw['faults']}
        edits = [{'sheet': s, 'cell': a, 'before': book[s][a].value,
            'after': None if proof['mode'] == 'financial_modeling' else '='+faults[s, a]['replacement'],
            'reason': 'Complete the selected business schedules.' if proof['mode'] == 'financial_modeling'
                else faults[s, a]['mechanism']} for s, a in points]
    finally:
        book.close()
    config = value.helper.read(evidence['preparation']['config'])
    return {'title': 'Complete the business review pack' if proof['mode'] == 'financial_modeling'
                else 'Repair the business review pack', 'mode': proof['mode'],
        'public_instruction': Path(proof['instruction']['path']).read_text(),
        'public_rules': [config['public_policy_brief']], 'scenario_inputs': [], 'edits': edits,
        'reference_evidence': [{'kind': 'independently_audited_financial_output_scope',
            'coverage': proof['independent_scope'], 'actual_validation': proof['actual_validation'],
            'whole_workbook_financial_certification': False}],
        'family_adapter': {'id': SETTING, 'plan': proof['plan'], 'full_D': proof['full_D'],
            'independent_scope_count': 766, 'physical_edit_count': len(edits),
            'complete_D_count': evidence['delta']['actual_change_count'],
            'activity_contract': 'joint_business_schedule_repair' if proof['mode'] == 'debugging'
                else 'scoped_business_schedule_completion', 'whole_workbook_financial_certification': False}}


class NativeNormalizeNode(normal.NormalizeNode):
    def execute(self, ctx):
        value, proof = context(ctx)
        cache = Path(ctx.config['run_dir'])/'sources'/proof['workbook']['sha256'][:16]/proof['mode']
        cache.mkdir(parents=True, exist_ok=True); baseline = cache/'baseline.xlsx'
        if not baseline.exists():
            shutil.copyfile(proof['goal']['path'], baseline)
        require(reference(baseline)['sha256'] == proof['goal']['sha256'], 'The audited baseline changed')
        evidence = {'method': 'byte_identical_copy_of_actual_recalculated_goal',
            'baseline': reference(baseline), 'actual_validation': proof['actual_validation'],
            'independent_scope': proof['independent_scope'], 'new_LO_calls': 0,
            'source_financially_verified_in_full': False, 'prequality_is_not_normal_quality': True}
        ctx.save('native_scoped_normalization.json', evidence)
        return {'source_id': proof['workbook']['sha256'], 'baseline': baseline, 'source_cache': cache,
            'engine_report': {'normalization_ok': True, 'recalculation_ok': True, 'stable': True,
                'normalization_artifact': str(baseline), 'normalization_evidence': evidence,
                'engine': ctx.engine.metadata()}}


class NativeProfileNode(normal.ProfileNode):
    def execute(self, ctx):
        _, proof = context(ctx)
        profile = profile_workbook(ctx.data['baseline'], max_cells=3_000_000, per_formula_reference_cells=5000)
        require(not profile['truncated'] and not profile['external_references']
            and profile['formula_count'] > 0 and profile['nonempty_sheet_count'] > 3,
            'The full native profile must be available without external dependencies')
        ctx.save('native_scoped_profile.json', profile)
        return {'profile': profile}


class NativePlanNode(normal.PlanNode):
    def execute(self, ctx):
        value, proof = context(ctx)
        return {'plan': canonical_plan(value), 'source_assessment': {
            'financial_scope': proof['independent_scope'], 'independently_checked_outputs': 766,
            'actual_task_validation': proof['actual_validation'], 'source_financially_verified_in_full': False,
            'provided_donor_context': value.evidence['plan']['donor_context_disclosure'],
            'source_business_issues': ctx.data.get('source_business_issues', [])}}


class NativeConstructNode(normal.ConstructNode):
    def execute(self, ctx):
        value, proof = context(ctx); expected = canonical_plan(value)
        require({k: v for k, v in ctx.data['plan'].items() if k != 'public_instruction'} ==
            {k: v for k, v in expected.items() if k != 'public_instruction'},
            'A repair changed financial scope or mutations; a newly validated actual task is required')
        require(type(ctx.data['plan']['public_instruction']) is str and ctx.data['plan']['public_instruction'].strip(),
            'The public business request cannot be empty')
        public, private = ctx.revision_dir/'public', ctx.revision_dir/'private'
        public.mkdir(parents=True, exist_ok=True); private.mkdir(parents=True, exist_ok=True)
        source, goal = public/'input.xlsx', private/'goal.xlsx'
        shutil.copyfile(proof['input']['path'], source); shutil.copyfile(proof['goal']['path'], goal)
        delta = compare_workbooks(source, goal, goal)
        labels = sorted(row['sheet']+'!'+row['cell'] for row in value.evidence['delta']['expected_changes'])
        require(delta['reward'] == 1 and delta['expected_changes'] == labels and labels,
            'The complete actual changed-value set differs from the independent scoped proof')
        plan = value.evidence['plan']
        protected = {tuple(p) for p in value.helper.read(plan['known_protected_points'])['points']}
        require(not protected & {(r['sheet'], r['cell']) for r in value.evidence['delta']['expected_changes']},
            'Known source risks intersect the actual complete task')
        guard = evaluate_native_risk_guard(labels, proof['workbook']['sha256'],
            project_root=ctx.config['project_root'], sheet_names=list(plan['component_namespaces']),
            legacy_risks=ctx.data.get('source_business_issues', []))
        require(not guard['blocking'], 'Q09: a registered source risk intersects the actual task')
        probe = scoped_native_evidence(value, proof, goal, labels, ctx.revision)
        require(not probe['blocking'], 'Q09/Q10: an unresolved native error reaches the actual task')
        validation = {'edit_count': len(expected['edits']), 'before_assertions_passed': True,
            'physical_edits_checked_by_actual_view_validation': proof['actual_validation'],
            'independent_financial_scope': proof['independent_scope'], 'full_D_count': len(labels),
            'actual_family_effects': value.evidence['delta']['family_effect_counts'],
            'source_financially_verified_in_full': False, 'reference_values_not_modified': True,
            'native_error_candidates': [], 'native_error_probe': probe, 'new_LO_calls': 0}
        for name, data in [('plan.json', ctx.data['plan']), ('edit_validation.json', validation),
                ('expected_delta.json', delta), ('root_impacts.json', []),
                ('native_risk_guard.json', guard), ('native_error_probe.json', probe)]:
            ctx.save(name, data)
        profile = profile_workbook(source, max_cells=3_000_000, per_formula_reference_cells=5000)
        require(not profile['truncated'], 'The full actual public task profile is required')
        return {'input': source, 'goal': goal, 'delta': delta, 'construction_validation': validation,
            'root_impacts': [], 'native_risk_guard': guard, 'public_profile': profile}


class NativeInstructionNode(normal.InstructionNode):
    def execute(self, ctx):
        context(ctx); text = ctx.data['plan']['public_instruction']
        path = ctx.revision_dir/'public/instruction.md'; path.write_text(text)
        return {'instruction': text, 'instruction_path': path,
            'revision_hash': hashlib.sha256(Path(ctx.data['input']).read_bytes()+text.encode()).hexdigest()}


class NativeControlsNode(normal.ControlsNode):
    def execute(self, ctx):
        value, proof = context(ctx); task = value.helper.validation_driver().task
        source, goal = Path(ctx.data['input']), Path(ctx.data['goal'])
        folder = ctx.revision_dir/'private/controls'/('attempt_'+uuid4().hex); folder.mkdir(parents=True)
        reports = {name: compare_files(source, goal, output) for name, output in [('oracle', goal), ('nop', source)]}
        calls = []; completed = False
        try:
            recipe = value.evidence['plan']; equivalent = {'sheet': 'FS - IS', 'cell': 'E7', 'action': 'formula'}
            book = load_workbook(goal, read_only=False, data_only=False)
            try:
                expression = book[equivalent['sheet']][equivalent['cell']].value
                require(type(expression) is str and expression.startswith('='), 'The equivalent control needs a genuine formula')
                equivalent['value'] = '('+expression[1:]+')+0'
            finally:
                book.close()
            missed = {'sheet': recipe['missed_root'][0], 'cell': recipe['missed_root'][1], 'action': 'clear'}
            if proof['mode'] == 'debugging':
                fault = recipe['faults'][0]; missed.update(action='formula', value=fault['replacement'])
            extra = recipe['extra_change']; extra_edit = {'sheet': extra['sheet'], 'cell': extra['cell'],
                'action': 'text', 'value': extra['replacement']}
            for index, (name, edit) in enumerate([('equivalent', equivalent), ('missed_root', missed), ('extra_change', extra_edit)], 1):
                raw, output = folder/(name+'.raw.xlsx'), folder/(name+'.xlsx')
                task.surgery(goal, raw, [edit]); tick = time.monotonic()
                call = {'index': index, 'stage': 'normal_control_'+name, 'input': reference(raw), 'completed': False}
                calls.append(call)
                before = len(ctx.engine.metadata().get('actual_resource_receipts', []))
                ctx.engine.recalculate(raw, output)
                call.update(completed=True, output=reference(output), elapsed_seconds=time.monotonic()-tick)
                receipts = ctx.engine.metadata()['actual_resource_receipts']
                require(len(receipts) == before+1, 'A normal control has an unrecorded calculation')
                call['actual_resource_evidence'] = validate_capped_call(call, receipts[-1],
                    value.evidence['preparation'], resource_validator=task.helper().support().validate_actual_call)
                ctx.save('normal_control_'+name+'.json', call)
                reports[name] = compare_files(source, goal, output)
            require(all(type(reports[n]['reward']) is int and reports[n]['reward'] == reward for n, reward in REWARDS.items()),
                'Q05/Q06: an actual positive or negative control failed')
            completed = True; ctx.save('local_controls.json', reports)
            return {'controls': reports}
        finally:
            (folder/'attempt.json').write_text(json.dumps({'completed': completed, 'reports': reports,
                'actual_LO_calls': calls, 'revision_hash': ctx.data['revision_hash']}, indent=2)+'\n')


class NativeRepairNode(quality.RepairNode):
    def execute(self, ctx):
        value, proof = context(ctx)
        routes = ctx.data.get('repair_routes', [])
        issues = {row['issue_id']: row for row in ctx.data.get('diagnosis', {}).get('issues', [])}
        require(routes and all(r['route_class'] == 'repair'
            and issues.get(r['issue_id'], {}).get('certainty') == 'confirmed' for r in routes),
            'Only confirmed numbered repair issues may request a revision')
        if any(row.get('problem_id') not in ('Q01', 'Q02', 'Q03') for row in routes):
            raise TaskRejected('A financial or mutation repair needs a newly validated actual task version')
        from ..llm.schemas import instruction_repair_output_schema
        requested = [row['issue_id'] for row in routes]
        payload = {'task_mode': ctx.mode, 'public_instruction': ctx.data['plan']['public_instruction'],
            'public_rules': ctx.data['plan']['public_rules'], 'assigned_issues': [issues[i] for i in requested],
            'repair_contract': {'permitted_changed_plan_fields': ['public_instruction'], 'full_revision_gates_required': True}}
        result = ctx.llm.complete(quality.prompt(ctx, 'instruction_repair.md')+'\nINPUT JSON:\n'+json.dumps(payload),
            role='repair_planner', task_id=ctx.task_id, stage=self.node_id,
            timeout=ctx.config['agents']['timeout_seconds'], output_schema=instruction_repair_output_schema(requested))
        ctx.save('repair_proposal.json', result)
        return {'next_plan': quality.apply_instruction_repair(ctx.data['plan'], result, requested)}


class NativeExportNode(quality.ExportNode):
    def execute(self, ctx):
        context(ctx)
        require(quality.validate_reference_policy_selection(ctx.config) == 'reference_review', 'The reference policy changed')
        binding = quality.reference_revision_binding(ctx)
        receipt = ctx.data.get('diagnosis', {}).get('reference_review', {})
        require(receipt.get('passed') is True and receipt.get('binding') == binding
            and ctx.data['diagnosis'].get('releasable') is True,
            'All current supported reference assessments and quality gates must pass before export')
        ctx.save('native_scoped_local_base_image.json', verify_local_base_image(PROFILE))
        destination = Path(ctx.config['run_dir'])/'SpreadsheetEval'/ctx.task_id
        require(not destination.exists() or not any(destination.iterdir()), 'Preserve every immutable normal export')
        metadata = {'task_id': ctx.task_id, 'mode': ctx.mode, 'source_id': ctx.data['source_id'],
            'source_file': ctx.source.name, 'revision': ctx.revision, 'revision_hash': ctx.data['revision_hash'],
            'difficulty_status': 'pending', 'base_image': ctx.config['engine']['image']}
        audit = ctx.revision_dir/'private/native_scoped_harbor_worker_cap.json'
        export_resource_harbor(ctx.revision_dir, destination, metadata, ctx.config['project_root'],
            runtime_profile=PROFILE, audit_path=audit)
        exported = inspect_resource_export(destination, audit_path=audit)
        require(exported['task_id'] == ctx.task_id and exported['revision_hash'] == ctx.data['revision_hash'],
            'The complete seventeen-file export differs from this revision')
        ctx.save('native_scoped_export_binding.json', exported)
        (ctx.directory/'lineage.json').write_text(json.dumps(metadata, indent=2)+'\n')
        return {'export_dir': destination}
