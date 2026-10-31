"""Research-only third solver for an already checked direct integer matrix.

No financial forward or other solver is called. Only the bundled public wheel
license is used, inside the isolated /app job. This grants no commercial use.
"""
from contextlib import contextmanager
import ast
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import time

MATRIX_UPSTREAM_SHA256 = 'fb1031c555fed919830a1f05fdb95bfa8912d2116fd6904801cfaba131a948ea'


def matrix_checks_ast():
    folder = Path(__file__).resolve().parent
    path = folder/'frozen_optimization_runtime.py'
    if not path.is_file(): path = folder/'optimization_runtime.py'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MATRIX_UPSTREAM_SHA256:
        raise ValueError('The frozen pure integer matrix checks changed')
    wanted = {'_require', '_integer', 'validate_model', '_plan', 'check_result'}
    tree = ast.parse(raw); tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    if {n.name for n in tree.body} != wanted: raise ValueError('A pure integer matrix gate is missing')
    return ast.fix_missing_locations(tree)


exec(compile(matrix_checks_ast(), __file__, 'exec'), globals())

VERSION = '13.0.0'
EMBEDDED_LICENSE_SHA256 = 'bfd93a10cf47cee70f6a2bbc5938e4da380db896bcfabd9c5d08fb7e8bb8e408'


def require(value, message):
    if not value: raise ValueError(message)


def reference(path):
    path = Path(path).absolute(); require(path == path.resolve() and path.is_file(), 'A real research artifact is required')
    raw = path.read_bytes(); return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_request(model, excluded):
    model = validate_model(model)
    require(len(model['project_ids']) <= 2000 and len(model['rows'])+int(excluded is not None) <= 2000,
        'The public size-limited license permits at most 2000 variables and linear constraints')
    excluded = None if excluded is None else _plan(model['project_ids'], excluded)
    return model, excluded


@contextmanager
def restricted_environment(log_path):
    require(Path.cwd() == Path('/app'), 'Start the research solver only inside the isolated /app container')
    require(not Path('gurobi.env').exists() and not Path('gurobi.lic').exists(), 'No job-local license or parameter override is allowed')
    package = importlib.util.find_spec('gurobipy')
    require(package is not None and package.origin is not None, 'The isolated gurobipy package is unavailable')
    license_path = Path(package.origin).parent/'.libs/gurobi.lic'
    record = reference(license_path)
    require(record['sha256'] == EMBEDDED_LICENSE_SHA256, 'The approved public wheel license changed')
    # Explicit selection prevents any personal/default host license lookup.
    previous = os.environ.get('GRB_LICENSE_FILE')
    os.environ['GRB_LICENSE_FILE'] = str(license_path)
    try:
        gp = importlib.import_module('gurobipy')
        require(gp.__version__ == VERSION, 'The pinned research solver version changed')
        with gp.Env(empty=True) as env:
            env.setParam('LogFile', str(log_path)); env.setParam('LogToConsole', 0)
            # No remote/server credentials are supplied or read by this program.
            for key in ('ComputeServer', 'TokenServer', 'CSManager', 'WLSAccessID', 'WLSSecret', 'CloudAccessID', 'CloudSecretKey'):
                env.setParam(key, '')
            env.setParam('LicenseID', 0); env.start()
            yield gp, env, record
    finally:
        if previous is None: os.environ.pop('GRB_LICENSE_FILE', None)
        else: os.environ['GRB_LICENSE_FILE'] = previous


