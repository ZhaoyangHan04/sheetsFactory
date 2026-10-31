"""Isolated prospective V3 publication namespaces, without score migration.

Only policy recognition, durable timing evidence and timing projection differ
from the frozen resource publication code. Existing source-family admission is
retained: heterogeneous source families are deliberately not admitted here.
"""
from __future__ import annotations

import ast as _ast
from functools import lru_cache as _lru_cache
import hashlib as _hashlib
import json as _json
from pathlib import Path as _Path
from types import ModuleType as _ModuleType

from .clock_resource_frontier import POLICY_V3 as _POLICY_V3

_BASE_ROOT = _Path(__file__).resolve().parents[3]
RESOURCE_PUBLICATION_SHA256 = '1836419e3a72b529709e2398430388cbf29214cbf1fd6d631b4152e88bdadfdb'
DATASET_PUBLISHER_SHA256 = '7075abd9032d558c79e9408782a0429a5c3d99fd4d76a2ec4987c4c6eea4350e'
RESOURCE_CLI_SHA256 = 'd38499cc259ce7f8afe58c70ca5ad5a6e9e851714fb428c40a280c8d9c32faf3'
_EXTRA_RECIPE = (
    'src/sheets_factory/evaluation/clock_resource_publication.py',
    'scripts/publish_clock_resource_dataset.py',
    'src/sheets_factory/evaluation/clock_resource_frontier.py',
    'scripts/evaluate_clock_resource_difficulty.py',
    'src/sheets_factory/evaluation/tool_time_clock_bounds.py')


def _frozen_ast(path, expected):
    raw = _Path(path).read_bytes()
    if _hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('The exact frozen publication template changed: ' + str(path))
    return _ast.parse(raw, filename=str(path))


def _same(node, source):
    return _ast.dump(node) == _ast.dump(_ast.parse(source).body[0])


def _policy_v3(frozen, require):
    policy = frozen.get('tool_time_policy')
    require(policy == _POLICY_V3 and type(frozen.get('tool_time_policy_version')) is int
            and frozen['tool_time_policy_version'] == 3,
            'Confirmation must freeze the complete explicit prospective version-three tool policy')
    return dict(policy)


