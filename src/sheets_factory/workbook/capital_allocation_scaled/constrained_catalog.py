"""Predeclared constrained capital primitives; no ledger, optimiser or workbook.

The six economic cohorts improve operating returns while dated credit shocks
and a smaller cumulative LP commitment create prospective interactions. These
are hypotheses, not assertions of feasibility, optimality or model difficulty.
"""
from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import random

from . import catalog as original
from .spec import SCALE, YEARS, RAW_ANCESTORS, canonical_sha, load_spec

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CATALOG = ROOT / 'config/capital_allocation_constrained_catalog_v1.json'
DEVELOPMENT_ID = '30-D02'
CONFIRMATION_ORDER = tuple(f'30-H{i:02d}' for i in range(1, 11))
PROFILE_ORDER = (DEVELOPMENT_ID, *CONFIRMATION_ORDER)
COHORTS = original.COHORTS
UPSTREAM_SHA256 = 'f0bcd3d476323e98a5d0b23dce9f88aae100ae45c545498d4eb4a12fa6b8acac'
UPSTREAM_CONFIG_SHA256 = '459ec8d185681e1441249a87abaa481db86aa9c7bb0e64603449dbd1de909071'
CRITERIA_IDS = ('public_primitive_completeness', 'positive_reachable_nonempty_portfolio',
    'real_funding_violation', 'dated_financing_activation', 'dated_FIFO_activation',
    'cross_scenario_ordering_reversal', 'candidate_economic_scale')
PROFILE_FIELDS = {'id', 'seed', 'project_count', 'cohort_counts', 'opening_cash_pence',
    'minimum_cash_pence', 'lp_commitment_pence', 'facility_limit_pence', 'advance_rate_bp',
    'tax_rate_bp', 'discount_rate_bp', 'loss_carry_years', 'calendar_shift_years',
    'early_stress_start', 'late_stress_start', 'stress_adjustment_bp'}
COHORT_FIELDS = {'id', 'count', 'cost_range_pence', 'commission_years_by_ordinal',
    'hold_years_range', 'depreciation_years_range', 'revenue_bp_of_cost_range',
    'opex_bp_of_cost_range', 'sale_bp_of_cost_range', 'revenue_growth_bp_range'}
CATALOG_FIELDS = {'kind', 'version', 'currency', 'monetary_unit', 'rate_denominator', 'years',
    'profile_order', 'confirmation_profile_order', 'prospective_first_strong_profile',
    'raw_ancestors', 'provenance', 'selection_uses_model_outcomes', 'cohorts', 'paired_capex_cohorts',
    'early_loss_recovery_delays_by_ordinal', 'scenario_stress_policy', 'engineering_criteria',
    'engineering_criteria_status', 'optimal_project_count_is_acceptance_criterion',
    'unique_optimum_or_financial_correctness_claimed', 'profiles'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _bounded(value, low, high, name):
    _require(type(value) is int and low <= value <= high, name + ' must be a bounded integer')


def assert_upstream():
    for path, expected in ((Path(original.__file__), UPSTREAM_SHA256),
                           (original.DEFAULT_CATALOG, UPSTREAM_CONFIG_SHA256)):
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                 'The reused primitive/money/public-contract implementation changed')


def _unique_json(pairs):
    value = {}
    for key, child in pairs:
        _require(key not in value, 'Duplicate prospective catalog field: ' + key)
        value[key] = child
    return value


