"""Opt-in N360 CP-SAT600 lifecycle; original producer bytes stay unchanged."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

from ..linear_capital_scaled import optimization_runtime as base
from ..linear_capital_scaled import model_b

ROOT = Path(__file__).resolve().parents[4]
PROFILE = ROOT / 'config/runtime_profiles/linear_capital_sensitivity9_reference600_v1.json'
BASE_SHA = '45f841e9d33917b8ac469694b5ef335311479aa9de98aad72207a358744e2d54'


def policy():
    return {'kind': 'independent_nine_case_private_reference_profile', 'version': 1,
        'id': 'linear_capital_sensitivity9_reference600_v1', 'image_id': base.IMAGE_ID,
        'producer': {'cpus': 16, 'memory_bytes': 32 * 1024**3, 'pids_limit': 256,
            'threads': 16, 'network': 'none', 'backend': 'cp_sat', 'solver_seconds_per_attempt': 600,
            'operational_timeout_seconds': 720, 'relative_gap': 0, 'absolute_gap': 0, 'automatic_retries': 0},
        'vendor': {'ortools': '9.14.6206', 'numpy': '1.26.4'}, 'projects': 360,
        'complete_business_rows': 941, 'cases': 9, 'max_parallel_cases': 2,
        'maximum_native_job_invocations': 18, 'best_requires_OPTIMAL_before_runner': True,
        'runner_excludes_complete_winner': True, 'runner_requires_OPTIMAL_gap_pence_at_least': 1,
        'cardinality_admission': False, 'prior_incumbent_or_warm_hint': False,
        'all_cases_required': True, 'reference_is_not_source_or_quality_or_difficulty': True}


def profile_reference():
    if base._canonical(json.loads(PROFILE.read_bytes())) != base._canonical(policy()):
        raise ValueError('The fixed nine-case CP-SAT600 resources or proof policy changed')
    return base.reference(PROFILE)


def _complete_scaled_dimension(model):
    if len(model['project_ids']) != 360 or len(model['rows']) != 941:
        raise ValueError('Require the complete 360-project, 941-row matrix')
    return model_b.validate_model(model)


def adapted_ast():
    if hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('The frozen N360 matrix-only producer lifecycle changed')
    counts = Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Assign(self, node):
            names = [getattr(t, 'id', None) for t in node.targets]
            if names == ['ROOT']:
                node.value = ast.Name('_SENSITIVITY_ROOT', ast.Load()); counts['root'] += 1
            elif names == ['PREPARATION_KIND']:
                node.value = ast.Constant('prepared_private_sensitivity9_CP600_solver'); counts['prepared'] += 1
            elif names == ['TERMINAL_KIND']:
                node.value = ast.Constant('private_sensitivity9_CP600_solver_execution'); counts['terminal'] += 1
            return self.generic_visit(node)
        def visit_Compare(self, node):
            text = ast.unparse(node)
            if text in ('time_limit_seconds == 3600', "request['time_limit_seconds'] == 3600"):
                counts[text] += 1
                return ast.parse(text.replace('3600', '600'), mode='eval').body
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if type(node.value) is str:
                if 'sf-scaled-producer16-integer-' in node.value:
                    node.value = node.value.replace('sf-scaled-producer16-integer-', 'sf-sensitivity9-CP600-')
                    counts['owned'] += 1
                node.value = node.value.replace('declared 3600-second', 'declared 600-second')
            return node
    tree = Adapt().visit(base.adapted_ast())
    if counts != Counter({'root': 1, 'prepared': 1, 'terminal': 1, 'owned': 2,
                           'time_limit_seconds == 3600': 1, "request['time_limit_seconds'] == 3600": 1}):
        raise ValueError('The exact isolated CP600 substitution sites changed: ' + str(counts))
    return ast.fix_missing_locations(tree)


# No mutation of any original module namespace. Native bundles still contain
# only the approved six matrix/schema sources, never a financial forward.
_namespace = {'__name__': __name__ + '._frozen', '__package__': __package__, '__file__': __file__,
    '_SENSITIVITY_ROOT': ROOT, '_complete_scaled_dimension': _complete_scaled_dimension,
    '_producer_source_files': base._producer_source_files, 'profile_reference': profile_reference}
exec(compile(adapted_ast(), __file__, 'exec'), _namespace)
for _name, _value in _namespace.items():
    if not _name.startswith('__'):
        globals()[_name] = _value