def _track_v3(timing, result_path, tracked, backend, base_tracker, release, require):
    """Check trial files inside the trial; check code only against the cohort recipe."""
    require(backend is not None and getattr(backend.runner, 'POLICY_V3', None) == _POLICY_V3
            and timing.get('policy_version') == 3, 'An explicit version-three publication backend is required')
    recipe = backend.cohort['publication_recipe']
    result_path = _Path(result_path).absolute()
    if timing.get('measurement_branch') == 'unchanged_exact_or_stop_bound':
        original = timing['base_policy_v2_receipt']
        # The original tracker still owns all old exact and container-stop chains.
        return base_tracker(original, result_path, tracked)
    require(timing.get('measurement_branch') == 'complete_clock_disagreement'
            and timing.get('state') == 'verified_conservative_bound' and timing.get('passed') is True,
            'Only an established complete-clock upper bound can reach publication')
    clock = timing['complete_clock_receipt']
    require(clock.get('state') == 'verified_conservative_bound' and clock.get('passed') is True
            and clock.get('complete') is True and clock.get('cumulative_exact_ns') is None
            and clock.get('cumulative_tool_seconds') is None
            and type(clock.get('cumulative_lower_bound_ns')) is int
            and type(clock.get('cumulative_upper_bound_ns')) is int
            and 0 <= clock['cumulative_lower_bound_ns'] <= clock['cumulative_upper_bound_ns'] < 1800*10**9,
            'Clock upper bound is incomplete, exactified, or not strictly below budget')
    evidence = base_tracker(clock['original_exact_receipt'], result_path, tracked)
    base_tracker(timing['base_policy_v2_receipt'], result_path, tracked)
    approved = {
        'implementation': 'src/sheets_factory/evaluation/tool_time_clock_bounds.py',
        'upstream_exact_parser': 'src/sheets_factory/evaluation/tool_time.py'}
    code_paths = set()
    for label, relative in approved.items():
        expected = recipe.get(relative)
        actual = clock.get(label)
        require(isinstance(expected, dict) and actual == expected,
                'Timing parser code is outside the frozen publication recipe')
        require(reference(expected['path']) == expected, 'Frozen timing implementation changed')
        require(tracked.setdefault(expected['path'], expected['sha256']) == expected['sha256'],
                'Conflicting timing implementation identity')
        code_paths.add(expected['path'])
    trial_paths = {str(result_path), str(result_path.parent/'agent/codex.txt')}
    sessions = clock['original_exact_receipt']['session_files']
    require(len(sessions) == 1, 'The complete clock proof requires exactly one original native session')
    native = _Path(sessions[0]['path']).absolute()
    require(native.is_relative_to(result_path.parent/'agent/sessions'), 'Native session escaped its original trial')
    trial_paths.add(str(native))
    artifacts = clock.get('artifacts')
    require(isinstance(artifacts, list) and len(artifacts) == len(trial_paths)+len(code_paths)
            and len({r.get('path') for r in artifacts}) == len(artifacts)
            and {r.get('path') for r in artifacts} == trial_paths | code_paths,
            'Complete clock artifact inventory differs from its exact approved inputs')
    for record in artifacts:
        if record['path'] in code_paths:
            require(reference(record['path']) == record, 'Timing implementation artifact changed')
        else:
            raw = release._file(_Path(record['path']), result_path.parent, tracked)
            require(type(record.get('bytes')) is int and len(raw) == record['bytes']
                    and _hashlib.sha256(raw).hexdigest() == record.get('sha256'),
                    'Original complete clock evidence changed')
    require(clock.get('result_file') == reference(result_path), 'Clock proof names another exact trial result')
    # The V2 accountant may have inspected a prospective stop receipt before
    # reaching its unknown result. Keep this input chain too, without changing
    # or claiming that it contributed to the complete-clock proof.
    stop_path = result_path.parent/'private/tool_time/stop_receipt.json'
    if stop_path.is_file():
        raw = release._file(stop_path, result_path.parent, tracked)
        stop = _json.loads(raw)
        for item in (stop.get('identity_file'), stop.get('result_file')):
            require(isinstance(item, dict), 'An inspected stop input reference is missing')
            payload = release._file(_Path(item['path']), result_path.parent, tracked)
            require(_hashlib.sha256(payload).hexdigest() == item['sha256'], 'Inspected stop input changed')
        identity = _json.loads(release._file(_Path(stop['identity_file']['path']), result_path.parent, tracked))
        config = identity.get('trial_config')
        require(isinstance(config, dict), 'Inspected stop identity lacks its original configuration')
        payload = release._file(_Path(config['path']), result_path.parent, tracked)
        require(_hashlib.sha256(payload).hexdigest() == config['sha256'], 'Inspected stop configuration changed')
    return {**evidence, 'complete_clock_artifact_sha256': {r['path']: r['sha256'] for r in artifacts},
            'clock_bound_is_exact': False}


def _project_v3(timing, evidence, require):
    """Serialize proven intervals as intervals; never create exact seconds."""
    common = ('method', 'budget_seconds', 'strict_less_than', 'state', 'passed',
              'cumulative_tool_seconds', 'model_response_time_included', 'parallel_executions')
    require(timing.get('policy_version') == 3, 'Timing projection requires version three')
    projected = {key: timing[key] for key in common}
    projected.update(policy_version=3, measurement_branch=timing['measurement_branch'])
    if timing['measurement_branch'] == 'complete_clock_disagreement':
        require(timing['state'] == 'verified_conservative_bound' and timing['passed'] is True
                and timing['cumulative_tool_seconds'] is None and timing['cumulative_exact_ns'] is None,
                'A complete clock bound must retain unknown exact timing')
        projected.update({key: timing[key] for key in ('exact_state', 'cumulative_exact_ns',
            'cumulative_lower_bound_ns', 'cumulative_upper_bound_ns',
            'cumulative_lower_bound_seconds', 'cumulative_upper_bound_seconds',
            'endpoint_margin_per_interval_ns', 'overlap_credit_ns', 'clock_disagreement_count')})
        projected.update(cumulative_tool_nanoseconds=None,
            native_tool_count=timing['coverage']['native_tool_count'],
            wrapper_call_count=timing['coverage']['wrapper_call_count'], evidence_sha256=evidence)
    else:
        base = timing['base_policy_v2_receipt']
        projected['cumulative_tool_nanoseconds'] = base.get('cumulative_tool_nanoseconds')
        projected.update({key: base[key] for key in ('exact_timing_state', 'lower_bound_seconds', 'upper_bound_seconds')})
        if base['state'] == 'bounded':
            projected.update({key: base[key] for key in ('lower_bound_nanoseconds', 'upper_bound_nanoseconds',
                                                       'upper_bound_may_include_idle_cleanup_time')})
            projected['evidence_sha256'] = evidence
    if 'threshold_reached' in timing:
        projected['threshold_reached'] = timing['threshold_reached']
    return projected


