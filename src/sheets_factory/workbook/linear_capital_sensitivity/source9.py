"""Pure source join over all nine genuine references and one shared A/B ledger.

No financial forward, optimiser, LibreOffice or model call is made here.
Materialised workbooks remain unverified until a separate real source lifecycle.
"""
from pathlib import Path
from copy import deepcopy
import json

from . import contract, reference

require = contract.require


def join_reference(value):
    """Fail closed before loading any winner unless the whole nine cold-admits."""
    actual = reference.validate_completed(value)
    preparation = reference.read(actual['preparation'])
    inventory = reference.read(preparation['all_nine_models'])
    prospective = reference.read(preparation['prospective'])
    original = reference.read(prospective['financial_terminal'])
    public = contract.spec.load_spec(reference.read(original['specification']))
    shared = {'public': public, 'A': reference.read(original['universe_A']),
        'B': reference.read(original['universe_B']),
        'universe_A': original['universe_A'], 'universe_B': original['universe_B']}
    require(actual['case_order'] == inventory['case_order'] == [c['id'] for c in contract.CASES]
            and len(actual['cases']) == len(inventory['cases']) == 9,
            'Every fixed case must have a genuine best and runner; no filtering')
    results = {side: {'projects': shared[side]['projects'], 'cases': {}} for side in ('A', 'B')}
    plans = {}; models = {}; projections = {}
    for record, row in zip(actual['cases'], inventory['cases'], strict=True):
        case = reference.read(record); identity = row['case']['id']
        require(case['case'] == row['case'] and case['passed'] is True and case['gap_pence'] >= 1,
                'A substituted or incomplete sensitivity case cannot become a source')
        projection = reference._financial_projection({'shared': shared}, row,
            case['winner_plan'], case['runner_plan'])
        require(projection == reference.read(case['financial_projection']),
                'Cold independent selected-plan financial projection differs')
        comparison = projection['comparison']; winner = comparison['plans'][0]
        require(comparison['passed'] is True and comparison['plan_count'] == 2
                and winner['id'] == 'winner' and winner['plan'] == case['winner_plan']
                and winner['passed'] is True and not winner['errors'] and not winner['differences'],
                'Complete independent winner postings are required')
        plans[identity] = contract.spec.validate_plan(public, case['winner_plan'])
        models[identity] = {side: reference.read(row['models'][side]) for side in ('A', 'B')}
        for side in ('A', 'B'):
            posting = winner[side]
            require(posting['feasible'] is True and posting['objective_pence'] == case['winner_objective_pence']
                    and len(posting['constraints']) == 941 and all(r['passed'] for r in posting['constraints']),
                    'The full winner financial report or exact objective is incomplete')
            results[side]['cases'][identity] = posting
        projections[identity] = case['financial_projection']
    reference._refs({'preparation': actual['preparation'], 'models': inventory['cases'],
        'finance': {k: original[k] for k in ('specification', 'universe_A', 'universe_B', 'model_A', 'model_B')}})
    vector_groups = {}
    for case in actual['case_order']:
        digest = contract.canonical_sha256(plans[case]); vector_groups.setdefault(digest, []).append(case)
    return {'kind': 'joined_all_nine_independent_financial_source_inputs', 'version': 1,
        'public': public, 'declaration': reference.read(prospective['contract']),
        'case_order': actual['case_order'], 'case_models': models, 'plans': plans, 'results': results,
        'references': {'nine_case_reference': reference.reference(value) if isinstance(value, (str, Path)) else value,
            'preparation': actual['preparation'], 'all_nine_models': preparation['all_nine_models'],
            'financial_terminal': prospective['financial_terminal'], 'universe_A': original['universe_A'],
            'universe_B': original['universe_B'], 'projections': projections},
        'shared_project_ledger_copies': 1, 'financial_forwards': 0, 'LO_calls': 0,
        'distinct_winner_vectors': len(vector_groups), 'winner_vector_groups': list(vector_groups.values()),
        'different_winners_required': False, 'nine_independent_hardness_claimed': False,
        'model_calls': 0, 'source_engine_verified': False, 'qualified': False}


def at(value, path):
    for key in path:
        require(isinstance(value, (dict, list)) and
                (type(key) is str if isinstance(value, dict) else type(key) is int),
                'An independent financial locator has an invalid path')
        require(key in value if isinstance(value, dict) else 0 <= key < len(value), 'Financial locator is out of bounds')
        value = value[key]
    return value


