"""Prospective first-30-project FM adapter with complete public accounting scope."""
from __future__ import annotations

import ast
from copy import deepcopy
import importlib
import inspect
import hashlib
import json
import math
from pathlib import Path
import shutil
import textwrap
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from ..core.node import BaseNode,TaskRejected
from ..nodes import construction as normal,quality
from ..nodes.quality import (validate_reference_policy_selection, reference_revision_binding,
    _reference_review_context,candidate_difficulty_context,REFERENCE_REVIEW_PREFIX,
    REFERENCE_REVIEW_CHECKS,PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS,
    prepare_workspace,reference_review_assessments,route_issues,DiagnosisRunner)
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..checkers.native_error_probe import probe_native_errors
from ..workbook.profile_indexed import profile_workbook
from ..evaluation.streaming_delta import compare_workbooks
from ..evaluation.resource_harbor import export_resource_harbor,inspect_resource_export,verify_local_base_image
from ..task_adapters.public_input_priority import canonical
from ..task_adapters.public_workbook_scope import CLAUSES,checked_bytes,read,reference,require
from ..task_adapters.lease_family import NS,_paths
from ..workbook.capital_allocation_scaled.catalog import public_contract,contract_markdown
from ..workbook.capital_allocation_scaled.spec import project_ids
from ..workbook.resource_engine import load_runtime_profile

ROOT=Path(__file__).resolve().parents[3]
PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
SETTING='scaled_capital_allocation_task'
ADAPTER_ID='scaled_capital_common_plan_FM_v1'
BACKEND='scaled_capital_public_A_integer_search_decimal_forward'
construction_contract=normal.construction_contract
validate_plan=normal.validate_plan
validate_shadow_root_certificate=normal.validate_shadow_root_certificate
digest=normal.digest
prompt=normal.prompt
compact_profile=normal.compact_profile
authoring_source_context=normal.authoring_source_context


def source_admission():
    return importlib.import_module('sheets_factory.pipelines.scaled_capital_admission')


def public_recovery():
    return importlib.import_module('sheets_factory.workbook.capital_allocation_scaled.public_recovery')


def setting(runtime_profile=PROFILE):
    admission=source_admission()
    return {'enabled':True,'version':1,'adapter':ADAPTER_ID,
        'implementation':reference(__file__),'ordinary_construction':reference(normal.__file__),
        'ordinary_quality':reference(quality.__file__),'source_admission':reference(admission.__file__),
        'scaled_emitter':reference(ROOT/'src/sheets_factory/workbook/capital_allocation_scaled/excel.py'),
        'public_catalog':reference(ROOT/'src/sheets_factory/workbook/capital_allocation_scaled/catalog.py'),
        'public_recovery':reference(public_recovery().__file__),
        'resource_exporter':reference(ROOT/'src/sheets_factory/evaluation/resource_harbor.py'),
        'resource_verifier':reference(ROOT/'src/sheets_factory/evaluation/resource_streaming_verifier.py'),
        'indexed_profile':reference(ROOT/'src/sheets_factory/workbook/profile_indexed.py'),
        'streaming_delta':reference(ROOT/'src/sheets_factory/evaluation/streaming_delta.py'),
        'runtime_profile':reference(runtime_profile),'profile_id':'30-D01','project_count':30,
        'financial_target_count':25511,'decision_target_count':30,'physical_target_count':25541,
        'provided_arithmetic_count':51972,'mask_scope':'all_financial_bindings_and_complete_common_thirty_decisions',
        'helper_values_are_protected':False,'recovery_backend':BACKEND,'operational_replay_timeout_seconds':7200}


def validate_setting(value):
    require(isinstance(value,dict) and type(value.get('version')) is int
            and value==setting(value['runtime_profile']['path']),
            'The explicit scaled capital adapter, policy or implementation changed')
    require(load_runtime_profile(value['runtime_profile']['path'])['id']=='entity_group_large_v2',
            'The scaled first-source task requires the explicitly approved v2 resource profile')
    validate_copies()
    return value


