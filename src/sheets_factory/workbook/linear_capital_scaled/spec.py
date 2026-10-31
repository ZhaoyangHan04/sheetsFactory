"""Version-two N360 contract over the unchanged version-one financial rules.

Only source identity, the complete project universe and relationship counts
change. The original module and its globals remain untouched. A native bundle
can retain the original source as a sibling named ``frozen_spec.py``.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM_SHA256 = '9905ca53b00001834bd86f740f5d9dfa23b7155b98ae036fdbf48cc68293b594'
SPEC_KIND = 'hypothetical_ringfenced_linear_capital_portfolio_scaled'
SPEC_VERSION = 2


def upstream_path():
    local = _Path(__file__).with_name('frozen_spec.py')
    return local if local.is_file() else _Path(__file__).resolve().parents[1]/'linear_capital_portfolio/spec.py'


def adapted_ast():
    path = upstream_path(); raw = path.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The unchanged financial specification source differs')
    tree = _ast.parse(raw, filename=str(path)); counts = {}
    replacements = {
        "s['version'] == 1": "s['version'] == 2",
        "s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio'":
            "s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio_scaled'",
        'len(groups) == 40': 'len(groups) == 60',
        'len(edges) == 80': 'len(edges) == 120',
    }
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self, node):
            if any(isinstance(target, _ast.Name) and target.id == 'PROJECT_IDS' for target in node.targets):
                expected = _ast.parse("tuple(f'P{i:03d}' for i in range(1, 241))", mode='eval').body
                if _ast.dump(node.value) != _ast.dump(expected):
                    raise ValueError('The original complete project identities changed')
                node.value = _ast.parse("tuple(f'P{i:03d}' for i in range(1, 361))", mode='eval').body
                counts['PROJECT_IDS'] = counts.get('PROJECT_IDS', 0)+1
            return self.generic_visit(node)

        def visit_Compare(self, node):
            key = _ast.unparse(node)
            if key in replacements:
                counts[key] = counts.get(key, 0)+1
                return _ast.parse(replacements[key], mode='eval').body
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    if counts != {'PROJECT_IDS': 1, **{key: 1 for key in replacements}}:
        raise ValueError('The exact version-two dimension substitutions changed')
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())

DIMENSIONS = {'projects': 360, 'scenarios': 3, 'years': 20, 'resources': 6,
    'regions': 6, 'sectors': 8, 'exclusivity_groups': 60, 'prerequisites': 120}
PRODUCTION_ROW_COUNT = 941
PRODUCTION_COUNTS = {'initial_sponsor_equity': 1, 'annual_new_lp': 60,
    'annual_debt_close': 60, 'resource': 360, 'region_exposure': 120,
    'sector_exposure': 160, 'exclusivity': 60, 'prerequisite': 120}


def expected_constraint_count(specification):
    """Complete row census for either the fixed N360 source or a toy fixture."""
    public = load_spec(specification)
    scenarios, years = len(public['scenario_ids']), len(public['years'])
    return (1 + 2*scenarios*years + len(public['resource_ids'])*scenarios*years
        + (len(public['region_ids'])+len(public['sector_ids']))*years
        + len(public['exclusivity_groups'])+len(public['prerequisites']))
