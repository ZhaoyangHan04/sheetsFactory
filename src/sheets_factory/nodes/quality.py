from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import uuid
import re

from ..core.node import BaseNode, TaskRejected, CooperativeCancelled
from ..core.audit import utcnow
from ..workbook import compare_workbooks
from ..checkers import DiagnosisRunner
from ..checkers.router import route_issues
from ..evaluation.harbor import export_harbor
from .construction import prompt, compact_profile, construction_contract, authoring_source_context


PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS = (
    '\nPrivate evidence transport: workspace_json_file_v1. Your current working directory is the '
    'private diagnostic workspace passed to this call. Open the relative file evidence.json from '
    'that directory; do not assume the public container path /workspace/evidence.json. '
    'The receipt below binds the complete evidence file by SHA256 and UTF-8 byte count. '
    'Use Python to load the JSON, inspect its keys and collection lengths, and retrieve bounded '
    'sections or iterate records as needed. Do not cat or print the entire evidence file. '
    'The complete payload remains available without omitted fields. Summaries are navigation aids, '
    'not replacements for evidence: review every assigned check and the COMPLETE expected_delta, '
    'including all downstream outputs and each provisional candidate, using bounded iteration when '
    'large. Request specific missing evidence if coverage cannot be completed; do not silently '
    'sample the required scope or mark it clear. Inspect input.xlsx/instruction.md and the allowed '
    'private reference as necessary. Return JSON only.\nEVIDENCE FILE RECEIPT:\n')

REFERENCE_POLICIES = {'independent_public_recovery', 'reference_review'}
REFERENCE_REVIEW_CHECKS = ('Q01', 'Q02', 'Q03', 'Q04')
REFERENCE_REVIEW_PREFIX = 'reference_review_json:'


def reference_evidence_policy(config):
    policy = config.get('diagnosis', {}).get('reference_evidence_policy', 'independent_public_recovery')
    if not isinstance(policy, str) or policy not in REFERENCE_POLICIES:
        raise ValueError('Unsupported diagnosis.reference_evidence_policy')
    return policy


def validate_reference_policy_selection(config, runner=None):
    policy = reference_evidence_policy(config)
    if policy == 'reference_review':
        runner = runner or DiagnosisRunner(config.get('project_root'))
        plan = runner.resolve(config)
        if set(plan['enabled_check_ids']) != {f'Q{number:02d}' for number in range(1, 13)}:
            raise ValueError('reference_review requires all twelve diagnostic checks enabled')
    return policy


def reference_revision_binding(ctx):
    input_raw = Path(ctx.data['input']).read_bytes()
    instruction_raw = ctx.data['instruction'].encode()
    revision_hash = hashlib.sha256(input_raw + instruction_raw).hexdigest()
    if ctx.data.get('revision_hash') != revision_hash:
        raise ValueError('Reference evidence has a stale public revision hash')
    return {'task_id': ctx.task_id, 'revision': ctx.revision, 'task_revision_hash': revision_hash,
        'input_sha256': hashlib.sha256(input_raw).hexdigest(),
        'instruction_sha256': hashlib.sha256(instruction_raw).hexdigest(),
        'goal_sha256': _recovery_sha(ctx.data['goal'])}


def reference_review_assessments(report, binding):
    """Validate actual supported conclusions; an exact solving witness is absent."""
    problems = []
    for check in REFERENCE_REVIEW_CHECKS:
        assessment = report.get('assessments', {}).get(check, {})
        if (assessment.get('state') != 'clear' or not assessment.get('reason')
                or not assessment.get('evidence') or assessment.get('execution_status', 'completed') != 'completed'):
            problems.append(check + ': supported clear assessment required')
    receipts = []
    for item in report.get('assessments', {}).get('Q04', {}).get('evidence', []):
        if isinstance(item, str) and item.startswith(REFERENCE_REVIEW_PREFIX):
            try:
                receipts.append(json.loads(item[len(REFERENCE_REVIEW_PREFIX):]))
            except (ValueError, TypeError):
                problems.append('Q04: invalid reference review JSON receipt')
    receipt = receipts[0] if len(receipts) == 1 and isinstance(receipts[0], dict) else {}
    if len(receipts) != 1:
        problems.append('Q04: exactly one explicit reference review receipt required')
    if receipt.get('binding') != binding:
        problems.append('Q04: reference review receipt is stale or unbound')
    if (not isinstance(receipt.get('business_evidence'), list) or not receipt['business_evidence']
            or any(not isinstance(item, (str, dict)) or not item for item in receipt['business_evidence'])):
        problems.append('Q04: source business evidence required')
    checks = receipt.get('financial_validation_checks')
    if (not isinstance(checks, list) or not checks
            or any(not isinstance(check, dict) or check.get('passed') is not True
                   or not isinstance(check.get('check'), str) or not check['check'].strip()
                   or not isinstance(check.get('method'), str) or not check['method'].strip()
                   or not isinstance(check.get('evidence'), list) or not check['evidence'] for check in checks)):
        problems.append('Q04: supported independent financial validation checks required')
    return {'passed': not problems, 'required_check_ids': list(REFERENCE_REVIEW_CHECKS),
        'binding': binding, 'problems': problems, 'q04_receipt': receipt,
        'method': 'reference_review', 'independent_public_recovery': False}