def enabled(ctx):
    value=ctx.config.get(SETTING)
    if value is None:return False
    validate_setting(value)
    require(ctx.mode=='financial_modeling','This first scaled allocation adapter supports FM only')
    recovery=ctx.config.get('recovery',{})
    require(recovery.get('compiler_backend')==BACKEND
            and type(recovery.get('replay_timeout_seconds')) is int and recovery['replay_timeout_seconds']==7200,
            'The public-only shared-A search and Decimal replay route must be explicit')
    require(isinstance(recovery.get('public_kernel_preparation'),dict),
            'Bind the separately prepared public static kernel before any normal node runs')
    public_recovery().validate_kernel_preparation(recovery['public_kernel_preparation'])
    require(ctx.config.get('diagnosis',{}).get('reference_evidence_policy','independent_public_recovery')=='independent_public_recovery',
            'The first scaled source requires its strict actual public-recovery witness')
    return True


def context_proof(ctx):
    require(enabled(ctx),'The explicit scaled capital task route is required')
    evidence=ctx.data.get('finance_evidence',{})
    require(evidence.get('financial_seed_verified') is True and evidence.get('financial_modeling_eligible') is True,
            'A completely audited scaled financial source is required')
    proof=source_admission().verify_admitted_proof(evidence.get('audited_source_binding'),
        session=ctx.data.get('_scaled_admission_session'))
    require(proof.get('profile_id')=='30-D01' and proof.get('project_count')==30
            and evidence.get('source_manifest')==proof['source_manifest']
            and reference(ctx.source)==proof['workbook']
            and reference(ctx.data['baseline'])['sha256']==proof['workbook']['sha256']
            and ctx.config[SETTING]['runtime_profile']==proof['runtime_profile'],
            'The complete first-source admission, exact baseline or resource binding changed')
    return proof


def _targets(binding):
    financial,decisions,support=(binding.get(key) for key in ('financial_bindings','decision_bindings','arithmetic_bindings'))
    require(isinstance(financial,list) and len(financial)==25511 and isinstance(decisions,list) and len(decisions)==30
            and isinstance(support,list) and len(support)==51972 and binding.get('gold_plan_supplied') is True,
            'The complete first30 financial, decision and arithmetic inventory is required')
    require(all(item.get('target_eligible') is True for item in financial+decisions)
            and all(item.get('target_eligible') is False and item.get('value_protected') is False for item in support),
            'Supplied arithmetic formulas cannot become masked or value-protected')
    require([item.get('project_id') for item in decisions]==list(project_ids(30)),
            'All thirty ordered common decisions are required; no eighteen-project fallback')
    selected=[(item['sheet'],item['cell']) for item in financial+decisions]
    helpers={(item['sheet'],item['cell']) for item in support}
    require(len(set(selected))==len(selected) and len(helpers)==len(support) and not set(selected)&helpers,
            'The complete financial targets and arithmetic support overlap or repeat')
    return financial+decisions,support


def _physical(edits):
    return [{key:item[key] for key in ('sheet','cell','before','after')} for item in edits]


