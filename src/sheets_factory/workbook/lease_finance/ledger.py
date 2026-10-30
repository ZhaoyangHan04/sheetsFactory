"""Independent Decimal lease journal using explicit future-payment valuation."""
from decimal import Decimal, ROUND_HALF_UP, localcontext

from .contract import decimal, month_date, validate_lease_spec

ZERO, ONE = Decimal(0), Decimal(1)
MONEY, RATE = Decimal('.01'), Decimal('.000000000001')


def q(value):
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def qr(value):
    return value.quantize(RATE, rounding=ROUND_HALF_UP)


def _payments(lease, period, end, index, retained):
    """Only current index/exposure and already contracted fixed steps enterPV."""
    start, frequency = lease['start_month'], lease['payment_frequency']
    base = decimal(lease['monthly_base_rent'], 'base rent')
    step = decimal(lease['fixed_step_rate'], 'fixed step')
    for future in range(period, end + 1):
        if (future - start + 1) % frequency == 0:
            step_count = (future - start) // lease['fixed_step_months']
            monthly = q(base * index * retained * qr((ONE + step) ** step_count))
            yield future, q(monthly * frequency)


def _one(lease, spec):
    events = {event['month']: event for event in lease['events']}
    end, start = lease['end_month'], lease['start_month']
    rate = decimal(lease['annual_discount_rate'], 'discount rate')
    index, retained = ONE, ONE
    liability, rou, charge = ZERO, ZERO, ZERO
    rows = []
    for period in range(1, 241):
        opening_l, opening_r = liability, rou
        event = events.get(period)
        commenced = period == start
        removed_l = removed_r = fee = direct = gain = delta = pv = ZERO
        measured_l, adjusted_r = opening_l, opening_r
        if event:
            fee = q(decimal(event['cash_fee'], 'termination fee'))
            fraction = event['retention_fraction']
            if fraction is not None:
                fraction = decimal(fraction, 'retained exposure')
                measured_l, adjusted_r = q(opening_l * fraction), q(opening_r * fraction)
                removed_l, removed_r = opening_l - measured_l, opening_r - adjusted_r
                retained = qr(retained * fraction)
                gain = q(removed_l - removed_r - fee)
            if event['index_ratio'] is not None:
                ratio = decimal(event['index_ratio'], 'index ratio')
                ratio = min(decimal(lease['index_cap_factor'], 'cap'), max(
                    decimal(lease['index_floor_factor'], 'floor'), ratio))
                index = qr(index * ratio)
            if event['annual_discount_rate'] is not None:
                rate = decimal(event['annual_discount_rate'], 'new discount rate')
            if event['new_end_month'] is not None:
                end = event['new_end_month']
            if event['kind'] == 'termination':
                end = period - 1
        active = start <= period <= end and retained > 0
        monthly_rate = qr((ONE + rate) ** (ONE / Decimal(12)) - ONE)
        pre_r, pre_l = adjusted_r, measured_l
        measurement = active and (commenced or event is not None)
        if measurement:
            cashflows = list(_payments(lease, period, end, index, retained))
            pv = q(sum((amount / (ONE + monthly_rate) ** (future - period + 1)
                        for future, amount in cashflows), ZERO))
            delta = pv - measured_l
            measured_l = pv
            if commenced:
                direct = q(decimal(lease['initial_direct_cost'], 'initial direct costs'))
            raw_rou = adjusted_r + delta + direct
            if raw_rou < 0:
                gain += -raw_rou
            adjusted_r = max(ZERO, q(raw_rou))
            charge = q(adjusted_r / Decimal(end - period + 1))
        interest = q(measured_l * monthly_rate) if active else ZERO
        recurring = nominal = ZERO
        if active and (period - start + 1) % lease['payment_frequency'] == 0:
            recurring = next(amount for future, amount in _payments(lease, period, period, index, retained))
            nominal = recurring
            if period == end:
                recurring = q(measured_l + interest)
        depreciation = (adjusted_r if period == end else min(adjusted_r, charge)) if active else ZERO
        liability = q(measured_l + interest - recurring)
        rou = q(adjusted_r - depreciation)
        cash = q(recurring + direct + fee)
        gain = q(gain)
        expense = q(interest + depreciation - gain)
        bridge = q(rou - opening_r + depreciation -
                   (liability - opening_l + cash - interest) - gain)
        when = month_date(spec['start_date'], period)
        rows.append({'period': period, 'date': when.isoformat(),
            'fiscal_year': when.year + int(when.month >= 4),
            'lease_rou_open': opening_r, 'lease_liability_open': opening_l,
            'lease_recurring_rent': recurring, 'lease_direct_cost_cash': direct,
            'lease_termination_fee_cash': fee, 'lease_cash_rent': cash,
            'lease_book_depreciation': q(depreciation), 'lease_book_interest': interest,
            'lease_termination_gain_loss': gain, 'lease_book_expense': expense,
            'lease_tax_deduction': cash, 'lease_taxable_adjustment': q(expense - cash),
            'lease_regulatory_expense': cash,
            'lease_rou_close': rou, 'lease_liability_close': liability,
            'lease_remeasurement_delta': q(delta), 'lease_pv_at_measurement': pv,
            'lease_liability_derecognized': q(removed_l), 'lease_rou_derecognized': q(removed_r),
            'lease_monthly_discount_rate': monthly_rate, 'lease_index_factor': index,
            'lease_retained_exposure': retained, 'lease_current_end_month': end,
            'lease_depreciation_charge': charge if active else ZERO,
            'lease_tax_rou_basis': ZERO, 'lease_tax_liability_basis': ZERO,
            'lease_net_temporary_difference': q(rou - liability),
            'lease_journal_bridge': bridge,
            'active_flag': int(active), 'measurement_flag': int(measurement),
            'event_flag': int(event is not None),
            'event_kind_code': {'index': 1, 'modification': 2, 'partial_termination': 3, 'termination': 4}.get(event['kind'], 0) if event else 0,
            'annual_discount_rate': rate, 'retained_rou': pre_r, 'retained_liability': pre_l,
            'rou_after_measurement': adjusted_r, 'liability_after_measurement': measured_l,
            'nominal_contract_payment': nominal,
            'event_index_ratio': decimal(event['index_ratio'], 'event ratio') if event and event['index_ratio'] is not None else ZERO,
            'event_new_rate': decimal(event['annual_discount_rate'], 'event rate') if event and event['annual_discount_rate'] is not None else ZERO,
            'event_rate_changed': int(event is not None and event['annual_discount_rate'] is not None),
            'event_new_end': event['new_end_month'] if event and event['new_end_month'] is not None else 0,
            'event_retention_fraction': decimal(event['retention_fraction'], 'event retention') if event and event['retention_fraction'] is not None else ONE})
    return rows


