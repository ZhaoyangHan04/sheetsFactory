"""Opt-in, policy-grounded debugging of a fixed-plan legal-entity close."""
from __future__ import annotations

import ast
from copy import deepcopy
import inspect
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import textwrap
from uuid import uuid4

import openpyxl

from ..core.node import BaseNode, TaskRejected
from ..nodes import construction as normal
from ..nodes import quality
from ..nodes.quality import (validate_reference_policy_selection, reference_revision_binding,
    _reference_review_context, candidate_difficulty_context, REFERENCE_REVIEW_PREFIX,
    REFERENCE_REVIEW_CHECKS, PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS,
    prepare_workspace, reference_review_assessments, route_issues, DiagnosisRunner)
from ..nodes.scc_activity import SCCConstructNode
from ..nodes.joint_controls import JointObservableControlsNode
from ..pipelines.entity_group_admission import verify_admitted_proof
from ..pipelines.entity_group_contract import (construction_contract, validate_plan,
    validate_upstream_validator, probe_native_errors)
from ..evaluation.streaming_delta import compare_workbooks
from ..evaluation.resource_harbor import export_resource_harbor, inspect_resource_export, verify_local_base_image
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..workbook.profile_indexed import profile_workbook
from ..workbook.resource_engine import DEFAULT_PROFILE
from ..workbook.resource_engine import load_runtime_profile
from ..workbook.entity_group.excel import expression_formula
from ..workbook.entity_group.validate import formula_signature
from .public_workbook_scope import CLAUSES, canonical, checked_bytes, read, reference, require

SETTING = 'entity_group_task'
ADAPTER_ID = 'entity_group_fixed_plan_financial_debug_v1'
METHOD = 'full_workbook_joint_repair'
ROOT = Path(__file__).resolve().parents[3]
digest = normal.digest
prompt = normal.prompt
authoring_source_context = normal.authoring_source_context
compact_profile = normal.compact_profile
apply_instruction_repair = quality.apply_instruction_repair

# This list is prospective and independent of model outcomes. Every matching
# canonical financial definition is selected; neither aliases nor limits are
# used to silently shorten the declared candidate inventory.
POLICIES = {
    'bank_interest': 'Treat the quoted monthly bank rate as an annual rate and divide it by twelve.',
    'current_tax': 'Charge tax before using eligible tax-loss vintages.',
    'interest_current_allowed': 'Give current interest the full capacity without first deducting old FIFO usage.',
    'borrowing_base': 'Use current certified NAV without lender advance-rate or haircut adjustments.',
    'capital_call': 'Apply the full additional commitment every month without deducting prior calls.',
    'distribution': 'Distribute available cash without preserving the contractual minimum cash floor.',
    'reserve_released': 'Release the opening reserve on the current covenant test instead of the opening trap state.',
}


def setting(runtime_profile=DEFAULT_PROFILE):
    return {'enabled': True, 'version': 1, 'adapter': ADAPTER_ID,
        'implementation': reference(__file__), 'source_admission': reference(ROOT / 'src/sheets_factory/pipelines/entity_group_admission.py'),
        'complete_contract': reference(ROOT / 'src/sheets_factory/pipelines/entity_group_contract.py'),
        'ordinary_construction': reference(normal.__file__), 'ordinary_quality': reference(quality.__file__),
        'indexed_profile': reference(ROOT / 'src/sheets_factory/workbook/profile_indexed.py'),
        'streaming_delta': reference(ROOT / 'src/sheets_factory/evaluation/streaming_delta.py'),
        'joint_construct': reference(ROOT / 'src/sheets_factory/nodes/scc_activity.py'),
        'joint_activity': reference(ROOT / 'src/sheets_factory/pipelines/joint_repair_activity.py'),
        'joint_controls': reference(ROOT / 'src/sheets_factory/nodes/joint_controls.py'),
        'resource_engine': reference(ROOT / 'src/sheets_factory/workbook/resource_engine.py'),
        'resource_exporter': reference(ROOT / 'src/sheets_factory/evaluation/resource_harbor.py'),
        'resource_verifier': reference(ROOT / 'src/sheets_factory/evaluation/resource_streaming_verifier.py'),
        'public_recovery': reference(ROOT / 'src/sheets_factory/workbook/entity_group_public_recovery.py'),
        'recovery_backend': 'entity_group_public_integer_shared_compiler',
        'operational_replay_timeout_seconds': 7200,
        'runtime_profile': reference(runtime_profile), 'activity_contract': METHOD,
        'mutation_policies': deepcopy(POLICIES), 'fixed_plan_provided_and_protected': True}