def _propose_from_checked_proof(baseline,proof):
    require(reference(baseline)['sha256']==proof['workbook']['sha256'],'The exact admitted baseline changed')
    binding=read(proof['bindings']);targets,support=_targets(binding)
    contract=read(proof['public_candidate_contract'])
    require(contract==public_contract('30-D01'),'The complete public candidate and field contract changed')
    markdown=checked_bytes(proof['public_contract_artifacts']['candidate_contract_markdown']).decode('utf-8')
    require(markdown==contract_markdown(public_contract('30-D01')),
            'The original complete public Markdown field dictionary changed')
    book=openpyxl.load_workbook(baseline,keep_links=False);edits=[]
    try:
        for item in targets:
            cell=book[item['sheet']][item['cell']]
            require(cell.data_type=='f' and isinstance(cell.value,str),'A complete financial target is absent')
            edits.append({'sheet':item['sheet'],'cell':item['cell'],'before':cell.value,'after':None,
                'reason':'Complete the common investment plan and connected financial forecast.',
                'business_rule':'Apply the full public candidate and accounting contract.'})
        for item in support:
            require(book[item['sheet']][item['cell']].data_type=='f','A provided arithmetic support formula is absent')
    finally:book.close()
    brief=('Select one common binary investment plan for all three scenarios that maximises the worst '
        'scenario LP net present value, and complete the financial model. Use Capital Rules, Capital '
        'Contract and Capital Inputs. Enter every shared project choice as 0 or 1. Preserve inputs and '
        'supplied arithmetic formulas while allowing their results to recalculate. '+CLAUSES['financial_modeling'])
    return {'title':'Complete the thirty-project common investment plan and financial model','mode':'financial_modeling',
        'public_instruction':brief+'\n\n'+markdown,
        'public_rules':['One common set of thirty choices applies to every scenario.',
            'Complete every standalone candidate schedule, including unselected candidates; Annual applies choices.',
            'All financial, tax-vintage and Summary fields follow the complete public contract in this instruction.'],
        'reference_evidence':[{'kind':'complete_independent_scaled_capital_source_admission','audited_source_binding':proof}],
        'scenario_inputs':[],'edits':edits,'family_adapter':{'id':ADAPTER_ID,'source_manifest':proof['source_manifest'],
            'source_sha256':proof['workbook']['sha256'],'bindings':proof['bindings'],
            'public_candidate_contract':proof['public_candidate_contract'],'public_contract_markdown_sha256':hashlib.sha256(markdown.encode()).hexdigest(),
            'financial_target_count':25511,'decision_target_count':30,'physical_target_count':25541,
            'provided_arithmetic_count':51972,'plan_dependent_support_count':sum(item.get('plan_dependent') is True for item in support),
            'helper_values_are_protected':False,'full_workbook_D_required':True}}


def audit_input_helper_caches(goal, draft, bindings):
    """Check the actual normal draft, rather than trusting an eligibility flag."""
    targets, support = _targets(bindings)
    selected = {(item['sheet'], item['cell']) for item in targets}
    originals = openpyxl.load_workbook(goal, keep_links=False)
    raw = openpyxl.load_workbook(draft, keep_links=False)
    try:
        require(originals.sheetnames == raw.sheetnames, 'Task construction changed source structure')
        for sheet in originals:
            other = raw[sheet.title]
            coordinates = set(sheet._cells) | set(other._cells)
            for row, column in coordinates:
                before, after = sheet.cell(row, column), other.cell(row, column)
                if (sheet.title, before.coordinate) in selected:
                    require(after.value is None, 'A declared financial or decision target was not physically masked')
                else:
                    require(before.data_type == after.data_type and before.value == after.value,
                            'An unselected definition or public primitive was changed')
        with ZipFile(draft) as archive:
            paths = _paths(archive)
            documents = {}
            cleared = []
            for item in support:
                if item.get('plan_dependent') is not True:
                    continue
                sheet = item['sheet']
                if sheet not in documents:
                    documents[sheet] = {cell.get('r'): cell for cell in
                        ET.fromstring(archive.read(paths[sheet])).findall('.//m:sheetData/m:row/m:c', NS)}
                cell = documents[sheet].get(item['cell'])
                require(cell is not None and cell.find('m:f', NS) is not None,
                        'Plan-dependent arithmetic must retain its supplied formula')
                cached = cell.find('m:v', NS)
                require((cached is None or not (cached.text or '').strip()) and cell.find('m:is', NS) is None,
                        'A plan-dependent arithmetic cell retained a gold cached value')
                cleared.append(sheet + '!' + item['cell'])
    finally:
        originals.close(); raw.close()
    return {'passed': True, 'goal': reference(goal), 'actual_normal_draft': reference(draft),
        'masked_financial_and_decision_count': len(targets),
        'provided_helper_formula_count': len(support), 'plan_dependent_caches_cleared_count': len(cleared),
        'cleared_support_coordinates_sha256': canonical(cleared),
        'unselected_definitions_and_public_primitives_unchanged': True,
        'helpers_physically_masked': False, 'helper_values_protected': False,
        'actual_input_recalculation_and_complete_D_still_required': True}