def resolve_expected(binding, result):
    value = at(result, binding['expected_path'])
    if 'vintage_field' in binding:
        require(isinstance(value, list), 'A complete sparse tax-vintage journal is required')
        for row in value:
            require(set(row) == {'year', 'fiscal_year', 'origin_year', *contract.spec.VINTAGE_FIELDS}
                    and type(row['year']) is int and type(row['origin_year']) is int
                    and 1 <= row['origin_year'] <= row['year']
                    and all(type(row[f]) is int and row[f] >= 0 for f in contract.spec.VINTAGE_FIELDS),
                    'A malformed vintage cannot be silently treated as zero')
        index = {(r['year'], r['origin_year']): r for r in value}
        require(len(index) == len(value) and 1 <= binding['origin_year'] <= binding['vintage_year'],
                'Duplicate or invalid tax-vintage identity')
        require(binding['vintage_field'] in contract.spec.VINTAGE_FIELDS, 'Unknown tax-vintage field')
        value = index.get((binding['vintage_year'], binding['origin_year']), {}).get(binding['vintage_field'], 0)
    if 'constraint_id' in binding:
        require(isinstance(value, list), 'A complete case constraint journal is required')
        index = {r['id']: r for r in value}
        require(len(index) == len(value) and binding['constraint_id'] in index
                and binding['constraint_field'] in ('lhs', 'limit', 'slack', 'passed'),
                'A case constraint locator is missing, duplicated or unknown')
        value = index[binding['constraint_id']][binding['constraint_field']]
    if binding['kind'] == 'flag':
        require(type(value) is bool or type(value) is int and value in (0, 1), 'An explicit financial flag is required')
        return int(value)
    require(type(value) is int and abs(value) < contract.spec.EXACT_LIMIT
            and binding['kind'] in ('money_pence', 'integer', 'nullable_money_pence'),
            'Every financial target requires an exact independently posted integer')
    return value


def expected_values(joined, bindings):
    require(bindings['kind'] == 'unverified_shared_ledger_nine_case_excel_bindings'
            and bindings['specification_sha256'] == contract.spec.canonical_sha256(joined['public'])
            and bindings['case_order'] == joined['case_order'], 'The complete source binding identity differs')
    values = {}; formulas = {}
    def add(row, value):
        point = row['sheet'], row['cell']; require(point not in values, 'Duplicate physical expected binding')
        values[point] = value
    for row in bindings['input_bindings']: add(row, at(joined['public'], row['path']))
    for row in bindings['literal_bindings']: add(row, row['value'])
    expected_decisions = [(case, pid) for case in joined['case_order'] for pid in joined['public']['project_ids']]
    require([(r['case_id'], r['project_id']) for r in bindings['decision_bindings']] == expected_decisions,
            'All nine complete decision vectors are required')
    for row in bindings['decision_bindings']:
        value = joined['plans'][row['case_id']][row['project_id']]
        require(type(value) is int and value in (0, 1) and row['value'] == value, 'A source choice differs from its genuine winner')
        add(row, value)
    financial = {(r['sheet'], r['cell']): r for r in bindings['financial_bindings']}
    require(len(financial) == len(bindings['financial_bindings']), 'Duplicate financial locator')
    for point, row in financial.items():
        av = resolve_expected(row, joined['results']['A']); bv = resolve_expected(row, joined['results']['B'])
        require(type(av) is type(bv) and av == bv, 'Independent A/B financial expectations disagree')
        if row['formula'] is None: require(values.get(point) == av, 'Financial literal zero differs from its independent journal')
    for row in bindings['arithmetic_bindings']:
        point = row['sheet'], row['cell']; require(point not in formulas, 'Duplicate formula identity')
        formulas[point] = row['formula']
        if point in financial:
            require(row == financial[point], 'Financial formula and arithmetic coverage differ')
            add(row, resolve_expected(row, joined['results']['A']))
        else:
            derivation = row['expected_derivation']; case = derivation['case_id']
            require(derivation['project_ids'] == joined['public']['project_ids'] and case in joined['case_order']
                    and derivation['kind'] in ('complete_binary_decisions', 'selected_project_count'),
                    'Unsupported input-only derivation')
            add(row, 1 if derivation['kind'] == 'complete_binary_decisions' else sum(joined['plans'][case].values()))
    require(len(formulas) == bindings['formula_count'], 'Every physical formula needs complete coverage')
    return {'values': values, 'formulas': formulas, 'financial_binding_count': len(financial),
            'actual_engine_validation_claimed': False}


