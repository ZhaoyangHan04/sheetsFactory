"""Isolated producer16 namespace for the frozen private matrix-only runtime.

Only producer CPU/workers, backend, provenance and names change. Source LO and
agent/verifier resources retain their separate two-CPU profile. Every original
vendoring, native-result, resource, owned-cleanup and one-attempt gate remains.
"""
import ast as _ast
import hashlib as _hashlib
import json as _json
from pathlib import Path as _Path

UPSTREAM_SHA256 = 'fb1031c555fed919830a1f05fdb95bfa8912d2116fd6904801cfaba131a948ea'
PROFILE = _Path(__file__).resolve().parents[4]/'config/runtime_profiles/linear_capital_reference_producer_v1.json'


def profile_reference():
    raw = PROFILE.read_bytes(); value = _json.loads(raw)
    expected = {'cpus': 16, 'memory_bytes': 32*1024**3, 'pids_limit': 256, 'threads': 16,
        'network': 'none', 'backend': 'cp_sat', 'solver_seconds_per_attempt': 3600,
        'relative_gap': 0, 'absolute_gap': 0, 'automatic_retries': 0}
    if (value.get('kind') != 'linear_capital_private_reference_producer_profile'
            or type(value.get('version')) is not int or value['version'] != 1
            or value.get('producer') != expected
            or any(type(value['producer'][key]) is not int for key in
                ('cpus', 'memory_bytes', 'pids_limit', 'threads', 'solver_seconds_per_attempt', 'relative_gap', 'absolute_gap', 'automatic_retries'))
            or value.get('image_id') != 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
            or value.get('agent_and_verifier') != {
                'unchanged_runtime_profile': 'config/runtime_profiles/entity_group_large_v2.yaml',
                'cpus': 2, 'memory_bytes': 32*1024**3, 'strict_tool_budget_seconds': 1800,
                'model_response_time_excluded': True, 'parallel_tool_executions': 'sum'}
            or value.get('independent_second_global_search_claimed') is not False
            or value.get('solver_status_is_not_formal_certificate') is not True):
        raise ValueError('The explicit private producer16 profile changed')
    return {'path': str(PROFILE), 'sha256': _hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _producer_source_files():
    folder = _Path(__file__).resolve().parent
    return {**{name: _real(folder/name) for name in ('spec.py', 'candidate_a.py', 'ledger.py', 'model_a.py')},
        'model_b.py': _real(folder/'producer_model_b.py'),
        'frozen_model_b.py': _real(folder/'model_b.py')}


def adapted_ast():
    path = _Path(__file__).with_name('optimization_runtime.py'); raw = path.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen matrix-only optimization runtime changed')
    tree = _ast.parse(raw, filename=str(path)); counts = {}
    def changed(name): counts[name] = counts.get(name, 0)+1
    def statement(text): return _ast.parse(text).body[0]
    def same(node, text): return _ast.dump(node) == _ast.dump(statement(text))
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self, node):
            if any(isinstance(t, _ast.Name) and t.id == 'PREPARATION_KIND' for t in node.targets):
                node.value = _ast.Constant('prepared_private_linear_capital_producer16_solver'); changed('preparation_kind')
            elif any(isinstance(t, _ast.Name) and t.id == 'TERMINAL_KIND' for t in node.targets):
                node.value = _ast.Constant('private_linear_capital_producer16_solver_execution'); changed('terminal_kind')
            elif any(isinstance(t, _ast.Name) and t.id == 'BACKENDS' for t in node.targets):
                node.value = _ast.parse("{'cp_sat': ('model_b', 'solve_cp_sat', 'native_model.pbtxt')}", mode='eval').body; changed('backend')
            elif any(isinstance(t, _ast.Name) and t.id == 'RUNNER' for t in node.targets):
                runner = _ast.parse(node.value.value)
                class Worker(_ast.NodeTransformer):
                    def visit_keyword(self, item):
                        if item.arg == 'threads' and isinstance(item.value, _ast.Constant) and item.value.value == 2:
                            item.value = _ast.Constant(16); changed('runner_call')
                        return item
                    def visit_Dict(self, item):
                        for i, key in enumerate(item.keys):
                            if isinstance(key, _ast.Constant) and key.value == 'threads' and isinstance(item.values[i], _ast.Constant) and item.values[i].value == 2:
                                item.values[i] = _ast.Constant(16); changed('runner_result')
                        return self.generic_visit(item)
                node.value = _ast.Constant(_ast.unparse(Worker().visit(runner)))
            return self.generic_visit(node)
        def visit_FunctionDef(self, node):
            if node.name == '_source_files':
                node.body = [statement('return _producer_source_files()')]; changed('source_closure'); return node
            node = self.generic_visit(node)
            if node.name == 'prepare':
                for i, item in enumerate(node.body):
                    if same(item, "_require(type(time_limit_seconds) is int and 1 <= time_limit_seconds <= 7200, 'The private reference limit must be 1..7200 seconds')"):
                        node.body[i] = statement("_require(type(time_limit_seconds) is int and time_limit_seconds == 3600, 'The private producer uses one declared 3600-second attempt')"); changed('prepare_time')
                # Bind the profile before the original immutable preparation write.
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Dict) and any(isinstance(k, _ast.Constant) and k.value == 'prepared_at' for k in item.keys):
                        item.keys.append(_ast.Constant('producer_profile')); item.values.append(_ast.Call(func=_ast.Name(id='profile_reference', ctx=_ast.Load()), args=[], keywords=[])); changed('profile_bind')
            elif node.name == 'validate_prepared':
                node.body.insert(2, statement("_require(frozen['producer_profile'] == profile_reference(), 'The private producer profile binding changed')")); changed('profile_guard')
            return node
        def visit_Dict(self, node):
            for index, key in enumerate(node.keys):
                if isinstance(key, _ast.Constant) and key.value in ('cpus', 'threads') and isinstance(node.values[index], _ast.Constant) and node.values[index].value == 2:
                    node.values[index] = _ast.Constant(16); changed('resource_or_thread_dict')
            return self.generic_visit(node)
        def visit_Compare(self, node):
            text = _ast.unparse(node)
            if text in ("request['threads'] == 2", "runtime.get('threads') == 2", "solver.get('threads') == 2"):
                node.comparators[0] = _ast.Constant(16); changed('thread_guard')
            elif text == "actual['NanoCpus'] == 2 * 10 ** 9":
                node.comparators[0] = _ast.parse('16 * 10**9', mode='eval').body; changed('actual_cpu')
            elif text == "1 <= request['time_limit_seconds'] <= 7200":
                node = _ast.parse("request['time_limit_seconds'] == 3600", mode='eval').body; changed('validation_time')
            return self.generic_visit(node)
        def visit_List(self, node):
            for i, item in enumerate(node.elts[:-1]):
                if isinstance(item, _ast.Constant) and item.value == '--cpus' and isinstance(node.elts[i+1], _ast.Constant) and node.elts[i+1].value == '2':
                    node.elts[i+1] = _ast.Constant('16'); changed('create_cpu')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if isinstance(node.value, str) and 'sf-private-integer-' in node.value:
                node.value = node.value.replace('sf-private-integer-', 'sf-producer16-integer-'); changed('owned_name')
            return node
    tree = Adapt().visit(tree)
    expected = {'preparation_kind': 1, 'terminal_kind': 1, 'backend': 1, 'runner_call': 1, 'runner_result': 1,
        'source_closure': 1, 'prepare_time': 1, 'profile_bind': 1, 'profile_guard': 1,
        'resource_or_thread_dict': 3, 'thread_guard': 3, 'actual_cpu': 1, 'validation_time': 1,
        'create_cpu': 1, 'owned_name': 2}
    if counts != expected:
        raise ValueError('The exact producer-only runtime substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