class ScaledCapitalAllocationPlanNode(BaseNode):
    node_id='plan'
    def execute(self,ctx):
        if not enabled(ctx):return normal.PlanNode().execute(ctx)
        proof=context_proof(ctx)
        plan=_propose_from_checked_proof(ctx.data['baseline'],proof)
        ctx.save('scaled_capital_plan_binding.json',plan['family_adapter'])
        return {'plan':plan,'source_assessment':{'financial_evidence':deepcopy(ctx.data['finance_evidence']),
            'authoring_backend':ADAPTER_ID,'full_quality_and_difficulty_pending':True}}


class ScaledCapitalAllocationProfileNode(normal.ProfileNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
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


class ScaledCapitalAllocationConstructNode(normal.ConstructNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        proof=context_proof(ctx)
        expected=_propose_from_checked_proof(ctx.data['baseline'],proof)
        plan=ctx.data['plan']
        require(plan.get('family_adapter')==expected['family_adapter'] and not plan.get('scenario_inputs')
                and 'mask_ranges' not in plan and _physical(plan.get('edits',[]))==_physical(expected['edits']),
                'The complete first30 physical target scope changed')
        require(checked_bytes(proof['public_contract_artifacts']['candidate_contract_markdown']).decode('utf-8') in plan.get('public_instruction',''),
                'The complete public field and candidate contract must remain in the actual instruction')
        result=self._execute_normal(ctx)
        binding=read(proof['bindings'])
        receipt=audit_input_helper_caches(result['goal'],ctx.revision_dir/'private/mutated_unrecalculated.xlsx',binding)
        complete=compare_workbooks(result['input'],result['goal'],result['goal'])
        require(complete==result['delta'],'The complete changed-value set was reduced')
        helpers={item['sheet']+'!'+item['cell'] for item in binding['arithmetic_bindings']}
        receipt.update(input=reference(result['input']),goal=reference(result['goal']),
            complete_required_D_count=complete['expected_change_count'],
            changed_helper_count=len(helpers&set(complete['expected_changes'])),
            no_helper_values_excluded_from_required_D=True,
            five_controls_recovery_12QA_Harbor_and_difficulty_pending=True)
        ctx.save('scaled_capital_actual_input_scope.json',receipt)
        return {**result,'scaled_capital_input_scope':receipt}
    def _execute_normal(self, ctx):
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
        # Every root must have an effect by itself, not merely a syntactic edit.
        root_impacts = []
        root_method = construction_contract(ctx.mode, ctx.config)['root_impact_validation']
        if ctx.mode == 'debugging' and root_method == 'separated_roots':
            from ..checkers.separated_roots import certify_separated_roots
            limits = construction_contract(ctx.mode, ctx.config)['dependency_requirements']
            certificate = certify_separated_roots(goal=goal, combined_input=input_file, edits=edits,
                max_dependency_cells=limits['max_dependency_closure_cells'],
                per_formula_reference_cells=limits['per_formula_reference_cells'])
            ctx.save('separated_roots_certificate.json', certificate)
            ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
                method=root_method, state=certificate.get('state'), passed=certificate.get('passed'),
                root_count=len(edits))
            if certificate.get('passed') is not True or certificate.get('blocking') is not False:
                raise TaskRejected('Q06: separated-root proof rejected: ' + str(certificate.get('reason', 'incomplete proof')))
            root_impacts = certificate.get('root_impacts', [])
            expected_roots = {edit['sheet'] + '!' + edit['cell'] for edit in edits}
            proven_roots = {next(iter(impact.get('expected_changes', [])), None) for impact in root_impacts
                            if impact.get('proof_method') == 'separated_dependency_graph_and_actual_combined_value_change'
                            and impact.get('expected_change_count', 0) >= 1
                            and impact.get('combined_marginal', {}).get('expected_change_count', 0) >= 1}
            if len(root_impacts) != len(edits) or proven_roots != expected_roots:
                raise TaskRejected('Q06: separated-root certificate does not prove every declared root')
            validation['root_impact_validation'] = {'method': root_method,
                'proof_method': certificate.get('proof_method'), 'root_count': len(root_impacts),
                'individual_LO_executions': False, 'marginal_LO_executions': False}
        elif ctx.mode == 'debugging' and root_method == 'batched_separated_roots':
            from ..checkers.batched_roots import prove_batched_root_impacts
            from uuid import uuid4
            limits = construction_contract(ctx.mode, ctx.config)
            batch_options = {}
            if limits['root_impact_concurrency'] > 1:
                from ..checkers.parallel_batched_roots import prove_parallel_batched_root_impacts
                prove_batched_root_impacts = prove_parallel_batched_root_impacts
                batch_options['concurrency'] = limits['root_impact_concurrency']
            certificate = prove_batched_root_impacts(goal=goal, combined_input=input_file,
                edits=edits, batches=ctx.data['plan'].get('root_impact_batches'), engine=ctx.engine,
                directory=private / 'batched_root_impact_probes' / uuid4().hex,
                max_batches=limits['max_root_impact_batches'],
                max_dependency_cells=limits['dependency_requirements']['max_dependency_closure_cells'],
                per_formula_reference_cells=limits['dependency_requirements']['per_formula_reference_cells'],
                **batch_options)
            ctx.save('batched_roots_certificate.json', certificate)
            ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
                method=root_method, state=certificate.get('state'), passed=certificate.get('passed'),
                root_count=len(edits), batch_count=certificate.get('batch_count'),
                actual_batch_LO_executions=certificate.get('actual_batch_LO_execution_count'),
                duration_ms=certificate.get('duration_ms'))
            if certificate.get('state') == 'execution_error':
                raise RuntimeError('Batch root-impact recalculation failed: ' + str(certificate.get('reason')))
            if certificate.get('passed') is not True or certificate.get('blocking') is not False:
                raise TaskRejected('Q06: batched root-impact proof rejected: ' + str(certificate.get('reason', 'incomplete proof')))
            root_impacts = certificate.get('root_impacts', [])
            expected_roots = {edit['sheet'] + '!' + edit['cell'] for edit in edits}
            proven_roots = {next(iter(impact.get('expected_changes', [])), None) for impact in root_impacts
                if impact.get('proof_method') == 'batched_separation_and_actual_LO_values'
                and impact.get('expected_change_count', 0) >= 1
                and impact.get('combined_marginal', {}).get('expected_change_count', 0) >= 1
                and impact.get('combined_marginal', {}).get('edits_reversed') is True
                and impact.get('combined_marginal', {}).get('base') == 'full_combined_mutation'}
            if len(root_impacts) != len(edits) or proven_roots != expected_roots:
                raise TaskRejected('Q06: batch certificate does not prove every declared root')
            validation['root_impact_validation'] = {'method': root_method,
                'proof_method': certificate['proof_method'], 'root_count': len(root_impacts),
                'batch_count': certificate['batch_count'],
                'actual_batch_LO_execution_count': certificate['actual_batch_LO_execution_count'],
                'individual_LO_executions': False, 'marginal_LO_executions': False,
                'counts_are_lower_bounds': True}
        elif ctx.mode == 'debugging' and root_method == 'shadow_roots':
            from ..checkers.shadow_roots import prove_shadow_root_impacts
            from uuid import uuid4
            limits = construction_contract(ctx.mode, ctx.config)['dependency_requirements']
            certificate = prove_shadow_root_impacts(goal=goal, combined_input=input_file,
                edits=edits, engine=ctx.engine,
                directory=private / 'shadow_root_impact_probes' / uuid4().hex,
                max_dependency_cells=limits['max_dependency_closure_cells'],
                per_formula_reference_cells=limits['per_formula_reference_cells'])
            ctx.save('shadow_roots_certificate.json', certificate)
            ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
                method=root_method, state=certificate.get('state'), passed=certificate.get('passed'),
                root_count=len(edits), actual_shadow_LO_executions=certificate.get('actual_LO_execution_count'),
                duration_ms=certificate.get('duration_ms'))
            if certificate.get('state') == 'execution_error':
                raise RuntimeError('Shadow root-impact recalculation failed: ' + str(certificate.get('reason')))
            root_impacts = validate_shadow_root_certificate(certificate, goal, input_file, edits)
            validation['root_impact_validation'] = {'method': root_method,
                'proof_method': certificate['proof_method'], 'root_count': len(root_impacts),
                'actual_shadow_LO_execution_count': certificate['actual_LO_execution_count'],
                'individual_LO_executions': False, 'marginal_LO_executions': False,
                'counts_are_lower_bounds': True, 'complete_per_root_changed_sets_claimed': False}
        elif ctx.mode == 'debugging':
            for index, edit in enumerate(edits):
                one = openpyxl.load_workbook(goal, keep_links=False)
                one[edit['sheet']][edit['cell']] = edit['after']
                raw = private / f'root_{index}_raw.xlsx'; one.save(raw); one.close()
                calc = ctx.engine.recalculate(raw, private / f'root_{index}.xlsx')
                impact = compare_workbooks(calc, goal, goal)
                root_impacts.append(impact)
                if not impact.get('expected_change_count'):
                    raise TaskRejected('Q06: an injected root is inactive or erased by rounding')
                combined = openpyxl.load_workbook(input_file, keep_links=False)
                combined[edit['sheet']][edit['cell']] = edit['before']
                partial_raw = private / f'marginal_{index}_raw.xlsx'; combined.save(partial_raw); combined.close()
                partial = ctx.engine.recalculate(partial_raw, private / f'marginal_{index}.xlsx')
                marginal = compare_workbooks(input_file, partial, partial)
                root_impacts[-1]['combined_marginal'] = marginal
                if not marginal.get('expected_change_count'):
                    raise TaskRejected('Q06: a root is inactive in the combined mutation')
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