def publisher_ast():
    tree = _frozen_ast(_BASE_ROOT/'scripts/publish_dataset.py', DATASET_PUBLISHER_SHA256)
    counts = {'policy': 0, 'track': 0, 'track_call': 0, 'projection': 0, 'v2_projection': 0, 'threshold_projection': 0}
    for node in tree.body:
        if not isinstance(node, _ast.FunctionDef):
            continue
        if node.name == '_frozen_tool_time_policy':
            node.body = _ast.parse('return _policy_v3(frozen, _require)').body
            counts['policy'] += 1
        elif node.name == '_track_tool_time_evidence':
            node.name = '_base_track_tool_time_evidence'
            counts['track'] += 1
        elif node.name == '_validate_confirmation':
            class Projection(_ast.NodeTransformer):
                def visit_Call(self, item):
                    if isinstance(item.func, _ast.Name) and item.func.id == '_track_tool_time_evidence':
                        item.keywords.append(_ast.keyword(arg='backend', value=_ast.Name(id='backend', ctx=_ast.Load())))
                        counts['track_call'] += 1
                    return self.generic_visit(item)
                def visit_Assign(self, item):
                    # Replace exactly the public timing value, preserving all
                    # actual trial identity, raw reward and score computations.
                    if len(item.targets) == 1 and isinstance(item.targets[0], _ast.Name) and item.targets[0].id == 'public_result':
                        if not isinstance(item.value, _ast.Dict):
                            raise ValueError('The frozen public timing projection changed')
                        keys = [v.value if isinstance(v, _ast.Constant) else None for v in item.value.keys]
                        if keys != ['task_id', 'mode', 'reward', 'raw_verifier_reward', 'result_sha256', 'tool_time']:
                            raise ValueError('The exact public result fields changed')
                        item.value.values[-1] = _ast.parse('_project_v3(timing, timing_evidence, _require)', mode='eval').body
                        counts['projection'] += 1
                    return self.generic_visit(item)
                def visit_If(self, item):
                    if _ast.dump(item.test) == _ast.dump(_ast.parse("timing.get('policy_version') == 2", mode='eval').body):
                        counts['v2_projection'] += 1
                        return None
                    if _ast.dump(item.test) == _ast.dump(_ast.parse("'threshold_reached' in timing", mode='eval').body):
                        counts['threshold_projection'] += 1
                        return None
                    return self.generic_visit(item)
            Projection().visit(node)
    if counts != {'policy': 1, 'track': 1, 'track_call': 1, 'projection': 1, 'v2_projection': 1, 'threshold_projection': 1}:
        raise ValueError('A counted frozen publisher adaptation is missing or repeated: '+str(counts))
    wrapper = _ast.parse('''
def _track_tool_time_evidence(timing, result_path, tracked, *, backend=None):
    return _track_v3(timing, result_path, tracked, backend, _base_track_tool_time_evidence, release, _require)
''').body[0]
    # It is defined before the unchanged main guard, not executed as a CLI.
    tree.body.insert(-1, wrapper)
    return _ast.fix_missing_locations(tree)


@_lru_cache(maxsize=1)
def publisher_namespace():
    module = _ModuleType('sheets_factory_clock_v3_isolated_dataset_publisher')
    module.__file__ = str(_BASE_ROOT/'scripts/publish_clock_resource_dataset.py')
    module.__dict__.update(_policy_v3=_policy_v3, _track_v3=_track_v3, _project_v3=_project_v3)
    exec(compile(publisher_ast(), module.__file__, 'exec'), module.__dict__)
    return module


