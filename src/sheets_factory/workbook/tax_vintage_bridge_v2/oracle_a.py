"""Independent Decimal vintage journal A; no workbook, B or cache inputs."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
from pathlib import Path

from . import spec
from ..associate_bridge_v1 import oracle_a as bridge_a
from ..operating_reports_200 import schema as vocabulary

BRIDGE_A_SHA = 'c297fca4d88a7b39ac21bf9a83746675ebc32aec5c2da82dc3ddab51ff39080c'
ZERO = Decimal(0)


def _amount(encoded):
    if encoded.get('kind') != 'rational':
        raise ValueError('Expected a finite monetary amount')
    value = Fraction(encoded['value'])
    amount = Decimal(value.numerator) / Decimal(value.denominator)
    if Fraction(amount) != value:
        raise ValueError('Decimal precision cannot represent this monetary input exactly')
    return amount


def _rational(value):
    return {'kind': 'rational', 'value': str(Fraction(value))}


def _display(value):
    q = Fraction(value)
    whole, remainder = divmod(abs(q.numerator)*100, q.denominator)
    whole += int(2*remainder >= q.denominator)
    return ('-' if q < 0 and whole else '') + f'{whole//100}.{whole%100:02d}'


def solve(public):
    public = spec.validate(public)
    if hashlib.sha256(Path(bridge_a.__file__).read_bytes()).hexdigest() != BRIDGE_A_SHA:
        raise ValueError('The retained independent bridge oracle A changed')
    baseline = bridge_a.solve(public['bridge'])
    output = deepcopy(baseline)
    output.update(kind=spec.RESULT_KIND, specification_sha256=spec.canonical_sha256(public))
    base = public['bridge']['base']
    old_fields = vocabulary.FLOWS + vocabulary.STOCKS
    all_fields = old_fields + spec.NEW_FLOWS + spec.NEW_STOCKS
    checks = {name: {} for name in ('opening_balance_residuals', 'quarter_balance_residuals',
              'cash_bridge_residuals', 'investment_bridge_residuals', 'retained_earnings_bridge_residuals',
              'tax_payable_bridge_residuals', 'ordinary_loss_bridge_residuals', 'investment_loss_bridge_residuals')}
    states, openings, investment_movements, opening_losses = {}, {}, {}, {}
    with localcontext() as context:
        context.prec = 250

        def prior(identity, period, field):
            return _amount(baseline['economic_exact_values'][f'{identity}/{period}/{field}'])

        def save(identity, period, field, value, money_scale, rate_scale=Fraction(1)):
            key = f'{identity}/{period}/{field}'
            exact = Fraction(value)
            raw = exact / (rate_scale if field.endswith('_percent') else money_scale)
            output['economic_exact_values'][key] = _rational(exact)
            output['raw_cell_exact_values'][key] = _rational(raw)
            output['typed_2dp_values'][key] = {'type': 'number', 'value': _display(raw)}

        def audit(identity, period, row, previous, movement, loss_before):
            key = identity + '/' + period
            checks['quarter_balance_residuals'][key] = row['total_assets']-row['total_liabilities_equity']
            checks['cash_bridge_residuals'][key] = row['closing_cash']-previous[0]-row['operating_cash_flow']+row['dividend']
            checks['investment_bridge_residuals'][key] = row['closing_investment']-previous[1]-movement
            checks['retained_earnings_bridge_residuals'][key] = row['closing_retained_earnings']-previous[2]-row['net_income']+row['dividend']
            checks['tax_payable_bridge_residuals'][key] = row['tax_payable_close']-previous[3]-row['current_tax']+row['cash_tax_paid']
            for pool in spec.POOLS:
                checks[pool+'_loss_bridge_residuals'][key] = (row[f'loss_{pool}_close']-loss_before[pool]
                    +row[f'loss_{pool}_expired']+row[f'loss_{pool}_used']-row[f'loss_{pool}_created'])

        for entity in base['entities']:
            identity = entity['id']
            scale = spec.MONEY_SCALES[entity['money_unit']]
            rate_scale = {'fraction': Fraction(100), 'percent_units': Fraction(1), 'basis_points': Fraction(1, 100)}[entity['rate_unit']]
            rate = Decimal(entity['parent_tax_rate'])*{'fraction': Decimal(1), 'percent_units': Decimal('.01'), 'basis_points': Decimal('.0001')}[entity['rate_unit']]
            bridge_policy = public['bridge']['policies'][identity]
            policy = public['tax_policies'][identity]
            begin = {k: Decimal(v)*scale for k, v in entity['opening'].items()}
            openings[identity] = begin
            checks['opening_balance_residuals'][identity] = begin['cash']+begin['investment']-begin['debt']-begin['capital']-begin['retained_earnings']
            lots = {lot['lot_id']: {'origin': lot['origin_index'], 'expiry': lot['last_eligible_index'],
                    **{pool: Decimal(lot[pool])*scale for pool in spec.POOLS}} for lot in policy['opening_lots']}
            lots.update({f'C{i:02d}': {'origin': i, 'expiry': None, **{pool: ZERO for pool in spec.POOLS}} for i in range(12)})
            opening_losses[identity] = {pool: sum((lot[pool] for lot in lots.values()), ZERO) for pool in spec.POOLS}
            due, payable, rows, movements = {}, ZERO, [], []
            for index, period in enumerate(spec.QUARTERS):
                term = max((t for t in policy['terms'] if t['effective_index'] <= index), key=lambda t: t['effective_index'])
                row = {field: prior(identity, period, field) for field in old_fields}
                receipt = Decimal(bridge_policy['cash_receipts'][period])*scale
                dividend_receipt = receipt if bridge_policy['receipt_kind'][period] == 'dividend' else ZERO
                investment_base = {'exempt': ZERO, 'recognized': row['associate_income'], 'cash_dividends': dividend_receipt}[bridge_policy['tax_class']]
                before = {'ordinary': row['pretax_before_associate'], 'investment': investment_base}
                lost_before = {pool: sum((lot[pool] for lot in lots.values()), ZERO) for pool in spec.POOLS}
                used_by_lot = {lot: {pool: ZERO for pool in spec.POOLS} for lot in spec.LOT_IDS}
                for pool in spec.POOLS:
                    expired = ZERO
                    for lot in lots.values():
                        if lot['expiry'] is not None and lot['expiry'] < index:
                            expired += lot[pool]
                            lot[pool] = ZERO
                    capacity = max(ZERO, before[pool])*term[pool+'_cap_bp']/10000
                    remaining, used = capacity, ZERO
                    for lot_id in sorted(lots, key=lambda name: (lots[name]['origin'], name)):
                        lot = lots[lot_id]
                        if lot['origin'] >= index or lot['expiry'] is None or lot['expiry'] < index:
                            continue
                        amount = min(lot[pool], remaining)
                        lot[pool] -= amount
                        remaining -= amount
                        used += amount
                        used_by_lot[lot_id][pool] = amount
                    created = max(ZERO, -before[pool])
                    lots[f'C{index:02d}'][pool] = created
                    row.update({f'tax_{pool}_before_losses': before[pool],
                                f'tax_{pool}_after_losses': max(ZERO, before[pool]-used),
                                f'loss_{pool}_expired': expired, f'loss_{pool}_used': used,
                                f'loss_{pool}_created': created,
                                f'loss_{pool}_close': sum((lot[pool] for lot in lots.values()), ZERO)})
                lots[f'C{index:02d}']['expiry'] = index+term['carry_quarters']
                tax = (row['tax_ordinary_after_losses']+row['tax_investment_after_losses'])*rate
                due_index = index+term['cash_tax_lag']
                due[due_index] = due.get(due_index, ZERO)+tax
                paid = due.get(index, ZERO)
                payable += tax-paid
                if payable < 0:
                    raise ArithmeticError('Cash settlement exceeds assessed unpaid tax')
                core = row['pretax_before_associate']-tax
                row.update(current_tax=tax, core_net_income=core, net_income=core+row['associate_income'],
                           cash_tax_paid=paid, tax_payable_close=payable,
                           operating_cash_flow=core+receipt+tax-paid, dividend=ZERO)
                for lot_id in spec.LOT_IDS:
                    for pool in spec.POOLS:
                        row[f'tax_lot_{lot_id}_{pool}_used'] = used_by_lot[lot_id][pool]
                        row[f'tax_lot_{lot_id}_{pool}_close'] = lots[lot_id][pool]
                previous_investment = begin['investment'] if index == 0 else prior(identity, spec.QUARTERS[index-1], 'closing_investment')
                movement = prior(identity, period, 'closing_investment')-previous_investment
                rows.append(row)
                movements.append((movement, lost_before))
            annual_income = sum((row['net_income'] for row in rows[8:]), ZERO)
            eligible = baseline['typed_2dp_values'][f'{identity}/FY2027/distribution_eligible']['value'] is True
            cash, investment, earnings, payable_before = begin['cash'], begin['investment'], begin['retained_earnings'], ZERO
            for index, (period, row, (movement, lost_before)) in enumerate(zip(spec.QUARTERS, rows, movements)):
                distribution = max(ZERO, annual_income)/5 if index == 11 and eligible else ZERO
                previous = cash, investment, earnings, payable_before
                cash += row['operating_cash_flow']-distribution
                investment += movement
                earnings += row['net_income']-distribution
                payable_before = row['tax_payable_close']
                if cash < 0 or investment < 0:
                    raise ValueError('The supplied cash or investment balance is exhausted')
                row.update(dividend=distribution, closing_cash=cash, closing_investment=investment,
                           closing_retained_earnings=earnings, total_assets=cash+investment,
                           total_liabilities_equity=begin['debt']+begin['capital']+earnings+payable_before)
                for field in all_fields+spec.LOT_FIELDS:
                    save(identity, period, field, row[field], scale, rate_scale)
                save(identity, period, 'net_margin_percent', Fraction(row['net_income'])*100/Fraction(row['revenue']), scale, rate_scale)
                save(identity, period, 'reported_current_tax', row['current_tax']*(-1 if entity['statement_sign'] == 'signed_contributions' else 1), scale, rate_scale)
                audit(identity, period, row, previous, movement, lost_before)
            states[identity] = rows
            investment_movements[identity] = [m[0] for m in movements]
            for year in spec.YEARS:
                block = rows[(year-2025)*4:(year-2024)*4]
                for field in all_fields:
                    amount = sum((r[field] for r in block), ZERO) if field in vocabulary.FLOWS+spec.NEW_FLOWS else block[-1][field]
                    save(identity, f'FY{year}', field, amount, scale, rate_scale)
                save(identity, f'FY{year}', 'net_margin_percent', Fraction(sum((r['net_income'] for r in block), ZERO))*100/Fraction(sum((r['revenue'] for r in block), ZERO)), scale, rate_scale)
        membership = {'DIV_'+d.upper(): [e['id'] for e in base['entities'] if e['division'] == d] for d in base['divisions']}
        membership['PORTFOLIO'] = [e['id'] for e in base['entities']]
        for identity, members in membership.items():
            begin = {k: sum((openings[e][k] for e in members), ZERO) for k in base['entities'][0]['opening']}
            checks['opening_balance_residuals'][identity] = begin['cash']+begin['investment']-begin['debt']-begin['capital']-begin['retained_earnings']
            previous = begin['cash'], begin['investment'], begin['retained_earnings'], ZERO
            loss_before = {pool: sum((opening_losses[e][pool] for e in members), ZERO) for pool in spec.POOLS}
            rows = []
            for index, period in enumerate(spec.QUARTERS):
                row = {field: sum((states[e][index][field] for e in members), ZERO) for field in all_fields}
                rows.append(row)
                for field in all_fields:
                    save(identity, period, field, row[field], 1)
                save(identity, period, 'net_margin_percent', Fraction(row['net_income'])*100/Fraction(row['revenue']), 1)
                audit(identity, period, row, previous, sum((investment_movements[e][index] for e in members), ZERO), loss_before)
                previous = row['closing_cash'], row['closing_investment'], row['closing_retained_earnings'], row['tax_payable_close']
                loss_before = {pool: row[f'loss_{pool}_close'] for pool in spec.POOLS}
            for year in spec.YEARS:
                block = rows[(year-2025)*4:(year-2024)*4]
                for field in all_fields:
                    amount = sum((r[field] for r in block), ZERO) if field in vocabulary.FLOWS+spec.NEW_FLOWS else block[-1][field]
                    save(identity, f'FY{year}', field, amount, 1)
                save(identity, f'FY{year}', 'net_margin_percent', Fraction(sum((r['net_income'] for r in block), ZERO))*100/Fraction(sum((r['revenue'] for r in block), ZERO)), 1)
        output['reconciliation_checks'] = {'passed': all(v == 0 for values in checks.values() for v in values.values()),
            **{name: {key: str(Fraction(value)) for key, value in values.items()} for name, values in checks.items()},
            'group_membership': membership}
    if not output['reconciliation_checks']['passed']:
        raise ArithmeticError('The complete vintage and financial bridges do not reconcile')
    expected = set(dict(spec.points(public)))
    if any(set(output[name]) != expected for name in ('economic_exact_values', 'raw_cell_exact_values', 'typed_2dp_values')):
        raise ValueError('The complete tax-vintage output inventory is incomplete')
    return output
