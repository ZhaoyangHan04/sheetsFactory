"""Integer forward close from the complete public fixed-plan contract.

No workbook, investment search, model, or other financial implementation is
imported.  Queues contain only nonzero live vintages; expiry/use evidence is
retained as sparse events, never a month-by-month zero vintage square.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import json

from .spec import PHASES, SCALE, load_spec, require


def rounded(numerator, denominator=SCALE):
    require(type(numerator) is int and type(denominator) is int and denominator > 0,
            'A posting requires an exact integer rational')
    answer = (2 * abs(numerator) + denominator) // (2 * denominator)
    return -answer if numerator < 0 else answer


def _ceil(numerator, denominator):
    require(numerator >= 0 and denominator > 0, 'A capacity conversion requires a nonnegative rational')
    return (numerator + denominator - 1) // denominator


def _asof(records, keys, month):
    eligible = [r for r in records if all(r[k] == v for k, v in keys.items())
                and r['effective_month'] <= month]
    require(bool(eligible), 'No applicable complete-key public contract')
    return max(eligible, key=lambda r: r['effective_month'])


def _expire(queue, offset, carry, months):
    expired = []
    for origin in sorted(list(queue)):
        if offset - origin > carry:
            expired.append({'vintage_month': months[origin], 'amount_minor': queue.pop(origin)})
    return expired


def _consume(queue, amount, months):
    events = []
    for origin in sorted(list(queue)):
        used = min(queue[origin], amount)
        if used:
            events.append({'vintage_month': months[origin], 'amount_minor': used})
            queue[origin] -= used
            amount -= used
        if not queue[origin]:
            del queue[origin]
        if not amount:
            break
    return amount, events


def _sum_events(events):
    return sum(event['amount_minor'] for event in events)


def _queue_rows(queue, months):
    return [{'vintage_month': months[origin], 'balance_minor': amount}
            for origin, amount in sorted(queue.items())]


def _project(project, selected, month, offset, months, scenario, books):
    before = books[project['id']]
    fields = dict.fromkeys(('capex', 'revenue', 'opex', 'depreciation', 'sale', 'sale_carrying', 'sale_gain'), 0)
    book = before
    if selected:
        if month == project['commission_month']:
            fields['capex'] = project['cost_minor']
            book += project['cost_minor']
        if project['commission_month'] < month <= project['sale_month']:
            fields['revenue'] = rounded(project['revenue_minor'][month] * scenario['revenue_factor_p12'][month])
            fields['opex'] = rounded(project['opex_minor'][month] * scenario['opex_factor_p12'][month])
            age = offset - months.index(project['commission_month'])
            if age <= project['depreciation_months']:
                charge = book if age == project['depreciation_months'] else rounded(project['cost_minor'], project['depreciation_months'])
                fields['depreciation'] = min(book, max(0, charge))
                book -= fields['depreciation']
            if month == project['sale_month']:
                fields['sale'] = rounded(project['sale_minor'] * scenario['sale_factor_p12'][month])
                fields['sale_carrying'] = book
                fields['sale_gain'] = fields['sale'] - book
                book = 0
    books[project['id']] = book
    return {'month': month, 'opening_book_minor': before, **fields, 'closing_book_minor': book,
            'certified_nav_minor': rounded(book * scenario['nav_factor_p12'][month])}


def _bank_usage(rows, entity_map, scenario, month):
    return sum(_ceil(row['bank_close'] * scenario['fx_gbp_p12'][entity_map[identity]['currency']][month], SCALE)
               for identity, row in rows.items())


def _next_covenant(opening_trap, opening_cure, ebitda, debt_service, threshold):
    passed = debt_service == 0 or ebitda * SCALE >= debt_service * threshold
    if not passed:
        return {'covenant_passed': False, 'cure_run_after_test': 0, 'trap_next': True, 'cure_count_next': 0}
    run = opening_cure + 1 if opening_trap else 0
    release = opening_trap and run >= 2
    return {'covenant_passed': True, 'cure_run_after_test': run,
            'trap_next': opening_trap and not release, 'cure_count_next': 0 if release else run}


MECHANISMS = (
    'effective_date_rollover', 'intercompany_draw', 'intercompany_interest',
    'intercompany_principal_repayment', 'bank_margin', 'shared_facility_contention',
    'covenant_breach', 'opening_trap_applied', 'two_pass_cure', 'restricted_cash_released',
    'interest_vintage_used', 'tax_vintage_used', 'vintage_expired', 'currency_translation',
)


def _scenario(public, scenario):
    months = public['months']
    entities = {e['id']: e for e in public['entities']}
    loans = {loan['id']: loan for loan in public['intercompany_loans']}
    balances = dict.fromkeys(loans, 0)
    books = dict.fromkeys(public['fixed_plan'], 0)
    states, result_entities, result_projects, result_loans = {}, {}, {}, {}
    for identity, e in entities.items():
        opening = e['opening_cash_minor'] + e['opening_restricted_minor']
        fx = public['opening_fx_gbp_p12'][e['currency']]
        states[identity] = {'cash': e['opening_cash_minor'], 'restricted': e['opening_restricted_minor'],
            'bank': 0, 'capital': opening, 'retained': 0, 'called': 0, 'nav': 0,
            'trap': e['opening_trap'], 'cure': e['opening_cure_count'], 'fx': fx,
            'capital_gbp': rounded(opening * fx), 'retained_gbp': 0,
            'fx_reserve_gbp': 0, 'posting_rounding_gbp': 0, 'interest_queue': {}, 'tax_queue': {}}
        result_entities[identity] = {'currency': e['currency'], 'monthly': []}
    for p in public['projects']:
        result_projects[p['id']] = []
    for identity in loans:
        result_loans[identity] = []
    activated = {name: {'count': 0, 'witnesses': []} for name in MECHANISMS}
    def witness(name, month, **details):
        record = activated[name]
        record['count'] += 1
        if len(record['witnesses']) < 8:
            record['witnesses'].append({'month': month, **details})
    monthly_group = []
    feasible, first_gap = True, None
    for offset, month in enumerate(months):
        opening_balances = dict(balances)
        rows, bank_terms, loan_terms, loan_rows = {}, {}, {}, {}
        for identity, e in entities.items():
            s = states[identity]
            fx = scenario['fx_gbp_p12'][e['currency']][month]
            term = _asof(public['bank_terms'], {'entity_id': identity, 'facility_id': e['facility_id'], 'currency': e['currency']}, month)
            bank_terms[identity] = term
            if offset and term['effective_month'] == month:
                witness('effective_date_rollover', month, entity_id=identity, facility_id=e['facility_id'], currency=e['currency'])
            rate = rounded(term['monthly_rate_p12'] * scenario['rate_factor_p12'][month])
            rows[identity] = {
                'month': month, 'cash_open': s['cash'], 'restricted_open': s['restricted'],
                'bank_open': s['bank'], 'capital_open': s['capital'], 'retained_open': s['retained'],
                'called_open': s['called'], 'prior_certified_nav': s['nav'],
                'trap_open': s['trap'], 'cure_count_open': s['cure'], 'fx_open_p12': s['fx'], 'fx_close_p12': fx,
                'bank_term_effective_month': term['effective_month'], 'bank_monthly_rate_p12': rate,
                'bank_interest': rounded(s['bank'] * rate), 'cash_close': s['cash'], 'bank_close': s['bank'],
                **dict.fromkeys(('revenue', 'opex', 'capex', 'depreciation', 'sale', 'sale_carrying',
                    'sale_gain', 'project_book_open', 'project_book_close', 'certified_nav_close',
                    'ic_interest_income', 'ic_interest_expense', 'ic_receivable_open', 'ic_payable_open',
                    'ic_principal_received', 'ic_principal_paid', 'ic_draw_lent', 'ic_draw_received',
                    'bank_local_margin', 'bank_shared_margin', 'bank_draw', 'reserve_locked', 'reserve_released'), 0),
            }
        for project in public['projects']:
            posting = _project(project, public['fixed_plan'][project['id']], month, offset, months, scenario, books)
            result_projects[project['id']].append(posting)
            row = rows[project['entity_id']]
            for field in ('revenue', 'opex', 'capex', 'depreciation', 'sale', 'sale_carrying', 'sale_gain'):
                row[field] += posting[field]
            row['project_book_open'] += posting['opening_book_minor']
            row['project_book_close'] += posting['closing_book_minor']
            row['certified_nav_close'] += posting['certified_nav_minor']
        for loan_id, loan in loans.items():
            term = _asof(public['intercompany_terms'], {'loan_id': loan_id,
                **{k: loan[k] for k in ('lender_id', 'borrower_id', 'currency')}}, month)
            loan_terms[loan_id] = term
            if offset and term['effective_month'] == month:
                witness('effective_date_rollover', month, loan_id=loan_id, lender_id=loan['lender_id'], borrower_id=loan['borrower_id'], currency=loan['currency'])
            rate = rounded(term['monthly_rate_p12'] * scenario['rate_factor_p12'][month])
            interest = rounded(opening_balances[loan_id] * rate)
            lender, borrower = rows[loan['lender_id']], rows[loan['borrower_id']]
            lender['ic_receivable_open'] += opening_balances[loan_id]
            borrower['ic_payable_open'] += opening_balances[loan_id]
            lender['ic_interest_income'] += interest
            borrower['ic_interest_expense'] += interest
            loan_rows[loan_id] = {'month': month, 'loan_id': loan_id, 'currency': loan['currency'],
                'lender_id': loan['lender_id'], 'borrower_id': loan['borrower_id'],
                'term_effective_month': term['effective_month'], 'opening_principal': opening_balances[loan_id],
                'interest': interest, 'mandatory_repayment': 0, 'draw': 0}
            if interest:
                witness('intercompany_interest', month, loan_id=loan_id, amount_minor=interest)
        for identity, row in rows.items():
            e, state = entities[identity], states[identity]
            row['ebitda'] = row['revenue'] - row['opex']
            interest_open = sum(state['interest_queue'].values())
            interest_expired = _expire(state['interest_queue'], offset, e['interest_carry_months'], months)
            capacity = rounded(max(0, row['ebitda']) * e['interest_limit_p12'])
            remaining, old_used = _consume(state['interest_queue'], capacity, months)
            expense = row['bank_interest'] + row['ic_interest_expense']
            current_allowed = min(expense, remaining)
            denied = expense - current_allowed
            if denied:
                state['interest_queue'][offset] = denied
            allowed = _sum_events(old_used) + current_allowed
            taxable = row['ebitda'] - row['depreciation'] + row['sale_gain'] + row['ic_interest_income'] - allowed
            tax_open = sum(state['tax_queue'].values())
            tax_expired = _expire(state['tax_queue'], offset, e['tax_carry_months'], months)
            after_loss, loss_used = _consume(state['tax_queue'], max(0, taxable), months)
            created = max(0, -taxable)
            if created:
                state['tax_queue'][offset] = created
            tax = rounded(after_loss * e['tax_rate_p12'])
            income = row['ebitda'] - row['depreciation'] + row['sale_gain'] + row['ic_interest_income'] - expense - tax
            row.update(interest_capacity=capacity, interest_current_allowed=current_allowed,
                interest_vintage_open=interest_open, interest_vintage_close=sum(state['interest_queue'].values()),
                interest_old_used=_sum_events(old_used), interest_denied_created=denied,
                interest_expired=interest_expired, interest_used_events=old_used,
                interest_live_vintages=_queue_rows(state['interest_queue'], months),
                taxable_before_loss=taxable, tax_loss_created=created, tax_loss_used=_sum_events(loss_used),
                tax_loss_open=tax_open, tax_loss_close=sum(state['tax_queue'].values()),
                tax_loss_expired=tax_expired, tax_loss_used_events=loss_used,
                tax_live_vintages=_queue_rows(state['tax_queue'], months),
                taxable_after_loss=after_loss, current_tax=tax, net_income=income)
            row['cash_close'] += (row['revenue'] - row['opex'] - row['capex'] + row['sale']
                - row['bank_interest'] - row['ic_interest_expense'] + row['ic_interest_income'] - tax)
            if old_used:
                witness('interest_vintage_used', month, entity_id=identity, amount_minor=_sum_events(old_used))
            if loss_used:
                witness('tax_vintage_used', month, entity_id=identity, amount_minor=_sum_events(loss_used))
            if interest_expired or tax_expired:
                witness('vintage_expired', month, entity_id=identity, interest=interest_expired, tax=tax_expired)
        for loan_id, loan in loans.items():
            term = loan_terms[loan_id]
            repayment = (opening_balances[loan_id] if month >= term['maturity_month']
                         else max(0, opening_balances[loan_id] - term['limit_minor']))
            balances[loan_id] -= repayment
            rows[loan['lender_id']]['cash_close'] += repayment
            rows[loan['borrower_id']]['cash_close'] -= repayment
            rows[loan['lender_id']]['ic_principal_received'] += repayment
            rows[loan['borrower_id']]['ic_principal_paid'] += repayment
            loan_rows[loan_id]['mandatory_repayment'] = repayment
            if repayment:
                witness('intercompany_principal_repayment', month, loan_id=loan_id, amount_minor=repayment)
        for identity, row in rows.items():
            term = bank_terms[identity]
            base = (0 if month >= term['maturity_month'] else min(term['local_limit_minor'],
                rounded(row['prior_certified_nav'] * term['advance_rate_p12']
                    * (SCALE - scenario['haircut_p12'][month]), SCALE * SCALE)))
            row['borrowing_base'] = base
            margin = max(0, row['bank_close'] - base)
            row['bank_local_margin'] = margin
            row['bank_close'] -= margin
            row['cash_close'] -= margin
        for identity in public['bank_priority']:
            row = rows[identity]
            excess = max(0, _bank_usage(rows, entities, scenario, month) - public['shared_bank_limit_gbp_pence'])
            repayment = min(row['bank_close'], _ceil(excess * SCALE, row['fx_close_p12']))
            row['bank_shared_margin'] = repayment
            row['bank_close'] -= repayment
            row['cash_close'] -= repayment
        require(_bank_usage(rows, entities, scenario, month) <= public['shared_bank_limit_gbp_pence'], 'Shared margin did not restore the declared bank limit')
        for identity, row in rows.items():
            e, state = entities[identity], states[identity]
            margin = row['bank_local_margin'] + row['bank_shared_margin']
            if margin:
                witness('bank_margin', month, entity_id=identity, amount_minor=margin)
            if row['trap_open']:
                locked = min(max(0, row['cash_close']), max(0, e['reserve_target_minor'] - row['restricted_open']))
                row['restricted_close'] = row['restricted_open'] + locked
                row['cash_close'] -= locked
                row['reserve_locked'] = locked
                witness('opening_trap_applied', month, entity_id=identity, locked_minor=locked)
            else:
                row['reserve_released'] = row['restricted_open']
                row['cash_close'] += row['restricted_open']
                row['restricted_close'] = 0
                if row['restricted_open']:
                    witness('restricted_cash_released', month, entity_id=identity, amount_minor=row['restricted_open'])
        for loan_id in public['loan_priority']:
            loan, term = loans[loan_id], loan_terms[loan_id]
            lender, borrower = rows[loan['lender_id']], rows[loan['borrower_id']]
            amount = (0 if month >= term['maturity_month'] else min(
                max(0, term['limit_minor'] - balances[loan_id]),
                max(0, lender['cash_close'] - entities[loan['lender_id']]['minimum_cash_minor']),
                max(0, entities[loan['borrower_id']]['minimum_cash_minor'] - borrower['cash_close'])))
            balances[loan_id] += amount
            lender['cash_close'] -= amount
            borrower['cash_close'] += amount
            lender['ic_draw_lent'] += amount
            borrower['ic_draw_received'] += amount
            loan_rows[loan_id]['draw'] = amount
            if amount:
                witness('intercompany_draw', month, loan_id=loan_id, amount_minor=amount)
        for identity in public['bank_priority']:
            row, e = rows[identity], entities[identity]
            wanted = min(max(0, e['minimum_cash_minor'] - row['cash_close']), max(0, row['borrowing_base'] - row['bank_close']))
            headroom = public['shared_bank_limit_gbp_pence'] - _bank_usage(rows, entities, scenario, month)
            available = headroom * SCALE // row['fx_close_p12']
            draw = min(wanted, available)
            if wanted > available:
                witness('shared_facility_contention', month, entity_id=identity, desired_local_minor=wanted,
                        allowed_local_minor=available, GBP_headroom_pence=headroom, fx_p12=row['fx_close_p12'])
            row['bank_draw'] = draw
            row['bank_close'] += draw
            row['cash_close'] += draw
            require(_bank_usage(rows, entities, scenario, month) <= public['shared_bank_limit_gbp_pence'], 'A draw exceeded exact shared GBP headroom')
        for identity, row in rows.items():
            state, e = states[identity], entities[identity]
            required = max(0, e['minimum_cash_minor'] - row['cash_close'])
            call = min(required, e['additional_commitment_minor'] - row['called_open'])
            row['capital_call'] = call
            row['called_close'] = row['called_open'] + call
            row['cash_close'] += call
            gap = required - call
            row['funding_gap'] = gap
            if gap:
                feasible = False
                if first_gap is None:
                    first_gap = {'month': month, 'entity_id': identity, 'amount_minor': gap}
            equity = row['capital_open'] + call + row['retained_open'] + row['net_income']
            distribution = min(max(0, row['cash_close'] - e['minimum_cash_minor']), max(0, equity))
            capital_return = min(distribution, row['capital_open'] + call)
            profit_distribution = distribution - capital_return
            row.update(equity_before_distribution=equity, distribution=distribution,
                return_of_capital=capital_return, profit_distribution=profit_distribution,
                capital_close=row['capital_open'] + call - capital_return,
                retained_close=row['retained_open'] + row['net_income'] - profit_distribution)
            row['cash_close'] -= distribution
            service = row['bank_interest'] + row['ic_interest_expense'] + row['bank_local_margin'] + row['bank_shared_margin'] + row['ic_principal_paid']
            row['debt_service'] = service
            row.update(_next_covenant(row['trap_open'], row['cure_count_open'], row['ebitda'], service, e['covenant_threshold_p12']))
            if not row['covenant_passed']:
                witness('covenant_breach', month, entity_id=identity, ebitda=row['ebitda'], debt_service=service)
            if row['trap_open'] and not row['trap_next']:
                witness('two_pass_cure', month, entity_id=identity, cure_run=row['cure_run_after_test'])
            row['ic_receivable_close'] = sum(balances[k] for k, loan in loans.items() if loan['lender_id'] == identity)
            row['ic_payable_close'] = sum(balances[k] for k, loan in loans.items() if loan['borrower_id'] == identity)
            total_cash = row['cash_close'] + row['restricted_close']
            total_cash_open = row['cash_open'] + row['restricted_open']
            row['total_assets'] = total_cash + row['project_book_close'] + row['ic_receivable_close']
            row['total_liabilities'] = row['bank_close'] + row['ic_payable_close']
            row['net_assets'] = row['total_assets'] - row['total_liabilities']
            row['equity_close'] = row['capital_close'] + row['retained_close']
            bank_repaid = row['bank_local_margin'] + row['bank_shared_margin']
            external_cash_flow = (row['revenue'] - row['opex'] - row['capex'] + row['sale']
                - row['bank_interest'] - row['current_tax'] - bank_repaid + row['bank_draw'] + call - distribution)
            internal_cash_flow = (row['ic_interest_income'] - row['ic_interest_expense']
                + row['ic_principal_received'] - row['ic_principal_paid'] + row['ic_draw_received'] - row['ic_draw_lent'])
            row['external_cash_flow'] = external_cash_flow
            row['internal_cash_flow'] = internal_cash_flow
            residuals = {
                'cash': total_cash - total_cash_open - external_cash_flow - internal_cash_flow,
                'bank': row['bank_close'] - row['bank_open'] + bank_repaid - row['bank_draw'],
                'capital': row['capital_close'] - row['capital_open'] - call + capital_return,
                'retained': row['retained_close'] - row['retained_open'] - row['net_income'] + profit_distribution,
                'project_book': row['project_book_close'] - row['project_book_open'] - row['capex'] + row['depreciation'] + row['sale_carrying'],
                'ic_receivable': row['ic_receivable_close'] - row['ic_receivable_open'] + row['ic_principal_received'] - row['ic_draw_lent'],
                'ic_payable': row['ic_payable_close'] - row['ic_payable_open'] + row['ic_principal_paid'] - row['ic_draw_received'],
                'net_assets': row['net_assets'] - row['equity_close'],
                'interest_vintage': row['interest_vintage_close'] - row['interest_vintage_open']
                    + _sum_events(row['interest_expired']) + row['interest_old_used'] - row['interest_denied_created'],
                'tax_loss_vintage': row['tax_loss_close'] - row['tax_loss_open']
                    + _sum_events(row['tax_loss_expired']) + row['tax_loss_used'] - row['tax_loss_created'],
            }
            require(all(value == 0 for value in residuals.values()), 'Legal-entity accounting residual: ' + identity + '/' + month)
            row['residuals'] = residuals
            opening_equity = row['capital_open'] + row['retained_open']
            fx = row['fx_close_p12']
            capital_gbp = state['capital_gbp'] + rounded(call * fx) - rounded(capital_return * fx)
            retained_gbp = state['retained_gbp'] + rounded(row['net_income'] * fx) - rounded(profit_distribution * fx)
            economic_fx = rounded(opening_equity * fx) - rounded(opening_equity * row['fx_open_p12'])
            posting_rounding = (rounded(row['equity_close'] * fx) - rounded(opening_equity * fx)
                - rounded(call * fx) - rounded(row['net_income'] * fx)
                + rounded(capital_return * fx) + rounded(profit_distribution * fx))
            require(abs(posting_rounding) <= 3, 'Translation posting rounding exceeds its six half-unit bound')
            fx_reserve = state['fx_reserve_gbp'] + economic_fx
            rounding_reserve = state['posting_rounding_gbp'] + posting_rounding
            translation_residual = rounded(row['net_assets'] * fx) - capital_gbp - retained_gbp - fx_reserve - rounding_reserve
            require(translation_residual == 0, 'Translation bridge does not conserve equity')
            row.update(capital_historical_gbp=capital_gbp, retained_historical_gbp=retained_gbp,
                economic_FX_this_month_gbp=economic_fx, economic_FX_reserve_gbp=fx_reserve,
                posting_translation_rounding_this_month_gbp=posting_rounding,
                posting_translation_rounding_reserve_gbp=rounding_reserve, translation_residual_gbp=translation_residual)
            if economic_fx:
                witness('currency_translation', month, entity_id=identity, opening_equity_minor=opening_equity,
                        previous_fx_p12=row['fx_open_p12'], current_fx_p12=fx, amount_gbp_pence=economic_fx)
            state.update(cash=row['cash_close'], restricted=row['restricted_close'], bank=row['bank_close'],
                capital=row['capital_close'], retained=row['retained_close'], called=row['called_close'],
                nav=row['certified_nav_close'], trap=row['trap_next'], cure=row['cure_count_next'], fx=fx,
                capital_gbp=capital_gbp, retained_gbp=retained_gbp, fx_reserve_gbp=fx_reserve, posting_rounding_gbp=rounding_reserve)
            result_entities[identity]['monthly'].append(row)
        for loan_id, loan_row in loan_rows.items():
            loan_row['closing_principal'] = balances[loan_id]
            loan_row['principal_bridge_residual'] = balances[loan_id] - loan_row['opening_principal'] + loan_row['mandatory_repayment'] - loan_row['draw']
            require(loan_row['principal_bridge_residual'] == 0, 'Bilateral loan principal did not reconcile')
            result_loans[loan_id].append(loan_row)
        def current(field):
            return sum(row[field] * row['fx_close_p12'] for row in rows.values())
        group = {'month': month, 'fiscal_year': date.fromisoformat(month).year + (date.fromisoformat(month).month > 3)}
        for name, opening, closing, movement in (
                ('cash', lambda r: r['cash_open'] + r['restricted_open'], lambda r: r['cash_close'] + r['restricted_close'], lambda r: r['external_cash_flow']),
                ('bank', lambda r: r['bank_open'], lambda r: r['bank_close'], lambda r: r['bank_draw'] - r['bank_local_margin'] - r['bank_shared_margin']),
                ('net_assets', lambda r: r['capital_open'] + r['retained_open'], lambda r: r['equity_close'], lambda r: r['net_income'] + r['capital_call'] - r['distribution'])):
            start = sum(opening(r) * r['fx_open_p12'] for r in rows.values())
            end = sum(closing(r) * r['fx_close_p12'] for r in rows.values())
            flows = sum(movement(r) * r['fx_close_p12'] for r in rows.values())
            fx_change = sum(opening(r) * (r['fx_close_p12'] - r['fx_open_p12']) for r in rows.values())
            residual = end - start - flows - fx_change
            require(residual == 0, 'Group ' + name + ' conservation failed')
            group.update({name + '_open_gbp_numerator': start, name + '_close_gbp_numerator': end,
                name + '_external_movement_gbp_numerator': flows, name + '_FX_gbp_numerator': fx_change,
                name + '_residual_gbp_numerator': residual})
        ic_asset = current('ic_receivable_close')
        ic_liability = current('ic_payable_close')
        ic_income, ic_expense = current('ic_interest_income'), current('ic_interest_expense')
        require(ic_asset == ic_liability and ic_income == ic_expense and current('internal_cash_flow') == 0,
                'Matched group intercompany eliminations failed')
        require(current('total_assets') - current('total_liabilities') - current('equity_close') == 0, 'Exact group balance sheet residual')
        cash_gbp = rounded(group['cash_close_gbp_numerator'])
        book_gbp, bank_gbp = rounded(current('project_book_close')), rounded(current('bank_close'))
        net_gbp = rounded(current('equity_close'))
        group_rounding = net_gbp - sum(rounded(r['equity_close'] * r['fx_close_p12']) for r in rows.values())
        display_rounding = net_gbp - cash_gbp - book_gbp + bank_gbp
        require(abs(group_rounding) <= len(rows) and abs(display_rounding) <= 2, 'Known reporting-rounding bound exceeded')
        group.update(shared_bank_usage_gbp_pence=_bank_usage(rows, entities, scenario, month),
            intercompany_principal_eliminated_gbp_numerator=ic_asset,
            intercompany_interest_eliminated_gbp_numerator=ic_income,
            principal_elimination_residual_gbp_numerator=ic_asset - ic_liability,
            interest_elimination_residual_gbp_numerator=ic_income - ic_expense,
            consolidated_cash_gbp_pence=cash_gbp, consolidated_book_gbp_pence=book_gbp,
            consolidated_external_bank_gbp_pence=bank_gbp, consolidated_net_assets_gbp_pence=net_gbp,
            economic_FX_reserve_gbp_pence=sum(r['economic_FX_reserve_gbp'] for r in rows.values()),
            posting_rounding_reserve_gbp_pence=sum(r['posting_translation_rounding_reserve_gbp'] for r in rows.values()),
            group_equity_translation_rounding_gbp_pence=group_rounding,
            aggregate_line_rounding_gbp_pence=display_rounding,
            historical_capital_gbp_pence=sum(r['capital_historical_gbp'] for r in rows.values()),
            historical_retained_gbp_pence=sum(r['retained_historical_gbp'] for r in rows.values()))
        require(net_gbp == group['historical_capital_gbp_pence'] + group['historical_retained_gbp_pence']
            + group['economic_FX_reserve_gbp_pence'] + group['posting_rounding_reserve_gbp_pence'] + group_rounding,
            'Group historical equity and explicit FX reserves do not reconcile')
        monthly_group.append(group)
    fiscal = []
    by_year = defaultdict(list)
    for row in monthly_group:
        by_year[row['fiscal_year']].append(row)
    for year, periods in sorted(by_year.items()):
        annual = {'fiscal_year': year, 'months': [r['month'] for r in periods]}
        for name in ('cash', 'bank', 'net_assets'):
            start, end = periods[0][name + '_open_gbp_numerator'], periods[-1][name + '_close_gbp_numerator']
            movement = sum(r[name + '_external_movement_gbp_numerator'] for r in periods)
            fx = sum(r[name + '_FX_gbp_numerator'] for r in periods)
            require(end - start - movement - fx == 0, 'Fiscal conservation failed')
            annual.update({name + '_open_gbp_numerator': start, name + '_close_gbp_numerator': end,
                name + '_external_movement_gbp_numerator': movement, name + '_FX_gbp_numerator': fx,
                name + '_residual_gbp_numerator': end - start - movement - fx})
        fiscal.append(annual)
    for record in activated.values():
        record['active'] = record['count'] > 0
        record['witnesses_truncated'] = record['count'] > len(record['witnesses'])
    return {'id': scenario['id'], 'feasible': feasible, 'first_funding_gap': first_gap,
        'entities': result_entities, 'projects': result_projects, 'intercompany': result_loans,
        'group_monthly': monthly_group, 'fiscal_years': fiscal, 'mechanism_activation': activated,
        'all_declared_mechanisms_active': all(r['active'] for r in activated.values()),
        'all_local_group_and_FX_residuals_zero': True}


def simulate(specification):
    """Close only the supplied fixed plan; never choose, repair or optimise it."""
    public = load_spec(specification)
    results = {scenario['id']: _scenario(public, scenario) for scenario in public['scenarios']}
    canonical = json.dumps(public, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    return {'kind': 'entity_group_integer_forward_ledger', 'version': 1,
        'dimension_mode': public['dimension_mode'], 'entity_count': len(public['entities']),
        'month_count': len(public['months']), 'scenario_count': len(public['scenarios']),
        'spec_sha256': hashlib.sha256(canonical).hexdigest(), 'fixed_plan': dict(public['fixed_plan']),
        'phases': list(PHASES), 'scenarios': results, 'feasible': all(s['feasible'] for s in results.values()),
        'optimisation_performed': False, 'financial_source_independently_certified': False,
        'workbook_engine_calls': 0, 'model_calls': 0, 'qualified': False,
        'task_count': 0, 'quality_or_difficulty_certified': False}
