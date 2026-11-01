#!/usr/bin/env python3
"""Prepare the same fixed200 FM normal review with scoped historical provenance."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN_ENTRY = ROOT/'scripts/run_operating_reports_200_quality.py'
FROZEN_ENTRY_SHA = 'aee22d0166c85f44c9ee0dc1dfa9a88c79627a27374ea59cc68692c73841e6ea'
if hashlib.sha256(FROZEN_ENTRY.read_bytes()).hexdigest() != FROZEN_ENTRY_SHA:
    raise ValueError('The frozen first fixed200 normal entry changed')

_tree = ast.parse(FROZEN_ENTRY.read_bytes())
_counts = {}
class _Adapter(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module == 'sheets_factory.pipelines' and len(node.names) == 1 and node.names[0].name == 'operating_reports_200_quality':
            _counts['pipeline'] = _counts.get('pipeline', 0)+1
            return ast.copy_location(ast.ImportFrom(module='sheets_factory.task_adapters.operating_reports_200_quality_revision2',
                names=[ast.alias(name='pipeline')], level=0), node)
        if node.module == 'sheets_factory.task_adapters' and len(node.names) == 1 and node.names[0].name == 'operating_reports_200_quality':
            _counts['nodes'] = _counts.get('nodes', 0)+1
            node.names[0].name = 'operating_reports_200_quality_revision2'
        return node
    def visit_Constant(self, node):
        if node.value == 'prepared_fixed200_financial_modeling_reference_quality':
            _counts['kind'] = _counts.get('kind', 0)+1
            return ast.copy_location(ast.Constant(value='prepared_fixed200_financial_modeling_reference_quality_revision2'), node)
        return node
_tree = _Adapter().visit(_tree)
if _counts != {'pipeline': 1, 'nodes': 1, 'kind': 1}:
    raise ValueError('The exact first fixed200 normal entry seams changed')
# Do not execute the ancestor's main guard before the complete recipe is bound.
_tree.body = [node for node in _tree.body if not (isinstance(node, ast.If)
    and ast.dump(node.test) == ast.dump(ast.parse("__name__ == '__main__'").body[0].value))]
exec(compile(ast.fix_missing_locations(_tree), str(FROZEN_ENTRY), 'exec'), globals())
_first_recipes = recipes


def recipes(config, admissions):
    result = _first_recipes(config, admissions)
    for path in (FROZEN_ENTRY, *nodes.ANCESTORS):
        row = reference(path); result[row['path']] = row['sha256']
    pipeline.References().check(nodes.FAILURE_DIAGNOSIS)
    result[nodes.FAILURE_DIAGNOSIS['path']] = nodes.FAILURE_DIAGNOSIS['sha256']
    return result


_namespace['recipes'] = recipes


def _trial_agent_identity(config, result, config_path, staged, expected_agent):
    """Link sparse original trial metadata to its rich immutable result config."""
    rich = result.get('config')
    require(isinstance(config, dict) and isinstance(rich, dict), 'Complete original and result trial configurations are required')
    thin_task, rich_task = config.get('task'), rich.get('task')
    require(isinstance(thin_task, dict) and isinstance(rich_task, dict)
        and thin_task.get('path') == rich_task.get('path') == str(staged)
        and all(key in rich_task and rich_task[key] == value for key, value in thin_task.items()),
        'The sparse and rich trial task identities differ')
    parent = Path(config_path).parent
    require(type(config.get('trial_name')) is str and bool(config['trial_name'])
        and config['trial_name'] == rich.get('trial_name') == result.get('trial_name') == parent.name
        and config.get('trials_dir') == rich.get('trials_dir') == str(parent.parent)
        and type(config.get('job_id')) is str and bool(config['job_id'])
        and config['job_id'] == rich.get('job_id'),
        'The sparse and rich trial, physical directory or job identities differ')
    require(expected_agent in ('oracle', 'nop')
        and isinstance(rich.get('agent'), dict) and rich['agent'].get('name') == expected_agent
        and isinstance(result.get('agent_info'), dict) and result['agent_info'].get('name') == expected_agent,
        'The rich actual control agent identity differs')
    if 'agent' in config:
        require(isinstance(config['agent'], dict) and config['agent'].get('name') == expected_agent,
            'The supplied sparse control agent identity differs')
    return expected_agent


_gate_tree = ast.parse(UPSTREAM.read_bytes())
_gate = next(node for node in _gate_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'validate_normal_resources')
_getter = ast.dump(ast.parse("config['agent']['name']").body[0].value, include_attributes=False)
_gate_replacements = []
class _TrialIdentity(ast.NodeTransformer):
    def visit_Subscript(self, node):
        if ast.dump(node, include_attributes=False) == _getter:
            _gate_replacements.append('strict_trial_agent_identity')
            return ast.copy_location(ast.parse('_trial_agent_identity(config, result, config_path, staged, agent)').body[0].value, node)
        return self.generic_visit(node)
_gate = _TrialIdentity().visit(_gate)
require(_gate_replacements == ['strict_trial_agent_identity'], 'The exact generic trial agent getter seam changed')
_namespace['_trial_agent_identity'] = _trial_agent_identity
exec(compile(ast.fix_missing_locations(ast.Module(body=[_gate], type_ignores=[])), str(UPSTREAM), 'exec'), _namespace)
validate_normal_resources = _namespace['validate_normal_resources']

if __name__ == '__main__':
    raise SystemExit(main())
