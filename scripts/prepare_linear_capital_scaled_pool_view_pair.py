#!/usr/bin/env python3
"""Apply the complete paired-view lifecycle to one fixed N360 pool member."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM = _Path(__file__).with_name('prepare_linear_capital_scaled_view_pair.py')
UPSTREAM_SHA256 = 'eda80d92e2172ea5d8f2119573c5f3495981f996fb4cb28c5ca3b0709dc5ca47'
POOL_POLICY_SHA256 = '3709050d1dc831704f234618308b715c0b81edff9fc7b454c152f0d4da1b0dec'


def adapted_ast():
    raw = UPSTREAM.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen complete P01 pair lifecycle changed')
    tree = _ast.parse(raw, filename=str(UPSTREAM))
    counts = {}
    strings = {
        'config/pipelines/linear_capital_scaled_view_pair_v2.json':
            'config/pipelines/linear_capital_scaled_pool_view_pair_v2.json',
        'e8dd5d8ed7e3c22e795c8fd0e0e6d24578110a92f260a2a5bfea12a6d0578ef9': POOL_POLICY_SHA256,
        'prepared_linear_capital_scaled_first_view_pair': 'prepared_linear_capital_scaled_pool_view_pair',
        'linear_capital_scaled_first_view_pair_actual_validation': 'linear_capital_scaled_pool_view_pair_actual_validation',
        'The complete fixed first-profile pair policy changed': 'The complete frozen pool pair policy changed',
        'P01 paired N360 task materialization and actual validation': 'Fixed-pool N360 paired task materialization and actual validation',
    }

    def changed(key): counts[key] = counts.get(key, 0) + 1

    class Adapt(_ast.NodeTransformer):
        function = None

        def visit_Constant(self, node):
            if type(node.value) is str and node.value in strings:
                before = node.value; node.value = strings[before]; changed(before)
            return node

        def visit_FunctionDef(self, node):
            previous = self.function; self.function = node.name
            if node.name == 'checked_source':
                changed('checked_source')
                node.body = _ast.parse('return _checked_pool_source(value, configuration)').body
            else:
                node = self.generic_visit(node)
            self.function = previous
            return node

        def visit_Dict(self, node):
            node = self.generic_visit(node)
            if self.function == 'prepare' and any(isinstance(k, _ast.Constant)
                    and k.value == 'both_modes_fixed_before_any_materialization' for k in node.keys):
                key = next(i for i,k in enumerate(node.keys) if isinstance(k, _ast.Constant) and k.value == 'profile_id')
                if _ast.unparse(node.values[key]) != "config['first_profile']['id']":
                    raise ValueError('The original prepared profile binding changed')
                node.values[key] = _ast.parse("_profile_identity(source, config)['profile_id']", mode='eval').body
                node.keys.append(_ast.Constant('pool_identity'))
                node.values.append(_ast.parse('_profile_identity(source, config)', mode='eval').body)
                changed('prepared_profile_identity')
            return node

        def visit_Compare(self, node):
            if self.function == 'validate_prepared' and _ast.unparse(node) == "frozen['profile_id'] == config['first_profile']['id']":
                changed('cold_profile_membership')
                return _ast.parse("frozen['profile_id'] in config['profile_order']", mode='eval').body
            return self.generic_visit(node)

        def visit_Call(self, node):
            node = self.generic_visit(node)
            if (self.function == 'validate_prepared' and isinstance(node.func,_ast.Name)
                    and node.func.id == 'require' and len(node.args) == 2
                    and isinstance(node.args[1],_ast.Constant)
                    and node.args[1].value == 'The admitted source or resource profile changed'):
                changed('cold_exact_source_profile')
                node.args[0] = _ast.BoolOp(op=_ast.And(), values=[node.args[0],
                    _ast.parse("_profile_identity(source, config) == frozen['pool_identity']", mode='eval').body,
                    _ast.parse("frozen['profile_id'] == frozen['pool_identity']['profile_id']", mode='eval').body])
            return node

    tree = Adapt().visit(tree)
    tree.body = [node for node in tree.body if not (isinstance(node,_ast.If)
        and _ast.dump(node.test) == _ast.dump(_ast.parse("__name__ == '__main__'",mode='eval').body))]
    expected = {key:1 for key in strings}
    expected.update(checked_source=1, prepared_profile_identity=1,
                    cold_profile_membership=1, cold_exact_source_profile=1)
    if counts != expected:
        raise ValueError('The exact isolated pool substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
_base_recipes = recipes


def recipes():
    return {**_base_recipes(), str(UPSTREAM.resolve()): reference(UPSTREAM)['sha256']}


def _pool_evidence(configuration):
    order = [f'L360-P{i:02d}' for i in range(1,21)]
    require(configuration.get('kind') == 'linear_capital_scaled_fixed_pool_view_pair_policy'
        and type(configuration.get('version')) is int and configuration['version'] == 2
        and configuration['profile_order'] == order
        and configuration['first_development_profile'] == 'L360-P01'
        and configuration['does_not_change_first_development_or_authorize_models'] is True,
        'The complete original pool order and first-development declaration are required')
    catalog = read(configuration['raw_catalog']); inventory = read(configuration['finance_inventory'])
    rows = configuration['profiles']
    require(catalog.get('kind') == 'prepared_scaled_linear_complete_raw_pool'
        and type(catalog.get('version')) is int and catalog['version'] == 2
        and catalog['profile_order'] == order and catalog['first_development_profile'] == 'L360-P01'
        and catalog['all_profiles_frozen_before_financial_execution'] is True
        and type(rows) is list and len(rows) == 20 and [row['profile_id'] for row in rows] == order
        and [{k:v for k,v in row.items() if k != 'financial_crosscheck'} for row in rows] == catalog['profiles']
        and all(type(row['seed']) is int and row['seed'] == 202701361+i
            and type(row['revenue_jitter_pence']) is int and row['revenue_jitter_pence'] == 150000
            for i,row in enumerate(rows)), 'The frozen complete raw profile identities differ')
    require(set(inventory) == {'kind','version','raw_catalog','profile_order','profiles'}
        and inventory['kind'] == 'completed_scaled_linear_finance_terminal_inventory'
        and type(inventory['version']) is int and inventory['version'] == 2
        and inventory['raw_catalog'] == configuration['raw_catalog'] and inventory['profile_order'] == order
        and inventory['profiles'] == [{'profile_id':row['profile_id'], 'terminal':row['financial_crosscheck']}
            for row in rows], 'The complete original finance inventory differs')
    return rows


def _profile_identity(source, configuration):
    rows = _pool_evidence(configuration)
    independent = read(source['independent_reference']); raw = read(independent['raw_preparation'])
    selected = [row for row in rows if row['profile_id'] == raw.get('profile_id')]
    require(len(selected) == 1, 'The actual source must belong to the complete frozen N360 pool')
    row = selected[0]
    require(independent.get('kind') == configuration['reference_kind'] and independent.get('passed') is True
        and raw.get('kind') == 'prepared_linear_capital_scaled_raw_assumptions'
        and type(raw.get('version')) is int and raw['version'] == 2
        and type(raw.get('seed')) is int and raw['seed'] == row['seed']
        and type(raw.get('revenue_jitter_pence')) is int and raw['revenue_jitter_pence'] == row['revenue_jitter_pence']
        and raw.get('prospective_profile_order') == configuration['profile_order']
        and independent['raw_preparation'] == row['raw_preparation']
        and independent['specification'] == raw['specification'] == row['specification']
        and independent['financial_crosscheck'] == source['financial_crosscheck'] == row['financial_crosscheck'],
        'The actual reference/source does not match its original raw and finance member')
    require((source['public_specification']['sha256'], source['public_specification']['bytes']) ==
        (row['specification']['sha256'], row['specification']['bytes']),
        'The source primitives differ from the original pool member bytes')
    return {'profile_id':row['profile_id'], 'seed':row['seed'], 'revenue_jitter_pence':row['revenue_jitter_pence'],
        'original_specification':row['specification'], 'raw_preparation':row['raw_preparation'],
        'financial_crosscheck':row['financial_crosscheck'], 'raw_catalog':configuration['raw_catalog'],
        'finance_inventory':configuration['finance_inventory']}


def _checked_pool_source(value, configuration):
    helper = support('source'); record = value if isinstance(value,dict) else reference(value)
    source = helper.validate_source(record)
    require(source.get('kind') == configuration['source_kind'] and type(source.get('version')) is int
        and source['version'] == 1 and source.get('status') == 'source_verified_not_task_or_difficulty_qualified'
        and source.get('source_financially_verified') is True and source.get('qualified') is False,
        'An actual complete N360 source admission is required; pending or old sources do not qualify')
    _profile_identity(source, configuration)
    profile, value = helper.runtime(source['runtime_profile']['path'])
    require(profile == source['runtime_profile'] == reference(ROOT/configuration['runtime_profile'])
        and value['image']['id'] == configuration['image_id']
        and all(value['docker_resources'][role] == configuration['resources'] for role in ('source','agent','verifier')),
        'All source/calculation and configured verifier resources must retain the same pinned 2CPU32 profile')
    return record, source


if __name__ == '__main__': raise SystemExit(main())
