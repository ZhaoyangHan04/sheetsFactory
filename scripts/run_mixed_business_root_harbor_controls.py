#!/usr/bin/env python3
"""Run both exact final-root commands with complete mixed-family observation."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
BASE = ROOT/'scripts/run_exact_root_harbor_controls.py'
BASE_SHA = 'ffa5be29410260900ef4a1e2d1ddc7e4632712940d0e0e81326146d54790569f'


def adapted_ast():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('The frozen exact-root control command implementation changed')
    tree = ast.parse(BASE.read_text()); counts = Counter()
    class Adapt(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module == 'sheets_factory.evaluation.resource_harbor':
                node.module = 'sheets_factory.evaluation.mixed_business_resources'; counts['inspector'] += 1
            elif node.module == 'sheets_factory.evaluation.resource_observer':
                node.module = 'sheets_factory.evaluation.mixed_business_resource_observer'; counts['observer'] += 1
            return node
    tree = Adapt().visit(tree)
    if counts != Counter(inspector=1,observer=1):
        raise ValueError('The two exact-root mixed-family imports changed')
    return ast.fix_missing_locations(tree)


namespace = {'__name__': '_mixed_exact_root_business_controls', '__file__': __file__}
exec(compile(adapted_ast(), __file__, 'exec'), namespace)
if __name__ == '__main__': namespace['main']()