def enabled(ctx):
    value = ctx.config.get(SETTING)
    if value is None:
        return False
    require(isinstance(value, dict) and type(value.get('version')) is int
            and value == setting(value['runtime_profile']['path']), 'The entity family implementation or policy changed')
    require(ctx.mode == 'debugging', 'The fixed-plan entity adapter currently supports debugging only')
    require(load_runtime_profile(value['runtime_profile']['path'])['id'] == 'entity_group_large_v2',
            'The new entity task requires an explicitly bound v2 profile; no legacy resource fallback')
    recovery = ctx.config.get('recovery', {})
    require(recovery.get('compiler_backend') == value['recovery_backend']
            and type(recovery.get('replay_timeout_seconds')) is int
            and recovery['replay_timeout_seconds'] == value['operational_replay_timeout_seconds'],
            'The explicit public-only entity recovery route and separate operational replay budget are required')
    validate_copies()
    return True


def context_proof(ctx):
    require(enabled(ctx), 'The explicit entity family adapter is required')
    evidence = ctx.data.get('finance_evidence', {})
    proof = verify_admitted_proof(evidence.get('audited_source_binding'))
    require(evidence.get('financial_seed_verified') is True
            and evidence.get('source_manifest') == proof['source_manifest']
            and reference(ctx.source) == proof['workbook']
            and reference(ctx.data['baseline'])['sha256'] == proof['workbook']['sha256']
            and ctx.config[SETTING]['runtime_profile'] == proof['runtime_profile'],
            'The original complete financial source, exact baseline or resource binding changed')
    return proof


def _shape(value, op, size):
    return isinstance(value, (list, tuple)) and len(value) == size and value[0] == op


def mutate_expression(field, expression, refs):
    e = deepcopy(expression)
    if field == 'bank_interest' and _shape(e, 'round_product', 3):
        return ['round_product', e[1], ['rounddiv', e[2], 12]]
    if field == 'current_tax' and _shape(e, 'round_product', 3):
        return ['round_product', refs['taxable_before_loss'], e[2]]
    if field == 'interest_current_allowed' and _shape(e, 'min', 3) and _shape(e[2], 'max', 3) and _shape(e[2][1], 'sub', 3):
        return ['min', e[1], e[2][1][1]]
    if field == 'borrowing_base' and _shape(e, 'if', 4) and e[2] == 0 and _shape(e[3], 'min', 3):
        return ['if', e[1], 0, ['min', e[3][1], refs['certified_nav_close']]]
    if field == 'capital_call' and _shape(e, 'min', 3) and _shape(e[2], 'sub', 3):
        return ['min', e[1], e[2][1]]
    if field == 'distribution' and _shape(e, 'min', 3) and _shape(e[1], 'max', 3) and _shape(e[1][1], 'sub', 3):
        return ['min', ['max', e[1][1][1], e[1][2]], e[2]]
    if field == 'reserve_released' and _shape(e, 'if', 4) and e[2] == 0:
        return ['if', refs['covenant_passed'], e[3], 0]
    raise ValueError('The declared financial-policy expression shape changed: ' + field)


def _physical(edits):
    return [{key: item[key] for key in ('sheet', 'cell', 'before', 'after')} for item in edits]


