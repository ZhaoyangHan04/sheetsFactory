"""Compile a public-input-only independent financial-journal recovery witness.

The standalone program contains calculation ledgers and public layout metadata,
never Excel emitters, reference answers, task edits or private source evidence.
"""
from __future__ import annotations

import ast
import base64
from datetime import date,datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile


PUBLIC_SHEET='Model Input Contracts'
CONTRACT_ORDER=('lease','programme','operating','holding')
OPTIONAL_CONTRACTS={'contingent','waterfall'}
CONTINGENT_LABELS={
 'total_recovery_entitlement':'Same-year total regulatory recovery entitlement',
 'variable_rents.P01':'P01 current variable cash rent',
 'variable_rents.P02':'P02 current variable cash rent',
 'variable_rents.P03':'P03 current variable cash rent',
 'variable_rents.P04':'P04 current variable cash rent',
 'variable_lease_cash':'Total current variable rent: cash paid',
 'variable_lease_allowance':'Separately posted current variable regulatory allowance',
 'variable_book_expense':'Current variable rent book expense',
 'variable_tax_deduction':'Current variable rent tax deduction'}

# Public fixed project row layout. This metadata contains no financial formula.
OPERATING_MAPPING={
 'Calendar':{'period':2,'date':3,'year':4,'month_days':5},
 'Operations':{'sales':2,'cogs':3,'other_opex':4,'startup_expense':5,'ebitda':6,
   'depreciation_initial':7,'depreciation_refresh':8,'depreciation':9,'ebit':10,
   'interest':11,'ebt':12,'tax':13,'net_income':14,'ar_open':15,'ar_close':16,
   'delta_ar':17,'inventory_open':18,'inventory_close':19,'delta_inventory':20,
   'ap_open':21,'ap_close':22,'delta_ap':23},
 'Assets':{'capex':2,'asset_initial_gross':6,'asset_refresh_gross':7,'accumulated_depreciation':8,'net_ppe':9},
 'Debt':{'loan_a_open':2,'loan_a_interest':3,'loan_a_scheduled_principal':4,
   'loan_a_extra_principal':5,'loan_a_close':6,'loan_b_open':7,'loan_b_interest':8,
   'loan_b_principal':9,'loan_b_close':10,'revolver_open':11,'revolver_interest':12,
   'revolver_draw':13,'revolver_repayment':14,'revolver_close':15},
 'Tax':{'nol_open':3,'nol_use':4,'nol_add':5,'nol_close':6},
 'Cash Flow':{'cash_open':2,'cfo_direct':3,'cfo_indirect':4,'cfi':5,
   'cash_before_allocation':8,'cash_gap':9,'dividend':10,'cff':11,'cash_close':12},
 'Balance Sheet':{'retained_open':15,'retained_close':16,'assets':9,'liabilities':14,'equity':18,'balance_check':19},
 'Equity Value':{'owner_cashflow':16}}


def _label(value):return re.sub(r'[^a-z0-9]+',' ',str(value or '').lower()).strip()


def _rows(sheet):
    result={}
    for cell in sheet['A']:
        label=_label(cell.value)
        if label:
            if label in result:raise ValueError('Ambiguous public row label: '+sheet.title+'/'+label)
            result[label]=cell.row
    return result


def _json_unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate public JSON key: '+key)
        result[key]=value
    return result


