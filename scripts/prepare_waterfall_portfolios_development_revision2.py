#!/usr/bin/env python3
"""Use revised Boolean-fact task admission with the unchanged native v6 attempt."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN_ENTRY = ROOT/'scripts/prepare_waterfall_portfolios_development.py'
FROZEN_SHA = 'fe6ef34ad73178a162e943dedffb6c64f935cc52d6218004c794ddcb3146935c'
TASK_VALIDATOR_SHA = '9b5d29d4607f8758dcd0c31d9c23ee49e16f91655715273d14dd74d360f25eb9'


def revised_ast():
    raw = FROZEN_ENTRY.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA:
        raise ValueError('The original waterfall first-attempt v6 entry changed')
    if len(TASK_VALIDATOR_SHA) != 64:
        raise ValueError('The reviewed task8 revision2 feature must be frozen before import')
    replacements = {
        'scripts/validate_waterfall_portfolios_tasks.py': 'scripts/validate_waterfall_portfolios_tasks_revision2.py',
        '8632ba14d4c2612df0e619424959a4a091290b43caafefe145aba8dccede6bfc': TASK_VALIDATOR_SHA,
        'prepared_waterfall_portfolios_task_engineering': 'prepared_waterfall_portfolios_task_engineering_revision2',
        'complete_waterfall_portfolios_task_engineering': 'complete_waterfall_portfolios_task_engineering_revision2',
    }
    counts = {key: 0 for key in replacements}
    counts['main'] = 0

    class Adapt(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in replacements:
                counts[node.value] += 1
                node.value = replacements[node.value]
            return node

        def visit_If(self, node):
            if ast.unparse(node.test) == "__name__ == '__main__'":
                counts['main'] += 1
                return None
            return self.generic_visit(node)

    tree = Adapt().visit(ast.parse(raw))
    expected = {key: 1 for key in counts}
    expected['scripts/validate_waterfall_portfolios_tasks.py'] = 2
    if counts != expected:
        raise ValueError('The exact task8 admission revision2 seams changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_revision = {'__name__': '_isolated_waterfall_development_revision2', '__file__': __file__}
exec(compile(revised_ast(), __file__, 'exec'), _revision)
_previous_recipes = _revision['recipes']


def recipes():
    return {**_previous_recipes(), str(FROZEN_ENTRY): _revision['ref'](FROZEN_ENTRY)}


_revision['recipes'] = recipes
_revision['_N']['recipes'] = recipes
for _name, _value in _revision.items():
    if not _name.startswith('__'):
        globals().setdefault(_name, _value)

if __name__ == '__main__':
    raise SystemExit(main())