def _reference_review_context(ctx, binding):
    source_business = {key: deepcopy(ctx.data.get(key, {} if key != 'source_business_issues' else []))
        for key in ('source_assessment', 'finance_evidence', 'source_business_issues')}
    context = {'binding': binding, 'source_business_evidence': source_business,
        'financial_validation': {'construction': ctx.data['construction_validation'],
            'engine_report': ctx.data['engine_report'], 'local_controls': ctx.data['controls']},
        'policy': 'reference_review', 'independent_public_recovery': False}
    ctx.save('reference_evidence_context.json', context)
    names = ('edit_validation.json', 'expected_delta.json', 'native_error_probe.json',
             'native_risk_guard.json', 'local_controls.json', 'reference_evidence_context.json')
    artifacts = {}
    for name in names:
        path = ctx.revision_dir / 'private' / name
        if not path.is_file():
            raise ValueError('Reference review lacks actual evidence: ' + name)
        artifacts[name] = {'path': str(path.resolve()), 'sha256': _recovery_sha(path)}
    return context, artifacts


def prepare_workspace(ctx, name):
    workspace = ctx.revision_dir / (name + '-' + uuid.uuid4().hex[:8])
    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ctx.data['input'], workspace / 'input.xlsx')
    (workspace / 'instruction.md').write_text(ctx.data['instruction'])
    return workspace


def candidate_difficulty_context(config):
    """Separate local Q08 evidence from the mandatory later cohort evaluation."""
    diagnosis = config.get('diagnosis', {})
    deferred = diagnosis.get('difficulty_deferred') is True
    required = not deferred and (diagnosis.get('difficulty_deferred') is False or bool(config.get('difficulty')))
    # This optional contract is explicitly public configuration, never the
    # private plan, reference, source paths or expected answers.
    contract = deepcopy(diagnosis.get('template_complexity_contract', []))
    def check_public(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r'private|secret|path', str(key), re.I):
                    raise ValueError('Q08 complexity contract must contain public constraints, not private paths')
                check_public(item)
        elif isinstance(value, list):
            for item in value:
                check_public(item)
        elif isinstance(value, str) and (
                re.search(r'''(?:^|[\s"'=(])(?:/|~[/\\]|[A-Za-z]:[/\\])\S+''', value)
                or re.search(r'''(?:^|[\s"'=(])(?:\.\.?/|private/|outputs/|\.secrets/)\S+''', value)
                or '/private/' in value or '.secrets' in value):
            raise ValueError('Q08 complexity contract must not expose filesystem paths')
    check_public(contract)
    return {'stage': 'candidate_quality', 'template_complexity_contract': contract,
        'candidate_Q08_scope': 'Declared hard complexity constraints and concrete executable-shortcut evidence only; inspect public artifacts and traces.',
        'no_applicable_local_probe_state': 'not_applicable',
        'planning_preferences_are_hard_constraints': False,
        'missing_future_cohort_score_is_evidence_gap': False,
        'candidate_assessment_grants_publication': False,
        'formal_cohort_gate': {'required': required,
            'status': 'pending' if required else ('deferred_by_explicit_scope' if deferred else 'not_configured'),
            'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh',
            'timeout_seconds': 1800,
            'overall_pass_at_1_max': 0.2, 'minimum_tasks_per_mode': 10,
            'fresh_frozen_confirmation_required': True}}


def _recovery_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _recovery_artifacts(ctx, result):
    work, replay = Path(result['workspace']), Path(result['replay']['directory'])
    attempt = Path(result['attempt_record_path']).parent
    return {'workspace_input': work / 'input.xlsx', 'workspace_instruction': work / 'instruction.md',
        'workspace_profile': work / 'public_profile.json', 'workspace_program': work / 'recovery.py',
        'replay_input': replay / 'input.xlsx', 'replay_program': replay / 'recovery.py',
        'replay_output': replay / 'output.xlsx', 'attempt_recovered': attempt / 'recovered.xlsx',
        'recovered': ctx.revision_dir / 'private/recovered.xlsx'}


