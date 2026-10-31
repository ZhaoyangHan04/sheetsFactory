"""Separate research query; never changes the original best/runner protocol.

Host preparation and mocked tests may import this file without importing a
solver. Only ``solve_query`` imports a native solver and starts one query.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import threading
import time
import types

UPSTREAM_RUNTIME_SHA256 = 'fb1031c555fed919830a1f05fdb95bfa8912d2116fd6904801cfaba131a948ea'
KIND = 'research_complete_plan_excluded_winner_threshold_feasibility_v1'
SECONDS = 900
THREADS = 16


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def query(model, winner):
    """Return precisely the two added LE rows; keep the original matrix intact."""
    from . import model_b
    model = model_b.validate_model(model)
    winner = model_b.validate_plan(model, winner)
    checked = model_b.check_plan(model, winner)
    require(checked['passed'], 'The complete winner must satisfy every original row')
    objective = checked['objective_pence']
    return {'kind': KIND, 'version': 1, 'original_model_sha256': hashlib.sha256(canonical(model)).hexdigest(),
        'complete_winner': winner, 'threshold_pence': objective, 'objective_optimization': False,
        'original_binary_variables': len(model['project_ids']), 'original_le_rows': len(model['rows']),
        'added_le_rows': [
            {'id': '__research_winner_threshold__', 'coefficients': [-c for c in model['objective_pence']], 'limit': -objective},
            {'id': '__research_complete_winner_no_good__',
                'coefficients': [1 if winner[pid] else -1 for pid in model['project_ids']], 'limit': sum(winner.values()) - 1}]}


def check_result(model, result, winner):
    """Exact primal checks, including every LE row, threshold, and complete no-good."""
    from . import model_b
    declaration = query(model, winner)
    require(result.get('query') == declaration and result.get('checked_optimal') is False,
        'The exact research query or original-optimality boundary changed')
    require(result.get('status') in {'OPTIMAL', 'FEASIBLE', 'INFEASIBLE', 'UNKNOWN', 'MODEL_INVALID'},
        'Unknown research query status')
    status = result['status']; plan = result.get('plan'); exact = None
    if plan is not None:
        require(status in {'OPTIMAL', 'FEASIBLE'}, 'A non-feasible query status cannot carry a primal')
        exact = model_b.check_plan(model, plan, exclude_plan=winner)
        require(exact['passed'], 'An alternative violates an original row or the complete-plan no-good')
        require(type(result.get('objective_pence')) is int and result['objective_pence'] == exact['objective_pence'],
            'The alternative integer objective differs')
        require(exact['objective_pence'] >= declaration['threshold_pence'], 'An alternative violates the winner threshold')
        require(exact['objective_pence'] == declaration['threshold_pence'],
            'An alternative above the independently proved original optimum contradicts the original best')
    else:
        require(result.get('objective_pence') is None and status not in {'OPTIMAL', 'FEASIBLE'},
            'A feasible query requires a complete exact primal')
    return {'native_status': status, 'checked_optimal': False,
        'exact_matrix_plan_check': None if exact is None else {
            'passed': True, 'all_integer_rows_checked': len(exact['rows']),
            'objective_pence': exact['objective_pence'], 'winner_threshold_checked': True,
            'excluded_plan_not_returned': True, 'complete_check': exact},
        'status': ('research_unique_by_native_infeasibility' if status == 'INFEASIBLE' else
            'research_ambiguous_tied_optimum' if exact is not None else 'research_uniqueness_unproved'),
        'unique_by_native_infeasibility': status == 'INFEASIBLE',
        'ambiguous_tied_optimum': exact is not None,
        'exact_runner_objective': None, 'exact_gap_pence': None,
        'original_v1_reference_passed': False, 'formal_global_certificate': False,
        'source_quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}


def solve_query(model, *, backend, time_limit_seconds, threads, exclude_plan, log_path, model_path):
    """One feasibility query; no nonconstant native objective, tuning, or retry."""
    require(type(time_limit_seconds) is int and time_limit_seconds == SECONDS and
        type(threads) is int and threads == THREADS, 'The research query requires exactly 900 seconds and 16 workers')
    require(backend in {'cp_sat', 'scip'}, 'Choose the frozen native backend')
    declaration = query(model, exclude_plan)
    paths = [Path(log_path), Path(model_path)]
    require(all(p.is_absolute() and p == p.resolve() and not p.exists() for p in paths), 'Preserve every native query artifact')
    require(paths[0] != paths[1], 'Native model and log paths must differ')
    started = time.monotonic()
    result = {'query': declaration, 'backend': backend, 'checked_optimal': False, 'plan': None, 'objective_pence': None,
        'model_sha256': declaration['original_model_sha256'], 'specification_sha256': model['specification_sha256'],
        'universe_sha256': model['universe_sha256'], 'exclude_plan': exclude_plan,
        'threads': THREADS, 'time_limit_seconds': SECONDS, 'gap_parameters': {'relative': 0, 'absolute': 0},
        'optimizer_calls': 1, 'retry_count': 0, 'objective_optimization': False, 'formal_global_certificate': False}
    if backend == 'cp_sat':
        require(importlib.metadata.version('ortools') == '9.14.6206', 'The approved CP-SAT version changed')
        from ortools.sat.python import cp_model
        native = cp_model.CpModel()
        variables = [native.new_bool_var(pid) for pid in model['project_ids']]
        for row in [*model['rows'], *declaration['added_le_rows']]:
            native.add(sum(c*v for c, v in zip(row['coefficients'], variables) if c) <= row['limit']).with_name(row['id'])
        # In particular, do not call maximize/minimize and do not enumerate all solutions.
        require(not native.proto.HasField('objective') and not native.proto.HasField('floating_point_objective'),
            'A pure feasibility query must have no native objective')
        solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = float(SECONDS)
        solver.parameters.num_search_workers = THREADS
        solver.parameters.relative_gap_limit = 0.0; solver.parameters.absolute_gap_limit = 0.0
        solver.parameters.log_to_stdout = False; solver.parameters.log_search_progress = True
        paths[1].write_text(str(native.proto))
        with Path(str(paths[1])+'.parameters.pbtxt').open('x') as stream: stream.write(str(solver.parameters))
        with paths[0].open('x') as stream:
            lock = threading.Lock()
            def log(message):
                with lock: stream.write(message); stream.flush()
            solver.log_callback = log
            raw = solver.solve(native)
        result.update(status=solver.status_name(raw), raw_status=int(raw),
            response_proto_text=str(solver.response_proto), solver_wall_seconds=solver.wall_time,
            solver_version='9.14.6206', branches=solver.num_branches, conflicts=solver.num_conflicts)
        if raw in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result['plan'] = {pid: int(solver.value(v)) for pid, v in zip(model['project_ids'], variables)}
    else:
        require(importlib.metadata.version('pyscipopt') == '6.0.0', 'The approved PySCIPOpt version changed')
        import pyscipopt
        native = pyscipopt.Model('research_original_matrix_threshold_complete_exclusion')
        try:
            native.hideOutput(True); native.setLogfile(str(paths[0]))
            default_tolerance = native.getParam('numerics/feastol')
            settings = {'limits/time': float(SECONDS), 'limits/gap': 0.0, 'limits/absgap': 0.0,
                'parallel/maxnthreads': THREADS, 'lp/threads': THREADS}
            for name, value in settings.items(): native.setParam(name, value)
            variables = [native.addVar(name=pid, vtype='B', obj=0.0) for pid in model['project_ids']]
            for index, row in enumerate([*model['rows'], *declaration['added_le_rows']]):
                native.addCons(pyscipopt.quicksum(c*v for c, v in zip(row['coefficients'], variables)) <= row['limit'], name='query_'+str(index))
            native.writeProblem(str(paths[1]), trans=False)
            native.optimize()
            status = str(native.getStatus()); best = native.getBestSol() if native.getNSols() > 0 else None
            require(status not in {'unbounded', 'inforunbd'}, 'A bounded binary feasibility query cannot be unbounded')
            if best is not None:
                require(status != 'infeasible', 'Infeasible status conflicts with a native primal')
                raw = [float(native.getSolVal(best, v)) for v in variables]
                require(all(v in (0.0, 1.0) for v in raw), 'The alternative native primal is not exactly binary')
                result['plan'] = dict(zip(model['project_ids'], map(int, raw)))
            result.update(status='INFEASIBLE' if status == 'infeasible' else 'FEASIBLE' if best is not None else 'UNKNOWN',
                raw_status=status, parameters=settings, solver_version='6.0.0',
                native_seconds=float(native.getSolvingTime()), native_nodes=int(native.getNNodes()),
                default_feasibility_tolerance=default_tolerance, feasibility_tolerance_changed=False)
            require(native.getParam('numerics/feastol') == default_tolerance, 'The default SCIP feasibility tolerance changed')
        finally:
            native.freeProb()
    if result['plan'] is not None:
        result['objective_pence'] = sum(c*result['plan'][pid] for c, pid in zip(model['objective_pence'], model['project_ids']))
    result['exact_query_check'] = check_result(model, result, exclude_plan)
    result['elapsed_seconds'] = time.monotonic() - started
    return result


def make_runtime():
    """Isolate exact lifecycle substitutions; retain the original module bytes."""
    from . import optimization_runtime as original
    raw = Path(original.__file__).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == UPSTREAM_RUNTIME_SHA256, 'The frozen matrix-only lifecycle changed')
    tree = ast.parse(raw); changes = {}
    def changed(key): changes[key] = changes.get(key, 0) + 1
    class Adapt(ast.NodeTransformer):
        def visit_Assign(self, node):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if 'PREPARATION_KIND' in names:
                node.value = ast.Constant('prepared_'+KIND); changed('prepare_kind')
            elif 'TERMINAL_KIND' in names:
                node.value = ast.Constant('execution_'+KIND); changed('terminal_kind')
            elif 'RUNNER' in names:
                text = node.value.value
                text = text.replace("backend=importlib.import_module('portfolio.'+module)", "backend=importlib.import_module('portfolio.unique_feasibility_research')")
                text = text.replace("getattr(backend,function)(model,", "backend.solve_query(model,backend=job['backend'],")
                text = text.replace('threads=2', 'threads=16').replace("'threads':2", "'threads':16")
                node.value = ast.Constant(text); changed('runner')
            return self.generic_visit(node)
        def visit_FunctionDef(self, node):
            if node.name == '_source_files':
                node.body = ast.parse('return _query_source_files()').body; changed('source'); return node
            if node.name == 'check_result':
                node.body = ast.parse('return _query_check_result(model, result, exclude_plan)').body; changed('check'); return node
            return self.generic_visit(node)
        def visit_Compare(self, node):
            before = ast.unparse(node)
            if before in ("request['threads'] == 2", "runtime.get('threads') == 2", "solver.get('threads') == 2"):
                node.comparators[0] = ast.Constant(16); changed('thread')
            elif before == "actual['NanoCpus'] == 2 * 10 ** 9":
                node.comparators[0] = ast.parse('16 * 10**9', mode='eval').body; changed('actual_cpu')
            elif before in ('1 <= time_limit_seconds <= 7200', "1 <= request['time_limit_seconds'] <= 7200"):
                lhs = 'time_limit_seconds' if before.startswith('1 <= time') else "request['time_limit_seconds']"
                node = ast.parse(lhs+' == 900', mode='eval').body; changed('time')
            return self.generic_visit(node)
        def visit_Dict(self, node):
            for i, key in enumerate(node.keys):
                if isinstance(key, ast.Constant) and key.value in ('cpus', 'threads', 'parallel/maxnthreads', 'lp/threads') and isinstance(node.values[i], ast.Constant) and node.values[i].value == 2:
                    node.values[i] = ast.Constant(16); changed('dict_resource')
            return self.generic_visit(node)
        def visit_List(self, node):
            for i, item in enumerate(node.elts[:-1]):
                if isinstance(item, ast.Constant) and item.value == '--cpus' and isinstance(node.elts[i+1], ast.Constant) and node.elts[i+1].value == '2':
                    node.elts[i+1] = ast.Constant('16'); changed('create_cpu')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if isinstance(node.value, str) and 'sf-private-integer-' in node.value:
                node.value = node.value.replace('sf-private-integer-', 'sf-unique-query-'); changed('owned_name')
            return node
    tree = Adapt().visit(tree)
    expected = {'prepare_kind': 1, 'terminal_kind': 1, 'runner': 1, 'source': 1, 'check': 1,
        'thread': 3, 'actual_cpu': 1, 'time': 2, 'dict_resource': 5, 'create_cpu': 1, 'owned_name': 2}
    require(changes == expected, 'The exact research lifecycle substitutions changed: '+str(changes))
    module = types.ModuleType(original.__package__+'._unique_query_runtime')
    module.__package__ = original.__package__; module.__file__ = __file__
    module.__dict__.update(_query_source_files=lambda: {**original._source_files(), 'unique_feasibility_research.py': Path(__file__)},
        _query_check_result=check_result)
    exec(compile(ast.fix_missing_locations(tree), __file__, 'exec'), module.__dict__)
    return module
