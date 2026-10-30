"""Independent Excel implementation of the holding contract; no ledger imports."""
from datetime import date
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as letter
from .schema import (SHEETS, PROGRAMME_FIELDS, OPERATING_FIELDS, PARENT_FIELDS,
                     GROUP_FIELDS, PARAMETERS, ANNUAL_PARAMETERS, row)


PUBLIC_RULES=(
 'This hypothetical GBP tax-transparent investment partnership owns 100% of the programme and a 25% equity-method interest in the provided USD operating project. Investor-level taxes are outside scope; no additional parent income or withholding tax applies. The programme already includes all lease cash, expenses, assets and liabilities: do not charge lease cash a second time.',
 'Reporting years run 1 April to 31 March, FY2024–2043. Keep the operating project January 2027–December 2029 calendar: acquire the interest in January 2027, receive each monthly dividend, and sell after the December 2029 dividend at the provided project equity exit value. These map to FY2027–2030. Aggregate by actual calendar date. Each monthly ownership share of income/dividend, purchase cost and exit proceeds is posted to USD cents, then separately converted to GBP cents at the provided constant forecast GBP-per-USD rate; no FX remeasurement arises.',
 'Record programme investment at owner contributions plus cumulative programme net income and asset revaluation OCI, less owner distributions. Record the operating interest at cost plus posted share of income, less posted dividends; derecognize its remaining carrying amount on sale and recognize the sale gain/loss. Only the programme is consolidated; the operating associate remains one equity-method investment.',
 'All monetary lines are posted to the nearest penny, half away from zero. Round each stated monetary product and translated monthly item separately, not the underlying rates or unposted intermediate products. Annual totals sum the posted monthly amounts. Ratios use the supplied full precision. Opening holdings and bank debt are zero; opening paid-in capital equals opening cash. Additional LP commitment is finite undrawn capital after this opening funding.',
 'Bank interest uses opening parent debt and the current FY rate; new draws begin accruing in the following FY. The annual fee is a cash expense. The borrowing base is the lesser of the facility limit and the nonnegative sum of posted RAV advance plus posted claims advance, less programme closing bank debt and closing lease liability. RAV uses nominal GBP. First post claims after the FY haircut, then apply the claims advance rate. CWIP and lease ROU assets have no separate collateral value.',
 'This is an annual settlement model, not an intrayear liquidity forecast. Assess the closing collateral base and all FY project dividends/sale/purchase and programme owner flows before financing. Cash before repayments is opening cash plus these receipts, less purchase, owner calls, opening-debt interest and fee. First repay opening bank debt above the base; next use cash above the minimum cash balance to repay remaining opening debt. Draw only the residual minimum-cash shortfall within the resulting headroom; call finite LP capital for the rest, or reject if unavailable. Negative funding-stage amounts are unmet requirements, not a cash account. Sources are funded before cash uses are settled. No parent distributions occur.',
 'The parent cash report classifies project/programme dividends, bank interest and fee as operating; associate purchase/sale and programme owner contributions as investing; parent bank principal and LP capital as financing. Programme cash uses its separately stated regulatory management classification. Consolidation removes the programme investment against programme equity, duplicate programme income/OCI, and both sides of owner cash flows across their original classifications. Programme lease obligations and external debt remain liabilities.',
 'At FY2043 the programme continues: retain actual closing investments, cash, debt and net assets. There is no forced sale, zero-balance terminal entry or unused-commitment asset. Statement rows marked opening/closing are stocks; funding-stage rows follow the above annual priority. Operating sale carrying amount and gain/loss are zero in years without sale; FY2030 derecognizes all remaining associate carrying amount.'
)


