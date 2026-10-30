from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import uuid

from ..core.node import BaseNode, TaskRejected
from ..workbook import compare_workbooks
from ..checkers import DiagnosisRunner
from ..checkers.router import route_issues
from ..evaluation.harbor import export_harbor
from .construction import prompt, compact_profile, construction_contract, authoring_source_context


def prepare_workspace(ctx, name):
    workspace = ctx.revision_dir / (name + '-' + uuid.uuid4().hex[:8])
    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ctx.data['input'], workspace / 'input.xlsx')
    (workspace / 'instruction.md').write_text(ctx.data['instruction'])
    return workspace


class RecoveryNode(BaseNode):
    node_id = 'independent_recovery'

    def execute(self, ctx):
        work = prepare_workspace(ctx, 'recovery_public')
        result = {'public_information_only': True, 'workspace': str(work), 'verified': False}
        try:
            (work / 'public_profile.json').write_text(json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False))
            public_payload = {'instruction': ctx.data['instruction'],
                'profile': compact_profile(ctx.data['public_profile']) if ctx.data.get('public_profile') else {}}
            compiler = ctx.llm.complete(prompt(ctx, 'recovery.md') + '\nPUBLIC INPUT JSON:\n' + json.dumps(public_payload, ensure_ascii=False),
                role='recovery_compiler', task_id=ctx.task_id, stage=self.node_id, workspace=work, isolated=True,
                timeout=ctx.config['agents']['timeout_seconds'])
            result['compiler'] = compiler
            if compiler.get('assumptions_added') or compiler.get('unresolved_questions'):
                raise ValueError('Public reconstruction requires unresolved or newly invented assumptions')
            code = compiler.get('code')
            if isinstance(code, str) and code.strip():
                compile(code, 'recovery.py', 'exec')
                (work / 'recovery.py').write_text(code)
                # Re-execute the witness from only public input and its program in a
                # fresh, network-disabled container. A hand-written output alone
                # cannot establish programmatic reconstruction.
                replay = ctx.revision_dir / ('recovery_replay-' + uuid.uuid4().hex[:8])
                replay.mkdir(parents=True)
                shutil.copy2(ctx.data['input'], replay / 'input.xlsx')
                shutil.copy2(work / 'recovery.py', replay / 'recovery.py')
                execution = subprocess.run(['docker', 'run', '--rm', '--user', '0', '--network', 'none',
                    '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
                    '--memory', '2g', '--pids-limit', '256', '--volume', str(replay.resolve()) + ':/workspace:rw',
                    '--workdir', '/workspace', '--entrypoint', '/usr/bin/python3',
                    ctx.config['engine']['image'], '/workspace/recovery.py'], capture_output=True, text=True, timeout=120)
                result['replay'] = {'directory': str(replay), 'returncode': execution.returncode,
                                    'stdout': execution.stdout[-4000:], 'stderr': execution.stderr[-4000:]}
                if execution.returncode or not (replay / 'output.xlsx').is_file():
                    raise ValueError('Independent recovery program did not reproduce an output from public input')
                calculated = ctx.engine.recalculate(replay / 'output.xlsx', ctx.revision_dir / 'private/recovered.xlsx')
                comparison = compare_workbooks(ctx.data['input'], ctx.data['goal'], calculated)
                result['comparison'] = comparison
                result['verified'] = comparison.get('reward') == 1
                result['program'] = (work / 'recovery.py').read_text()
        except Exception as exc:
            result['error'] = str(exc)
        ctx.save('independent_recovery.json', result)
        return {'recovery': result}


class TrajectoryNode(BaseNode):
    node_id = 'trajectory'

    def execute(self, ctx):
        work = prepare_workspace(ctx, 'trials/trial-000')
        trace = {'trial_id': 'trial-000', 'events': [], 'workspace': str(work)}
        try:
            result = ctx.llm.attempt(prompt(ctx, 'trajectory.md'), work, taskid=ctx.task_id, stage=self.node_id,
                                     timeout=ctx.config['agents']['trajectory_timeout_seconds'])
            trace.update({k: result[k] for k in ['events', 'reply', 'call_id', 'duration_ms'] if k in result})
        except Exception as exc:
            from ..llm.trace import recover_failed_attempt
            trace.update(recover_failed_attempt(exc, task_id=ctx.task_id, workspace=work))
        # No completion/reward branch: all traces proceed to diagnosis.
        ctx.save('trajectory.json', trace)
        return {'traces': [trace]}