def read_public_contracts(book):
    if PUBLIC_SHEET not in book:raise ValueError('Missing public Model Input Contracts')
    sheet=book[PUBLIC_SHEET];specs={};hashes={}
    def reject_outputs(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'ledger','journal','annual','monthly','valuation','goal','expected_cells','private_path','local_path','path'}:
                    raise ValueError('A public input contract contains a computed result or local artifact reference: '+key)
                reject_outputs(item)
        elif isinstance(value,list):
            for item in value:reject_outputs(item)
        elif isinstance(value,str) and (value.startswith(('/data/','/workspace/','file://'))):
            raise ValueError('Public input contract contains a local artifact location')
    rows=list(enumerate(CONTRACT_ORDER,4))
    for offset in range(8,sheet.max_row+1):
        name=sheet.cell(offset,1).value
        if name is None and sheet.cell(offset,2).value is None:continue
        if name not in OPTIONAL_CONTRACTS or name in [n for _,n in rows]:
            raise ValueError('Unknown or duplicate optional public input contract')
        rows.append((offset,name))
    for offset,name in rows:
        label=sheet.cell(offset,1);cell=sheet.cell(offset,2)
        if label.value!=name or cell.data_type=='f' or not isinstance(cell.value,str):
            raise ValueError('Public contract rows must be explicit labelled JSON literals')
        spec=json.loads(cell.value,object_pairs_hook=_json_unique)
        if not isinstance(spec,dict):raise ValueError('Public contract must be a JSON object')
        reject_outputs(spec);specs[name]=spec;hashes[name]=hashlib.sha256(cell.value.encode()).hexdigest()
    return specs,hashes


def _operating_bindings(book,spec,ledger,mapping):
    """Infer all variable row positions from the provided project labels."""
    rows={name:_rows(book[target]) for name,target in mapping.items()}
    def require(sheet,key):
        result=rows[sheet].get(_label(key))
        if result is None:raise ValueError('Missing public project row: '+sheet+'/'+key)
        return result
    monthly={key:{'sheet':sheet,'row':r} for sheet,fields in OPERATING_MAPPING.items() for key,r in fields.items()}
    flattened={}
    for key,value in spec['parameters'].items():
        if isinstance(value,list):flattened.update({f'ramp_{i}':v for i,v in enumerate(value,1)})
        else:flattened[key]=value
    # An explicit prose zero-residual policy does not need a duplicate numeric row.
    parameters={key:rows['Scenario'][_label(key)] for key in flattened if _label(key) in rows['Scenario']}
    annual={key:require('Annual Statements',key) for key in ledger['annual'][0]
            if key not in {'year','periods','start_date','end_date'} and _label(key) in rows['Annual Statements']}
    valuation={key:'B'+str(require('Equity Value',key)) for key in ledger['valuation']
               if _label(key) in rows['Equity Value']}
    covenant={}
    if spec.get('covenant_parameters',{}).get('covenant_enabled') in (1,'1',True):
        for key in ('cfads','quarter_cfads','contractual_service','quarter_service','required_cfads','dscr_display',
                    'test_due','test_passed','lock_open','passes_open','passes_close','lock_close',
                    'dsra_open','dsra_target','dsra_release','dsra_support','dsra_funding','dsra_close','dsra_shortfall','dsra_net_transfer'):
            covenant[key]={'row':require('Covenants',key),'kind':'ratio' if key=='dscr_display' else 'integer' if key in {
              'test_due','test_passed','lock_open','passes_open','passes_close','lock_close'} else 'money'}
    tax_annual={key:require('Tax Vintages',key) for key in ledger.get('tax_annual',[{}])[0] if key!='year'}
    result={'monthly':monthly,'annual':annual,'valuation':valuation,'parameter_rows':parameters,
      'source_anchor_rows':dict(zip(('revenue','ebit','da','tax_rate','debt_rate','equity_rate','growth'),range(2,9))),
      'payment_row':require('Scenario','Original Loan A level payment'),'covenant':covenant,
      'covenant_parameter_rows':{key:require('Scenario',key) for key in spec.get('covenant_parameters',{})},
      'covenant_annual':{},'advanced_tax_annual':{},'tax_annual':tax_annual,
      'tax_monthly':{'current_tax':7,'nol_expired':8,'interest_cf_close':9,'deferred_tax_expense':10,'dta_close':11,'dtl_close':12}
                     if tax_annual else {},
      'tax_parameter_rows':{key:require('Scenario',key) for key in spec.get('advanced_tax_parameters',{})}}
    if 'debt_sizing' in ledger:
        result['debt_sizing']={key:'B'+str(require('DebtSizing',key)) for key in ledger['debt_sizing']}
        result['cyclic_financing_parameter_rows']={key:require('Scenario','cyclic_'+key) for key in spec['cyclic_financing_parameters']}
    return result


