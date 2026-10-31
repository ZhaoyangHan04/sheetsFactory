"""SHA-bound supplied-mask forwards, separate from search and optimum proofs.

Core B checks an A partition and core A checks a B partition. Only the selected
core's frozen raw reader and unchanged financial forward are compiled. A caller
must separately prove that the supplied masks contain every partition leaf.
Preparation never compiles or executes; execution is an explicit operation.
"""
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import uuid

from . import spec

MASK = struct.Struct('<Q')
RECORD = struct.Struct('<QQqqq')
RECORD_BYTES = 40
NULL_NPV = -(1 << 63)
CHUNK_ROWS = 65536
KERNEL = Path(__file__).with_suffix('.cpp')
PREPARED_KIND = 'prepared_sparse_capital_supplied_mask_crosscheck'
EXECUTION_KIND = 'sparse_capital_supplied_mask_crosscheck_execution'


def reference(path):
    path = Path(path).absolute()
    spec.require(path == path.resolve() and path.is_file(), 'Evidence requires a real nonsymlink file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def checked(value):
    if isinstance(value, dict):
        spec.require(set(value) == {'path', 'sha256', 'bytes'} and reference(value['path']) == value,
                     'Immutable evidence changed')
        return Path(value['path'])
    path = Path(value).absolute()
    reference(path)
    return path


def _json(value):
    return json.loads(checked(value).read_text())


def _write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def _positive(value):
    spec.require(type(value) is int and 0 < value < 10**18, 'A bounded positive literal limit is required')
    return value


def _count(value):
    spec.require(type(value) is str and value == str(int(value)) and int(value) >= 0,
                 'A canonical nonnegative count string is required')
    return int(value)


def _core(core):
    spec.require(type(core) is str and core in ('A', 'B'), 'Select checking financial core A or B')
    return importlib.import_module('.search_' + core.lower(), __package__)


def _reader(core, module):
    text = checked(module.KERNEL).read_text()
    start, end = (('static Public sparse_public(const char* path) {', '\nstruct Cut') if core == 'A' else
                  ('static I bounded(std::istream& in,I low,I high)', '\nstruct BRow'))
    spec.require(text.count(start) == 1 and text.count(end) == 1, 'The frozen public reader boundaries changed')
    fragment = text[text.index(start):text.index(end)]
    spec.require('int main(' not in fragment, 'Only the raw reader may be extracted')
    return fragment


def _recipe(core):
    module = _core(core)
    module.assert_template()
    return {name: reference(path) for name, path in {
        'checker_python': __file__, 'checker_cpp': KERNEL, 'schema': spec.__file__,
        'raw_serializer': module.__file__, 'raw_reader_source': module.KERNEL,
        'frozen_financial_forward': module.TEMPLATE}.items()}


def _claims():
    return {'optimizer_runs': 0, 'model_calls': 0, 'LO_calls': 0,
            'optimum_certified': False, 'complete_partition_coverage_certified': False,
            'all_financial_journal_fields_checked': False, 'two_searches_certified': False,
            'source_quality_or_difficulty_certified': False}


def _claims_match(value):
    return all(type(value.get(key)) is type(flag) and value[key] == flag for key, flag in _claims().items())


def _mask_count(path, n, cap):
    size = path.stat().st_size
    spec.require(size > 0 and size % MASK.size == 0, 'A nonempty complete uint64 mask stream is required')
    count = size // MASK.size
    spec.require(count <= cap, 'Supplied mask count exceeds its explicit cap')
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK_ROWS * MASK.size), b''):
            spec.require(len(block) % MASK.size == 0, 'Mask stream changed during reading')
            spec.require(all(row[0] < 1 << n for row in MASK.iter_unpack(block)), 'Mask exceeds public dimension')
    return count