def propose_from_checked_proof(baseline, proof):
    bindings = read(proof['bindings']); public = read(proof['public_specification'])
    ledger = read(proof['independent_ledger'])
    require(bindings.get('public_spec') == public and bindings.get('fixed_plan_provided_and_protected') is True,
            'The source binding and complete public contract differ')
    references = {}
    logical_counts = {field: 0 for field in POLICIES}
    for item in bindings['output_bindings']:
        path = item['path']
        if (item['encoding'] == 'scalar' and len(path) == 7 and path[0] == 'scenarios'
                and path[2] == 'entities' and path[4] == 'monthly'):
            references.setdefault((path[1], path[3], public['months'][path[5]]), {})[path[6]] = item['reference']
            if path[6] in logical_counts:
                logical_counts[path[6]] += 1
    pattern = re.compile(r'^(S0[1-3])/(E[0-9]{2})/([0-9]{4}-[0-9]{2}-[0-9]{2})/([^/]+)$')
    edits, priority, inventory = [], [], {field: {'complete_logical_field_bindings': logical_counts[field],
        'canonical_rows_examined': 0, 'selected': 0} for field in POLICIES}
    book = openpyxl.load_workbook(baseline, keep_links=False)
    try:
        require(book.sheetnames == bindings['worksheet_order'], 'The original financial worksheet order changed')
        for item in bindings['formula_bindings']:
            match = pattern.fullmatch(item['label'])
            if match is None or match[4] not in POLICIES:
                continue
            sid, identity, month, field = match.groups()
            require(item.get('monetary') is True, 'A financial mutation cannot silently target a state/helper row')
            inventory[field]['canonical_rows_examined'] += 1
            refs = references[(sid, identity, month)]
            require(item['sheet'] == sid + ' Close'
                    and refs[field] == "'" + item['sheet'] + "'!$" + re.sub(r'([A-Z]+)([0-9]+)', r'\1$\2', item['cell']),
                    'A public financial label does not identify its own complete scalar binding')
            cell = book[item['sheet']][item['cell']]
            require(cell.data_type == 'f' and formula_signature(cell.value) == formula_signature(item['formula']),
                    'The actual original financial formula differs from its audited expression')
            expression = mutate_expression(field, item['expression'], refs)
            after = '=' + expression_formula(expression)
            require(len(after) <= 8192 and formula_signature(after) != formula_signature(cell.value),
                    'The prospective mutation is unchanged or exceeds the formula-length bound')
            edits.append({'sheet': item['sheet'], 'cell': item['cell'], 'before': cell.value, 'after': after,
                'reason': POLICIES[field], 'business_rule': field, 'mutation_policy': field})
            if field == 'bank_interest':
                source_row = ledger['scenarios'][sid]['entities'][identity]['monthly'][public['months'].index(month)]
                if type(source_row['bank_interest']) is int and source_row['bank_interest'] >= 2:
                    priority.append(len(edits) - 1)
            inventory[field]['selected'] += 1
    finally:
        book.close()
    logical_expected = len(public['entities']) * len(public['months']) * len(public['scenarios'])
    for row in inventory.values():
        row['logical_alias_bindings_without_a_separate_canonical_physical_row'] = row['complete_logical_field_bindings'] - row['selected']
    require(all(row['selected'] > 0 and row['complete_logical_field_bindings'] == logical_expected
                and row['logical_alias_bindings_without_a_separate_canonical_physical_row'] >= 0
                for row in inventory.values()) and 2 <= len(edits) <= 200000,
            'The complete predeclared policy inventory is absent or exceeds the explicit edit ceiling; do not truncate')
    require(public['dimension_mode'] != 'production' or priority,
            'The predeclared control order needs an actually active source bank-interest amount')
    priority_set = set(priority)
    edits = [edits[index] for index in priority] + [edit for index, edit in enumerate(edits) if index not in priority_set]
    return {'title': 'Repair the fixed-plan multi-entity monthly financial close', 'mode': 'debugging',
        'public_instruction': 'Repair the financial formulas in the supplied fixed-plan legal-entity model. '
            'The shared project choices are provided inputs. Reconcile each entity and the consolidated group across '
            'all three scenarios and every supplied month under Group Rules and the complete Group Contract. '
            + CLAUSES['debugging'],
        'public_rules': ['Group Contract contains the complete public primitive JSON; Group Inputs repeats its literal paths.',
            'Each Close sheet labels existing model cells by financial definition, period and legal owner. '
            'Financial amounts use functional minor units unless labelled GBP pence. Rate, factor and FX labels '
            'ending in p12 are integer numerators over 10^12; flags use integer 0 or 1 and dates use ISO text.',
            'Supplied exact-arithmetic helpers retain their formulas and their dependent values recalculate. '
            'A whole/remainder pair represents whole*10^12+remainder, with 0<=remainder<10^12; '
            'the whole component uses floor division, including for negative numerators.',
            'This is a forward close for the supplied fixed plan; do not change project choices or add an investment optimisation.'],
        'reference_evidence': {'source_manifest': proof['source_manifest'], 'financial_audits': proof['financial_audits'],
            'public_specification': proof['public_specification']},
        'scenario_inputs': [], 'edits': edits,
        'family_adapter': {'id': ADAPTER_ID, 'source_sha256': proof['workbook']['sha256'],
            'activity_contract': METHOD, 'physical_formula_mutation_count': len(edits),
            'physical_edits_sha256': canonical(_physical(edits)), 'complete_predeclared_policy_inventory': inventory,
            'ordered_control_priority': 'All independent-source bank-interest amounts >=2 minor units, then all remaining canonical source rows',
            'source_active_bank_interest_priority_count': len(priority),
            'priority_uses_model_or_control_outcomes': False,
            'mutations_truncated': False, 'selection_uses_model_outcomes': False,
            'individual_or_marginal_activity_claimed': False, 'optimisation_performed': False}}


class EntityGroupPlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        if not enabled(ctx):
            return normal.PlanNode().execute(ctx)
        proof = context_proof(ctx)
        plan = propose_from_checked_proof(ctx.data['baseline'], proof)
        ctx.save('entity_group_policy_inventory.json', plan['family_adapter'])
        return {'plan': plan, 'source_assessment': {'financial_evidence': deepcopy(ctx.data['finance_evidence']),
            'authoring_backend': ADAPTER_ID, 'full_quality_and_difficulty_pending': True}}


