#!/usr/bin/env python3
"""Freeze the retained C02 precision-v2 material for one native v6 attempt."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'scripts/prepare_operating_reports_financial_cohort_development.py'
BASE_SHA = 'f092107c18f2bcf4c361261f8748572f89df8ff1e6f040caa5b2cdcfada6b313'
TASK = ROOT / 'scripts/validate_operating_reports_financial_cohort_tasks_revision2.py'
TASK_SHA = '51c2c4467bd9252e94bad4f98c6d5eecf7dab0721a25e719d45d0f3ba155a031'
TERMINAL = ROOT / 'outputs/research/financial_cohort_C02_task5_precision_revision2_20261101T024000Z/prepared/terminal.json'
TERMINAL_SHA = 'ab826d1009bdd73a0de3618e8fd36a559bf0ece2eadcf5c3c9dd3d3269a557b5'
SOURCE_SHA = '06711c55f3577aa01e0f4b1bae3366f668db2d1c473ed8fd3e78fab41723c2f8'
POLICY_SHA = '76c8c2e0895f68fce6a1288fcac7817bf33a3cb2123995f8ac25e0ea9d43b210'
INPUT_SHA = '05e610a7733c3b6e50e204c111b610fb7057e9014f8b2009019f537673c3ef97'
GOAL_SHA = 'c65cdd9c19042813d398f9173b42d85c688b87739da6f916ccb5aaa03a8ef097'
BRIEF_SHA = '5d9f8922d806cb3d25ef8bca7355b5061dda372d39da8cc453168ca96894f077'
CASE_ID = 'FM-C02'
KIND = 'prequality_operating_reports_financial_cohort_single_development_v6_revision2'


def _checked_engineering(value):
    require, read, checked = (_N[key] for key in ('require', 'read', 'checked'))
    terminal = _N['ref'](checked(value) if isinstance(value, dict) else value)
    require(terminal['sha256'] == TERMINAL_SHA, 'Select only the retained C02 precision-v2 task terminal')
    require(_N['ref'](SCHEMA)['sha256'] == SCHEMA_SHA, 'The frozen cohort schema changed')
    actual = _N['validation_driver']().validate_completed(terminal)
    require(actual['kind'] == 'complete_operating_reports_financial_cohort_FM_task_engineering_revision2'
            and type(actual['version']) is int and actual['version'] == 2 and actual['passed'] is True
            and actual['failure'] is None
            and actual['actual_LO_calls_started'] == actual['actual_LO_calls_completed'] == 5
            and actual['source_LO_calls_reused'] == 3
            and actual['qualified'] is actual['normal_all12_QA_passed'] is actual['difficulty_claimed'] is False
            and set(actual['records']['modes']) == {'financial_modeling'},
            'Require genuine precision-v2 five-call FM engineering without inherited qualification')
    frozen = read(actual['preparation'])
    public = read(frozen['specification'])
    schema.validate_spec(public)
    require(schema.candidate(public['seed'])['candidate_id'] == CASE_ID
            and public['dimension_mode'] == 'production'
            and frozen['kind'] == 'prepared_operating_reports_financial_cohort_FM_task_engineering_revision2'
            and type(frozen['version']) is int and frozen['version'] == 2 and frozen['case_id'] == CASE_ID
            and frozen['mode_order'] == ['financial_modeling']
            and frozen['independent_business_field_count'] == 93510 and frozen['formula_count'] == 88676
            and frozen['financial_target_count'] == frozen['forecast_mask_count'] == 62322
            and frozen['report_NA_count'] == 4834,
            'Only the predeclared C02 raw case and complete FM scope may enter this attempt')
    require(frozen['raw_inventory']['sha256'] == RAW_INVENTORY_SHA,
            'The original jointly frozen all-nine raw inventory changed')
    inventory = raw.validate_all(frozen['raw_inventory'])
    require(set(inventory['specifications']) == set(CASE_IDS)
            and inventory['specifications'][CASE_ID] == public,
            'Keep all nine frozen raw cases and the exact original C02 public specification')
    source = read(actual['source_manifest'])
    sf = read(frozen['source_preparation'])
    candidate = read(frozen['candidate_preparation'])
    require(actual['source_manifest'] == frozen['source_manifest']
            and actual['source_manifest']['sha256'] == SOURCE_SHA
            and source['kind'] == 'independently_checked_operating_reports_financial_cohort_source_precision_revision2'
            and type(source['version']) is int and source['version'] == 2 and source['passed'] is True
            and source['failure'] is None
            and source['actual_LO_calls_started'] == source['actual_LO_calls_completed'] == 3
            and source['reused_native_calls'] == 1
            and source['new_native_calls_started'] == source['new_native_calls_completed'] == 2
            and source['cold_start_is_unseeded'] is True
            and source['new_financial_forwards'] == 0
            and source['old_failure_reclassified'] is source['E05_E06_grader_changed'] is False
            and source['policy_sha256'] == frozen['source_precision_policy_sha256']
            == sf['source_only_policy_sha256'] == POLICY_SHA
            and frozen['source_independent_expected'] == sf['expected']
            and frozen['actual_primary_expected_from_genuine_goal_ref'] == frozen['genuine_goal']
            and source['preparation'] == frozen['source_preparation']
            and source['source'] == frozen['genuine_goal'] == source['actual_calls'][-1]['output']
            and source['specification'] == sf['specification'] == frozen['specification']
            and checked(candidate['specification']).read_bytes() == checked(frozen['specification']).read_bytes()
            and sf['case_id'] == candidate['candidate_id'] == CASE_ID
            and sf['raw_inventory'] == frozen['raw_inventory']
            and sf['candidate_manifest'] == frozen['candidate_preparation']
            and candidate['kind'] == 'prepared_unverified_operating_reports_financial_cohort_fm_emission'
            and candidate['version'] == 1,
            'Bind the genuine precision source, unchanged independent evidence and original C02 emission')
    mode = actual['records']['modes']['financial_modeling']
    brief = mode['instruction']
    original = checked(brief).read_bytes()
    require(mode['goal'] == frozen['genuine_goal'] and mode['complete_D_count'] == 62322
            and mode['input']['sha256'] == INPUT_SHA and mode['goal']['sha256'] == GOAL_SHA
            and mode['controls'] == {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
            and mode['instruction'] == frozen['instruction_bytes']['financial_modeling']
            and brief['bytes'] == len(original) == 403 and brief['sha256'] == BRIEF_SHA
            and checked(candidate['views']['financial_modeling']['instruction']).read_bytes() == original,
            'Keep exact C02 input, healthy goal, original brief and complete five controls')
    checked(mode['input'])
    checked(mode['goal'])
    return actual, {'specification': frozen['specification'],
                    'views': {'financial_modeling': {'instruction': brief}},
                    'instructions': {'financial_modeling': brief}}


def adapted_ast():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('The frozen single-FM v6 entry changed')
    counts = {'provider_path': 0, 'provider_sha': 0, 'engineering_hook': 0, 'prepared_kind': 0, 'main': 0}

    class Adapt(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name == '_checked_engineering':
                counts['engineering_hook'] += 1
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            if ast.unparse(node.test) == "__name__ == '__main__'":
                counts['main'] += 1
                return None
            return self.generic_visit(node)

        def visit_Constant(self, node):
            if node.value == 'scripts/validate_operating_reports_financial_cohort_tasks.py':
                counts['provider_path'] += 1
                node.value = 'scripts/validate_operating_reports_financial_cohort_tasks_revision2.py'
            elif node.value == '8188d2add6e96660f8b7401114d4d6af6bc46ffd6f01647971daa50eefd77b91':
                counts['provider_sha'] += 1
                node.value = TASK_SHA
            elif node.value == 'prequality_operating_reports_financial_cohort_single_development_v6':
                counts['prepared_kind'] += 1
                node.value = KIND
            return node

    tree = Adapt().visit(ast.parse(BASE.read_bytes()))
    if counts != {'provider_path': 2, 'provider_sha': 1, 'engineering_hook': 1, 'prepared_kind': 1, 'main': 1}:
        raise ValueError('The exact C02 single-attempt adaptation sites changed: ' + str(counts))
    return ast.fix_missing_locations(tree), counts


_P = {'__name__': '_isolated_C02_precision_v2_first_development', '__file__': __file__,
      '_checked_engineering': _checked_engineering}
_tree, ADAPTATION_COUNTS = adapted_ast()
exec(compile(_tree, __file__, 'exec'), _P)
_P['__doc__'] = __doc__
_N = _P['_N']
SCHEMA, SCHEMA_SHA, schema, raw, CASE_IDS, RAW_INVENTORY_SHA = (
    _P[key] for key in ('SCHEMA', 'SCHEMA_SHA', 'schema', 'raw', 'CASE_IDS', 'RAW_INVENTORY_SHA'))
_original_recipes = _P['recipes']


def recipes():
    result = _original_recipes()
    for path in (BASE, Path(__file__)):
        result[str(path.resolve())] = _N['ref'](path)
    return result


_P.update(_checked_engineering=_checked_engineering, recipes=recipes)
_N.update(_checked_engineering=_checked_engineering, recipes=recipes)
for _name, _value in _N.items():
    if not _name.startswith('__'):
        globals().setdefault(_name, _value)
main = _P['main']


if __name__ == '__main__':
    raise SystemExit(main())
