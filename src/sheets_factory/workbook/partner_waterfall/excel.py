"""Independent formula implementation. It does not call the Decimal allocator."""
from datetime import date
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter as letter
from .contract import PUBLIC_RULES, FINANCIAL_FIELDS
from .schema import SHEETS, INPUT_FIELDS, FIELDS, INTEGER_FIELDS, RATE_FIELDS, row


def emit_waterfall(book, policy, parent_refs):
    years=policy['years']
    if years!=list(range(2024,2044)) or set(parent_refs)!=set(years):
        raise ValueError('Partner formulas require all twenty reporting years')
    if any(sn in book.sheetnames for sn in SHEETS.values()):
        raise ValueError('Partner sheet names already exist')
    sheets={key:book.create_sheet(sn) for key,sn in SHEETS.items()};bindings=[]
    for key,sheet in sheets.items():
        sheet['A1']=SHEETS[key];sheet['A1'].font=Font(size=14,bold=True)
        sheet.column_dimensions['A'].width=35;sheet.freeze_panes='C3'
    for i,text in enumerate(PUBLIC_RULES,3):sheets['brief'].cell(i,1,text)
    sheets['brief'].column_dimensions['A'].width=120
    params={}
    for i,field in enumerate(INPUT_FIELDS,3):
        sheets['inputs'].cell(i,1,field)
        value=date.fromisoformat(policy[field]) if field=='opening_date' else float(policy[field])
        sheets['inputs'].cell(i,2,value)
        if field=='opening_date':sheets['inputs'].cell(i,2).number_format='yyyy-mm-dd'
        params[field]=f"'{SHEETS['inputs']}'!$B${i}"
    ws=sheets['waterfall'];ws['B2']=date.fromisoformat(policy['opening_date']);ws['B2'].number_format='yyyy-mm-dd'
    for field in FIELDS:ws.cell(row(field),1,field)
    def put(col,field,formula,index,section='partner_waterfall',kind=None):
        kind=kind or ('nullable_rate' if field=='lp_xirr' else ('nullable_integer' if field=='flip_effective_year'
             else ('integer' if field in INTEGER_FIELDS else ('rate' if field in RATE_FIELDS else ('npv' if field=='hurdle_xnpv' else 'money')))))
        if kind=='money':formula=f'ROUND(({formula}),2)'
        cell=ws.cell(row(field),col,'='+formula)
        cell.number_format='0.000000000000' if 'rate' in kind else ('0' if 'integer' in kind else '#,##0.00;[Red](#,##0.00)')
        bindings.append({'sheet':SHEETS['waterfall'],'cell':cell.coordinate,'section':section,
            'index':index,'field':field,'kind':kind,'target_eligible':field in FINANCIAL_FIELDS})
    put(2,'lp_net_cashflow',f'-ROUND({params["opening_capital"]}*{params["lp_capital_fraction"]},2)',0,'partner_opening')
    put(2,'gp_net_cashflow',f'-({params["opening_capital"]}-ROUND({params["opening_capital"]}*{params["lp_capital_fraction"]},2))',0,'partner_opening')
    for yi,year in enumerate(years):
        ci=yi+3;col=letter(ci);prev=letter(ci-1)
        ws.cell(2,ci,date(year,3,31)).number_format='yyyy-mm-dd'
        ref=lambda f:f'{col}{row(f)}'
        old=lambda f:f'{prev}{row(f)}'
        prior=lambda f:old(f) if yi else '0'
        lp_after=f'({ref("lp_capital_open")}+{ref("lp_contribution")})'
        gp_after=f'({ref("gp_capital_open")}+{ref("gp_contribution")})'
        totalcap=f'({lp_after}+{gp_after})'
        roc=f'MIN({ref("distributable_cash")}-{ref("lp_preference")},{totalcap})'
        remaining=f'({ref("distributable_cash")}-{ref("lp_preference")}-{ref("capital_distribution")}-{ref("gp_catchup")})'
        last_effective=old('flip_effective_year') if yi else '0'
        prevsign=old('lp_last_nonzero_sign') if yi else '-1'
        F={
          'capital_called':parent_refs[year]['capital_called'],
          'distributable_cash':parent_refs[year]['distributable_cash'],
          'lp_contribution':f'ROUND({ref("capital_called")}*{params["lp_capital_fraction"]},2)',
          'gp_contribution':f'{ref("capital_called")}-{ref("lp_contribution")}',
          'lp_capital_open':old('lp_capital_close') if yi else f'ROUND({params["opening_capital"]}*{params["lp_capital_fraction"]},2)',
          'gp_capital_open':old('gp_capital_close') if yi else f'{params["opening_capital"]}-ROUND({params["opening_capital"]}*{params["lp_capital_fraction"]},2)',
          'preference_open':prior('preference_close'),
          'preference_accrual':f'ROUND({ref("lp_capital_open")}*{params["preference_rate"]},2)',
          'lp_preference':f'MIN({ref("distributable_cash")},{ref("preference_open")}+{ref("preference_accrual")})',
          'lp_return_of_capital':f'MIN({lp_after},MAX({roc}-{gp_after},IF({totalcap}=0,0,ROUND({roc}*{lp_after}/{totalcap},2))))',
          'gp_return_of_capital':f'{roc}-{ref("lp_return_of_capital")}',
          'capital_distribution':f'{ref("lp_return_of_capital")}+{ref("gp_return_of_capital")}',
          'gp_catchup':f'MIN({ref("distributable_cash")}-{ref("lp_preference")}-{ref("capital_distribution")},MAX(0,ROUND(({ref("carry_rate")}*({prior("lp_cumulative_profit")}+{ref("lp_preference")}+{prior("gp_cumulative_profit")})-{prior("gp_cumulative_profit")})/(1-{ref("carry_rate")}),2)))',
          'gp_residual':f'ROUND({remaining}*{ref("carry_rate")},2)',
          'lp_residual':f'{remaining}-{ref("gp_residual")}',
          'lp_distribution':f'{ref("lp_preference")}+{ref("lp_return_of_capital")}+{ref("lp_residual")}',
          'gp_distribution':f'{ref("gp_return_of_capital")}+{ref("gp_catchup")}+{ref("gp_residual")}',
          'profit_distribution':f'{ref("lp_preference")}+{ref("gp_catchup")}+{ref("lp_residual")}+{ref("gp_residual")}',
          'total_distribution':f'{ref("lp_distribution")}+{ref("gp_distribution")}',
          'lp_capital_close':f'{lp_after}-{ref("lp_return_of_capital")}',
          'gp_capital_close':f'{gp_after}-{ref("gp_return_of_capital")}',
          'preference_close':f'{ref("preference_open")}+{ref("preference_accrual")}-{ref("lp_preference")}',
          'lp_cumulative_profit':f'{prior("lp_cumulative_profit")}+{ref("lp_preference")}+{ref("lp_residual")}',
          'gp_cumulative_profit':f'{prior("gp_cumulative_profit")}+{ref("gp_catchup")}+{ref("gp_residual")}',
          'lp_net_cashflow':f'{ref("lp_distribution")}-{ref("lp_contribution")}',
          'gp_net_cashflow':f'{ref("gp_distribution")}-{ref("gp_contribution")}',
          'carry_rate':old('next_carry_rate') if yi else params['initial_carry_rate'],
          'lp_last_nonzero_sign':f'IF({ref("lp_net_cashflow")}=0,{prevsign},SIGN({ref("lp_net_cashflow")}))',
          'lp_sign_changes':f'{prior("lp_sign_changes")}+IF(AND({ref("lp_net_cashflow")}<>0,SIGN({ref("lp_net_cashflow")})<>{prevsign}),1,0)',
          'lp_xirr_eligible':f'IF(AND({ref("lp_sign_changes")}=1,{ref("lp_last_nonzero_sign")}=1),1,0)',
          'flip_earned':f'IF(AND({last_effective}=0,{ref("lp_xirr_eligible")}=1,{ref("lp_capital_close")}=0,{ref("gp_capital_close")}=0,{ref("hurdle_xnpv")}>=0),1,0)',
          'flip_effective_year':f'IF({last_effective}>0,{last_effective},IF({ref("flip_earned")}=1,{year+1},0))',
          'next_carry_rate':f'IF({ref("flip_effective_year")}>0,{params["flipped_carry_rate"]},{params["initial_carry_rate"]})',
        }
        vals=f'$B${row("lp_net_cashflow")}:{col}{row("lp_net_cashflow")}'
        dates=f'$B$2:{col}$2'
        F['hurdle_xnpv']=f'XNPV({params["lp_xirr_hurdle"]},{vals},{dates})'
        F['lp_xirr']=f'IF({ref("lp_xirr_eligible")}=1,ROUND(IFERROR(XIRR({vals},{dates}),XIRR({vals},{dates},-0.5)),12),"")'
        for field in FIELDS:put(ci,field,F[field],yi)
    return {'bindings':bindings,'sheet_names':SHEETS,'annual_refs':{
        year:{field:f"'{SHEETS['waterfall']}'!{letter(i+3)}{row(field)}" for field in FIELDS}
        for i,year in enumerate(years)}}
