"""Prospective v4 publication clocks; no migration of earlier selections.

The generic publisher still owns quality, actual trials, scores and atomic
payload copying. This namespace changes only the declared timing contract and
its evidence projection. Bounds remain bounds.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from types import ModuleType, SimpleNamespace

from . import clock_resource_publication as previous
from .clock_resource_frontier_v4 import POLICY_V4
from .tool_time_clock_bounds_v4 import account_complete_clock_overlap

ROOT = Path(__file__).resolve().parents[3]
PREVIOUS_SHA256 = '600b871aecbf24f9adcb936e955dc6e2513a8087ae9bd31ebc4e52e7b8cb672a'


def guard():
    previous._frozen_ast(previous.__file__, PREVIOUS_SHA256)


def _policy_v4(frozen, require):
    require(type(frozen.get('tool_time_policy_version')) is int
            and frozen['tool_time_policy_version'] == 4
            and frozen.get('tool_time_policy') == POLICY_V4,
            'Publication requires the complete prospectively frozen version-four policy')
    return dict(POLICY_V4)


def _track_v4(timing, result_path, tracked, backend, base_tracker, release, require):
    guard()
    require(backend is not None and getattr(backend.runner, 'POLICY_V4', None) == POLICY_V4
            and timing.get('policy_version') == 4, 'An explicit version-four publication backend is required')
    branch = timing.get('measurement_branch')
    if branch == 'unchanged_v3_exact_or_bound':
        old = timing['base_policy_v3_receipt']
        # A timing-only context checks the retained earlier proof. It supplies
        # no task admission, source family, score or trial identity methods.
        context = SimpleNamespace(runner=SimpleNamespace(POLICY_V3=previous._POLICY_V3), cohort=backend.cohort)
        require({k: v for k, v in timing.items() if k not in
                 {'policy_version', 'method', 'measurement_branch', 'base_policy_v3_receipt'}} ==
                {k: v for k, v in old.items() if k not in {'policy_version', 'method', 'measurement_branch'}},
                'The retained earlier timing proof was changed')
        return previous._track_v3(old, result_path, tracked, context, base_tracker, release, require)
    require(branch == 'complete_proven_owned_overlap'
            and timing.get('state') == 'verified_owned_overlap_bound' and timing.get('passed') is True,
            'Only a complete proved owned-overlap bound can reach publication')
    clock = timing.get('complete_owned_overlap_receipt')
    require(isinstance(clock, dict) and clock == account_complete_clock_overlap(result_path, budget_seconds=1800),
            'The original full raw timing evidence does not reproduce the frozen v4 bound')
    require(clock.get('complete') is True and clock.get('passed') is True
            and clock.get('state') == 'verified_owned_overlap_bound'
            and clock.get('cumulative_tool_seconds') is None and clock.get('cumulative_exact_ns') is None
            and type(clock.get('cumulative_lower_bound_ns')) is int
            and type(clock.get('cumulative_upper_bound_ns')) is int
            and 0 <= clock['cumulative_lower_bound_ns'] <= clock['cumulative_upper_bound_ns'] < 1800*10**9,
            'The v4 interval is incomplete, exactified or not strictly below budget')
    require(all(timing.get(k) == value for k, value in clock.items() if k != 'method')
            and timing.get('method') == POLICY_V4['measurement'], 'The projected timing bound changed')
    evidence = base_tracker(clock['original_exact_receipt'], result_path, tracked)
    old = timing['base_policy_v3_receipt']
    require(old.get('state') == 'unknown', 'The new branch must retain the earlier unknown')
    base_tracker(old['base_policy_v2_receipt'], result_path, tracked)
    recipe = backend.cohort['publication_recipe']
    approved = ('src/sheets_factory/evaluation/tool_time_clock_bounds_v4.py',
                'src/sheets_factory/evaluation/tool_time_clock_bounds.py',
                'src/sheets_factory/evaluation/tool_time.py')
    code = {recipe[name]['path'] for name in approved}
    native = clock['original_exact_receipt']['session_files']
    require(len(native) == 1, 'Require one complete original native session')
    result_path = Path(result_path).absolute()
    require(Path(native[0]['path']).is_relative_to(result_path.parent/'agent/sessions'),
            'Native timing evidence escaped its original trial')
    trial = {str(result_path), str(result_path.parent/'agent/codex.txt'), native[0]['path']}
    artifacts = clock.get('artifacts', [])
    require(len(artifacts) == 6 and len({r.get('path') for r in artifacts}) == 6
            and {r.get('path') for r in artifacts} == code | trial,
            'The v4 proof must bind exactly the original trial and three frozen parsers')
    for record in artifacts:
        if record['path'] in code:
            require(record in [recipe[name] for name in approved], 'Timing parser is outside the prospective recipe')
            actual = previous.reference(record['path'])
        else:
            release._file(Path(record['path']), result_path.parent, tracked)
            actual = previous.reference(record['path'])
        require(actual == record, 'Original v4 timing evidence changed')
        require(tracked.setdefault(record['path'], record['sha256']) == record['sha256'],
                'Conflicting v4 timing evidence identity')
    # Preserve all originally inspected stop-chain files even though the
    # complete normal-tail proof does not use a stop as an elapsed shortcut.
    stop_path = result_path.parent/'private/tool_time/stop_receipt.json'
    if stop_path.is_file():
        import json
        stop = json.loads(release._file(stop_path, result_path.parent, tracked))
        for record in (stop.get('identity_file'), stop.get('result_file')):
            require(isinstance(record, dict), 'An inspected stop-chain input is missing')
            release._file(Path(record['path']), result_path.parent, tracked)
            require(previous.reference(record['path']) == record, 'An inspected stop-chain input changed')
        identity = json.loads(Path(stop['identity_file']['path']).read_bytes())
        config = identity.get('trial_config')
        require(isinstance(config, dict), 'The inspected stop identity lacks its configuration')
        release._file(Path(config['path']), result_path.parent, tracked)
        require(previous.reference(config['path']) == config, 'The inspected stop configuration changed')
    return {**evidence, 'complete_owned_overlap_artifact_sha256': {r['path']: r['sha256'] for r in artifacts},
            'clock_bound_is_exact': False}


def _project_v4(timing, evidence, require):
    require(timing.get('policy_version') == 4, 'Timing projection requires version four')
    if timing.get('measurement_branch') == 'unchanged_v3_exact_or_bound':
        result = previous._project_v3(timing['base_policy_v3_receipt'], evidence, require)
        result.update(policy_version=4, method=timing['method'], measurement_branch=timing['measurement_branch'],
                      retained_v3_measurement_branch=timing['base_policy_v3_receipt']['measurement_branch'])
        return result
    require(timing.get('state') == 'verified_owned_overlap_bound' and timing.get('passed') is True
            and timing.get('cumulative_tool_seconds') is None and timing.get('cumulative_exact_ns') is None,
            'A v4 interval must retain unknown exact time')
    keys = ('method', 'budget_seconds', 'strict_less_than', 'state', 'passed', 'model_response_time_included',
            'parallel_executions', 'cumulative_tool_seconds', 'cumulative_exact_ns', 'cumulative_lower_bound_ns',
            'cumulative_upper_bound_ns', 'cumulative_lower_bound_seconds', 'cumulative_upper_bound_seconds',
            'primitive_upper_sum_ns', 'wrapper_upper_sum_ns', 'overlap_credit_ns', 'clock_disagreement_count')
    return {**{k: timing[k] for k in keys}, 'policy_version': 4, 'measurement_branch': timing['measurement_branch'],
            'cumulative_tool_nanoseconds': None, 'coverage': timing['coverage'], 'evidence_sha256': evidence}


def publisher_ast():
    guard(); tree = previous.publisher_ast(); counts = {name: 0 for name in ('_policy_v3', '_track_v3', '_project_v3')}
    class Names(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in counts:
                counts[node.id] += 1; node.id = node.id[:-1]+'4'
            return node
    tree = Names().visit(tree)
    if counts != {'_policy_v3': 1, '_track_v3': 1, '_project_v3': 1}:
        raise ValueError('The exact v3 publisher timing call sites changed')
    return ast.fix_missing_locations(tree)


@lru_cache(maxsize=1)
def publisher_namespace():
    module = ModuleType('sheets_factory_clock_v4_isolated_dataset_publisher')
    module.__file__ = str(ROOT/'scripts/publish_linear_capital_scaled_v4.py')
    module.__dict__.update(_policy_v4=_policy_v4, _track_v4=_track_v4, _project_v4=_project_v4)
    exec(compile(publisher_ast(), module.__file__, 'exec'), module.__dict__)
    return module