class DiagnoseNode(BaseNode):
    node_id = 'diagnose'

    def execute(self, ctx):
        from ..llm.schemas import diagnosis_output_schema
        diagnosis_prompt = prompt(ctx, 'diagnosis.md')
        public = {'instruction': ctx.data['instruction'], 'profile': compact_profile(ctx.data['public_profile']),
                  'rules': ctx.data['plan']['public_rules'], 'task_mode': ctx.mode,
                  'input_sha256': hashlib.sha256(Path(ctx.data['input']).read_bytes()).hexdigest()}
        private = {'plan': ctx.data['plan'], 'construction': ctx.data['construction_validation'],
                   'expected_delta': ctx.data['delta'], 'root_impacts': ctx.data['root_impacts'],
                   'independent_recovery': ctx.data['recovery'],
                   'source_assessment': ctx.data.get('source_assessment', {}),
                   'native_risk_guard': ctx.data.get('native_risk_guard', {}),
                   'source_business_issues': ctx.data.get('source_business_issues', []),
                   'goal_sha256': hashlib.sha256(Path(ctx.data['goal']).read_bytes()).hexdigest(),
                   'native_errors': ctx.data['profile']['errors']}
        health = {'healthy': all(not t.get('infrastructure_error') for t in ctx.data['traces']),
                  'checks': [{'probe': 'codex_native_cli', 'model': ctx.llm.model},
                             {'probe': 'libreoffice_full_recalculation', 'engine': ctx.data['engine_report']}]}
        bundle = {'task_id': ctx.task_id, 'revision_hash': ctx.data['revision_hash'],
                  'revision': ctx.revision,
                  'public': public, 'private': private, 'engine_report': ctx.data['engine_report'],
                  'infrastructure_health_report': health}
        bundle['reviewer_context_hash'] = hashlib.sha256(json.dumps({
            'prompt': diagnosis_prompt, 'agents': ctx.config['agents'],
            'schema_contract': diagnosis_output_schema(['Q01'])},
            sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

        def review(payload):
            is_public = payload['visibility'] == 'public_only'
            work = prepare_workspace(ctx, 'diagnostic_public' if is_public else 'diagnostic_private')
            (work / 'evidence.json').write_text(json.dumps(payload, ensure_ascii=False, default=str))
            instruction = (diagnosis_prompt + '\nRead /workspace/evidence.json for all assigned '
                           'checks and evidence. Inspect input.xlsx/instruction.md as necessary. Return JSON only.')
            if not is_public:
                instruction = diagnosis_prompt + '\nINPUT JSON:\n' + json.dumps(payload, ensure_ascii=False, default=str)
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
        if not ctx.data['recovery']['verified']:
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
        else:
            report['mandatory_gates'] = {'independent_recovery': {'passed': True}}
        report['routes'] = route_issues(report['issues'], runner.catalog,
                                        ctx.config.get('diagnosis', {}).get('difficulty_deferred', False))
        report['coverage']['blocking_issue_ids'] = [issue['issue_id'] for issue in report['issues']
            if issue.get('severity', 'blocker') == 'blocker'
            and not (issue['problem_id'] == 'Q08' and runner.resolve(ctx.config)['difficulty_deferred'])]
        report['releasable'] = (report['releasable'] and ctx.data['recovery']['verified']
                                and not report['coverage']['blocking_issue_ids'])
        ctx.save('diagnosis.json', report)
        ctx.audit.task(ctx.task_id, issues=report['issues'], diagnosis_scope=report['scope'])
        for check, assessment in report['assessments'].items():
            ctx.audit.emit('checker.result', task_id=ctx.task_id, revision=ctx.revision,
                           checker=check, state=assessment['state'], reason=assessment['reason'])
        return {'diagnosis': report}


class RepairNode(BaseNode):
    node_id = 'repair'

    def execute(self, ctx):
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


def apply_instruction_repair(current_plan, patch, assigned_issue_ids):
    """Validate a Q03 patch and preserve every non-instruction field by copy."""
    expected_fields = {'public_instruction', 'addressed_issue_ids', 'changes', 'unresolved_questions'}
    if not isinstance(patch, dict) or set(patch) != expected_fields:
        raise TaskRejected('Q03 instruction repair must use the minimal four-field patch contract')
    instruction = patch['public_instruction']
    if not isinstance(instruction, str) or not instruction.strip():
        raise TaskRejected('Q03 instruction repair requires a nonempty public instruction')
    for field in ('addressed_issue_ids', 'changes', 'unresolved_questions'):
        if not isinstance(patch[field], list) or any(not isinstance(value, str) for value in patch[field]):
            raise TaskRejected('Q03 instruction repair requires string-list receipts')
    addressed = patch['addressed_issue_ids']
    if (len(addressed) != len(set(addressed)) or set(addressed) != set(assigned_issue_ids)):
        raise TaskRejected('Repair proposal did not account for all assigned issue instances exactly once')
    if patch['unresolved_questions']:
        raise TaskRejected('Q03 instruction repair has unresolved questions; collect evidence before applying it')
    proposed = deepcopy(current_plan)
    proposed['public_instruction'] = instruction.strip()
    return proposed


def _repair_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), default=str).encode()).hexdigest()