def load_catalog(value=DEFAULT_CATALOG):
    value = json.loads(Path(value).read_text(), object_pairs_hook=_unique_json) if isinstance(value, (str, Path)) else deepcopy(value)
    _require(isinstance(value, dict) and set(value) == CATALOG_FIELDS,
             'Only the complete predeclared raw-primitive catalog is accepted')
    _require(value['kind'] == 'predeclared_constrained_scaled_capital_allocation_catalog'
        and type(value['version']) is int and value['version'] == 1 and value['currency'] == 'GBP'
        and value['monetary_unit'] == 'pence' and type(value['rate_denominator']) is int
        and value['rate_denominator'] == SCALE and value['years'] == [2024, 2043],
        'Keep the original GBP-pence, P12, twenty-FY financial schema')
    _require(value['profile_order'] == list(PROFILE_ORDER)
        and value['confirmation_profile_order'] == list(CONFIRMATION_ORDER)
        and value['prospective_first_strong_profile'] == DEVELOPMENT_ID
        and value['raw_ancestors'] == RAW_ANCESTORS
        and type(value['provenance']) is str and 'hypothetical' in value['provenance']
        and value['selection_uses_model_outcomes'] is False
        and value['engineering_criteria_status'] == 'predeclared_not_evaluated'
        and value['optimal_project_count_is_acceptance_criterion'] is False
        and value['unique_optimum_or_financial_correctness_claimed'] is False,
        'Prospective identities, ancestry and honest unknown-state claims must remain explicit')
    cohorts = value['cohorts']
    _require(isinstance(cohorts, list) and [c.get('id') for c in cohorts] == list(COHORTS), 'All six economic cohorts are required')
    for c in cohorts:
        _require(set(c) == COHORT_FIELDS and type(c['count']) is int and c['count'] == 5,
                 'Each complete economic cohort has exactly five public projects')
        for field, low, high in [('cost_range_pence', 1, 700000000), ('hold_years_range', 4, 19),
                ('depreciation_years_range', 1, 20), ('revenue_bp_of_cost_range', 0, 10000),
                ('opex_bp_of_cost_range', 0, 10000), ('sale_bp_of_cost_range', 0, 14000),
                ('revenue_growth_bp_range', 0, 200)]:
            pair = c[field]
            _require(isinstance(pair, list) and len(pair) == 2, 'A declared primitive range is missing')
            for n in pair: _bounded(n, low, high, field)
            _require(pair[0] <= pair[1], 'A declared primitive range is reversed')
        _require(len(c['commission_years_by_ordinal']) == 5, 'All cohort commissioning slots are required')
        for year in c['commission_years_by_ordinal']: _bounded(year, 2024, 2032, 'commission year')
    _require(value['paired_capex_cohorts'] == ['contracted_long_life', 'merchant_cycle']
        and value['early_loss_recovery_delays_by_ordinal'] == [2, 2, 2, 2, 5],
        'The equal-capex competing families and long recovery FIFO case must remain predeclared')
    stress = value['scenario_stress_policy']
    _require(set(stress) == {'early_duration_years', 'late_duration_years', 'early', 'late'}
        and type(stress['early_duration_years']) is int and stress['early_duration_years'] == 3
        and type(stress['late_duration_years']) is int and stress['late_duration_years'] == 4,
        'The scenario stress windows must remain explicit')
    for phase in ('early', 'late'):
        _require(set(stress[phase]) == {'revenue_bp','opex_bp','nav_bp','sale_bp','bank_rate_bp','haircut_bp'},
                 'Every scenario stress factor is required')
        for key, n in stress[phase].items(): _bounded(n, 0, 10000 if key in ('bank_rate_bp','haircut_bp') else 30000, key)
    _require([c.get('id') for c in value['engineering_criteria']] == list(CRITERIA_IDS)
        and all(set(c) == {'id', 'threshold'} and type(c['threshold']) is str and bool(c['threshold'])
                for c in value['engineering_criteria']), 'The complete independent engineering criteria are required')
    profiles = value['profiles']
    _require([p.get('id') for p in profiles] == list(PROFILE_ORDER), 'No development or confirmation profile may be omitted or reordered')
    for p in profiles:
        _require(set(p) == PROFILE_FIELDS and type(p['project_count']) is int and p['project_count'] == 30
            and p['cohort_counts'] == [5] * 6 and all(type(n) is int for n in p['cohort_counts']),
            'Exactly all thirty projects and six complete cohorts are required')
        _bounded(p['seed'], 0, 2**31 - 1, 'seed')
        for name in ('opening_cash_pence','minimum_cash_pence','lp_commitment_pence','facility_limit_pence'):
            _bounded(p[name], 0, 10**11, name)
        _require(p['opening_cash_pence'] >= p['minimum_cash_pence'], 'Opening cash cannot be below the minimum')
        for name in ('advance_rate_bp','tax_rate_bp'): _bounded(p[name], 1, 10000, name)
        _bounded(p['discount_rate_bp'], 1, 3000, 'discount rate')
        _bounded(p['loss_carry_years'], 1, 20, 'loss carry')
        _bounded(p['calendar_shift_years'], 0, 1, 'calendar shift')
        _bounded(p['early_stress_start'], 2025, 2028, 'early stress')
        _bounded(p['late_stress_start'], 2033, 2036, 'late stress')
        _bounded(p['stress_adjustment_bp'], -400, 400, 'stress adjustment')
    _require(len({p['seed'] for p in profiles}) == len(profiles), 'Distinct predeclared seeds are required')
    assert_upstream()
    return value


