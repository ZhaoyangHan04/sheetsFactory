"""Validate explicit hypothetical lease terms; no economic defaults."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path


SPEC_FIELDS = {'schema_version', 'start_date', 'months', 'currency', 'leases'}
LEASE_FIELDS = {'lease_id', 'asset_description', 'start_month', 'end_month', 'payment_frequency',
    'monthly_base_rent', 'initial_direct_cost', 'annual_discount_rate', 'fixed_step_rate',
    'fixed_step_months', 'index_floor_factor', 'index_cap_factor', 'events'}
EVENT_FIELDS = {'month', 'kind', 'index_ratio', 'annual_discount_rate', 'new_end_month',
    'retention_fraction', 'cash_fee'}


def decimal(value, label):
    if isinstance(value, bool) or value is None:
        raise ValueError('Explicit finite numeric input required: ' + label)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid numeric input: ' + label) from None
    if not result.is_finite():
        raise ValueError('Nonfinite input: ' + label)
    return result


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Integer input outside contract bounds: ' + label)
    return value


def validate_lease_spec(spec):
    if not isinstance(spec, dict) or set(spec) != SPEC_FIELDS or spec['schema_version'] != 1:
        raise ValueError('Explicit version1 lease schema required')
    try:
        start = date.fromisoformat(spec['start_date'])
    except (ValueError, TypeError):
        raise ValueError('Explicit ISO lease start_date required') from None
    if start.month != 4 or start.day != 1 or spec['months'] != 240 or spec['currency'] != 'GBP_nominal':
        raise ValueError('This contract requires240months from1April, nominalGBP')
    if not isinstance(spec['leases'], list) or not 1 <= len(spec['leases']) <= 5:
        raise ValueError('One to five explicit lease contracts required')
    ids = set()
    for lease in spec['leases']:
        if not isinstance(lease, dict) or set(lease) != LEASE_FIELDS:
            raise ValueError('Every lease field must be explicit')
        identity = lease['lease_id']
        if not isinstance(identity, str) or not identity.isalnum() or len(identity) > 12 or identity in ids:
            raise ValueError('Safe unique lease_id required')
        ids.add(identity)
        if not isinstance(lease['asset_description'], str) or not lease['asset_description'].strip():
            raise ValueError('Public asset description required')
        start_month = integer(lease['start_month'], identity + '.start_month', 1, 240)
        end = integer(lease['end_month'], identity + '.end_month', start_month, 240)
        frequency = integer(lease['payment_frequency'], identity + '.frequency', 1, 12)
        if 12 % frequency or (end - start_month + 1) % frequency:
            raise ValueError('Lease term must end on its contractual payment cycle')
        interval = integer(lease['fixed_step_months'], identity + '.step_interval', 1, 240)
        if interval % frequency:
            raise ValueError('Fixed rent steps must start at a payment-cycle boundary')
        for key in ('monthly_base_rent', 'initial_direct_cost', 'annual_discount_rate', 'fixed_step_rate'):
            if decimal(lease[key], identity + '.' + key) < 0:
                raise ValueError('Lease monetary amounts and rates must be nonnegative')
        if decimal(lease['monthly_base_rent'], identity + '.rent') <= 0:
            raise ValueError('Positive contractual base rent required')
        floor, cap = [decimal(lease[k], identity + '.' + k) for k in ('index_floor_factor', 'index_cap_factor')]
        if not 0 < floor <= 1 <= cap:
            raise ValueError('Index floor/cap must straddle one')
        if not isinstance(lease['events'], list):
            raise ValueError('Explicit lease event list required')
        previous = start_month
        for event in lease['events']:
            if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
                raise ValueError('Every event field must be explicit, null means unchanged')
            month = integer(event['month'], identity + '.event_month', previous + 1, end)
            if (month - start_month) % frequency:
                raise ValueError('Lease events must occur at payment-cycle starts')
            kind = event['kind']
            if kind not in {'index', 'modification', 'partial_termination', 'termination'}:
                raise ValueError('Unsupported public lease event')
            fee = decimal(event['cash_fee'], identity + '.event_fee')
            if fee < 0 or (kind in {'index', 'modification'} and fee != 0):
                raise ValueError('Cash fees are nonnegative termination expenses only')
            if event['index_ratio'] is not None and decimal(event['index_ratio'], identity + '.index_ratio') <= 0:
                raise ValueError('Positive observed index ratio required')
            if kind == 'index' and event['index_ratio'] is None:
                raise ValueError('Index event requires its observed ratio')
            if event['annual_discount_rate'] is not None and decimal(event['annual_discount_rate'], identity + '.new_rate') < 0:
                raise ValueError('New discount rate must be nonnegative')
            if kind == 'modification' and event['annual_discount_rate'] is None and event['new_end_month'] is None:
                raise ValueError('Modification must change the remaining term or rate')
            if kind == 'partial_termination':
                fraction = decimal(event['retention_fraction'], identity + '.retention')
                if not 0 < fraction < 1:
                    raise ValueError('Partial termination needs a retained fraction strictly between0and1')
            elif kind == 'termination':
                if decimal(event['retention_fraction'], identity + '.retention') != 0:
                    raise ValueError('Full termination retains zero')
            elif event['retention_fraction'] is not None:
                raise ValueError('Only termination events change retained exposure')
            if event['new_end_month'] is not None:
                end = integer(event['new_end_month'], identity + '.new_end', month, 240)
                if (end - start_month + 1) % frequency:
                    raise ValueError('Modified term must preserve the payment-cycle boundary')
            if kind == 'termination':
                end = month - 1
            previous = month
    return deepcopy(spec)


def load_lease_spec(path):
    return validate_lease_spec(json.loads(Path(path).read_text()))


def month_date(start, period):
    start = date.fromisoformat(start) if isinstance(start, str) else start
    offset = start.month - 1 + period - 1
    return date(start.year + offset // 12, offset % 12 + 1, 1)
