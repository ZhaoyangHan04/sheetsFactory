"""Predeclared production primitives only; never import or run a ledger here."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

from .spec import SCALE, load_spec, require

ROOT = Path(__file__).resolve().parents[4]
CONFIG = ROOT / 'config/entity_group_catalog_v1.json'
PROFILE_IDS = tuple(f'G{i:02d}' for i in range(1, 11))
PROVENANCE = {
    'kind': 'hypothetical_entity_group_extension',
    'raw_ancestor_hashes_for_provenance_only': {
        'NYU': 'df8f9e91cc53afe2bdb33cf39b8f2719206ac03b6a5031f1858f82235ea944c9',
        'Ofgem': '2f02bfdf2c4c85449129add05038fb1cbc10ad4ea716e9571a7dba0ea3642ce8',
    },
    'new_company_is_an_original_source_company': False,
    'unchanged_original_company_forecasts_claimed': False,
    'all_forecasts_and_financing_policies_are_public_hypothetical_primitives': True,
}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_catalog(path=CONFIG):
    value = json.loads(Path(path).read_text())
    require(set(value) == {'version', 'kind', 'months', 'entities', 'scenarios', 'start_month',
            'tax_carry_months', 'interest_carry_months', 'profiles'}
            and type(value['version']) is int and value['version'] == 1
            and value['kind'] == 'predeclared_hypothetical_entity_group_primitives'
            and value['months'] == 120 and value['entities'] == 24 and value['scenarios'] == 3
            and value['start_month'] == '2024-04-01'
            and type(value['tax_carry_months']) is int and value['tax_carry_months'] == 3
            and type(value['interest_carry_months']) is int and value['interest_carry_months'] == 3,
            'The complete prospective catalog dimensions and FIFO windows are fixed')
    require(isinstance(value['profiles'], list) and all(isinstance(p, dict) for p in value['profiles'])
            and [p.get('id') for p in value['profiles']] == list(PROFILE_IDS),
            'Declare all ten ordered profiles before observing outcomes')
    for p in value['profiles']:
        require(set(p) == {'id', 'phase_order', 'treasury_owner', 'stress_start', 'money_percent',
            'shared_bank_gbp_pence', 'bank_order', 'bridge_first', 'tax_rate_percent', 'fx_shift'},
            'Unknown profile fields')
        require(isinstance(p['phase_order'], list) and len(p['phase_order']) == 6
                and all(type(x) is int for x in p['phase_order'])
                and sorted(p['phase_order']) == list(range(6)), 'Each operating phase permutation is complete')
        require(isinstance(p['treasury_owner'], list) and len(p['treasury_owner']) == 6
                and all(type(x) is int and x in (0, 1) for x in p['treasury_owner'])
                and p['treasury_owner'].count(0) == p['treasury_owner'].count(1) == 3,
                'Each treasury finances three real operating entities')
        for key, lo, hi in (('stress_start', 4, 20), ('money_percent', 80, 130),
                           ('shared_bank_gbp_pence', 20000, 60000), ('tax_rate_percent', 15, 35), ('fx_shift', 0, 12)):
            require(type(p[key]) is int and lo <= p[key] <= hi, 'Out-of-bound prospective profile primitive: ' + key)
        require(p['bank_order'] in ('interleave', 'reverse', 'rotate') and type(p['bridge_first']) is bool,
                'A profile must declare its funding priority before execution')
    return value


def _months(start, count):
    d = date.fromisoformat(start)
    return [date((d.year * 12 + d.month - 1 + i) // 12,
                 (d.year * 12 + d.month - 1 + i) % 12 + 1, 1).isoformat() for i in range(count)]


def build_spec(profile_id, catalog=None):
    catalog = load_catalog() if catalog is None else catalog
    require(profile_id in PROFILE_IDS, 'Unknown predeclared profile')
    p = next(p for p in catalog['profiles'] if p['id'] == profile_id)
    profile_index = PROFILE_IDS.index(profile_id)
    months = _months(catalog['start_month'], 120)
    def series(value): return dict.fromkeys(months, value)
    def money(value): return (value * p['money_percent'] + 50) // 100
    entities, projects, bank_terms, loans, terms = [], [], [], [], []
    fixed_plan, stress_by_entity = {}, {}
    bridge_ids, direct_ids = [], []
    currencies = ('GBP', 'USD', 'EUR')
    for group, currency in enumerate(currencies):
        offset = group * 8
        for within in range(8):
            identity, project_id = f'E{offset + within + 1:02d}', f'P{offset + within + 1:02d}'
            treasury = within < 2
            entities.append({'id': identity, 'currency': currency,
                'opening_cash_minor': money(350000 if treasury else 2000), 'opening_restricted_minor': 0,
                'opening_trap': False, 'opening_cure_count': 0, 'minimum_cash_minor': money(2000),
                'reserve_target_minor': money(10000), 'additional_commitment_minor': 0 if treasury else money(80000),
                'tax_rate_p12': p['tax_rate_percent'] * SCALE // 100,
                'interest_limit_p12': 3 * SCALE // 10, 'tax_carry_months': 3, 'interest_carry_months': 3,
                'covenant_threshold_p12': 5 * SCALE // 4, 'facility_id': 'BANK'})
            phase = 0 if treasury else p['phase_order'][within - 2]
            stress = p['stress_start'] + 2 * phase
            stress_by_entity[identity] = (stress, stress + 5)
            sale_index = 110 + ((within + 2 * group + profile_index) % 10)
            revenue, opex = {}, {}
            for i, month in enumerate(months):
                operating = 0 < i <= sale_index
                stressed = stress <= i < stress + 6
                revenue[month] = money(1000 if stressed else 12000 + 100 * group) if operating else 0
                opex[month] = money(8000 if stressed else 5000) if operating else 0
            projects.append({'id': project_id, 'entity_id': identity, 'currency': currency,
                'commission_month': months[0], 'sale_month': months[sale_index],
                'cost_minor': money(100000), 'depreciation_months': 96,
                'revenue_minor': revenue, 'opex_minor': opex, 'sale_minor': money(150000)})
            fixed_plan[project_id] = int(not treasury)
            for event_index, rate, advance in ((0, 6 * SCALE // 1000, 4 * SCALE // 5),
                                              (24, 8 * SCALE // 1000, 3 * SCALE // 4)):
                bank_terms.append({'entity_id': identity, 'facility_id': 'BANK', 'currency': currency,
                    'effective_month': months[event_index], 'maturity_month': months[-1],
                    'local_limit_minor': money(120000), 'monthly_rate_p12': rate,
                    'advance_rate_p12': advance})
        # Six direct treasury-to-operating contracts plus two genuine liquidity
        # bridges between entities with non-overlapping stress windows.
        ranked = sorted(range(6), key=lambda i: p['phase_order'][i])
        pairs = [(p['treasury_owner'][i], i + 2, False) for i in range(6)]
        pairs += [(ranked[0] + 2, ranked[3] + 2, True), (ranked[1] + 2, ranked[4] + 2, True)]
        for index, (lender, borrower, bridge) in enumerate(pairs):
            loan_id = f'L{group * 8 + index + 1:02d}'
            lender_id, borrower_id = f'E{offset + lender + 1:02d}', f'E{offset + borrower + 1:02d}'
            borrower_project = projects[offset + borrower]
            loans.append({'id': loan_id, 'lender_id': lender_id, 'borrower_id': borrower_id, 'currency': currency})
            if bridge: bridge_ids.append(loan_id)
            else: direct_ids.append(loan_id)
            active_index = stress_by_entity[borrower_id][0] if bridge else 0
            schedule = [(0, 0 if bridge else money(120000), 4 * SCALE // 1000 if bridge else 5 * SCALE // 1000)]
            if bridge:
                schedule.append((active_index, money(30000), 4 * SCALE // 1000))
            else:
                schedule.append((24 + group, money(130000), 6 * SCALE // 1000))
            for event_index, limit, rate in schedule:
                terms.append({'loan_id': loan_id, 'lender_id': lender_id, 'borrower_id': borrower_id,
                    'currency': currency, 'effective_month': months[event_index],
                    'maturity_month': borrower_project['sale_month'], 'limit_minor': limit, 'monthly_rate_p12': rate})
    operating = [f'E{group * 8 + within + 1:02d}' for within in range(2, 8) for group in range(3)]
    if p['bank_order'] == 'reverse': operating.reverse()
    elif p['bank_order'] == 'rotate':
        rotation = (profile_index * 3) % len(operating)
        operating = operating[rotation:] + operating[:rotation]
    treasury_ids = [e['id'] for e in entities if fixed_plan['P' + e['id'][1:]] == 0]
    bank_priority = operating + treasury_ids
    loan_priority = (bridge_ids + direct_ids) if p['bridge_first'] else (direct_ids + bridge_ids)
    scenarios = []
    opening_fx = {'GBP': SCALE, 'USD': 8 * SCALE // 10, 'EUR': 9 * SCALE // 10}
    for number, (rev_percent, opex_percent, sale_percent) in enumerate(((100, 100, 100), (90, 110, 90), (105, 95, 105)), 1):
        fx = {'GBP': series(SCALE), 'USD': {}, 'EUR': {}}
        for i, month in enumerate(months):
            usd = (80, 112 if number == 2 else 92 if number == 1 else 72, 96 if number == 2 else 84 if number == 1 else 88)
            eur = (90, 117 if number == 2 else 102 if number == 1 else 108, 99 if number == 2 else 95 if number == 1 else 94)
            fx['USD'][month] = usd[0 if i < 7 + p['fx_shift'] else 1 if i < 30 + p['fx_shift'] else 2] * SCALE // 100
            fx['EUR'][month] = eur[0 if i < 9 + p['fx_shift'] else 1 if i < 34 + p['fx_shift'] else 2] * SCALE // 100
        scenarios.append({'id': f'S{number:02d}', 'revenue_factor_p12': series(rev_percent * SCALE // 100),
            'opex_factor_p12': series(opex_percent * SCALE // 100), 'sale_factor_p12': series(sale_percent * SCALE // 100),
            'nav_factor_p12': {m: (100 if i < 36 else 95) * SCALE // 100 for i, m in enumerate(months)},
            'haircut_p12': {m: (15 if 6 + p['fx_shift'] <= i < 20 + p['fx_shift'] else 5) * SCALE // 100 for i, m in enumerate(months)},
            'rate_factor_p12': {m: (110 if number == 2 and 12 <= i < 60 else 100) * SCALE // 100 for i, m in enumerate(months)},
            'fx_gbp_p12': fx})
    public = {'schema_version': 1, 'dimension_mode': 'production', 'months': months,
        'reporting_currency': 'GBP', 'fiscal_year_end_month': 3, 'opening_fx_gbp_p12': opening_fx,
        'shared_bank_limit_gbp_pence': p['shared_bank_gbp_pence'], 'entities': entities, 'projects': projects,
        'fixed_plan': fixed_plan, 'plan_policy': 'provided_fixed_not_an_optimisation_task',
        'bank_terms': bank_terms, 'intercompany_loans': loans, 'intercompany_terms': terms,
        'bank_priority': bank_priority, 'loan_priority': loan_priority, 'scenarios': scenarios}
    return load_spec(public)


def structural_evidence(public):
    """Static declared structure; no assertion of actual financial activation."""
    public = load_spec(public)
    loans = public['intercompany_loans']
    graph = {'loans': loans, 'bank_priority': public['bank_priority'], 'loan_priority': public['loan_priority'],
        'bank_effective_keys': [(t['entity_id'], t['effective_month'], t['monthly_rate_p12'], t['advance_rate_p12']) for t in public['bank_terms']],
        'loan_effective_keys': [(t['loan_id'], t['effective_month'], t['limit_minor'], t['monthly_rate_p12']) for t in public['intercompany_terms']]}
    return {'entity_count': len(public['entities']), 'month_count': len(public['months']),
        'scenario_count': len(public['scenarios']), 'project_count': len(public['projects']),
        'provided_investments': sum(public['fixed_plan'].values()),
        'treasury_entities': sum(v == 0 for v in public['fixed_plan'].values()),
        'bilateral_loan_count': len(loans), 'bank_term_events': len(public['bank_terms']),
        'loan_term_events': len(public['intercompany_terms']), 'structure_sha256': canonical_sha(graph),
        'spec_sha256': canonical_sha(public), 'actual_mechanism_activation_certified': False,
        'full_ledger_executed': False, 'financial_source_certified': False}


MECHANISMS = (
    'effective_date_rollover', 'intercompany_draw', 'intercompany_interest',
    'intercompany_principal_repayment', 'bank_margin', 'shared_facility_contention',
    'covenant_breach', 'opening_trap_applied', 'two_pass_cure', 'restricted_cash_released',
    'interest_vintage_used', 'tax_vintage_used', 'vintage_expired', 'currency_translation',
)


def reachability_evidence(public, result):
    """Inspect a bound forward report, without claiming independent financial audit.

    Positive amounts and complete dated paths establish prototype reachability.
    This is deliberately separate from the independent workbook implementation.
    """
    public = load_spec(public)
    months = public['months']
    entity_map = {e['id']: e for e in public['entities']}
    loan_map = {r['id']: r for r in public['intercompany_loans']}
    require(result['kind'] == 'entity_group_integer_forward_ledger'
            and result['spec_sha256'] == canonical_sha(public)
            and result['fixed_plan'] == public['fixed_plan']
            and result['dimension_mode'] == public['dimension_mode']
            and result['entity_count'] == len(entity_map)
            and result['month_count'] == len(months)
            and result['scenario_count'] == len(public['scenarios'])
            and result['optimisation_performed'] is False
            and result['workbook_engine_calls'] == result['model_calls'] == 0,
            'The actual forward report must bind the complete supplied fixed-plan specification')
    require(set(result['scenarios']) == {s['id'] for s in public['scenarios']}, 'Missing scenario paths')
    scenarios = {}
    for scenario_id, scenario in result['scenarios'].items():
        require(set(scenario['entities']) == set(entity_map)
                and set(scenario['projects']) == set(public['fixed_plan'])
                and set(scenario['intercompany']) == set(loan_map), 'Incomplete legal-entity/project/loan graph')
        observations = {k: {'count': 0, 'witnesses': []} for k in MECHANISMS}
        participating_entities = set()
        def observed(name, pointer, month, **details):
            record = observations[name]
            record['count'] += 1
            if len(record['witnesses']) < 2:
                record['witnesses'].append({'pointer': pointer, 'month': month, **details})
        for entity_id, data in scenario['entities'].items():
            require(data['currency'] == entity_map[entity_id]['currency']
                    and [r['month'] for r in data['monthly']] == months, 'Incomplete entity monthly path')
            for index, row in enumerate(data['monthly']):
                month = row['month']
                pointer = f'/scenarios/{scenario_id}/entities/{entity_id}/monthly/{index}'
                require(bool(row['residuals']) and all(type(v) is int and v == 0 for v in row['residuals'].values())
                        and row['translation_residual_gbp'] == 0, 'Nonzero legal or translation residual')
                for field, carry in (('interest_live_vintages', 'interest_carry_months'), ('tax_live_vintages', 'tax_carry_months')):
                    queue = row[field]
                    require(len(queue) <= entity_map[entity_id][carry] + 1
                            and all(v['balance_minor'] > 0 and 0 <= index - months.index(v['vintage_month'])
                                    <= entity_map[entity_id][carry] for v in queue), 'FIFO window is not bounded and live')
                if any(row[k] for k in ('revenue', 'capex', 'sale', 'ic_draw_lent', 'ic_draw_received',
                                        'ic_interest_income', 'ic_interest_expense', 'bank_draw')):
                    participating_entities.add(entity_id)
                if index and row['bank_term_effective_month'] == month and row['bank_open'] > 0:
                    observed('effective_date_rollover', pointer, month, entity_id=entity_id,
                             opening_bank_minor=row['bank_open'], posted_rate_p12=row['bank_monthly_rate_p12'])
                if row['bank_local_margin'] + row['bank_shared_margin'] > 0:
                    observed('bank_margin', pointer, month, entity_id=entity_id,
                             local_minor=row['bank_local_margin'], shared_minor=row['bank_shared_margin'])
                if row['covenant_passed'] is False:
                    require(row['debt_service'] > 0 and row['ebitda'] * SCALE
                            < row['debt_service'] * entity_map[entity_id]['covenant_threshold_p12'],
                            'A breach witness must actually fail its public threshold')
                    observed('covenant_breach', pointer, month, entity_id=entity_id,
                             ebitda_minor=row['ebitda'], debt_service_minor=row['debt_service'])
                if row['trap_open'] is True and row['restricted_close'] > 0:
                    observed('opening_trap_applied', pointer, month, entity_id=entity_id,
                             restricted_minor=row['restricted_close'], locked_minor=row['reserve_locked'])
                if row['trap_open'] is True and row['trap_next'] is False:
                    require(row['covenant_passed'] is True and row['cure_run_after_test'] >= 2,
                            'Cure needs two actual consecutive passes')
                    observed('two_pass_cure', pointer, month, entity_id=entity_id,
                             passes=row['cure_run_after_test'])
                for mechanism, field in (('restricted_cash_released', 'reserve_released'),
                        ('interest_vintage_used', 'interest_old_used'), ('tax_vintage_used', 'tax_loss_used')):
                    if row[field] > 0:
                        observed(mechanism, pointer, month, entity_id=entity_id, amount_minor=row[field])
                expired = row['interest_expired'] + row['tax_loss_expired']
                if expired:
                    require(all(v['amount_minor'] > 0 and v['vintage_month'] < month for v in expired),
                            'Expiry evidence must contain positive old balances')
                    observed('vintage_expired', pointer, month, entity_id=entity_id,
                             interest=row['interest_expired'], tax=row['tax_loss_expired'])
                if row['economic_FX_this_month_gbp']:
                    require(row['fx_open_p12'] != row['fx_close_p12'], 'FX witness requires an actual rate change')
                    observed('currency_translation', pointer, month, entity_id=entity_id,
                             previous_fx_p12=row['fx_open_p12'], current_fx_p12=row['fx_close_p12'],
                             amount_gbp_pence=row['economic_FX_this_month_gbp'])
        for project_rows in scenario['projects'].values():
            require([r['month'] for r in project_rows] == months, 'Incomplete project path')
        for loan_id, loan_rows in scenario['intercompany'].items():
            require([r['month'] for r in loan_rows] == months, 'Incomplete intercompany path')
            for index, row in enumerate(loan_rows):
                loan = loan_map[loan_id]
                require(all(row[k] == loan[k] for k in ('currency', 'lender_id', 'borrower_id'))
                        and row['principal_bridge_residual'] == 0, 'Wrong bilateral identity or principal bridge')
                pointer = f'/scenarios/{scenario_id}/intercompany/{loan_id}/{index}'
                if index and row['term_effective_month'] == row['month'] and row['opening_principal'] > 0:
                    observed('effective_date_rollover', pointer, row['month'], loan_id=loan_id,
                             opening_principal_minor=row['opening_principal'])
                for mechanism, field in (('intercompany_draw', 'draw'), ('intercompany_interest', 'interest'),
                        ('intercompany_principal_repayment', 'mandatory_repayment')):
                    if row[field] > 0:
                        observed(mechanism, pointer, row['month'], loan_id=loan_id,
                                 lender_id=loan['lender_id'], borrower_id=loan['borrower_id'],
                                 currency=loan['currency'], amount_minor=row[field])
        # Headroom is an intermediate ordered-funding state. Inspect its retained
        # actual branch evidence rather than inferring marginal effects from D.
        for index, event in enumerate(scenario['mechanism_activation']['shared_facility_contention']['witnesses']):
            require(event['month'] in months and event['entity_id'] in entity_map
                    and event['desired_local_minor'] > event['allowed_local_minor'] >= 0
                    and event['allowed_local_minor'] == event['GBP_headroom_pence'] * SCALE // event['fx_p12'],
                    'Contention must have a real positive denied draw at the public GBP conversion')
            row = scenario['entities'][event['entity_id']]['monthly'][months.index(event['month'])]
            require(row['bank_draw'] == event['allowed_local_minor'] and row['fx_close_p12'] == event['fx_p12'],
                    'Contention branch does not match the actual bank posting')
            observed('shared_facility_contention', f'/scenarios/{scenario_id}/mechanism_activation/shared_facility_contention/witnesses/{index}',
                     event['month'], **{k: v for k, v in event.items() if k != 'month'})
        require([r['month'] for r in scenario['group_monthly']] == months, 'Incomplete group close path')
        for row in scenario['group_monthly'] + scenario['fiscal_years']:
            residuals = [v for k, v in row.items() if 'residual' in k]
            require(bool(residuals) and all(type(v) is int and v == 0 for v in residuals), 'Nonzero group or fiscal bridge')
        actual_gap = next(({'month': r['month'], 'entity_id': e, 'amount_minor': r['funding_gap']}
                          for month in months for e in entity_map
                          for r in [scenario['entities'][e]['monthly'][months.index(month)]] if r['funding_gap'] > 0), None)
        require(scenario['feasible'] is (actual_gap is None) and scenario['first_funding_gap'] == actual_gap,
                'Feasibility must match the actual dated funding gaps')
        for evidence in observations.values():
            evidence['active'] = evidence['count'] > 0
            evidence['count_scope'] = 'positive_economic_observations_in_checked_evidence'
        observations['shared_facility_contention']['retained_branch_witnesses_are_truncated'] = (
            scenario['mechanism_activation']['shared_facility_contention']['witnesses_truncated'])
        scenarios[scenario_id] = {'feasible': scenario['feasible'], 'first_funding_gap': actual_gap,
            'entity_months_checked': len(entity_map) * len(months),
            'all_entities_economically_active': participating_entities == set(entity_map),
            'mechanisms': observations, 'all_mechanisms_with_dated_economic_evidence': all(v['active'] for v in observations.values())}
    feasible = all(s['feasible'] for s in scenarios.values())
    require(result['feasible'] is feasible, 'Top-level feasibility differs from scenario paths')
    passed = feasible and all(s['all_entities_economically_active'] and s['all_mechanisms_with_dated_economic_evidence']
                             for s in scenarios.values())
    return {'kind': 'entity_group_forward_report_reachability', 'version': 1,
        'method': 'bound_integer_ledger_paths_and_dated_economic_observations', 'passed': passed,
        'spec_sha256': canonical_sha(public), 'result_sha256': canonical_sha(result), 'scenarios': scenarios,
        'feasible': feasible, 'independent_financial_audit': False, 'production_workbook_created': False,
        'workbook_engine_calls': 0, 'model_calls': 0, 'qualified': False, 'quality_or_difficulty_certified': False}
