"""Prospective stream resilience in an isolated copy of the frozen v3 runner.

Only factory.stream_max_retries=8 changes native transport. HTTP request retries,
idle timeout, model, effort, tools, resources and all scoring remain unchanged.
This mitigation does not establish the cause of any previous stream failure.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
import json as _json
from pathlib import Path as _Path

from .clock_resource_frontier import (adapted_ast as _clock_ast, _v3_provenance,
    account_trial_tool_time_v3, POLICY_V3)

PROFILE_PATH = _Path(__file__).resolve().parents[3]/'config/native_transport_profiles/factory_stream_retries8_v1.json'
PROFILE_SHA256 = '90b4bacd77289b5e9799cd82b627377ba03addcbcbc101dcf00ad45848e3df15'


def transport_profile():
    """Return a fresh copy of one exact, noncredential transport profile."""
    raw = PROFILE_PATH.read_bytes()
    if PROFILE_PATH != PROFILE_PATH.resolve() or _hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('The prospective native transport profile changed')
    return _json.loads(raw)


def _transport_provenance():
    transport_profile()
    return {'native_transport_profile': {'path': str(PROFILE_PATH),
        'sha256': PROFILE_SHA256, 'bytes': PROFILE_PATH.stat().st_size},
        'native_transport_adapter': {'path': str(_Path(__file__).resolve()),
            'sha256': _hashlib.sha256(_Path(__file__).read_bytes()).hexdigest()}}


def adapted_ast():
    """Fail closed unless each small prospective substitution occurs once."""
    transport_profile()
    tree = _clock_ast()
    counts = {'provider': 0, 'agent_path': 0, 'source_guard': 0, 'selection_profile': 0,
              'selection_guard': 0, 'provenance': 0}
    def parsed(statement):
        return _ast.parse(statement).body[0]
    provider = _ast.parse("{'name': 'factory', 'base_url': base_url, 'env_key': 'OPENAI_API_KEY', 'wire_api': 'responses'}", mode='eval').body
    for node in tree.body:
        if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        if node.name == '_job_config':
            class Provider(_ast.NodeTransformer):
                def visit_Dict(self, value):
                    if _ast.dump(value) == _ast.dump(provider):
                        value.keys.append(_ast.Constant('stream_max_retries'))
                        value.values.append(_ast.Constant(8)); counts['provider'] += 1
                    return self.generic_visit(value)
            Provider().visit(node)
        elif node.name == 'freeze_selection':
            for index, item in reversed(list(enumerate(node.body))):
                if _ast.dump(item) == _ast.dump(parsed('source = json.loads(source_raw)')):
                    node.body.insert(index+1, parsed("_require(source.get('native_transport_profile') == transport_profile(), 'The prospective transport profile must be frozen in the source')"))
                    counts['source_guard'] += 1
                if _ast.dump(item) == _ast.dump(parsed('_selection_execution_budget(selection)')):
                    node.body.insert(index, parsed("selection['native_transport_profile'] = transport_profile()"))
                    counts['selection_profile'] += 1
        elif node.name == '_selection_execution_budget':
            node.body.insert(0, parsed("_require(selection.get('native_transport_profile') == transport_profile(), 'The frozen prospective transport profile changed')"))
            counts['selection_guard'] += 1
        elif node.name == '_runtime_provenance':
            returns = [i for i, item in enumerate(node.body) if isinstance(item, _ast.Return)]
            if len(returns) != 1:
                raise ValueError('The prospective provenance return changed')
            node.body.insert(returns[0], parsed('provenance.update(_transport_provenance())'))
            counts['provenance'] += 1
    class AgentPath(_ast.NodeTransformer):
        def visit_Constant(self, value):
            if value.value == 'sheets_factory.evaluation.clock_resource_frontier:LocalCodex':
                counts['agent_path'] += 1
                value.value = 'sheets_factory.evaluation.native_transport_frontier:LocalCodex'
            return value
    tree = AgentPath().visit(tree)
    if counts != {'provider': 1, 'agent_path': 2, 'source_guard': 1, 'selection_profile': 1,
                  'selection_guard': 1, 'provenance': 1}:
        raise ValueError('The exact prospective transport substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


# This globals dictionary is separate from every original runner namespace.
exec(compile(adapted_ast(), __file__, 'exec'), globals())