def recover_public(source,destination,report_path=None):
    """Recompute from the exact input workbook; no task plan or goal is accepted."""
    import openpyxl
    from openpyxl.utils import get_column_letter as L
    from sheets_factory.workbook.lease_finance.contract import month_date
    from sheets_factory.workbook.lease_finance.ledger import simulate_lease
    from sheets_factory.workbook.derived_regulatory.ledger import simulate as programme_simulate,annual_bridge
    from sheets_factory.workbook.derived_regulatory.validate import expected_cells as programme_expected
    from sheets_factory.workbook.derived_gold.ledger import simulate as operating_simulate,_DEFAULTS,_REQUIRED_RESOLVED
    from sheets_factory.workbook.derived_gold.validate import audit_workbook as operating_audit,ledger_invariants_pass
    from sheets_factory.workbook.holding_treasury.ledger import simulate_parent
    from sheets_factory.workbook.holding_treasury.schema import SHEETS,OPERATING_FIELDS,PARENT_FIELDS,GROUP_FIELDS,row
    source=Path(source);destination=Path(destination)
    if source.resolve()==destination.resolve():raise ValueError('Public recovery does not overwrite its input')
    book=openpyxl.load_workbook(source,keep_links=False)
    try:
        specs,contract_hashes=read_public_contracts(book)
        operating_spec=specs['operating'];parameters=operating_spec['parameters']
        if 'residual' not in parameters:
            policy=' '.join(str(c.value or '') for row_ in book['Operating Read Me'] for c in row_).lower()
            if not ('zero residual' in policy or re.search(r'cost\s*/\s*life',policy)):
                raise ValueError('The public project is missing its residual policy')
            parameters['residual']='0'
        if (set(_DEFAULTS)|set(_REQUIRED_RESOLVED))-set(parameters):
            raise ValueError('Missing explicit public operating assumptions')
        lease=simulate_lease(specs['lease'])
        programme=programme_simulate(specs['programme'],external_lease_annual=lease['annual'],
                                     contingent_spec=specs.get('contingent'))
        operating=operating_simulate(operating_spec)
        holding=simulate_parent(specs['holding'],annual_bridge(specs['programme'],programme),operating,operating_spec,
                                 waterfall_spec=specs.get('waterfall'))
        if (not all(lease['checks'].values()) or not all(programme['checks'].values())
                or not ledger_invariants_pass(operating['checks']) or not all(holding['checks'].values())):
            raise ValueError('Independent public journals do not reconcile')
        expected={};kinds={};counts={}
        def add(sheet,address,value,kind='money'):
            if sheet not in book:raise ValueError('Missing public calculation sheet: '+sheet)
            key=(sheet,address)
            if key in expected and str(expected[key])!=str(value):raise ValueError('Conflicting independent public bindings')
            expected[key]=value;kinds[key]=kind
        def copy_fields(sheet,column,record):
            rows=_rows(book[sheet])
            for field,value in record.items():
                label=_label(field)
                if label in rows:add(sheet,column+str(rows[label]),value)
        # Lease layout is labelled publicly. Its dates and fiscal mapping are
        # recomputed from supplied calendar primitives, never cached dates.
        for period in range(1,241):
            c=L(period+2);when=month_date(specs['lease']['start_date'],period)
            add('Lease Calendar',c+'1',when,'date');add('Lease Calendar',c+'3',when.year+(when.month>=4),'integer')
            for contract in specs['lease']['leases']:
                sheet='Lease '+contract['lease_id'];add(sheet,c+'1',when,'date');add(sheet,c+'2',period,'integer')
                copy_fields(sheet,c,lease['lease_monthly'][contract['lease_id']][period-1])
            add('Lease Monthly',c+'1',when,'date');add('Lease Monthly',c+'2',period,'integer')
            copy_fields('Lease Monthly',c,lease['monthly'][period-1])
        for yi,year in enumerate(specs['holding']['years']):copy_fields('Lease Annual',L(yi+3),lease['annual'][year])
        counts['lease']=len(expected)
        for (sheet,r,c),value in programme_expected(specs['programme'],programme).items():add(sheet,L(c)+str(r),value)
        counts['programme']=len(expected)-sum(counts.values())
        if 'contingent' in specs:
            rows=_rows(book['Contingent Annual'])
            for yi,year in enumerate(specs['programme']['years']):
                solved=programme['contingent_recovery']['annual'][year]
                for field,label in CONTINGENT_LABELS.items():
                    if _label(label) not in rows:raise ValueError('Missing public contingent financial row: '+label)
                    value=(solved['variable_rents'][field.split('.')[1]] if field.startswith('variable_rents.')
                           else solved[field])
                    add('Contingent Annual',L(yi+3)+str(rows[_label(label)]),value)
            counts['contingent']=len(expected)-sum(counts.values())
        mapping={name.removeprefix('Operating '):name for name in book.sheetnames if name.startswith('Operating ')}
        bindings=_operating_bindings(book,operating_spec,operating,mapping)
        audit=operating_audit(source,operating_spec,operating,bindings,sheet_mapping=mapping)
        if not audit['all_ledger_invariants_passed']:raise ValueError('Operating independent invariants failed')
        for item in audit['cell_checks']:
            sheet,address=item['address'].rsplit('!',1)
            add(mapping[sheet],address,item['expected_independent'],item['kind'])
        counts['operating']=len(expected)-sum(counts.values())
        for i,record in enumerate(holding['operating_monthly_bridge']):
            for ci,field in enumerate(OPERATING_FIELDS,1):
                add(SHEETS['operating'],L(ci)+str(i+3),record[field],'date' if field=='date' else 'integer' if field=='fiscal_year' else 'money')
        for section,key,fields in [('annual','parent',PARENT_FIELDS),('consolidated','group',GROUP_FIELDS)]:
            for yi,record in enumerate(holding[section]):
                for field in fields:add(SHEETS[key],L(yi+3)+str(row(field,fields)),record[field])
        if 'waterfall' in specs:
            from sheets_factory.workbook.partner_waterfall.schema import FIELDS,INTEGER_FIELDS,RATE_FIELDS
            rows=_rows(book['Partner Waterfall'])
            for field in ('lp_net_cashflow','gp_net_cashflow'):
                add('Partner Waterfall','B'+str(rows[_label(field)]),holding['partner_opening'][0][field])
            for yi,record in enumerate(holding['partner_waterfall']):
                for field in FIELDS:
                    if _label(field) not in rows:raise ValueError('Missing public partner financial row: '+field)
                    value=record[field]
                    if field in INTEGER_FIELDS:value=0 if value is None else int(value)
                    add('Partner Waterfall',L(yi+3)+str(rows[_label(field)]),value,
                        'nullable_rate' if field=='lp_xirr' else 'integer' if field in INTEGER_FIELDS else 'money')
        counts['holding']=len(expected)-sum(counts.values())
        # Coverage is checked against every currently visible derived formula;
        # blank masked cells are recovered through the same public row layout.
        owned={name for name in book.sheetnames if name.startswith(('Lease ','Operating ','Reopener ','Holding ','Contingent ','Partner '))}
        missing=[sheet.title+'!'+c.coordinate for sheet in book if sheet.title in owned
                 for c in sheet._cells.values() if c.data_type=='f' and (sheet.title,c.coordinate) not in expected]
        if missing:raise ValueError('Unbound public financial formulas: '+repr(missing[:10]))
        for (sheet,address),value in expected.items():
            kind=kinds[(sheet,address)]
            if kind=='date':value=value if isinstance(value,(date,datetime)) else date.fromisoformat(str(value)[:10])
            elif kind=='nullable_rate' and value is None:value=''
            elif kind in {'integer','control'}:value=int(Decimal(str(value)))
            else:
                number=Decimal(str(value))
                if not number.is_finite():raise ValueError('Nonfinite independent value')
                value=float(number)
            book[sheet][address]=value
        destination.parent.mkdir(parents=True,exist_ok=True);book.save(destination)
        report={'status':'public-only-independent-journal-witness-not-model-score','qualified':False,'task_count':0,
          'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'raw_output_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
          'public_contract_payload_sha256':contract_hashes,'independent_value_bindings':len(expected),
          'binding_counts':counts,'lease_checks':lease['checks'],'programme_checks':programme['checks'],
          'operating_checks':operating['checks'],'holding_checks':holding['checks'],
          'holding_regimes':holding['observed_regimes']}
        if report_path is not None:Path(report_path).write_text(json.dumps(report,indent=2,default=str)+'\n')
        return report
    finally:book.close()


