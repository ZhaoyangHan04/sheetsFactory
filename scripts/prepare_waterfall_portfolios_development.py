#!/usr/bin/env python3
"""Freeze two independent waterfall first attempts under the existing v6 clock."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANCESTOR = ROOT/'scripts/prepare_operating_reports_200_development.py'
ANCESTOR_SHA = 'd6cd3b7aebedfb7aebe632217585951838eb28e0fe38d03fab4277fe47f0e6f3'
TASK_VALIDATOR = ROOT/'scripts/validate_waterfall_portfolios_tasks.py'
TASK_VALIDATOR_SHA = '8632ba14d4c2612df0e619424959a4a091290b43caafefe145aba8dccede6bfc'
RAW_SHA = '2dc3d88fab5afc26d036b8f566e30d3a02fd9a09f2756e29cebd8f2f09dcacb4'
SPECIFICATION_SHA = 'e87b89196e48523f1bec937fa09afeb609308081f4b06ef29c4d39f2cfb96666'


def adapted_ast():
    data = ANCESTOR.read_bytes()
    if hashlib.sha256(data).hexdigest() != ANCESTOR_SHA:
        raise ValueError('The existing first-attempt v6 lifecycle changed')
    if len(TASK_VALIDATOR_SHA) != 64:
        raise ValueError('The reviewed waterfall task8 feature must be frozen before import')
    replacements = {
        'scripts/validate_operating_reports_200_tasks.py': 'scripts/validate_waterfall_portfolios_tasks.py',
        'b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5': TASK_VALIDATOR_SHA,
        '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40': SPECIFICATION_SHA,
    }
    counts = {k: 0 for k in replacements}
    counts.update(replace_engineering=0, remove_main=0)

    class Adapt(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name == '_checked_engineering':
                counts['replace_engineering'] += 1
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            if ast.unparse(node.test) == "__name__ == '__main__'":
                counts['remove_main'] += 1
                return None
            return self.generic_visit(node)

        def visit_Constant(self, node):
            if type(node.value) is str:
                if node.value in replacements:
                    counts[node.value] += 1
                    node.value = replacements[node.value]
                else:
                    node.value = (node.value
                        .replace('fixed_operating_reports_200', 'waterfall_portfolios_24')
                        .replace('fixed_hypothetical_operating_reports_200', 'hypothetical_waterfall_portfolios_24')
                        .replace('operating-reports-200-', 'waterfall-portfolios-24-')
                        .replace('fixed200', 'waterfall24'))
            return node

    tree = Adapt().visit(ast.parse(data))
    if any(value != 1 for value in counts.values()):
        raise ValueError('The exact v6 family adaptation sites changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_N = {'__name__': '_isolated_waterfall_first_development_v6', '__file__': __file__}
exec(compile(adapted_ast(), __file__, 'exec'), _N)
_first_recipes = _N['recipes']


def _checked_engineering(value):
    driver = _N['validation_driver']()
    actual = driver.validate_completed(value)
    require = _N['require']
    read, checked = _N['read'], _N['checked']
    require(actual['kind'] == 'complete_waterfall_portfolios_task_engineering'
        and actual['version'] == 1 and actual['passed'] is True
        and actual['actual_LO_calls_started'] == actual['actual_LO_calls_completed'] == 8
        and actual['qualified'] is False and actual['normal_all12_QA_passed'] is False,
        'Require the complete genuine eight-call waterfall task engineering')
    prepared = read(actual['preparation'])
    candidate = read(prepared['candidate_preparation'])
    raw = read(prepared['specification'])
    require(prepared['kind'] == 'prepared_waterfall_portfolios_task_engineering'
        and prepared['version'] == 1 and prepared['source_manifest'] == actual['source_manifest']
        and prepared['financial_target_count'] == 189600 and prepared['forecast_mask_count'] == 170640
        and prepared['DBG_formula_root_count'] == 1296 and set(actual['records']['modes']) == set(_N['MODES'])
        and prepared['specification']['sha256'] == RAW_SHA and _N['canonical'](raw) == SPECIFICATION_SHA
        and candidate['kind'] == 'pure_waterfall_portfolios_native_emission' and candidate['version'] == 1
        and candidate['qualified'] is False and candidate['specification_sha256'] == SPECIFICATION_SHA
        and read(candidate['specification']) == raw
        and candidate['sheet_count'] == 100 and candidate['formula_count'] == 189600
        and candidate['FM_mask_count'] == 170640 and candidate['DBG_root_count'] == 1296,
        'Bind the original 24 funds, 20 years, three scenarios, complete mask and complete fixed faults')
    require(len(raw['funds']) == 24 and raw['years'] == list(range(2025, 2045))
        and raw['scenario_ids'] == ['BASE', 'DOWN', 'UP'] and raw['dimension_mode'] == 'production',
        'Do not substitute a toy or a partial waterfall cohort')
    for mode in _N['MODES']:
        material = actual['records']['modes'][mode]
        require(material['goal'] == prepared['genuine_goal']
            and material['controls'] == {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
            and checked(material['instruction']).read_bytes() == checked(candidate['views'][mode]['instruction']).read_bytes()
            and type(material['complete_D_count']) is int and material['complete_D_count'] > 0
            and (mode != 'financial_modeling' or material['complete_D_count'] == 170640),
            'Keep genuine full-grid controls and exactly the original public instructions')
    # The emitter copy and the original raw are separate real artifacts. The
    # source identity uses the original raw, while both remain verified above.
    return actual, {**candidate, 'specification': prepared['specification'],
        'instructions': {mode: candidate['views'][mode]['instruction'] for mode in _N['MODES']}}


def recipes():
    return {**_first_recipes(), str(ANCESTOR): _N['ref'](ANCESTOR)}


_N.update(_checked_engineering=_checked_engineering, recipes=recipes)
for _name, _value in _N.items():
    if not _name.startswith('__'):
        globals().setdefault(_name, _value)

if __name__ == '__main__':
    raise SystemExit(main())
