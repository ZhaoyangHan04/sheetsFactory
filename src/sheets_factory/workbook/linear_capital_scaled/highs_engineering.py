"""Optional unseeded scaled HiGHS engineering; never reference admission.

The observed native M02 route scaled the objective by 1e6 and each retained
row by max(1, RHS, max(abs(coefficients))). This adapter preserves that route,
except that the requested absolute objective gap is zero rather than the
observed 1e-7. It imports HiGHS only when explicitly called. No lifecycle,
installation, network operation, financial forward or retry occurs here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

SCREEN_KIND = 'linear_capital_scaled_unseeded_highs2_engineering'
SCREEN_SECONDS = 800
MAX_SECONDS = 1800
OBJECTIVE_DIVISOR = 1_000_000
FEASIBILITY_TOLERANCE = 1e-9
PARAMETERS = {'time_limit':800.0, 'threads':2, 'mip_rel_gap':0.0,
    'mip_abs_gap':0.0, 'mip_feasibility_tolerance':FEASIBILITY_TOLERANCE}
LEGACY_KIND = 'linear_capital_portfolio_direct_binary_integer_model'
NATIVE_ROUTE_EVIDENCE = {
    'receipt_sha256':'05e689c4782a22802d1f52bc0ce32425e038be420e7d2eae3273ebe47a50eaed',
    'retained_solve_script_command_sha256':'ec65b7ea98db2ad87fefd8db5e1ff510605eff06d0bca7ecf56a4d4277c79313',
    'observed_absolute_gap':1e-7, 'requested_absolute_gap':0.0,
    'incumbent_or_gold_data_consumed':False,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()


def validate_model(model):
    """Accept only the unchanged old schema or the isolated N360 schema.

    The old validator runs in its own namespace over the exact frozen old
    source. No old module globals or public APIs are changed. Both validators
    enforce complete production family counts before any redundant row drops.
    Explicit one-to-four-project toy matrices retain their original contract.
    """
    from . import model_a
    require(isinstance(model, dict), 'The complete canonical engineering model is required')
    if model.get('kind') == model_a.KIND:
        return model_a.validate_model(model)
    require(model.get('kind') == LEGACY_KIND, 'Unknown engineering model schema')
    raw = model_a.upstream_path().read_bytes()
    require(hashlib.sha256(raw).hexdigest() == model_a.UPSTREAM_SHA256,
        'The unchanged legacy model validator differs')
    namespace = {'__name__':__name__+'._legacy_contract', '__package__':__package__,
        '__file__':str(model_a.upstream_path())}
    exec(compile(raw, str(model_a.upstream_path()), 'exec'), namespace)
    return namespace['validate_model'](model)


def scaled_model(model):
    """Remove only exact duplicates and satisfied zero rows, then scale."""
    validate_model(model)
    seen, rows, dropped = {}, [], []
    for row in model['rows']:
        coefficients, limit = row['coefficients'], row['limit']
        key = (tuple(coefficients), limit)
        if not any(coefficients) and limit >= 0:
            dropped.append({'id':row['id'], 'reason':'satisfied_zero_row'})
            continue
        if key in seen:
            dropped.append({'id':row['id'], 'reason':'exact_duplicate', 'retained_id':seen[key]})
            continue
        seen[key] = row['id']
        divisor = max(1, limit, max(map(abs, coefficients), default=0))
        rows.append({'id':row['id'], 'divisor':divisor,
            'coefficients':[v/divisor for v in coefficients], 'limit':limit/divisor})
    return {'kind':SCREEN_KIND, 'version':1,
        'original_model_sha256':hashlib.sha256(canonical(model)).hexdigest(),
        'original_model_kind':model['kind'], 'original_model_version':model['version'],
        'project_ids':list(model['project_ids']), 'objective_divisor':OBJECTIVE_DIVISOR,
        'objective':[v/OBJECTIVE_DIVISOR for v in model['objective_pence']],
        'rows':rows, 'dropped_rows':dropped, 'original_row_count':len(model['rows']),
        'incumbent_seed':None, 'known_objective_cut':None,
        'reference_admission':False, 'reference_admission_permitted':False}


def exact_plan_check(model, values):
    """Audit every original row with Python integers, including removed rows."""
    validate_model(model)
    require(isinstance(values, list) and len(values) == len(model['project_ids'])
        and all(type(v) is int and v in (0,1) for v in values),
        'A complete exact binary engineering incumbent is required')
    checks = []
    for row in model['rows']:
        lhs = sum(a*b for a,b in zip(row['coefficients'], values))
        checks.append({'id':row['id'], 'lhs':lhs, 'limit':row['limit'],
            'slack':row['limit']-lhs, 'passed':lhs <= row['limit']})
    violations = [row['id'] for row in checks if not row['passed']]
    return {'passed':not violations, 'feasible':not violations, 'complete':True,
        'integer_arithmetic':True, 'all_integer_rows_checked':len(checks),
        'objective_pence':sum(a*b for a,b in zip(model['objective_pence'], values)),
        'plan':dict(zip(model['project_ids'], values)), 'rows':checks,
        'violations':violations}


def _paths(log_path, model_path):
    paths = []
    for path in (log_path, model_path):
        require(path is not None, 'Fresh exact native log and model paths are required')
        actual = Path(path).absolute()
        require(actual == actual.resolve() and not actual.exists(),
            'Fresh nonsymlink native artifact paths are required')
        paths.append(actual)
    require(paths[0] != paths[1], 'Native log and model paths must be distinct')
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    return paths


def _finite(value):
    actual = float(value)
    return actual if math.isfinite(actual) else None


def solve_highs(model, *, time_limit_seconds=SCREEN_SECONDS, threads=2,
    exclude_plan=None, log_path=None, model_path=None):
    """One explicit bounded attempt, with no warm start or objective cut.

    Float status and bounds are engineering observations. Even native OPTIMAL
    with an exact feasible incumbent never becomes an admitted reference.
    An invalid or infeasible incumbent remains in the result with its audit.
    """
    require(type(time_limit_seconds) in (int,float) and math.isfinite(time_limit_seconds)
        and 0 < time_limit_seconds <= MAX_SECONDS, 'Use a finite positive engineering limit at most1800 seconds')
    require(type(threads) is int and threads == 2 and exclude_plan is None,
        'The engineering attempt requires exactly two threads and no excluded plan')
    transformed = scaled_model(model)
    log_path, model_path = _paths(log_path, model_path)
    import numpy as np
    import highspy as hs
    native = hs.Highs()
    parameters = deepcopy(PARAMETERS); parameters['time_limit'] = float(time_limit_seconds)
    def configured(status):
        require(status == hs.HighsStatus.kOk, 'The native engineering model or option was rejected')
    for name, value in parameters.items():
        configured(native.setOptionValue(name, value))
    configured(native.setOptionValue('log_file', str(log_path)))
    count = len(model['project_ids']); indices = np.arange(count, dtype=np.int32)
    configured(native.addVars(count, np.zeros(count), np.ones(count)))
    configured(native.changeColsCost(count, indices, np.array(transformed['objective'])))
    configured(native.changeColsIntegrality(count, indices, np.array([hs.HighsVarType.kInteger]*count)))
    configured(native.setMaximize())
    for row in transformed['rows']:
        nonzero = np.flatnonzero(row['coefficients']).astype(np.int32)
        configured(native.addRow(-hs.kHighsInf, row['limit'], len(nonzero), nonzero,
            np.array(row['coefficients'])[nonzero]))
    configured(native.writeModel(str(model_path)))
    started = time.monotonic(); run_status = native.run()
    require(run_status in (hs.HighsStatus.kOk, hs.HighsStatus.kWarning), 'The native engineering attempt failed')
    solution, information = native.getSolution(), native.getInfo()
    raw = [float(v) for v in solution.col_value]
    result = {'kind':SCREEN_KIND, 'version':1, 'completed':True, 'checked_optimal':False,
        'reference_admission':False, 'reference_admission_permitted':False,
        'formal_global_certificate_claimed':False, 'floating_native_gap_is_not_formal_proof':True,
        'raw_status':str(native.getModelStatus()), 'native_run_status':str(run_status),
        'model_sha256':transformed['original_model_sha256'],
        'specification_sha256':model['specification_sha256'], 'universe_sha256':model['universe_sha256'],
        'exclude_plan':None, 'incumbent_seed':None, 'known_objective_cut':None,
        'optimizer_calls':1, 'retry_count':0, 'parameters':parameters,
        'threads':2, 'time_limit_seconds':time_limit_seconds,
        'plan':None, 'objective_pence':None, 'exact_integer_check':None,
        'native_primal_within_integrality_tolerance':None, 'candidate_from_rounded_primal':False,
        'native_solution_values':[v if math.isfinite(v) else None for v in raw],
        'native_gap':_finite(information.mip_gap),
        'native_dual_bound_pence':(_finite(information.mip_dual_bound)*OBJECTIVE_DIVISOR
            if _finite(information.mip_dual_bound) is not None else None),
        'native_seconds':float(native.getRunTime()), 'native_nodes':int(information.mip_node_count),
        'elapsed_seconds':time.monotonic()-started, 'transformation':transformed,
        'route_evidence':deepcopy(NATIVE_ROUTE_EVIDENCE)}
    if not getattr(solution, 'value_valid', False):
        result['incomplete_reason'] = 'The native solver has no valid primal solution'
    elif len(raw) != count or not all(math.isfinite(v) for v in raw):
        result['incomplete_reason'] = 'The native primal vector is incomplete or nonfinite'
    else:
        values = [int(round(v)) for v in raw]
        if not all(v in (0,1) for v in values):
            result['incomplete_reason'] = 'The rounded native primal is outside the binary domain'
        else:
            checked = exact_plan_check(model, values)
            result['exact_integer_check'] = checked
            result['native_primal_within_integrality_tolerance'] = all(
                abs(v-rounded) <= FEASIBILITY_TOLERANCE for v,rounded in zip(raw,values))
            if not checked['passed']:
                result['incomplete_reason'] = 'The floating incumbent violates an original exact integer row'
            else:
                # This is candidate construction, not a native certificate.
                # Exact binary-domain and original integer-row checks decide
                # whether the rounded plan is usable; float distance is kept
                # as an observation and cannot suppress a feasible candidate.
                result.update(plan=checked['plan'], objective_pence=checked['objective_pence'],
                    candidate_from_rounded_primal=True)
    return result
