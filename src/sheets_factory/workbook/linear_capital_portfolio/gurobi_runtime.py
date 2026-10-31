"""Research-only Gurobi namespace; no existing runtime is changed.

Uses the approved private producer transport, but a separate one-package
vendor, explicit wheel license, native LP/PRM artifacts and honest new kinds.
"""
import ast as _ast
import hashlib as _hashlib
import json as _json
from pathlib import Path as _Path

from . import producer_optimization_runtime as _producer

PRODUCER_UPSTREAM_SHA256 = '13958fd26b9b0318a04601fefc8c7b52f8df9fc64bb3f27100158eb26a6d4222'
PROFILE = _Path(__file__).resolve().parents[4]/'config/runtime_profiles/linear_capital_gurobi_research_v1.json'


def profile_reference():
    raw = PROFILE.read_bytes(); value = _json.loads(raw)
    expected = {'kind': 'linear_capital_gurobi_restricted_research_profile', 'version': 1,
        'id': 'linear_capital_gurobi_research_v1', 'producer_cpus': 16, 'producer_threads': 16,
        'memory_bytes': 32*1024**3, 'pids_limit': 256, 'network': 'none',
        'maximum_private_solver_seconds': 3600, 'gurobipy_version': '13.0.0',
        'license_source': 'exact_public_wheel_embedded_size_limited_license_only',
        'maximum_variables': 2000, 'maximum_linear_constraints_including_no_good': 2000,
        'MIPGap': 0, 'MIPGapAbs': 0, 'personal_license_mounted': False,
        'remote_license_or_paid_service_permitted': False, 'research_evaluation_only': True,
        'commercial_or_production_use_authorized_by_this_profile': False,
        'agent_and_verifier_cpus_unchanged': 2, 'agent_strict_SUM_tool_seconds_unchanged': 1800,
        'automatic_retries': 0}
    if value != expected or any(type(value[k]) is not type(v) for k, v in expected.items()):
        raise ValueError('The restricted Gurobi research profile changed')
    return {'path': str(PROFILE), 'sha256': _hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _producer_source_files():
    folder = _Path(__file__).resolve().parent
    return {'model_gurobi.py': _real(folder/'model_gurobi.py'),
        'frozen_optimization_runtime.py': _real(folder/'optimization_runtime.py')}


def adapted_ast():
    if _hashlib.sha256(_Path(_producer.__file__).read_bytes()).hexdigest() != PRODUCER_UPSTREAM_SHA256:
        raise ValueError('The approved isolated producer transport changed')
    tree = _producer.adapted_ast(); counts = {}
    def mark(name): counts[name] = counts.get(name, 0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self, node):
            names = {n.id for n in node.targets if isinstance(n, _ast.Name)}
            if 'PREPARATION_KIND' in names: node.value = _ast.Constant('prepared_private_gurobi_restricted_research'); mark('prepare_kind')
            elif 'TERMINAL_KIND' in names: node.value = _ast.Constant('private_gurobi_restricted_research_execution'); mark('terminal_kind')
            elif 'VENDOR_SITE_PACKAGES' in names:
                node.value = _ast.parse("ROOT/'outputs/tmp/linear-gurobi130-vendor'", mode='eval').body; mark('vendor_path')
            elif 'VENDOR_ROOTS' in names:
                node.value = _ast.parse("{'gurobipy', 'gurobipy-13.0.0.dist-info'}", mode='eval').body; mark('vendor_roots')
            elif 'DISTRIBUTIONS' in names:
                node.value = _ast.parse("{'gurobipy':'13.0.0'}", mode='eval').body; mark('version')
            elif 'BACKENDS' in names:
                node.value = _ast.parse("{'gurobi':('model_gurobi','solve_gurobi','native_model.lp')}", mode='eval').body; mark('backend')
            elif 'RUNNER' in names:
                runner = _ast.parse(node.value.value)
                class Runner(_ast.NodeTransformer):
                    def visit_Subscript(self, item):
                        if isinstance(item.value, _ast.Dict) and {k.value for k in item.value.keys if isinstance(k, _ast.Constant)} == {'scip', 'cp_sat'}:
                            item.value = _ast.parse("{'gurobi':('model_gurobi','solve_gurobi','native_model.lp')}", mode='eval').body; mark('runner_backend')
                        return self.generic_visit(item)
                node.value = _ast.Constant(_ast.unparse(Runner().visit(runner)))
            return self.generic_visit(node)
        def visit_Compare(self, node):
            text = _ast.unparse(node)
            if text in ('time_limit_seconds == 3600', "request['time_limit_seconds'] == 3600"):
                variable = 'time_limit_seconds' if text.startswith('time_limit_seconds') else "request['time_limit_seconds']"
                node = _ast.parse('1 <= '+variable+' <= 3600', mode='eval').body; mark('time_guard')
            elif text == "frozen['request']['backend'] == 'cp_sat'":
                node.comparators[0] = _ast.Constant('gurobi'); mark('native_parameters')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == '.parameters.pbtxt': node.value = '.parameters.prm'; mark('native_suffix')
            elif isinstance(node.value, str) and 'sf-producer16-integer-' in node.value:
                node.value = node.value.replace('sf-producer16-integer-', 'sf-gurobi-research-'); mark('owned_name')
            elif node.value == 'The native CP-SAT settings changed': node.value = 'The native Gurobi research settings changed'; mark('message')
            return node
    tree = Adapt().visit(tree)
    expected = {'prepare_kind': 1, 'terminal_kind': 1, 'vendor_path': 1, 'vendor_roots': 1, 'version': 1,
        'backend': 1, 'runner_backend': 1, 'time_guard': 2, 'native_parameters': 1,
        'native_suffix': 1, 'owned_name': 2, 'message': 1}
    if counts != expected:
        raise ValueError('The exact Gurobi-only transport substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
