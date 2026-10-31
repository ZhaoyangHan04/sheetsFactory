"""One fixed HiGHS engineering attempt using the frozen two-CPU lifecycle.

This module prepares exact matrix/code/dependency copies. Execution remains an
explicit action. It never admits references or changes the image or old vendor.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import ModuleType

from . import highs_engineering as engineering, model_a

UPSTREAM = Path(__file__).resolve().parents[1]/'linear_capital_portfolio/optimization_runtime.py'
UPSTREAM_SHA256 = 'fb1031c555fed919830a1f05fdb95bfa8912d2116fd6904801cfaba131a948ea'
DISTRIBUTIONS = {'highspy': '1.15.1', 'numpy': '1.26.4'}
WHEEL_SHA256 = '9730647160a6481426729f46d9989a0507d05f3cf96f9fb180f4ab9891bea67b'
WHEEL_BYTES = 5034168
WHEEL_URL = 'https://files.pythonhosted.org/packages/82/6b/18bec60d8585df860b8d33d310e99e7893eaabe3c8e9ebfa7e387ba9d2a4/highspy-1.15.1-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl'
APPROVED_NUMPY_ROOT = Path(__file__).resolve().parents[4]/'outputs/tmp/linear-solver-914-py312/lib/python3.12/site-packages'
VENDOR_ROOTS = {'highspy', 'highspy-1.15.1.dist-info', 'numpy', 'numpy.libs', 'numpy-1.26.4.dist-info'}
SOURCE_NAMES = {'spec.py', 'frozen_spec.py', 'model_a.py', 'frozen_model_a.py', 'highs_engineering.py'}
PREPARATION_KIND = 'prepared_private_linear_capital_scaled_highs2_engineering'
TERMINAL_KIND = 'private_linear_capital_scaled_highs2_engineering_execution'


def adapted_ast():
    raw = UPSTREAM.read_bytes()
    engineering.require(UPSTREAM == UPSTREAM.resolve() and hashlib.sha256(raw).hexdigest() == UPSTREAM_SHA256,
        'The frozen two-CPU lifecycle changed')
    tree = ast.parse(raw, filename=str(UPSTREAM)); counts = {}
    def changed(key): counts[key] = counts.get(key, 0)+1
    strings = {
        'prepared_private_linear_capital_integer_solver': PREPARATION_KIND,
        'private_linear_capital_integer_solver_execution': TERMINAL_KIND,
        'sf-private-integer-': 'sf-scaled-highs2-engineering-',
        '/sf-private-integer-': '/sf-scaled-highs2-engineering-',
        'private_reference_time_limit_seconds': 'native_engineering_time_limit_seconds',
        'Private integer reference solve': 'Unseeded scaled HiGHS engineering screen',
    }
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in strings:
                before = node.value; node.value = strings[before]; changed(before)
            return node
        def visit_FunctionDef(self, node):
            if node.name in ('prepare', 'execute_prepared'):
                marker = 'prepared_at' if node.name == 'prepare' else 'requested_resources'
                for item in ast.walk(node):
                    if isinstance(item, ast.Dict) and any(isinstance(key, ast.Constant) and key.value == marker for key in item.keys):
                        for key, value in [('reference_admission', False), ('hardness_certified', False),
                            ('dependency_version_equivalence_to_M02', 'unknown')]:
                            item.keys.append(ast.Constant(key)); item.values.append(ast.Constant(value))
                        changed(node.name+'_claim_boundary')
            if node.name == 'execute_prepared':
                class NativeOptions(ast.NodeTransformer):
                    def visit_If(self, item):
                        if ast.unparse(item.test) == "frozen['request']['backend'] == 'scip'":
                            changed('highs_parameters')
                            return ast.parse('_check_highs_parameters(solver, frozen)').body[0]
                        return self.generic_visit(item)
                node = NativeOptions().visit(node)
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    expected = {key: 1 for key in strings}; expected['/sf-private-integer-'] = 1
    expected.update(highs_parameters=1, prepare_claim_boundary=1, execute_prepared_claim_boundary=1)
    engineering.require(counts == expected, 'The exact HiGHS lifecycle substitutions changed: '+str(counts))
    return ast.fix_missing_locations(tree)


RUNNER = r'''import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib,importlib.metadata,json,time,traceback
root=Path('/app');sys.path.insert(0,str(root/'vendor'))
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()
start=time.monotonic()
try:
 inv=json.loads((root/'inventory.json').read_text())
 for name,r in inv.items():
  p=root/name
  if not p.is_file() or p.is_symlink() or sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:raise ValueError('Engineering input/code/vendor changed')
 if {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}!=set(inv)|{'inventory.json'}:raise ValueError('Unexpected engineering input file')
 job=json.loads((root/'job.json').read_text());model=json.loads((root/'model.json').read_text())
 versions={name:importlib.metadata.version(name) for name in job['distribution_versions']}
 if versions!=job['distribution_versions']:raise ValueError('Engineering dependency versions changed')
 import numpy,highspy
 paths={'numpy':numpy.__file__,'highspy':highspy.__file__}
 if not all(path.startswith('/app/vendor/'+name+'/') for name,path in paths.items()):raise ValueError('Engineering dependency import escaped frozen vendor')
 from portfolio.highs_engineering import solve_highs
 if job['backend']!='highs' or job['time_limit_seconds']!=800 or job['threads']!=2 or job['exclude_plan'] is not None:raise ValueError('The fixed engineering request changed')
 result=solve_highs(model,time_limit_seconds=800,threads=2,exclude_plan=None,log_path=root/'solver.log',model_path=root/'native_model.lp')
 (root/'solver_result.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 for name,r in inv.items():
  p=root/name
  if sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:raise ValueError('Engineering input changed during execution')
 runtime={'completed':True,'backend':'highs','model_canonical_sha256':hashlib.sha256(canonical(model)).hexdigest(),'elapsed_seconds':time.monotonic()-start,'distribution_versions':versions,'dependency_import_paths':paths,'financial_forward_executed':False,'gap_requested':0,'threads':2,'solver_result':'solver_result.json','reference_admission':False,'optimizer_calls':1,'retry_count':0}
 (root/'runtime_result.json').write_text(json.dumps(runtime,indent=2,allow_nan=False)+'\n');print(json.dumps(runtime),flush=True)
except BaseException as error:
 (root/'runtime_error.json').write_text(json.dumps({'type':type(error).__name__,'error':str(error),'elapsed_seconds':time.monotonic()-start},indent=2)+'\n');traceback.print_exc();sys.exit(1)
'''


def _source_files():
    model_a.adapted_ast()
    files = {name+'.py': path for name, path in model_a.source_files().items()}
    files['highs_engineering.py'] = Path(engineering.__file__)
    engineering.require(set(files) == SOURCE_NAMES, 'The matrix-only engineering code closure changed')
    return files


def build_runtime(vendor_lock, dependency_probe):
    """Create one isolated lifecycle bound to exact reviewed dependency files."""
    runtime = ModuleType(__name__+'._isolated')
    runtime.__file__ = __file__; runtime.__package__ = __package__
    exec(compile(adapted_ast(), __file__, 'exec'), runtime.__dict__)
    lock_ref, probe_ref = runtime.reference(vendor_lock), runtime.reference(dependency_probe)
    lock, probe = runtime._read(vendor_lock), runtime._read(dependency_probe)
    def dependencies():
        adapted_ast()
        engineering.require(runtime.reference(lock_ref['path']) == lock_ref
            and runtime.reference(probe_ref['path']) == probe_ref, 'The dependency lock or import probe changed')
        engineering.require(lock['kind'] == 'prepared_isolated_highs_numpy_vendor' and type(lock['version']) is int
            and lock['version'] == 1 and lock['distributions'] == DISTRIBUTIONS
            and lock['wheel_sha256'] == WHEEL_SHA256 and lock['wheel']['sha256'] == WHEEL_SHA256
            and set(lock['package_roots']) == VENDOR_ROOTS, 'The reviewed HiGHS dependency policy changed')
        for key in ('official_metadata', 'wheel'):
            engineering.require(runtime.reference(lock[key]['path']) == lock[key], 'A pinned official dependency artifact changed')
        metadata = runtime._read(lock['official_metadata']['path'])
        wheel_rows = [row for row in metadata['urls'] if row['url'] == WHEEL_URL]
        engineering.require(metadata['info']['name'] == 'highspy' and metadata['info']['version'] == '1.15.1'
            and lock['wheel_url'] == WHEEL_URL and lock['wheel']['bytes'] == WHEEL_BYTES
            and len(wheel_rows) == 1 and wheel_rows[0]['digests']['sha256'] == WHEEL_SHA256
            and wheel_rows[0]['size'] == WHEEL_BYTES, 'The exact official wheel metadata changed')
        engineering.require(probe.get('passed') is True and probe.get('optimizer_calls') == 0
            and type(probe.get('optimizer_calls')) is int and probe.get('native_solver_instantiated') is False
            and probe['vendor_lock'] == lock_ref and probe['image_id'] == runtime.IMAGE_ID
            and probe['imported']['versions'] == DISTRIBUTIONS and probe['cleanup']['passed'] is True,
            'A completed no-solve dependency import probe with owned cleanup is required')
        engineering.require(probe['imported']['paths'] == {'numpy': '/vendor/numpy/__init__.py',
                'highspy': '/vendor/highspy/__init__.py'}
            and probe['before']['Id'] == probe['after']['Id'] == probe['container_id']
            and probe['before']['State']['Status'] == 'created'
            and probe['after']['State']['Status'] == 'exited'
            and probe['after']['State']['Running'] is False
            and probe['after']['State']['ExitCode'] == 0
            and probe['after']['State']['OOMKilled'] is False,
            'The exact dependency import paths or completed container identity changed')
        for stage in ('before', 'after'):
            actual = probe[stage]
            engineering.require(actual['Image'] == runtime.IMAGE_ID and actual['NanoCpus'] == 2*10**9
                and actual['Memory'] == 32*1024**3 and actual['PidsLimit'] == 256
                and actual['NetworkMode'] == 'none' and actual['ReadOnly'] is True
                and len(actual['Mounts']) == 1 and actual['Mounts'][0]['Source'] == lock['vendor_root']
                and actual['Mounts'][0]['Destination'] == '/vendor' and actual['Mounts'][0]['RW'] is False,
                'The dependency import probe did not use the exact pinned isolated image')
        engineering.require(runtime._inventory(lock['vendor_root']) == lock['vendor_inventory'], 'A complete frozen dependency byte changed')
        numpy_names = {name for name in lock['vendor_inventory'] if Path(name).parts[0] in
            {'numpy','numpy.libs','numpy-1.26.4.dist-info'}}
        engineering.require(numpy_names == set(lock['numpy_source_inventory']), 'The complete approved NumPy source inventory is required')
        for name, row in lock['numpy_source_inventory'].items():
            copied = lock['vendor_inventory'][name]
            engineering.require(Path(row['path']) == APPROVED_NUMPY_ROOT/name
                and runtime.reference(row['path']) == row
                and (row['sha256'], row['bytes']) == (copied['sha256'], copied['bytes']),
                'The approved original NumPy source changed')
        return lock
    dependencies()
    runtime.VENDOR_SITE_PACKAGES = Path(lock['vendor_root'])
    runtime.VENDOR_ROOTS = set(VENDOR_ROOTS); runtime.DISTRIBUTIONS = dict(DISTRIBUTIONS)
    runtime.BACKENDS = {'highs': ('highs_engineering', 'solve_highs', 'native_model.lp')}
    runtime.CODE_FILES = tuple(sorted(SOURCE_NAMES)); runtime.RUNNER = RUNNER
    runtime._source_files = _source_files
    def validate_model(model):
        engineering.require(model.get('kind') == model_a.KIND and type(model.get('version')) is int and model['version'] == 2,
            'Use only the new scaled integer model namespace')
        return engineering.validate_model(model)
    runtime.validate_model = validate_model
    def options(solver, frozen):
        engineering.require(solver.get('kind') == engineering.SCREEN_KIND and type(solver.get('version')) is int
            and solver['version'] == 1 and solver.get('completed') is True
            and solver.get('parameters') == engineering.PARAMETERS
            and type(solver.get('threads')) is int and solver['threads'] == 2
            and type(solver.get('time_limit_seconds')) is int and solver['time_limit_seconds'] == 800
            and solver.get('incumbent_seed') is None and solver.get('known_objective_cut') is None
            and type(solver.get('optimizer_calls')) is int and solver['optimizer_calls'] == 1
            and type(solver.get('retry_count')) is int and solver['retry_count'] == 0,
            'The fixed unseeded HiGHS settings changed')
    runtime._check_highs_parameters = options
    def check_result(model, result, exclude_plan=None):
        validate_model(model)
        engineering.require(exclude_plan is None and result.get('checked_optimal') is False
            and result.get('reference_admission') is False and result.get('reference_admission_permitted') is False
            and result.get('formal_global_certificate_claimed') is False
            and result.get('floating_native_gap_is_not_formal_proof') is True
            and result.get('transformation') == engineering.scaled_model(model),
            'Engineering observations cannot admit a reference or change matrix transformations')
        exact = result.get('exact_integer_check'); plan = result.get('plan')
        if exact is not None:
            values = [exact['plan'][pid] for pid in model['project_ids']]
            engineering.require(exact == engineering.exact_plan_check(model, values), 'Every original exact row must be retained and rechecked')
        if plan is not None:
            engineering.require(exact is not None and exact['passed'] is True and plan == exact['plan']
                and type(result.get('objective_pence')) is int and result['objective_pence'] == exact['objective_pence'],
                'The engineering candidate differs from its complete exact row audit')
        else: engineering.require(result.get('objective_pence') is None, 'An absent candidate has no objective')
        return {'status': 'engineering_exact_feasible_incumbent' if plan is not None else 'engineering_no_exact_feasible_incumbent',
            'checked_optimal': False, 'native_status': result['raw_status'], 'exact_matrix_plan_check': exact,
            'reference_admission': False, 'formal_global_certificate_claimed': False}
    runtime.check_result = check_result
    base_prepare, base_validate = runtime.prepare, runtime.validate_prepared
    def prepare(model_json, output, *, backend='highs', time_limit_seconds=800, exclude_plan=None):
        dependencies()
        engineering.require(backend == 'highs' and type(time_limit_seconds) is int and time_limit_seconds == 800
            and exclude_plan is None, 'One fixed unseeded 800-second HiGHS attempt is required')
        return base_prepare(model_json, output, backend='highs', time_limit_seconds=800,
            exclude_plan=None, vendor_site_packages=runtime.VENDOR_SITE_PACKAGES)
    def validate_prepared(output):
        dependencies(); frozen = base_validate(output); request = frozen['request']
        engineering.require(request['backend'] == 'highs' and type(request['time_limit_seconds']) is int
            and request['time_limit_seconds'] == 800 and request['exclude_plan'] is None,
            'The fixed 800-second unseeded engineering attempt changed')
        return frozen
    runtime.prepare = prepare; runtime.validate_prepared = validate_prepared
    runtime.dependency_lock = lock_ref; runtime.dependency_probe = probe_ref
    return runtime