def _recovery_binding(ctx, result):
    return {'version': 1, 'task_id': ctx.task_id, 'revision': ctx.revision,
        'task_revision_hash': ctx.data.get('revision_hash'),
        'input_sha256': _recovery_sha(ctx.data['input']),
        'instruction_sha256': hashlib.sha256(ctx.data['instruction'].encode()).hexdigest(),
        'goal_sha256': _recovery_sha(ctx.data['goal']),
        'program_sha256': hashlib.sha256(result['program'].encode()).hexdigest(),
        'artifacts': {name: {'path': str(path.resolve()), 'sha256': _recovery_sha(path)}
                      for name, path in _recovery_artifacts(ctx, result).items()}}


def _recovery_local_file(path, ctx):
    path, root = Path(path).absolute(), ctx.revision_dir.resolve()
    return (path.is_relative_to(root) and path.resolve().is_relative_to(root) and path.is_file()
        and not any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)))


def _recovery_replay_command(ctx, replay):
    return ['docker', 'run', '--rm', '--user', '0', '--network', 'none',
        '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
        '--memory', '2g', '--pids-limit', '256', '--volume', str(Path(replay).resolve()) + ':/workspace:rw',
        '--workdir', '/workspace', '--entrypoint', '/usr/bin/python3',
        ctx.config['engine']['image'], '/workspace/recovery.py']


def _recovery_public_execution_valid(ctx, candidate):
    compiler, replay = candidate.get('compiler') or {}, candidate.get('replay') or {}
    program = candidate.get('program')
    if (candidate.get('public_information_only') is not True or not ctx.data.get('revision_hash')
            or compiler.get('assumptions_added') or compiler.get('unresolved_questions')
            or type(replay.get('returncode')) is not int or replay['returncode'] != 0
            or replay.get('fresh_network_disabled_container') is not True
            or not isinstance(program, str) or not program or compiler.get('code') != program
            or replay.get('command') != _recovery_replay_command(ctx, replay['directory'])):
        return False
    files = _recovery_artifacts(ctx, candidate)
    required = ('workspace_input', 'workspace_instruction', 'workspace_profile', 'workspace_program',
                'replay_input', 'replay_program', 'replay_output', 'attempt_recovered')
    if not all(_recovery_local_file(files[name], ctx) for name in required):
        return False
    return (files['workspace_input'].read_bytes() == Path(ctx.data['input']).read_bytes()
        and files['replay_input'].read_bytes() == Path(ctx.data['input']).read_bytes()
        and files['workspace_instruction'].read_bytes() == ctx.data['instruction'].encode()
        and files['workspace_profile'].read_bytes() == json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False).encode()
        and files['workspace_program'].read_bytes() == program.encode()
        and files['replay_program'].read_bytes() == program.encode()
        and replay.get('initial_files') == {'input.xlsx': _recovery_sha(ctx.data['input']),
            'recovery.py': hashlib.sha256(program.encode()).hexdigest()})