def backend_ast():
    tree = _frozen_ast(_BASE_ROOT/'src/sheets_factory/evaluation/resource_publication.py', RESOURCE_PUBLICATION_SHA256)
    counts = {'runner': 0, 'kind': 0, 'recipe': 0, 'publisher': 0, 'version': 0, 'agent': 0}
    for node in tree.body:
        if isinstance(node, _ast.ImportFrom) and node.level == 1 and node.module is None:
            if [(a.name, a.asname) for a in node.names] == [('resource_frontier', 'runner')]:
                node.names = [_ast.alias(name='clock_resource_frontier', asname='runner')]; counts['runner'] += 1
        elif isinstance(node, _ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, _ast.Name)]
            if targets == ['KIND']:
                node.value = _ast.Constant('frozen_resource_quality_cohort_clock_v3_for_fresh_confirmation'); counts['kind'] += 1
            elif targets == ['RECIPE_FILES']:
                if not isinstance(node.value, _ast.Tuple):
                    raise ValueError('The resource recipe declaration changed')
                node.value.elts.extend(_ast.Constant(x) for x in _EXTRA_RECIPE); counts['recipe'] += 1
        elif isinstance(node, _ast.ClassDef) and node.name == 'ResourcePublicationBackend':
            for item in node.body:
                if isinstance(item, _ast.Assign) and _same(item, "agent_import_path = 'sheets_factory.evaluation.resource_frontier:LocalCodex'"):
                    item.value = _ast.Constant('sheets_factory.evaluation.clock_resource_frontier:LocalCodex'); counts['agent'] += 1
                elif isinstance(item, _ast.FunctionDef):
                    if item.name == '__init__':
                        for index, statement in enumerate(item.body):
                            if _same(statement, "self.publisher = support(self.root, 'publish_dataset.py')"):
                                item.body[index] = _ast.parse('self.publisher = publisher_namespace()').body[0]; counts['publisher'] += 1
                    elif item.name == 'validate_cohort_shape':
                        class Version(_ast.NodeTransformer):
                            def visit_Compare(self, value):
                                if _ast.dump(value) == _ast.dump(_ast.parse("cohort.get('tool_time_policy_version') == 2", mode='eval').body):
                                    value.comparators[0] = _ast.Constant(3); counts['version'] += 1
                                return self.generic_visit(value)
                        Version().visit(item)
    if counts != {'runner': 1, 'kind': 1, 'recipe': 1, 'publisher': 1, 'version': 1, 'agent': 1}:
        raise ValueError('A counted resource backend adaptation is missing or repeated: '+str(counts))
    return _ast.fix_missing_locations(tree)


def cli_ast():
    tree = _frozen_ast(_BASE_ROOT/'scripts/publish_resource_dataset.py', RESOURCE_CLI_SHA256)
    counts = {'publisher': 0, 'backend': 0, 'version': 0}
    for node in tree.body:
        if isinstance(node, _ast.Import) and [(a.name, a.asname) for a in node.names] == [('publish_dataset', 'legacy')]:
            replacement = _ast.parse('from sheets_factory.evaluation.clock_resource_publication import publisher_namespace\nlegacy = publisher_namespace()').body
            index = tree.body.index(node); tree.body[index:index+1] = replacement; counts['publisher'] += 1
        elif isinstance(node, _ast.ImportFrom) and node.module == 'sheets_factory.evaluation.resource_publication':
            node.module = 'sheets_factory.evaluation.clock_resource_publication'; counts['backend'] += 1
    class Version(_ast.NodeTransformer):
        def visit_Dict(self, node):
            for index, key in enumerate(node.keys):
                if isinstance(key, _ast.Constant) and key.value == 'tool_time_policy_version':
                    if not isinstance(node.values[index], _ast.Constant) or node.values[index].value != 2:
                        raise ValueError('The frozen cohort timing declaration changed')
                    node.values[index] = _ast.Constant(3); counts['version'] += 1
            return self.generic_visit(node)
    Version().visit(tree)
    if counts != {'publisher': 1, 'backend': 1, 'version': 1}:
        raise ValueError('A counted V3 publication CLI adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(backend_ast(), __file__, 'exec'), globals())
ClockResourcePublicationBackend = ResourcePublicationBackend