def validate_copies():
    validate_upstream_validator()
    pairs = ((normal.ProfileNode.execute, EntityGroupProfileNode._execute_profile),
             (SCCConstructNode._execute_scc, EntityGroupConstructNode._execute_scc),
             (quality.RepairNode.execute, EntityGroupRepairNode._execute_repair))
    for before, after in pairs:
        a = ast.parse(textwrap.dedent(inspect.getsource(before)))
        b = ast.parse(textwrap.dedent(inspect.getsource(after)))
        b.body[0].name = a.body[0].name
        require(ast.dump(a) == ast.dump(b), 'A family adapter copy changed an unapproved normal gate or route')
    before = ast.parse(textwrap.dedent(inspect.getsource(quality.DiagnoseNode.execute)))
    after = ast.parse(textwrap.dedent(inspect.getsource(EntityGroupDiagnoseNode._execute_diagnose)))
    after.body[0].name = before.body[0].name
    needle = ast.dump(ast.parse("not ctx.data['recovery']['verified']", mode='eval').body)
    replacement = ast.parse("not valid_entity_group_recovery_witness(ctx, ctx.data['recovery'])", mode='eval').body
    class WitnessGuard(ast.NodeTransformer):
        count = 0
        def visit_UnaryOp(self, node):
            if ast.dump(node) == needle:
                self.count += 1
                return deepcopy(replacement)
            return self.generic_visit(node)
    substitution = WitnessGuard(); before = substitution.visit(before)
    require(substitution.count == 1 and ast.dump(before) == ast.dump(after),
            'The family diagnosis may change only the mandatory strict-witness validator lookup')


def valid_entity_group_recovery_witness(ctx, candidate):
    from ..workbook.entity_group_public_recovery import valid_entity_group_recovery_witness as validate
    return validate(ctx, candidate)


class EntityGroupProfileNode(normal.ProfileNode):
    def execute(self, ctx):
        if not enabled(ctx):
            return super().execute(ctx)
        return self._execute_profile(ctx)


    def _execute_profile(self, ctx):
        path = ctx.data['source_cache'] / 'profile.json'
        contract = construction_contract(ctx.mode, ctx.config)
        limits = {'max_profile_cells': contract['source_requirements']['max_profile_cells'],
                  'per_formula_reference_cells': contract['dependency_requirements']['per_formula_reference_cells']}
        profile = json.loads(path.read_text()) if path.exists() else None
        legacy_limits = {'max_profile_cells': 200000, 'per_formula_reference_cells': 5000}
        if profile is None or profile.get('analysis_limits', legacy_limits) != limits:
            profile = profile_workbook(ctx.data['baseline'], max_cells=limits['max_profile_cells'],
                                       per_formula_reference_cells=limits['per_formula_reference_cells'])
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
        if profile['nonempty_sheet_count'] < 4 or profile['formula_count'] < 6:
            raise TaskRejected('Source lacks four nonempty sheets or a usable formula model')
        if profile['truncated']:
            raise TaskRejected('Full profile exceeds the configured coverage limit')
        if not any(any(ref['sheet'] != sheet['name'] for ref in cell.get('dependencies', {}).get('references', []))
                   for sheet in profile['sheets'] for cell in sheet['cells'] if cell.get('formula')):
            raise TaskRejected('Source contains no genuine cross-sheet formula dependency')
        return {'profile': profile}


