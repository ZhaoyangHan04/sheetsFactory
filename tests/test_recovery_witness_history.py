"""Offline witness-history contracts, not model or LibreOffice evidence.

Workbooks contain explicitly declared caches. The subprocess fixture copies a
declared replay observation, and the engine transports that file unchanged.
Only the history, isolation, hashing and comparison controller is exercised.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import openpyxl
import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.core.node import CooperativeCancelled, TaskContext
from sheets_factory.nodes.quality import RecoveryNode
from sheets_factory.workbook.compare import compare_workbooks
from sheets_factory.workbook.profile import profile_workbook
from test_pipeline import model_fixture


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = '''import openpyxl
book = openpyxl.load_workbook('/workspace/input.xlsx')
for period in range(1, 7):
    book['Forecast'][f'B{period}'] = f'=Inputs!B1*{period}'
book.save('/workspace/output.xlsx')
book.close()
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DeclaredBackend:
    """Write real temporary audit rows for declared offline call observations."""
    model = 'offline-recovery-history'

    def __init__(self, audit):
        self.audit, self.calls, self.mode = audit, [], 'success'

    def complete(self, instruction, **kwargs):
        workspace = Path(kwargs['workspace'])
        call_id = 'actual-audit-call-' + str(len(self.calls))
        row = self.audit.record('calls', {'call_id': call_id, 'task_id': kwargs['task_id'],
            'stage': kwargs['stage'], 'role': kwargs['role'], 'workspace': str(workspace),
            'model': self.model, 'reasoning_effort': 'high', 'status': 'completed',
            'input_tokens': 40, 'cached_input_tokens': 20, 'output_tokens': 5})
        self.calls.append({'call_id': call_id, 'instruction': instruction, 'kwargs': kwargs,
                           'audit_row': row})
        assert kwargs['isolated'] is True and kwargs['role'] == 'recovery_compiler'
        assert 'PRIVATE_COMPARISON_ONLY' not in instruction
        assert not any('private' in file.name or 'goal' in file.name for file in workspace.iterdir())
        if self.mode == 'cancel':
            self.audit.update_record('calls', row, {'status': 'cancelled'})
            raise CooperativeCancelled('Declared fixture cooperative stop')
        if self.mode == 'llm_error':
            self.audit.update_record('calls', row, {'status': 'failed', 'error': 'Declared compiler transport failure'})
            raise RuntimeError('Declared compiler transport failure')
        return {'code': 'this is invalid Python !!!' if self.mode == 'syntax_error' else PROGRAM,
            'public_evidence_used': ['Forecast row periods; Inputs!B1 revenue; public instruction'],
            'assumptions_added': ['Declared unsupported fixture assumption'] if self.mode == 'assumption' else [],
            'unresolved_questions': [], 'call_id': 'untrusted-model-self-reported-call-id'}


class DeclaredReplay:
    def __init__(self, goal):
        self.goal, self.calls, self.mode = goal, [], 'success'

    def __call__(self, command, **kwargs):
        assert command[0] == 'docker' and command[command.index('--network') + 1] == 'none'
        volume = command[command.index('--volume') + 1]
        directory = Path(volume.rsplit(':/workspace:', 1)[0])
        assert {'input.xlsx', 'recovery.py'} <= {path.name for path in directory.iterdir()}
        assert not any('private' in path.name or 'goal' in path.name for path in directory.iterdir())
        self.calls.append({'command': command, 'directory': directory, 'kwargs': kwargs})
        if self.mode != 'no_output':
            shutil.copy2(self.goal, directory / 'output.xlsx')
        return SimpleNamespace(returncode=3 if self.mode == 'execution_error' else 0,
            stdout='Declared offline replay observation; no process was executed.',
            stderr='Declared local program failure.' if self.mode == 'execution_error' else '')


class FileTransportEngine:
    """Transport explicit caches. This object never evaluates Excel formulas."""
    def __init__(self):
        self.calls = []

    def recalculate(self, source, destination):
        source, destination = Path(source), Path(destination)
        self.calls.append((source, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination


@pytest.fixture
def witness(tmp_path, monkeypatch):
    audit = AuditStore(tmp_path / 'audit', {'id': 'offline-witness-history'})
    task_dir = tmp_path / 'task'
    revision = task_dir / 'revisions/000'
    (revision / 'private').mkdir(parents=True)
    (revision / 'public').mkdir()
    goal = model_fixture(revision / 'private/goal.xlsx')
    public_input = revision / 'public/input.xlsx'
    book = openpyxl.load_workbook(goal)
    for index in range(1, 7):
        book['Forecast'][f'B{index}'] = None
    book.save(public_input)
    book.close()
    instruction = 'Restore Forecast!B1:B6. Period n revenue equals Inputs!B1 multiplied by n.'
    (revision / 'public/instruction.md').write_text(instruction)
    backend, engine = DeclaredBackend(audit), FileTransportEngine()
    context = TaskContext('offline-witness-history', 'fm-witness', 'financial_modeling', goal,
        task_dir, {'project_root': str(ROOT), 'agents': {'timeout_seconds': 10},
                   'engine': {'image': 'declared-offline-transport-only'}}, audit, backend, engine)
    context.data.update(input=public_input, goal=goal, instruction=instruction,
        revision_hash='declared-revision-0', public_profile=profile_workbook(public_input),
        recovery={'verified': False, 'comparison': {'wrong_values': ['PRIVATE_COMPARISON_ONLY']}})
    replay = DeclaredReplay(goal)
    monkeypatch.setattr('sheets_factory.nodes.quality.subprocess.run', replay)
    fixture = SimpleNamespace(ctx=context, audit=audit, backend=backend, replay=replay, engine=engine,
        private=revision / 'private', input=public_input, goal=goal)
    yield fixture
    audit.db.close()


def execute(fixture):
    result = RecoveryNode().execute(fixture.ctx)['recovery']
    fixture.ctx.data['recovery'] = result
    return result


def attempt_path(result):
    return Path(result['attempt_record_path'])


def attempt_records(fixture):
    return sorted((fixture.private / 'recovery_attempts').glob('attempt_*/attempt.json'))


def modify_workbook(path):
    book = openpyxl.load_workbook(path)
    book['Notes']['B2'] = 'Declared artifact-tampering fixture.'
    book.save(path)
    book.close()


def test_successful_witness_has_immutable_record_and_reuse_starts_no_new_work(witness):
    first = execute(witness)
    assert first['verified'] is True
    assert first['comparison']['expected_change_count'] == 6
    record = attempt_path(first)
    assert record == witness.private / 'recovery_attempts/attempt_000000/attempt.json'
    assert first['attempt_record_sha256'] == digest(record)
    assert (record.parent / 'attempt.sha256').read_text().strip() == digest(record)
    assert first['witness_binding']['version'] == 1
    before = {path: path.read_bytes() for path in record.parent.rglob('*') if path.is_file()}
    second = execute(witness)
    assert second['verified'] and second['attempt_record_path'] == first['attempt_record_path']
    assert len(witness.backend.calls) == len(witness.replay.calls) == len(witness.engine.calls) == 1
    assert attempt_records(witness) == [record]
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert witness.audit.snapshot()['metrics']['total_tokens'] == 45


def test_lost_context_and_later_failed_aggregate_do_not_hide_an_earlier_valid_success(witness):
    success = execute(witness)
    before = attempt_path(success).read_bytes()
    failed_dir = witness.private / 'recovery_attempts/attempt_000001'
    failed_dir.mkdir()
    failed = {'verified': False, 'error': 'Declared later unsuccessful compiler observation'}
    failed_file = failed_dir / 'attempt.json'
    failed_file.write_text(json.dumps(failed))
    (failed_dir / 'attempt.sha256').write_text(digest(failed_file))
    failed.update(attempt_record_path=str(failed_file), attempt_record_sha256=digest(failed_file))
    (witness.private / 'independent_recovery.json').write_text(json.dumps(failed))
    witness.ctx.data.pop('recovery')
    witness.backend.mode = 'llm_error'
    result = execute(witness)
    assert result['verified'] is True and attempt_path(result) == attempt_path(success)
    assert len(witness.backend.calls) == len(witness.replay.calls) == 1
    assert attempt_path(success).read_bytes() == before
    assert len(attempt_records(witness)) == 2


@pytest.mark.parametrize('artifact', ['input', 'instruction', 'goal', 'program',
    'workspace_input', 'workspace_instruction', 'workspace_profile',
    'replay_input', 'replay_program', 'replay_output', 'attempt_recovered', 'canonical_recovered'])
def test_every_bound_artifact_change_prevents_successful_witness_reuse(witness, artifact):
    first = execute(witness)
    workspace = Path(first['workspace'])
    replay = Path(first['replay']['directory'])
    if artifact == 'input':
        modify_workbook(witness.input)
    elif artifact == 'instruction':
        witness.ctx.data['instruction'] += ' Preserve the declared public annual units.'
        (witness.private.parent / 'public/instruction.md').write_text(witness.ctx.data['instruction'])
    elif artifact == 'goal':
        modify_workbook(witness.goal)
    elif artifact == 'program':
        with (workspace / 'recovery.py').open('a') as stream:
            stream.write('\n# Declared artifact tampering.\n')
    elif artifact.startswith('workspace_'):
        path = workspace / {'workspace_input': 'input.xlsx', 'workspace_instruction': 'instruction.md',
                            'workspace_profile': 'public_profile.json'}[artifact]
        if path.suffix == '.xlsx':
            modify_workbook(path)
        else:
            path.write_bytes(path.read_bytes() + b'\n ')
    elif artifact.startswith('replay_'):
        path = replay / {'replay_input': 'input.xlsx', 'replay_program': 'recovery.py',
                         'replay_output': 'output.xlsx'}[artifact]
        if path.suffix == '.xlsx':
            modify_workbook(path)
        else:
            path.write_bytes(path.read_bytes() + b'\n# Declared artifact tampering.\n')
    elif artifact == 'attempt_recovered':
        candidates = list(attempt_path(first).parent.glob('*recovered*.xlsx'))
        assert len(candidates) == 1
        modify_workbook(candidates[0])
    else:
        modify_workbook(witness.private / 'recovered.xlsx')
    old_record = attempt_path(first).read_bytes()
    result = execute(witness)
    assert len(witness.backend.calls) == 2, 'Changed evidence must require a new independent attempt'
    assert len(witness.replay.calls) == 2
    assert attempt_path(first).read_bytes() == old_record
    assert len(attempt_records(witness)) == 2
    assert attempt_path(result).parent.name == 'attempt_000001'


def test_legacy_verified_claim_without_new_binding_cannot_skip_reconstruction(witness):
    shutil.copy2(witness.goal, witness.private / 'recovered.xlsx')
    legacy = {'verified': True, 'public_information_only': True,
        'comparison': {'reward': 1}, 'compiler': {'assumptions_added': [], 'unresolved_questions': []}}
    witness.ctx.data['recovery'] = legacy
    (witness.private / 'independent_recovery.json').write_text(json.dumps(legacy))
    result = execute(witness)
    assert result['verified'] and len(witness.backend.calls) == len(witness.replay.calls) == 1
    assert result['witness_binding']['version'] == 1


@pytest.mark.parametrize('stage', ['syntax_error', 'llm_error', 'assumption', 'execution_error', 'no_output'])
def test_failed_attempt_is_retained_and_never_overwrites_an_earlier_record(witness, stage):
    if stage in {'syntax_error', 'llm_error', 'assumption'}:
        witness.backend.mode = stage
    else:
        witness.replay.mode = stage
    failed = execute(witness)
    assert failed['verified'] is False
    failed_record = attempt_path(failed)
    original = failed_record.read_bytes()
    assert (failed_record.parent / 'attempt.sha256').read_text().strip() == digest(failed_record)
    assert not (witness.private / 'recovered.xlsx').exists()
    witness.backend.mode = witness.replay.mode = 'success'
    success = execute(witness)
    assert success['verified'] and len(witness.backend.calls) == 2
    assert failed_record.read_bytes() == original
    assert [path.parent.name for path in attempt_records(witness)] == ['attempt_000000', 'attempt_000001']


def test_failed_comparison_is_never_transmitted_as_feedback_to_a_new_compiler(witness, monkeypatch):
    ordinary = compare_workbooks
    def declared_mismatch(*args):
        observed = ordinary(*args)
        observed.update(reward=0, wrong_values=['PRIVATE_COMPARISON_ONLY'])
        return observed
    monkeypatch.setattr('sheets_factory.nodes.quality.compare_workbooks', declared_mismatch)
    first = execute(witness)
    assert first['verified'] is False
    assert first['comparison']['wrong_values'] == ['PRIVATE_COMPARISON_ONLY']
    assert not (witness.private / 'recovered.xlsx').exists()
    monkeypatch.setattr('sheets_factory.nodes.quality.compare_workbooks', ordinary)
    result = execute(witness)
    assert result['verified'] and len(witness.backend.calls) == 2
    assert all('PRIVATE_COMPARISON_ONLY' not in call['instruction'] for call in witness.backend.calls)
    for call in witness.backend.calls:
        workspace = Path(call['kwargs']['workspace'])
        assert all(b'PRIVATE_COMPARISON_ONLY' not in path.read_bytes()
                   for path in workspace.iterdir() if path.is_file())


def test_reuse_rechecks_complete_comparison_instead_of_trusting_a_saved_reward(witness, monkeypatch):
    execute(witness)
    calls = []
    def changed_verifier_decision(*args):
        calls.append(args)
        result = compare_workbooks(*args)
        assert result['expected_change_count'] == 6
        result['reward'] = 0
        return result
    monkeypatch.setattr('sheets_factory.nodes.quality.compare_workbooks', changed_verifier_decision)
    result = execute(witness)
    assert calls, 'A saved success must undergo another complete value comparison'
    assert len(witness.backend.calls) == 2 and result['verified'] is False
    assert any(Path(args[0]) == witness.input and Path(args[1]) == witness.goal for args in calls)


def test_attempt_links_actual_audit_call_and_usage_not_model_self_report(witness):
    result = execute(witness)
    record = json.loads(attempt_path(result).read_text())
    actual, = witness.audit.snapshot()['llm_calls']
    encoded = json.dumps(record)
    assert actual['call_id'] in encoded and actual['call_id'] != result['compiler']['call_id']
    assert actual['workspace'] == result['workspace']
    usage, = record['usage_calls']
    assert record['usage_attribution'] == 'audit_call_ids'
    assert usage['call_id'] == actual['call_id']
    assert usage['input_tokens'] == actual['input_tokens'] == 40
    assert usage['output_tokens'] == actual['output_tokens'] == 5
    assert actual['input_tokens'] == 40 and actual['output_tokens'] == 5
    assert witness.audit.snapshot()['metrics']['total_tokens'] == 45
    assert len(witness.backend.calls) == 1


def test_cooperative_stop_escapes_recovery_instead_of_becoming_a_failed_witness(witness):
    witness.backend.mode = 'cancel'
    with pytest.raises(CooperativeCancelled):
        execute(witness)
    assert len(witness.backend.calls) == 1 and not witness.replay.calls
    assert not (witness.private / 'recovered.xlsx').exists()
    assert witness.audit.snapshot()['llm_calls'][0]['status'] == 'cancelled'


@pytest.mark.parametrize('artifact', ['input.xlsx', 'instruction.md', 'public_profile.json'])
def test_compiler_changing_its_public_inputs_cannot_obtain_an_initial_verified_receipt(witness, artifact):
    original = witness.backend.complete
    def compile_then_change_public_input(instruction, **kwargs):
        result = original(instruction, **kwargs)
        path = Path(kwargs['workspace']) / artifact
        if path.suffix == '.xlsx':
            modify_workbook(path)
        else:
            path.write_bytes(path.read_bytes() + b'\n ')
        return result
    witness.backend.complete = compile_then_change_public_input
    result = execute(witness)
    assert result['verified'] is False
    assert not (witness.private / 'recovered.xlsx').exists()
    assert len(witness.backend.calls) == 1 and attempt_path(result).is_file()


@pytest.mark.parametrize('artifact', ['recovery.py', 'input.xlsx'])
def test_replay_self_modification_cannot_obtain_an_initial_verified_receipt(witness, monkeypatch, artifact):
    original = witness.replay
    def replay_then_change_its_input(command, **kwargs):
        result = original(command, **kwargs)
        path = original.calls[-1]['directory'] / artifact
        if path.suffix == '.xlsx':
            modify_workbook(path)
        else:
            path.write_bytes(path.read_bytes() + b'\n# Declared self-modification.\n')
        return result
    monkeypatch.setattr('sheets_factory.nodes.quality.subprocess.run', replay_then_change_its_input)
    result = execute(witness)
    assert result['verified'] is False
    assert not (witness.private / 'recovered.xlsx').exists()
    assert len(witness.backend.calls) == len(witness.replay.calls) == 1


def rewrite_record(result, mutate):
    """Construct internally hash-consistent adversarial *test* metadata."""
    changed = deepcopy(result)
    changed.pop('attempt_record_sha256')
    mutate(changed)
    record = attempt_path(result)
    record.chmod(0o600)
    record.write_text(json.dumps(changed, ensure_ascii=False, indent=2) + '\n')
    checksum = digest(record)
    sidecar = record.parent / 'attempt.sha256'
    sidecar.chmod(0o600)
    sidecar.write_text(checksum + '\n')
    changed['attempt_record_sha256'] = checksum
    return changed


@pytest.mark.parametrize('claim', ['public_only', 'network_flag', 'returncode', 'network_command',
                                  'extra_mount', 'invented_assumption'])
def test_hash_consistent_but_invalid_execution_claims_cannot_reuse_a_witness(witness, claim):
    first = execute(witness)
    def corrupt(record):
        if claim == 'public_only':
            record['public_information_only'] = False
        elif claim == 'network_flag':
            record['replay']['fresh_network_disabled_container'] = False
        elif claim == 'returncode':
            record['replay']['returncode'] = False  # bool must not masquerade as process exit code 0.
        elif claim == 'network_command':
            command = record['replay']['command']
            command[command.index('--network') + 1] = 'host'
        elif claim == 'extra_mount':
            record['replay']['command'][2:2] = ['--volume', '/unavailable-private-evidence:/hidden:ro']
        else:
            record['compiler']['assumptions_added'] = ['An undeclared financing assumption']
    changed = rewrite_record(first, corrupt)
    witness.ctx.data['recovery'] = changed
    (witness.private / 'independent_recovery.json').write_text(json.dumps(changed))
    result = execute(witness)
    assert result['verified'] and len(witness.backend.calls) == 2
    assert attempt_path(result).parent.name == 'attempt_000001'


def test_reuse_event_contains_binding_digest_without_private_paths(witness):
    execute(witness)
    execute(witness)
    event, = [event for event in witness.audit.events() if event['kind'] == 'recovery.witness_reused']
    assert event['binding_sha256'] and len(event['binding_sha256']) == 64
    assert str(witness.private.parent) not in json.dumps(event)


@pytest.mark.parametrize('change', ['revision_hash', 'revision', 'immutable_record_sha'])
def test_changed_revision_identity_or_broken_immutable_record_prevents_reuse(witness, change):
    first = execute(witness)
    record = attempt_path(first)
    if change == 'revision_hash':
        witness.ctx.data['revision_hash'] = 'declared-different-revision-hash'
    elif change == 'revision':
        old_input, old_goal = witness.ctx.data['input'], witness.ctx.data['goal']
        witness.ctx.revision = 1
        revision = witness.ctx.revision_dir
        (revision / 'public').mkdir(parents=True)
        (revision / 'private').mkdir()
        witness.ctx.data['input'] = revision / 'public/input.xlsx'
        witness.ctx.data['goal'] = revision / 'private/goal.xlsx'
        shutil.copy2(old_input, witness.ctx.data['input'])
        shutil.copy2(old_goal, witness.ctx.data['goal'])
        (revision / 'public/instruction.md').write_text(witness.ctx.data['instruction'])
        witness.ctx.data['revision_hash'] = 'declared-revision-1'
        witness.replay.goal = witness.ctx.data['goal']
    else:
        record.chmod(0o600)
        record.write_bytes(record.read_bytes() + b'\n')  # Valid JSON, invalid immutable-byte checksum.
    retained = record.read_bytes()
    result = execute(witness)
    assert result['verified'] and len(witness.backend.calls) == 2
    assert attempt_path(result) != record and record.read_bytes() == retained
    assert result['witness_binding']['revision'] == witness.ctx.revision
    assert result['witness_binding']['task_revision_hash'] == witness.ctx.data['revision_hash']
