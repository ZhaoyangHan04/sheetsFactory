"""Bind every new formula to an independently computed result, including dates."""
from datetime import date,datetime
from decimal import Decimal
import openpyxl
from .schema import SHEETS,PARAMETERS,ANNUAL_PARAMETERS


def expected_cells(ledger,bindings):
    return {(b['sheet'],b['cell']):ledger[b['section']][b['index']][b['field']] for b in bindings}


def audit_workbook(path,ledger,bindings,*,spec,waterfall_spec=None):
    values=openpyxl.load_workbook(path,data_only=True,keep_links=False)
    formulas=openpyxl.load_workbook(path,data_only=False,keep_links=False)
    checked=[];mismatches=[];uncovered=[];errors=[];seen=set();control_mismatches=[]
    try:
        for binding in bindings:
            sn=binding['sheet'];addr=binding['cell'];expected=ledger[binding['section']][binding['index']][binding['field']]
            actual=values[sn][addr].value;kind=binding['kind'];seen.add((sn,addr))
            if kind=='date':
                observed=actual.date() if isinstance(actual,datetime) else actual
                target=date.fromisoformat(str(expected)[:10]);passed=observed==target
            elif kind=='integer':passed=type(actual) in (int,float) and actual==int(expected)
            elif kind=='nullable_integer':passed=(actual==0 if expected is None else type(actual) in (int,float) and actual==int(expected))
            elif kind=='nullable_rate' and expected is None:passed=actual in (None,'')
            elif kind in ('rate','nullable_rate'):passed=type(actual) in (int,float) and abs(Decimal(str(actual))-Decimal(str(expected)))<Decimal('1e-10')
            else:passed=type(actual) in (int,float) and abs(Decimal(str(actual))-Decimal(str(expected)))<Decimal('.005')
            item={'address':sn+'!'+addr,'kind':kind,'expected':str(expected),'observed':str(actual),'passed':passed}
            checked.append(item)
            if not passed:mismatches.append(item)
        controls=[(f'B{i}',spec['parameters'][field]) for i,field in enumerate(PARAMETERS,3)]
        inputs={int(r['year']):r for r in spec['annual_inputs']}
        for yi,year in enumerate(spec['years']):
            col=openpyxl.utils.get_column_letter(yi+3)
            controls.append((f'{col}15',year))
            for ri,field in enumerate(ANNUAL_PARAMETERS,16):controls.append((f'{col}{ri}',inputs[year][field]))
        for addr,goal in controls:
            actual=formulas[SHEETS['inputs']][addr]
            if actual.data_type=='f' or type(actual.value) not in (int,float) or Decimal(str(actual.value))!=Decimal(str(goal)):
                control_mismatches.append({'address':SHEETS['inputs']+'!'+addr,'expected':str(goal),'observed':str(actual.value)})
        formula_sheets=set(SHEETS.values())
        if waterfall_spec is not None:
            from ..partner_waterfall.schema import SHEETS as PARTNER_SHEETS,INPUT_FIELDS
            formula_sheets.update(PARTNER_SHEETS.values())
            for i,field in enumerate(INPUT_FIELDS,3):
                cell=formulas[PARTNER_SHEETS['inputs']][f'B{i}'];actual=cell.value
                if field=='opening_date':
                    observed=actual.date() if isinstance(actual,datetime) else actual
                    passed=cell.data_type!='f' and observed==date.fromisoformat(waterfall_spec[field])
                else:
                    passed=cell.data_type!='f' and type(actual) in (int,float) and Decimal(str(actual))==Decimal(str(waterfall_spec[field]))
                if not passed:control_mismatches.append({'address':PARTNER_SHEETS['inputs']+'!'+cell.coordinate,'expected':str(waterfall_spec[field]),'observed':str(actual)})
        formula_count=0
        for sheet in formulas:
            for cell in sheet._cells.values():
                if cell.data_type=='f' and sheet.title in formula_sheets:
                    formula_count+=1
                    if (sheet.title,cell.coordinate) not in seen:uncovered.append(sheet.title+'!'+cell.coordinate)
                cached=values[sheet.title][cell.coordinate]
                if cached.data_type=='e':errors.append({'address':sheet.title+'!'+cell.coordinate,'error':cached.value})
        return {'passed':not mismatches and not uncovered and not errors and not control_mismatches and formula_count==len(seen)==len(bindings)
                 and all(v is True for v in ledger['checks'].values()),
                'checked_cells':len(checked),'new_formula_count':formula_count,
                'all_new_formula_cells_independently_covered':not uncovered and formula_count==len(seen)==len(bindings),
                'mismatches':mismatches,'uncovered':uncovered,'native_errors':errors,
                'public_parameters_verified':not control_mismatches,'control_mismatches':control_mismatches,
                'independent_journal_checks':ledger['checks'],'cell_checks':checked}
    finally:values.close();formulas.close()