class EntityGroupConstructNode(SCCConstructNode):
    def execute(self, ctx):
        if not enabled(ctx):
            return normal.ConstructNode().execute(ctx)
        proof = context_proof(ctx)
        expected = propose_from_checked_proof(ctx.data['baseline'], proof)
        require(ctx.data['plan'].get('family_adapter') == expected['family_adapter']
                and not ctx.data['plan'].get('scenario_inputs') and 'mask_ranges' not in ctx.data['plan']
                and _physical(ctx.data['plan'].get('edits', [])) == _physical(expected['edits']),
                'The complete prospective financial-policy mutation inventory changed')
        return self._execute_scc(ctx, {'activity_contract': METHOD})


    def _execute_scc(self, ctx, binding):
        public, private = ctx.revision_dir / 'public', ctx.revision_dir / 'private'
        public.mkdir(parents=True, exist_ok=True); private.mkdir(parents=True, exist_ok=True)
        goal = private / 'goal.xlsx'
        scenario = ctx.data['plan'].get('scenario_inputs', [])
        if scenario:
            scenario_limit = construction_contract(ctx.mode, ctx.config)['scenario_inputs']['max_count']
            if len(scenario) > scenario_limit:
                raise TaskRejected(f'Scenario input set exceeds supported scope (actual={len(scenario)}, max={scenario_limit})')
            base = openpyxl.load_workbook(ctx.data['baseline'], keep_links=False)
            for item in scenario:
                cell = base[item['sheet']][item['cell']]
                after = item['after']
                if cell.data_type == 'f' or cell.value != item.get('before') or isinstance(after, bool) or not isinstance(after, (int, float)) or not math.isfinite(after):
                    base.close()
                    raise TaskRejected('Scenario inputs must match numeric/blank public source inputs')
                if cell.value is not None and (isinstance(cell.value, bool) or not isinstance(cell.value, (int, float))):
                    base.close(); raise TaskRejected('Scenario cannot overwrite labels, dates or text')
                cell.value = after
            raw_baseline = private / 'scenario_baseline_raw.xlsx'; base.save(raw_baseline); base.close()
            ctx.engine.recalculate(raw_baseline, goal)
            ctx.save('scenario_inputs.json', scenario)
        else:
            shutil.copy2(ctx.data['baseline'], goal)
        validation = validate_plan(ctx.data['plan'], goal, ctx.mode, ctx.config)
        book = openpyxl.load_workbook(goal, keep_links=False)
        edits = ctx.data['plan']['edits']
        for edit in edits:
            book[edit['sheet']][edit['cell']] = edit['after']
        draft = private / 'mutated_unrecalculated.xlsx'
        book.save(draft); book.close()
        input_file = ctx.engine.recalculate(draft, public / 'input.xlsx')
        delta = compare_workbooks(input_file, goal, goal)
        if not delta.get('expected_change_count'):
            raise TaskRejected('Q06: mutation has no observable normalized value impact')
        if ctx.mode == 'financial_modeling' and any(
                e['sheet'] + '!' + e['cell'] not in delta['expected_changes'] for e in edits):
            raise TaskRejected('Q06: at least one masked target has no observable value change')
        native_guard = evaluate_native_risk_guard(delta['expected_changes'], ctx.data.get('source_id'),
            project_root=ctx.config['project_root'], sheet_names=delta.get('goal_sheets', []),
            registry_path=ctx.config.get('native_risks', {}).get('registry_path'),
            legacy_risks=ctx.data.get('source_business_issues', []))
        # Persist before rejection so the repair planner receives the actual D
        # intersection, including downstream cells outside physical edits.
        ctx.save('plan.json', ctx.data['plan']); ctx.save('expected_delta.json', delta)
        ctx.save('native_risk_guard.json', native_guard)
        ctx.data['native_risk_guard'] = native_guard
        ctx.audit.emit('native_risk_guard.result', task_id=ctx.task_id, revision=ctx.revision,
                       state=native_guard['state'], blocking=native_guard['blocking'],
                       risk_ids=[issue['risk_id'] for issue in native_guard['issues']])
        if native_guard['blocking']:
            affected = sorted({cell for issue in native_guard['issues'] if issue['certainty'] == 'confirmed'
                               for cell in issue['affected_cells']})
            raise TaskRejected('Q09: confirmed native unsafe region intersects complete changed-value set: '
                               + ', '.join(affected[:16]) + '; see private/native_risk_guard.json')
        # Cached errors in an expanded lookup range are provisional, never
        # automatically cleared. Recheck the complete actual D, not roots only.
        error_probe = probe_native_errors(goal=goal, required_delta=delta['expected_changes'],
            candidates=validation['native_error_candidates'], engine=ctx.engine,
            directory=private / 'native_error_probes', source_sha256=ctx.data.get('source_id') or digest(ctx.source),
            plan=ctx.data['plan'], revision=ctx.revision,
            immutable_files={'source': ctx.source, 'baseline': ctx.data['baseline']},
            engine_metadata=ctx.data.get('engine_report', {}).get('engine'),
            max_dependency_cells=construction_contract(ctx.mode, ctx.config)['dependency_requirements']['max_dependency_closure_cells'],
            per_formula_reference_cells=construction_contract(ctx.mode, ctx.config)['dependency_requirements']['per_formula_reference_cells'])
        validation['native_error_probe'] = error_probe
        validation['native_error_candidates'] = error_probe.get('candidates', validation['native_error_candidates'])
        validation['native_error_candidates_provisional'] = bool(validation['native_error_candidates'])
        ctx.save('native_error_probe.json', error_probe)
        ctx.save('edit_validation.json', validation)
        ctx.data['construction_validation'] = validation
        ctx.audit.emit('native_error_probe.result', task_id=ctx.task_id, revision=ctx.revision,
                       state=error_probe['state'], blocking=error_probe['blocking'],
                       candidates=len(error_probe['candidates']), probes=len(error_probe['probes']),
                       duration_ms=error_probe['duration_ms'])
        if error_probe['blocking']:
            raise TaskRejected(error_probe['problem_id'] + ': ' + error_probe.get('reason', 'native-error evidence incomplete')
                               + '; see private/native_error_probe.json')
        root_impacts = self._prove_activity(ctx, binding, goal, input_file, draft, edits, delta, private, validation)
        analysis = construction_contract(ctx.mode, ctx.config)
        public_profile = profile_workbook(input_file,
            max_cells=analysis['source_requirements']['max_profile_cells'],
            per_formula_reference_cells=analysis['dependency_requirements']['per_formula_reference_cells'])
        ctx.save('plan.json', ctx.data['plan']); ctx.save('edit_validation.json', validation)
        ctx.save('expected_delta.json', delta); ctx.save('root_impacts.json', root_impacts)
        ctx.save('profile.json', public_profile, private=False)
        return {'input': input_file, 'goal': goal, 'public_profile': public_profile,
                'delta': delta, 'construction_validation': validation, 'root_impacts': root_impacts,
                'native_risk_guard': native_guard}


