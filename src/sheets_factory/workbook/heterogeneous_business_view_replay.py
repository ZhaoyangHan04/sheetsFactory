"""Current-revision public-table replay for the two business-view scopes.

The public parser and Decimal ledger are shared with the previously tested
recovery. They are independent of Excel definitions, not a third financial
implementation. Only public tables, instructions, generic code and a nonce
enter the replay mount. Private reference comparison occurs after its exit.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import types
import uuid

from ..nodes.quality import RecoveryNode
from . import heterogeneous_financial_view_public_recovery as original

SETTING = 'heterogeneous_business_modeling'
BACKEND = original.BACKEND
REPLAY_SECONDS = 7200
IMAGE = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
SOURCE_SHA256 = {
    'recovery': '009a454cd9a6a03b14054be7218b54e6809f7188622b088153f24c9aa059b5bf',
    'spec': 'e501a93319532c7132f256a0c2e01e0354ea3ababaf2627237e56f166d90bdcf',
    'ledger': 'abf47300e5685c8507de4f93279839d31a0ebedd661c5972a2ff3fcca3b18351',
}
PUBLIC_FILES = ('input.xlsx', 'instruction.md', 'run.py', 'public_nonce.txt',
    'public_recovery/__init__.py', 'public_recovery/recovery.py',
    'public_recovery/heterogeneous_contracts/spec.py',
    'public_recovery/heterogeneous_contracts/ledger.py')
GENERATED_FILES = ('recovered.xlsx', 'public_recovery_report.json')
_BASE_EXCLUDED = ('month', 'term_id', 'tax_policy', 'dscr_policy', 'cure_open', 'cure_next')
_V3_EXCLUDED = ('cash_before_financing', 'trap_operative')
_RUNNER = '''import sys
sys.dont_write_bytecode = True
import json, re
from pathlib import Path
from public_recovery.recovery import recover_public
nonce = Path('public_nonce.txt').read_text()
if not re.fullmatch('[0-9a-f]{32}\\n', nonce):
    raise ValueError('A fresh public replay nonce is required')
report = recover_public(Path('input.xlsx'), Path('recovered.xlsx'),
    Path('public_recovery_report.json'), instruction_path=Path('instruction.md'))
print(json.dumps({'declared_business_slots': report['declared_business_slots'],
    'numeric_results_written': report['numeric_results_written'],
    'intentional_policy_blank_results': report['intentional_policy_blank_results'],
    'all_scenarios_feasible': report['all_scenarios_feasible']}), flush=True)
'''
_INSPECT = ('{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"NanoCpus":{{.HostConfig.NanoCpus}},"Memory":{{.HostConfig.Memory}},'
    '"PidsLimit":{{.HostConfig.PidsLimit}},"NetworkMode":{{json .HostConfig.NetworkMode}},'
    '"Privileged":{{json .HostConfig.Privileged}},"CapDrop":{{json .HostConfig.CapDrop}},'
    '"CapAdd":{{json .HostConfig.CapAdd}},"SecurityOpt":{{json .HostConfig.SecurityOpt}},'
    '"Mounts":{{json .Mounts}},"State":{{json .State}},"Cmd":{{json .Config.Cmd}},'
    '"Entrypoint":{{json .Config.Entrypoint}},"WorkingDir":{{json .Config.WorkingDir}},'
    '"User":{{json .Config.User}}}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(path):
    return original._reference(path)


def _read(record):
    require(reference(record['path']) == record, 'An immutable replay artifact changed')
    return json.loads(Path(record['path']).read_text(encoding='utf-8'))


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def public_implementation_recipe():
    result = {'recovery': reference(original.__file__), 'spec': reference(original.spec.__file__),
              'ledger': reference(original.ledger.__file__)}
    require(all(result[name]['sha256'] == digest for name, digest in SOURCE_SHA256.items()),
            'The frozen public-table parser or financial schema/ledger changed')
    return {**result, 'transport': reference(__file__)}


def scoped_public_source(view_version):
    """Only the v3 public account-set exclusion differs from the original AST."""
    require(type(view_version) is int and view_version in (2, 3), 'Only complete v2/v3 scopes are supported')
    recipe = public_implementation_recipe()
    source = Path(recipe['recovery']['path']).read_bytes()
    require(hashlib.sha256(source).hexdigest() == SOURCE_SHA256['recovery'], 'Public parser changed while reading')
    tree = ast.parse(source)
    selector = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'public_forecast_slots')
    matching = [n for n in ast.walk(selector) if isinstance(n, ast.Tuple)
                and all(isinstance(x, ast.Constant) for x in n.elts)
                and tuple(x.value for x in n.elts) == _BASE_EXCLUDED]
    require(len(matching) == 1, 'The exact frozen public account-set selector differs')
    if view_version == 3:
        matching[0].elts.extend(ast.Constant(value=value) for value in _V3_EXCLUDED)
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


def _scoped(view_version):
    module = types.ModuleType('sheets_factory.workbook._heterogeneous_business_public_scope')
    module.__package__ = 'sheets_factory.workbook'
    exec(compile(scoped_public_source(view_version), '<SHA-bound public business parser>', 'exec'), module.__dict__)
    return module


def public_program_files(view_version):
    """Return generic public code only, without compiling or running finance."""
    recipe = public_implementation_recipe()
    return {'run.py': _RUNNER.encode(), 'public_recovery/__init__.py': b'',
        'public_recovery/recovery.py': scoped_public_source(view_version).encode(),
        'public_recovery/heterogeneous_contracts/spec.py': Path(recipe['spec']['path']).read_bytes(),
        'public_recovery/heterogeneous_contracts/ledger.py': Path(recipe['ledger']['path']).read_bytes()}


def inventory(directory):
    root = Path(directory).absolute()
    require(root == root.resolve() and root.is_dir(), 'Use a real replay directory')
    paths = list(root.rglob('*'))
    require(not any(p.is_symlink() for p in paths), 'A replay cannot contain symlinks')
    require(all(p.is_file() or p.is_dir() for p in paths), 'Replay special files are not supported')
    return {p.relative_to(root).as_posix(): reference(p) for p in sorted(paths) if p.is_file()}


def prepare_public_bundle(source, instruction, destination, *, view_version, nonce):
    """Materialize exactly eight public files; no reference parameter exists."""
    source_ref = reference(source)
    require(isinstance(instruction, str) and bool(instruction.strip()), 'A public instruction is required')
    require(type(nonce) is str and re.fullmatch('[0-9a-f]{32}', nonce), 'A complete fresh nonce is required')
    directory = Path(destination).absolute()
    require(directory == directory.resolve() and not directory.exists(), 'Use a fresh nonsymlink replay directory')
    directory.mkdir(mode=0o700)
    shutil.copyfile(source, directory / 'input.xlsx')
    (directory / 'instruction.md').write_text(instruction, encoding='utf-8')
    (directory / 'public_nonce.txt').write_text(nonce + '\n', encoding='utf-8')
    for relative, content in public_program_files(view_version).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(content)
    result = inventory(directory)
    require(set(result) == set(PUBLIC_FILES) and result['input.xlsx']['sha256'] == source_ref['sha256']
            and reference(source) == source_ref, 'The exact public-only eight-file bundle differs')
    return result


def audit_public_output(source, output, *, view_version):
    """Check literal business results and provided cells against public finance.

    This is a shared-Decimal value check, not a formula reconstruction claim.
    No private workbook or binding map is accepted by this function.
    """
    import openpyxl
    parser = _scoped(view_version)
    source_ref, output_ref = reference(source), reference(output)
    initial = openpyxl.load_workbook(source, read_only=True, data_only=False, keep_links=True)
    actual = openpyxl.load_workbook(output, read_only=True, data_only=False, keep_links=True)
    try:
        public = parser._parse_book(initial)
        slots = parser.public_forecast_slots(initial, public)
        require(parser._parse_book(actual) == public, 'The recovered public business primitives changed')
        require(parser.public_forecast_slots(actual, public, require_masked=False) == slots,
                'The recovered complete public account geometry changed')
        targets = {(s['sheet'], openpyxl.utils.get_column_letter(s['column']) + str(s['row'])) for s in slots}
        before, after = parser._values(initial), parser._values(actual)
        require({k: v for k, v in after.items() if k not in targets} == before,
                'A provided cell or an unrelated blank changed')
        forward = parser.ledger.simulate(public)
        require(forward['feasible'] is True and forward['checks']['all_journals_and_financial_bridges_verified'] is True,
                'The public supplied business forecasts are infeasible or unbalanced')
        blanks = 0
        for slot in slots:
            coordinate = openpyxl.utils.get_column_letter(slot['column']) + str(slot['row'])
            observed = after.get((slot['sheet'], coordinate), (None, None, None))[1]
            expected = parser._posted(forward, slot)
            if expected is None:
                require(observed is None, 'A non-applicable result is not an intentional blank')
                blanks += 1
            else:
                require(type(expected) in (int, bool) and parser._integer(observed, slot['scale']) == int(expected),
                        'A public business posting does not match its exact unit/value')
    finally:
        initial.close()
        actual.close()
    require(reference(source) == source_ref and reference(output) == output_ref, 'A workbook changed during the value audit')
    return {'kind': 'heterogeneous_public_business_literal_value_audit', 'version': 1,
        'passed': True, 'input': source_ref, 'output': output_ref, 'view_version': view_version,
        'specification_sha256': parser.spec.canonical_sha256(public), 'business_slots': len(slots),
        'numeric_values_checked': len(slots) - blanks, 'intentional_policy_blanks_checked': blanks,
        'all_public_primitives_and_provided_cells_preserved': True, 'all_labelled_business_slots_checked': True,
        'all_scenarios_feasible': True, 'shared_Decimal_source_audit_implementation': True,
        'third_independent_financial_implementation': False, 'formula_targets_claimed': False,
        'quality_or_difficulty_certified': False}


def _settings(ctx):
    setting = ctx.config[SETTING]
    require(type(setting.get('version')) is int and setting['version'] == 1 and setting.get('enabled') is True,
            'Explicit business-view recovery opt-in is required')
    version = setting.get('view_version')
    require(type(version) is int and version in (2, 3), 'A complete public business scope is required')
    require(setting.get('excluded_entity_fields') == ['cure_open', 'cure_next'] + (list(_V3_EXCLUDED) if version == 3 else []),
            'The explicit business forecast exclusion set differs')
    require(reference(setting['view_module']['path']) == setting['view_module']
            and setting.get('recovery') == reference(__file__), 'The business-view/replay implementation changed')
    recovery = ctx.config.get('recovery', {})
    require(recovery.get('compiler_backend') == BACKEND and type(recovery.get('replay_timeout_seconds')) is int
            and recovery['replay_timeout_seconds'] == REPLAY_SECONDS, 'The public replay backend or operational bound differs')
    from .resource_engine import load_runtime_profile
    record = setting['runtime_profile']
    require(reference(record['path']) == record, 'The pinned runtime profile changed')
    profile = load_runtime_profile(record['path'])
    require(profile['id'] == 'entity_group_large_v2' and profile['image']['id'] == IMAGE
        and profile['docker_resources']['agent'] == {'cpus': 2, 'memory_bytes': 32 * 1024**3, 'pids_limit': 256},
        'This family requires actual 2-CPU/32-GiB/PID256 pinned-image replay')
    return version, profile, record


def _source_binding(ctx):
    from ..task_adapters.heterogeneous_business_modeling import context_proof
    proof = context_proof(ctx)
    version, _, profile = _settings(ctx)
    require(proof['runtime_profile'] == profile and proof['view_version'] == version
        and ctx.data.get('finance_evidence', {}).get('financial_seed_verified') is True,
        'The current business view and source admission must bind the same resource profile/scope')
    require(all({key: reference(ctx.data[name])[key] for key in ('sha256', 'bytes')}
        == {key: proof[name][key] for key in ('sha256', 'bytes')} for name in ('input', 'goal')),
            'The current business input or goal differs from its admitted projection')
    return {key: proof[key] for key in ('source_manifest', 'native_source', 'runtime_profile',
        'view_module', 'view_version', 'view_plan_ref', 'projection_manifest', 'input', 'goal', 'full_D')}


def _command(ctx, directory, nonce):
    _, profile, _ = _settings(ctx)
    resource = profile['docker_resources']['agent']
    return ['docker', 'create', '--name', 'sheetsfactory-business-replay-' + nonce,
        '--user', '0', '--network', 'none', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
        '--security-opt', 'no-new-privileges', '--cpus', str(resource['cpus']), '--memory', str(resource['memory_bytes']),
        '--pids-limit', str(resource['pids_limit']), '--volume', str(Path(directory).resolve()) + ':/app:rw',
        '--workdir', '/app', '--entrypoint', '/usr/bin/python3', IMAGE, '/app/run.py']


def _host_valid(actual, container_id, directory, profile):
    resource = profile['docker_resources']['agent']
    mounts = actual.get('Mounts', [])
    return (type(container_id) is str and re.fullmatch('[0-9a-f]{64}', container_id) is not None
        and actual.get('Id') == container_id and actual.get('Image') == IMAGE
        and type(actual.get('NanoCpus')) is int and actual['NanoCpus'] == resource['cpus'] * 10**9
        and type(actual.get('Memory')) is int and actual['Memory'] == resource['memory_bytes']
        and type(actual.get('PidsLimit')) is int and actual['PidsLimit'] == resource['pids_limit']
        and actual.get('NetworkMode') == 'none' and actual.get('Privileged') is False
        and actual.get('CapDrop') == ['ALL'] and actual.get('CapAdd') == ['CAP_DAC_OVERRIDE']
        and actual.get('SecurityOpt') == ['no-new-privileges'] and actual.get('User') == '0'
        and actual.get('Entrypoint') == ['/usr/bin/python3'] and actual.get('Cmd') == ['/app/run.py']
        and actual.get('WorkingDir') == '/app' and len(mounts) == 1
        and mounts[0].get('Type') == 'bind' and mounts[0].get('RW') is True
        and mounts[0].get('Source') == str(Path(directory).resolve()) and mounts[0].get('Destination') == '/app')


def _execute_replay(ctx, directory, attempt, result):
    from ..core.audit import utcnow
    _, profile, profile_ref = _settings(ctx)
    replay = result['replay']
    command = _command(ctx, directory, replay['nonce'])
    replay.update(command=command, runtime_profile=profile_ref, actual_resources_verified=False,
        operational_timeout_seconds=REPLAY_SECONDS, operational_replay_budget_is_solver_tool_budget=False,
        started_at=utcnow(), completed=False)
    _write(attempt / 'replay_started.json', dict(replay))
    owned = None
    try:
        created = subprocess.run(command, capture_output=True, text=True, timeout=30)
        _write(attempt / 'create_result.json', {'returncode': created.returncode, 'stdout': created.stdout, 'stderr': created.stderr})
        require(created.returncode == 0 and re.fullmatch('[0-9a-f]{64}', created.stdout.strip()),
                'Creation did not return a complete owned container ID')
        owned = created.stdout.strip()
        replay['container_id'] = owned
        def inspect_owned(name):
            completed = subprocess.run(['docker', 'inspect', owned, '--format', _INSPECT], capture_output=True, text=True, timeout=30)
            require(completed.returncode == 0, 'The owned public container could not be inspected')
            actual = json.loads(completed.stdout)
            replay[name] = _write(attempt / (name + '.json'), actual)
            require(_host_valid(actual, owned, directory, profile), 'The actual public container resources or isolation differ')
            return actual
        inspect_owned('host_before')
        replay['actual_resources_verified'] = True
        with (attempt / 'replay.stdout').open('xb') as stdout, (attempt / 'replay.stderr').open('xb') as stderr:
            completed = subprocess.run(['docker', 'start', '--attach', owned], stdout=stdout, stderr=stderr, timeout=REPLAY_SECONDS)
        replay['returncode'] = completed.returncode
        after = inspect_owned('host_after')
        require(completed.returncode == 0 and after.get('State', {}).get('Status') == 'exited'
            and type(after['State'].get('ExitCode')) is int and after['State']['ExitCode'] == 0
            and after['State'].get('OOMKilled') is False, 'The isolated public program did not exit normally')
        final = inventory(directory)
        require(set(final) == set(PUBLIC_FILES) | set(GENERATED_FILES)
            and all(final[name] == record for name, record in replay['initial_files'].items()),
            'The held-out public input, instruction, code or nonce changed, or extra files appeared')
        replay.update(final_files=final, completed=True, public_information_unchanged=True)
    finally:
        if owned is not None:
            try:
                removed = subprocess.run(['docker', 'rm', '--force', owned], capture_output=True, text=True, timeout=30)
                replay['cleanup'] = {'owned_full_id': owned, 'returncode': removed.returncode}
            except Exception as error:
                replay['cleanup'] = {'owned_full_id': owned, 'returncode': None, 'error_type': type(error).__name__}
        else:
            replay['cleanup_skipped_no_owned_container'] = True
        replay['finished_at'] = utcnow()
        replay['terminal'] = _write(attempt / 'replay_terminal.json', dict(replay))
    require(replay.get('cleanup') == {'owned_full_id': owned, 'returncode': 0}, 'Owned replay cleanup did not complete')


def _artifacts(ctx, result):
    work, replay = Path(result['workspace']), Path(result['replay']['directory'])
    attempt = Path(result['attempt_record_path']).parent
    return {'workspace_input': work / 'input.xlsx', 'workspace_instruction': work / 'instruction.md',
        'workspace_profile': work / 'public_profile.json', 'workspace_program': work / 'run.py',
        **{'replay/' + name: replay / name for name in (*PUBLIC_FILES, *GENERATED_FILES)},
        'host_before': attempt / 'host_before.json', 'host_after': attempt / 'host_after.json',
        'replay_terminal': attempt / 'replay_terminal.json',
        'resource_audit': attempt / 'value_audits.json', 'stability': attempt / 'stability.json',
        'recovered_pass1': attempt / 'calculated_pass1.xlsx', 'attempt_recovered': attempt / 'recovered.xlsx',
        'recovered': ctx.revision_dir / 'private/recovered.xlsx'}


def _binding(ctx, result):
    return {'version': 1, 'task_id': ctx.task_id, 'revision': ctx.revision,
        'task_revision_hash': ctx.data.get('revision_hash'), 'input': reference(ctx.data['input']),
        'goal': reference(ctx.data['goal']), 'instruction_sha256': hashlib.sha256(ctx.data['instruction'].encode()).hexdigest(),
        'source': _source_binding(ctx), 'implementation': reference(__file__),
        'public_recipe': public_implementation_recipe(), 'runtime_profile': _settings(ctx)[2],
        'artifacts': {name: reference(path) for name, path in _artifacts(ctx, result).items()},
        'resource_recalculations': result['resource_recalculations']}


def _resource_valid(record, source, destination, profile, profile_ref):
    from . import resource_engine
    resource = profile['docker_resources']['source']
    value = _read(record)
    return (value.get('kind') == 'resource_bound_libreoffice_call' and type(value.get('version')) is int
        and value['version'] == 1 and value.get('role') == 'source'
        and value.get('status') == 'completed' and value.get('actual_resources_verified') is True
        and value.get('source') == reference(source) and value.get('output') == reference(destination)
        and value.get('destination') == str(Path(destination).resolve()) and value.get('image_id') == IMAGE
        and value.get('profile') == profile_ref and value.get('implementation') == reference(resource_engine.__file__)
        and value.get('upstream_engine') == reference(resource_engine.original_engine.__file__)
        and value.get('profile_canonical_sha256') == hashlib.sha256(json.dumps(profile, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        and value.get('requested_resources') == resource and value.get('workbook_file_timeout_seconds') == 600
        and re.fullmatch('[0-9a-f]{64}', value.get('container_id', '')) is not None
        and value.get('actual_resources') == {'cpus_nanoseconds': resource['cpus'] * 10**9,
            'memory_bytes': resource['memory_bytes'], 'pids_limit': resource['pids_limit']})


def _execution_valid(ctx, result):
    from ..nodes.quality import _recovery_local_file
    from .heterogeneous_contracts.validate import compare_typed_caches
    version, profile, profile_ref = _settings(ctx)
    replay = result['replay']
    directory = Path(replay['directory'])
    nonce = replay['nonce']
    require(re.fullmatch('[0-9a-f]{32}', nonce) and directory == ctx.revision_dir / ('recovery_replay-' + nonce),
            'The fresh replay directory/nonce binding differs')
    require(result['compiler_backend'] == BACKEND and result['replay_timeout_seconds'] == REPLAY_SECONDS
        and result['public_information_only'] is True and result['view_version'] == version
        and result['compiler'] == {'code': _RUNNER, 'is_llm_attempt': False,
            'public_recipe': public_implementation_recipe(), 'assumptions_added': [], 'unresolved_questions': [],
            'shared_Decimal_source_audit_implementation': True, 'third_independent_financial_implementation': False,
            'independent_from_native_Excel_formulas': True, 'literal_business_targets': True},
        'The explicit public program/implementation claims differ')
    require(result.get('program') == _RUNNER and replay.get('completed') is True
        and replay.get('actual_resources_verified') is True and type(replay.get('returncode')) is int
        and replay['returncode'] == 0 and replay.get('runtime_profile') == profile_ref
        and replay.get('command') == _command(ctx, directory, nonce)
        and replay.get('cleanup') == {'owned_full_id': replay['container_id'], 'returncode': 0},
        'Actual current-revision replay evidence is incomplete')
    artifacts = _artifacts(ctx, result)
    require(all(_recovery_local_file(path, ctx) for name, path in artifacts.items() if name != 'recovered'),
            'A witness artifact escapes this revision')
    require(reference(artifacts['workspace_input']) == {**reference(ctx.data['input']), 'path': str(artifacts['workspace_input'].resolve())}
        and artifacts['workspace_instruction'].read_bytes() == ctx.data['instruction'].encode()
        and artifacts['workspace_program'].read_text() == _RUNNER
        and artifacts['workspace_profile'].read_text() == json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False),
        'The public workspace differs from the current task')
    terminal = _read(replay['terminal'])
    require(terminal == {key: value for key, value in replay.items() if key != 'terminal'}, 'The immutable replay terminal differs')
    initial = replay['initial_files']
    require(set(initial) == set(PUBLIC_FILES) and replay.get('final_files') == inventory(directory)
        and set(replay['final_files']) == set(PUBLIC_FILES) | set(GENERATED_FILES)
        and all(replay['final_files'][name] == record for name, record in initial.items()), 'Public-only mount inventory changed')
    expected_code = public_program_files(version)
    require(all((directory / name).read_bytes() == content for name, content in expected_code.items())
        and reference(directory / 'input.xlsx')['sha256'] == reference(ctx.data['input'])['sha256']
        and (directory / 'instruction.md').read_bytes() == ctx.data['instruction'].encode()
        and (directory / 'public_nonce.txt').read_text() == nonce + '\n', 'Held-out public code/input/nonce identities differ')
    require(all(_host_valid(_read(replay[name]), replay['container_id'], directory, profile) for name in ('host_before', 'host_after')),
            'The actual before/after resources or isolation differ')
    state = _read(replay['host_after'])['State']
    require(state.get('Status') == 'exited' and type(state.get('ExitCode')) is int and state['ExitCode'] == 0
            and state.get('OOMKilled') is False, 'The public process did not complete successfully')
    report = _read(reference(directory / 'public_recovery_report.json'))
    require(all(report.get(key) == {**reference(directory / name), 'path': '/app/' + name}
                for key, name in [('input', 'input.xlsx'), ('instruction', 'instruction.md'), ('output', 'recovered.xlsx')])
        and report.get('backend') == BACKEND and report.get('all_labelled_forecasts_written') is True
        and report.get('shared_Decimal_source_audit_implementation') is True
        and report.get('third_independent_financial_implementation') is False
        and report.get('private_goal_specification_bindings_or_parent_plan_parameters_supported') is False,
        'The public recovery report claims the wrong data or financial implementation')
    # Container paths in its report are /app paths. Only byte identities, not
    # host path identity, bind those three records at the host boundary.
    resources = result['resource_recalculations']
    require(len(resources) == 2 and _resource_valid(resources[0], directory / 'recovered.xlsx', artifacts['recovered_pass1'], profile, profile_ref)
        and _resource_valid(resources[1], artifacts['recovered_pass1'], artifacts['attempt_recovered'], profile, profile_ref),
        'Two actual resource-bound recalculations are required')
    audits = [audit_public_output(ctx.data['input'], path, view_version=version)
        for path in (directory / 'recovered.xlsx', artifacts['recovered_pass1'], artifacts['attempt_recovered'])]
    require(_read(reference(artifacts['resource_audit'])) == audits, 'The complete literal financial audits differ')
    stability = [compare_typed_caches(directory / 'recovered.xlsx', artifacts['recovered_pass1']),
                 compare_typed_caches(artifacts['recovered_pass1'], artifacts['attempt_recovered'])]
    require(_read(reference(artifacts['stability'])) == stability and all(s.get('passed') is True
        and s.get('entire_value_union_checked') is True and s.get('typed_value_mismatches') == 0 for s in stability),
        'The complete public values changed during actual recalculation')
    return True


def valid_heterogeneous_business_recovery_witness(ctx, candidate):
    """Verify current immutable execution/resource/value/full-D evidence."""
    from ..nodes.quality import _recovery_local_file
    from ..evaluation.streaming_delta import compare_workbooks
    try:
        if not isinstance(candidate, dict) or candidate.get('verified') is not True:
            return False
        if (candidate.get('task_revision_hash') != ctx.data.get('revision_hash')
            or candidate.get('usage_calls') != [] or candidate.get('usage_attribution') != 'not_applicable_programmatic'):
            return False
        record = Path(candidate['attempt_record_path'])
        checksum = record.with_name('attempt.sha256')
        require(record.parent.parent.absolute() == (ctx.revision_dir / 'private/recovery_attempts').absolute()
            and _recovery_local_file(record, ctx) and _recovery_local_file(checksum, ctx), 'The immutable attempt is outside its revision')
        actual = reference(record)
        require(candidate.get('attempt_record_sha256') == actual['sha256'] and checksum.read_text().strip() == actual['sha256']
            and json.loads(record.read_text()) == {key: value for key, value in candidate.items() if key != 'attempt_record_sha256'},
            'The complete immutable attempt or checksum differs')
        require(_execution_valid(ctx, candidate) and candidate.get('witness_binding') == _binding(ctx, candidate),
                'The public replay witness does not bind this task')
        artifacts = _artifacts(ctx, candidate)
        require(reference(artifacts['attempt_recovered'])['sha256'] == reference(artifacts['recovered'])['sha256'],
                'The canonical recovered copy differs')
        comparison = compare_workbooks(ctx.data['input'], ctx.data['goal'], artifacts['recovered'])
        return comparison.get('reward') == 1 and comparison == candidate.get('comparison')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        return False


class HeterogeneousBusinessRecoveryNode(RecoveryNode):
    node_id = 'independent_recovery'

    def execute(self, ctx):
        from ..core.audit import utcnow
        from ..core.node import CooperativeCancelled
        from ..nodes import quality as normal
        from ..evaluation.streaming_delta import compare_workbooks
        from .heterogeneous_contracts.validate import compare_typed_caches
        if ctx.config.get(SETTING) is None:
            return super().execute(ctx)
        require(normal.validate_reference_policy_selection(ctx.config) == 'independent_public_recovery',
                'The explicit business family requires public reconstruction')
        version, _, _ = _settings(ctx)
        _source_binding(ctx)
        saved = ctx.revision_dir / 'private/independent_recovery.json'
        if saved.is_file():
            candidate = json.loads(saved.read_text())
            if valid_heterogeneous_business_recovery_witness(ctx, candidate):
                return {'recovery': candidate}
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
            'task_revision_hash': ctx.data.get('revision_hash'), 'compiler_backend': BACKEND,
            'replay_timeout_seconds': REPLAY_SECONDS, 'view_version': version}
        try:
            work = normal.prepare_workspace(ctx, 'recovery_public')
            result['workspace'] = str(work)
            (work / 'public_profile.json').write_text(json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False))
            (work / 'run.py').write_text(_RUNNER)
            result['program'] = _RUNNER
            result['compiler'] = {'code': _RUNNER, 'is_llm_attempt': False,
                'public_recipe': public_implementation_recipe(), 'assumptions_added': [], 'unresolved_questions': [],
                'shared_Decimal_source_audit_implementation': True, 'third_independent_financial_implementation': False,
                'independent_from_native_Excel_formulas': True, 'literal_business_targets': True}
            nonce = uuid.uuid4().hex
            replay = ctx.revision_dir / ('recovery_replay-' + nonce)
            initial = prepare_public_bundle(ctx.data['input'], ctx.data['instruction'], replay, view_version=version, nonce=nonce)
            result['replay'] = {'directory': str(replay), 'nonce': nonce, 'initial_files': initial,
                'returncode': None, 'fresh_network_disabled_container': True}
            _execute_replay(ctx, replay, attempt, result)
            # Private reference scoring occurs only after successful public
            # process exit, unchanged mount verification and owned cleanup.
            audits = [audit_public_output(ctx.data['input'], replay / 'recovered.xlsx', view_version=version)]
            resources = []
            source = replay / 'recovered.xlsx'
            for destination in (attempt / 'calculated_pass1.xlsx', attempt / 'recovered.xlsx'):
                calculated = ctx.engine.recalculate(source, destination)
                require(Path(calculated).resolve() == destination.resolve(), 'The recovery calculation returned another output')
                matches = [r for r in ctx.engine.metadata().get('actual_resource_receipts', [])
                           if _read(r).get('output') == reference(destination)]
                require(len(matches) == 1, 'The actual recovered workbook needs exactly one resource receipt')
                resources.append(matches[0])
                audits.append(audit_public_output(ctx.data['input'], destination, view_version=version))
                source = destination
            result['resource_recalculations'] = resources
            _write(attempt / 'value_audits.json', audits)
            stability = [compare_typed_caches(replay / 'recovered.xlsx', attempt / 'calculated_pass1.xlsx'),
                         compare_typed_caches(attempt / 'calculated_pass1.xlsx', attempt / 'recovered.xlsx')]
            _write(attempt / 'stability.json', stability)
            require(_execution_valid(ctx, result), 'The current resource/value/public-only evidence failed')
            comparison = compare_workbooks(ctx.data['input'], ctx.data['goal'], attempt / 'recovered.xlsx')
            result['comparison'] = comparison
            if comparison.get('reward') == 1:
                shutil.copy2(attempt / 'recovered.xlsx', ctx.revision_dir / 'private/recovered.xlsx')
                result['witness_binding'] = _binding(ctx, result)
                result['verified'] = True
        except CooperativeCancelled:
            result.update(status='cancelled', error='Explicit cooperative stop; no recovery certified')
            raise
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error))
        finally:
            result.update(usage_calls=[], usage_attribution='not_applicable_programmatic', finished_at=utcnow())
            result.setdefault('status', 'verified' if result['verified'] else 'unverified')
            raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
            with (attempt / 'attempt.json').open('xb') as stream:
                stream.write(raw)
            with (attempt / 'attempt.sha256').open('x') as stream:
                stream.write(hashlib.sha256(raw).hexdigest() + '\n')
            (attempt / 'attempt.json').chmod(0o444)
            (attempt / 'attempt.sha256').chmod(0o444)
            result['attempt_record_sha256'] = hashlib.sha256(raw).hexdigest()
            ctx.save('independent_recovery.json', result)
        return {'recovery': result}
