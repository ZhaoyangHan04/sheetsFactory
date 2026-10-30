"""Names and cell-binding metadata only; no financial calculations."""
SHEETS={'brief':'Holding Brief','inputs':'Holding Inputs','operating':'Holding Operating Link',
        'parent':'Holding Statements','group':'Holding Consolidated'}
PROGRAMME_FIELDS=('owner_capital','owner_distribution','net_income','asset_revaluation',
 'total_assets','total_equity','cash_close','closing_rav_nominal','claims_close','debt_close',
 'lease_liability_close','cfo','cfi','cff')
OPERATING_FIELDS=('date','fiscal_year','income_usd','dividend_usd','acquisition_usd','sale_usd',
                  'income_gbp','dividend_gbp','acquisition_gbp','sale_gbp')
PARENT_FIELDS=('cash_open','bank_open','programme_investment_open','operating_investment_open',
 'capital_open','retained_open','oci_open','lp_called_open','bank_interest','management_fee',
 'operating_income','operating_dividend','operating_acquisition','operating_sale',
 'operating_sale_carrying','operating_sale_gain','operating_investment_close',
 'programme_income','programme_oci','programme_capital','programme_distribution',
 'programme_investment_close','rav_collateral','claims_after_haircut','claims_collateral',
 'senior_obligations','borrowing_base','funding_before_repayments','mandatory_margin',
 'funding_after_margin','optional_repayment','funding_after_repayments','bank_headroom',
 'bank_draw','lp_required','lp_capital','lp_called_close','lp_remaining','cash_close',
 'bank_close','net_income','capital_close','retained_close','oci_close','assets','liabilities',
 'equity','balance_check','cfo','cfi','cff','cash_check','programme_investment_check')
GROUP_FIELDS=('cash_open','cash_close','parent_assets','programme_assets','investment_elimination',
 'assets','parent_liabilities','programme_bank_debt','programme_lease_liability','liabilities',
 'parent_equity','programme_equity','equity_elimination','equity','balance_check',
 'parent_income','programme_income','income_elimination','net_income','income_check',
 'parent_oci','programme_oci','oci_elimination','oci','owner_capital_elimination',
 'owner_distribution_elimination','cfo','cfi','cff','cash_check')
PARAMETERS=('opening_cash','minimum_cash','facility_limit','additional_lp_commitment',
            'rav_advance_rate','claim_advance_rate','operating_ownership','gbp_per_usd')
ANNUAL_PARAMETERS=('bank_rate','management_fee','claim_haircut')


def row(field,fields):return 3+fields.index(field)