class EntityGroupRepairNode(quality.RepairNode):
    def execute(self, ctx):
        if not enabled(ctx):
            return super().execute(ctx)
        context_proof(ctx)
        assessment = {'financial_evidence': deepcopy(ctx.data['finance_evidence']),
            'authoring_backend': ADAPTER_ID, 'full_quality_and_difficulty_pending': True}
        require(not ctx.data.get('source_assessment') or ctx.data['source_assessment'] == assessment,
                'A repair cannot replace the complete original source assessment')
        ctx.data['source_assessment'] = assessment
        return self._execute_repair(ctx)


    def _execute_repair(self, ctx):
        routes = ctx.data.get('repair_routes', [])
        issues = {issue['issue_id']: issue for issue in ctx.data.get('diagnosis', {}).get('issues', [])}
        if not routes or any(route['route_class'] != 'repair'
            or issues.get(route['issue_id'], {}).get('certainty') != 'confirmed' for route in routes):
            raise TaskRejected('Content repair requires confirmed repair-class routes; collect evidence or retry infrastructure first')
        payload = {**authoring_source_context(ctx), 'construction_contract': construction_contract(ctx.mode, ctx.config),
                   'task_mode': ctx.mode, 'current_plan': ctx.data['plan'],
                   'diagnosis': ctx.data.get('diagnosis'), 'construction_error': ctx.data.get('construction_error'),
                   'assigned_repair_routes': routes,
                   'native_risk_guard': ctx.data.get('native_risk_guard', {}),
                   'source_business_issues': ctx.data.get('source_business_issues', []),
                   'source_profile': compact_profile(ctx.data['profile']),
                   'remaining_steps': ctx.config['run']['max_steps'] - ctx.revision}
        requested = [route['issue_id'] for route in routes]
        instruction_only = all(route.get('problem_id') == 'Q03' for route in routes)
        options = {}
        if instruction_only:
            from ..llm.schemas import instruction_repair_output_schema
            options['output_schema'] = instruction_repair_output_schema(requested)
            payload['repair_contract'] = {'permitted_changed_plan_fields': ['public_instruction'],
                                         'preserve_all_other_fields_programmatically': True}
        result = ctx.llm.complete(prompt(ctx, 'instruction_repair.md' if instruction_only else 'repair.md')
                                 + '\nINPUT JSON:\n' + json.dumps(payload, ensure_ascii=False, default=str),
                                 role='repair_planner', task_id=ctx.task_id, stage=self.node_id,
                                 timeout=ctx.config['agents']['timeout_seconds'], **options)
        ctx.save('repair_proposal.json', result)
        if instruction_only:
            proposed = apply_instruction_repair(ctx.data['plan'], result, requested)
            ctx.save('instruction_repair_receipt.json', {'assigned_issue_ids': requested,
                'changed_plan_fields': ['public_instruction'], 'requires_full_revision_gates': True,
                'reuse_old_harbor_controls': False})
            return {'next_plan': proposed}
        requested = set(requested)
        addressed = set(result.get('addressed_issue_ids', []))
        if result.get('repaired_task') and not requested <= addressed:
            raise TaskRejected('Repair proposal did not account for all assigned issue instances')
        return {'next_plan': result.get('repaired_task')}


