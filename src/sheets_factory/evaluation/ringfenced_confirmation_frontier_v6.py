"""Native v6 confirmation for a predeclared five-pair replacement wave.

The wave has five tasks per mode. Its results do not represent a fresh twenty
item confirmation; retained-material results remain a separately reported scope.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from . import ringfenced_frontier_v6 as native

NATIVE_SHA = '90324a912def33dd6ddeed8bbf773091eb976cf4261f0451757fe10cb3c60444'


def _ref(path):
    p = Path(path).absolute(); raw = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def verify_dependencies():
    if _ref(native.__file__)['sha256'] != NATIVE_SHA:
        raise ValueError('The frozen ring-fenced v6 protocol changed')
    native.verify_dependencies()


def _provenance():
    verify_dependencies()
    return {**native._provenance(), 'replacement_wave_cardinality': _ref(__file__),
            'replacement_wave_scope': {'financial_modeling': 5, 'debugging': 5},
            'retained_materials_retested': False}


def adapted_ast():
    verify_dependencies(); tree = native.adapted_ast(); changed = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ('freeze_selection', 'summarize'):
            for part in ast.walk(node):
                if isinstance(part, ast.Compare) and ast.unparse(part) in ('counts[mode] >= 10', "by_mode[mode]['tasks'] >= 10"):
                    part.comparators[0] = ast.Constant(5); changed.append(node.name)
            if node.name == 'freeze_selection':
                for part in ast.walk(node):
                    if isinstance(part, ast.Constant) and part.value == 'Confirmation requires at least ten tasks per category':
                        part.value = 'The replacement wave requires at least five tasks per category'
    if sorted(changed) != ['freeze_selection', 'summarize']:
        raise ValueError('The two explicit replacement-wave cardinality seams changed')
    return ast.fix_missing_locations(tree)


_namespace = {**native._namespace, '__name__': __name__, '__file__': __file__,
              '__package__': __package__, '_transport_provenance': _provenance}
exec(compile(adapted_ast(), __file__, 'exec'), _namespace)
POLICY_V6 = dict(native.POLICY_V6)
for _name in ('freeze_selection', 'run_evaluation', 'execute_evaluation', 'apply_tool_time_policy',
              'LocalCodex', 'collect_attempts', 'classify_retryable', 'assess_infrastructure_retry',
              'review_agent_timeout', 'transport_profile', 'TASK_FILES', 'MODEL', 'EFFORT', 'PROMPT',
              'PROFILE_PATH', 'summarize', '_runtime_provenance'):
    if _name in _namespace:
        globals()[_name] = _namespace[_name]