def prepare_inputs(public, masks, directory, *, core, max_masks, max_ms):
    """Freeze exact public primitives and ordered masks; perform zero forwards."""
    public = spec.load_spec(public)
    max_masks, max_ms = _positive(max_masks), _positive(max_ms)
    module = _core(core)
    recipe = _recipe(core)
    mask_path = checked(masks)
    original = reference(mask_path)
    count = _mask_count(mask_path, len(public['projects']), max_masks)
    directory = Path(directory).absolute()
    spec.require(directory == directory.resolve() and not directory.exists(), 'A fresh real preparation directory is required')
    directory.mkdir(parents=True)
    _write(directory / 'public.json', public)
    raw = module._public_wire(public) if core == 'A' else module._raw(public)
    for name, text in {'public_raw.txt': raw, 'public_reader.inc': _reader(core, module)}.items():
        with (directory / name).open('x') as stream:
            stream.write(text)
    with mask_path.open('rb') as source, (directory / 'masks.u64le').open('xb') as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    spec.require(reference(mask_path) == original and reference(directory / 'masks.u64le')['sha256'] == original['sha256']
                 and (directory / 'masks.u64le').stat().st_size == original['bytes'], 'Mask stream changed during preparation')
    value = {'kind': PREPARED_KIND, 'version': 1, 'checking_financial_core': core,
             'checks_partition_backend': 'B' if core == 'A' else 'A',
             'public_spec_sha256': spec.canonical_sha(public), 'project_count': len(public['projects']),
             'row_count': str(count), 'limits': {'max_masks': str(max_masks), 'max_ms': str(max_ms)},
             'record_format': '<QQqqq', 'record_bytes': RECORD_BYTES, 'mask_format': '<Q',
             'public': reference(directory / 'public.json'), 'raw_public': reference(directory / 'public_raw.txt'),
             'public_reader': reference(directory / 'public_reader.inc'),
             'masks': reference(directory / 'masks.u64le'), 'original_masks': original,
             'recipe': recipe, 'compiler_runs': 0, **_claims()}
    spec.require(_recipe(core) == recipe, 'Recipe changed during preparation')
    _write(directory / 'preparation.json', value)
    return value


def validate_prepared(preparation):
    """Rehash the prepared stream, reader and recipe without financial execution."""
    if not isinstance(preparation, dict) and Path(preparation).is_dir():
        preparation = Path(preparation) / 'preparation.json'
    value = _json(preparation)
    core = value.get('checking_financial_core')
    module = _core(core)
    spec.require(value.get('kind') == PREPARED_KIND and type(value.get('version')) is int and value['version'] == 1,
                 'Wrong supplied-mask preparation')
    spec.require(value['recipe'] == _recipe(core), 'Prepared checker recipe changed')
    for key in ('public', 'raw_public', 'public_reader', 'masks', 'original_masks'):
        checked(value[key])
    public = spec.load_spec(value['public']['path'])
    spec.require(value['public_spec_sha256'] == spec.canonical_sha(public)
                 and value['project_count'] == len(public['projects'])
                 and value['checks_partition_backend'] == ('B' if core == 'A' else 'A')
                 and value['record_format'] == '<QQqqq' and value['record_bytes'] == RECORD_BYTES
                 and value['mask_format'] == '<Q', 'Prepared public or protocol binding differs')
    spec.require(value['limits'] == {key: str(_positive(int(value['limits'][key]))) for key in ('max_masks', 'max_ms')},
                 'Noncanonical checker limits')
    raw = module._public_wire(public) if core == 'A' else module._raw(public)
    spec.require(checked(value['raw_public']).read_text() == raw
                 and checked(value['public_reader']).read_text() == _reader(core, module), 'Prepared raw reader or public wire differs')
    count = _mask_count(checked(value['masks']), len(public['projects']), int(value['limits']['max_masks']))
    spec.require(value['row_count'] == str(count)
                 and all(value['masks'][key] == value['original_masks'][key] for key in ('sha256', 'bytes')),
                 'Prepared ordered mask binding differs')
    spec.require(_claims_match(value) and type(value['compiler_runs']) is int and value['compiler_runs'] == 0,
                 'Preparation makes unsupported claims')
    return value, public


