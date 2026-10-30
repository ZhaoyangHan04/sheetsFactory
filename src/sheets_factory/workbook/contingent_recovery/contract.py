"""Validate supplied business terms without inferring any missing contract input."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

PENNY = Decimal('.01')
CONTRACT_FIELDS = {'lease_id', 'active', 'rate', 'threshold', 'annual_cap',
                   'rounding_quantum', 'rounding_mode'}
ACCOUNTING = {'book_expense': 'same_reporting_year', 'cash_payment': 'same_reporting_year',
              'tax_deduction': 'same_reporting_year', 'base_lease_pv_rou_liability': 'excluded',
              'variable_allowance_posting': 'separate_penny_posting_of_fraction_times_total_variable_rent'}
ITERATION = {'domain': 'finite_contractual_total_rent_grid', 'max_steps': 128,
             'acceptance': 'identical_fixed_point_from_zero_and_sum_of_caps'}
SPEC_FIELDS = {'schema_version', 'scenario_id', 'currency', 'feedback_basis', 'accounting',
               'iteration_policy', 'public_rules', 'annual_terms'}


def decimal(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Explicit exact decimal input required: ' + label)
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid decimal input: ' + label) from None
    if not result.is_finite():
        raise ValueError('Finite decimal input required: ' + label)
    return result


def posted(value, label, *, nonnegative=False):
    result = decimal(value, label)
    if result != result.quantize(PENNY) or (nonnegative and result < 0):
        raise ValueError('Explicit posted penny amount required: ' + label)
    return result


def validate_contracts(contracts):
    """The scalar API accepts one to four supplied contracts, including inactive ones."""
    if not isinstance(contracts, list) or not 1 <= len(contracts) <= 4:
        raise ValueError('One to four explicit annual lease contracts are required')
    seen, rate_sum = set(), Decimal(0)
    for contract in contracts:
        if not isinstance(contract, dict) or set(contract) != CONTRACT_FIELDS:
            raise ValueError('Every annual contingent-rent term must be explicit')
        identity = contract['lease_id']
        if not isinstance(identity, str) or not re.fullmatch(r'P0[1-4]', identity) or identity in seen:
            raise ValueError('Safe unique lease identity P01 through P04 is required')
        seen.add(identity)
        if type(contract['active']) is not bool:
            raise ValueError('An explicit boolean annual payability flag is required')
        rate = decimal(contract['rate'], identity + '.rate')
        threshold = posted(contract['threshold'], identity + '.threshold', nonnegative=True)
        cap = posted(contract['annual_cap'], identity + '.annual_cap', nonnegative=True)
        quantum = posted(contract['rounding_quantum'], identity + '.rounding_quantum', nonnegative=True)
        if quantum not in {Decimal(100), Decimal(1000)} or contract['rounding_mode'] != 'ROUND_HALF_UP':
            raise ValueError('Contractual rounding must explicitly be half up in GBP100 or GBP1000 units')
        if cap % quantum:
            raise ValueError('Each annual cap must be a whole number of its contractual rounding units')
        if contract['active']:
            if not Decimal('.005') <= rate <= Decimal('.02') or cap < quantum:
                raise ValueError('Payable contracts need a rate .005–.02 and a positive contractual cap')
        elif rate != 0 or cap != 0:
            raise ValueError('An inactive contract must explicitly have zero rate and zero annual cap')
        rate_sum += rate
    if not rate_sum < Decimal('.1'):
        raise ValueError('The sum of annual contingent-rent rates must be strictly below .1')
    return deepcopy(contracts)


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != SPEC_FIELDS or spec['schema_version'] != 1:
        raise ValueError('The complete explicit version 1 contingent-recovery contract is required')
    if not isinstance(spec['scenario_id'], str) or not spec['scenario_id'].strip():
        raise ValueError('Explicit scenario identity is required')
    if spec['currency'] != 'GBP_nominal' or spec['feedback_basis'] != 'same_year_total_recovery_entitlement':
        raise ValueError('Contingent rent requires the explicit same-year nominal GBP recovery basis')
    if spec['accounting'] != ACCOUNTING or spec['iteration_policy'] != ITERATION:
        raise ValueError('Explicit current-expense accounting and finite-grid acceptance policies are required')
    if not isinstance(spec['public_rules'], list) or not spec['public_rules'] or any(not isinstance(r, str) or not r.strip() for r in spec['public_rules']):
        raise ValueError('Public contractual calculation rules are required')
    annual = spec['annual_terms']
    if not isinstance(annual, list) or [row.get('year') for row in annual] != list(range(2024, 2044)):
        raise ValueError('Twenty explicitly ordered April–March reporting years FY2024–2043 are required')
    payable_years = 0
    for row in annual:
        if set(row) != {'year', 'eligible_fraction', 'contracts'} or type(row['year']) is not int:
            raise ValueError('Every reporting year needs its own explicit variable eligibility fraction and contracts')
        fraction = decimal(row['eligible_fraction'], 'variable eligibility fraction')
        if not 0 < fraction < 1:
            raise ValueError('The variable eligibility fraction must be strictly between zero and one')
        validate_contracts(row['contracts'])
        if {contract['lease_id'] for contract in row['contracts']} != {'P01', 'P02', 'P03', 'P04'}:
            raise ValueError('Every year must explicitly include all four lease payability records')
        payable_years += any(contract['active'] for contract in row['contracts'])
    if payable_years < 12:
        raise ValueError('At least twelve reporting years must contain payable contingent contracts')
    return deepcopy(spec)


def load_spec(path):
    return validate_spec(json.loads(Path(path).read_text()))
