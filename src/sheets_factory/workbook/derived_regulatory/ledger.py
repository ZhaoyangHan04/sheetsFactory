"""Independent penny-posted journal for the hypothetical regulatory reopener.

No Excel, emitter, formula or hidden-reference imports are used here.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext

D = Decimal
ZERO = D(0)
PENNY = D('.01')


def money(value):
    return D(str(value)).quantize(PENNY, rounding=ROUND_HALF_UP)


def gross_up(base, available, cap, rate):
    """Continuous policy solution; separately post tax and loss use once."""
    if base <= 0:
        return ZERO, ZERO, money(-base)
    continuous_use = min(available, cap * base / (1 - rate * (1 - cap)))
    return money(rate * (base - continuous_use) / (1 - rate)), money(continuous_use), ZERO


def simulate(spec):
    with localcontext() as context:
        context.prec = 50
        return _simulate(spec)


def _simulate(spec):
    years = list(spec['years'])
    batches = spec['batches']
    p = spec['parameters']
    annual_inputs = {int(row['year']): row for row in spec['annual_inputs']}
    cohort = {batch['id']: {'cwip_close': ZERO, 'rav_close': ZERO,
        'general_close': ZERO, 'special_close': ZERO, 'structures_close': ZERO,
        'tax_cip_close': ZERO} for batch in batches}
    rav_records, tax_records = defaultdict(list), defaultdict(list)
    claims, losses = {year: ZERO for year in years}, {year: ZERO for year in years}
    claim_records, loss_records = defaultdict(list), defaultdict(list)
    journal, accounts, annual = [], defaultdict(lambda: ZERO), []
    checks = {'journal_balanced': True, 'balance_sheets_balanced': True,
        'cash_reconciled': True, 'rav_reconciled': True, 'claims_reconciled': True,
        'tax_bases_reconciled': True, 'losses_reconciled': True, 'nonnegative_states': True}
    regimes = defaultdict(list)

    def post(year, label, **entries):
        entries = {key: money(value) for key, value in entries.items() if value}
        if sum(entries.values(), ZERO) != 0:
            raise ValueError('Unbalanced independent journal: ' + label)
        for key, value in entries.items():
            accounts[key] += value
        journal.append({'year': year, 'label': label, 'debit_positive_entries': entries})

    for year in years:
        inputs = annual_inputs[year]
        index = D(str(inputs['price_index']))
        rate, carry_rate = D(str(inputs['tax_rate'])), D(str(inputs['claim_carry_rate']))
        old_cwip_nom, old_rav_nom = accounts['cwip'], accounts['rav']
        open_rav = sum((state['rav_close'] for state in cohort.values()), ZERO)
        open_cwip = sum((state['cwip_close'] for state in cohort.values()), ZERO)
        capex_real = commission_real = depreciation = writeoff = ZERO
        capex_nom = commission_nom = depreciation_nom = writeoff_nom = ZERO
        remaining_disallowance = D(str(inputs['disallowance_real']))
        # Public order is FIFO by commission year, with table order as tie-break.
        ordered = sorted(enumerate(batches), key=lambda pair: (int(pair[1]['commission_year']), pair[0]))
        current_rav = {}
        for _, batch in ordered:
            identity = batch['id']; old = cohort[identity]
            cost = D(str(batch['real_cost'])); nominal_cost = D(str(batch['nominal_cost']))
            paid, service = int(batch['paid_year']), int(batch['commission_year'])
            added = cost if year == paid else ZERO
            commissioned = cost if year == service else ZERO
            available_rav = old['rav_close'] + commissioned
            charge = money(cost / int(batch['regulatory_life']))
            dep = min(available_rav, money(charge / 2) if year == service else charge) if year >= service else ZERO
            before_disallowance = available_rav - dep
            disallowed = min(before_disallowance, remaining_disallowance) if year >= service else ZERO
            remaining_disallowance -= disallowed
            closing = before_disallowance - disallowed
            cwip = old['cwip_close'] + added - commissioned
            current_rav[identity] = {'cwip_close': cwip, 'depreciation': dep,
                                    'disallowance': disallowed, 'rav_close': closing}
            rav_records[identity].append(current_rav[identity])
            capex_real += added; commission_real += commissioned
            depreciation += dep; writeoff += disallowed
            capex_nom += nominal_cost if year == paid else ZERO
            commission_nom += money(cost * index) if year == service else ZERO
            depreciation_nom += money(dep * index); writeoff_nom += money(disallowed * index)
        if writeoff:
            regimes['rav_disallowance'].append(year)
        real_return = money((open_rav + sum((row['rav_close'] for row in current_rav.values()), ZERO))
                            / 2 * D(str(inputs['real_wacc'])))
        return_nom = money(real_return * index)
        tax_allowances = transfer_total = ZERO
        tax_open = sum((sum((state[name] for name in ('general_close','special_close','structures_close','tax_cip_close')), ZERO)
                        for state in cohort.values()), ZERO)
        for batch in batches:
            identity = batch['id']; state = cohort[identity]
            nominal_cost = D(str(batch['nominal_cost']))
            service, paid = int(batch['commission_year']), int(batch['paid_year'])
            add = nominal_cost if year == service else ZERO
            pool = batch['tax_pool']
            general_add = add if pool == 'General' else ZERO
            special_add = add if pool == 'Special' else ZERO
            structures_add = add if pool == 'Structures' else ZERO
            transfer = money(state['general_close'] * D(str(inputs['general_transfer_fraction'])))
            general_pre = state['general_close'] - transfer + general_add
            special_pre = state['special_close'] + transfer + special_add
            general_ca = min(general_pre, money((state['general_close'] - transfer + general_add / 2)
                                                * D(str(inputs['general_rate']))))
            special_ca = min(special_pre, money((state['special_close'] + transfer + special_add / 2)
                                                * D(str(inputs['special_rate']))))
            normal = money(nominal_cost / int(p['structures_tax_life']))
            structures_pre = state['structures_close'] + structures_add
            structures_ca = (min(structures_pre, money(normal / 2) if year == service else normal)
                             if year >= service else ZERO)
            row = {'tax_cip_close': nominal_cost if paid <= year < service else ZERO,
                   'general_close': general_pre - general_ca,
                   'special_close': special_pre - special_ca,
                   'structures_close': structures_pre - structures_ca,
                   'capital_allowance': general_ca + special_ca + structures_ca}
            tax_records[identity].append(row)
            tax_allowances += row['capital_allowance']; transfer_total += transfer
            state.update(current_rav[identity]); state.update(row)
        if transfer_total:
            regimes['tax_pool_transfer'].append(year)
        tax_close = sum((sum((state[name] for name in ('general_close','special_close','structures_close','tax_cip_close')), ZERO)
                         for state in cohort.values()), ZERO)
        checks['tax_bases_reconciled'] &= tax_close == tax_open + capex_nom - tax_allowances
        debt_open = -accounts['debt']
        debt_draw = money(capex_nom * D(str(p['gearing'])))
        debt_repayment = min(debt_open + debt_draw, money(depreciation_nom * D(str(p['gearing']))))
        interest = money(debt_open * D(str(inputs['debt_rate'])))
        opening_claims = sum(claims.values(), ZERO)
        interests = {vintage: money(amount * carry_rate) if vintage < year else ZERO
                     for vintage, amount in claims.items()}
        carrying_interest = sum(interests.values(), ZERO)
        opening_losses = sum(losses.values(), ZERO)
        expired = {vintage: amount if year > vintage + int(p['loss_carry_years']) else ZERO
                   for vintage, amount in losses.items()}
        for vintage, amount in expired.items():
            losses[vintage] -= amount
        loss_expired = sum(expired.values(), ZERO)
        if loss_expired:
            regimes['tax_loss_expiry'].append(year)
        available_losses = sum(losses.values(), ZERO)
        base = depreciation_nom + return_nom + carrying_interest - interest - tax_allowances
        tax, loss_used, loss_added = gross_up(base, available_losses, D(str(p['loss_use_cap'])), rate)
        remaining_use = loss_used
        for vintage in years:
            used = min(losses[vintage], remaining_use) if vintage < year else ZERO
            remaining_use -= used; losses[vintage] -= used
            if vintage == year:
                losses[vintage] += loss_added
            loss_records[vintage].append({'expired': expired[vintage], 'used': used, 'close': losses[vintage]})
        if remaining_use:
            raise ValueError('Loss allocation exceeds actual penny balances')
        if loss_used:
            regimes['tax_loss_fifo_use'].append(year)
        if tax:
            regimes['positive_tax_gross_up'].append(year)
        capital_entitlement = depreciation_nom + return_nom + tax
        earned_revenue = capital_entitlement + carrying_interest
        available_cap = D(str(inputs['collection_cap_nominal']))
        receipts = ZERO
        for vintage in years:
            interest_vintage = interests[vintage]
            available = claims[vintage] + interest_vintage
            collected = min(available, available_cap) if year >= vintage + int(p['claim_lag_years']) else ZERO
            available_cap -= collected; receipts += collected
            claims[vintage] = capital_entitlement if vintage == year else available - collected
            claim_records[vintage].append({'interest': interest_vintage, 'collected': collected,
                                          'close': claims[vintage]})
        if available_cap == 0 and receipts > 0:
            regimes['collection_cap_binding'].append(year)
        closing_cwip = sum((state['cwip_close'] for state in cohort.values()), ZERO)
        closing_rav = sum((state['rav_close'] for state in cohort.values()), ZERO)
        nominal_cwip = sum((money(state['cwip_close'] * index) for state in cohort.values()), ZERO)
        nominal_rav = sum((money(state['rav_close'] * index) for state in cohort.values()), ZERO)
        cwip_revaluation = nominal_cwip - old_cwip_nom - capex_nom + commission_nom
        rav_revaluation = nominal_rav - old_rav_nom - commission_nom + depreciation_nom + writeoff_nom
        post(year, 'Capital cash spending', cwip=capex_nom, cash=-capex_nom)
        post(year, 'Commission indexed assets', rav=commission_nom, cwip=-commission_nom)
        post(year, 'Index construction assets', cwip=cwip_revaluation, revaluation=-cwip_revaluation)
        post(year, 'Index regulated assets', rav=rav_revaluation, revaluation=-rav_revaluation)
        post(year, 'Regulatory depreciation', depreciation=depreciation_nom, rav=-depreciation_nom)
        post(year, 'Regulatory disallowance', impairment=writeoff_nom, rav=-writeoff_nom)
        post(year, 'Earn capital and financing revenue', claims=earned_revenue, revenue=-earned_revenue)
        post(year, 'Collect matured claims', cash=receipts, claims=-receipts)
        post(year, 'Draw programme debt', cash=debt_draw, debt=-debt_draw)
        post(year, 'Repay programme debt', debt=debt_repayment, cash=-debt_repayment)
        post(year, 'Pay opening debt interest', interest=interest, cash=-interest)
        post(year, 'Pay current tax', tax=tax, cash=-tax)
        owner_capital, dividend = max(-accounts['cash'], ZERO), max(accounts['cash'], ZERO)
        post(year, 'Contractual owner funding', cash=owner_capital, capital=-owner_capital)
        post(year, 'Distribute cash surplus', retained=dividend, cash=-dividend)
        net_income = earned_revenue - depreciation_nom - writeoff_nom - interest - tax
        post(year, 'Close annual income', revenue=earned_revenue, depreciation=-depreciation_nom,
             impairment=-writeoff_nom, interest=-interest, tax=-tax, retained=-net_income)
        row = {'opening_cwip_real': open_cwip, 'opening_rav_real': open_rav,
            'capital_spend_real': capex_real, 'commissioning_real': commission_real,
            'depreciation_real': depreciation, 'disallowance_real': writeoff,
            'closing_cwip_real': closing_cwip, 'closing_rav_real': closing_rav,
            'real_return': real_return, 'capital_spend_nominal': capex_nom,
            'commissioning_nominal': commission_nom, 'depreciation_nominal': depreciation_nom,
            'disallowance_nominal': writeoff_nom, 'return_nominal': return_nom,
            'closing_cwip_nominal': nominal_cwip, 'closing_rav_nominal': nominal_rav,
            'asset_revaluation': cwip_revaluation + rav_revaluation,
            'tax_capital_allowances': tax_allowances, 'tax_basis_transfer': transfer_total,
            'closing_tax_basis': tax_close, 'debt_open': debt_open, 'debt_draw': debt_draw,
            'debt_repayment': debt_repayment, 'debt_interest': interest, 'debt_close': -accounts['debt'],
            'claims_open': opening_claims, 'claim_carrying_interest': carrying_interest,
            'claims_receipts': receipts, 'claims_close': sum(claims.values(), ZERO),
            'losses_open': opening_losses, 'losses_expired': loss_expired,
            'losses_available': available_losses, 'pre_allowance_taxable_profit': base,
            'losses_used': loss_used, 'losses_created': loss_added, 'losses_close': sum(losses.values(), ZERO),
            'current_tax_allowance': tax, 'capital_entitlement': capital_entitlement,
            'earned_revenue': earned_revenue, 'net_income': net_income,
            'owner_capital': owner_capital, 'owner_distribution': dividend,
            'owner_net_cashflow': dividend - owner_capital, 'cash_close': accounts['cash'],
            'paid_in_capital': -accounts['capital'], 'retained_earnings': -accounts['retained'],
            'revaluation_reserve': -accounts['revaluation']}
        row['total_assets'] = nominal_cwip + nominal_rav + row['claims_close'] + accounts['cash']
        row['total_equity'] = row['paid_in_capital'] + row['retained_earnings'] + row['revaluation_reserve']
        row['balance_check'] = row['total_assets'] - row['debt_close'] - row['total_equity']
        row['cash_check'] = receipts + debt_draw + owner_capital - capex_nom - debt_repayment - interest - tax - dividend
        row['claims_check'] = row['claims_close'] - opening_claims - earned_revenue + receipts
        checks['balance_sheets_balanced'] &= row['balance_check'] == 0
        checks['cash_reconciled'] &= row['cash_check'] == 0 and accounts['cash'] == 0
        checks['rav_reconciled'] &= closing_rav == open_rav + commission_real - depreciation - writeoff
        checks['claims_reconciled'] &= row['claims_check'] == 0
        checks['losses_reconciled'] &= row['losses_close'] == opening_losses - loss_expired - loss_used + loss_added
        checks['nonnegative_states'] &= all(value >= 0 for state in cohort.values() for value in state.values()) and all(value >= 0 for value in claims.values()) and all(value >= 0 for value in losses.values())
        if sum(accounts.values(), ZERO):
            raise ValueError('Independent trial balance is not zero')
        annual.append(row)
    return {'annual': annual, 'rav_batches': dict(rav_records), 'tax_batches': dict(tax_records),
            'claim_vintages': dict(claim_records), 'loss_vintages': dict(loss_records),
            'journal': journal, 'checks': checks, 'observed_regimes': dict(regimes)}