def validate_output(outcomes, masks, *, project_count, expected_count):
    """Check record identity/shape/count only; never substitute for finance."""
    path, mask_path = checked(outcomes), checked(masks)
    _positive(expected_count)
    spec.project_ids(project_count)
    spec.require(path.stat().st_size == expected_count * RECORD_BYTES
                 and mask_path.stat().st_size == expected_count * MASK.size, 'Incomplete or trailing output records')
    chunks = []
    count = 0
    with path.open('rb') as output, mask_path.open('rb') as source:
        while True:
            block = output.read(CHUNK_ROWS * RECORD_BYTES)
            if not block:
                break
            spec.require(len(block) % RECORD_BYTES == 0, 'Truncated checker record')
            number = len(block) // RECORD_BYTES
            originals = source.read(number * MASK.size)
            spec.require(len(originals) == number * MASK.size, 'Truncated supplied masks')
            for row, original in zip(RECORD.iter_unpack(block), MASK.iter_unpack(originals), strict=True):
                mask, flags, *npvs = row
                spec.require(mask == original[0] and mask < 1 << project_count and flags < 8,
                             'Output order, mask or feasibility flags differ')
                spec.require(all(bool(flags & (1 << index)) == (npv != NULL_NPV) for index, npv in enumerate(npvs)),
                             'Output feasibility and null NPV disagree')
            chunks.append({'start_row': str(count), 'end_row_exclusive': str(count + number),
                           'record_count': str(number), 'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
            count += number
        spec.require(source.read(1) == b'' and count == expected_count, 'Output row count differs')
    return chunks


def execute_prepared(preparation):
    """Explicitly compile and compute only the supplied stream, with fixed caps."""
    if not isinstance(preparation, dict) and Path(preparation).is_dir():
        preparation = Path(preparation) / 'preparation.json'
    preparation = reference(checked(preparation))
    frozen, public = validate_prepared(preparation)
    directory = Path(preparation['path']).parent / 'attempts' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    receipt = {'kind': EXECUTION_KIND, 'version': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
               'preparation': preparation, 'checking_financial_core': frozen['checking_financial_core'],
               'checks_partition_backend': frozen['checks_partition_backend'], 'public_spec_sha256': frozen['public_spec_sha256'],
               'masks': frozen['masks'], 'limits': frozen['limits'], 'recipe': frozen['recipe'],
               'row_count': '0', 'complete': False, 'passed': False, 'status': 'started', **_claims()}
    _write(directory / 'started.json', receipt)
    receipt['started'] = reference(directory / 'started.json')
    try:
        compiler = shutil.which('g++')
        spec.require(compiler is not None, 'g++ is required; no compiler is installed automatically')
        compiler = str(Path(compiler).resolve())
        version = subprocess.run([compiler, '--version'], capture_output=True, text=True, timeout=10, check=True)
        binary = directory / 'check_masks'
        command = [compiler, '-O3', '-std=c++17', '-static', '-DCHECK_FINANCIAL_' + frozen['checking_financial_core'],
                   '-I', str(Path(frozen['public_reader']['path']).parent), str(KERNEL), '-o', str(binary)]
        env = dict(os.environ, TMPDIR=str(directory))
        with (directory / 'compile.stdout').open('xb') as stdout, (directory / 'compile.stderr').open('xb') as stderr:
            compiled = subprocess.run(command, stdout=stdout, stderr=stderr, env=env, timeout=60)
        receipt['compilation'] = {'compiler': reference(compiler), 'version': version.stdout, 'command': command,
                                  'exit_code': compiled.returncode, 'stdout': reference(directory / 'compile.stdout'),
                                  'stderr': reference(directory / 'compile.stderr')}
        spec.require(compiled.returncode == 0, 'Checker compilation failed')
        receipt['compilation']['binary'] = reference(binary)
        validate_prepared(preparation)
        output, summary = directory / 'outcomes.bin', directory / 'native_summary.json'
        native = [str(binary), frozen['raw_public']['path'], frozen['masks']['path'], str(output), str(summary),
                  frozen['row_count'], frozen['limits']['max_masks'], frozen['limits']['max_ms']]
        receipt['native_command'] = native
        with (directory / 'native.stdout').open('xb') as stdout, (directory / 'native.stderr').open('xb') as stderr:
            done = subprocess.run(native, stdout=stdout, stderr=stderr, env=env,
                                  timeout=int(frozen['limits']['max_ms']) / 1000 + 60)
        receipt.update(exit_code=done.returncode, native_stdout=reference(directory / 'native.stdout'),
                       native_stderr=reference(directory / 'native.stderr'))
        if output.exists():
            receipt['outcomes'] = reference(output)
        if summary.exists():
            receipt['native_summary'] = reference(summary)
            observed = _json(receipt['native_summary'])
            receipt['row_count'] = observed.get('row_count', '0')
            receipt['financial_forward_calls'] = observed.get('financial_forward_calls')
            receipt['scenario_forward_calls'] = observed.get('scenario_forward_calls')
        spec.require(done.returncode == 0, 'Native checker did not complete')
        receipt['output_chunks'] = validate_output(receipt['outcomes'], frozen['masks'],
            project_count=len(public['projects']), expected_count=int(frozen['row_count']))
        receipt.update(complete=True, passed=True, status='completed')
        _validate_execution(receipt)
    except Exception as error:
        receipt.update(complete=False, passed=False, status='incomplete', error_type=type(error).__name__, error=str(error))
        for name in ('outcomes.bin', 'native_summary.json', 'native.stdout', 'native.stderr'):
            if (directory / name).exists():
                receipt.setdefault('retained_partial_artifacts', {})[name] = reference(directory / name)
    receipt.update(finished_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - began)
    _write(directory / 'receipt.json', receipt)
    return reference(directory / 'receipt.json')


def _validate_execution(value):
    spec.require(value.get('kind') == EXECUTION_KIND and type(value.get('version')) is int and value['version'] == 1
                 and value.get('complete') is True and value.get('passed') is True and value.get('status') == 'completed'
                 and value.get('exit_code') == 0, 'Incomplete supplied-mask execution is not evidence')
    frozen, public = validate_prepared(value['preparation'])
    for key in ('checking_financial_core', 'checks_partition_backend', 'public_spec_sha256', 'masks', 'limits', 'recipe', 'row_count'):
        spec.require(value[key] == frozen[key], 'Execution binding differs: ' + key)
    spec.require(_claims_match(value), 'Execution makes unsupported claims')
    started = _json(value['started'])
    spec.require(started.get('status') == 'started' and started.get('complete') is False and started.get('passed') is False
                 and all(started[key] == value[key] for key in ('kind', 'version', 'started_at', 'preparation',
                     'checking_financial_core', 'checks_partition_backend', 'public_spec_sha256', 'masks', 'limits', 'recipe')),
                 'Immutable before-start record differs')
    compilation = value['compilation']
    for key in ('compiler', 'binary', 'stdout', 'stderr'):
        checked(compilation[key])
    spec.require(compilation['exit_code'] == 0 and type(compilation['version']) is str and compilation['version'], 'Compilation failed')
    binary = compilation['binary']['path']
    expected_compile = [compilation['compiler']['path'], '-O3', '-std=c++17', '-static',
                        '-DCHECK_FINANCIAL_' + frozen['checking_financial_core'], '-I',
                        str(Path(frozen['public_reader']['path']).parent), str(KERNEL), '-o', binary]
    spec.require(compilation['command'] == expected_compile, 'Compilation command differs')
    native = _json(value['native_summary'])
    spec.require(native.get('kind') == 'sparse_capital_supplied_masks_native' and type(native.get('version')) is int
                 and native['version'] == 1 and native['complete'] is True and native['status'] == 'completed'
                 and native['stop_reason'] == '' and native['checking_financial_core'] == frozen['checking_financial_core'],
                 'Native forward stream is incomplete')
    count = int(frozen['row_count'])
    spec.require(native['expected_rows'] == native['row_count'] == native['financial_forward_calls'] == str(count)
                 and native['scenario_forward_calls'] == str(count * 3)
                 and native['max_masks'] == frozen['limits']['max_masks'] and native['max_ms'] == frozen['limits']['max_ms']
                 and _count(native['elapsed_nanoseconds']) < int(frozen['limits']['max_ms']) * 10**6
                 and type(native['optimizer_runs']) is int and native['optimizer_runs'] == 0 and native['optimum_certified'] is False
                 and native['source_quality_or_difficulty_certified'] is False, 'Native counts or limits differ')
    spec.require(value['financial_forward_calls'] == str(count) and value['scenario_forward_calls'] == str(count * 3), 'Forward counts differ')
    if frozen['checking_financial_core'] == 'A':
        spec.require(native['actual_scenario_year_states'] is None, 'A does not instrument actual scenario years')
    else:
        years = native['actual_scenario_year_states']
        spec.require(count * 3 <= _count(years) <= count * 60,
                     'B scenario year count is invalid')
    for key in ('native_stdout', 'native_stderr', 'outcomes'):
        checked(value[key])
    expected_native = [binary, frozen['raw_public']['path'], frozen['masks']['path'], value['outcomes']['path'],
                       value['native_summary']['path'], str(count), frozen['limits']['max_masks'], frozen['limits']['max_ms']]
    spec.require(value['native_command'] == expected_native, 'Native command differs')
    chunks = validate_output(value['outcomes'], frozen['masks'], project_count=len(public['projects']), expected_count=count)
    spec.require(value['output_chunks'] == chunks, 'Output chunk hashes differ')
    return value


def validate_execution(receipt, *, expected_core=None, expected_public_sha=None, expected_masks=None):
    """Read-only complete-forward validation; does not validate a partition."""
    value = _validate_execution(_json(receipt))
    if expected_core is not None:
        spec.require(value['checking_financial_core'] == expected_core, 'Wrong opposite financial core')
    if expected_public_sha is not None:
        spec.require(value['public_spec_sha256'] == expected_public_sha, 'Wrong public specification')
    if expected_masks is not None:
        expected = reference(checked(expected_masks))
        spec.require(all(value['masks'][key] == expected[key] for key in ('sha256', 'bytes')), 'Wrong complete leaf projection')
    return value