def _valid_recovery_witness(ctx, candidate):
    """Validate an actual new receipt and bytes, never a bare verified flag."""
    try:
        if not isinstance(candidate, dict) or candidate.get('verified') is not True:
            return False
        record_path = Path(candidate['attempt_record_path'])
        checksum_path = record_path.parent / 'attempt.sha256'
        if (record_path.parent.parent.absolute() != (ctx.revision_dir / 'private/recovery_attempts').absolute()
                or not _recovery_local_file(record_path, ctx) or not _recovery_local_file(checksum_path, ctx)):
            return False
        raw = record_path.read_bytes()
        checksum = _recovery_sha(record_path)
        if (candidate.get('attempt_record_sha256') != checksum
                or checksum_path.read_text().strip() != checksum):
            return False
        stored = json.loads(raw)
        if stored != {k: v for k, v in candidate.items() if k != 'attempt_record_sha256'}:
            return False
        if not _recovery_public_execution_valid(ctx, candidate):
            return False
        files = _recovery_artifacts(ctx, candidate)
        if not all(_recovery_local_file(path, ctx) for path in files.values()):
            return False
        binding = candidate.get('witness_binding') or {}
        if not binding.get('task_revision_hash') or binding != _recovery_binding(ctx, candidate):
            return False
        if files['attempt_recovered'].read_bytes() != files['recovered'].read_bytes():
            return False
        actual = compare_workbooks(ctx.data['input'], ctx.data['goal'], files['recovered'])
        return actual.get('reward') == 1 and actual == candidate.get('comparison')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _reusable_recovery(ctx):
    candidates = [ctx.data.get('recovery')]
    aggregate = ctx.revision_dir / 'private/independent_recovery.json'
    if aggregate.is_file():
        try:
            candidates.append(json.loads(aggregate.read_text()))
        except (OSError, ValueError):
            pass
    for path in sorted((ctx.revision_dir / 'private/recovery_attempts').glob('attempt_*/attempt.json')):
        try:
            candidate = json.loads(path.read_text())
            candidate['attempt_record_sha256'] = (path.parent / 'attempt.sha256').read_text().strip()
            candidates.append(candidate)
        except (OSError, ValueError, TypeError):
            continue
    seen = set()
    for candidate in candidates:
        # The current context, aggregate and immutable history often contain the
        # same receipt. Recheck its workbook once, without treating duplicates as
        # another opportunity to obtain a passing comparison.
        fingerprint = json.dumps(candidate, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        if _valid_recovery_witness(ctx, candidate):
            return candidate
    return None


def _recovery_calls(ctx):
    snapshot = getattr(ctx.audit, 'snapshot', None)
    if not callable(snapshot):
        return {}
    calls = snapshot().get('llm_calls', [])
    return {call['call_id']: call for call in calls if call.get('call_id')
            and call.get('task_id') == ctx.task_id and call.get('stage') == 'independent_recovery'}


class RecoveryNode(BaseNode):
    node_id = 'independent_recovery'

    def execute(self, ctx):
        policy = validate_reference_policy_selection(ctx.config)
        if policy == 'reference_review':
            result = {'status': 'not_applicable', 'skipped': True, 'verified': False,
                'public_information_only': False, 'reference_evidence_policy': policy,
                'binding': reference_revision_binding(ctx), 'task_revision_hash': ctx.data['revision_hash'],
                'reason': 'Reference correctness is reviewed by supported Q01–Q04 diagnostics; no public-solving witness was attempted.',
                'usage_calls': [], 'usage_attribution': 'not_applicable_no_solver_call'}
            ctx.save('independent_recovery.json', result)
            return {'recovery': result}
        compiler_backend = ctx.config.get('recovery', {}).get('compiler_backend', 'llm')
        if compiler_backend not in {'llm', 'project_journal'}:
            raise ValueError('Unsupported recovery.compiler_backend')
        if compiler_backend == 'project_journal' and ctx.data.get('finance_evidence', {}).get('financial_seed_verified') is not True:
            raise TaskRejected('Journal reconstruction requires a verified financial source')
        reusable = _reusable_recovery(ctx)
        if reusable is not None:
            ctx.save('independent_recovery.json', reusable)
            ctx.audit.emit('recovery.witness_reused', task_id=ctx.task_id, revision=ctx.revision,
                attempt_id=reusable['attempt_id'], binding_sha256=hashlib.sha256(json.dumps(
                    reusable['witness_binding'], sort_keys=True).encode()).hexdigest())
            return {'recovery': reusable}
        history = ctx.revision_dir / 'private/recovery_attempts'
        history.mkdir(parents=True, exist_ok=True)
        index = 0
        while True:
            attempt = history / f'attempt_{index:06d}'
            try:
                attempt.mkdir(mode=0o700)
                break
            except FileExistsError:
                index += 1
        result = {'public_information_only': True, 'verified': False, 'attempt_id': attempt.name,
            'attempt_record_path': str(attempt / 'attempt.json'), 'started_at': utcnow(),
            'task_revision_hash': ctx.data.get('revision_hash'), 'compiler_backend': compiler_backend}
        previous_calls = set(_recovery_calls(ctx))
        try:
            work = prepare_workspace(ctx, 'recovery_public')
            result['workspace'] = str(work)
            (work / 'public_profile.json').write_text(json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False))
            public_payload = {'instruction': ctx.data['instruction'],
                'profile': compact_profile(ctx.data['public_profile']) if ctx.data.get('public_profile') else {}}
            if compiler_backend == 'project_journal':
                from ..workbook.derived_gold.public_recovery import compile_public_project_recovery
                compiler = {'code': compile_public_project_recovery(),
                    'public_evidence_used': ['Public Scenario assumptions, model labels and business policies'],
                    'assumptions_added': [], 'unresolved_questions': [],
                    'implementation': 'independent_decimal_journal', 'is_llm_attempt': False}
            else:
                compiler = ctx.llm.complete(prompt(ctx, 'recovery.md') + '\nPUBLIC INPUT JSON:\n' + json.dumps(public_payload, ensure_ascii=False),
                    role='recovery_compiler', task_id=ctx.task_id, stage=self.node_id, workspace=work, isolated=True,
                    timeout=ctx.config['agents']['timeout_seconds'])
            result['compiler'] = compiler
            if compiler.get('assumptions_added') or compiler.get('unresolved_questions'):
                raise ValueError('Public reconstruction requires unresolved or newly invented assumptions')
            code = compiler.get('code')
            if not isinstance(code, str) or not code.strip():
                raise ValueError('Compiler did not return a runnable recovery program')
            if isinstance(code, str) and code.strip():
                result['program'] = code
                compile(code, 'recovery.py', 'exec')
                (work / 'recovery.py').write_text(code)
                # Re-execute the witness from only public input and its program in a
                # fresh, network-disabled container. A hand-written output alone
                # cannot establish programmatic reconstruction.
                replay = ctx.revision_dir / ('recovery_replay-' + uuid.uuid4().hex[:8])
                replay.mkdir(parents=True)
                shutil.copy2(ctx.data['input'], replay / 'input.xlsx')
                shutil.copy2(work / 'recovery.py', replay / 'recovery.py')
                command = _recovery_replay_command(ctx, replay)
                initial = {'input.xlsx': _recovery_sha(replay / 'input.xlsx'),
                           'recovery.py': _recovery_sha(replay / 'recovery.py')}
                result['replay'] = {'directory': str(replay), 'returncode': None,
                                    'fresh_network_disabled_container': True, 'initial_files': initial,
                                    'command': command}
                execution = subprocess.run(command, capture_output=True, text=True, timeout=120)
                (attempt / 'replay.stdout.txt').write_text(execution.stdout)
                (attempt / 'replay.stderr.txt').write_text(execution.stderr)
                result['replay'].update(returncode=execution.returncode,
                    stdout=execution.stdout[-4000:], stderr=execution.stderr[-4000:],
                    stdout_file=str(attempt / 'replay.stdout.txt'), stderr_file=str(attempt / 'replay.stderr.txt'))
                if execution.returncode or not (replay / 'output.xlsx').is_file():
                    raise ValueError('Independent recovery program did not reproduce an output from public input')
                calculated = ctx.engine.recalculate(replay / 'output.xlsx', attempt / 'recovered.xlsx')
                if not _recovery_public_execution_valid(ctx, result):
                    raise ValueError('Recovery execution is not bound to the unchanged public inputs and returned program')
                comparison = compare_workbooks(ctx.data['input'], ctx.data['goal'], calculated)
                result['comparison'] = comparison
                if comparison.get('reward') == 1:
                    shutil.copy2(calculated, ctx.revision_dir / 'private/recovered.xlsx')
                    result['replay_output_sha256'] = _recovery_sha(replay / 'output.xlsx')
                    result['recovered_sha256'] = _recovery_sha(calculated)
                    result['witness_binding'] = _recovery_binding(ctx, result)
                    result['verified'] = True
        except CooperativeCancelled:
            result.update(status='cancelled', error='Explicit cooperative stop before further recovery work')
            raise
        except Exception as exc:
            result['error'] = str(exc)
            result['error_type'] = type(exc).__name__
        finally:
            calls = _recovery_calls(ctx)
            keys = ('call_id', 'model', 'reasoning_effort', 'status', 'input_tokens', 'cached_input_tokens',
                    'cache_write_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'duration_ms')
            result['usage_calls'] = [{k: call.get(k) for k in keys} for call_id, call in calls.items()
                                     if call_id not in previous_calls]
            result['usage_attribution'] = ('audit_call_ids' if result['usage_calls'] else
                'not_applicable_programmatic' if compiler_backend == 'project_journal' else 'unavailable')
            result['finished_at'] = utcnow()
            result.setdefault('status', 'verified' if result['verified'] else 'unverified')
            raw = (json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n').encode()
            record = attempt / 'attempt.json'
            with record.open('xb') as stream:
                stream.write(raw)
            checksum = hashlib.sha256(raw).hexdigest()
            with (attempt / 'attempt.sha256').open('x') as stream:
                stream.write(checksum + '\n')
            record.chmod(0o444)
            (attempt / 'attempt.sha256').chmod(0o444)
            result['attempt_record_sha256'] = checksum
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
