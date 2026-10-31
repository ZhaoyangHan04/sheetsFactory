"""Explicit business-value FM nodes; original formula-based routes stay intact."""
from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import shutil
import textwrap

import openpyxl

from ..nodes import construction as normal, quality
from ..nodes.quality import (validate_reference_policy_selection, reference_revision_binding,
    _reference_review_context, prompt, compact_profile, candidate_difficulty_context,
    PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS, REFERENCE_REVIEW_PREFIX, REFERENCE_REVIEW_CHECKS,
    prepare_workspace, reference_review_assessments)
from ..core.node import TaskRejected
from ..checkers import DiagnosisRunner
from ..checkers.router import route_issues
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..checkers.native_error_probe import probe_native_errors
from ..evaluation.streaming_delta import compare_workbooks
from ..evaluation.streaming_verifier import compare_files
from ..evaluation.resource_harbor import export_resource_harbor, inspect_resource_export, verify_local_base_image
from ..workbook.profile_indexed import profile_workbook
from ..workbook.resource_engine import load_runtime_profile
from ..workbook.heterogeneous_contracts import policy_specialization as native_references
from . import heterogeneous_financial_view as base

ROOT = base.ROOT
SETTING = 'heterogeneous_business_modeling'
ADAPTER_ID = 'heterogeneous_complete_business_projection_normal_FM_v1'
BACKEND = 'heterogeneous_public_tables_shared_decimal_financial_ledger'
VIEW_NAME = 'sheets_factory.task_adapters.heterogeneous_financial_view_v3'
REPLAY_NAME = 'sheets_factory.workbook.heterogeneous_business_view_replay'
REGISTRY = ROOT / 'config/task_adapters/heterogeneous_business_modeling_nodes.yaml'
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
require, reference, canonical = base.require, base.reference, base.canonical


def setting(runtime_profile=PROFILE):
    view, replay = importlib.import_module(VIEW_NAME), importlib.import_module(REPLAY_NAME)
    return {'enabled': True, 'version': 1, 'adapter': ADAPTER_ID, 'implementation': reference(__file__),
        'registry': reference(REGISTRY), 'view_module': reference(view.__file__), 'view_version': 3,
        'view_policy': reference(view.DEFAULT_POLICY), 'recovery': reference(replay.__file__),
        'native_reference_parser': reference(native_references.__file__),
        'runtime_profile': reference(runtime_profile),
        'excluded_entity_fields': ['cure_open', 'cure_next', 'cash_before_financing', 'trap_operative']}


def validate_setting(value):
    require(isinstance(value, dict) and type(value.get('version')) is int and value['version'] == 1
        and value.get('enabled') is True and value == setting(value['runtime_profile']['path']),
        'The explicit current business-view family code, policy and profile must be frozen')
    require(load_runtime_profile(value['runtime_profile']['path'])['id'] == 'entity_group_large_v2',
        'The approved business-view runtime profile is required')
    validate_diagnose_copy()
    return value


def enabled(ctx):
    if ctx.config.get(SETTING) is None: return False
    validate_setting(ctx.config[SETTING])
    require(ctx.mode == 'financial_modeling', 'The business projection supports only financial modeling')
    return True


def context_proof(ctx):
    from ..pipelines.heterogeneous_business_quality import ProjectionAdmission
    require(enabled(ctx), 'The business projection route is required')
    session = ctx.data.get('_heterogeneous_admission')
    require(isinstance(session, ProjectionAdmission), 'An opaque live source/projection admission is required')
    proof = session.guard()
    require(reference(ctx.source) == proof['native_source']
        and ctx.config[SETTING]['runtime_profile'] == proof['runtime_profile'],
        'The actual native source identity or resource profile changed')
    for key in ('baseline', 'input', 'goal'):
        if ctx.data.get(key):
            actual = reference(ctx.data[key]); expected = proof['input' if key == 'input' else 'goal']
            require((actual['sha256'], actual['bytes']) == (expected['sha256'], expected['bytes']),
                'An admitted business projection file changed: ' + key)
    return proof


def construction_contract(mode=None, config=None):
    result = normal.construction_contract(mode, config)
    result = deepcopy(result)
    result['target_requirements'].update(original_must_be_existing_formula=False,
        before_must_equal_original_formula_exactly=False, original_must_equal_audited_business_literal=True)
    result['dependency_requirements'].update(true_cross_sheet_formula_edge_in_target_closure=False,
        native_source_complete_financial_dependency_provenance_required=True,
        projection_constants_must_not_be_reported_as_formulas=True)
    return result


