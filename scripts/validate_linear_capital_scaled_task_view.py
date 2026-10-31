#!/usr/bin/env python3
"""Validate N360 task views with the complete actual calculation gates.

Preparation reads existing evidence. Only the explicit run command starts the
seven modeling or eleven debugging calculations; neither path calls a model.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM = _Path(__file__).with_name('validate_linear_capital_task_view.py')
UPSTREAM_SHA256 = '24decf5b019f1183ef6c7538c4947e9757cd160d1f11c54d9e3fce36582ae974'
VERSION = 2


def adapted_ast():
    """Retain every actual-evidence gate in a separate, versioned namespace."""
    raw = UPSTREAM.read_bytes()
    if UPSTREAM != UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen complete actual task validator changed')
    tree = _ast.parse(raw, filename=str(UPSTREAM)); counts = {}
    def changed(key): counts[key] = counts.get(key, 0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], _ast.Name) and node.targets[0].id == 'SOURCE_PROVIDERS':
                changed('provider')
                node.value = _ast.parse("{'scaled360': ('build_linear_capital_scaled_source.py', 'independently_verified_linear_capital_scaled_native_source')}", mode='eval').body
                return node
            return self.generic_visit(node)
        def visit_ImportFrom(self, node):
            if node.module == 'sheets_factory.workbook.linear_capital_portfolio':
                node.module = 'sheets_factory.workbook.linear_capital_scaled'; changed('schema')
            return node
        def visit_Constant(self, node):
            if node.value == 'linear_capital_task_view_actual_validation':
                node.value = 'linear_capital_scaled_task_view_actual_validation'; changed('kind')
            elif node.value == 'materialized_unverified_linear_capital_task_view':
                node.value = 'materialized_unverified_linear_capital_scaled_task_view'; changed('material')
            elif node.value == 'standard':
                node.value = 'scaled360'; changed('default')
            return node
        def visit_FunctionDef(self, node):
            node = self.generic_visit(node)
            if node.name in ('prepare', 'execute_prepared'):
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Dict):
                        for key, value in zip(item.keys, item.values):
                            if isinstance(key, _ast.Constant) and key.value == 'version' and isinstance(value, _ast.Constant) and value.value == 1:
                                value.value = VERSION; changed('envelope')
            elif node.name in ('validate_prepared', 'validate_completed'):
                for item in _ast.walk(node):
                    if isinstance(item, _ast.Compare) and _ast.unparse(item) in ("frozen['version'] == 1", "result['version'] == 1"):
                        item.comparators[0] = _ast.Constant(VERSION); changed('version_gate')
            return node
    # The old CLI runs only in its own script. The new CLI below has no provider
    # override: old source providers can never enter this namespace.
    tree.body = [node for node in tree.body if not (isinstance(node, _ast.If)
        and _ast.dump(node.test) == _ast.dump(_ast.parse("__name__ == '__main__'", mode='eval').body))]
    tree = Adapt().visit(tree)
    if counts != {'provider': 1, 'schema': 2, 'kind': 1, 'material': 1,
                  'default': 8, 'envelope': 2, 'version_gate': 2}:
        raise ValueError('The exact N360 actual task substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
_base_recipes = recipes


def recipes(provider='scaled360'):
    adapted_ast()
    return {**_base_recipes(provider), str(UPSTREAM.resolve()): UPSTREAM_SHA256}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    entry = commands.add_parser('prepare')
    for name in ('source-manifest', 'view-manifest', 'output'):
        entry.add_argument('--'+name, type=Path, required=True)
    for command in ('run', 'validate'):
        entry = commands.add_parser(command); entry.add_argument('--prepared', type=Path, required=True)
    entry = commands.add_parser('validate-completed'); entry.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare': result = prepare(args.source_manifest, args.view_manifest, args.output)
    elif args.command == 'run': result = execute_prepared(args.prepared)
    elif args.command == 'validate': result = validate_prepared(args.prepared)[0]
    else: result = validate_completed(args.receipt)
    print(json.dumps(result, ensure_ascii=False)); return 0


if __name__ == '__main__': raise SystemExit(main())
