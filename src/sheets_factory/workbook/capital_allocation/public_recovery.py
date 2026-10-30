"""Public-only complete investment search and the normal recovery receipt route."""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile


def _json_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate public contract key: ' + key)
        result[key] = value
    return result


def read_public_spec(book):
    from .spec import RULES, load_spec
    for name in ('Capital Rules', 'Capital Contract', 'Capital Inputs', 'Investment Plan',
                 'Capital Summary', 'Exact Arithmetic'):
        if name not in book:
            raise ValueError('Missing public financial worksheet: ' + name)
    chunks = []
    sheet = book['Capital Contract']
    for row in range(2, sheet.max_row + 1):
        label, cell = sheet.cell(row, 1), sheet.cell(row, 2)
        if label.value is None and cell.value is None:
            continue
        if label.value != 'JSON part ' + str(len(chunks) + 1) or cell.data_type == 'f' or not isinstance(cell.value, str):
            raise ValueError('Public contract chunks must be ordered labelled JSON literals')
        chunks.append(cell.value)
    if not chunks:
        raise ValueError('Missing complete public contract')
    spec = load_spec(json.loads(''.join(chunks), object_pairs_hook=_json_unique))
    if any(book['Capital Rules'].cell(index, 1).value != text for index, text in enumerate(RULES, 4)):
        raise ValueError('The public policy differs from the supported complete financial contract')
    def flatten(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from flatten(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from flatten(child, (*path, index))
        else:
            yield '/'.join(map(str, path)), value
    provided = {}
    inputs = book['Capital Inputs']
    for row in range(3, inputs.max_row + 1):
        name, cell = inputs.cell(row, 1).value, inputs.cell(row, 2)
        if name is None and cell.value is None:
            continue
        if not isinstance(name, str) or name in provided or cell.data_type == 'f':
            raise ValueError('Public primitive labels are missing, repeated or calculated')
        provided[name] = cell.value
    expected = dict(flatten(spec))
    if set(provided) != set(expected):
        raise ValueError('The labelled public inputs do not cover the complete contract')
    for key, value in expected.items():
        actual = provided[key]
        if type(value) is int:
            if isinstance(actual, bool) or type(actual) not in (int, float) or actual != value:
                raise ValueError('The public labelled integer differs from its JSON primitive: ' + key)
        elif type(actual) is not type(value) or actual != value:
            raise ValueError('The public labelled primitive differs from the contract: ' + key)
    return spec


def _choose_plan(spec, active_project_ids=None):
    from .spec import PROJECT_IDS
    from .verify import _Interpreter
    active = list(PROJECT_IDS if active_project_ids is None else active_project_ids)
    if len(set(active)) != len(active) or any(identifier not in PROJECT_IDS for identifier in active):
        raise ValueError('Invalid public recovery choice dimensions')
    indices = [PROJECT_IDS.index(identifier) for identifier in active]
    engine = _Interpreter(spec)
    best = second = winner = None
    count = 0
    plans = 1 << len(active)
    for mask in range(plans):
        full = sum(1 << index for bit, index in enumerate(indices) if mask & (1 << bit))
        result = engine.evaluate(full)
        value = result['objective_pence']
        if value is None:
            continue
        if best is None or value > best:
            second = best
            best, winner, count = value, full, 1
        elif value == best:
            second = best
            count += 1
        elif second is None or value > second:
            second = value
    if count != 1 or second is None or best - second < 1:
        raise ValueError('Public exhaustive search did not establish a unique best plan with a one-penny gap')
    return engine, winner, {'plan_count': plans, 'scenario_year_evaluations': plans * 60,
        'full_enumeration': active == list(PROJECT_IDS), 'toy_only': active != list(PROJECT_IDS),
        'unique_best': True, 'objective_pence': best, 'gap_pence': best - second}


def recover_public(source, destination, report_path=None, *, active_project_ids=None):
    """Read public labels/primitives only. No reference artifact is accepted."""
    import openpyxl
    from datetime import date, datetime
    from .spec import ANNUAL_FIELDS, PROJECT_FIELDS, PROJECT_IDS, SCENARIO_IDS, VINTAGE_FIELDS, YEARS
    from .verify import PROJECT_COLUMNS, _round_ratio, DENOMINATOR
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Public reconstruction cannot overwrite its input')
    book = openpyxl.load_workbook(source, keep_links=False)
    filled = set()
    try:
        spec = read_public_spec(book)
        solver, winner, enumeration = _choose_plan(spec, active_project_ids)
        solved = solver.evaluate(winner, details=True)
        if not solved['feasible']:
            raise ValueError('The independently selected common plan is infeasible')
        def put(sheet, row, column, value):
            key = sheet.title, row, column
            if key in filled:
                raise ValueError('A public financial binding was repeated')
            if value is not None and type(value) is not int:
                raise ValueError('A reconstructed financial value is not integer pence')
            sheet.cell(row, column, '' if value is None else value)
            filled.add(key)
        choices = {}
        for row in range(3, book['Investment Plan'].max_row + 1):
            identifier = book['Investment Plan'].cell(row, 1).value
            if identifier is None:
                continue
            if identifier not in PROJECT_IDS or identifier in choices:
                raise ValueError('Ambiguous public common-plan row')
            choices[identifier] = row
        if set(choices) != set(PROJECT_IDS):
            raise ValueError('The public worksheet is missing common project choices')
        for bit, identifier in enumerate(PROJECT_IDS):
            put(book['Investment Plan'], choices[identifier], 2, int(bool(winner & (1 << bit))))
        def rows(sheet, pair=False):
            result = {}
            for row in range(4, sheet.max_row + 1):
                label = (sheet.cell(row, 1).value, sheet.cell(row, 2).value) if pair else sheet.cell(row, 1).value
                if label == (None, None) or label is None:
                    continue
                if label in result:
                    raise ValueError('Ambiguous public financial row in ' + sheet.title)
                result[label] = row
            return result
        for index, identity in enumerate(SCENARIO_IDS):
            project_sheet, annual_sheet, vintage_sheet = (book[identity + suffix] for suffix in
                (' Projects', ' Annual', ' Tax Vintages'))
            for sheet in (project_sheet, annual_sheet, vintage_sheet):
                for column, year in enumerate(YEARS, 3):
                    value = sheet.cell(2, column).value
                    if (not isinstance(value, (date, datetime))
                            or (value.year, value.month, value.day) != (year, 3, 31)):
                        raise ValueError('The public financial fiscal-year calendar differs')
            project_rows, annual_rows, vintage_rows = rows(project_sheet, True), rows(annual_sheet), rows(vintage_sheet, True)
            if (set(project_rows) != {(p, f) for p in PROJECT_IDS for f in PROJECT_FIELDS}
                    or set(annual_rows) != set(ANNUAL_FIELDS)
                    or set(vintage_rows) != {(v, f) for v in YEARS for f in VINTAGE_FIELDS}):
                raise ValueError('The public financial row layout is incomplete or unsupported')
            actual = solved['scenarios'][index]
            previous_losses = [0] * 20
            for yi, year in enumerate(YEARS):
                column = yi + 3
                frame = actual['annual'][yi]
                for pi, identifier in enumerate(PROJECT_IDS):
                    start = yi * len(PROJECT_COLUMNS)
                    fields = dict(zip(PROJECT_COLUMNS, solver.projects[index][pi][start:start + len(PROJECT_COLUMNS)]))
                    fields['closing_book_value'], fields['certified_nav'] = fields.pop('book'), fields.pop('nav')
                    for field in PROJECT_FIELDS:
                        put(project_sheet, project_rows[identifier, field], column, fields[field])
                for field in ANNUAL_FIELDS:
                    put(annual_sheet, annual_rows[field], column, frame[field])
                for vi, vintage in enumerate(YEARS):
                    opening = previous_losses[vi]
                    expired = opening if year - vintage > spec['tax_loss_carry_years'] else 0
                    created = max(0, -frame['taxable_before_losses']) if vintage == year else 0
                    closing = frame['closing_loss_vintages'][vi]
                    values = {'opening': opening, 'expired': expired, 'created': created,
                        'closing': closing, 'used': opening - expired + created - closing}
                    if values['used'] < 0:
                        raise ValueError('Independent public tax-vintage conservation failed')
                    for field in VINTAGE_FIELDS:
                        put(vintage_sheet, vintage_rows[vintage, field], column, values[field])
                previous_losses = frame['closing_loss_vintages']
            summary = book['Capital Summary']
            if summary.cell(index + 3, 1).value != identity:
                raise ValueError('Public scenario summary identities differ')
            diagnostic = _round_ratio(int(actual['net_npv_numerator']), DENOMINATOR)
            put(summary, index + 3, 2, int(actual['feasible']))
            put(summary, index + 3, 3, diagnostic)
            put(summary, index + 3, 4, actual['npv_pence'])
        put(book['Capital Summary'], 7, 2, int(solved['feasible']))
        put(book['Capital Summary'], 7, 4, solved['objective_pence'])
        unbound = [sheet.title + '!' + cell.coordinate for sheet in book if sheet.title != 'Exact Arithmetic'
            for cell in sheet._cells.values() if cell.data_type == 'f'
            and (sheet.title, cell.row, cell.column) not in filled]
        if unbound:
            raise ValueError('Unbound public financial formulas remain: ' + repr(unbound[:8]))
        book.save(destination)
    finally:
        book.close()
    report = {'public_information_only': True, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'financial_and_decision_cells_reconstructed': len(filled), 'enumeration': enumeration,
        'assumptions_added': [], 'unresolved_questions': [],
        'private_reference_or_search_certificate_read': False,
        'provided_arithmetic_formulas_preserved': True, 'actual_LO_replay_still_required': True}
    if report_path is not None:
        Path(report_path).write_text(json.dumps(report, indent=2))
    return report


def compile_public_capital_recovery():
    """Bundle only public primitives/schema and the independent integer engine."""
    base = Path(__file__).resolve().parent
    parsed = ast.parse((base / 'verify.py').read_text())
    names = {'_require', '_round_ratio', '_project_schedules', '_Interpreter'}
    constants = {'DENOMINATOR', 'PROJECT_COLUMNS'}
    nodes = [node for node in parsed.body if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names)
        or (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in constants for target in node.targets))]
    integer_source = ('from __future__ import annotations\nimport hashlib, struct\n'
        'from .spec import ANNUAL_FIELDS, PROJECT_IDS, SCENARIO_IDS, YEARS\n'
        + ast.unparse(ast.Module(body=nodes, type_ignores=[])) + '\n')
    own = ast.parse(Path(__file__).read_text())
    functions = {'_json_unique', 'read_public_spec', '_choose_plan', 'recover_public'}
    public_source = ('from __future__ import annotations\nimport json, hashlib\nfrom pathlib import Path\n'
        + ast.unparse(ast.Module(body=[node for node in own.body
            if isinstance(node, ast.FunctionDef) and node.name in functions], type_ignores=[])) + '\n')
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        prefix = 'sheets_factory/workbook/capital_allocation/'
        def write(name, content):
            entry = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
        for name in ('sheets_factory/__init__.py', 'sheets_factory/workbook/__init__.py', prefix + '__init__.py'):
            write(name, '')
        write(prefix + 'spec.py', (base / 'spec.py').read_text())
        write(prefix + 'verify.py', integer_source)
        write(prefix + 'public_runtime.py', public_source)
    encoded = base64.b64encode(payload.getvalue()).decode()
    return ('import base64,io,sys,tempfile,zipfile\nfrom pathlib import Path\n'
        + 'directory=tempfile.mkdtemp(prefix="capital-public-")\n'
        + 'with zipfile.ZipFile(io.BytesIO(base64.b64decode(' + repr(encoded) + '))) as archive: archive.extractall(directory)\n'
        + 'sys.path.insert(0,directory)\n'
        + 'from sheets_factory.workbook.capital_allocation.public_runtime import recover_public\n'
        + 'recover_public(Path("input.xlsx"),Path("output.xlsx"),Path("public_recovery_report.json"))\n')