def instruction_repair_receipt(*, task_id, revision, current_plan, assigned_issues,
                               source_path, baseline_path, expected_source_sha256,
                               expected_baseline_sha256, proposal):
    """Bind a legacy proposal to audited files/plan/issues, without applying it."""
    if not assigned_issues or any(issue.get('problem_id') != 'Q03' or issue.get('certainty') != 'confirmed'
        or not issue.get('issue_id') or not issue.get('evidence') for issue in assigned_issues):
        raise TaskRejected('Legacy instruction replay requires confirmed, evidenced Q03 issues')
    source_hash = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    baseline_hash = hashlib.sha256(Path(baseline_path).read_bytes()).hexdigest()
    if source_hash != expected_source_sha256 or baseline_hash != expected_baseline_sha256:
        raise TaskRejected('Immutable source or baseline no longer matches the recorded repair receipts')
    return {'receipt_version': 1, 'task_id': task_id, 'revision': revision,
        'source_sha256': source_hash, 'baseline_sha256': baseline_hash,
        'plan_sha256': _repair_digest(current_plan),
        'issues_sha256': _repair_digest(sorted(assigned_issues, key=lambda issue: issue['issue_id'])),
        'proposal_sha256': _repair_digest(proposal)}


def replay_legacy_instruction_proposal(current_plan, proposal, assigned_issues, *, recorded_receipt, current_receipt):
    """Prepare an instruction-only plan from matched receipts; never release it.

    Callers must build current_receipt from the current files using
    instruction_repair_receipt. The controller must still consume the next
    revision and run all normal gates, including new actual Harbor controls.
    """
    required = {'receipt_version', 'task_id', 'revision', 'source_sha256', 'baseline_sha256',
                'plan_sha256', 'issues_sha256', 'proposal_sha256'}
    if (not isinstance(recorded_receipt, dict) or not isinstance(current_receipt, dict)
        or set(recorded_receipt) != required or recorded_receipt != current_receipt):
        raise TaskRejected('Legacy instruction replay receipts do not match the current task/source/plan/issues')
    if (current_receipt['plan_sha256'] != _repair_digest(current_plan)
        or current_receipt['proposal_sha256'] != _repair_digest(proposal)
        or current_receipt['issues_sha256'] != _repair_digest(sorted(assigned_issues, key=lambda issue: issue['issue_id']))):
        raise TaskRejected('Legacy instruction replay inputs differ from their receipt hashes')
    if any(issue.get('problem_id') != 'Q03' or issue.get('certainty') != 'confirmed' for issue in assigned_issues):
        raise TaskRejected('Legacy instruction replay is limited to confirmed Q03 issues')
    candidate = proposal.get('repaired_task', proposal) if isinstance(proposal, dict) else None
    if not isinstance(candidate, dict):
        raise TaskRejected('Legacy proposal has no public instruction candidate')
    patch = {'public_instruction': candidate.get('public_instruction'),
        'addressed_issue_ids': proposal.get('addressed_issue_ids', []),
        'changes': ['Extract only public_instruction from a receipt-matched historical proposal.'],
        'unresolved_questions': proposal.get('unresolved_questions', [])}
    next_plan = apply_instruction_repair(current_plan, patch, [issue['issue_id'] for issue in assigned_issues])
    differences = []
    for key in sorted((set(current_plan) | set(candidate)) - {'public_instruction'}):
        if key not in candidate or key not in current_plan or candidate[key] != current_plan[key]:
            differences.append({'field': key, 'kind': 'missing' if key not in candidate else
                'added' if key not in current_plan else 'changed', 'ignored': True})
    return {'next_plan': next_plan, 'receipt': deepcopy(current_receipt),
            'ignored_noninstruction_differences': differences,
            'requires_full_revision_gates': True, 'reuse_old_harbor_controls': False}


class ExportNode(BaseNode):
    node_id = 'export'

    def execute(self, ctx):
        destination = Path(ctx.config['run_dir']) / 'SpreadsheetEval' / ctx.task_id
        metadata = {'task_id': ctx.task_id, 'mode': ctx.mode, 'source_id': ctx.data['source_id'],
                    'source_file': ctx.source.name, 'difficulty_status': (
                        'deferred' if ctx.config.get('diagnosis', {}).get('difficulty_deferred', True) else 'pending'),
                    'revision': ctx.revision, 'revision_hash': ctx.data['revision_hash'],
                    'base_image': ctx.config['engine']['image']}
        export_harbor(ctx.revision_dir, destination, metadata, ctx.config['project_root'])
        (ctx.directory / 'lineage.json').write_text(json.dumps(metadata, indent=2))
        return {'export_dir': destination}