def compile_public_composite_recovery():
    """Return a deterministic standalone script with only approved ledger code."""
    root=Path(__file__).resolve().parents[1]
    modules=('lease_finance/contract.py','lease_finance/ledger.py',
      'derived_regulatory/schema.py','derived_regulatory/ledger.py','derived_regulatory/validate.py',
      'derived_gold/ledger.py','derived_gold/validate.py','holding_treasury/schema.py','holding_treasury/ledger.py',
      'contingent_recovery/contract.py','contingent_recovery/solver.py',
      'partner_waterfall/contract.py','partner_waterfall/schema.py','partner_waterfall/ledger.py')
    archive=io.BytesIO();hashes={}
    with zipfile.ZipFile(archive,'w') as zip_:
        for package in ('sheets_factory','sheets_factory/workbook',
                        *('sheets_factory/workbook/'+name for name in ('lease_finance','derived_regulatory','derived_gold',
                                                                     'holding_treasury','contingent_recovery','partner_waterfall'))):
            info=zipfile.ZipInfo(package+'/__init__.py',date_time=(2000,1,1,0,0,0));zip_.writestr(info,'')
        for name in modules:
            source=(root/name).read_text();hashes[name]=hashlib.sha256(source.encode()).hexdigest()
            if name=='derived_gold/ledger.py':
                tree=ast.parse(source)
                defaults=next(node for node in tree.body if isinstance(node,ast.AnnAssign)
                              and isinstance(node.target,ast.Name) and node.target.id=='_DEFAULTS')
                if not isinstance(defaults.value,ast.Dict):raise ValueError('Operating default schema changed')
                defaults.value.values=[ast.Constant(None) for _ in defaults.value.keys]
                source=ast.unparse(ast.fix_missing_locations(tree))+'\n'
            info=zipfile.ZipInfo('sheets_factory/workbook/'+name,date_time=(2000,1,1,0,0,0))
            zip_.writestr(info,source,compress_type=zipfile.ZIP_DEFLATED)
    payload=base64.b64encode(archive.getvalue()).decode()
    tree=ast.parse(Path(__file__).read_text())
    runtime=[]
    for node in tree.body:
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            if isinstance(node,ast.ImportFrom) and node.module=='__future__':continue
            runtime.append(node)
        elif isinstance(node,ast.Assign):runtime.append(node)
        elif isinstance(node,ast.FunctionDef) and node.name!='compile_public_composite_recovery':runtime.append(node)
    code=ast.unparse(ast.fix_missing_locations(ast.Module(body=runtime,type_ignores=[])))
    bootstrap=("import sys,tempfile\n"+
      "_witness_temp=tempfile.TemporaryDirectory(prefix='composite-public-ledger-')\n"+
      "_witness_zip=Path(_witness_temp.name)/'public_ledgers.zip'\n"+
      f"_witness_zip.write_bytes(base64.b64decode({payload!r}))\n"+
      "sys.path.insert(0,str(_witness_zip))\n"+
      f"BUNDLED_SOURCE_SHA256={hashes!r}\n"+
      "if __name__=='__main__':\n"+
      " import argparse\n"+
      " p=argparse.ArgumentParser();p.add_argument('--input',default='/workspace/input.xlsx');p.add_argument('--output',default='/workspace/output.xlsx');p.add_argument('--report');a=p.parse_args()\n"+
      " r=recover_public(a.input,a.output,a.report);print(json.dumps({'bindings':r['independent_value_bindings'],'counts':r['binding_counts'],'input_sha256':r['input_sha256']}))\n")
    result=code+'\n'+bootstrap;compile(result,'composite_public_recovery.py','exec');return result