from ...nodes.quality import RecoveryNode


class CapitalAllocationRecoveryNode(RecoveryNode):
    """The ordinary isolated witness contract, with a separate public compiler."""
    node_id = 'independent_recovery'

    def execute(self, ctx):
        import shutil
        import subprocess
        import uuid
        from ...core.audit import utcnow
        from ...core.node import CooperativeCancelled, TaskRejected
        from ...nodes import quality as normal
        if normal.validate_reference_policy_selection(ctx.config) == 'reference_review':
            return super().execute(ctx)
        backend = ctx.config.get('recovery', {}).get('compiler_backend')
        timeout = ctx.config.get('recovery', {}).get('replay_timeout_seconds')
        if backend != 'capital_allocation_integer' or type(timeout) is not int or timeout != 1800:
            raise ValueError('The explicit capital recovery backend and 1800-second reference replay budget are required')
        if ctx.data.get('finance_evidence', {}).get('financial_seed_verified') is not True:
            raise TaskRejected('Public capital reconstruction requires a verified financial source')
        reusable = normal._reusable_recovery(ctx)
        if reusable is not None and reusable.get('compiler_backend') == backend and reusable.get('replay_timeout_seconds') == timeout:
            ctx.save('independent_recovery.json', reusable)
            ctx.audit.emit('recovery.witness_reused', task_id=ctx.task_id, revision=ctx.revision,
                attempt_id=reusable['attempt_id'], binding_sha256=hashlib.sha256(json.dumps(reusable['witness_binding'], sort_keys=True).encode()).hexdigest())
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
            'task_revision_hash': ctx.data.get('revision_hash'), 'compiler_backend': backend,
            'replay_timeout_seconds': timeout}
        try:
            work = normal.prepare_workspace(ctx, 'recovery_public')
            result['workspace'] = str(work)
            (work / 'public_profile.json').write_text(json.dumps(ctx.data.get('public_profile', {}), ensure_ascii=False))
            program = compile_public_capital_recovery()
            compile(program, 'recovery.py', 'exec')
            result['program'] = program
            result['compiler'] = {'code': program, 'public_evidence_used': [
                'Capital Rules, complete Capital Contract JSON, labelled Capital Inputs and financial row layouts'],
                'assumptions_added': [], 'unresolved_questions': [],
                'implementation': 'independent_public_integer_complete_eighteen_choice_search', 'is_llm_attempt': False}
            (work / 'recovery.py').write_text(program)
            replay = ctx.revision_dir / ('recovery_replay-' + uuid.uuid4().hex[:8])
            replay.mkdir(parents=True)
            shutil.copy2(ctx.data['input'], replay / 'input.xlsx')
            shutil.copy2(work / 'recovery.py', replay / 'recovery.py')
            command = normal._recovery_replay_command(ctx, replay)
            result['replay'] = {'directory': str(replay), 'returncode': None,
                'fresh_network_disabled_container': True,
                'initial_files': {'input.xlsx': normal._recovery_sha(replay / 'input.xlsx'),
                    'recovery.py': normal._recovery_sha(replay / 'recovery.py')}, 'command': command}
            execution = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            (attempt / 'replay.stdout.txt').write_text(execution.stdout)
            (attempt / 'replay.stderr.txt').write_text(execution.stderr)
            result['replay'].update(returncode=execution.returncode,
                stdout=execution.stdout[-4000:], stderr=execution.stderr[-4000:],
                stdout_file=str(attempt / 'replay.stdout.txt'), stderr_file=str(attempt / 'replay.stderr.txt'))
            if execution.returncode or not (replay / 'output.xlsx').is_file():
                raise ValueError('Public capital recovery did not produce an output in the isolated replay')
            calculated = ctx.engine.recalculate(replay / 'output.xlsx', attempt / 'recovered.xlsx')
            if not normal._recovery_public_execution_valid(ctx, result):
                raise ValueError('Public recovery execution is not bound to the unchanged exact public input')
            comparison = normal.compare_workbooks(ctx.data['input'], ctx.data['goal'], calculated)
            result['comparison'] = comparison
            if comparison.get('reward') == 1:
                shutil.copy2(calculated, ctx.revision_dir / 'private/recovered.xlsx')
                result.update(replay_output_sha256=normal._recovery_sha(replay / 'output.xlsx'),
                    recovered_sha256=normal._recovery_sha(calculated))
                result['witness_binding'] = normal._recovery_binding(ctx, result)
                result['verified'] = True
        except CooperativeCancelled:
            result.update(status='cancelled', error='Explicit cooperative stop before further recovery work')
            raise
        except Exception as exception:
            result.update(error=str(exception), error_type=type(exception).__name__)
        finally:
            result.update(usage_calls=[], usage_attribution='not_applicable_programmatic', finished_at=utcnow())
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
