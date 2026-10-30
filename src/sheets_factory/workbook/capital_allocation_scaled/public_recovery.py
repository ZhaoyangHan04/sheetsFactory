"""Public-only scaled recovery, with declared shared native/Decimal dependencies.

The public program performs a fresh complete native A search. It receives no
reference, winner, source bindings or search proof. A and the Decimal journal
are shared with source validation; this is public reachability, not another
independently authored optimum proof. Binary preparation is always explicit.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
import zipfile

from ...nodes.quality import RecoveryNode

BACKEND = 'scaled_capital_public_A_integer_search_decimal_forward'
SETTING = 'scaled_capital_allocation_task'
REPLAY_SECONDS = 7200
KERNEL_KIND = 'prepared_scaled_capital_public_A_static_kernel'
SOURCE_SHA256 = 'f69ccd8846b3b7a53b3e0c9a26dadd0ee605a21ab47b1885ef25116caaa8180d'
RESOURCE_HELPER_SHA256 = 'd1bbbdf7992038e7bc7cc3839d3b0faaae700dd001928cfc28dc6a52d6a63c32'
CONTRACT_SHA256 = 'a965864eae7490a2185d1e3030fc8b56c69ea08bfb5b936df59816ed21f7b4e4'
PUBLIC_FILES = ('input.xlsx', 'instruction.md', 'recovery.py', 'public_nonce.txt')
GENERATED_FILES = ('output.xlsx', 'public_recovery_report.json', 'public_definitions.json',
                   'public_forward_ledger.json', 'public_specification.json', 'public_search_result.json')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _reference(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file(), 'An exact regular artifact without symlink components is required')
    return {'path': str(path), 'sha256': _sha(path), 'bytes': path.stat().st_size}


def _read_reference(record):
    _require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}
             and _reference(record['path']) == record, 'A frozen reference changed')
    return json.loads(Path(record['path']).read_text(), object_pairs_hook=_unique_json)


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
    if isinstance(value, list):
        return [_ordered_public(child, ranks, (*path, index)) for index, child in enumerate(value)]
    if not isinstance(value, dict):
        return value
    def first(key):
        return min((ranks[label] for label, _ in _flatten(value[key], (*path, key))), default=len(ranks))
    return {key: _ordered_public(value[key], ranks, (*path, key)) for key in sorted(value, key=first)}


def _contract_markdown():
    local = Path(__file__).with_name('public_contract.md')
    if local.is_file():
        text = local.read_text()
    else:
        from .catalog import public_contract, contract_markdown
        text = contract_markdown(public_contract('30-D01'))
    _require(hashlib.sha256(text.encode()).hexdigest() == CONTRACT_SHA256, 'The complete public field dictionary changed')
    return text


def read_public_spec(book, instruction):
    from .spec import load_spec
    from .excel import PUBLIC_RULES
    _require(type(instruction) is str and _contract_markdown().strip() in instruction,
             'The actual public instruction must contain the complete candidate, Annual, vintage and Summary contract')
    _require(all(name in book for name in ('Capital Rules', 'Capital Contract', 'Capital Inputs',
                 'Investment Plan', 'Capital Summary', 'Exact Arithmetic')), 'A public financial worksheet is absent')
    chunks = []
    sheet = book['Capital Contract']
    for row in range(2, sheet.max_row + 1):
        label, cell = sheet.cell(row, 1), sheet.cell(row, 2)
        _require(label.value == 'JSON part ' + str(len(chunks) + 1) and cell.data_type != 'f'
                 and type(cell.value) is str, 'Public JSON parts must be complete ordered literals')
        chunks.append(cell.value)
    _require(bool(chunks), 'The complete public JSON contract is absent')
    public = load_spec(json.loads(''.join(chunks), object_pairs_hook=_unique_json,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError('Nonfinite public JSON'))))
    _require(len(public['projects']) == 30, 'This explicit recovery supports all thirty public projects')
    rules = book['Capital Rules']
    _require(rules.max_row == len(PUBLIC_RULES) + 3
             and [rules.cell(i, 1).value for i in range(4, rules.max_row + 1)] == list(PUBLIC_RULES),
             'The full public policy or candidate/Summary interpretation changed')
    expected, provided, ranks = dict(_flatten(public)), {}, {}
    inputs = book['Capital Inputs']
    for row in range(3, inputs.max_row + 1):
        label, cell = inputs.cell(row, 1).value, inputs.cell(row, 2)
        _require(type(label) is str and label in expected and label not in provided and cell.data_type != 'f',
                 'A public primitive is unknown, duplicated, missing or calculated')
        wanted = expected[label]
        matched = (type(cell.value) in (int, float) and cell.value == wanted if type(wanted) is int
                   else type(cell.value) is type(wanted) and cell.value == wanted)
        _require(matched, 'A typed public primitive differs from the JSON contract: ' + label)
        provided[label], ranks[label] = cell.value, row
    _require(set(provided) == set(expected), 'The labelled inputs do not cover every public primitive')
    return _ordered_public(public, ranks)


def _static_elf(path):
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:6] != b'\x7fELF\x02\x01':
            return False
        offset, size, count = struct.unpack_from('<Q', header, 32)[0], struct.unpack_from('<H', header, 54)[0], struct.unpack_from('<H', header, 56)[0]
        if size != 56 or not 1 <= count <= 128:
            return False
        stream.seek(offset)
        segments = stream.read(size * count)
        return (len(segments) == size * count
                and all(struct.unpack_from('<I', segments, i * size)[0] not in (2, 3) for i in range(count)))


def prepare_public_kernel(output):
    """Explicit host compilation only. Never enumerate or access a workbook."""
    source = Path(__file__).with_name('search_a.cpp')
    _require(_sha(source) == SOURCE_SHA256, 'The public A source changed')
    output = Path(output).absolute()
    _require(output == output.resolve() and output.is_relative_to(Path('/data')) and not output.exists(),
             'Use a fresh real compilation directory under /data')
    output.mkdir(parents=True)
    temporary = output / 'temporary'; temporary.mkdir()
    compiler = shutil.which('g++')
    _require(compiler is not None, 'Explicit public-kernel preparation requires g++')
    compiler = Path(compiler).resolve()
    command = [str(compiler), '-std=c++17', '-O3', '-static', '-Wall', '-Wextra', str(source), '-o', str(output / 'public_search_a')]
    started = {'kind': KERNEL_KIND, 'version': 1, 'source_cpp': _reference(source), 'command': command,
        'compiler_binary': _reference(compiler), 'preparation_implementation': _reference(__file__),
        'enumerations': 0, 'LO_calls': 0, 'model_calls': 0, 'same_image_execution_compatibility_verified': False}
    (output / 'started.json').write_text(json.dumps(started, indent=2) + '\n')
    try:
        version = subprocess.run([str(compiler), '--version'], capture_output=True, text=True, timeout=30)
        (output / 'compiler_version.stdout').write_text(version.stdout)
        (output / 'compiler_version.stderr').write_text(version.stderr)
        _require(version.returncode == 0, 'Cannot identify the actual compiler')
        execution = subprocess.run(command, capture_output=True, text=True,
            env={**os.environ, 'TMPDIR': str(temporary)}, timeout=120)
        (output / 'compile.stdout').write_text(execution.stdout); (output / 'compile.stderr').write_text(execution.stderr)
        _require(execution.returncode == 0 and _static_elf(output / 'public_search_a'),
                 'The explicit static public-kernel compilation failed')
        result = {**started, 'status': 'compiled_public_code_not_executed', 'returncode': 0,
            'binary': _reference(output / 'public_search_a'), 'static_elf_without_dynamic_loader': True,
            **{name: _reference(output / name) for name in ('compiler_version.stdout', 'compiler_version.stderr', 'compile.stdout', 'compile.stderr')}}
    except BaseException as error:
        (output / 'failed.json').write_text(json.dumps({**started, 'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)}, indent=2) + '\n')
        raise
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    return _reference(output / 'receipt.json')


def validate_kernel_preparation(record):
    if isinstance(record, (str, Path)):
        record = Path(record); record = _reference(record / 'receipt.json' if record.is_dir() else record)
    frozen = _read_reference(record)
    source = Path(__file__).with_name('search_a.cpp')
    binary = Path(record['path']).parent / 'public_search_a'
    _require(frozen.get('kind') == KERNEL_KIND and type(frozen.get('version')) is int and frozen['version'] == 1
        and frozen.get('status') == 'compiled_public_code_not_executed' and type(frozen.get('returncode')) is int and frozen['returncode'] == 0
        and frozen.get('source_cpp') == _reference(source) and _sha(source) == SOURCE_SHA256
        and frozen.get('preparation_implementation') == _reference(__file__)
        and frozen.get('binary') == _reference(binary) and _static_elf(binary)
        and frozen.get('static_elf_without_dynamic_loader') is True
        and all(type(frozen.get(k)) is int and frozen[k] == 0 for k in ('enumerations', 'LO_calls', 'model_calls'))
        and frozen.get('same_image_execution_compatibility_verified') is False,
        'A frozen explicitly compiled public code binary is required, without fabricated runtime evidence')
    compiler = frozen['compiler_binary']; _require(_reference(compiler['path']) == compiler, 'The bound compiler changed')
    _require(frozen['command'] == [compiler['path'], '-std=c++17', '-O3', '-static', '-Wall', '-Wextra',
             str(source), '-o', str(binary)], 'The public static compilation command changed')
    for name in ('compiler_version.stdout', 'compiler_version.stderr', 'compile.stdout', 'compile.stderr'):
        _require(frozen[name] == _reference(binary.parent / name), 'The preserved compilation evidence changed')
    return frozen


def _native_search(public, directory, kernel, active_project_ids=None):
    from . import spec as schema
    from .search_a import raw_primitives
    ids = list(schema.project_ids(30))
    active = ids if active_project_ids is None else list(active_project_ids)
    _require(bool(active) and len(set(active)) == len(active) and all(p in ids for p in active)
             and active == sorted(active, key=ids.index)
             and (active_project_ids is None or len(active) <= 8), 'Toy activity must be an explicit ordered subset of at most eight')
    wire = directory / 'public_raw_primitives.txt'; wire.write_text(raw_primitives(public, [ids.index(p) for p in active]))
    command = [str(kernel), str(wire), '/dev/null']
    clock = time.monotonic()
    with (directory / 'public_kernel.stdout').open('x') as stdout, (directory / 'public_kernel.stderr').open('x') as stderr:
        run = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=REPLAY_SECONDS)
    _require(run.returncode == 0, 'The fresh public complete native search failed')
    result = json.loads((directory / 'public_kernel.stdout').read_text(), object_pairs_hook=_unique_json)
    count = 1 << len(active)
    _require(result.get('kind') == 'capital_scaled_kernel_a_result' and type(result.get('version')) is int and result['version'] == 1
        and result.get('project_count') == 30 and result.get('active_count') == len(active)
        and type(result.get('plan_count')) is int and result['plan_count'] == count
        and result.get('scenario_evaluations') == count * 3
        and result.get('unique_best') is True and type(result.get('best_count')) is int and result['best_count'] == 1
        and all(type(result.get(k)) is int for k in ('best_mask', 'runnerup_mask', 'objective_pence', 'runnerup_objective_pence', 'gap_pence', 'feasible_count'))
        and 2 <= result['feasible_count'] <= count and 0 <= result['best_mask'] < count
        and 0 <= result['runnerup_mask'] < count and result['best_mask'] != result['runnerup_mask']
        and result['gap_pence'] == result['objective_pence'] - result['runnerup_objective_pence'] >= 1,
        'The native search must genuinely complete the exact dimension with a unique penny-gap winner')
    full = sum(int(bool(result['best_mask'] & (1 << i))) << ids.index(p) for i, p in enumerate(active))
    plan = {p: int(bool(full & (1 << i))) for i, p in enumerate(ids)}
    return plan, {**result, 'active_project_ids': active, 'full_enumeration': active_project_ids is None,
        'toy_only': active_project_ids is not None, 'records_destination': '/dev/null',
        'kernel_command': command, 'kernel_returncode': run.returncode,
        'native_complete_count_and_rank_verified': True, 'independent_record_stream_scan_performed': False,
        'second_independent_search_claimed': False, 'elapsed_seconds_observed': time.monotonic() - clock,
        'raw_wire_sha256': _sha(wire), 'binary_sha256': _sha(kernel)}


def _literal_equal(left, right):
    from datetime import date, datetime
    if isinstance(left, (date, datetime)) and isinstance(right, (date, datetime)):
        return (left.year, left.month, left.day) == (right.year, right.month, right.day)
    if type(left) in (int, float) and type(right) in (int, float): return left == right
    return type(left) is type(right) and left == right


def _layout(original, rebuilt, bindings):
    from .validate import _formula_tokens
    targets = {(v['sheet'], v['cell']) for k in ('financial_bindings', 'decision_bindings') for v in bindings[k]}
    _require(original.sheetnames == rebuilt.sheetnames, 'The full original worksheet list must be preserved')
    for sheet in rebuilt:
        source = original[sheet.title]
        for row, column in set(sheet._cells) | set(source._cells):
            before, expected = source.cell(row, column), sheet.cell(row, column)
            if (sheet.title, expected.coordinate) in targets:
                _require(before.value is None, 'Every approved financial and common-decision target must be missing')
            elif expected.data_type == 'f':
                _require(before.data_type == 'f' and _formula_tokens(before.value) == _formula_tokens(expected.value),
                         'A provided arithmetic definition changed')
            else:
                _require(before.data_type != 'f' and _literal_equal(before.value, expected.value),
                         'A public primitive, row label, date or worksheet boundary differs')
    return targets


def recover_public(source, destination, report_path=None, *, instruction_path=None, kernel_path=None, active_project_ids=None):
    """Use public bytes only; an explicit small subset is marked toy, never a witness."""
    import openpyxl
    from . import excel, ledger, validate
    source, destination = Path(source), Path(destination)
    _require(source.resolve() != destination.resolve() and not destination.exists(), 'Never overwrite the public input or an earlier replay')
    _require(instruction_path is not None, 'The actual public instruction is required')
    instruction = Path(instruction_path).read_text()
    book = openpyxl.load_workbook(source, keep_links=False)
    rebuilt = openpyxl.Workbook(); rebuilt.remove(rebuilt.active)
    try:
        public = read_public_spec(book, instruction)
        kernel = Path(kernel_path) if kernel_path is not None else Path(__file__).with_name('public_search_a')
        plan, search = _native_search(public, destination.parent, kernel, active_project_ids)
        forward = ledger.simulate(public, plan)
        _require(forward['feasible'] is True and forward['objective_pence'] == search['objective_pence'],
                 'The independent public Decimal journal disagrees with the native winner')
        bindings = excel.emit_capital_allocation_workbook(rebuilt, public, plan)
        targets = _layout(book, rebuilt, bindings)
        expected = validate.expected_cells(public, plan, forward, bindings)
        for key in ('financial_bindings', 'decision_bindings'):
            for item in bindings[key]:
                value = expected[validate._reference(item['sheet'], item['cell'])]
                book[item['sheet']][item['cell']] = '' if value is None else value
        book.save(destination)
    finally:
        rebuilt.close(); book.close()
    for name, value in [('public_specification.json', public), ('public_forward_ledger.json', forward),
                        ('public_definitions.json', bindings), ('public_search_result.json', search)]:
        with (destination.parent / name).open('x') as stream: json.dump(value, stream, ensure_ascii=False)
    report = {'public_information_only': True, 'source_sha256': _sha(source),
        'instruction_sha256': hashlib.sha256(instruction.encode()).hexdigest(), 'output_sha256': _sha(destination),
        'financial_and_decision_cells_reconstructed': len(targets), 'enumeration': search,
        'shared_source_A_optimizer': True, 'shared_source_Decimal_forward_implementation': True,
        'shared_excel_layout_and_support_compiler': True, 'independent_second_search_claimed': False,
        'private_goal_source_bindings_or_search_proof_read': False, 'complete_public_row_layout_verified': True,
        'provided_arithmetic_formulas_preserved': True, 'full_required_D_not_reduced': True,
        'expected_all_formula_values_derived': len(bindings['financial_bindings']) + len(bindings['decision_bindings']) + len(bindings['arithmetic_bindings']),
        'actual_cache_audit_still_required': True, 'assumptions_added': [], 'unresolved_questions': []}
    if report_path is not None:
        with Path(report_path).open('x') as stream: json.dump(report, stream, indent=2)
    return report


def audit_public_recovered(path, public, plan, forward, bindings):
    """Audit value-filled finance and formula-filled helpers, not a gold-formula claim."""
    import openpyxl
    from . import validate
    expected = validate.expected_cells(public, plan, forward, bindings)
    definitions = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    caches = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    mismatches = []
    records = bindings['financial_bindings'] + bindings['decision_bindings'] + bindings['arithmetic_bindings']
    helpers = {(i['sheet'], i['cell']): i for i in bindings['arithmetic_bindings']}
    try:
        _require(definitions.sheetnames == caches.sheetnames == bindings['sheet_names'], 'Recovered structure differs')
        actual_formulas = {(s.title, c.coordinate) for s in definitions for c in s._cells.values() if c.data_type == 'f'}
        _require(actual_formulas == set(helpers), 'Only the provided exact-arithmetic formulas may remain')
        for item in records:
            address = validate._reference(item['sheet'], item['cell']); wanted = expected[address]
            actual = caches[item['sheet']][item['cell']].value
            good = actual in (None, '') if wanted is None else type(actual) in (int, float) and actual == wanted
            if (item['sheet'], item['cell']) in helpers:
                good = good and validate._formula_tokens(definitions[item['sheet']][item['cell']].value) == validate._formula_tokens(item['formula'])
            if not good: mismatches.append({'address': address, 'expected': wanted, 'observed': actual})
    finally:
        definitions.close(); caches.close()
    return {'passed': not mismatches, 'checked_cells': len(records), 'formula_helper_count': len(helpers),
        'financial_and_decision_values_checked': len(records) - len(helpers), 'mismatches': mismatches,
        'all_scenarios_feasible': forward['feasible'], 'all_journals_balance': all(s['all_journals_balance'] for s in forward['scenarios'].values()),
        'all_financial_and_support_values_covered': True, 'gold_formula_auditor_claimed': False}


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


def _extra_artifacts(ctx, result):
    replay = Path(result['replay']['directory'])
    attempt = Path(result['attempt_record_path']).parent
    return {'replay_instruction': replay / 'instruction.md', 'replay_nonce': replay / 'public_nonce.txt',
        **{name: replay / name for name in GENERATED_FILES},
        **{name: replay / name for name in ('public_raw_primitives.txt', 'public_kernel.stdout', 'public_kernel.stderr')},
        'host_config': attempt / 'replay_host_config.json', 'cache_audit': attempt / 'public_cache_audit.json'}


def _witness_binding(ctx, result):
    from ...nodes import quality as normal
    return {**normal._recovery_binding(ctx, result), 'version': 2,
        'public_replay_artifacts': {key: _reference(path) for key, path in _extra_artifacts(ctx, result).items()},
        'runtime_profile': result['replay']['runtime_profile'], 'public_recipe': public_implementation_recipe(),
        'implementation': _reference(__file__), 'resource_recalculation': result['resource_recalculation'],
        'public_kernel_preparation': ctx.config['recovery']['public_kernel_preparation']}


def public_implementation_recipe():
    """All dependencies are code/schema; none contains a winner or proof."""
    base = Path(__file__).resolve().parent
    files = ['spec.py', 'ledger.py', 'excel.py', 'validate.py', 'search_a.py', 'search_a.cpp']
    result = {str(base / name): _reference(base / name) for name in files}
    for name in ('spec.py', 'ledger.py', 'excel.py'):
        file = base.parent / 'capital_allocation' / name; result[str(file)] = _reference(file)
    from .. import entity_group_public_recovery as helpers
    _require(_sha(helpers.__file__) == RESOURCE_HELPER_SHA256, 'The source of the copied resource/ownership proof changed')
    result[str(Path(helpers.__file__))] = _reference(helpers.__file__)
    return result


def compile_public_scaled_capital_recovery(kernel_preparation, *, active_project_ids=None):
    """Deterministic bundle creation, with no implicit compilation/execution."""
    frozen = validate_kernel_preparation(kernel_preparation)
    public_implementation_recipe()
    if active_project_ids is not None:
        ids = ['P' + str(i).zfill(2) for i in range(1, 31)]
        active_project_ids = list(active_project_ids)
        _require(1 <= len(active_project_ids) <= 8 and len(set(active_project_ids)) == len(active_project_ids)
                 and all(p in ids for p in active_project_ids) and active_project_ids == sorted(active_project_ids, key=ids.index),
                 'Only an explicit ordered small toy subset may alter a test bundle')
    source = Path(__file__).read_text(); parsed = ast.parse(source)
    functions = {'_require', '_sha', '_unique_json', '_flatten', '_ordered_public', '_contract_markdown',
        'read_public_spec', '_native_search', '_literal_equal', '_layout', 'recover_public', 'audit_public_recovered'}
    runtime = ('from __future__ import annotations\nimport hashlib,json,subprocess,time\nfrom pathlib import Path\n'
        + 'CONTRACT_SHA256=' + repr(CONTRACT_SHA256) + '\nREPLAY_SECONDS=' + str(REPLAY_SECONDS) + '\n'
        + ast.unparse(ast.Module(body=[n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name in functions], type_ignores=[])) + '\n')
    payload = io.BytesIO(); base = Path(__file__).parent
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        def put(name, value):
            entry = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, value)
        for name in ('sheets_factory/__init__.py', 'sheets_factory/workbook/__init__.py',
                     'sheets_factory/workbook/capital_allocation/__init__.py', 'sheets_factory/workbook/capital_allocation_scaled/__init__.py'):
            put(name, '')
        for relative in (['capital_allocation/' + n for n in ('spec.py', 'ledger.py', 'excel.py')]
            + ['capital_allocation_scaled/' + n for n in ('spec.py', 'ledger.py', 'excel.py', 'validate.py', 'search_a.py', 'search_a.cpp')]):
            put('sheets_factory/workbook/' + relative, (base.parent / relative).read_bytes())
        prefix = 'sheets_factory/workbook/capital_allocation_scaled/'
        put(prefix + 'public_runtime.py', runtime)
        put(prefix + 'public_search_a', Path(frozen['binary']['path']).read_bytes())
        put(prefix + 'public_contract.md', _contract_markdown())
    encoded = base64.b64encode(payload.getvalue()).decode()
    return ('import base64,io,os,sys,tempfile,zipfile\nfrom pathlib import Path\n'
        'directory=Path(tempfile.mkdtemp(prefix="scaled-capital-public-",dir=Path.cwd()))\n'
        'temporary=directory/"temporary";temporary.mkdir();os.environ["TMPDIR"]=str(temporary);tempfile.tempdir=str(temporary)\n'
        + 'with zipfile.ZipFile(io.BytesIO(base64.b64decode(' + repr(encoded) + '))) as archive: archive.extractall(directory)\n'
        'binary=directory/"sheets_factory/workbook/capital_allocation_scaled/public_search_a";binary.chmod(0o700)\n'
        'sys.path.insert(0,str(directory))\n'
        'from sheets_factory.workbook.capital_allocation_scaled.public_runtime import recover_public\n'
        'recover_public(Path("input.xlsx"),Path("output.xlsx"),Path("public_recovery_report.json"),'
        + 'instruction_path=Path("instruction.md"),active_project_ids=' + repr(active_project_ids) + ')\n')


def _profile(ctx):
    from ..resource_engine import load_runtime_profile
    record = ctx.config[SETTING]['runtime_profile']
    _require(_reference(record['path']) == record, 'The explicit runtime profile changed')
    profile = load_runtime_profile(record['path'])
    _require(profile['id'] == 'entity_group_large_v2'
        and profile['docker_resources']['source'] == profile['docker_resources']['agent'] == profile['docker_resources']['verifier']
        and profile['docker_resources']['agent']['cpus'] == 2
        and profile['docker_resources']['agent']['memory_bytes'] == 32 * 1024**3,
        'The thirty-project reference and task must use the same explicit 2-CPU 32-GiB profile')
    return profile, record


def _replay_command(ctx, replay, nonce):
    profile, _ = _profile(ctx); r = profile['docker_resources']['agent']
    return ['docker', 'create', '--name', 'sheetsfactory-scaled-capital-recovery-' + nonce,
        '--user', '0', '--network', 'none', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
        '--security-opt', 'no-new-privileges', '--cpus', str(r['cpus']), '--memory', str(r['memory_bytes']),
        '--pids-limit', str(r['pids_limit']), '--volume', str(Path(replay).resolve()) + ':/workspace:rw',
        '--workdir', '/workspace', '--entrypoint', '/usr/bin/python3', profile['image']['id'], '/workspace/recovery.py']


def _public_execution_valid(ctx, result):
    from ...nodes import quality as normal
    from .. import resource_engine
    compiler, replay = result.get('compiler', {}), result.get('replay', {})
    profile, profile_binding = _profile(ctx)
    kernel_preparation = ctx.config['recovery']['public_kernel_preparation']
    kernel = validate_kernel_preparation(kernel_preparation)
    program, nonce = result.get('program'), replay.get('nonce', '')
    if (result.get('compiler_backend') != BACKEND or result.get('replay_timeout_seconds') != REPLAY_SECONDS
        or result.get('public_information_only') is not True or not ctx.data.get('revision_hash')
        or compiler.get('code') != program or not isinstance(program, str) or not program
        or program != compile_public_scaled_capital_recovery(kernel_preparation)
        or compiler.get('assumptions_added') != [] or compiler.get('unresolved_questions') != []
        or compiler.get('is_llm_attempt') is not False
        or compiler.get('shared_source_A_optimizer') is not True
        or compiler.get('shared_source_Decimal_forward_implementation') is not True
        or compiler.get('shared_excel_layout_and_support_compiler') is not True
        or compiler.get('independent_second_search_claimed') is not False
        or compiler.get('public_recipe') != public_implementation_recipe()
        or compiler.get('public_kernel_preparation') != kernel_preparation
        or type(replay.get('returncode')) is not int or replay['returncode'] != 0
        or replay.get('fresh_network_disabled_container') is not True
        or replay.get('actual_resources_verified') is not True or replay.get('runtime_profile') != profile_binding
        or replay.get('cleanup_returncode') != 0 or not re.fullmatch('[0-9a-f]{32}', nonce)
        or replay.get('command') != _replay_command(ctx, replay['directory'], nonce)):
        return False
    files = normal._recovery_artifacts(ctx, result); extras = _extra_artifacts(ctx, result)
    if not all(normal._recovery_local_file(files[name], ctx) for name in (
        'workspace_input', 'workspace_instruction', 'workspace_profile', 'workspace_program',
        'replay_input', 'replay_program', 'replay_output', 'attempt_recovered')):
        return False
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
    search = json.loads(extras['public_search_result.json'].read_text())
    forward = json.loads(extras['public_forward_ledger.json'].read_text())
    raw_search = json.loads(extras['public_kernel.stdout'].read_text())
    resource = _read_reference(result['resource_recalculation']); r = profile['docker_resources']['source']
    return (report.get('public_information_only') is True
        and report.get('source_sha256') == _sha(ctx.data['input'])
        and report.get('instruction_sha256') == hashlib.sha256(ctx.data['instruction'].encode()).hexdigest()
        and report.get('output_sha256') == _sha(files['replay_output'])
        and report.get('shared_source_A_optimizer') is True
        and report.get('shared_source_Decimal_forward_implementation') is True
        and report.get('shared_excel_layout_and_support_compiler') is True
        and report.get('independent_second_search_claimed') is False
        and report.get('private_goal_source_bindings_or_search_proof_read') is False
        and report.get('complete_public_row_layout_verified') is True
        and report.get('provided_arithmetic_formulas_preserved') is True
        and report.get('full_required_D_not_reduced') is True
        and report.get('enumeration') == search
        and report.get('expected_all_formula_values_derived') == audit.get('checked_cells') == 77513
        and report.get('financial_and_decision_cells_reconstructed') == audit.get('financial_and_decision_values_checked') == 25541
        and audit.get('formula_helper_count') == 51972
        and audit.get('passed') is True and audit.get('all_financial_and_support_values_covered') is True
        and audit.get('gold_formula_auditor_claimed') is False and audit.get('all_scenarios_feasible') is True
        and audit.get('all_journals_balance') is True and audit.get('mismatches') == []
        and search.get('full_enumeration') is True and search.get('toy_only') is False
        and search.get('plan_count') == 1 << 30 and search.get('scenario_evaluations') == 3 * (1 << 30)
        and search.get('project_count') == search.get('active_count') == 30
        and search.get('active_project_ids') == ['P' + str(i).zfill(2) for i in range(1, 31)]
        and search.get('unique_best') is True and search.get('best_count') == 1
        and type(search.get('gap_pence')) is int and search['gap_pence'] >= 1
        and search.get('records_destination') == '/dev/null' and search.get('kernel_returncode') == 0
        and search.get('independent_record_stream_scan_performed') is False
        and search.get('second_independent_search_claimed') is False
        and search.get('raw_wire_sha256') == _sha(extras['public_raw_primitives.txt'])
        and search.get('binary_sha256') == kernel['binary']['sha256']
        and all(search.get(key) == value for key, value in raw_search.items())
        and forward.get('feasible') is True and forward.get('objective_pence') == search.get('objective_pence')
        and resource.get('status') == 'completed' and resource.get('actual_resources_verified') is True
        and resource.get('source') == _reference(files['replay_output'])
        and resource.get('output') == _reference(files['attempt_recovered'])
        and resource.get('image_id') == profile['image']['id']
        and resource.get('implementation') == _reference(resource_engine.__file__)
        and resource.get('profile') == profile_binding
        and resource.get('profile_canonical_sha256') == hashlib.sha256(json.dumps(profile, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        and resource.get('requested_resources') == r and resource.get('workbook_file_timeout_seconds') == 600
        and resource.get('actual_resources') == {'cpus_nanoseconds': r['cpus'] * 10**9,
            'memory_bytes': r['memory_bytes'], 'pids_limit': r['pids_limit']})


def valid_scaled_capital_recovery_witness(ctx, candidate):
    """Strict current-revision execution/resource/full-D proof, never a flag."""
    from ...nodes import quality as normal
    from ...evaluation.streaming_delta import compare_workbooks
    try:
        if not isinstance(candidate, dict) or candidate.get('verified') is not True:
            return False
        if (candidate.get('task_revision_hash') != ctx.data.get('revision_hash')
            or candidate.get('usage_calls') != [] or candidate.get('usage_attribution') != 'not_applicable_programmatic'):
            return False
        record = Path(candidate['attempt_record_path']); checksum = record.with_name('attempt.sha256')
        if (record.parent.parent.absolute() != (ctx.revision_dir / 'private/recovery_attempts').absolute()
            or not normal._recovery_local_file(record, ctx) or not normal._recovery_local_file(checksum, ctx)
            or candidate.get('attempt_record_sha256') != _sha(record) or checksum.read_text().strip() != _sha(record)
            or json.loads(record.read_text()) != {k: v for k, v in candidate.items() if k != 'attempt_record_sha256'}
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


class ScaledCapitalAllocationRecoveryNode(RecoveryNode):
    node_id = 'independent_recovery'

    def execute(self, ctx):
        from ...core.audit import utcnow
        from ...core.node import CooperativeCancelled
        from ...nodes import quality as normal
        from ...evaluation.streaming_delta import compare_workbooks
        if ctx.config.get(SETTING) is None:
            return super().execute(ctx)
        from ...pipelines.scaled_capital_admission import verify_admitted_proof
        _require(normal.validate_reference_policy_selection(ctx.config) == 'independent_public_recovery'
            and ctx.config['recovery'].get('compiler_backend') == BACKEND
            and type(ctx.config['recovery'].get('replay_timeout_seconds')) is int
            and ctx.config['recovery']['replay_timeout_seconds'] == REPLAY_SECONDS,
            'Actual public reconstruction and its explicit backend/operational bound are required')
        _, profile_binding = _profile(ctx)
        kernel_preparation = ctx.config['recovery']['public_kernel_preparation']
        validate_kernel_preparation(kernel_preparation)
        evidence = ctx.data.get('finance_evidence', {})
        proof = verify_admitted_proof(evidence.get('audited_source_binding'), session=ctx.data.get('_scaled_admission_session'))
        _require(evidence.get('financial_seed_verified') is True and proof['runtime_profile'] == profile_binding,
                 'The independently verified financial source and exact same profile are mandatory')
        saved = ctx.revision_dir / 'private/independent_recovery.json'
        if saved.is_file():
            candidate = json.loads(saved.read_text())
            if valid_scaled_capital_recovery_witness(ctx, candidate):
                return {'recovery': candidate}
        history = ctx.revision_dir / 'private/recovery_attempts'; history.mkdir(parents=True, exist_ok=True)
        index = 0
        while True:
            attempt = history / f'attempt_{index:06d}'
            try:
                attempt.mkdir(mode=0o700); break
            except FileExistsError:
                index += 1
        result = {'public_information_only': True, 'verified': False, 'attempt_id': attempt.name,
            'attempt_record_path': str(attempt / 'attempt.json'), 'started_at': utcnow(),
            'task_revision_hash': ctx.data.get('revision_hash'), 'compiler_backend': BACKEND,
            'replay_timeout_seconds': REPLAY_SECONDS}
        try:
            work = normal.prepare_workspace(ctx, 'recovery_public'); result['workspace'] = str(work)
            (work / 'public_profile.json').write_text(json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False))
            program = compile_public_scaled_capital_recovery(kernel_preparation); compile(program, 'recovery.py', 'exec')
            result['program'] = program
            result['compiler'] = {'code': program, 'public_evidence_used': ['Capital Rules', 'Capital Contract JSON',
                'Capital Inputs typed labels', 'complete candidate and accounting field dictionary in instruction.md', 'public financial row labels'],
                'assumptions_added': [], 'unresolved_questions': [], 'implementation': BACKEND, 'is_llm_attempt': False,
                'shared_source_A_optimizer': True, 'shared_source_Decimal_forward_implementation': True,
                'shared_excel_layout_and_support_compiler': True, 'independent_second_search_claimed': False,
                'public_recipe': public_implementation_recipe(), 'public_kernel_preparation': kernel_preparation}
            (work / 'recovery.py').write_text(program)
            nonce = uuid.uuid4().hex; replay = ctx.revision_dir / ('recovery_replay-' + nonce); replay.mkdir(mode=0o700)
            shutil.copy2(ctx.data['input'], replay / 'input.xlsx')
            (replay / 'instruction.md').write_text(ctx.data['instruction']); (replay / 'recovery.py').write_text(program)
            (replay / 'public_nonce.txt').write_text(nonce + '\n')
            _require({p.name for p in replay.iterdir()} == set(PUBLIC_FILES), 'Only public input, instruction, program and nonce may enter replay')
            result['replay'] = {'directory': str(replay), 'nonce': nonce, 'returncode': None,
                'fresh_network_disabled_container': True, 'initial_files': {name: _sha(replay / name) for name in PUBLIC_FILES}}
            _execute_replay(ctx, replay, attempt, result)
            _require(all((replay / name).is_file() for name in GENERATED_FILES), 'The public reconstruction outputs are incomplete')
            calculated = ctx.engine.recalculate(replay / 'output.xlsx', attempt / 'recovered.xlsx')
            matches = [r for r in ctx.engine.metadata().get('actual_resource_receipts', [])
                       if _read_reference(r).get('output') == _reference(calculated)]
            _require(len(matches) == 1, 'The actual recovered workbook needs one matching resource receipt')
            result['resource_recalculation'] = matches[0]
            public = json.loads((replay / 'public_specification.json').read_text())
            bindings = json.loads((replay / 'public_definitions.json').read_text())
            forward = json.loads((replay / 'public_forward_ledger.json').read_text())
            audit = audit_public_recovered(calculated, public, forward['plan'], forward, bindings)
            with (attempt / 'public_cache_audit.json').open('x') as stream: json.dump(audit, stream, indent=2)
            _require(audit['passed'] and _public_execution_valid(ctx, result), 'The full public cache or actual resource evidence failed')
            comparison = compare_workbooks(ctx.data['input'], ctx.data['goal'], calculated); result['comparison'] = comparison
            if comparison.get('reward') == 1:
                shutil.copy2(calculated, ctx.revision_dir / 'private/recovered.xlsx')
                result.update(replay_output_sha256=_sha(replay / 'output.xlsx'), recovered_sha256=_sha(calculated))
                result['witness_binding'] = _witness_binding(ctx, result); result['verified'] = True
        except CooperativeCancelled:
            result.update(status='cancelled', error='Explicit cooperative stop; no public recovery certified'); raise
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error))
        finally:
            result.update(usage_calls=[], usage_attribution='not_applicable_programmatic', finished_at=utcnow())
            result.setdefault('status', 'verified' if result['verified'] else 'unverified')
            raw = (json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n').encode()
            with (attempt / 'attempt.json').open('xb') as stream: stream.write(raw)
            with (attempt / 'attempt.sha256').open('x') as stream: stream.write(hashlib.sha256(raw).hexdigest() + '\n')
            (attempt / 'attempt.json').chmod(0o444); (attempt / 'attempt.sha256').chmod(0o444)
            result['attempt_record_sha256'] = hashlib.sha256(raw).hexdigest(); ctx.save('independent_recovery.json', result)
        return {'recovery': result}
