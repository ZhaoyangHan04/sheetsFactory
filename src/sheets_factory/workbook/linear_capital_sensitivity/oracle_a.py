"""A: integer rowwise transformation and exact dot-product plan audit."""
from copy import deepcopy

from . import contract as rules


def build_cases(public, base_model, contract):
    rules.validate_contract(public, contract, base_model, 'A')
    cases = []
    for definition in contract['cases']:
        case_public = deepcopy(public)
        limits = case_public['shared_limits']
        limits['initial_sponsor_equity_pence'] = (limits['initial_sponsor_equity_pence'] * definition['budget_percent']) // 100
        for resource in case_public['resource_ids']:
            for scenario in case_public['scenario_ids']:
                for year in case_public['years']:
                    old = limits['resource_capacity_units'][resource][scenario][str(year)]
                    limits['resource_capacity_units'][resource][scenario][str(year)] = old * definition['capacity_percent'] // 100
        model = deepcopy(base_model)
        model['specification_sha256'] = rules.spec.canonical_sha256(case_public)
        for row in model['rows']:
            if row['family'] == 'initial_sponsor_equity':
                row['limit'] = row['limit'] * definition['budget_percent'] // 100
            elif row['family'] == 'resource':
                row['limit'] = row['limit'] * definition['capacity_percent'] // 100
        rules.validate_base(case_public, model, 'A')
        cases.append({'case': dict(definition), 'model': model})
    return {'kind': 'rowwise_integer_independent_sensitivity_cases_A', 'version': 1,
            'contract_sha256': rules.canonical_sha256(contract), 'cases': cases,
            'reference_admission': False, 'checked_optimal': False, 'optimizer_calls': 0}


def check_plans(public, base_model, contract, plans):
    # Reconstruct from the prospective inputs; a caller cannot supply an easier
    # mutable bundle or a solver's rounded feasibility flag.
    bundle = build_cases(public, base_model, contract)
    ids = [entry['case']['id'] for entry in bundle['cases']]
    rules.require(ids == [c['id'] for c in rules.CASES] and isinstance(plans, dict) and set(plans) == set(ids),
                  'Every fixed case needs a separate complete plan; no case omission or extra case')
    results = []
    for entry in bundle['cases']:
        identity = entry['case']['id']; model = entry['model']; plan = plans[identity]
        rules.model_a.validate_model(model)
        rules.require(isinstance(plan, dict) and set(plan) == set(model['project_ids'])
                      and all(type(v) is int and v in (0, 1) for v in plan.values()),
                      'Each plan requires all 360 exact integer binary choices')
        choice = [plan[pid] for pid in model['project_ids']]
        rows = []
        for row in model['rows']:
            lhs = sum(a * x for a, x in zip(row['coefficients'], choice, strict=True))
            rows.append({'id': row['id'], 'lhs': lhs, 'limit': row['limit'],
                         'slack': row['limit'] - lhs, 'passed': lhs <= row['limit']})
        results.append({'case_id': identity, 'objective_pence': sum(a * x for a, x in zip(model['objective_pence'], choice, strict=True)),
                        'selected_project_count': sum(choice), 'rows': rows,
                        'feasible': all(r['passed'] for r in rows), 'checked_optimal': False})
    return results