class EntityGroupExportNode(quality.ExportNode):
    node_id = 'export'

    def execute(self, ctx):
        if not enabled(ctx):
            return super().execute(ctx)
        context_proof(ctx)
        require(valid_entity_group_recovery_witness(ctx, ctx.data.get('recovery', {})),
                'A current, strictly bound public-only recovery witness is required before export')
        actual_base = verify_local_base_image(ctx.config[SETTING]['runtime_profile']['path'])
        ctx.save('entity_group_actual_local_base_image.json', actual_base)
        destination = Path(ctx.config['run_dir']) / 'SpreadsheetEval' / ctx.task_id
        # Resume's existing quarantine preserves older completed exports. An
        # unexpected nonempty destination is rejected instead of overwritten.
        require(not destination.exists() or not any(destination.iterdir()),
                'The resource export needs a fresh directory; preserve any prior attempt')
        metadata = {'task_id': ctx.task_id, 'mode': ctx.mode, 'source_id': ctx.data['source_id'],
                    'source_file': ctx.source.name, 'difficulty_status': (
                        'deferred' if ctx.config.get('diagnosis', {}).get('difficulty_deferred', True) else 'pending'),
                    'revision': ctx.revision, 'revision_hash': ctx.data['revision_hash'],
                    'base_image': ctx.config['engine']['image']}
        export_resource_harbor(ctx.revision_dir, destination, metadata, ctx.config['project_root'],
            runtime_profile=ctx.config[SETTING]['runtime_profile']['path'])
        binding = inspect_resource_export(destination)
        require(binding['task_id'] == ctx.task_id and binding['revision'] == ctx.revision
                and binding['revision_hash'] == ctx.data['revision_hash'], 'The exact resource export binding differs')
        (ctx.directory / 'lineage.json').write_text(json.dumps(metadata, indent=2))
        return {'export_dir': destination}


