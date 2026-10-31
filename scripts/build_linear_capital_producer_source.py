#!/usr/bin/env python3
"""Explicit producer16-reference source adapter; source LO stays two CPU.

All original native emission, three complete A/B audits, two typed stability
checks and resource gates execute unchanged in a separate namespace. The new
reference proves one global best and runner and checks both financial paths.
"""
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM_SHA256 = '43b934bc84136ab96fa5b82239ad494ff7e03d7a8b0f9c57936c9b95c8ac659a'


def adapted_ast():
    path = _Path(__file__).with_name('build_linear_capital_source.py'); raw = path.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen three-pass native source builder changed')
    tree = _ast.parse(raw, filename=str(path)); counts = {'kind': 0, 'prepared': 0, 'provider': 0, 'reference_kind': 0}
    for node in tree.body:
        if isinstance(node, _ast.Assign):
            for target in node.targets:
                if isinstance(target, _ast.Name) and target.id == 'SOURCE_KIND':
                    node.value = _ast.Constant('independently_verified_linear_capital_producer16_native_source'); counts['kind'] += 1
                if isinstance(target, _ast.Name) and target.id == 'PREPARED_KIND':
                    node.value = _ast.Constant('prepared_linear_capital_producer16_native_source'); counts['prepared'] += 1
        elif isinstance(node, _ast.FunctionDef) and node.name == '_reference_provider':
            node.body = _ast.parse("return _module(ROOT/'scripts/run_linear_capital_producer_reference.py', '_linear_producer16_source_reference')").body
            counts['provider'] += 1
        elif isinstance(node, _ast.FunctionDef) and node.name == '_validate_reference':
            for value in _ast.walk(node):
                if isinstance(value, _ast.Constant) and value.value == 'linear_capital_independent_best_runner_reference':
                    value.value = 'linear_capital_producer16_best_runner_dual_financial_reference'; counts['reference_kind'] += 1
    if counts != {'kind': 1, 'prepared': 1, 'provider': 1, 'reference_kind': 1}:
        raise ValueError('The exact producer source-provider substitutions changed')
    # This adapter owns its explicit entry point after all override functions.
    tree.body = [n for n in tree.body if not (isinstance(n, _ast.If)
        and _ast.dump(n.test) == _ast.dump(_ast.parse("__name__ == '__main__'", mode='eval').body))]
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
_base_recipes = recipes


def recipes():
    provider = _reference_provider()
    extra = [ROOT/'scripts/build_linear_capital_source.py', *[Path(p) for p in provider.recipes()]]
    return {**_base_recipes(), **{str(p.resolve()): reference(p)['sha256'] for p in extra}}


def expected_results(proof):
    """Reuse retained independent postings; no fictitious second runner search."""
    universes = [read(proof['universe_'+side]) for side in ('A', 'B')]
    validation = read(proof['reference_validation'])
    require(validation.get('kind') == 'posted_universe_plan_aggregation_crosscheck'
        and validation.get('passed') is True and validation.get('require_group_feasible') is True
        and validation.get('plan_count') == 2
        and [r['id'] for r in validation['plans']] == ['winner', 'runner'],
        'The complete independent winner and single runner financial aggregates are required')
    winner = validation['plans'][0]
    require(winner['plan'] == proof['winner_plan'] and winner['passed'] is True
        and not winner['errors'] and not winner['differences'], 'Winner financial aggregation is incomplete')
    results = []
    for side, universe in zip(('A', 'B'), universes):
        require(winner[side]['feasible'] is True and winner[side]['objective_pence'] == proof['winner_objective_pence'],
            'Winner financial postings differ from the global optimum')
        results.append({**universe, **winner[side], 'plan': proof['winner_plan']})
    return tuple(results)


if __name__ == '__main__':
    raise SystemExit(main())
