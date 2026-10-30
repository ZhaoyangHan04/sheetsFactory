"""Audit every emitted lease formula against the independent journal."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import openpyxl

from .contract import month_date, validate_lease_spec


_RATES = {'lease_index_factor', 'lease_retained_exposure', 'annual_discount_rate',
          'lease_monthly_discount_rate', 'event_index_ratio', 'event_new_rate', 'event_retention_fraction'}
_INTEGERS = {'active_flag', 'event_flag', 'event_kind_code', 'measurement_flag',
             'event_rate_changed', 'event_new_end', 'lease_current_end_month'}


def audit_lease_workbook(path, spec, journal, bindings):
    spec = validate_lease_spec(spec)
    formula = openpyxl.load_workbook(path, keep_links=False)
    values = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    try:
        checked, errors = [], []
        owned_sheets = set(bindings['sheets'].values()) | set(bindings['lease_sheets'].values())
        actual_formulas = {(ws.title, c.coordinate) for ws in formula if ws.title in owned_sheets
                           for row in ws for c in row if c.data_type == 'f'}
        declared = {(b['sheet'], b['cell']) for b in bindings['cell_bindings']}
        complete = actual_formulas == declared and len(declared) == len(bindings['cell_bindings'])
        for binding in bindings['cell_bindings']:
            source = binding['source']
            field = ''
            if source[0] == 'lease_monthly':
                _, identity, period, field = source
                expected = journal['lease_monthly'][identity][period - 1][field]
            elif source[0] == 'monthly':
                _, period, field = source
                expected = journal['monthly'][period - 1][field]
            elif source[0] == 'annual':
                _, year, field = source
                expected = journal['annual'][year][field]
            elif source[0] == 'calendar_date':
                expected = month_date(spec['start_date'], source[1]).isoformat()
            elif source[0] == 'calendar_year':
                when = month_date(spec['start_date'], source[1])
                expected = when.year + int(when.month >= 4)
            elif source[0] == 'period':
                expected = source[1]
            else:
                raise ValueError('Unknown independent lease audit binding')
            cell = values[binding['sheet']][binding['cell']]
            actual = cell.value
            try:
                if source[0] == 'calendar_date':
                    observed = actual.date().isoformat() if isinstance(actual, datetime) else actual.isoformat()
                    passed = observed == expected
                else:
                    if isinstance(actual, bool) or actual is None or cell.data_type == 'e':
                        raise ValueError('Missing/nonfinite lease formula cache')
                    observed = Decimal(str(actual))
                    wanted = Decimal(str(expected))
                    if not observed.is_finite():
                        raise ValueError('Nonfinite lease cache')
                    unit = Decimal('0.000000000001') if field in _RATES else Decimal('1') if field in _INTEGERS or source[0] in {'period','calendar_year'} else Decimal('.01')
                    passed = observed.quantize(unit, rounding=ROUND_HALF_UP) == wanted.quantize(unit, rounding=ROUND_HALF_UP)
                reason = None
            except (TypeError, ValueError, ArithmeticError, AttributeError) as exc:
                passed, reason = False, str(exc)
            record = {'address':binding['sheet']+'!'+binding['cell'],'source':source,
                      'expected_independent':str(expected),'actual':str(actual),'passed':passed}
            if reason:
                record['reason'] = reason
            checked.append(record)
            if not passed:
                errors.append(record)
        control_errors = []
        for control in bindings['literal_controls']:
            cell = formula[control['sheet']][control['cell']]
            actual = cell.value.isoformat() if hasattr(cell.value,'isoformat') else cell.value
            if cell.data_type == 'f' or actual != control['value']:
                control_errors.append({'sheet':control['sheet'],'cell':control['cell'],'expected':control['value'],'actual':actual})
        passed = complete and not errors and not control_errors and all(journal['checks'].values())
        return {'passed':passed,'complete_formula_coverage':complete,'formula_count':len(actual_formulas),
                'checked_cells':len(checked),'mismatch_count':len(errors),'control_mismatch_count':len(control_errors),
                'journal_checks':journal['checks'],'mismatches':errors,'control_mismatches':control_errors,
                'cell_checks':checked,'method':'independent_decimal_future_cashflows_vs_actual_excel_caches'}
    finally:
        formula.close()
        values.close()
