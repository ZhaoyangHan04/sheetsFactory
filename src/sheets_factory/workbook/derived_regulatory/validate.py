"""Check every new policy output against independently computed journal values."""
from decimal import Decimal
import openpyxl
from .schema import (SHEETS, ANNUAL_FIELDS, COMBINED_ANNUAL_FIELDS, CONTINGENT_ANNUAL_FIELDS, RAV_FIELDS, TAX_FIELDS, CLAIM_FIELDS,
                     LOSS_FIELDS, annual_row, batch_row, vintage_row)


def expected_cells(spec, ledger):
    result={}
    annual_fields=COMBINED_ANNUAL_FIELDS if ledger.get('lease_integrated') else ANNUAL_FIELDS
    if ledger.get('contingent_recovery') is not None:annual_fields=CONTINGENT_ANNUAL_FIELDS
    for yi,year in enumerate(spec['years']):
        col=yi+3
        for field in annual_fields:result[(SHEETS['annual'],3+annual_fields.index(field),col)]=ledger['annual'][yi][field]
        for i,batch in enumerate(spec['batches']):
            for key,fields,records in [('rav',RAV_FIELDS,ledger['rav_batches']),('tax',TAX_FIELDS,ledger['tax_batches'])]:
                for field in fields:result[(SHEETS[key],batch_row(i,fields,field),col)]=records[batch['id']][yi][field]
        for i,vintage in enumerate(spec['years']):
            for key,fields,records in [('claims',CLAIM_FIELDS,ledger['claim_vintages']),('losses',LOSS_FIELDS,ledger['loss_vintages'])]:
                record=records.get(vintage,records.get(str(vintage)))[yi]
                for field in fields:result[(SHEETS[key],vintage_row(i,fields,field),col)]=record[field]
    return result


def audit_workbook(path,spec,ledger):
    expected=expected_cells(spec,ledger)
    formulas=openpyxl.load_workbook(path,data_only=False,keep_links=False)
    values=openpyxl.load_workbook(path,data_only=True,keep_links=False)
    checked=[];mismatches=[];uncovered=[];native_errors=[]
    try:
        for (sn,row,col),amount in expected.items():
            actual=values[sn].cell(row,col);goal=Decimal(str(amount))
            passed=(type(actual.value) in (int,float) and abs(Decimal(str(actual.value))-goal)<Decimal('.005'))
            record={'address':sn+'!'+actual.coordinate,'expected_independent':str(goal),
                    'observed':str(actual.value),'passed':passed}
            checked.append(record)
            if not passed:mismatches.append(record)
        new_formula_count=0
        for sheet in formulas:
            for cell in sheet._cells.values():
                if cell.data_type=='f' and sheet.title in [SHEETS[key] for key in ('rav','tax','claims','losses','annual')]:
                    new_formula_count+=1
                    if (sheet.title,cell.row,cell.column) not in expected:uncovered.append(sheet.title+'!'+cell.coordinate)
                if values[sheet.title][cell.coordinate].data_type=='e':native_errors.append({'address':sheet.title+'!'+cell.coordinate,'value':values[sheet.title][cell.coordinate].value})
        invariants=all(value is True for value in ledger['checks'].values())
        return {'passed':not mismatches and not uncovered and not native_errors and invariants,
            'scope':'Every new hypothetical policy calculation; original upstream forecast remains provided, not independently recertified.',
            'checked_cells':len(checked),'new_formula_count':new_formula_count,
            'all_new_formula_cells_independently_covered':not uncovered and new_formula_count==len(expected),
            'mismatches':mismatches,'uncovered':uncovered,'native_errors':native_errors,
            'independent_journal_checks':ledger['checks'],'cell_checks':checked}
    finally:formulas.close();values.close()