def emit_parent(book,spec,programme_annual_refs,operating_refs,*,waterfall_spec=None):
    """Add five sheets using only public inputs and live source formula references.

    programme_annual_refs[FY][field] must be an absolute Excel cell reference.
    operating_refs contains equity_paid_in, equity_exit and 36 monthly records
    with date, net_income and dividend references. No cached source answers enter
    this function. Returned bindings cover every newly emitted formula.
    """
    years=spec['years'];p=spec['parameters'];annual={int(v['year']):v for v in spec['annual_inputs']}
    if list(years)!=list(range(2024,2044)) or len(operating_refs['monthly'])!=36:
        raise ValueError('Holding requires FY2024–2043 and the original 36 source months')
    if any(sn in book.sheetnames for sn in SHEETS.values()):raise ValueError('Holding sheet names already exist')
    refs={int(k):v for k,v in programme_annual_refs.items()}
    if set(refs)!=set(years) or any(any(f not in refs[y] for f in PROGRAMME_FIELDS) for y in years):
        raise ValueError('Programme live references are incomplete')
    sheets={key:book.create_sheet(title) for key,title in SHEETS.items()};bindings=[]
    for key,sheet in sheets.items():
        sheet['A1']=SHEETS[key];sheet['A1'].font=Font(size=14,bold=True)
        sheet.freeze_panes='C3';sheet.column_dimensions['A'].width=39;sheet.column_dimensions['B'].width=18
    public_rules=PUBLIC_RULES
    if waterfall_spec is not None:
        public_rules=tuple(text.replace('Additional LP commitment','Additional partner commitment')
            .replace('call finite LP capital','call finite partner capital').replace('No parent distributions occur.',
            'After this priority, distribute only cash above the minimum through the provided LP/GP Partner Contract. The existing finite additional commitment is total partner capital, split between LP and GP by that contract.') for text in PUBLIC_RULES)
        public_rules+=('Consolidation elimination rows display the original underlying amount, with its original sign; the consolidated totals subtract the investment, equity, income and OCI rows. Owner capital is a positive parent payment/programme receipt, and owner distribution a positive programme payment/parent receipt. Cash-flow eliminations reverse these actual flows in their original reporting categories. These display rows are not signed adjustment journals.',)
    for i,text in enumerate(public_rules,3):sheets['brief'].cell(i,1,text)
    if spec.get('credit_policy'):sheets['brief'].cell(3+len(public_rules),1,spec['credit_policy'])
    sheets['brief'].column_dimensions['A'].width=120
    def reference(key,cell):return "'"+SHEETS[key].replace("'","''")+"'!"+cell
    def live(ref):
        if not isinstance(ref,str) or not ref or ref.startswith('='):
            raise ValueError('Source links must be explicit cell references without leading equals')
        return ref
    def put(key,r,c,formula,section,index,field,kind='money'):
        if kind=='money':formula=f'ROUND(({formula}),2)'
        cell=sheets[key].cell(r,c,'='+formula)
        cell.number_format='yyyy-mm-dd' if kind=='date' else ('0' if kind=='integer' else '#,##0.00;[Red](#,##0.00)')
        bindings.append({'sheet':SHEETS[key],'cell':cell.coordinate,'section':section,
                         'index':index,'field':field,'kind':kind})
    param={}
    for i,key in enumerate(PARAMETERS,3):
        sheets['inputs'].cell(i,1,key);sheets['inputs'].cell(i,2,float(p[key]));param[key]=reference('inputs',f'$B${i}')
    for yi,y in enumerate(years):
        c=yi+3;col=letter(c);sheets['inputs'].cell(15,c,y)
        for offset,key in enumerate(ANNUAL_PARAMETERS,16):
            sheets['inputs'].cell(offset,1,key);sheets['inputs'].cell(offset,c,float(annual[y][key]))
    # The original monthly project data retain their calendar and USD units.
    for i,field in enumerate(OPERATING_FIELDS,1):sheets['operating'].cell(2,i,field)
    for i,source in enumerate(operating_refs['monthly']):
        r=i+3
        put('operating',r,1,live(source['date']),'operating_monthly_bridge',i,'date','date')
        put('operating',r,2,f'YEAR(A{r})+IF(MONTH(A{r})>3,1,0)','operating_monthly_bridge',i,'fiscal_year','integer')
        vals={'income_usd':f'ROUND({live(source["net_income"])}*{param["operating_ownership"]},2)',
              'dividend_usd':f'ROUND({live(source["dividend"])}*{param["operating_ownership"]},2)',
              'acquisition_usd':f'ROUND({live(operating_refs["equity_paid_in"])}*{param["operating_ownership"]},2)' if i==0 else '0',
              'sale_usd':f'ROUND({live(operating_refs["equity_exit"])}*{param["operating_ownership"]},2)' if i==35 else '0'}
        for offset,field in enumerate(OPERATING_FIELDS[2:6],3):put('operating',r,offset,vals[field],'operating_monthly_bridge',i,field)
        for offset,field in enumerate(OPERATING_FIELDS[6:],7):
            put('operating',r,offset,f'ROUND({letter(offset-4)}{r}*{param["gbp_per_usd"]},2)','operating_monthly_bridge',i,field)
    for key,fields in [('parent',PARENT_FIELDS),('group',GROUP_FIELDS)]:
        for field in fields:sheets[key].cell(row(field,fields),1,field)
    waterfall_meta=None
    if waterfall_spec is not None:
        from ..partner_waterfall.excel import emit_waterfall
        parent_links={}
        for yi,y in enumerate(years):
            col=letter(yi+3)
            field_ref=lambda field:reference('parent',f'{col}{row(field,PARENT_FIELDS)}')
            parent_links[y]={'capital_called':field_ref('lp_capital'),
                'distributable_cash':f'MAX(0,{field_ref("funding_after_repayments")}+{field_ref("bank_draw")}+{field_ref("lp_capital")}-{param["minimum_cash"]})'}
        waterfall_meta=emit_waterfall(book,waterfall_spec,parent_links)
        bindings.extend(waterfall_meta['bindings'])
    for yi,y in enumerate(years):
        c=yi+3;col=letter(c);prev=letter(c-1)
        for key in ('parent','group'):sheets[key].cell(2,c,y)
        pr=lambda f:f'{col}{row(f,PARENT_FIELDS)}'
        old=lambda f:f'{prev}{row(f,PARENT_FIELDS)}'
        pfull=lambda f:reference('parent',pr(f))
        sr=lambda f:live(refs[y][f])
        ar=lambda f:reference('inputs',f'{col}{16+ANNUAL_PARAMETERS.index(f)}')
        F={}
        for opening,closing in [('cash_open','cash_close'),('bank_open','bank_close'),
                                ('programme_investment_open','programme_investment_close'),
                                ('operating_investment_open','operating_investment_close'),
                                ('capital_open','capital_close'),('retained_open','retained_close'),
                                ('oci_open','oci_close'),('lp_called_open','lp_called_close')]:
            F[opening]=old(closing) if yi else (param['opening_cash'] if opening in ('cash_open','capital_open') else '0')
        F['bank_interest']=f'ROUND({pr("bank_open")}*{ar("bank_rate")},2)';F['management_fee']=ar('management_fee')
        for target,sourcecol in [('operating_income','G'),('operating_dividend','H'),('operating_acquisition','I'),('operating_sale','J')]:
            F[target]=f'SUMIF({reference("operating","$B$3:$B$38")},{y},{reference("operating",f"${sourcecol}$3:${sourcecol}$38")})'
        carrying=f'{pr("operating_investment_open")}+{pr("operating_acquisition")}+{pr("operating_income")}-{pr("operating_dividend")}'
        F['operating_sale_carrying']=carrying if y==2030 else '0'
        F['operating_sale_gain']=f'{pr("operating_sale")}-{pr("operating_sale_carrying")}'
        F['operating_investment_close']=carrying+'-'+pr('operating_sale_carrying')
        for name,field in [('programme_income','net_income'),('programme_oci','asset_revaluation'),
                           ('programme_capital','owner_capital'),('programme_distribution','owner_distribution')]:F[name]=sr(field)
        F['programme_investment_close']=f'{pr("programme_investment_open")}+{pr("programme_capital")}+{pr("programme_income")}+{pr("programme_oci")}-{pr("programme_distribution")}'
        F['rav_collateral']=f'ROUND({sr("closing_rav_nominal")}*{param["rav_advance_rate"]},2)'
        F['claims_after_haircut']=f'ROUND({sr("claims_close")}*(1-{ar("claim_haircut")}),2)'
        F['claims_collateral']=f'ROUND({pr("claims_after_haircut")}*{param["claim_advance_rate"]},2)'
        F['senior_obligations']=sr('debt_close')+'+'+sr('lease_liability_close')
        F['borrowing_base']=f'MIN({param["facility_limit"]},MAX(0,{pr("rav_collateral")}+{pr("claims_collateral")}-{pr("senior_obligations")}))'
        F['funding_before_repayments']=f'{pr("cash_open")}-{pr("bank_interest")}-{pr("management_fee")}+{pr("operating_dividend")}+{pr("operating_sale")}-{pr("operating_acquisition")}+{pr("programme_distribution")}-{pr("programme_capital")}'
        F['mandatory_margin']=f'MAX(0,{pr("bank_open")}-{pr("borrowing_base")})'
        F['funding_after_margin']=pr('funding_before_repayments')+'-'+pr('mandatory_margin')
        F['optional_repayment']=f'MIN({pr("bank_open")}-{pr("mandatory_margin")},MAX(0,{pr("funding_after_margin")}-{param["minimum_cash"]}))'
        F['funding_after_repayments']=pr('funding_after_margin')+'-'+pr('optional_repayment')
        F['bank_headroom']=f'MAX(0,{pr("borrowing_base")}-{pr("bank_open")}+{pr("mandatory_margin")}+{pr("optional_repayment")})'
        F['bank_draw']=f'MIN(MAX(0,{param["minimum_cash"]}-{pr("funding_after_repayments")}),{pr("bank_headroom")})'
        F['lp_required']=f'MAX(0,{param["minimum_cash"]}-{pr("funding_after_repayments")}-{pr("bank_draw")})'
        # NA is intentional infeasibility: finite capital may never silently fill a plug.
        F['lp_capital']=f'IF({pr("lp_required")}<={param["additional_lp_commitment"]}-{pr("lp_called_open")},{pr("lp_required")},NA())'
        F['lp_called_close']=pr('lp_called_open')+'+'+pr('lp_capital')
        F['lp_remaining']=param['additional_lp_commitment']+'-'+pr('lp_called_close')
        F['cash_close']=f'{pr("funding_after_repayments")}+{pr("bank_draw")}+{pr("lp_capital")}'
        F['bank_close']=f'{pr("bank_open")}-{pr("mandatory_margin")}-{pr("optional_repayment")}+{pr("bank_draw")}'
        F['net_income']=f'{pr("programme_income")}+{pr("operating_income")}+{pr("operating_sale_gain")}-{pr("bank_interest")}-{pr("management_fee")}'
        F['capital_close']=pr('capital_open')+'+'+pr('lp_capital')
        F['retained_close']=pr('retained_open')+'+'+pr('net_income');F['oci_close']=pr('oci_open')+'+'+pr('programme_oci')
        F['assets']=f'{pr("cash_close")}+{pr("programme_investment_close")}+{pr("operating_investment_close")}'
        F['liabilities']=pr('bank_close');F['equity']=f'{pr("capital_close")}+{pr("retained_close")}+{pr("oci_close")}'
        F['balance_check']=f'{pr("assets")}-{pr("liabilities")}-{pr("equity")}'
        F['cfo']=f'{pr("operating_dividend")}+{pr("programme_distribution")}-{pr("bank_interest")}-{pr("management_fee")}'
        F['cfi']=f'{pr("operating_sale")}-{pr("operating_acquisition")}-{pr("programme_capital")}'
        F['cff']=f'{pr("bank_draw")}-{pr("mandatory_margin")}-{pr("optional_repayment")}+{pr("lp_capital")}'
        if waterfall_meta is not None:
            wr=waterfall_meta['annual_refs'][y]
            F['cash_close']+='-'+wr['total_distribution']
            F['capital_close']+='-'+wr['capital_distribution']
            F['retained_close']+='-'+wr['profit_distribution']
            F['cff']+='-'+wr['total_distribution']
        F['cash_check']=f'{pr("cash_close")}-{pr("cash_open")}-{pr("cfo")}-{pr("cfi")}-{pr("cff")}'
        F['programme_investment_check']=pr('programme_investment_close')+'-'+sr('total_equity')
        for field in PARENT_FIELDS:put('parent',row(field,PARENT_FIELDS),c,F[field],'annual',yi,field)
        gr=lambda f:f'{col}{row(f,GROUP_FIELDS)}'
        G={
          'cash_open':pfull('cash_open')+('+'+live(refs[years[yi-1]]['cash_close']) if yi else ''),
          'cash_close':pfull('cash_close')+'+'+sr('cash_close'),
          'parent_assets':pfull('assets'),'programme_assets':sr('total_assets'),
          'investment_elimination':pfull('programme_investment_close'),
          'parent_liabilities':pfull('liabilities'),'programme_bank_debt':sr('debt_close'),
          'programme_lease_liability':sr('lease_liability_close'),'parent_equity':pfull('equity'),
          'programme_equity':sr('total_equity'),'equity_elimination':sr('total_equity'),
          'parent_income':pfull('net_income'),'programme_income':sr('net_income'),
          'income_elimination':pfull('programme_income'),'parent_oci':pfull('programme_oci'),
          'programme_oci':sr('asset_revaluation'),'oci_elimination':pfull('programme_oci'),
          'owner_capital_elimination':sr('owner_capital'),'owner_distribution_elimination':sr('owner_distribution')}
        G['assets']=f'{gr("parent_assets")}+{gr("programme_assets")}-{gr("investment_elimination")}'
        G['liabilities']=f'{gr("parent_liabilities")}+{gr("programme_bank_debt")}+{gr("programme_lease_liability")}'
        G['equity']=f'{gr("parent_equity")}+{gr("programme_equity")}-{gr("equity_elimination")}'
        G['balance_check']=f'{gr("assets")}-{gr("liabilities")}-{gr("equity")}'
        G['net_income']=f'{gr("parent_income")}+{gr("programme_income")}-{gr("income_elimination")}'
        G['income_check']=f'{gr("net_income")}-({sr("net_income")}+{pfull("operating_income")}+{pfull("operating_sale_gain")}-{pfull("bank_interest")}-{pfull("management_fee")})'
        G['oci']=f'{gr("parent_oci")}+{gr("programme_oci")}-{gr("oci_elimination")}'
        G['cfo']=pfull('cfo')+'+'+sr('cfo')+'-'+gr('owner_distribution_elimination')
        G['cfi']=pfull('cfi')+'+'+sr('cfi')+'+'+gr('owner_capital_elimination')
        G['cff']=pfull('cff')+'+'+sr('cff')+'-'+gr('owner_capital_elimination')+'+'+gr('owner_distribution_elimination')
        G['cash_check']=f'{gr("cash_close")}-{gr("cash_open")}-{gr("cfo")}-{gr("cfi")}-{gr("cff")}'
        for field in GROUP_FIELDS:put('group',row(field,GROUP_FIELDS),c,G[field],'consolidated',yi,field)
    for sheet in sheets.values():
        for cell in sheet._cells.values():
            if cell.data_type=='f':cell.font=Font(color='000000')
            elif isinstance(cell.value,(int,float)):cell.font=Font(color='0000AA')
    result={'bindings':bindings,'sheet_names':SHEETS,'annual_refs':{
      y:{f:reference('parent',f'{letter(i+3)}{row(f,PARENT_FIELDS)}') for f in PARENT_FIELDS}
      for i,y in enumerate(years)},'consolidated_refs':{
      y:{f:reference('group',f'{letter(i+3)}{row(f,GROUP_FIELDS)}') for f in GROUP_FIELDS}
      for i,y in enumerate(years)}}
    if waterfall_meta is not None:
        result['waterfall_refs']=waterfall_meta['annual_refs']
        result['waterfall_binding']=waterfall_meta
    return result
