"""Public business primitives. No optimizer, workbook answers, or official donors."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import calendar
import json
from pathlib import Path

KIND = 'synthetic_period_boundary_financial_portfolio'
FAULTS = ('next_month_start', 'calendar_year_fiscal_basis', 'unclipped_maturity', 'immediate_terminal_settlement')
RULES = (
    'This is a hypothetical GBP equity cash-flow forecast, not an observed company or investment recommendation. Amounts are GBP; rates are percentages. Cash postings and each discounted cash flow round to the nearest penny, with exact half pennies away from zero.',
    'Forecast periods are full calendar months. The valuation date is the day before the first forecast month. Fiscal years end on the last day of each business\'s stated fiscal-end month. Annual revenue growth first applies when the forecast enters a new fiscal year, and compounds at each subsequent fiscal-year transition.',
    'Each business earns its stated monthly base revenue throughout its initial forecast fiscal year. Its operating margin is constant. Annualized revenue and operating costs are twelve times the current month; receivables and payables use the actual number of days in that business\'s fiscal year. Opening net working capital is separately provided; subsequent cash investment is the change in net working capital.',
    'The supplied opening facility draws fund the initial project expenditure and opening working capital at the valuation date. Debt is outstanding at the start of the first forecast month and pays monthly cash interest on opening principal. Accrual includes the first day of a month and excludes the repayment date. Principal is repaid at the start of the maturity date, so interest in the maturity month stops before that date. ACT/365F and ACT/360 use their stated fixed denominators, including in leap years.',
    'A Bullet facility repays all remaining principal at maturity. A Quarterly principal facility repays its stated fixed installment at each calendar-quarter end, capped at opening principal, and repays all remaining principal at maturity. Quarter-end scheduled repayment occurs after that month\'s interest accrual. No new borrowing occurs during the forecast.',
    'The portfolio pays cash tax monthly on positive aggregate operating profit less cash interest; losses have no tax benefit or carry. Monthly equity cash flow equals operating profit less interest, cash tax, principal repayment, and investment in net working capital. Initial equity contribution equals initial project expenditure plus opening net working capital less the opening facility draws.',
    'At forecast end, operations cease. The entire closing net working capital is collected in cash after the stated settlement lag in calendar days. There is no other terminal value, disposal receipt, or terminal debt: all facilities must mature within the forecast.',
    'All monthly cash flows occur on calendar month end; the terminal working-capital collection occurs on its actual settlement date. Discount equity cash flows at the stated annual effective rate using actual elapsed days divided by 365. Round each present value to pennies before summing, and include the negative opening equity contribution at the valuation date.',
    'Preserve all supplied assumptions, business policy text, worksheet names/order, and formatting. Complete or correct all derived dates and financial outputs in the forecast, debt service, equity cash-flow, and valuation schedules. Blank spacer cells and unused table areas remain blank.',
)
BRIEFS = {
    'financial_modeling': 'Complete the monthly financial model and equity valuation for the businesses and facilities shown. Follow the workbook\'s business policies, reconcile the cash movements and terminal working-capital collection, and preserve the supplied assumptions, worksheet structure, and formatting. Save the completed workbook to output.xlsx.',
    'debugging': 'Review and correct the monthly financial model and equity valuation so that all derived dates, debt service, working-capital movements, and cash-flow valuation follow the workbook\'s business policies. Preserve the supplied assumptions, worksheet structure, and formatting. Save the corrected workbook to output.xlsx.',
}


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def shifted_month(first, offset):
    serial = first.year * 12 + first.month - 1 + offset
    return date(serial // 12, serial % 12 + 1, 1)


def prototype():
    return {
        'kind': KIND, 'version': 1, 'synthetic': True, 'start_month': '2027-12-01', 'months': 12,
        'discount_rate': '0.09', 'tax_rate': '0.25', 'initial_project_expenditure_pence': 45000000,
        'terminal_settlement_lag_days': 45,
        'businesses': [
            {'id': 'B01', 'name': 'Regional Distribution', 'fiscal_end_month': 6, 'monthly_revenue_pence': 13000000,
             'operating_margin': '0.24', 'annual_growth': '0.08', 'receivable_days': 45, 'payable_days': 30,
             'opening_working_capital_pence': 10000000},
            {'id': 'B02', 'name': 'Equipment Maintenance', 'fiscal_end_month': 3, 'monthly_revenue_pence': 9000000,
             'operating_margin': '0.28', 'annual_growth': '0.06', 'receivable_days': 60, 'payable_days': 45,
             'opening_working_capital_pence': 7000000},
        ],
        'facilities': [
            {'id': 'F01', 'name': 'Bridge facility', 'type': 'Bullet', 'opening_principal_pence': 18000000,
             'annual_rate': '0.065', 'day_count_basis': 365, 'maturity_date': '2028-02-15', 'quarterly_principal_pence': 0},
            {'id': 'F02', 'name': 'Equipment facility', 'type': 'Quarterly principal', 'opening_principal_pence': 12000000,
             'annual_rate': '0.052', 'day_count_basis': 360, 'maturity_date': '2028-08-17', 'quarterly_principal_pence': 2000000},
        ],
        'provenance': {'type': 'new_synthetic_business_primitives', 'official_workbook_or_gold_used': False,
            'description': 'Predeclared calendar, debt and cash-flow assumptions; no source values or formulas copied from SpreadsheetBench2.'},
    }


def load_spec(value):
    from decimal import Decimal
    s = deepcopy(value if isinstance(value, dict) else json.loads(Path(value).read_text()))
    assert s['kind'] == KIND and type(s['version']) is int and s['version'] == 1 and s['synthetic'] is True
    first = date.fromisoformat(s['start_month']); assert first.day == 1
    assert type(s['months']) is int and 3 <= s['months'] <= 60
    final = month_end(shifted_month(first, s['months']-1).year, shifted_month(first, s['months']-1).month)
    assert type(s['terminal_settlement_lag_days']) is int and 1 <= s['terminal_settlement_lag_days'] <= 180
    assert 1 <= len(s['businesses']) <= 12 and 1 <= len(s['facilities']) <= 12
    for field in ['discount_rate', 'tax_rate']:
        assert type(s[field]) is str and Decimal(s[field]).is_finite() and 0 <= Decimal(s[field]) <= 1
    assert type(s['initial_project_expenditure_pence']) is int and 0 <= s['initial_project_expenditure_pence'] <= 10**11
    for collection in ['businesses', 'facilities']:
        assert len({x['id'] for x in s[collection]}) == len(s[collection])
        assert all(type(x['name']) is str and x['name'] and not x['name'].startswith('=') for x in s[collection])
    for b in s['businesses']:
        assert type(b['fiscal_end_month']) is int and 1 <= b['fiscal_end_month'] <= 12
        for field in ['monthly_revenue_pence','opening_working_capital_pence']:
            assert type(b[field]) is int and 0 <= b[field] <= 10**11
        for field in ['receivable_days','payable_days']:
            assert type(b[field]) is int and 0 <= b[field] <= 180
        for field in ['operating_margin','annual_growth']:
            assert type(b[field]) is str and Decimal(b[field]).is_finite() and 0 <= Decimal(b[field]) <= 1
    for f in s['facilities']:
        assert f['type'] in ['Bullet', 'Quarterly principal'] and type(f['day_count_basis']) is int and f['day_count_basis'] in [360,365]
        assert type(f['annual_rate']) is str and Decimal(f['annual_rate']).is_finite() and 0 <= Decimal(f['annual_rate']) <= 1
        assert first <= date.fromisoformat(f['maturity_date']) <= final
        for field in ['opening_principal_pence','quarterly_principal_pence']:
            assert type(f[field]) is int and 0 <= f[field] <= 10**11
        assert (f['type'] == 'Bullet' and f['quarterly_principal_pence'] == 0) or (f['type'] == 'Quarterly principal' and f['quarterly_principal_pence'] > 0)
    return s