class ScaledCapitalAllocationDiagnoseNode(quality.DiagnoseNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
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
        elif not valid_scaled_capital_recovery_witness(ctx,ctx.data['recovery']):
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


class ScaledCapitalAllocationExportNode(quality.ExportNode):
    node_id = 'export'

    def execute(self, ctx):
        if not enabled(ctx):
            return super().execute(ctx)
        context_proof(ctx)
        require(valid_scaled_capital_recovery_witness(ctx, ctx.data.get('recovery', {})),
                'A current, strictly bound public-only recovery witness is required before export')
        actual_base = verify_local_base_image(ctx.config[SETTING]['runtime_profile']['path'])
        ctx.save('scaled_capital_actual_local_base_image.json', actual_base)
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


def valid_scaled_capital_recovery_witness(ctx,candidate):
    from ..workbook.capital_allocation_scaled.public_recovery import valid_scaled_capital_recovery_witness as validate
    return validate(ctx,candidate)


def validate_copies():
    for before,after in ((normal.ProfileNode.execute,ScaledCapitalAllocationProfileNode._execute_profile),
                         (normal.ConstructNode.execute,ScaledCapitalAllocationConstructNode._execute_normal)):
        a=ast.parse(textwrap.dedent(inspect.getsource(before)));b=ast.parse(textwrap.dedent(inspect.getsource(after)))
        b.body[0].name=a.body[0].name
        require(ast.dump(a)==ast.dump(b),'An unapproved normal construction/profile gate changed')
    a=ast.parse(textwrap.dedent(inspect.getsource(quality.DiagnoseNode.execute)))
    b=ast.parse(textwrap.dedent(inspect.getsource(ScaledCapitalAllocationDiagnoseNode._execute_diagnose)))
    b.body[0].name=a.body[0].name
    needle=ast.dump(ast.parse("not ctx.data['recovery']['verified']",mode='eval').body)
    replacement=ast.parse("not valid_scaled_capital_recovery_witness(ctx,ctx.data['recovery'])",mode='eval').body
    class Guard(ast.NodeTransformer):
        count=0
        def visit_UnaryOp(self,node):
            if ast.dump(node)==needle:
                self.count+=1;return deepcopy(replacement)
            return self.generic_visit(node)
    guard=Guard();a=guard.visit(a)
    require(guard.count==1 and ast.dump(a)==ast.dump(b),'Only the strict family recovery witness lookup may differ')