class EntityGroupDiagnoseNode(quality.DiagnoseNode):
    def execute(self, ctx):
        if not enabled(ctx):
            return super().execute(ctx)
        context_proof(ctx)
        return self._execute_diagnose(ctx)


    def _execute_diagnose(self, ctx):
        from ..llm.schemas import diagnosis_output_schema
        policy = validate_reference_policy_selection(ctx.config)
        binding, review_context, review_artifacts = None, None, None
        if policy == 'reference_review':
            binding = reference_revision_binding(ctx)
            review_context, review_artifacts = _reference_review_context(ctx, binding)
        diagnosis_prompt = prompt(ctx, 'diagnosis.md')
        public = {'instruction': ctx.data['instruction'], 'profile': compact_profile(ctx.data['public_profile']),
                  'rules': ctx.data['plan']['public_rules'], 'task_mode': ctx.mode,
                  'difficulty_review_context': candidate_difficulty_context(ctx.config),
                  'input_sha256': hashlib.sha256(Path(ctx.data['input']).read_bytes()).hexdigest()}
        private = {'plan': ctx.data['plan'], 'construction': ctx.data['construction_validation'],
                   'expected_delta': ctx.data['delta'], 'root_impacts': ctx.data['root_impacts'],
                   'independent_recovery': ctx.data['recovery'],
                   'source_assessment': ctx.data.get('source_assessment', {}),
                   'native_risk_guard': ctx.data.get('native_risk_guard', {}),
                   'source_business_issues': ctx.data.get('source_business_issues', []),
                   'goal_sha256': hashlib.sha256(Path(ctx.data['goal']).read_bytes()).hexdigest(),
                   'native_errors': ctx.data['profile']['errors']}
        if policy == 'reference_review':
            public['reference_evidence_policy'] = policy
            private['reference_review_context'] = review_context
            private['reference_review_requirements'] = {
                'policy': policy, 'binding': binding,
                'goal_artifact': 'reference.xlsx',
                'instructions': 'Q04 must inspect the actual reference.xlsx, source business evidence, complete expected delta, financial identities and independent calculations. Existing formula existence alone is not truth. No exact public solver is required or claimed. Q01/Q02/Q03 must independently establish public sufficiency and scope.',
                'required_Q04_evidence_string': REFERENCE_REVIEW_PREFIX + json.dumps({
                    'binding': binding, 'business_evidence': ['Concrete source business policy and inspected public evidence'],
                    'financial_validation_checks': [{'check': 'Concrete financial identity or independent recalculation',
                        'method': 'Describe the independent calculation actually performed',
                        'passed': True, 'evidence': ['Actual inspected cells, calculation and observed result']}]}),
            }
        health = {'healthy': all(not t.get('infrastructure_error') for t in ctx.data['traces']),
                  'checks': [{'probe': 'codex_native_cli', 'model': ctx.llm.model},
                             {'probe': 'libreoffice_full_recalculation', 'engine': ctx.data['engine_report']}]}
        bundle = {'task_id': ctx.task_id, 'revision_hash': ctx.data['revision_hash'],
                  'revision': ctx.revision,
                  'public': public, 'private': private, 'engine_report': ctx.data['engine_report'],
                  'infrastructure_health_report': health}
        bundle['reviewer_context_hash'] = hashlib.sha256(json.dumps({
            'prompt': diagnosis_prompt, 'agents': ctx.config['agents'],
            'private_evidence_transport': PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS,
            'schema_contract': diagnosis_output_schema(['Q01'])},
            sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

        def review(payload):
            is_public = payload['visibility'] == 'public_only'
            work = prepare_workspace(ctx, 'diagnostic_public' if is_public else 'diagnostic_private')
            evidence = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
            (work / 'evidence.json').write_bytes(evidence)
            instruction = (diagnosis_prompt + '\nRead /workspace/evidence.json for all assigned '
                           'checks and evidence. Inspect input.xlsx/instruction.md as necessary. Return JSON only.')
            if not is_public:
                if policy == 'reference_review':
                    shutil.copy2(ctx.data['goal'], work / 'reference.xlsx')
                receipt = {'file': 'evidence.json', 'sha256': hashlib.sha256(evidence).hexdigest(),
                           'bytes': len(evidence), 'assigned_check_ids': payload['assigned_check_ids']}
                instruction = diagnosis_prompt + PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS + json.dumps(receipt)
            instruction += ('\nReturn assessments as an object keyed by every assigned_check_id exactly once. '
                            'Follow the supplied output schema; missing assigned checks are a backend protocol failure.')
            return ctx.llm.complete(instruction, role='public_diagnostician' if is_public else 'reference_diagnostician',
                                    task_id=ctx.task_id, stage=self.node_id, workspace=work,
                                    isolated=is_public, timeout=ctx.config['agents']['timeout_seconds'],
                                    output_schema=diagnosis_output_schema(payload['assigned_check_ids']))

        runner = DiagnosisRunner(ctx.config['project_root'])
        report = runner.diagnose(bundle, ctx.data['traces'], ctx.data['controls'], review, ctx.config,
                                batch_cache=ctx.data.setdefault('diagnostic_batch_cache', {}))
        ctx.save('diagnostic_batch_cache.json', ctx.data['diagnostic_batch_cache'])
        if policy == 'reference_review':
            receipt = reference_review_assessments(report, binding)
            receipt['artifacts'] = review_artifacts
            receipt['diagnostic_run_id'] = report['diagnostic_run_id']
            receipt['check_plan_hash'] = report['check_plan_hash']
            ctx.save('reference_review.json', receipt)
            report.update(reference_evidence_policy=policy, reference_validation_method=policy,
                reference_binding=binding, reference_review=receipt,
                mandatory_gates={'reference_review': {'passed': receipt['passed'], 'required_check_ids': list(REFERENCE_REVIEW_CHECKS)}})
            if not receipt['passed']:
                report['issues'].append({'issue_id': ctx.task_id + '-Q12-reference-review',
                    'problem_id': 'Q12', 'severity': 'blocker', 'certainty': 'confirmed',
                    'claim': 'Reference review lacks current supported public and financial evidence',
                    'revision_hash': ctx.data['revision_hash'], 'depends_on_issue_ids': [],
                    'evidence': receipt['problems']})
            evidence_passed = receipt['passed']
        elif not valid_entity_group_recovery_witness(ctx, ctx.data['recovery']):
            issue = {'issue_id': ctx.task_id + '-Q12-recovery', 'problem_id': 'Q12',
                'severity': 'blocker', 'certainty': 'confirmed',
                'claim': 'Independent public-information reconstruction has not matched reference values',
                'revision_hash': ctx.data['revision_hash'], 'depends_on_issue_ids': [],
                'evidence': [ctx.data['recovery'].get('comparison', ctx.data['recovery'].get('error', 'no output'))]}
            report['issues'].append(issue)
            # Mandatory recovery is separate from optional diagnostic selection.
            # A disabled Q12 plugin remains skipped, but cannot disable this gate.
            report['mandatory_gates'] = {'independent_recovery': {'passed': False, 'issue_id': issue['issue_id']}}
            if 'Q12' in report['enabled_check_ids']:
                assessment = report['assessments']['Q12']
                assessment.update(state='flagged', reason=issue['claim'])
                assessment.setdefault('evidence', []).extend(issue['evidence'])
                assessment.setdefault('issue_ids', []).append(issue['issue_id'])
            evidence_passed = False
        else:
            report['mandatory_gates'] = {'independent_recovery': {'passed': True}}
            evidence_passed = True
        report['routes'] = route_issues(report['issues'], runner.catalog,
                                        ctx.config.get('diagnosis', {}).get('difficulty_deferred', False))
        report['coverage']['blocking_issue_ids'] = [issue['issue_id'] for issue in report['issues']
            if issue.get('severity', 'blocker') == 'blocker'
            and not (issue['problem_id'] == 'Q08' and runner.resolve(ctx.config)['difficulty_deferred'])]
        report['releasable'] = (report['releasable'] and evidence_passed
                                and not report['coverage']['blocking_issue_ids'])
        ctx.save('diagnosis.json', report)
        ctx.audit.task(ctx.task_id, issues=report['issues'], diagnosis_scope=report['scope'])
        for check, assessment in report['assessments'].items():
            ctx.audit.emit('checker.result', task_id=ctx.task_id, revision=ctx.revision,
                           checker=check, state=assessment['state'], reason=assessment['reason'])
        return {'diagnosis': report}
