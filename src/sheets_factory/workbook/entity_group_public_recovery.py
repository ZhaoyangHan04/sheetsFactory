"""Public-only fixed-plan recovery, with an explicitly shared formula compiler.

The integer financial ledger is independent of Excel. Formula definitions and
row layout deliberately reuse the source's public compiler. This establishes
public reproducibility, not a second independently authored formula engine.
Only the public workbook, public instruction, program and nonce enter replay.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import zipfile

from ..nodes.quality import RecoveryNode

BACKEND = 'entity_group_public_integer_shared_compiler'
REPLAY_SECONDS = 7200
PUBLIC_MODULE_SHA256 = {
    'spec.py': 'f98ae807d392bcfe79ef9ae7d9df12e226eb55ddc53fd0e5b4579835715fa509',
    'ledger.py': 'db6226fe1a97c3f9fb1612137934ee04148358375e07968f8258ea13031a5eaa',
    'excel.py': '65049b4749c269b01efeed0a10d3f06bd50638396ebd8967bd7132c076733da4',
    'validate.py': '84fde5df6587422f985a5e78ce148bade786bafdfc1762c98cb6e12abcc43ad9',
}
PUBLIC_FILES = ('input.xlsx', 'instruction.md', 'recovery.py', 'public_nonce.txt')
GENERATED_FILES = ('output.xlsx', 'public_recovery_report.json', 'public_definitions.json',
                   'public_forward_ledger.json', 'public_specification.json')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'Duplicate public contract key: ' + key)
        result[key] = value
    return result


def _flatten(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten(child, (*path, index))
    else:
        yield '/'.join(map(str, path)), value


def _ordered_public(value, ranks, path=()):
    """Recover insertion order only from the public primitive-path row order."""
    if isinstance(value, list):
        return [_ordered_public(child, ranks, (*path, index)) for index, child in enumerate(value)]
    if not isinstance(value, dict):
        return value
    def first(key):
        leaves = list(_flatten(value[key], (*path, key)))
        return min((ranks[label] for label, _ in leaves), default=len(ranks))
    return {key: _ordered_public(value[key], ranks, (*path, key)) for key in sorted(value, key=first)}


def read_public_spec(book):
    """Read complete typed JSON, explicit policy and labelled literals only."""
    from .entity_group.spec import PHASES, RULES, load_spec
    _require(all(name in book for name in ('Group Rules', 'Group Contract', 'Group Inputs')),
             'The public fixed-plan contract worksheets are missing')
    chunks = []
    sheet = book['Group Contract']
    for row in range(2, sheet.max_row + 1):
        label, cell = sheet.cell(row, 1), sheet.cell(row, 2)
        _require(label.value == 'JSON part ' + str(len(chunks) + 1)
                 and cell.data_type != 'f' and type(cell.value) is str,
                 'Public contract chunks must be ordered labelled JSON literals')
        chunks.append(cell.value)
    _require(bool(chunks), 'The complete public financial contract is empty')
    public = load_spec(json.loads(''.join(chunks), object_pairs_hook=_unique_json,
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite public JSON'))))
    rules = book['Group Rules']
    expected_rules = [('Phase', text) for text in PHASES] + [('Rule', text) for text in RULES]
    _require(rules.max_row == len(expected_rules) + 1
             and [(rules.cell(row, 1).value, rules.cell(row, 2).value)
                  for row in range(2, rules.max_row + 1)] == expected_rules,
             'The public financial phase order or policy differs')
    expected = dict(_flatten(public))
    inputs, provided, labels = book['Group Inputs'], {}, []
    for row in range(2, inputs.max_row + 1):
        name, cell = inputs.cell(row, 1).value, inputs.cell(row, 2)
        _require(type(name) is str and name in expected and name not in provided and cell.data_type != 'f',
                 'A public primitive label is unknown, duplicated or calculated')
        value, actual = expected[name], cell.value
        if type(value) is bool:
            matched = type(actual) in (int, float) and actual == int(value)
        elif type(value) is int:
            matched = type(actual) in (int, float) and actual == value
        else:
            matched = type(actual) is type(value) and actual == value
        _require(matched, 'A labelled public primitive differs from its exact JSON value: ' + name)
        provided[name] = actual
        labels.append(name)
    _require(set(provided) == set(expected), 'The public primitive table is incomplete')
    ordered = _ordered_public(public, {name: index for index, name in enumerate(labels)})
    _require([name for name, _ in _flatten(ordered)] == labels,
             'The public primitive paths do not form the supplied complete contiguous tree')
    return load_spec(ordered)


def _compare_public_layout(original, rebuilt, formula_signature):
    _require(original.sheetnames == rebuilt.sheetnames, 'Public worksheet names or order changed')
    different = 0
    for source, expected in zip(original, rebuilt):
        actual_cells = {key: cell for key, cell in source._cells.items() if cell.value is not None}
        expected_cells = {key: cell for key, cell in expected._cells.items() if cell.value is not None}
        _require(set(actual_cells) == set(expected_cells), 'The public nonempty-cell boundary or row map differs')
        for key, wanted in expected_cells.items():
            actual = actual_cells[key]
            if wanted.data_type == 'f':
                _require(actual.data_type == 'f', 'An existing financial formula was replaced by a literal')
                different += formula_signature(actual.value) != formula_signature(wanted.value)
            else:
                numeric = type(wanted.value) is int and type(actual.value) in (int, float)
                _require((numeric or type(actual.value) is type(wanted.value)) and actual.value == wanted.value,
                         'An existing public label or provided literal differs')
    return different


def recover_public(source, destination, report_path=None, *, instruction_path=None):
    """Regenerate from public primitives; no private-artifact argument exists."""
    import openpyxl
    from .entity_group.excel import emit_entity_group_workbook
    from .entity_group.ledger import simulate
    from .entity_group.validate import expected_values, formula_signature
    source, destination = Path(source), Path(destination)
    instruction = Path(instruction_path) if instruction_path is not None else source.with_name('instruction.md')
    _require(source.resolve() != destination.resolve(), 'Recovery cannot overwrite the public input')
    _require(source.is_file() and not source.is_symlink() and instruction.is_file()
             and not instruction.is_symlink() and bool(instruction.read_text().strip()),
             'The regular public input and nonempty public instruction are required')
    _require(not destination.exists(), 'Recovery output must be fresh')
    original = openpyxl.load_workbook(source, keep_links=False)
    rebuilt = openpyxl.Workbook()
    rebuilt.remove(rebuilt.active)
    try:
        public = read_public_spec(original)
        ledger = simulate(public)
        _require(ledger['feasible'] is True and ledger['optimisation_performed'] is False,
                 'The public supplied fixed plan is financially infeasible')
        # These definitions are regenerated here from public inputs. No source
        # bindings file, faulty-cell list or reference workbook is accepted.
        definitions = emit_entity_group_workbook(rebuilt, public, max_formulas=2_000_000,
                                                  allow_production=public['dimension_mode'] == 'production')
        repaired = _compare_public_layout(original, rebuilt, formula_signature)
        audit = expected_values(public, ledger, definitions)
        audit.pop('values')
        _require(audit['all_independent_journal_fields_covered'] is True,
                 'The independent public ledger did not cover the complete financial graph')
        rebuilt.save(destination)
        for name, value in (('public_definitions.json', definitions), ('public_forward_ledger.json', ledger),
                            ('public_specification.json', public)):
            with (destination.parent / name).open('x') as stream:
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        report = {'kind': 'entity_group_public_reconstruction', 'version': 1,
            'public_information_only': True, 'source_sha256': _sha(source),
            'instruction_sha256': _sha(instruction), 'output_sha256': _sha(destination),
            'fixed_plan': public['fixed_plan'], 'optimisation_performed': False,
            'shared_excel_compiler': True, 'independent_second_formula_engine': False,
            'independent_integer_financial_ledger': True,
            'private_goal_source_bindings_or_fault_list_read': False,
            'different_formula_definitions_reconstructed': repaired,
            'complete_public_row_layout_verified': True, 'independent_field_audit': audit,
            'assumptions_added': [], 'unresolved_questions': [],
            'actual_LO_cache_audit_pending': True, 'quality_or_difficulty_certified': False}
        if report_path is not None:
            with Path(report_path).open('x') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return report
    finally:
        original.close()
        rebuilt.close()


def _reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': _sha(path), 'bytes': path.stat().st_size}


def public_implementation_recipe():
    base = Path(__file__).with_name('entity_group')
    result = {}
    for name, digest in PUBLIC_MODULE_SHA256.items():
        path = base / name
        _require(_sha(path) == digest, 'The public financial compiler/ledger recipe changed: ' + name)
        result[name] = _reference(path)
    return result


def compile_public_entity_group_recovery():
    """Bundle fixed public code only; no task data or reference is embedded."""
    recipe = public_implementation_recipe()
    own = ast.parse(Path(__file__).read_text())
    names = {'_require', '_sha', '_unique_json', '_flatten', '_ordered_public', 'read_public_spec',
             '_compare_public_layout', 'recover_public'}
    body = [node for node in own.body if isinstance(node, ast.FunctionDef) and node.name in names]
    runtime = ('from __future__ import annotations\nimport hashlib,json\nfrom pathlib import Path\n'
               + ast.unparse(ast.Module(body=body, type_ignores=[])) + '\n')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        def write(name, content):
            entry = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
        for name in ('sheets_factory/__init__.py', 'sheets_factory/workbook/__init__.py',
                     'sheets_factory/workbook/entity_group/__init__.py'):
            write(name, '')
        for name, reference in recipe.items():
            write('sheets_factory/workbook/entity_group/' + name, Path(reference['path']).read_text())
        write('sheets_factory/workbook/entity_group_public_recovery.py', runtime)
    encoded = base64.b64encode(data.getvalue()).decode()
    return ('import base64,io,sys,tempfile,zipfile\nfrom pathlib import Path\n'
        'directory=tempfile.mkdtemp(prefix="entity-public-")\n'
        'with zipfile.ZipFile(io.BytesIO(base64.b64decode(' + repr(encoded) + '))) as archive: archive.extractall(directory)\n'
        'sys.path.insert(0,directory)\n'
        'from sheets_factory.workbook.entity_group_public_recovery import recover_public\n'
        'recover_public(Path("input.xlsx"),Path("output.xlsx"),Path("public_recovery_report.json"),'
        'instruction_path=Path("instruction.md"))\n')


def _profile(ctx):
    """Consume an explicitly bound profile, including future capacity versions."""
    import yaml
    from ..task_adapters.public_workbook_scope import checked_bytes
    record = ctx.config['entity_group_task']['runtime_profile']
    profile = yaml.safe_load(checked_bytes(record))
    _require(isinstance(profile, dict) and profile.get('kind') == 'workbook_runtime_resource_profile'
             and type(profile.get('version')) is int and profile['version'] >= 1
             and type(profile.get('id')) is str and bool(profile['id'])
             and re.fullmatch(r'sha256:[0-9a-f]{64}', profile.get('image', {}).get('id', '')),
             'A SHA-bound explicit resource profile and immutable image are required')
    resources = profile.get('docker_resources', {})
    _require(set(resources) == {'source', 'agent', 'verifier'}
             and resources['source'] == resources['agent'] == resources['verifier'],
             'Source, agent and verifier must have the same explicit resources')
    r = resources['source']
    _require(type(r.get('cpus')) is int and r['cpus'] == 2
             and type(r.get('memory_bytes')) is int and 8 * 1024**3 <= r['memory_bytes'] <= 128 * 1024**3
             and r['memory_bytes'] % 1024**3 == 0
             and type(r.get('pids_limit')) is int and 64 <= r['pids_limit'] <= 4096,
             'The explicit replay capacity must be bounded and cannot silently fall back')
    _require(profile.get('timeouts') == {'workbook_file_seconds': 600, 'verifier_total_seconds': 2400}
             and profile.get('solver_tool_budget') == {'seconds': 1800, 'strict_less_than': True,
                'exclude_model_response_time': True, 'parallel_executions': 'sum'},
             'Recalculation and solver-tool budgets are separate and unchanged')
    _require(profile['solver_tool_budget']['strict_less_than'] is True
             and profile['solver_tool_budget']['exclude_model_response_time'] is True
             and profile.get('limits', {}).get('truncate') is False
             and profile['limits'].get('source_physical_formulas') == 2_000_000,
             'The full public financial scope and strict tool budget cannot be relaxed')
    return profile, record


def _replay_command(ctx, replay, nonce):
    profile, _ = _profile(ctx)
    r = profile['docker_resources']['agent']
    return ['docker', 'create', '--name', 'sheetsfactory-entity-recovery-' + nonce,
        '--user', '0', '--network', 'none', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
        '--security-opt', 'no-new-privileges', '--cpus', str(r['cpus']), '--memory', str(r['memory_bytes']),
        '--pids-limit', str(r['pids_limit']), '--volume', str(Path(replay).resolve()) + ':/workspace:rw',
        '--workdir', '/workspace', '--entrypoint', '/usr/bin/python3',
        profile['image']['id'], '/workspace/recovery.py']


def _host_resources_valid(actual, profile, replay, container_id):
    r = profile['docker_resources']['agent']
    mounts = actual.get('Mounts', [])
    return (re.fullmatch(r'[0-9a-f]{64}', container_id) is not None
        and actual.get('Id') == container_id and actual.get('Image') == profile['image']['id']
        and type(actual.get('NanoCpus')) is int and actual['NanoCpus'] == r['cpus'] * 10**9
        and type(actual.get('Memory')) is int and actual['Memory'] == r['memory_bytes']
        and type(actual.get('PidsLimit')) is int and actual['PidsLimit'] == r['pids_limit']
        and actual.get('NetworkMode') == 'none' and actual.get('Cmd') == ['/workspace/recovery.py']
        and actual.get('Entrypoint') == ['/usr/bin/python3'] and actual.get('WorkingDir') == '/workspace'
        and actual.get('User') == '0' and len(mounts) == 1
        and mounts[0].get('Type') == 'bind' and mounts[0].get('RW') is True
        and mounts[0].get('Source') == str(Path(replay).resolve()) and mounts[0].get('Destination') == '/workspace')


def _execute_replay(ctx, replay, attempt, result):
    profile, binding = _profile(ctx)
    nonce = result['replay']['nonce']
    command = _replay_command(ctx, replay, nonce)
    name = command[command.index('--name') + 1]
    result['replay'].update(command=command, runtime_profile=binding,
        actual_resources_verified=False, operational_timeout_seconds=REPLAY_SECONDS,
        operational_replay_budget_is_solver_tool_budget=False)
    owned_id = None
    try:
        created = subprocess.run(command, capture_output=True, text=True, timeout=30)
        (attempt / 'create.stdout.txt').write_text(created.stdout)
        (attempt / 'create.stderr.txt').write_text(created.stderr)
        _require(created.returncode == 0, 'Recovery container creation failed: ' + created.stderr[-2000:])
        container_id = created.stdout.strip()
        _require(re.fullmatch(r'[0-9a-f]{64}', container_id) is not None,
                 'Container creation did not return a complete owned container ID')
        owned_id = container_id
        result['replay']['container_id'] = container_id
        template = ('{"Id":{{json .Id}},"Image":{{json .Image}},"NanoCpus":{{.HostConfig.NanoCpus}},'
            '"Memory":{{.HostConfig.Memory}},"PidsLimit":{{.HostConfig.PidsLimit}},'
            '"NetworkMode":{{json .HostConfig.NetworkMode}},"Mounts":{{json .Mounts}},'
            '"Cmd":{{json .Config.Cmd}},"Entrypoint":{{json .Config.Entrypoint}},'
            '"WorkingDir":{{json .Config.WorkingDir}},"User":{{json .Config.User}}}')
        inspected = subprocess.run(['docker', 'inspect', owned_id, '--format', template],
                                   capture_output=True, text=True, timeout=30)
        (attempt / 'inspect.stdout.txt').write_text(inspected.stdout)
        (attempt / 'inspect.stderr.txt').write_text(inspected.stderr)
        _require(inspected.returncode == 0, 'Cannot inspect the actual public-recovery container')
        actual = json.loads(inspected.stdout)
        with (attempt / 'replay_host_config.json').open('x') as stream:
            json.dump(actual, stream, indent=2)
        result['replay']['host_config'] = _reference(attempt / 'replay_host_config.json')
        _require(_host_resources_valid(actual, profile, replay, container_id),
                 'Actual public-recovery container resources, image, network or mount differ')
        result['replay']['actual_resources_verified'] = True
        try:
            execution = subprocess.run(['docker', 'start', '--attach', owned_id],
                                       capture_output=True, text=True, timeout=REPLAY_SECONDS)
        except subprocess.TimeoutExpired as error:
            def partial(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
            (attempt / 'replay.stdout.txt').write_text(partial(error.stdout))
            (attempt / 'replay.stderr.txt').write_text(partial(error.stderr))
            result['replay']['error_type'] = 'TimeoutExpired'
            raise
        (attempt / 'replay.stdout.txt').write_text(execution.stdout)
        (attempt / 'replay.stderr.txt').write_text(execution.stderr)
        result['replay'].update(returncode=execution.returncode,
            stdout_file=str(attempt / 'replay.stdout.txt'), stderr_file=str(attempt / 'replay.stderr.txt'))
        _require(execution.returncode == 0, 'Public recovery failed: ' + execution.stderr[-2000:])
    finally:
        if owned_id is None:
            result['replay'].update(cleanup_returncode=None, cleanup_skipped_no_owned_container=True)
        else:
            try:
                removed = subprocess.run(['docker', 'rm', '--force', owned_id], capture_output=True, text=True, timeout=30)
                result['replay']['cleanup_returncode'] = removed.returncode
            except Exception as error:
                result['replay'].update(cleanup_returncode=None, cleanup_error_type=type(error).__name__, cleanup_error=str(error))
    _require(result['replay']['cleanup_returncode'] == 0, 'The owned public replay container was not removed')


def _read_reference(record):
    from ..task_adapters.public_workbook_scope import checked_bytes
    return json.loads(checked_bytes(record))


def _extra_artifacts(ctx, result):
    replay = Path(result['replay']['directory'])
    attempt = Path(result['attempt_record_path']).parent
    return {'replay_instruction': replay / 'instruction.md', 'replay_nonce': replay / 'public_nonce.txt',
        **{name: replay / name for name in GENERATED_FILES},
        'host_config': attempt / 'replay_host_config.json', 'cache_audit': attempt / 'public_cache_audit.json'}


def _witness_binding(ctx, result):
    from ..nodes import quality as normal
    return {**normal._recovery_binding(ctx, result), 'version': 2,
        'public_replay_artifacts': {key: _reference(path) for key, path in _extra_artifacts(ctx, result).items()},
        'runtime_profile': result['replay']['runtime_profile'], 'public_recipe': public_implementation_recipe(),
        'implementation': _reference(__file__), 'resource_recalculation': result['resource_recalculation']}


def _public_execution_valid(ctx, result):
    from ..nodes import quality as normal
    from . import resource_engine
    compiler, replay = result.get('compiler', {}), result.get('replay', {})
    profile, profile_binding = _profile(ctx)
    program = result.get('program')
    nonce = replay.get('nonce', '')
    if (result.get('compiler_backend') != BACKEND or result.get('replay_timeout_seconds') != REPLAY_SECONDS
        or result.get('public_information_only') is not True or not ctx.data.get('revision_hash')
        or compiler.get('code') != program or not isinstance(program, str) or not program
        or program != compile_public_entity_group_recovery()
        or compiler.get('assumptions_added') != [] or compiler.get('unresolved_questions') != []
        or compiler.get('shared_excel_compiler') is not True or compiler.get('independent_second_formula_engine') is not False
        or compiler.get('is_llm_attempt') is not False
        or compiler.get('public_recipe') != public_implementation_recipe()
        or type(replay.get('returncode')) is not int or replay['returncode'] != 0
        or replay.get('fresh_network_disabled_container') is not True
        or replay.get('actual_resources_verified') is not True or replay.get('runtime_profile') != profile_binding
        or replay.get('cleanup_returncode') != 0
        or not re.fullmatch('[0-9a-f]{32}', nonce)
        or replay.get('command') != _replay_command(ctx, replay['directory'], nonce)):
        return False
    files = normal._recovery_artifacts(ctx, result)
    if not all(normal._recovery_local_file(files[name], ctx) for name in (
        'workspace_input', 'workspace_instruction', 'workspace_profile', 'workspace_program',
        'replay_input', 'replay_program', 'replay_output', 'attempt_recovered')):
        return False
    extras = _extra_artifacts(ctx, result)
    if not all(normal._recovery_local_file(path, ctx) for path in extras.values()):
        return False
    if replay.get('host_config') != _reference(extras['host_config']):
        return False
    if (files['workspace_input'].read_bytes() != Path(ctx.data['input']).read_bytes()
        or files['replay_input'].read_bytes() != Path(ctx.data['input']).read_bytes()
        or files['workspace_instruction'].read_bytes() != ctx.data['instruction'].encode()
        or extras['replay_instruction'].read_bytes() != ctx.data['instruction'].encode()
        or files['workspace_profile'].read_bytes() != json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False).encode()
        or files['workspace_program'].read_bytes() != program.encode() or files['replay_program'].read_bytes() != program.encode()
        or extras['replay_nonce'].read_text() != nonce + '\n'
        or replay.get('initial_files') != {'input.xlsx': _sha(ctx.data['input']),
            'instruction.md': hashlib.sha256(ctx.data['instruction'].encode()).hexdigest(),
            'recovery.py': hashlib.sha256(program.encode()).hexdigest(),
            'public_nonce.txt': hashlib.sha256((nonce + '\n').encode()).hexdigest()}):
        return False
    if not _host_resources_valid(_read_reference(replay['host_config']), profile, replay['directory'], replay['container_id']):
        return False
    report = json.loads(extras['public_recovery_report.json'].read_text())
    audit = json.loads(extras['cache_audit'].read_text())
    resource = _read_reference(result['resource_recalculation'])
    r = profile['docker_resources']['source']
    return (report.get('public_information_only') is True
        and report.get('source_sha256') == _sha(ctx.data['input'])
        and report.get('instruction_sha256') == hashlib.sha256(ctx.data['instruction'].encode()).hexdigest()
        and report.get('output_sha256') == _sha(files['replay_output'])
        and report.get('shared_excel_compiler') is True and report.get('independent_second_formula_engine') is False
        and report.get('private_goal_source_bindings_or_fault_list_read') is False
        and report.get('complete_public_row_layout_verified') is True
        and report.get('independent_field_audit', {}).get('all_independent_journal_fields_covered') is True
        and type(report['independent_field_audit'].get('physical_formulas_checked')) is int
        and report['independent_field_audit']['physical_formulas_checked'] > 0
        and type(report['independent_field_audit'].get('logical_fields_checked')) is int
        and report['independent_field_audit']['logical_fields_checked'] > 0
        and audit.get('passed') is True and audit.get('all_independent_journal_fields_covered') is True
        and audit.get('provided_fixed_plan_verified') is True and audit.get('all_scenarios_feasible') is True
        and audit.get('mismatches') == [] and audit.get('control_mismatches') == []
        and audit.get('physical_formulas_checked') == report['independent_field_audit']['physical_formulas_checked']
        and audit.get('logical_fields_checked') == report['independent_field_audit']['logical_fields_checked']
        and resource.get('status') == 'completed' and resource.get('actual_resources_verified') is True
        and resource.get('source') == _reference(files['replay_output'])
        and resource.get('output') == _reference(files['attempt_recovered'])
        and resource.get('image_id') == profile['image']['id']
        and resource.get('implementation') == _reference(resource_engine.__file__)
        and resource.get('profile') == profile_binding
        and resource.get('profile_canonical_sha256') == hashlib.sha256(json.dumps(
            profile, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        and resource.get('requested_resources') == r
        and resource.get('workbook_file_timeout_seconds') == 600
        and resource.get('actual_resources') == {'cpus_nanoseconds': r['cpus'] * 10**9,
                                               'memory_bytes': r['memory_bytes'], 'pids_limit': r['pids_limit']})


def valid_entity_group_recovery_witness(ctx, candidate):
    """Verify actual immutable evidence and full D; a verified flag alone fails."""
    from ..nodes import quality as normal
    from ..evaluation.streaming_delta import compare_workbooks
    try:
        if not isinstance(candidate, dict) or candidate.get('verified') is not True:
            return False
        if (candidate.get('task_revision_hash') != ctx.data.get('revision_hash')
            or candidate.get('usage_calls') != [] or candidate.get('usage_attribution') != 'not_applicable_programmatic'):
            return False
        record = Path(candidate['attempt_record_path'])
        checksum = record.with_name('attempt.sha256')
        if (record.parent.parent.absolute() != (ctx.revision_dir / 'private/recovery_attempts').absolute()
            or not normal._recovery_local_file(record, ctx) or not normal._recovery_local_file(checksum, ctx)
            or candidate.get('attempt_record_sha256') != _sha(record) or checksum.read_text().strip() != _sha(record)
            or json.loads(record.read_text()) != {key: value for key, value in candidate.items() if key != 'attempt_record_sha256'}
            or not _public_execution_valid(ctx, candidate)
            or candidate.get('witness_binding') != _witness_binding(ctx, candidate)):
            return False
        files = normal._recovery_artifacts(ctx, candidate)
        if not all(normal._recovery_local_file(path, ctx) for path in files.values()):
            return False
        if files['attempt_recovered'].read_bytes() != files['recovered'].read_bytes():
            return False
        actual = compare_workbooks(ctx.data['input'], ctx.data['goal'], files['recovered'])
        return actual.get('reward') == 1 and actual == candidate.get('comparison')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


class EntityGroupRecoveryNode(RecoveryNode):
    """Explicit resource-aware public replay; ordinary routing stays unchanged."""
    def execute(self, ctx):
        from ..core.audit import utcnow
        from ..core.node import CooperativeCancelled
        from ..nodes import quality as normal
        from ..evaluation.streaming_delta import compare_workbooks
        from .entity_group.validate import audit_entity_group_workbook
        from ..pipelines.entity_group_admission import verify_admitted_proof
        if ctx.config.get('entity_group_task') is None:
            return super().execute(ctx)
        _require(normal.validate_reference_policy_selection(ctx.config) == 'independent_public_recovery',
                 'This explicit entity family requires actual public recovery')
        _require(ctx.config.get('recovery', {}).get('compiler_backend') == BACKEND
                 and type(ctx.config['recovery'].get('replay_timeout_seconds')) is int
                 and ctx.config['recovery']['replay_timeout_seconds'] == REPLAY_SECONDS,
                 'The explicit public-entity backend and operational replay bound are required')
        profile, profile_binding = _profile(ctx)
        evidence = ctx.data.get('finance_evidence', {})
        proof = verify_admitted_proof(evidence.get('audited_source_binding'))
        _require(evidence.get('financial_seed_verified') is True and proof['runtime_profile'] == profile_binding,
                 'An independently verified source and the exact same profile are required')
        saved = ctx.revision_dir / 'private/independent_recovery.json'
        if saved.is_file():
            candidate = json.loads(saved.read_text())
            if valid_entity_group_recovery_witness(ctx, candidate):
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
            'replay_timeout_seconds': REPLAY_SECONDS}
        try:
            work = normal.prepare_workspace(ctx, 'recovery_public')
            result['workspace'] = str(work)
            (work / 'public_profile.json').write_text(json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False))
            program = compile_public_entity_group_recovery()
            compile(program, 'recovery.py', 'exec')
            result['program'] = program
            result['compiler'] = {'code': program, 'public_evidence_used': ['Group Contract JSON',
                'Group Rules complete phase order', 'Group Inputs typed primitive paths', 'public financial row labels', 'instruction.md'],
                'assumptions_added': [], 'unresolved_questions': [], 'implementation': BACKEND,
                'is_llm_attempt': False, 'shared_excel_compiler': True,
                'independent_second_formula_engine': False, 'public_recipe': public_implementation_recipe()}
            (work / 'recovery.py').write_text(program)
            nonce = uuid.uuid4().hex
            replay = ctx.revision_dir / ('recovery_replay-' + nonce)
            replay.mkdir(mode=0o700)
            shutil.copy2(ctx.data['input'], replay / 'input.xlsx')
            (replay / 'instruction.md').write_text(ctx.data['instruction'])
            (replay / 'recovery.py').write_text(program)
            (replay / 'public_nonce.txt').write_text(nonce + '\n')
            _require({file.name for file in replay.iterdir()} == set(PUBLIC_FILES),
                     'The initial replay may contain public inputs, program and nonce only')
            result['replay'] = {'directory': str(replay), 'nonce': nonce, 'returncode': None,
                'fresh_network_disabled_container': True,
                'initial_files': {name: _sha(replay / name) for name in PUBLIC_FILES}}
            _execute_replay(ctx, replay, attempt, result)
            _require(all((replay / name).is_file() for name in GENERATED_FILES), 'The public program outputs are incomplete')
            calculated = ctx.engine.recalculate(replay / 'output.xlsx', attempt / 'recovered.xlsx')
            metadata = ctx.engine.metadata()
            matches = [record for record in metadata.get('actual_resource_receipts', [])
                       if _read_reference(record).get('output') == _reference(calculated)]
            _require(len(matches) == 1, 'The actual recovered workbook needs one matching resource receipt')
            result['resource_recalculation'] = matches[0]
            public = json.loads((replay / 'public_specification.json').read_text())
            definitions = json.loads((replay / 'public_definitions.json').read_text())
            ledger = json.loads((replay / 'public_forward_ledger.json').read_text())
            audit = audit_entity_group_workbook(calculated, public, ledger, definitions)
            with (attempt / 'public_cache_audit.json').open('x') as stream:
                json.dump(audit, stream, ensure_ascii=False, indent=2)
            _require(audit.get('passed') is True, 'The complete independent public-ledger cache audit failed')
            _require(_public_execution_valid(ctx, result), 'The actual replay evidence does not bind all public artifacts and resources')
            comparison = compare_workbooks(ctx.data['input'], ctx.data['goal'], calculated)
            result['comparison'] = comparison
            if comparison.get('reward') == 1:
                shutil.copy2(calculated, ctx.revision_dir / 'private/recovered.xlsx')
                result.update(replay_output_sha256=_sha(replay / 'output.xlsx'), recovered_sha256=_sha(calculated))
                result['witness_binding'] = _witness_binding(ctx, result)
                result['verified'] = True
        except CooperativeCancelled:
            result.update(status='cancelled', error='Explicit cooperative stop; no recovery is certified')
            raise
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error))
        finally:
            result.update(usage_calls=[], usage_attribution='not_applicable_programmatic', finished_at=utcnow())
            result.setdefault('status', 'verified' if result['verified'] else 'unverified')
            raw = (json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n').encode()
            with (attempt / 'attempt.json').open('xb') as stream:
                stream.write(raw)
            with (attempt / 'attempt.sha256').open('x') as stream:
                stream.write(hashlib.sha256(raw).hexdigest() + '\n')
            (attempt / 'attempt.json').chmod(0o444)
            (attempt / 'attempt.sha256').chmod(0o444)
            result['attempt_record_sha256'] = hashlib.sha256(raw).hexdigest()
            ctx.save('independent_recovery.json', result)
        return {'recovery': result}
