"""Normal nodes for explicitly admitted native linear-capital task views.

Full physical/value evidence stays in private files. Public reviewers receive
business rules and bounded examples, with the actual workbook available; private
reviewers receive the ordinary immutable audited-summary evidence transport.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
import json
import math
from pathlib import Path
import shutil
import textwrap
import time
import uuid

import openpyxl
from openpyxl.utils import get_column_letter

from ..core.node import TaskRejected
from ..nodes import construction as normal, quality
from ..nodes.quality import (validate_reference_policy_selection, reference_revision_binding,
    _reference_review_context, prompt, candidate_difficulty_context,
    PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS, REFERENCE_REVIEW_PREFIX, REFERENCE_REVIEW_CHECKS,
    prepare_workspace, reference_review_assessments)
from ..checkers import DiagnosisRunner
from ..checkers.router import route_issues
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..evaluation.streaming_delta import compare_workbooks
from ..evaluation.streaming_verifier import compare_files, _sparse_cells
from ..evaluation.thread_capped_harbor_export import export_resource_harbor, inspect_resource_export, verify_local_base_image
from ..pipelines.linear_capital_quality import (ROOT, References, reference, require, require_view_admission,
    LinearViewAdmission, DEFAULT_PROVIDERS, REWARDS)
from ..pipelines.entity_group_contract import probe_native_errors, validate_upstream_validator
from ..workbook.profile_indexed import profile_workbook
from ..workbook.resource_engine import load_runtime_profile
from ..workbook import linear_capital_public_recovery as recovery
from ..workbook.linear_capital_portfolio import excel

SETTING = recovery.SETTING
ADAPTER_ID = 'complete_native_linear_capital_normal_quality_v1'
REGISTRY = ROOT/'config/task_adapters/linear_capital_portfolio_nodes.yaml'
PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'


def setting(runtime_profile=PROFILE, provider_registry=DEFAULT_PROVIDERS):
    from ..pipelines import entity_group_contract
    return {'version':1, 'enabled':True, 'adapter':ADAPTER_ID, 'implementation':reference(__file__),
        'node_registry':reference(REGISTRY), 'runtime_profile':reference(runtime_profile),
        'provider_registry':reference(provider_registry), 'recovery':reference(recovery.__file__),
        'large_native_probe':reference(entity_group_contract.__file__)}


def validate_setting(value):
    require(type(value) is dict and type(value.get('version')) is int and value['version']==1
        and value.get('enabled') is True
        and value==setting(value['runtime_profile']['path'],value['provider_registry']['path']),
        'The complete explicit current native-linear family route must be frozen')
    profile=load_runtime_profile(value['runtime_profile']['path'])
    require(profile['id']=='entity_group_large_v2' and profile['limits']['max_profile_cells']==3_000_000
        and profile['limits']['max_dependency_closure_cells']==3_000_000,
        'The family requires its complete untruncated native analysis capacity')
    validate_upstream_validator();validate_diagnose_copy()
    return value


def enabled(ctx):
    if ctx.config.get(SETTING) is None:return False
    validate_setting(ctx.config[SETTING])
    require(ctx.mode in ('financial_modeling','debugging'), 'Unknown linear financial task mode')
    return True


def context_proof(ctx):
    require(enabled(ctx), 'The explicit family route is required')
    session=ctx.data.get('_linear_admission');proof=require_view_admission(session)
    require(proof['mode']==ctx.mode and proof['runtime_profile']==ctx.config[SETTING]['runtime_profile']
        and proof['provider_registry']==ctx.config[SETTING]['provider_registry']
        and reference(ctx.source)==proof['workbook'], 'The actual mode, source or profile differs from admission')
    for key in ('baseline','input','goal'):
        if ctx.data.get(key):
            actual=reference(ctx.data[key]);expected=proof['input' if key=='input' else 'goal']
            require((actual['sha256'],actual['bytes'])==(expected['sha256'],expected['bytes']),
                'A copied admitted task workbook changed: '+key)
    return proof


def compact_profile(profile):
    """Prompt examples only; complete programmatic profile remains unchanged."""
    result=normal.compact_profile(profile,formula_limit=1,literal_limit=4)
    result['examples_are_not_complete_target_or_audit_coverage']=True
    result['complete_public_workbook_available_for_inspection']=True
    return result


def canonical_plan(session):
    proof=require_view_admission(session);view=session.plan
    if proof['mode']=='financial_modeling':
        edits=[{'sheet':r['sheet'],'cell':r['cell'],'before':r['before'],'after':None,
            'reason':'Complete the financial model and common investment choices.'} for r in view['masked_targets']]
    else:
        edits=[dict(r) for r in view['formula_edits']]+[dict(r) for r in view['choice_edits']]
    return {'title':'Complete the native portfolio model' if proof['mode']=='financial_modeling' else 'Repair the native portfolio model',
        'mode':proof['mode'],'public_instruction':view['instruction'],'public_rules':list(excel.PUBLIC_RULES),
        'reference_evidence':[{'kind':'independently_admitted_native_financial_source',
            'source_manifest':proof['source_manifest'],'actual_task_validation':proof['actual_validation_terminal'],
            'complete_financial_bindings':proof['bindings']}],
        'scenario_inputs':[],'edits':edits,
        'family_adapter':{'id':ADAPTER_ID,'view_plan':proof['view_plan'],
            'view_plan_sha256':proof['view_plan_sha256'],'actual_complete_D':proof['full_D'],
            'physical_edit_count':len(edits),'complete_D_count':proof['full_D_count'],
            'actual_family_effects':proof['actual_prequality_family_effects'],
            'activity_contract':'full_workbook_joint_repair' if proof['mode']=='debugging' else 'complete_financial_model',
            'individual_or_marginal_root_activity_claimed':False}}


class LinearNormalizeNode(normal.NormalizeNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        proof=context_proof(ctx)
        cache=Path(ctx.config['run_dir'])/'sources'/proof['workbook']['sha256'][:12]/proof['view_plan_sha256'][:12]
        cache.mkdir(parents=True,exist_ok=True);baseline=cache/'baseline.xlsx'
        if not baseline.exists():shutil.copyfile(proof['goal']['path'],baseline)
        require(reference(baseline)['sha256']==proof['goal']['sha256'],'The current audited baseline changed')
        evidence={'method':'byte_identical_copy_of_independently_audited_native_goal','baseline':reference(baseline),
            'source':proof['workbook'],'source_manifest':proof['source_manifest'],
            'actual_source_calls':proof['source_financial_evidence']['actual_engine_calls'],
            'actual_new_LO_calls_by_this_node':0,'prequality_evidence_is_not_normal_quality':True}
        ctx.save('linear_normalization.json',evidence)
        return {'source_id':proof['workbook']['sha256'],'baseline':baseline,'source_cache':cache,
            'engine_report':{'normalization_ok':True,'recalculation_ok':True,'stable':True,
                'normalization_artifact':str(baseline),'normalization_evidence':evidence,'engine':ctx.engine.metadata()}}


class LinearProfileNode(normal.ProfileNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        context_proof(ctx)
        profile=profile_workbook(ctx.data['baseline'],max_cells=3_000_000,per_formula_reference_cells=5000)
        require(not profile['truncated'] and not profile['errors'] and not profile['external_references']
            and profile['formula_count']>0 and profile['nonempty_sheet_count']>3,
            'The complete native financial profile must be internally supported and error-free')
        ctx.save('linear_native_profile.json',profile)
        return {'profile':profile}


class LinearPlanNode(normal.PlanNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        proof=context_proof(ctx)
        return {'plan':canonical_plan(ctx.data['_linear_admission']),
            'source_assessment':{'financial_evidence':deepcopy(ctx.data.get('finance_evidence',{})),
                'source_admission':proof['source_financial_evidence'],
                'actual_view_validation':proof['actual_validation_terminal'],
                'complete_financial_bindings':proof['bindings'],
                'formula_existence_is_not_financial_correctness':True}}


class LinearConstructNode(normal.ConstructNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        proof=context_proof(ctx);session=ctx.data['_linear_admission'];expected=canonical_plan(session)
        require({k:v for k,v in ctx.data['plan'].items() if k!='public_instruction'}==
            {k:v for k,v in expected.items() if k!='public_instruction'}
            and type(ctx.data['plan'].get('public_instruction')) is str and ctx.data['plan']['public_instruction'].strip(),
            'A repair changed financial scope, assumptions or admitted physical mutations; a new actual view is required')
        public,private=ctx.revision_dir/'public',ctx.revision_dir/'private'
        public.mkdir(parents=True,exist_ok=True);private.mkdir(parents=True,exist_ok=True)
        source,goal=public/'input.xlsx',private/'goal.xlsx'
        shutil.copyfile(proof['input']['path'],source);shutil.copyfile(proof['goal']['path'],goal)
        delta=compare_workbooks(source,goal,goal)
        original={k:v for k,v in session.delta.items() if k!='workbook_binding'}
        require(delta==original and delta['reward']==1 and delta['expected_change_count']>0,
            'The complete current input/goal difference changed')
        labels=delta['expected_changes']
        guard=evaluate_native_risk_guard(labels,proof['workbook']['sha256'],project_root=ctx.config['project_root'],
            sheet_names=session.plan['sheetnames'],registry_path=ctx.config.get('native_risks',{}).get('registry_path'),
            legacy_risks=ctx.data.get('source_business_issues',[]))
        require(not guard['blocking'],'Q09: an unresolved native source risk intersects the complete task')
        probe=probe_native_errors(goal=goal,required_delta=labels,candidates=[],engine=ctx.engine,
            directory=private/'native_error_probes',source_sha256=proof['workbook']['sha256'],
            plan=ctx.data['plan'],revision=ctx.revision,immutable_files={'source':ctx.source,'baseline':ctx.data['baseline']},
            engine_metadata=ctx.data['engine_report']['engine'],max_dependency_cells=3_000_000,per_formula_reference_cells=5000)
        require(not probe['blocking'],'Q09/Q10: unresolved native error reaches the complete task value set')
        validation={'edit_count':len(expected['edits']),'before_assertions_passed':True,
            'physical_edits_checked_by_actual_view_validation':proof['actual_validation_terminal'],
            'source_financial_admission':proof['source_manifest'],'actual_family_effects':proof['actual_prequality_family_effects'],
            'full_D_count':len(labels),'unchanged_outside_approved_edits_and_declared_choices':True,
            'reference_values_not_modified':True,'native_error_candidates':[],'native_error_probe':probe,
            'activity_contract':expected['family_adapter']['activity_contract'],
            'individual_or_marginal_root_activity_claimed':False,'actual_new_LO_calls_by_construct':0}
        for name,value in [('plan.json',ctx.data['plan']),('edit_validation.json',validation),('expected_delta.json',delta),
            ('root_impacts.json',[]),('native_risk_guard.json',guard),('native_error_probe.json',probe)]:ctx.save(name,value)
        profile=profile_workbook(source,max_cells=3_000_000,per_formula_reference_cells=5000)
        require(not profile['truncated'],'The complete actual public profile exceeds the explicit family capacity')
        return {'input':source,'goal':goal,'delta':delta,'construction_validation':validation,
            'root_impacts':[],'native_risk_guard':guard,'public_profile':profile}


class LinearInstructionNode(normal.InstructionNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        context_proof(ctx);text=ctx.data['plan']['public_instruction']
        path=ctx.revision_dir/'public/instruction.md';path.write_text(text)
        return {'instruction':text,'instruction_path':path,
            'revision_hash':hashlib.sha256(Path(ctx.data['input']).read_bytes()+text.encode()).hexdigest()}


class LinearControlsNode(normal.ControlsNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        proof=context_proof(ctx);session=ctx.data['_linear_admission']
        source,goal=Path(ctx.data['input']),Path(ctx.data['goal'])
        folder=ctx.revision_dir/'private/controls'/('attempt_'+uuid.uuid4().hex);folder.mkdir(parents=True)
        reports={};calls=[];completed=False
        try:
            # Select a value actually in D, not a syntactic edit assumed to have
            # an individual marginal effect. The omission is graded in reality.
            required=set(ctx.data['delta']['expected_changes']);first=None
            book=openpyxl.load_workbook(goal,read_only=True,data_only=True)
            try:
                for sheet in book:
                    for (row,col),cell in _sparse_cells(sheet):
                        address=get_column_letter(col)+str(row)
                        if sheet.title+'!'+address in required and type(cell['value']) in (int,float) and math.isfinite(cell['value']):
                            first=(sheet.title,address,cell['value']);break
                    if first:break
            finally:book.close()
            require(first is not None,'The complete D lacks an observable numeric local-control candidate')
            for name,output in [('oracle',goal),('nop',source)]:reports[name]=compare_files(source,goal,output)
            for index,name in enumerate(('equivalent','missed_root','extra_change'),1):
                book=openpyxl.load_workbook(goal,keep_links=False)
                try:
                    if name=='equivalent':book[first[0]][first[1]]='='+str(first[2])+'+0'
                    elif name=='missed_root':book[first[0]][first[1]]=None
                    else:
                        cell=book.worksheets[0]['A1'];require(type(cell.value) is str,'A protected native title is required')
                        cell.value+=' changed'
                    raw=folder/(name+'.raw.xlsx');book.save(raw)
                finally:book.close()
                from ..core.audit import utcnow
                call={'index':index,'role':'normal_control_'+name,'input':reference(raw),'started_at':utcnow(),'completed':False}
                before=len(ctx.engine.metadata().get('actual_resource_receipts',[]));clock=time.monotonic()
                try:
                    output=Path(ctx.engine.recalculate(raw,folder/(name+'.xlsx')))
                    require(output.resolve()==(folder/(name+'.xlsx')).resolve(),'The engine returned another control artifact')
                    call.update(output=reference(output),completed=True,elapsed_seconds=time.monotonic()-clock)
                    receipts=ctx.engine.metadata()['actual_resource_receipts']
                    require(len(receipts)==before+1,'A normal control has an unrecorded actual calculation')
                    profile=load_runtime_profile(proof['runtime_profile']['path'])
                    call['actual_resource_evidence']=session.source.helper.validate_actual_call(call,receipts[-1],
                        {'runtime_profile':proof['runtime_profile'],'runtime_profile_value':profile})
                finally:
                    call['finished_at']=utcnow();calls.append(call)
                    (folder/(name+'.terminal.json')).write_text(json.dumps(call,indent=2)+'\n')
                reports[name]=compare_files(source,goal,output)
            require(all(type(reports[n].get('reward')) is int and reports[n]['reward']==v for n,v in REWARDS.items()),
                'Q05/Q06: an actual normal positive or negative control failed')
            completed=True;ctx.save('local_controls.json',reports)
            return {'controls':reports}
        finally:
            (folder/'attempt.json').write_text(json.dumps({'completed':completed,'reports':reports,'actual_LO_calls':calls,
                'source':reference(source),'goal':reference(goal),'revision_hash':ctx.data['revision_hash']},indent=2)+'\n')


def valid_linear_capital_recovery_witness(ctx,candidate):
    return recovery.valid_linear_capital_recovery_witness(ctx,candidate)


class LinearDiagnoseNode(quality.DiagnoseNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        context_proof(ctx)
        require(ctx.config['diagnosis'].get('execution',{}).get('reference_evidence_transport')=='audited_summary',
            'The complete private artifacts must use audited-summary transport, never a million-cell inline prompt')
        return self._execute_diagnose(ctx)

    def _execute_diagnose(self, ctx):
        from ..llm.schemas import diagnosis_output_schema
        policy = validate_reference_policy_selection(ctx.config)
        binding, review_context, review_artifacts = (None, None, None)
        if policy == 'reference_review':
            binding = reference_revision_binding(ctx)
            review_context, review_artifacts = _reference_review_context(ctx, binding)
        diagnosis_prompt = prompt(ctx, 'diagnosis.md')
        public = {'instruction': ctx.data['instruction'], 'profile': compact_profile(ctx.data['public_profile']), 'rules': ctx.data['plan']['public_rules'], 'task_mode': ctx.mode, 'difficulty_review_context': candidate_difficulty_context(ctx.config), 'input_sha256': hashlib.sha256(Path(ctx.data['input']).read_bytes()).hexdigest()}
        private = {'plan': ctx.data['plan'], 'construction': ctx.data['construction_validation'], 'expected_delta': ctx.data['delta'], 'root_impacts': ctx.data['root_impacts'], 'independent_recovery': ctx.data['recovery'], 'source_assessment': ctx.data.get('source_assessment', {}), 'native_risk_guard': ctx.data.get('native_risk_guard', {}), 'source_business_issues': ctx.data.get('source_business_issues', []), 'goal_sha256': hashlib.sha256(Path(ctx.data['goal']).read_bytes()).hexdigest(), 'native_errors': ctx.data['profile']['errors']}
        if policy == 'reference_review':
            public['reference_evidence_policy'] = policy
            private['reference_review_context'] = review_context
            private['reference_review_requirements'] = {'policy': policy, 'binding': binding, 'goal_artifact': 'reference.xlsx', 'instructions': 'Q04 must inspect the actual reference.xlsx, source business evidence, complete expected delta, financial identities and independent calculations. Existing formula existence alone is not truth. No exact public solver is required or claimed. Q01/Q02/Q03 must independently establish public sufficiency and scope.', 'required_Q04_evidence_string': REFERENCE_REVIEW_PREFIX + json.dumps({'binding': binding, 'business_evidence': ['Concrete source business policy and inspected public evidence'], 'financial_validation_checks': [{'check': 'Concrete financial identity or independent recalculation', 'method': 'Describe the independent calculation actually performed', 'passed': True, 'evidence': ['Actual inspected cells, calculation and observed result']}]})}
        health = {'healthy': all((not t.get('infrastructure_error') for t in ctx.data['traces'])), 'checks': [{'probe': 'codex_native_cli', 'model': ctx.llm.model}, {'probe': 'libreoffice_full_recalculation', 'engine': ctx.data['engine_report']}]}
        bundle = {'task_id': ctx.task_id, 'revision_hash': ctx.data['revision_hash'], 'revision': ctx.revision, 'public': public, 'private': private, 'engine_report': ctx.data['engine_report'], 'infrastructure_health_report': health}
        bundle['reviewer_context_hash'] = hashlib.sha256(json.dumps({'prompt': diagnosis_prompt, 'agents': ctx.config['agents'], 'private_evidence_transport': PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS, 'schema_contract': diagnosis_output_schema(['Q01'])}, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

        def review(payload):
            is_public = payload['visibility'] == 'public_only'
            work = prepare_workspace(ctx, 'diagnostic_public' if is_public else 'diagnostic_private')
            evidence = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
            (work / 'evidence.json').write_bytes(evidence)
            instruction = diagnosis_prompt + '\nRead /workspace/evidence.json for all assigned checks and evidence. Inspect input.xlsx/instruction.md as necessary. Return JSON only.'
            if not is_public:
                if policy == 'reference_review':
                    shutil.copy2(ctx.data['goal'], work / 'reference.xlsx')
                receipt = {'file': 'evidence.json', 'sha256': hashlib.sha256(evidence).hexdigest(), 'bytes': len(evidence), 'assigned_check_ids': payload['assigned_check_ids']}
                instruction = diagnosis_prompt + PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS + json.dumps(receipt)
            instruction += '\nReturn assessments as an object keyed by every assigned_check_id exactly once. Follow the supplied output schema; missing assigned checks are a backend protocol failure.'
            return ctx.llm.complete(instruction, role='public_diagnostician' if is_public else 'reference_diagnostician', task_id=ctx.task_id, stage=self.node_id, workspace=work, isolated=is_public, timeout=ctx.config['agents']['timeout_seconds'], output_schema=diagnosis_output_schema(payload['assigned_check_ids']))
        runner = DiagnosisRunner(ctx.config['project_root'])
        report = runner.diagnose(bundle, ctx.data['traces'], ctx.data['controls'], review, ctx.config, batch_cache=ctx.data.setdefault('diagnostic_batch_cache', {}))
        ctx.save('diagnostic_batch_cache.json', ctx.data['diagnostic_batch_cache'])
        if policy == 'reference_review':
            receipt = reference_review_assessments(report, binding)
            receipt['artifacts'] = review_artifacts
            receipt['diagnostic_run_id'] = report['diagnostic_run_id']
            receipt['check_plan_hash'] = report['check_plan_hash']
            ctx.save('reference_review.json', receipt)
            report.update(reference_evidence_policy=policy, reference_validation_method=policy, reference_binding=binding, reference_review=receipt, mandatory_gates={'reference_review': {'passed': receipt['passed'], 'required_check_ids': list(REFERENCE_REVIEW_CHECKS)}})
            if not receipt['passed']:
                report['issues'].append({'issue_id': ctx.task_id + '-Q12-reference-review', 'problem_id': 'Q12', 'severity': 'blocker', 'certainty': 'confirmed', 'claim': 'Reference review lacks current supported public and financial evidence', 'revision_hash': ctx.data['revision_hash'], 'depends_on_issue_ids': [], 'evidence': receipt['problems']})
            evidence_passed = receipt['passed']
        elif not valid_linear_capital_recovery_witness(ctx, ctx.data['recovery']):
            issue = {'issue_id': ctx.task_id + '-Q12-recovery', 'problem_id': 'Q12', 'severity': 'blocker', 'certainty': 'confirmed', 'claim': 'Independent public-information reconstruction has not matched reference values', 'revision_hash': ctx.data['revision_hash'], 'depends_on_issue_ids': [], 'evidence': [ctx.data['recovery'].get('comparison', ctx.data['recovery'].get('error', 'no output'))]}
            report['issues'].append(issue)
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
        report['routes'] = route_issues(report['issues'], runner.catalog, ctx.config.get('diagnosis', {}).get('difficulty_deferred', False))
        report['coverage']['blocking_issue_ids'] = [issue['issue_id'] for issue in report['issues'] if issue.get('severity', 'blocker') == 'blocker' and (not (issue['problem_id'] == 'Q08' and runner.resolve(ctx.config)['difficulty_deferred']))]
        report['releasable'] = report['releasable'] and evidence_passed and (not report['coverage']['blocking_issue_ids'])
        ctx.save('diagnosis.json', report)
        ctx.audit.task(ctx.task_id, issues=report['issues'], diagnosis_scope=report['scope'])
        for check, assessment in report['assessments'].items():
            ctx.audit.emit('checker.result', task_id=ctx.task_id, revision=ctx.revision, checker=check, state=assessment['state'], reason=assessment['reason'])
        return {'diagnosis': report}


class LinearRepairNode(quality.RepairNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        proof=context_proof(ctx)
        routes=ctx.data.get('repair_routes',[])
        issues={r['issue_id']:r for r in ctx.data.get('diagnosis',{}).get('issues',[])}
        require(routes and all(r['route_class']=='repair' and issues.get(r['issue_id'],{}).get('certainty')=='confirmed'
            for r in routes),'Only confirmed content-repair routes may request a new revision')
        if any(r.get('problem_id') not in ('Q01','Q02','Q03') for r in routes):
            raise TaskRejected('Financial, mutation or reference repairs require a newly admitted actual source/view; no frozen truth is silently changed')
        from ..llm.schemas import instruction_repair_output_schema
        requested=[r['issue_id'] for r in routes]
        payload={'task_mode':ctx.mode,'public_instruction':ctx.data['plan']['public_instruction'],
            'public_rules':ctx.data['plan']['public_rules'],'public_profile_examples':compact_profile(ctx.data['public_profile']),
            'assigned_issues':[issues[r] for r in requested],
            'complete_private_plan':proof['view_plan'],'complete_actual_D':proof['full_D'],
            'repair_contract':{'permitted_changed_plan_fields':['public_instruction'],
                'all_other_fields_preserved_programmatically':True,'new_revision_requires_all_normal_gates':True}}
        result=ctx.llm.complete(prompt(ctx,'instruction_repair.md')+'\nINPUT JSON:\n'+json.dumps(payload,ensure_ascii=False),
            role='repair_planner',task_id=ctx.task_id,stage=self.node_id,
            timeout=ctx.config['agents']['timeout_seconds'],output_schema=instruction_repair_output_schema(requested))
        ctx.save('repair_proposal.json',result)
        proposed=quality.apply_instruction_repair(ctx.data['plan'],result,requested)
        ctx.save('instruction_repair_receipt.json',{'assigned_issue_ids':requested,'changed_plan_fields':['public_instruction'],
            'requires_full_revision_gates':True,'reuse_old_harbor_controls':False})
        return {'next_plan':proposed}


class LinearExportNode(quality.ExportNode):
    def execute(self,ctx):
        if not enabled(ctx):return super().execute(ctx)
        context_proof(ctx)
        require(valid_linear_capital_recovery_witness(ctx,ctx.data.get('recovery',{})),
            'A current complete isolated public-only recovery witness is required before normal export')
        profile=ctx.config[SETTING]['runtime_profile']['path']
        ctx.save('linear_actual_local_base_image.json',verify_local_base_image(profile))
        destination=Path(ctx.config['run_dir'])/'SpreadsheetEval'/ctx.task_id
        require(not destination.exists() or not any(destination.iterdir()),'Preserve each immutable normal export')
        metadata={'task_id':ctx.task_id,'mode':ctx.mode,'source_id':ctx.data['source_id'],'source_file':ctx.source.name,
            'revision':ctx.revision,'revision_hash':ctx.data['revision_hash'],'difficulty_status':'pending',
            'base_image':ctx.config['engine']['image']}
        audit_path=ctx.revision_dir/'private/linear_harbor_worker_cap.json'
        export_resource_harbor(ctx.revision_dir,destination,metadata,ctx.config['project_root'],runtime_profile=profile,
            audit_path=audit_path)
        binding=inspect_resource_export(destination,audit_path=audit_path)
        require(binding['task_id']==ctx.task_id and binding['revision_hash']==ctx.data['revision_hash'],
            'The full seventeen-file worker-capped resource export differs from this revision')
        ctx.save('linear_resource_export_binding.json',binding)
        (ctx.directory/'lineage.json').write_text(json.dumps(metadata,indent=2)+'\n')
        return {'export_dir':destination}


def validate_diagnose_copy():
    expected=ast.parse(textwrap.dedent(inspect.getsource(quality.DiagnoseNode.execute))).body[0]
    actual=ast.parse(textwrap.dedent(inspect.getsource(LinearDiagnoseNode._execute_diagnose))).body[0]
    expected.name=actual.name
    match=ast.dump(ast.parse("ctx.data['recovery']['verified']",mode='eval').body)
    class StrictWitness(ast.NodeTransformer):
        count=0
        def visit_Subscript(self,node):
            if ast.dump(node)==match:
                self.count+=1
                return ast.parse("valid_linear_capital_recovery_witness(ctx,ctx.data['recovery'])",mode='eval').body
            return self.generic_visit(node)
    change=StrictWitness();expected=change.visit(expected)
    require(change.count==1 and ast.dump(expected,include_attributes=False)==ast.dump(actual,include_attributes=False),
        'The twelve-check diagnostic route changed beyond its explicit strict family witness condition')