def canonical_plan(admission):
    p = admission.proof; view = admission.plan
    edits = [{'sheet': r['sheet'], 'cell': r['cell'], 'before': base._untyped(r['reference_value']),
        'after': None, 'reason': 'Complete the labelled business forecast.',
        'business_rule': 'Apply the supplied raw business assumptions and complete Contract Notes.'}
        for r in view['forecast_targets'] if r['reference_value'][0] != 'empty']
    return {'title': 'Complete the heterogeneous monthly business forecasts', 'mode': 'financial_modeling',
        'public_instruction': view['original_brief'],
        'public_rules': ['The supplied Contract Notes govern the labelled business forecasts, including applicable zero amounts and policy-defined covenant blanks.'],
        'reference_evidence': [{'kind': 'audited_native_financial_model_and_business_projection', 'admission': p}],
        'scenario_inputs': [], 'edits': edits,
        'family_adapter': {'id': ADAPTER_ID, 'view_plan_sha256': view['plan_sha256'],
            'projection_manifest': p['projection_manifest'], 'declared_business_slots': len(view['forecast_targets']),
            'physical_masked_nonempty_business_values': len(edits), 'policy_blank_slots_are_not_physical_edits': True,
            'reference_is_audited_source_values_not_formula_definitions': True}}


class HeterogeneousBusinessNormalizeNode(normal.NormalizeNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        proof = context_proof(ctx)
        cache = Path(ctx.config['run_dir']) / 'sources' / proof['native_source']['sha256'][:12] / proof['view_plan_sha256'][:12]
        cache.mkdir(parents=True, exist_ok=True)
        baseline = cache / 'baseline.xlsx'
        if not baseline.exists(): shutil.copyfile(proof['goal']['path'], baseline)
        require(reference(baseline)['sha256'] == proof['goal']['sha256'], 'The projected baseline changed')
        receipt = {'method': 'verified_actual_native_source_to_literal_business_projection',
            'source': proof['native_source'], 'baseline': reference(baseline),
            'actual_projection_engine_calls': proof['actual_projection_engine_calls'],
            'actual_new_calculation_calls_by_this_node': 0,
            'source_and_baseline_are_distinct_artifacts': True, 'source_id_is_actual_native_SHA': True}
        ctx.save('business_projection_normalization.json', receipt)
        return {'source_id': proof['native_source']['sha256'], 'baseline': baseline, 'source_cache': cache,
            'engine_report': {'normalization_ok': True, 'recalculation_ok': True, 'stable': True,
                'normalization_artifact': str(baseline), 'normalization_evidence': receipt,
                'engine': ctx.engine.metadata()}}


class HeterogeneousBusinessProfileNode(normal.ProfileNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        proof = context_proof(ctx)
        limit = construction_contract(ctx.mode, ctx.config)['source_requirements']['max_profile_cells']
        profile = profile_workbook(ctx.data['baseline'], max_cells=limit, per_formula_reference_cells=5000)
        require(profile['truncated'] is False and profile['formula_count'] == 0
            and profile['nonempty_sheet_count'] >= 4 and not profile['errors'] and not profile['external_references'],
            'The complete audited literal business profile is required')
        profile['native_financial_source_evidence'] = {'source_admission': proof['native_source_admission'],
            'business_view_is_literal': True, 'formula_count_not_synthesized': True}
        ctx.save('business_projection_profile.json', profile)
        return {'profile': profile}


class HeterogeneousBusinessPlanNode(normal.PlanNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        proof = context_proof(ctx)
        return {'plan': canonical_plan(ctx.data['_heterogeneous_admission']),
            'source_assessment': {'financial_evidence': deepcopy(ctx.data.get('finance_evidence', {})),
                'native_source_admission': proof['native_source_admission'], 'business_projection_admission': proof,
                'source_and_reference_financial_truth_not_inferred_from_formula_existence': True}}


def native_dependency_provenance(admission):
    bindings = base._read(admission.proof['native_source_admission']['bindings']['path'])
    formulas, defined, coordinates = {}, set(), {}
    for key in ('arithmetic_bindings', 'financial_bindings', 'input_bindings', 'literal_bindings'):
        for row in bindings.get(key, []):
            cell = row['sheet'], row['cell']; defined.add(cell)
            coordinates[native_references._reference(row)] = cell
            if 'expression' in row:
                if cell in formulas: require(formulas[cell] == row['expression'], 'Conflicting native expression aliases')
                formulas[cell] = row['expression']
    def refs(expression):
        # Native bindings use absolute, sheet-qualified string references, not
        # a separate ['ref', sheet, cell] AST operator. Use the frozen emitter's
        # exact reference grammar and the complete physical coordinate map.
        strings = native_references._refs(expression)
        require(strings <= coordinates.keys(), 'The source dependency graph has an unresolved reference')
        return {coordinates[value] for value in strings}
    roots = {(r['source']['sheet'], r['source']['cell']) for r in admission.plan['forecast_targets']}
    pending = list(roots); seen = set(); cross = 0
    while pending:
        cell = pending.pop()
        if cell in seen: continue
        require(cell in defined, 'A source financial dependency is unbound')
        seen.add(cell)
        require(len(seen) <= 3_000_000, 'The complete native dependency closure exceeds its explicit family bound')
        for parent in refs(formulas.get(cell)):
            require(parent in defined, 'The source dependency graph has an unresolved reference')
            cross += int(parent[0] != cell[0]); pending.append(parent)
    require(cross > 0, 'A genuine native cross-sheet financial dependency is required')
    return {'kind': 'native_financial_dependency_provenance_for_literal_business_projection',
        'source_bindings': admission.proof['native_source_admission']['bindings'],
        'reference_parser': reference(native_references.__file__),
        'complete_selected_native_alias_count': len(roots), 'complete_dependency_closure_cells': len(seen),
        'native_cross_sheet_edges': cross, 'frontier_omitted': False,
        'native_source_audits': admission.proof['native_source_admission']['financial_audits'],
        'projected_formula_count': 0, 'not_a_projected_formula_dependency_claim': True}


class HeterogeneousBusinessConstructNode(normal.ConstructNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        proof = context_proof(ctx); session = ctx.data['_heterogeneous_admission']
        expected = canonical_plan(session)
        require({k: v for k, v in ctx.data['plan'].items() if k != 'public_instruction'} ==
            {k: v for k, v in expected.items() if k != 'public_instruction'}
            and bool(ctx.data['plan'].get('public_instruction')), 'A repair changed audited business truth or complete target scope')
        public, private = ctx.revision_dir / 'public', ctx.revision_dir / 'private'
        public.mkdir(parents=True, exist_ok=True); private.mkdir(parents=True, exist_ok=True)
        goal, source = private / 'goal.xlsx', public / 'input.xlsx'
        shutil.copyfile(proof['goal']['path'], goal); shutil.copyfile(proof['input']['path'], source)
        view = importlib.import_module(VIEW_NAME)
        projection = view.validate_view(session.plan, source, goal)
        delta = compare_workbooks(source, goal, goal)
        labels = {e['sheet'] + '!' + e['cell'] for e in expected['edits']}
        require(delta['reward'] == 1 and set(delta['expected_changes']) == labels
            and delta['expected_change_count'] == proof['full_D_count'], 'The complete actual business-value D differs from the declared masks')
        dependencies = native_dependency_provenance(session)
        native_labels = [r['source']['sheet'] + '!' + r['source']['cell'] for r in session.plan['forecast_targets']
            if r['reference_value'][0] != 'empty']
        guard = evaluate_native_risk_guard(native_labels, proof['native_source']['sha256'],
            project_root=ctx.config['project_root'], sheet_names=sorted({r['source']['sheet'] for r in session.plan['forecast_targets']}),
            registry_path=ctx.config.get('native_risks', {}).get('registry_path'), legacy_risks=ctx.data.get('source_business_issues', []))
        require(not guard['blocking'], 'Q09: native source risk intersects the audited business projection')
        probe = probe_native_errors(goal=goal, required_delta=delta['expected_changes'], candidates=[], engine=ctx.engine,
            directory=private / 'native_error_probes', source_sha256=proof['native_source']['sha256'],
            plan=ctx.data['plan'], revision=ctx.revision, immutable_files={'source':ctx.source,'baseline':ctx.data['baseline']},
            engine_metadata=ctx.data['engine_report']['engine'], max_dependency_cells=500000, per_formula_reference_cells=5000)
        require(not probe['blocking'], 'Q09/Q10: the complete projected D has an unresolved native error')
        validation = {'edit_count': len(expected['edits']), 'before_assertions_passed': True,
            'before_assertion_type': 'independently_audited_business_literal', 'before_must_be_formula': False,
            'projection_audit': projection, 'native_financial_dependency_evidence': dependencies,
            'native_error_candidates': [], 'native_error_probe': probe,
            'reference_values_not_modified': True, 'actual_new_LO_calls_by_construct': 0}
        for name, value in [('plan.json',ctx.data['plan']),('edit_validation.json',validation),('expected_delta.json',delta),
            ('root_impacts.json',[]),('native_risk_guard.json',guard),('native_error_probe.json',probe)]: ctx.save(name,value)
        profile = profile_workbook(source, max_cells=500000, per_formula_reference_cells=5000)
        require(not profile['truncated'] and not profile['errors'], 'The complete actual public profile is required')
        return {'input': source, 'goal': goal, 'delta': delta, 'construction_validation': validation,
            'root_impacts': [], 'native_risk_guard': guard, 'public_profile': profile}


class HeterogeneousBusinessInstructionNode(normal.InstructionNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        context_proof(ctx)
        text = ctx.data['plan']['public_instruction']
        require(type(text) is str and bool(text.strip()), 'A business completion brief is required')
        path = ctx.revision_dir / 'public/instruction.md'; path.write_text(text)
        return {'instruction':text,'instruction_path':path,
            'revision_hash':hashlib.sha256(Path(ctx.data['input']).read_bytes()+text.encode()).hexdigest()}


class HeterogeneousBusinessControlsNode(normal.ControlsNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        context_proof(ctx)
        source, goal = ctx.data['input'], ctx.data['goal']; private = ctx.revision_dir / 'private'
        controls = {'oracle':compare_workbooks(source,goal,goal),'nop':compare_workbooks(source,goal,source)}
        folder = private / 'controls'; folder.mkdir(parents=True,exist_ok=True)
        first = ctx.data['plan']['edits'][0]
        for name in ('equivalent','missed_root','extra_change'):
            book = openpyxl.load_workbook(goal,keep_links=False)
            try:
                if name == 'equivalent': book[first['sheet']][first['cell']] = '=IF(TRUE(),'+str(first['before'])+',"")'
                elif name == 'missed_root': book[first['sheet']][first['cell']] = None
                else: book[book.sheetnames[0]]['XFD100'] = 'unexpected extra value'
                raw = folder/(name+'_raw.xlsx'); book.save(raw)
            finally: book.close()
            actual = ctx.engine.recalculate(raw,folder/(name+'.xlsx'))
            controls[name] = compare_workbooks(source,goal,actual)
        ctx.save('local_controls.json',controls)
        require(all(controls[n]['reward'] == v for n,v in
            {'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}.items()), 'Q05/Q06: an actual business-value control failed')
        return {'controls':controls}


def valid_heterogeneous_business_recovery_witness(ctx, candidate):
    return importlib.import_module(REPLAY_NAME).valid_heterogeneous_business_recovery_witness(ctx,candidate)


class HeterogeneousBusinessDiagnoseNode(quality.DiagnoseNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
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
        elif not ctx.data['recovery']['verified']:
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



class HeterogeneousBusinessExportNode(quality.ExportNode):
    def execute(self, ctx):
        if not enabled(ctx): return super().execute(ctx)
        context_proof(ctx)
        require(valid_heterogeneous_business_recovery_witness(ctx,ctx.data.get('recovery',{})),
            'A strict current public-only recovery witness is required before export')
        ctx.save('business_actual_local_base_image.json', verify_local_base_image(ctx.config[SETTING]['runtime_profile']['path']))
        destination = Path(ctx.config['run_dir'])/'SpreadsheetEval'/ctx.task_id
        require(not destination.exists() or not any(destination.iterdir()), 'Preserve an existing immutable export')
        metadata = {'task_id':ctx.task_id,'mode':ctx.mode,'source_id':ctx.data['source_id'],'source_file':ctx.source.name,
            'revision':ctx.revision,'revision_hash':ctx.data['revision_hash'],'difficulty_status':'pending',
            'base_image':ctx.config['engine']['image']}
        export_resource_harbor(ctx.revision_dir,destination,metadata,ctx.config['project_root'],runtime_profile=ctx.config[SETTING]['runtime_profile']['path'])
        binding = inspect_resource_export(destination)
        require(binding['task_id'] == ctx.task_id and binding['revision_hash'] == ctx.data['revision_hash'], 'The complete resource export differs')
        ctx.save('business_resource_export_binding.json',binding)
        (ctx.directory/'lineage.json').write_text(json.dumps(metadata,indent=2))
        return {'export_dir':destination}


def validate_diagnose_copy():
    expected = ast.parse(textwrap.dedent(inspect.getsource(quality.DiagnoseNode.execute))).body[0]
    actual = ast.parse(textwrap.dedent(inspect.getsource(HeterogeneousBusinessDiagnoseNode._execute_diagnose))).body[0]
    expected.name = actual.name
    for node in ast.walk(expected):
        if isinstance(node,ast.Name) and node.id == '_valid_recovery_witness':
            node.id = 'valid_heterogeneous_business_recovery_witness'
    require(ast.dump(expected,include_attributes=False) == ast.dump(actual,include_attributes=False),
        'Normal twelve-check diagnosis changed beyond the declared strict family witness lookup')
