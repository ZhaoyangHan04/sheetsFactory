"""Matrix-only N360 SCIP representation; original integer checks are retained."""
import ast
from collections import Counter
from decimal import Decimal
import hashlib
import importlib.util
from pathlib import Path

WRAPPER_SHA = '6bb86d51b39970d151fa4f638d2427c1f04253f87d611f802f5bc0621221354d'


def require(value, message):
    if not value: raise ValueError(message)


def solver_rows(model):
    """Only exact duplicates/zero tautologies and declared positive scaling."""
    seen = set(); rows = []; omitted = []
    for row in model['rows']:
        a = row['coefficients']; b = row['limit']; key = (tuple(a), b)
        if not any(a) and b >= 0:
            omitted.append({'id': row['id'], 'reason': 'zero_tautology'}); continue
        if key in seen:
            omitted.append({'id': row['id'], 'reason': 'exact_duplicate'}); continue
        seen.add(key); maximum = max(map(abs, a), default=0)
        scale = 100000 if maximum > 1000000 else 1000 if maximum > 10 else 1
        rows.append({**row, 'coefficients': [c/scale for c in a], 'limit': b/scale,
                     'positive_solver_scale': scale})
    return rows, omitted


def bound_diagnostics(result):
    answer = {}
    for field in ('native_objective', 'primal_bound', 'dual_bound', 'gap'):
        value = result.get(field)
        answer[field] = None if value is None else {'float_hex': float(value).hex(),
            'exact_binary_float_decimal': str(Decimal.from_float(float(value)))}
    answer['integer_objective_pence'] = result.get('objective_pence')
    bound = result.get('dual_bound'); objective = result.get('objective_pence')
    answer['dual_minus_integer_objective_exact_decimal'] = (None if bound is None or objective is None
        else str(Decimal.from_float(float(bound))-Decimal(objective)))
    return answer


def wrapper_path():
    local = Path(__file__).with_name('frozen_scaled_model_a.py')
    return local if local.is_file() else Path(__file__).resolve().parents[1]/'linear_capital_scaled/model_a.py'


def adapted_ast():
    path = wrapper_path()
    require(hashlib.sha256(path.read_bytes()).hexdigest() == WRAPPER_SHA, 'Frozen N360 A wrapper changed')
    package = __package__ if path.name == 'frozen_scaled_model_a.py' else __package__.rsplit('.', 1)[0]+'.linear_capital_scaled'
    descriptor = importlib.util.spec_from_file_location(package+'._sensitivity_SCIP_base', path)
    module = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(module)
    tree = module.adapted_ast(); hits = Counter()
    class Adapt(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name == 'build_model': hits['remove_financial_forward'] += 1; return None
            if node.name == 'solve_scip':
                body = []
                for item in node.body:
                    if isinstance(item, ast.For) and ast.unparse(item.target) == '(index, row)' and ast.unparse(item.iter) == "enumerate(model['rows'])":
                        item.iter = ast.parse('enumerate(_solver_rows)', mode='eval').body
                        body.extend(ast.parse('_solver_rows,_solver_omitted=solver_rows(model)').body); hits['rows'] += 1
                    body.append(item)
                node.body = body
                final = next(item for item in node.body if isinstance(item, ast.Try)).finalbody
                require(ast.unparse(final[-1]) == 'native.freeProb()', 'Frozen native cleanup changed')
                final[-1:-1] = ast.parse("result.update(solver_representation={'raw_original_rows':len(model['rows']),'native_nonzero_distinct_rows':len(_solver_rows),'omitted_rows':_solver_omitted,'row_scaling':'100000 if maxabs>1000000 else1000 if maxabs>10 else1','objective_scaled':False,'complete_original_integer_rows_rechecked':True},native_bound_precision=bound_diagnostics(result),declared_feasibility_tolerance=1e-9,applied_feasibility_tolerance=native.getParam('numerics/feastol'))").body
                hits['precision'] += 1
            return self.generic_visit(node)
        def visit_Dict(self, node):
            keys = [getattr(k, 'value', None) for k in node.keys]
            if keys == ['limits/time','limits/gap','limits/absgap','parallel/maxnthreads','lp/threads']:
                node.keys.append(ast.Constant('numerics/feastol')); node.values.append(ast.Constant(1e-9)); hits['tolerance'] += 1
            if 'feasibility_tolerance_changed' in keys:
                node.values[keys.index('feasibility_tolerance_changed')] = ast.parse('default_tolerance != 1e-9', mode='eval').body
                hits['metadata'] += 1
            return self.generic_visit(node)
        def visit_Compare(self, node):
            if ast.unparse(node) == "native.getParam('numerics/feastol') != default_tolerance":
                node.comparators[0] = ast.Constant(1e-9); hits['guard'] += 1
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    require(hits == Counter(dict(remove_financial_forward=1,rows=1,precision=1,tolerance=1,metadata=1,guard=1)),
            'Exact N360 SCIP adaptation sites changed: '+str(hits))
    return ast.fix_missing_locations(tree)


def strict_evidence(result, model):
    """No float gap display, rounded primal, or FEASIBLE status admits gold."""
    if not result['checked_optimal']: return
    objective = result['objective_pence']; values = result['native_solution_values']; plan = result['plan']
    require(result['completed'] is True and result['raw_status'] == 'optimal' and type(objective) is int
        and len(values) == len(model['project_ids']) and all(type(v) in (int,float) and v in (0.0,1.0) for v in values)
        and values == [plan[p] for p in model['project_ids']]
        and all(type(result[k]) in (int,float) and result[k] == float(objective)
                for k in ('native_objective','primal_bound','dual_bound'))
        and type(result['gap']) in (int,float) and result['gap'] == 0.0
        and result['native_bound_precision'] == bound_diagnostics(result),
        'Strict native objective/primal/dual/binary evidence is required')


# In the native seven-file bundle this file is imported as portfolio.model_a.
# Financial construction is absent from the compiled namespace.
if __name__.split('.')[-1] == 'model_a':
    from . import spec as _spec
    _SCALED_PRODUCTION_COUNTS = _spec.PRODUCTION_COUNTS
    exec(compile(adapted_ast(), __file__, 'exec'), globals())