def solve_gurobi(model, *, time_limit_seconds, threads=16, exclude_plan=None, log_path=None, model_path=None):
    started = time.monotonic(); model, excluded = validate_request(model, exclude_plan)
    require(type(time_limit_seconds) is int and 1 <= time_limit_seconds <= 3600, 'Use a fixed research time limit at most 3600 seconds')
    require(type(threads) is int and threads == 16, 'The research profile requires exactly sixteen workers')
    require(log_path is not None and model_path is not None, 'Retain native model, parameters and complete solver log')
    log_path, model_path = Path(log_path).absolute(), Path(model_path).absolute()
    parameters_path = Path(str(model_path)+'.parameters.prm')
    require(len({log_path, model_path, parameters_path}) == 3
        and all(p == p.resolve() and not p.exists() for p in (log_path, model_path, parameters_path)),
        'Use fresh separate native research artifacts')
    result = {'backend': 'gurobi_restricted_research', 'solver_version': VERSION, 'status': 'NOT_STARTED',
        'raw_status': None, 'checked_optimal': False, 'plan': None, 'objective_pence': None,
        'exclude_plan': excluded, 'model_sha256': canonical(model),
        'specification_sha256': model['specification_sha256'], 'universe_sha256': model['universe_sha256'],
        'threads': threads, 'time_limit_seconds': time_limit_seconds, 'gap_parameters': {'relative': 0, 'absolute': 0},
        'formal_global_certificate': False, 'financial_forward_executed': False,
        'research_evaluation_only': True, 'personal_or_remote_license_used': False, 'second_solve_automatically_started': False}
    with restricted_environment(log_path) as (gp, env, license_ref):
        with gp.Model('private_linear_capital_research', env=env) as native:
            native.Params.Threads = threads; native.Params.TimeLimit = time_limit_seconds
            native.Params.MIPGap = 0; native.Params.MIPGapAbs = 0
            variables = [native.addVar(vtype=gp.GRB.BINARY, name=pid) for pid in model['project_ids']]
            for row in model['rows']:
                native.addConstr(gp.LinExpr(row['coefficients'], variables) <= row['limit'], name=row['id'])
            native.setObjective(gp.LinExpr(model['objective_pence'], variables), gp.GRB.MAXIMIZE)
            if excluded is not None:
                bits = [excluded[pid] for pid in model['project_ids']]
                native.addConstr(gp.LinExpr([-1 if b else 1 for b in bits], variables) >= 1-sum(bits),
                    name='complete_winner_Hamming_no_good')
            native.update(); native.write(str(model_path)); native.write(str(parameters_path))
            native.optimize()  # Exactly one native solve; no tuning or retry.
            status = int(native.Status)
            result.update(raw_status=status, status='OPTIMAL' if status == gp.GRB.OPTIMAL else 'TIME_LIMIT' if status == gp.GRB.TIME_LIMIT else 'NATIVE_STATUS_'+str(status),
                solver_wall_seconds=float(native.Runtime), solution_count=int(native.SolCount),
                embedded_public_license=license_ref, native_variables=int(native.NumVars), native_linear_constraints=int(native.NumConstrs),
                parameters={'Threads': int(native.Params.Threads), 'TimeLimit': float(native.Params.TimeLimit),
                    'MIPGap': float(native.Params.MIPGap), 'MIPGapAbs': float(native.Params.MIPGapAbs)},
                feasibility_tolerances_changed=False)
            if native.SolCount:
                raw = [float(v.X) for v in variables]
                require(all(math.isfinite(v) and min(abs(v), abs(v-1)) <= 1e-5 for v in raw), 'A native choice is not binary')
                plan = {pid: int(v >= .5) for pid, v in zip(model['project_ids'], raw)}
                objective = sum(c*plan[pid] for c, pid in zip(model['objective_pence'], model['project_ids']))
                result.update(plan=plan, objective_pence=objective, reported_objective=float(native.ObjVal),
                    reported_best_bound=float(native.ObjBound), reported_gap=float(native.MIPGap))
                require(math.isfinite(result['reported_objective']) and abs(result['reported_objective']-objective) <= 1e-5,
                    'The native objective differs from the exact integer objective')
                check_result(model, result, excluded)
                if status == gp.GRB.OPTIMAL:
                    require(math.isfinite(result['reported_best_bound']) and abs(result['reported_best_bound']-objective) <= 1e-5
                        and result['reported_gap'] == 0, 'The OPTIMAL native bound does not close the exact integer objective')
                    result['checked_optimal'] = True
            require(result['native_variables'] == len(model['project_ids'])
                and result['native_linear_constraints'] == len(model['rows'])+int(excluded is not None), 'The actual native model scope differs')
    result.update(elapsed_seconds=time.monotonic()-started, log_reference=reference(log_path),
        model_reference=reference(model_path), parameters_reference=reference(parameters_path))
    return result
