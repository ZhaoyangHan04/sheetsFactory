"""Opt-in SCC-v8 activity at the ordinary Construct phase.

The unchanged upstream implementation has no root-proof injection point. Its
construction prefix and final profile/persistence suffix are copied below and
locked to its exact source SHA and AST. Only root activity uses the opt-in v8
provider. All other nodes, financial sources and default construction delegate.
"""
from __future__ import annotations

import math
import shutil
from uuid import uuid4

import openpyxl

from ..core.node import TaskRejected
from ..workbook import profile_workbook, compare_workbooks
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..checkers.native_error_probe import probe_native_errors
from ..pipelines.scc_activity_admission import validate_context_binding, validate_certificate, validate_index_policy
from ..pipelines.joint_repair_activity import METHOD as JOINT_METHOD, prove_joint_repair, validate_joint_certificate
from ..task_adapters.public_input_priority import ref
from .construction import ConstructNode, construction_contract, validate_plan, digest


class SCCConstructNode(ConstructNode):
    node_id = 'construct'

    def execute(self, ctx):
        try:
            binding = validate_context_binding(ctx)
        except ValueError as exc:
            raise TaskRejected('Q06: SCC activity admission rejected: ' + str(exc)) from exc
        if binding is None:
            return super().execute(ctx)
        return self._execute_scc(ctx, binding)

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


    def _prove_activity(self, ctx, binding, goal, input_file, draft, edits, delta, private, validation):
        if binding['activity_contract'] == JOINT_METHOD:
            certificate = prove_joint_repair(goal=goal, combined_input=input_file, raw_mutation=draft,
                edits=edits, delta=delta, engine=ctx.engine,
                directory=private / 'joint_repair_probes' / uuid4().hex)
            receipt = ctx.save('joint_repair_certificate.json', certificate)
            ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
                method=JOINT_METHOD, state=certificate.get('state'), passed=certificate.get('passed'),
                physical_formula_mutation_count=len(edits),
                actual_joint_workbook_LO_executions=certificate.get('actual_joint_workbook_LO_execution_count'))
            if certificate.get('state') == 'execution_error':
                raise RuntimeError('Joint-workbook recalculation failed: ' + str(certificate.get('reason')))
            try:
                summary = validate_joint_certificate(certificate, goal, input_file, edits, delta)
            except ValueError as exc:
                raise TaskRejected('Q06: joint-workbook proof rejected: ' + str(exc)) from exc
            validation['root_impact_validation'] = {
                'method':JOINT_METHOD, 'physical_formula_mutation_count':len(edits),
                'physical_edits_in_actual_D_count':summary['physical_edits_in_actual_D_count'],
                'unobservable_physical_edit_count':summary['unobservable_physical_edit_count'],
                'complete_required_D_count':summary['complete_required_D_count'],
                'native_input_error_count':len(summary['native_input_errors']),
                'individual_or_marginal_activity_claimed':False,
                'counterfactual_uniqueness_claimed':False,'joint_input_global_uniqueness_claimed':False,
                'actual_joint_workbook_LO_execution_count':2,'certificate':ref(receipt),
                'five_controls_recovery_quality_Harbor_pending':True,
                'semantic_mutation_quality_pending':True}
            # No synthetic per-root impacts are returned in the joint contract.
            return []
        # Activity alone is replaced. Complete D and native-error policy above
        # remain the ordinary construction evidence; this is no 2N replay claim.
        limits = construction_contract(ctx.mode, ctx.config)['dependency_requirements']
        kwargs = dict(binding['proof_limits'])
        if binding['allow_constant_index_ancestors']:
            kwargs['allow_constant_index_ancestors'] = True
        certificate = binding['provider'].prove_scc_island_root_impacts(
            goal=goal, combined_input=input_file, edits=edits, engine=ctx.engine,
            directory=private / 'scc_v8_root_impact_probes' / uuid4().hex,
            max_dependency_cells=limits['max_dependency_closure_cells'],
            per_formula_reference_cells=limits['per_formula_reference_cells'], **kwargs)
        ctx.save('scc_v8_roots_certificate.json', certificate)
        ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
            method='scc_island_v8', state=certificate.get('state'), passed=certificate.get('passed'),
            root_count=len(edits), actual_checker_LO_executions=certificate.get('actual_LO_execution_count'),
            duration_ms=certificate.get('duration_ms'))
        if certificate.get('state') == 'execution_error':
            raise RuntimeError('SCC-v8 root-impact recalculation failed: ' + str(certificate.get('reason')))
        try:
            validate_index_policy(certificate, binding['allow_constant_index_ancestors'])
            root_impacts = validate_certificate(certificate, goal, input_file, edits,
                provider=binding['provider'], checker_reference=binding['setting']['checker'])
        except ValueError as exc:
            raise TaskRejected('Q06: SCC-v8 root-impact proof rejected: ' + str(exc)) from exc
        validation['root_impact_validation'] = {
            'method': 'scc_island_v8', 'proof_method': certificate['proof_method'],
            'root_count': len(root_impacts), 'actual_checker_LO_execution_count': 6,
            'individual_LO_executions': False, 'marginal_LO_executions': False,
            'counts_are_lower_bounds': True, 'complete_per_root_changed_sets_claimed': False,
            'counterfactual_uniqueness_claimed': False,
            'source_uniqueness_transferred_to_mutants': False}
        return root_impacts