def simulate_lease(spec):
    spec = validate_lease_spec(spec)
    with localcontext() as context:
        context.prec = 60
        by_lease = {lease['lease_id']: _one(lease, spec) for lease in spec['leases']}
        financial = [key for key in next(iter(by_lease.values()))[0] if key.startswith('lease_')
                     and key not in {'lease_monthly_discount_rate', 'lease_index_factor',
                                     'lease_retained_exposure', 'lease_current_end_month'}]
        monthly = []
        for index in range(240):
            first = next(iter(by_lease.values()))[index]
            monthly.append({**{key: first[key] for key in ('period', 'date', 'fiscal_year')},
                **{key: q(sum((rows[index][key] for rows in by_lease.values()), ZERO)) for key in financial}})
        annual = {}
        for offset in range(0, 240, 12):
            periods = monthly[offset:offset + 12]
            values = {}
            for key in financial:
                if key.endswith('_open'):
                    amount = periods[0][key]
                elif key.endswith('_close') or key in {'lease_tax_rou_basis', 'lease_tax_liability_basis',
                                                        'lease_net_temporary_difference'}:
                    amount = periods[-1][key]
                else:
                    amount = sum((row[key] for row in periods), ZERO)
                values[key] = q(amount)
            annual[periods[-1]['fiscal_year']] = values
        checks = {'monthly_journals_balanced': all(row['lease_journal_bridge'] == 0 for rows in by_lease.values() for row in rows),
            'nonnegative_assets_liabilities': all(row['lease_rou_close'] >= 0 and row['lease_liability_close'] >= 0
                                                 for rows in by_lease.values() for row in rows),
            'all_leases_settled_by_horizon': all(rows[-1]['lease_rou_close'] == 0 and rows[-1]['lease_liability_close'] == 0
                                                for rows in by_lease.values()),
            'annual_journals_balanced': all(q(a['lease_rou_close'] - a['lease_rou_open'] + a['lease_book_depreciation']
                - (a['lease_liability_close'] - a['lease_liability_open'] + a['lease_cash_rent'] - a['lease_book_interest'])
                - a['lease_termination_gain_loss']) == 0 for a in annual.values())}
        return {'monthly': monthly, 'lease_monthly': by_lease, 'annual': annual, 'checks': checks,
                'units': 'nominal absolute GBP', 'start_date': spec['start_date'], 'months': 240}