def _profile(config, identity):
    _require(identity in PROFILE_ORDER, 'Unknown constrained development/confirmation identity')
    return next(p for p in config['profiles'] if p['id'] == identity)


def _project(identifier, policy, ordinal, profile, rng, paired_costs, config):
    cohort = policy['id']
    cost = (paired_costs[ordinal] if cohort in config['paired_capex_cohorts']
            else rng.randint(policy['cost_range_pence'][0] // 1000000, policy['cost_range_pence'][1] // 1000000) * 1000000)
    commission = policy['commission_years_by_ordinal'][ordinal] + profile['calendar_shift_years']
    sale = min(2043, commission + rng.randint(*policy['hold_years_range']))
    life = rng.randint(*policy['depreciation_years_range'])
    rev, op, growth = (rng.randint(*policy[k]) for k in ('revenue_bp_of_cost_range','opex_bp_of_cost_range','revenue_growth_bp_range'))
    cycle = rng.randrange(4); revenues, expenses = {}, {}
    for year in YEARS:
        age = year - commission
        if not commission < year <= sale:
            revenues[str(year)] = expenses[str(year)] = 0; continue
        rb, ob = rev, op
        if cohort == 'early_loss_rebuild' and age <= config['early_loss_recovery_delays_by_ordinal'][ordinal]:
            rb = max(0, op - (800 if age == 1 else 400 if age == 2 else 200))
        elif cohort == 'merchant_cycle':
            rb = rev * (128, 76, 114, 86)[(year + cycle) % 4] // 100
            ob += (0, 150, 300, 100)[(year + cycle) % 4]
        elif cohort == 'short_refurbishment' and age == 2:
            ob += rng.randint(800, 1200)
        elif cohort == 'delayed_delivery' and age <= 2:
            rb, ob = (1000, 1600) if age == 1 else (2500, 1800)
        revenues[str(year)] = original._money(cost, rb, growth, age - 1)
        expenses[str(year)] = original._money(cost, ob, max(0, growth - 30), age - 1)
    return {'id': identifier, 'commission_year': commission, 'sale_year': sale,
        'acquisition_cost_pence': cost, 'depreciation_years': life,
        'annual_revenue_pence': revenues, 'annual_opex_pence': expenses,
        'sale_proceeds_pence': original._money(cost, rng.randint(*policy['sale_bp_of_cost_range']))}


def _scenarios(profile, config):
    rows = []
    names = ('revenue_factors_p12','opex_factors_p12','nav_factors_p12','sale_factors_p12','bank_rates_p12','haircuts_p12')
    stress = config['scenario_stress_policy']; adjust = profile['stress_adjustment_bp']
    for index in range(3):
        result = {'id': 'S' + str(index + 1).zfill(2), **{k: {} for k in names}}
        for i, year in enumerate(YEARS):
            cycle = (i + profile['seed'] % 5) % 5
            early = profile['early_stress_start'] <= year < profile['early_stress_start'] + stress['early_duration_years']
            late = profile['late_stress_start'] <= year < profile['late_stress_start'] + stress['late_duration_years']
            if index == 0:
                values = (10000 + (0,200,-150,100,-100)[cycle], 10000 + (0,150,50,200,100)[cycle],
                    10000 - 50 * cycle, 10000 - 70 * cycle, 600 + 35 * cycle, 1200 + 100 * cycle)
            elif index == 1 and early or index == 2 and late:
                v = stress['early' if index == 1 else 'late']
                values = (v['revenue_bp'] - adjust, v['opex_bp'] + adjust // 2, v['nav_bp'] - adjust,
                    v['sale_bp'] - adjust, v['bank_rate_bp'] + adjust // 10, v['haircut_bp'] + adjust)
            elif index == 1:
                values = (10900 - 70 * cycle, 10000 + 40 * cycle, 10200 - 60 * cycle,
                    10600 - 80 * cycle, 700 + 20 * cycle, 1400 + 100 * cycle)
            else:
                values = (11200 - 60 * cycle, 10000 + 70 * cycle, 10500 - 75 * cycle,
                    11000 - 90 * cycle, 720 + 25 * cycle, 1200 + 120 * cycle)
            for name, bp in zip(names, values): result[name][str(year)] = bp * (SCALE // 10000)
        rows.append(result)
    return rows


def _build(profile, config):
    rng = random.Random(profile['seed']); roles = [c for c in COHORTS for _ in range(5)]; rng.shuffle(roles)
    paired = [rng.randint(300, 500) * 1000000 for _ in range(5)]
    policies = {p['id']: p for p in config['cohorts']}; counts = dict.fromkeys(COHORTS, 0); projects, metadata = [], []
    with localcontext() as context:
        context.prec = 70
        for index, cohort in enumerate(roles):
            ordinal = counts[cohort]; counts[cohort] += 1; identifier = 'P' + str(index + 1).zfill(2)
            projects.append(_project(identifier, policies[cohort], ordinal, profile, rng, paired, config))
            metadata.append({'id': identifier, 'cohort': cohort, 'cohort_ordinal': ordinal,
                'paired_capex_ordinal': ordinal if cohort in config['paired_capex_cohorts'] else None})
        discount = 1 + Decimal(profile['discount_rate_bp']) / 10000
        public = {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
            **{k: profile[k] for k in ('opening_cash_pence','minimum_cash_pence','lp_commitment_pence','facility_limit_pence')},
            'advance_rate_p12': profile['advance_rate_bp'] * (SCALE // 10000),
            'tax_rate_p12': profile['tax_rate_bp'] * (SCALE // 10000), 'tax_loss_carry_years': profile['loss_carry_years'],
            'discount_factors_p12': {str(y): original._round(Decimal(SCALE) / discount**(i + 1)) for i, y in enumerate(YEARS)},
            'projects': projects, 'scenarios': _scenarios(profile, config),
            'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': dict(RAW_ANCESTORS)}}
    return load_spec(public), metadata


def build_spec(profile_id, catalog=DEFAULT_CATALOG):
    config = load_catalog(catalog)
    return _build(_profile(config, profile_id), config)[0]


def describe_profile(profile_id, catalog=DEFAULT_CATALOG):
    config = load_catalog(catalog); p = _profile(config, profile_id); public, metadata = _build(p, config)
    descriptions = {**original.COHORT_DESCRIPTIONS,
        'contracted_long_life': 'Higher-margin contracted operating cash with long asset lives and stated residual proceeds.',
        'early_loss_rebuild': 'Four projects have two initial loss years; the fifth has five explicitly forecast loss years before recovery, to test dated FIFO expiry.',
        'short_refurbishment': 'Four-to-six-year operating holds with a separately forecast second-year maintenance outlay.',
        'delayed_delivery': 'Two low-delivery operating years followed by higher forecast revenue; commissioning follows the earlier cash cohorts.'}
    return {'profile_id': profile_id, 'project_count': 30, 'prospective_role': 'first_development' if profile_id == DEVELOPMENT_ID else 'fresh_confirmation_candidate',
        'public_spec_sha256': canonical_sha(public), 'candidate_cohorts': metadata,
        'cohort_descriptions': descriptions, 'hypothetical_forecasts_and_policies': True,
        'raw_ancestry_is_provenance_only': True, 'raw_ancestors': dict(RAW_ANCESTORS), 'source_original_ancestors': 2,
        'shared_common_plan_across_scenarios': True, 'engineering_criteria_status': 'predeclared_not_evaluated',
        'financial_feasibility_or_uniqueness_claimed': False, 'model_difficulty_claimed': False, 'qualified': False, 'task_count': 0}


def public_contract(profile_id, catalog=DEFAULT_CATALOG):
    config = load_catalog(catalog); _profile(config, profile_id)
    contract = original.public_contract('30-D01')
    contract['profile_id'] = profile_id
    return contract


contract_markdown = original.contract_markdown


def fixed_diagnostic_plans(profile_id, catalog=DEFAULT_CATALOG):
    config = load_catalog(catalog); public, metadata = _build(_profile(config, profile_id), config)
    ids = [p['id'] for p in public['projects']]
    groups = {c: [p['id'] for p in metadata if p['cohort'] == c] for c in COHORTS}
    plans = []
    def add(name, selected):
        selected = set(selected); plans.append({'id': name, 'plan': {p: int(p in selected) for p in ids}})
    add('empty', []); add('all', ids)
    for cohort in COHORTS: add('cohort_' + cohort, groups[cohort])
    for identity in ids: add('singleton_' + identity, [identity])
    add('cash_then_growth', groups['contracted_long_life'] + groups['delayed_delivery'])
    add('collateral_then_growth', groups['collateral_carry'] + groups['delayed_delivery'])
    add('balanced_first_two_each_cohort', [p for c in COHORTS for p in groups[c][:2]])
    first = min(p['commission_year'] for p in public['projects'])
    first_wave = [p['id'] for p in public['projects'] if p['commission_year'] == first]
    add('first_commission_wave_only', first_wave); add('later_commission_waves_only', set(ids) - set(first_wave))
    add('tax_expiry_isolation', groups['early_loss_rebuild'][4:5])
    return plans


def engineering_inventory(profile_id, catalog=DEFAULT_CATALOG):
    config = load_catalog(catalog); public = build_spec(profile_id, config)
    return {'kind': 'predeclared_constrained_capital_fixed_plan_diagnostics', 'version': 1,
        'profile_id': profile_id, 'public_spec_sha256': canonical_sha(public), 'project_count': 30,
        'plans': fixed_diagnostic_plans(profile_id, config),
        'comparison_pairs': [['cohort_contracted_long_life','cohort_merchant_cycle'],
            ['cash_then_growth','collateral_then_growth'], ['empty','balanced_first_two_each_cohort']],
        'engineering_criteria': deepcopy(config['engineering_criteria']), 'engineering_criteria_status': 'predeclared_not_evaluated',
        'all_mechanisms_or_feasibility_guaranteed': False, 'plan_enumeration_or_ranking_performed': False,
        'source_financial_audit_or_global_optimum_proven': False, 'maximum_selected_project_count_rule': None,
        'minimum_optimal_project_count_rule': None, 'difficulty_requires_actual_fresh_first_attempt_model_evidence': True,
        'failure_policy': 'Retain every generated profile and diagnostic result. New parameter revisions require new immutable artifacts; do not select by model outcomes.',
        'financial_ledger_calls': 0, 'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0, 'qualified': False}


def generate_specs(catalog=DEFAULT_CATALOG):
    config = load_catalog(catalog)
    return [{'profile_id': identity, 'spec': build_spec(identity, config)} for identity in PROFILE_ORDER]
