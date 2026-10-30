"""Excel lease schedules; formulas never call or embed the Decimal journal."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as L

from .contract import validate_lease_spec


FIELDS = [
    'active_flag', 'event_flag', 'event_kind_code', 'measurement_flag',
    'event_index_ratio', 'event_new_rate', 'event_rate_changed', 'event_new_end', 'event_retention_fraction',
    'lease_index_factor', 'lease_retained_exposure', 'annual_discount_rate', 'lease_monthly_discount_rate',
    'lease_current_end_month', 'lease_rou_open', 'lease_liability_open', 'retained_rou', 'retained_liability',
    'lease_rou_derecognized', 'lease_liability_derecognized', 'lease_pv_at_measurement',
    'lease_remeasurement_delta', 'lease_direct_cost_cash', 'lease_termination_fee_cash',
    'rou_after_measurement', 'liability_after_measurement', 'lease_depreciation_charge',
    'lease_book_depreciation', 'lease_book_interest', 'nominal_contract_payment', 'lease_recurring_rent',
    'lease_cash_rent', 'lease_termination_gain_loss', 'lease_book_expense', 'lease_tax_deduction',
    'lease_taxable_adjustment', 'lease_regulatory_expense', 'lease_rou_close', 'lease_liability_close',
    'lease_tax_rou_basis', 'lease_tax_liability_basis', 'lease_net_temporary_difference', 'lease_journal_bridge',
]
ROWS = {field: index + 3 for index, field in enumerate(FIELDS)}
ANNUAL_FIELDS = [
    'lease_rou_open', 'lease_rou_close', 'lease_liability_open', 'lease_liability_close',
    'lease_recurring_rent', 'lease_direct_cost_cash', 'lease_termination_fee_cash', 'lease_cash_rent',
    'lease_book_depreciation', 'lease_book_interest', 'lease_termination_gain_loss', 'lease_book_expense',
    'lease_tax_deduction', 'lease_taxable_adjustment', 'lease_regulatory_expense',
    'lease_tax_rou_basis', 'lease_tax_liability_basis', 'lease_net_temporary_difference', 'lease_journal_bridge',
]
PARAMETERS = ['lease_id', 'asset_description', 'start_month', 'end_month', 'payment_frequency',
    'monthly_base_rent', 'initial_direct_cost', 'annual_discount_rate', 'fixed_step_rate',
    'fixed_step_months', 'index_floor_factor', 'index_cap_factor']
PARAMETER_ROWS = {key: index + 5 for index, key in enumerate(PARAMETERS)}


def _quoted(name):
    return "'" + name.replace("'", "''") + "'"


def emit_lease_workbook(spec, path=None, *, workbook=None, prefix='Lease '):
    spec = validate_lease_spec(spec)
    if not isinstance(prefix, str) or not prefix or len(prefix) > 17:
        raise ValueError('Short nonempty lease sheet prefix required')
    owned = workbook is None
    book = openpyxl.Workbook() if owned else workbook
    if owned:
        book.remove(book.active)
    names = {key: prefix + key for key in ['Read Me', 'Inputs', 'Events', 'Calendar', 'Monthly', 'Annual']}
    lease_names = {lease['lease_id']: prefix + lease['lease_id'] for lease in spec['leases']}
    if any(name in book.sheetnames or len(name) > 31 for name in [*names.values(), *lease_names.values()]):
        raise ValueError('Lease worksheet names collide or exceed31characters')
    sheets = {key: book.create_sheet(name) for key, name in names.items()}
    for identity, name in lease_names.items():
        book.create_sheet(name)
    bindings = []
    def put(sheet, address, formula, source):
        book[sheet][address] = formula
        bindings.append({'sheet': sheet, 'cell': address, 'source': source})
    instructions = Path(__file__).with_name('CONTRACT.md').read_text().split('\n\n')
    for row, paragraph in enumerate(instructions, 1):
        sheets['Read Me'].cell(row, 1, paragraph.strip())
    inp = sheets['Inputs']
    inp['A1'], inp['B1'] = 'Currency and units', 'nominal absolute GBP'
    inp['A2'], inp['B2'] = 'Global first month', datetime.fromisoformat(spec['start_date'])
    inp['B2'].number_format = 'yyyy-mm-dd'
    inp['A3'], inp['B3'] = 'Global month count', spec['months']
    for field, row in PARAMETER_ROWS.items():
        inp.cell(row, 1, field.replace('_', ' '))
    for column, lease in enumerate(spec['leases'], 3):
        for field, row in PARAMETER_ROWS.items():
            value = lease[field]
            if field not in {'lease_id', 'asset_description', 'start_month', 'end_month', 'payment_frequency', 'fixed_step_months'}:
                value = float(Decimal(value))
            inp.cell(row, column, value)
    events = sheets['Events']
    events.append(['Lease ID', 'Global month', 'Event code 1index 2modify 3partial 4terminate',
                   'Observed index ratio', 'New annual discount rate', 'New end month',
                   'Retained fraction', 'Cash termination fee', 'Discount rate supplied'])
    event_codes = {'index': 1, 'modification': 2, 'partial_termination': 3, 'termination': 4}
    for lease in spec['leases']:
        for event in lease['events']:
            events.append([lease['lease_id'], event['month'], event_codes[event['kind']],
                None if event['index_ratio'] is None else float(Decimal(event['index_ratio'])),
                None if event['annual_discount_rate'] is None else float(Decimal(event['annual_discount_rate'])),
                event['new_end_month'], None if event['retention_fraction'] is None else float(Decimal(event['retention_fraction'])),
                float(Decimal(event['cash_fee'])), int(event['annual_discount_rate'] is not None)])
    last_event = max(events.max_row, 2)
    event_ref = _quoted(names['Events'])
    cal_ref, input_ref = _quoted(names['Calendar']), _quoted(names['Inputs'])
    for period in range(1, 241):
        c = L(period + 2)
        sheets['Calendar'][c + '2'] = period
        put(names['Calendar'], c + '1', f'=EDATE({input_ref}!$B$2,{c}2-1)', ['calendar_date', period])
        put(names['Calendar'], c + '3', f'=YEAR({c}1)+IF(MONTH({c}1)>=4,1,0)', ['calendar_year', period])
        sheets['Calendar'][c + '1'].number_format = 'yyyy-mm-dd'
    sheets['Calendar']['A1'], sheets['Calendar']['A2'], sheets['Calendar']['A3'] = 'Date', 'Global month', 'Fiscal year ending March'
    for parameter_column, lease in enumerate(spec['leases'], 3):
        identity, sn = lease['lease_id'], lease_names[lease['lease_id']]
        pc = L(parameter_column)
        p = {key: f'{input_ref}!${pc}${row}' for key, row in PARAMETER_ROWS.items()}
        ws = book[sn]
        for key, row in ROWS.items():
            ws.cell(row, 1, key.replace('_', ' '))
        for period in range(1, 241):
            col = period + 2
            c, previous = L(col), L(col - 1)
            r = lambda field: c + str(ROWS[field])
            prior = lambda field, first: first if period == 1 else previous + str(ROWS[field])
            sum_event = lambda column: f'SUMIFS({event_ref}!${column}$2:${column}${last_event},{event_ref}!$A$2:$A${last_event},{p["lease_id"]},{event_ref}!$B$2:$B${last_event},{c}$2)'
            formulas = {
                'event_flag': f'=COUNTIFS({event_ref}!$A$2:$A${last_event},{p["lease_id"]},{event_ref}!$B$2:$B${last_event},{c}$2)',
                'event_kind_code': '=' + sum_event('C'), 'event_index_ratio': '=' + sum_event('D'),
                'event_new_rate': '=' + sum_event('E'), 'event_rate_changed': '=' + sum_event('I'),
                'event_new_end': '=' + sum_event('F'),
                'event_retention_fraction': f'=IF({r("event_kind_code")}>2,{sum_event("G")},1)',
                'lease_termination_fee_cash': f'=ROUND({sum_event("H")},2)',
                'lease_index_factor': f'=IF({r("event_index_ratio")}>0,ROUND({prior("lease_index_factor","1")}*MIN({p["index_cap_factor"]},MAX({p["index_floor_factor"]},{r("event_index_ratio")})),12),{prior("lease_index_factor","1")})',
                'lease_retained_exposure': f'=ROUND({prior("lease_retained_exposure","1")}*{r("event_retention_fraction")},12)',
                'annual_discount_rate': f'=IF({r("event_rate_changed")}=1,{r("event_new_rate")},{prior("annual_discount_rate",p["annual_discount_rate"])})',
                'lease_monthly_discount_rate': f'=ROUND((1+{r("annual_discount_rate")})^(1/12)-1,12)',
                'lease_current_end_month': f'=IF({r("event_kind_code")}=4,{c}$2-1,IF({r("event_new_end")}>0,{r("event_new_end")},{prior("lease_current_end_month",p["end_month"])}))',
                'active_flag': f'=IF(AND({c}$2>={p["start_month"]},{c}$2<={r("lease_current_end_month")},{r("lease_retained_exposure")}>0),1,0)',
                'measurement_flag': f'=IF(AND({r("active_flag")}=1,OR({c}$2={p["start_month"]},{r("event_flag")}=1)),1,0)',
                'lease_rou_open': '=' + prior('lease_rou_close', '0'),
                'lease_liability_open': '=' + prior('lease_liability_close', '0'),
                'retained_rou': f'=ROUND({r("lease_rou_open")}*{r("event_retention_fraction")},2)',
                'retained_liability': f'=ROUND({r("lease_liability_open")}*{r("event_retention_fraction")},2)',
                'lease_rou_derecognized': f'=ROUND({r("lease_rou_open")}-{r("retained_rou")},2)',
                'lease_liability_derecognized': f'=ROUND({r("lease_liability_open")}-{r("retained_liability")},2)',
                'lease_direct_cost_cash': f'=IF({c}$2={p["start_month"]},ROUND({p["initial_direct_cost"]},2),0)',
            }
            periods = f'{cal_ref}!$C$2:${L(242)}$2'
            #240months occupyC:IH. Future fixed rent steps are known; future
            #index events do not enter this present-value measurement.
            payment = f'ROUND({p["monthly_base_rent"]}*{r("lease_index_factor")}*{r("lease_retained_exposure")}*ROUND((1+{p["fixed_step_rate"]})^INT(({periods}-{p["start_month"]})/{p["fixed_step_months"]}),12),2)*{p["payment_frequency"]}'
            formulas['lease_pv_at_measurement'] = f'=IF({r("measurement_flag")}=1,ROUND(SUMPRODUCT(({periods}>={c}$2)*({periods}<={r("lease_current_end_month")})*(MOD({periods}-{p["start_month"]}+1,{p["payment_frequency"]})=0)*({payment})/(1+{r("lease_monthly_discount_rate")})^({periods}-{c}$2+1)),2),0)'
            formulas.update({
                'lease_remeasurement_delta': f'=IF({r("measurement_flag")}=1,ROUND({r("lease_pv_at_measurement")}-{r("retained_liability")},2),0)',
                'rou_after_measurement': f'=MAX(0,ROUND({r("retained_rou")}+{r("lease_remeasurement_delta")}+{r("lease_direct_cost_cash")},2))',
                'liability_after_measurement': f'=IF({r("measurement_flag")}=1,{r("lease_pv_at_measurement")},{r("retained_liability")})',
                'lease_depreciation_charge': f'=IF({r("active_flag")}=1,IF({r("measurement_flag")}=1,ROUND({r("rou_after_measurement")}/({r("lease_current_end_month")}-{c}$2+1),2),{prior("lease_depreciation_charge","0")}),0)',
                'lease_book_depreciation': f'=IF({r("active_flag")}=1,IF({c}$2={r("lease_current_end_month")},{r("rou_after_measurement")},MIN({r("rou_after_measurement")},{r("lease_depreciation_charge")})),0)',
                'lease_book_interest': f'=IF({r("active_flag")}=1,ROUND({r("liability_after_measurement")}*{r("lease_monthly_discount_rate")},2),0)',
                'nominal_contract_payment': f'=IF(AND({r("active_flag")}=1,MOD({c}$2-{p["start_month"]}+1,{p["payment_frequency"]})=0),ROUND({p["payment_frequency"]}*ROUND({p["monthly_base_rent"]}*{r("lease_index_factor")}*{r("lease_retained_exposure")}*ROUND((1+{p["fixed_step_rate"]})^INT(({c}$2-{p["start_month"]})/{p["fixed_step_months"]}),12),2),2),0)',
                'lease_recurring_rent': f'=IF(AND({r("active_flag")}=1,{c}$2={r("lease_current_end_month")}),ROUND({r("liability_after_measurement")}+{r("lease_book_interest")},2),{r("nominal_contract_payment")})',
                'lease_cash_rent': f'=ROUND({r("lease_recurring_rent")}+{r("lease_direct_cost_cash")}+{r("lease_termination_fee_cash")},2)',
                'lease_termination_gain_loss': f'=ROUND({r("lease_liability_derecognized")}-{r("lease_rou_derecognized")}-{r("lease_termination_fee_cash")}+MAX(0,-({r("retained_rou")}+{r("lease_remeasurement_delta")}+{r("lease_direct_cost_cash")})),2)',
                'lease_book_expense': f'=ROUND({r("lease_book_depreciation")}+{r("lease_book_interest")}-{r("lease_termination_gain_loss")},2)',
                'lease_tax_deduction': '='+r('lease_cash_rent'),
                'lease_taxable_adjustment': f'=ROUND({r("lease_book_expense")}-{r("lease_tax_deduction")},2)',
                'lease_regulatory_expense': '='+r('lease_cash_rent'),
                'lease_rou_close': f'=ROUND({r("rou_after_measurement")}-{r("lease_book_depreciation")},2)',
                'lease_liability_close': f'=ROUND({r("liability_after_measurement")}+{r("lease_book_interest")}-{r("lease_recurring_rent")},2)',
                'lease_tax_rou_basis': '=0', 'lease_tax_liability_basis': '=0',
                'lease_net_temporary_difference': f'=ROUND({r("lease_rou_close")}-{r("lease_liability_close")},2)',
                'lease_journal_bridge': f'=ROUND({r("lease_rou_close")}-{r("lease_rou_open")}+{r("lease_book_depreciation")}-({r("lease_liability_close")}-{r("lease_liability_open")}+{r("lease_cash_rent")}-{r("lease_book_interest")} )-{r("lease_termination_gain_loss")},2)',
            })
            put(sn, c+'1', f'={cal_ref}!{c}1', ['calendar_date', period])
            put(sn, c+'2', f'={cal_ref}!{c}2', ['period', period])
            ws[c+'1'].number_format = 'yyyy-mm-dd'
            if set(formulas) != set(FIELDS):
                raise ValueError('Uncovered Excel lease field')
            for key, formula in formulas.items():
                put(sn, r(key), formula, ['lease_monthly', identity, period, key])
    aggregate_rows = {key: index + 3 for index, key in enumerate(ANNUAL_FIELDS)}
    annual_refs = {}
    for key, row in aggregate_rows.items():
        sheets['Monthly'].cell(row, 1, key.replace('_', ' '))
        sheets['Annual'].cell(row, 1, key.replace('_', ' '))
    for period in range(1,241):
        c = L(period+2)
        put(names['Monthly'], c+'1', f'={cal_ref}!{c}1', ['calendar_date',period])
        put(names['Monthly'], c+'2', f'={cal_ref}!{c}2', ['period',period])
        sheets['Monthly'][c+'1'].number_format = 'yyyy-mm-dd'
        for key,row in aggregate_rows.items():
            refs = ','.join(f'{_quoted(sn)}!{c}{ROWS[key]}' for sn in lease_names.values())
            put(names['Monthly'], c+str(row), f'=ROUND(SUM({refs}),2)', ['monthly',period,key])
    first_year = date.fromisoformat(spec['start_date']).year+1
    monthly_ref = _quoted(names['Monthly'])
    for year_index in range(20):
        year, c = first_year+year_index, L(year_index+3)
        sheets['Annual'][c+'2'] = year
        annual_refs[year] = {}
        left,right = L(year_index*12+3),L(year_index*12+14)
        for key,row in aggregate_rows.items():
            if key.endswith('_open'):
                formula = f'={monthly_ref}!{left}{row}'
            elif key.endswith('_close') or key in {'lease_tax_rou_basis','lease_tax_liability_basis','lease_net_temporary_difference'}:
                formula = f'={monthly_ref}!{right}{row}'
            else:
                formula = f'=ROUND(SUM({monthly_ref}!{left}{row}:{right}{row}),2)'
            put(names['Annual'],c+str(row),formula,['annual',year,key])
            annual_refs[year][key] = f'{_quoted(names["Annual"])}!{c}{row}'
    for name in [*names.values(),*lease_names.values()]:
        ws = book[name]
        ws.freeze_panes='C3'
        ws.column_dimensions['A'].width=43
        ws.column_dimensions['B'].width=14
        for row in ws:
            for cell in row:
                if cell.row==1 or cell.column==1:
                    cell.font=Font(bold=True,color='17365D')
                if cell.data_type=='f':
                    cell.number_format = ('yyyy-mm-dd' if cell.row == 1 and cell.column >= 3
                                          else '#,##0.00;[Red](#,##0.00);–')
    sheets['Read Me'].column_dimensions['A'].width=115
    for row in sheets['Read Me']:
        row[0].alignment=Alignment(wrap_text=True,vertical='top')
        sheets['Read Me'].row_dimensions[row[0].row].height=95
    if path is not None:
        book.save(path)
    controls = []
    for name in [*names.values(), *lease_names.values()]:
        for row in book[name]:
            for cell in row:
                if cell.value is not None and cell.data_type != 'f':
                    value = cell.value.isoformat() if hasattr(cell.value, 'isoformat') else cell.value
                    controls.append({'sheet':name,'cell':cell.coordinate,'value':value})
    result={'sheets':names,'lease_sheets':lease_names,'cell_bindings':bindings,'literal_controls':controls,
            'annual_refs':annual_refs,'monthly_rows':aggregate_rows,'lease_rows':ROWS,
            'units':'nominal absolute GBP','formula_count':len(bindings)}
    if owned:
        book.close()
    return result
