"""Independent integer sensitivity matrices and selected-plan checks.

Only the retained B matrix and public integer limits are consumed.  This module
neither recomputes project financials nor invokes an optimiser.  The alternatives
are explicit hypothetical reuse of P02, not independent new financial sources.
"""
from copy import deepcopy
import hashlib
import json

from . import contract
from ..linear_capital_scaled import model_b, spec

KIND = 'independent_reused_budget_capacity_sensitivity_B'
VERSION = 1


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _base(public, matrix, declaration):
    contract.validate_contract(public, declaration, model=matrix, implementation='B')
    for case in declaration['cases']:
        _require(type(case['id']) is str and
                 all(type(case[k]) is int for k in ('budget_percent', 'capacity_percent')),
                 'Case percentages must be declared integers, not Boolean or floating values')
    return spec.load_spec(public)


def build_cases(public, base_model_B, declaration):
    """Construct all nine complete models, changing only the two declared limits."""
    original = _base(public, base_model_B, declaration)
    alternatives = []
    for case in declaration['cases']:
        revised = deepcopy(original)
        limits = revised['shared_limits']
        limits['initial_sponsor_equity_pence'] = (
            original['shared_limits']['initial_sponsor_equity_pence'] * case['budget_percent'] // 100)
        for resource, scenarios in limits['resource_capacity_units'].items():
            for scenario, years in scenarios.items():
                for year in years:
                    years[year] = (original['shared_limits']['resource_capacity_units']
                                   [resource][scenario][year] * case['capacity_percent'] // 100)
        revised = spec.load_spec(revised)
        matrix = deepcopy(base_model_B)
        matrix['specification_sha256'] = _sha(revised)
        for row in matrix['rows']:
            if row['id'] == 'initial_sponsor_equity':
                row['limit'] = limits['initial_sponsor_equity_pence']
            elif row['family'] == 'resource':
                prefix, resource, scenario, year = row['id'].split(':')
                _require(prefix == 'resource', 'A physical-resource identity differs')
                row['limit'] = limits['resource_capacity_units'][resource][scenario][year]
        # Structural integer validation is shared with the retained B schema;
        # scaling and selected-plan arithmetic above/below are implemented here.
        matrix = model_b.validate_model(matrix)
        alternatives.append({'case': deepcopy(case), 'model': matrix})
    return {'kind': KIND, 'version': VERSION, 'contract_sha256': _sha(declaration),
            'cases': alternatives, 'reference_admission': False,
            'checked_optimal': False, 'optimizer_calls': 0}


def check_plans(public, base_model_B, declaration, plans):
    """Audit every integer row/objective for nine complete supplied plans.

    Passing a selected plan establishes feasibility only.  It cannot establish
    global optimality, uniqueness, or a reference admission.
    """
    bundle = build_cases(public, base_model_B, declaration)
    order = declaration['case_order']
    _require(isinstance(plans, dict) and len(plans) == len(order) and set(plans) == set(order),
             'Supply the complete fixed nine-case plan inventory, without extra cases')
    checks = []
    for alternative in bundle['cases']:
        case_id = alternative['case']['id']
        matrix = alternative['model']
        identities = matrix['project_ids']
        plan = plans[case_id]
        _require(isinstance(plan, dict) and len(plan) == len(identities) and set(plan) == set(identities),
                 'Every supplied plan must contain every original project exactly once')
        _require(all(type(plan[identity]) is int and plan[identity] in (0, 1)
                     for identity in identities),
                 'Each project choice must be an integer zero or one')
        selected = [i for i, identity in enumerate(identities) if plan[identity] == 1]
        objective = sum(matrix['objective_pence'][i] for i in selected)
        rows = []
        for constraint in matrix['rows']:
            lhs = sum(constraint['coefficients'][i] for i in selected)
            limit = constraint['limit']
            rows.append({'id': constraint['id'], 'lhs': lhs, 'limit': limit,
                         'slack': limit-lhs, 'passed': lhs <= limit})
        checks.append({'case_id': case_id, 'objective_pence': objective,
                       'selected_project_count': len(selected), 'rows': rows,
                       'feasible': all(row['passed'] for row in rows),
                       'checked_optimal': False})
    return checks
