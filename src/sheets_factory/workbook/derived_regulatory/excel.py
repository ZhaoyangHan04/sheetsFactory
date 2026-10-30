"""Independent Excel implementation of the public hypothetical policy.

This module does not import or evaluate the independent journal implementation.
"""
from datetime import datetime
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from .schema import (SHEETS, ANNUAL_FIELDS, ANNUAL_INPUT_FIELDS, RAV_FIELDS, TAX_FIELDS,
                     CLAIM_FIELDS, LOSS_FIELDS, COMBINED_ANNUAL_FIELDS, LEASE_FIELDS,
                     annual_row, batch_row, vintage_row)

PARAMETERS=('gearing','loss_carry_years','loss_use_cap','claim_lag_years','structures_tax_life')

def create_workbook(source, spec, path, public_brief, *, external_annual_refs=None):
    book=openpyxl.load_workbook(source,data_only=False,keep_links=False)
    integrated=external_annual_refs is not None
    annual_fields=COMBINED_ANNUAL_FIELDS if integrated else ANNUAL_FIELDS
    if integrated and 'lease_allowable_fraction' not in spec['parameters']:
        raise ValueError('Integrated leases require an explicit public lease_allowable_fraction')
    # A path-dependent cover identifier is metadata, never a financial target.
    adapters=[]
    if 'Cover' in book:
        old_cover=book['Cover']['G4'].value
        if isinstance(old_cover,str) and 'cell(' in old_cover.casefold() and 'filename' in old_cover.casefold():
            book['Cover']['G4']='Hypothetical regulatory capital reopener; Ofgem ED2 V5 baseline'
            adapters.append({'sheet':'Cover','cell':'G4','before':old_cover,
                'after':book['Cover']['G4'].value,
                'purpose':'Stabilize a path-dependent nonfinancial display identifier; no financial formula changed'})
    for name in SHEETS.values():
        if name in book.sheetnames:raise ValueError('Reopener worksheet already exists')
        sheet=book.create_sheet(name);sheet.freeze_panes='C3';sheet.column_dimensions['A'].width=48
        sheet.column_dimensions['B'].width=18
    brief=book[SHEETS['brief']];brief['A1']='Hypothetical incremental capital programme: public policies'
    for number, paragraph in enumerate(public_brief.split('\n\n'),3):
        brief.cell(number,1,paragraph);brief.cell(number,1).alignment=openpyxl.styles.Alignment(wrap_text=True,vertical='top')
        brief.row_dimensions[number].height=max(30,min(150,len(paragraph)/3))
    brief.column_dimensions['A'].width=145
    inputs=book[SHEETS['inputs']];inputs['A1']='Public annual inputs, current-year values control'
    for number,field in enumerate(ANNUAL_INPUT_FIELDS,3):inputs.cell(number,1,field.replace('_',' '))
    for number,field in enumerate(PARAMETERS,30):
        inputs.cell(number,1,field.replace('_',' '));inputs.cell(number,2,float(spec['parameters'][field]))
    if integrated:
        inputs.cell(35,1,'lease allowable fraction');inputs.cell(35,2,float(spec['parameters']['lease_allowable_fraction']))
    assets=book[SHEETS['assets']]
    asset_headers=('id','paid year','commission year','regulatory life','tax pool','real cost GBP 2020/21',
                   'original nominal cost GBP','source address','source GBP millions','programme share')
    for col,field in enumerate(asset_headers,1):assets.cell(2,col,field)
    for i,batch in enumerate(spec['batches'],3):
        for col,key in enumerate(('id','paid_year','commission_year','regulatory_life','tax_pool','real_cost',
                                   'nominal_cost','source_address','source_millions','programme_share'),1):
            value=batch[key]
            assets.cell(i,col,float(value) if key in ('real_cost','nominal_cost','source_millions','programme_share') else value)
    years=spec['years'];batches=spec['batches'];n=len(batches)
    for sheetkey in ('inputs','rav','tax','claims','losses','annual'):
        sheet=book[SHEETS[sheetkey]]
        sheet['A1']=SHEETS[sheetkey]+' — additional programme only'
        for i,year in enumerate(years,3):
            sheet.cell(2,i,datetime(year,3,31));sheet.cell(2,i).number_format='yyyy-mm-dd'
    for i,row in enumerate(spec['annual_inputs'],3):
        for j,field in enumerate(ANNUAL_INPUT_FIELDS,3):
            inputs.cell(j,i,float(row[field]));inputs.cell(j,i).number_format='0.000000000000' if field in ('price_index','real_wacc','tax_rate','claim_carry_rate','debt_rate','general_rate','special_rate','general_transfer_fraction') else '#,##0.00'
    for i,field in enumerate(annual_fields,3):book[SHEETS['annual']].cell(i,1,field.replace('_',' '))
    for key,fields in [('rav',RAV_FIELDS),('tax',TAX_FIELDS)]:
        for i,batch in enumerate(batches):
            for field in fields:book[SHEETS[key]].cell(batch_row(i,fields,field),1,batch['id']+' | '+field.replace('_',' '))
    for key,fields in [('claims',CLAIM_FIELDS),('losses',LOSS_FIELDS)]:
        for i,year in enumerate(years):
            for field in fields:book[SHEETS[key]].cell(vintage_row(i,fields,field),1,str(year)+' | '+field.replace('_',' '))
    def ref(sheet,col,row):return "'"+SHEETS[sheet]+"'!"+col+str(row)
    def asset(i,col):return "'"+SHEETS['assets']+"'!$"+col+'$'+str(i+3)
    def parameter(key):return "'"+SHEETS['inputs']+"'!$B$"+str(30+PARAMETERS.index(key))
    def total(expressions):return 'SUM('+','.join(expressions)+')' if expressions else '0'
    ordered=sorted(range(n),key=lambda i:(batches[i]['commission_year'],i))
    formula_cells=[]
    for yi,year in enumerate(years):
        col=get_column_letter(yi+3);prev=get_column_letter(yi+2)
        def inp(field):return ref('inputs',col,3+ANNUAL_INPUT_FIELDS.index(field))
        def ann(field):return ref('annual',col,3+annual_fields.index(field))
        def oldann(field):return ref('annual',prev,3+annual_fields.index(field)) if yi else '0'
        external=(external_annual_refs.get(year,external_annual_refs.get(str(year))) if integrated else None)
        if integrated and (not isinstance(external,dict) or any(not isinstance(external.get(key),str)
                or '!' not in external[key] or external[key].startswith('=') for key in LEASE_FIELDS)):
            raise ValueError('Incomplete formula-bound annual lease interface')
        def rav(i,field):return ref('rav',col,batch_row(i,RAV_FIELDS,field))
        def tax(i,field):return ref('tax',col,batch_row(i,TAX_FIELDS,field))
        def oldrav(i,field):return ref('rav',prev,batch_row(i,RAV_FIELDS,field)) if yi else '0'
        def oldtax(i,field):return ref('tax',prev,batch_row(i,TAX_FIELDS,field)) if yi else '0'
        def claim(i,field):return ref('claims',col,vintage_row(i,CLAIM_FIELDS,field))
        def loss(i,field):return ref('losses',col,vintage_row(i,LOSS_FIELDS,field))
        def oldclaim(i):return ref('claims',prev,vintage_row(i,CLAIM_FIELDS,'close')) if yi else '0'
        def oldloss(i):return ref('losses',prev,vintage_row(i,LOSS_FIELDS,'close')) if yi else '0'
        index=inp('price_index')
        def assign(key,row,expression):
            cell=book[SHEETS[key]].cell(row,yi+3,'='+expression);cell.number_format='#,##0.00'
            formula_cells.append((SHEETS[key],cell.coordinate))
        for i,batch in enumerate(batches):
            cost,nominal=asset(i,'F'),asset(i,'G');paid,service=asset(i,'B'),asset(i,'C')
            commission='IF('+str(year)+'='+service+','+cost+',0)'
            available='('+oldrav(i,'rav_close')+'+'+commission+')'
            normal='ROUND('+cost+'/'+asset(i,'D')+',2)'
            dep='IF('+str(year)+'<'+service+',0,MIN('+available+',IF('+str(year)+'='+service+',ROUND('+normal+'/2,2),'+normal+')))'
            before='('+available+'-'+rav(i,'depreciation')+')'
            earlier=ordered[:ordered.index(i)]
            disallowed='MIN('+before+',MAX(0,'+inp('disallowance_real')+'-'+total([rav(j,'disallowance') for j in earlier])+'))'
            expressions={'cwip_close':'IF(AND('+str(year)+'>='+paid+','+str(year)+'<'+service+'),'+cost+',0)',
                         'depreciation':dep,'disallowance':disallowed,
                         'rav_close':before+'-'+rav(i,'disallowance')}
            for field,expression in expressions.items():assign('rav',batch_row(i,RAV_FIELDS,field),expression)
            transfer='ROUND('+oldtax(i,'general_close')+'*'+inp('general_transfer_fraction')+',2)'
            adds={pool:'IF(AND('+str(year)+'='+service+','+asset(i,'E')+'="'+pool+'"),'+nominal+',0)' for pool in ('General','Special','Structures')}
            general_pre='('+oldtax(i,'general_close')+'-'+transfer+'+'+adds['General']+')'
            special_pre='('+oldtax(i,'special_close')+'+'+transfer+'+'+adds['Special']+')'
            structures_pre='('+oldtax(i,'structures_close')+'+'+adds['Structures']+')'
            general_ca='MIN('+general_pre+',ROUND(('+oldtax(i,'general_close')+'-'+transfer+'+'+adds['General']+'/2)*'+inp('general_rate')+',2))'
            special_ca='MIN('+special_pre+',ROUND(('+oldtax(i,'special_close')+'+'+transfer+'+'+adds['Special']+'/2)*'+inp('special_rate')+',2))'
            normal_sl='ROUND('+nominal+'/'+parameter('structures_tax_life')+',2)'
            structures_ca='IF('+str(year)+'<'+service+',0,MIN('+structures_pre+',IF('+str(year)+'='+service+',ROUND('+normal_sl+'/2,2),'+normal_sl+')))'
            expressions={'tax_cip_close':'IF(AND('+str(year)+'>='+paid+','+str(year)+'<'+service+'),'+nominal+',0)',
                'general_close':general_pre+'-'+general_ca,'special_close':special_pre+'-'+special_ca,
                'structures_close':structures_pre+'-'+structures_ca,
                'capital_allowance':general_ca+'+'+special_ca+'+'+structures_ca}
            for field,expression in expressions.items():assign('tax',batch_row(i,TAX_FIELDS,field),expression)
        for i,vintage in enumerate(years):
            previous=oldclaim(i)
            interest='ROUND('+previous+'*'+inp('claim_carry_rate')+',2)' if vintage<year else '0'
            collected=('MIN('+previous+'+'+claim(i,'interest')+',MAX(0,'+inp('collection_cap_nominal')+'-'+total([claim(j,'collected') for j in range(i)])+'))'
                       if year>=vintage+int(spec['parameters']['claim_lag_years']) else '0')
            closing=ann('capital_entitlement') if vintage==year else previous+'+'+claim(i,'interest')+'-'+claim(i,'collected')
            for field,expression in [('interest',interest),('collected',collected),('close',closing)]:assign('claims',vintage_row(i,CLAIM_FIELDS,field),expression)
            expired='IF('+str(year)+'>'+str(vintage)+'+'+parameter('loss_carry_years')+','+oldloss(i)+',0)'
            used=('MIN('+oldloss(i)+'-'+loss(i,'expired')+',MAX(0,'+ann('losses_used')+'-'+total([loss(j,'used') for j in range(i)])+'))' if vintage<year else '0')
            closing=ann('losses_created') if vintage==year else oldloss(i)+'-'+loss(i,'expired')+'-'+loss(i,'used')
            for field,expression in [('expired',expired),('used',used),('close',closing)]:assign('losses',vintage_row(i,LOSS_FIELDS,field),expression)
        def ravsum(field):return total([rav(i,field) for i in range(n)])
        def taxsum(field):return total([tax(i,field) for i in range(n)])
        def nominal_ravsum(field):return total(['ROUND('+rav(i,field)+'*'+index+',2)' for i in range(n)])
        def paid_sum(field,colasset):return total(['IF('+str(year)+'='+asset(i,field)+','+asset(i,colasset)+',0)' for i in range(n)])
        nominal_commission=total(['IF('+str(year)+'='+asset(i,'C')+',ROUND('+asset(i,'F')+'*'+index+',2),0)' for i in range(n)])
        b=ann('pre_allowance_taxable_profit');available=ann('losses_available');u=parameter('loss_use_cap');r=inp('tax_rate')
        continuous_loss='MIN('+available+','+u+'*'+b+'/(1-'+r+'*(1-'+u+')))'
        cf='('+ann('claims_receipts')+'+'+ann('debt_draw')+'-'+ann('capital_spend_nominal')+'-'+ann('debt_repayment')+'-'+ann('debt_interest')+'-'+ann('current_tax_allowance')+')'
        if integrated:cf='('+cf+'-'+ann('lease_cash_rent')+')'
        expressions={
          'opening_cwip_real':oldann('closing_cwip_real'),'opening_rav_real':oldann('closing_rav_real'),
          'capital_spend_real':paid_sum('B','F'),'commissioning_real':paid_sum('C','F'),
          'depreciation_real':ravsum('depreciation'),'disallowance_real':ravsum('disallowance'),
          'closing_cwip_real':ravsum('cwip_close'),'closing_rav_real':ravsum('rav_close'),
          'real_return':'ROUND(('+ann('opening_rav_real')+'+'+ann('closing_rav_real')+')/2*'+inp('real_wacc')+',2)',
          'capital_spend_nominal':paid_sum('B','G'),'commissioning_nominal':nominal_commission,
          'depreciation_nominal':nominal_ravsum('depreciation'),'disallowance_nominal':nominal_ravsum('disallowance'),
          'return_nominal':'ROUND('+ann('real_return')+'*'+index+',2)',
          'closing_cwip_nominal':nominal_ravsum('cwip_close'),'closing_rav_nominal':nominal_ravsum('rav_close'),
          'asset_revaluation':ann('closing_cwip_nominal')+'+'+ann('closing_rav_nominal')+'-'+oldann('closing_cwip_nominal')+'-'+oldann('closing_rav_nominal')+'-'+ann('capital_spend_nominal')+'+'+ann('depreciation_nominal')+'+'+ann('disallowance_nominal'),
          'tax_capital_allowances':taxsum('capital_allowance'),
          'tax_basis_transfer':total(['ROUND('+oldtax(i,'general_close')+'*'+inp('general_transfer_fraction')+',2)' for i in range(n)]),
          'closing_tax_basis':total([taxsum(field) for field in TAX_FIELDS if field!='capital_allowance']),
          'debt_open':oldann('debt_close'),'debt_draw':'ROUND('+ann('capital_spend_nominal')+'*'+parameter('gearing')+',2)',
          'debt_repayment':'MIN('+ann('debt_open')+'+'+ann('debt_draw')+',ROUND('+ann('depreciation_nominal')+'*'+parameter('gearing')+',2))',
          'debt_interest':'ROUND('+ann('debt_open')+'*'+inp('debt_rate')+',2)',
          'debt_close':ann('debt_open')+'+'+ann('debt_draw')+'-'+ann('debt_repayment'),
          'claims_open':oldann('claims_close'),'claim_carrying_interest':total([claim(i,'interest') for i in range(len(years))]),
          'claims_receipts':total([claim(i,'collected') for i in range(len(years))]),
          'claims_close':total([claim(i,'close') for i in range(len(years))]),
          'losses_open':oldann('losses_close'),'losses_expired':total([loss(i,'expired') for i in range(len(years))]),
          'losses_available':ann('losses_open')+'-'+ann('losses_expired'),
          'pre_allowance_taxable_profit':ann('depreciation_nominal')+'+'+ann('return_nominal')+'+'+ann('claim_carrying_interest')+'-'+ann('debt_interest')+'-'+ann('tax_capital_allowances'),
          'losses_used':'IF('+b+'>0,ROUND('+continuous_loss+',2),0)',
          'losses_created':'MAX(0,-'+b+')','losses_close':total([loss(i,'close') for i in range(len(years))]),
          'current_tax_allowance':'IF('+b+'>0,ROUND('+r+'*('+b+'-'+continuous_loss+')/(1-'+r+'),2),0)',
          'capital_entitlement':ann('depreciation_nominal')+'+'+ann('return_nominal')+'+'+ann('current_tax_allowance'),
          'earned_revenue':ann('capital_entitlement')+'+'+ann('claim_carrying_interest'),
          'net_income':ann('earned_revenue')+'-'+ann('depreciation_nominal')+'-'+ann('disallowance_nominal')+'-'+ann('debt_interest')+'-'+ann('current_tax_allowance'),
          'owner_capital':'MAX(0,-'+cf+')','owner_distribution':'MAX(0,'+cf+')',
          'owner_net_cashflow':ann('owner_distribution')+'-'+ann('owner_capital'),
          'cash_close':cf+'+'+ann('owner_capital')+'-'+ann('owner_distribution'),
          'paid_in_capital':oldann('paid_in_capital')+'+'+ann('owner_capital'),
          'retained_earnings':oldann('retained_earnings')+'+'+ann('net_income')+'-'+ann('owner_distribution'),
          'revaluation_reserve':oldann('revaluation_reserve')+'+'+ann('asset_revaluation'),
          'total_assets':ann('closing_cwip_nominal')+'+'+ann('closing_rav_nominal')+'+'+ann('claims_close')+'+'+ann('cash_close'),
          'total_equity':ann('paid_in_capital')+'+'+ann('retained_earnings')+'+'+ann('revaluation_reserve'),
          'balance_check':ann('total_assets')+'-'+ann('debt_close')+'-'+ann('total_equity'),
          'cash_check':ann('cash_close'),
          'claims_check':ann('claims_close')+'-'+ann('claims_open')+'-'+ann('earned_revenue')+'+'+ann('claims_receipts')}
        if integrated:
            expressions.update({key:external[key] for key in LEASE_FIELDS})
            expressions['lease_regulatory_allowance']='ROUND('+ann('lease_regulatory_expense')+"*'"+SHEETS['inputs']+"'!$B$35,2)"
            expressions['pre_allowance_taxable_profit']+='+'+ann('lease_regulatory_allowance')+'-'+ann('lease_tax_deduction')
            expressions['capital_entitlement']+='+'+ann('lease_regulatory_allowance')
            expressions['net_income']+='-'+ann('lease_book_depreciation')+'-'+ann('lease_book_interest')+'+'+ann('lease_termination_gain_loss')
            expressions['total_assets']+='+'+ann('lease_rou_close')
            expressions['balance_check']='('+expressions['balance_check']+')-'+ann('lease_liability_close')
            expressions['total_liabilities']=ann('debt_close')+'+'+ann('lease_liability_close')
            expressions['cfo']=ann('claims_receipts')+'-'+ann('debt_interest')+'-'+ann('current_tax_allowance')+'-'+ann('lease_cash_rent')
            expressions['cfi']='-'+ann('capital_spend_nominal')
            expressions['cff']=ann('debt_draw')+'-'+ann('debt_repayment')+'+'+ann('owner_capital')+'-'+ann('owner_distribution')
        if set(expressions)!=set(annual_fields):raise ValueError('Annual formula/schema coverage mismatch')
        for field,expression in expressions.items():assign('annual',3+annual_fields.index(field),expression)
    for sn in SHEETS.values():
        sheet=book[sn]
        for cell in sheet[2]:
            if cell.value is not None:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='214B63')
    Path(path).parent.mkdir(parents=True,exist_ok=True);book.save(path);book.close()
    return {'formula_cells':formula_cells,'new_formula_count':len(formula_cells),
        'metadata_adapter':adapters,'lease_integrated':integrated,
        'annual_refs':{year:{field:ref('annual',get_column_letter(i+3),3+annual_fields.index(field))
                            for field in annual_fields} for i,year in enumerate(years)}}
