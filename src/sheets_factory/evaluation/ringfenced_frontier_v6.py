"""The same native v6 clock and agent with the strict ring-fenced export inspector."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path
from . import linear_capital_scaled_frontier_v6 as native

NATIVE_SHA = '4a0c68ce47657f22b00200f5b50c46a88af221968280934a3297a09c44e18d74'


def _ref(path):
    p=Path(path).resolve();b=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}


def verify_dependencies():
    if _ref(native.__file__)['sha256'] != NATIVE_SHA:
        raise ValueError('The original native v6 protocol changed')
    native.verify_dependencies()


def _provenance():
    verify_dependencies()
    from . import ringfenced_resource_harbor as resources
    return {**native._provenance(),'ringfenced_native_inspection':_ref(__file__),
            'ringfenced_resource_export':_ref(resources.__file__)}


def adapted_ast():
    verify_dependencies();tree=native.adapted_ast();counts={'inspector':0,'agent':0}
    for node in tree.body:
        if isinstance(node,ast.ImportFrom) and node.level==1 and node.module=='resource_harbor':
            if [(x.name,x.asname) for x in node.names] != [('inspect_resource_export','inspect_export')]:
                raise ValueError('The original native resource-inspector import changed')
            node.module='ringfenced_resource_harbor';counts['inspector']+=1
    class Agent(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='sheets_factory.evaluation.linear_capital_scaled_frontier_v6:LocalCodex':
                counts['agent']+=1
                return ast.copy_location(ast.Constant('sheets_factory.evaluation.ringfenced_frontier_v6:LocalCodex'),node)
            return node
    tree=Agent().visit(tree)
    if counts!={'inspector':1,'agent':2}:
        raise ValueError('The exact ring-fenced native adaptation seams changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_namespace={**native._namespace,'__name__':__name__,'__file__':__file__,
            '__package__':__package__,'_transport_provenance':_provenance}
exec(compile(adapted_ast(),__file__,'exec'),_namespace)
POLICY_V6=dict(native.POLICY_V6)
for _name in ('freeze_selection','run_evaluation','execute_evaluation','apply_tool_time_policy',
              'LocalCodex','collect_attempts','classify_retryable','assess_infrastructure_retry',
              'review_agent_timeout','transport_profile','TASK_FILES','MODEL','EFFORT','PROMPT',
              'PROFILE_PATH','summarize','_runtime_provenance'):
    if _name in _namespace:
        globals()[_name]=_namespace[_name]