def recipes():
    from . import excel9
    paths = [Path(__file__), Path(excel9.__file__), Path(excel9.base.__file__), excel9.base.UPSTREAM,
             Path(excel9.task_views.__file__), excel9.task_views.UPSTREAM]
    return {**reference.recipes(), **{str(p): reference.reference(p) for p in paths}}


def _expected_rows(values):
    return [{'sheet': sheet, 'cell': cell, 'value': value} for (sheet, cell), value in sorted(values.items())]


def build_candidate(reference_terminal, output):
    """Materialise only after genuine whole-nine proof; never claims engine PASS."""
    from . import excel9
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(reference.ROOT/'outputs') and not output.exists(),
            'Use a fresh research candidate directory')
    joined = join_reference(reference_terminal); before = recipes(); (output/'private').mkdir(parents=True)
    goal = output/'private/goal_uncalculated.xlsx'
    bindings = excel9.emit_workbook(goal, joined['public'], joined['case_models'], joined['plans'])
    expected = expected_values(joined, bindings)
    bound = reference.write(output/'private/bindings.json', bindings)
    expected_ref = reference.write(output/'private/independent_expected.json', {
        'kind': 'complete_shared_ledger_nine_case_independent_expected_values', 'version': 1,
        'values': _expected_rows(expected['values']), 'formula_count': len(expected['formulas']),
        'financial_binding_count': expected['financial_binding_count'],
        'all_values_checked_against_independent_A_B': True, 'actual_engine_validated': False})
    modes = {}
    for mode in excel9.INSTRUCTIONS:
        edits = excel9.materialize_view(goal, output/mode, bindings, joined['public'], mode=mode)
        modes[mode] = {'input': reference.reference(output/mode/'public/input.xlsx'),
            'instruction': reference.reference(output/mode/'public/instruction.md'),
            'private_edits': reference.write(output/'private'/(mode+'_edits.json'), edits)}
    require(recipes() == before, 'Source implementation changed during pure emission')
    return reference.write(output/'preparation.json', {'kind': 'unverified_shared_ledger_nine_case_source_candidate',
        'version': 1, 'genuine_reference': joined['references']['nine_case_reference'],
        'reference_lineage': joined['references'], 'recipe': before, 'goal': reference.reference(goal),
        'bindings': bound, 'independent_expected': expected_ref, 'views': modes,
        'case_order': joined['case_order'], 'shared_project_ledger_copies': 1,
        'decision_count': len(bindings['decision_bindings']), 'case_cash_rows': bindings['case_cash_rows'],
        'case_constraint_rows': bindings['case_constraint_rows'],
        'distinct_winner_vectors': joined['distinct_winner_vectors'],
        'winner_vector_groups': joined['winner_vector_groups'], 'different_winners_required': False,
        'financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0, 'optimizer_calls': 0,
        'source_engine_verified': False, 'first_native_source_input_is_uncached': True,
        'actual_task_stability_full_D_controls_verified': False, 'qualified': False})


def validate_candidate(value):
    record = reference.reference(value) if isinstance(value, (str, Path)) else value
    candidate = reference.read(record)
    require(candidate['kind'] == 'unverified_shared_ledger_nine_case_source_candidate'
            and type(candidate['version']) is int and candidate['version'] == 1
            and candidate['recipe'] == recipes() and candidate['qualified'] is False
            and candidate['source_engine_verified'] is False
            and all(type(candidate[k]) is int and candidate[k] == 0 for k in ('financial_forwards', 'LO_calls', 'model_calls', 'optimizer_calls')),
            'A pure candidate cannot inherit source-engine or difficulty admission')
    reference._refs(candidate); joined = join_reference(candidate['genuine_reference'])
    require(candidate['reference_lineage'] == joined['references'] and candidate['case_order'] == joined['case_order'],
            'Whole-nine source ancestry differs')
    bindings = reference.read(candidate['bindings']); actual = expected_values(joined, bindings)
    expected = reference.read(candidate['independent_expected'])
    require(expected['values'] == _expected_rows(actual['values'])
            and expected['formula_count'] == len(actual['formulas']), 'The complete independent value scope changed')
    return candidate
