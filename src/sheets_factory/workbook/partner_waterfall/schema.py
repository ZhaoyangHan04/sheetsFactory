"""Public layout and type metadata only; no financial computations."""
from .contract import FINANCIAL_FIELDS

SHEETS = {'inputs': 'Partner Inputs', 'waterfall': 'Partner Waterfall', 'brief': 'Partner Contract'}
INPUT_FIELDS = ('opening_date', 'opening_capital', 'lp_capital_fraction', 'preference_rate',
                'initial_carry_rate', 'flipped_carry_rate', 'lp_xirr_hurdle')
FIELDS = FINANCIAL_FIELDS + ('hurdle_xnpv', 'carry_rate', 'next_carry_rate', 'flip_earned',
    'flip_effective_year', 'lp_sign_changes', 'lp_xirr_eligible', 'lp_last_nonzero_sign')
INTEGER_FIELDS = {'flip_earned', 'flip_effective_year', 'lp_sign_changes',
                  'lp_xirr_eligible', 'lp_last_nonzero_sign'}
RATE_FIELDS = {'lp_xirr', 'carry_rate', 'next_carry_rate'}


def row(field):
    return 3 + FIELDS.index(field)
