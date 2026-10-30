"""Public field names and row metadata; contains no forecasting calculation."""
RAV_FIELDS=('cwip_close','depreciation','disallowance','rav_close')
TAX_FIELDS=('tax_cip_close','general_close','special_close','structures_close','capital_allowance')
CLAIM_FIELDS=('interest','collected','close')
LOSS_FIELDS=('expired','used','close')
ANNUAL_FIELDS=('opening_cwip_real','opening_rav_real','capital_spend_real','commissioning_real',
 'depreciation_real','disallowance_real','closing_cwip_real','closing_rav_real','real_return',
 'capital_spend_nominal','commissioning_nominal','depreciation_nominal','disallowance_nominal',
 'return_nominal','closing_cwip_nominal','closing_rav_nominal','asset_revaluation',
 'tax_capital_allowances','tax_basis_transfer','closing_tax_basis','debt_open','debt_draw',
 'debt_repayment','debt_interest','debt_close','claims_open','claim_carrying_interest',
 'claims_receipts','claims_close','losses_open','losses_expired','losses_available',
 'pre_allowance_taxable_profit','losses_used','losses_created','losses_close',
 'current_tax_allowance','capital_entitlement','earned_revenue','net_income',
 'owner_capital','owner_distribution','owner_net_cashflow','cash_close','paid_in_capital',
 'retained_earnings','revaluation_reserve','total_assets','total_equity','balance_check',
 'cash_check','claims_check')
SHEETS={'inputs':'Reopener Inputs','assets':'Reopener Assets','rav':'Reopener RAV',
        'tax':'Reopener Tax Basis','claims':'Reopener Claims','losses':'Reopener Tax Loss',
        'annual':'Reopener Statements','brief':'Reopener Brief'}
ANNUAL_INPUT_FIELDS=('price_index','real_wacc','tax_rate','claim_carry_rate','debt_rate',
 'collection_cap_nominal','disallowance_real','general_rate','special_rate','general_transfer_fraction')
BATCH_FIELDS=('id','paid_year','commission_year','regulatory_life','tax_pool','real_cost','nominal_cost')
LEASE_FIELDS=('lease_cash_rent','lease_book_depreciation','lease_book_interest',
 'lease_termination_gain_loss','lease_tax_deduction','lease_regulatory_expense',
 'lease_rou_open','lease_rou_close','lease_liability_open','lease_liability_close')
COMBINED_ANNUAL_FIELDS=ANNUAL_FIELDS+LEASE_FIELDS+('lease_regulatory_allowance','total_liabilities','cfo','cfi','cff')


def annual_row(field):return 3+ANNUAL_FIELDS.index(field)
def batch_row(index,fields,field):return 3+index*len(fields)+fields.index(field)
def vintage_row(index,fields,field):return 3+index*len(fields)+fields.index(field)
