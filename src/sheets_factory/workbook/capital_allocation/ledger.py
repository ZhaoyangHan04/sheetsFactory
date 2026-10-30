"""Independent Decimal forward journal. No optimiser or Excel imports."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext

from .spec import (ANNUAL_FIELDS, OPENING_DATE, PROJECT_FIELDS, SCALE, YEARS, load_spec, validate_plan)

D = Decimal


def _pence(value):
    return int(D(value).quantize(D(1), rounding=ROUND_HALF_UP))


def _factor(amount, numerator):
    return _pence(D(amount) * D(numerator) / D(SCALE))


def build_project_flows(spec, scenario):
    """Rebuild each project independently from its public nominal primitives."""
    result = {}
    with localcontext() as context:
        context.prec = 60
        for project in spec['projects']:
            remaining = project['acquisition_cost_pence']
            rows = []
            for year in YEARS:
                key = str(year)
                active = project['commission_year'] < year <= project['sale_year']
                age = year - project['commission_year']
                depreciation = 0
                if active and age <= project['depreciation_years']:
                    depreciation = (remaining if age == project['depreciation_years'] else
                        min(remaining, max(0, _pence(D(project['acquisition_cost_pence']) / D(project['depreciation_years'])))))
                    remaining -= depreciation
                sale = year == project['sale_year']
                carrying = remaining if sale else 0
                proceeds = _factor(project['sale_proceeds_pence'], scenario['sale_factors_p12'][key]) if sale else 0
                if sale:
                    remaining = 0
                book = remaining if project['commission_year'] <= year < project['sale_year'] else 0
                row = {'year': year, 'capex': project['acquisition_cost_pence'] if year == project['commission_year'] else 0,
                    'revenue': _factor(project['annual_revenue_pence'][key], scenario['revenue_factors_p12'][key]),
                    'opex': _factor(project['annual_opex_pence'][key], scenario['opex_factors_p12'][key]),
                    'depreciation': depreciation, 'sale_proceeds': proceeds, 'sale_carrying': carrying,
                    'sale_gain': proceeds - carrying, 'closing_book_value': book,
                    'certified_nav': _factor(book, scenario['nav_factors_p12'][key])}
                rows.append(row)
            result[project['id']] = rows
    return result


class Journal:
    def __init__(self):
        self.entries = []
        self.accounts = {}

    def post(self, year, event, postings):
        values = {name: D(value) for name, value in postings.items() if value}
        if not values:
            return
        if sum(values.values(), D(0)) != 0:
            raise ArithmeticError('Unbalanced journal event: ' + event)
        for name, value in values.items():
            self.accounts[name] = self.accounts.get(name, D(0)) + value
        self.entries.append({'year': year, 'event': event,
            'debits': {name: int(value) for name, value in values.items() if value > 0},
            'credits': {name: int(-value) for name, value in values.items() if value < 0}})

    def value(self, name):
        return int(self.accounts.get(name, D(0)))

    def close_income(self, year):
        profit = 0
        for name in ('Revenue', 'OperatingExpense', 'DepreciationExpense',
                     'SaleGainLoss', 'BankInterestExpense', 'CurrentTaxExpense'):
            value = self.value(name)
            profit -= value
            self.post(year, 'close_' + name, {name: -value, 'RetainedEarnings': value})
        return profit


def _scenario(spec, scenario, plan):
    projects = build_project_flows(spec, scenario)
    journal = Journal()
    opening = spec['opening_cash_pence']
    journal.post(2023, 'opening_LP_contribution', {'Cash': opening, 'PaidInCapital': -opening})
    cash, bank, capital, retained, called, previous_nav = opening, 0, opening, 0, 0, 0
    losses, annual, violations, vintage_rows = {}, [], [], []
    numerator = D(0)
    with localcontext() as context:
        context.prec = 60
        for index, year in enumerate(YEARS):
            key = str(year)
            row = {'year': year, 'cash_open': cash, 'bank_open': bank,
                'capital_open': capital, 'retained_open': retained, 'lp_called_open': called,
                'prior_certified_nav': previous_nav}
            total = {name: sum(projects[pid][index][name] * plan[pid] for pid in plan) for name in PROJECT_FIELDS}
            row.update({name: total[name] for name in ('revenue', 'opex', 'capex', 'depreciation',
                'sale_proceeds', 'sale_carrying', 'sale_gain', 'certified_nav')})
            interest = _factor(bank, scenario['bank_rates_p12'][key])
            taxable = total['revenue'] - total['opex'] - total['depreciation'] + total['sale_gain'] - interest
            loss_open = sum(losses.values())
            expired = used = created = 0
            vintage = {}
            for origin in sorted(losses):
                amount = losses[origin]
                expiry = amount if year - origin > spec['tax_loss_carry_years'] else 0
                vintage[origin] = {'year': year, 'vintage': origin, 'opening': amount,
                    'expired': expiry, 'used': 0, 'created': 0, 'closing': amount - expiry}
                losses[origin] -= expiry
                expired += expiry
            taxable_after = max(0, taxable)
            for origin in sorted(losses):
                taken = min(losses[origin], taxable_after)
                losses[origin] -= taken
                taxable_after -= taken
                used += taken
                vintage[origin]['used'] = taken
                vintage[origin]['closing'] = losses[origin]
            if taxable < 0:
                created = -taxable
                losses[year] = created
                vintage[year] = {'year': year, 'vintage': year, 'opening': 0,
                    'expired': 0, 'used': 0, 'created': created, 'closing': created}
            # Keep all twenty vintage cells explicit, including zero amounts.
            for origin in YEARS:
                vintage_rows.append(vintage.get(origin, {'year': year, 'vintage': origin,
                    'opening': 0, 'expired': 0, 'used': 0, 'created': 0, 'closing': 0}))
            tax = _factor(taxable_after, spec['tax_rate_p12'])
            income = taxable - tax
            base = (0 if year == YEARS[-1] else min(spec['facility_limit_pence'],
                _pence(D(previous_nav) * D(spec['advance_rate_p12'])
                       * D(SCALE - scenario['haircuts_p12'][key]) / D(SCALE)**2)))
            minimum = 0 if year == YEARS[-1] else spec['minimum_cash_pence']
            before = cash + total['revenue'] - total['opex'] - total['capex'] + total['sale_proceeds'] - interest - tax
            margin = max(0, bank - base)
            after_margin = before - margin
            optional = min(bank - margin, max(0, after_margin - minimum))
            after_optional = after_margin - optional
            draw = min(max(0, base - (bank - margin - optional)), max(0, minimum - after_optional))
            required = max(0, minimum - after_optional - draw)
            contribution = min(required, max(0, spec['lp_commitment_pence'] - called))
            gap = required - contribution
            before_distribution = after_optional + draw + contribution
            equity_before = capital + contribution + retained + income
            distribution = min(max(0, before_distribution - minimum), max(0, equity_before))
            returned = min(distribution, capital + contribution)
            profit_distribution = distribution - returned
            closing_cash = before_distribution - distribution
            closing_bank = bank - margin - optional + draw
            closing_capital = capital + contribution - returned
            closing_retained = retained + income - profit_distribution

            # Raise the stated finance before the annual net settlement. Each
            # project and account posting is independently double entered.
            journal.post(year, 'bank_draw', {'Cash': draw, 'BankDebt': -draw})
            journal.post(year, 'LP_call', {'Cash': contribution, 'PaidInCapital': -contribution})
            for pid in plan:
                if not plan[pid]:
                    continue
                item = projects[pid][index]
                journal.post(year, pid + '_acquisition', {'ProjectAssets': item['capex'], 'Cash': -item['capex']})
                journal.post(year, pid + '_revenue', {'Cash': item['revenue'], 'Revenue': -item['revenue']})
                journal.post(year, pid + '_opex', {'OperatingExpense': item['opex'], 'Cash': -item['opex']})
                journal.post(year, pid + '_depreciation', {'DepreciationExpense': item['depreciation'], 'ProjectAssets': -item['depreciation']})
                journal.post(year, pid + '_sale', {'Cash': item['sale_proceeds'],
                    'ProjectAssets': -item['sale_carrying'], 'SaleGainLoss': -item['sale_gain']})
            journal.post(year, 'bank_interest', {'BankInterestExpense': interest, 'Cash': -interest})
            journal.post(year, 'current_tax', {'CurrentTaxExpense': tax, 'Cash': -tax})
            journal.post(year, 'mandatory_margin', {'BankDebt': margin, 'Cash': -margin})
            journal.post(year, 'optional_repayment', {'BankDebt': optional, 'Cash': -optional})
            if journal.close_income(year) != income:
                raise ArithmeticError('Independent P&L closing differs from the financial bridge')
            journal.post(year, 'return_of_capital', {'PaidInCapital': returned, 'Cash': -returned})
            journal.post(year, 'profit_distribution', {'RetainedEarnings': profit_distribution, 'Cash': -profit_distribution})
            book = total['closing_book_value']
            cash_check = closing_cash - (cash + total['revenue'] - total['opex'] - total['capex']
                + total['sale_proceeds'] - interest - tax - margin - optional + draw + contribution - distribution)
            row.update(bank_interest=interest, taxable_before_losses=taxable,
                loss_open=loss_open, loss_expired=expired, loss_used=used, loss_created=created,
                loss_close=sum(losses.values()), taxable_after_losses=taxable_after,
                current_tax=tax, net_income=income, borrowing_base=base,
                cash_before_financing=before, mandatory_margin=margin, cash_after_margin=after_margin,
                optional_repayment=optional, cash_after_optional=after_optional, bank_draw=draw,
                lp_required=required, lp_call=contribution, funding_gap=gap,
                cash_before_distribution=before_distribution, equity_before_distribution=equity_before,
                distribution=distribution, return_of_capital=returned, profit_distribution=profit_distribution,
                net_lp_cashflow=distribution - contribution, lp_called_close=called + contribution,
                lp_remaining=spec['lp_commitment_pence'] - called - contribution,
                cash_close=closing_cash, bank_close=closing_bank, capital_close=closing_capital,
                retained_close=closing_retained, project_book_value=book,
                total_assets=closing_cash + book, total_liabilities=closing_bank,
                total_equity=closing_capital + closing_retained,
                balance_check=closing_cash + book - closing_bank - closing_capital - closing_retained,
                cash_check=cash_check, bank_check=closing_bank - bank + margin + optional - draw,
                capital_check=closing_capital - capital - contribution + returned,
                loss_check=sum(losses.values()) - loss_open + expired + used - created)
            if any(row[name] != 0 for name in ('balance_check', 'cash_check', 'bank_check', 'capital_check', 'loss_check')):
                raise ArithmeticError('An independent financial conservation identity failed')
            if (journal.value('Cash'), -journal.value('BankDebt'), -journal.value('PaidInCapital'),
                -journal.value('RetainedEarnings'), journal.value('ProjectAssets')) != (
                    closing_cash, closing_bank, closing_capital, closing_retained, book):
                raise ArithmeticError('Journal balances differ from the independent account bridge')
            if gap:
                violations.append({'year': year, 'kind': 'unfunded_cash_deficiency', 'amount_pence': gap})
            if year == YEARS[-1]:
                for name, amount in (('terminal_bank_debt', closing_bank),
                                     ('terminal_project_assets', book), ('terminal_cash', closing_cash)):
                    if amount:
                        violations.append({'year': year, 'kind': name, 'amount_pence': amount})
            numerator += D(distribution - contribution) * D(spec['discount_factors_p12'][key])
            annual.append(row)
            cash, bank, capital, retained, called, previous_nav = (
                closing_cash, closing_bank, closing_capital, closing_retained, called + contribution, total['certified_nav'])
        net_numerator = numerator - D(opening) * D(SCALE)
        npv = _pence(net_numerator / D(SCALE))
    if any(set(row) != {'year', *ANNUAL_FIELDS} for row in annual):
        raise ArithmeticError('The declared annual financial binding fields differ')
    return {'id': scenario['id'], 'feasible': not violations, 'violations': violations,
        'first_violation': violations[0] if violations else None, 'annual': annual,
        'project_flows': projects, 'tax_vintages': vintage_rows,
        'lp_cashflows': [{'date': OPENING_DATE, 'amount_pence': -opening}] + [
            {'date': f"{row['year']}-03-31", 'amount_pence': row['net_lp_cashflow']} for row in annual],
        'npv_numerator': str(numerator), 'net_npv_numerator': str(net_numerator),
        'diagnostic_npv_pence': npv,
        'npv_pence': npv if not violations else None,
        'journal': journal.entries, 'account_balances': {name: int(value) for name, value in journal.accounts.items()},
        'all_journals_balance': all(sum(item['debits'].values()) == sum(item['credits'].values()) for item in journal.entries),
        'diagnostic_continuation_after_infeasibility': True}


def simulate(spec, plan):
    """Evaluate one common plan from public primitives, without selecting it."""
    spec, plan = load_spec(spec), validate_plan(plan)
    scenarios = {scenario['id']: _scenario(spec, scenario, plan) for scenario in spec['scenarios']}
    feasible = all(row['feasible'] for row in scenarios.values())
    return {'schema_version': 1, 'plan': plan, 'feasible': feasible, 'scenarios': scenarios,
        'objective_pence': min(row['npv_pence'] for row in scenarios.values()) if feasible else None,
        'objective_kind': 'maximin_LP_net_present_value_pence',
        'optimisation_performed': False, 'unique_optimum_claimed': False}
