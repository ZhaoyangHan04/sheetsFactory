#!/usr/bin/env python3
"""Prepare and independently verify a hypothetical cross-entity cashpool source."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from decimal import Decimal
import hashlib,importlib.util,json,time
from pathlib import Path
import openpyxl
from sheets_factory.workbook.cashpool.ledger import simulate_pool
from sheets_factory.workbook.cashpool.excel import emit_pool
from sheets_factory.workbook.engine import LibreOfficeEngine
from sheets_factory.workbook.compare import compare_workbooks

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):p=Path(p).resolve();return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def write(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def prepare(root,config_path,out):
    root,out=Path(root).resolve(),Path(out).resolve();config_path=Path(config_path);config_path=config_path if config_path.is_absolute() else root/config_path
    if out.exists():raise ValueError('Output exists; preserve it and use a new immutable directory')
    spec=json.loads(config_path.read_text());ancestor_path=root/spec['verified_source_manifest'];ancestor=json.loads(ancestor_path.read_text())
    if ancestor.get('financial_audit_passed') is not True or ancestor.get('status')!='financially_verified_planning_seed':raise ValueError('Verified operating source is required')
    if len(spec['members'])!=4 or {m['contract'] for m in spec['members']}!={'demand_provider','revolving_borrower','term_depositor','nav_borrower'}:raise ValueError('All four heterogeneous contracts are required')
    if set(spec['funding_order'])!={m['id'] for m in spec['members']} or len(spec['funding_order'])!=4:raise ValueError('A unique complete funding order is required')
    original=Path(ancestor['local_path'])
    if sha(original)!=ancestor['derived_workbook_sha256']:raise ValueError('Operating source SHA mismatch')
    for key in ('financial_audit','independent_expectations','public_scenario'):
        proof=ancestor[key]
        if sha(proof['path'])!=proof['sha256']:raise ValueError('Operating source evidence changed')
    out.mkdir(parents=True);private=out/'private';private.mkdir(mode=0o700);start=time.monotonic()
    recipe={p:ref(root/p) for p in ('scripts/build_cashpool_source.py','src/sheets_factory/workbook/cashpool/ledger.py','src/sheets_factory/workbook/cashpool/excel.py','src/sheets_factory/workbook/cashpool/schema.py','src/sheets_factory/workbook/engine.py','src/sheets_factory/workbook/uno_recalculate.py','src/sheets_factory/workbook/compare.py','tests/test_cashpool_source.py')};recipe['config']=ref(config_path)
    ledger_inputs={};project_specs={};source_bindings={};project_source_proofs={}
    for record in ancestor['entities']:
        i=record['id'];lp=Path(record['ledger']['path']);sp=Path(record['public_scenario']['path']);bp=Path(record['bindings']['path'])
        for p,key in ((lp,'ledger'),(sp,'public_scenario'),(bp,'bindings')):
            if sha(p)!=record[key]['sha256']:raise ValueError('Entity source evidence changed')
        value=json.loads(lp.read_text())
        for row in value['monthly']:
            row['net_income']=Decimal(row['net_income']);row['dividend']=Decimal(row['dividend'])
        value['valuation']['equity_exit']=Decimal(value['valuation']['equity_exit'])
        ledger_inputs[i]=value;project_specs[i]=json.loads(sp.read_text());source_bindings[i]=json.loads(bp.read_text());project_source_proofs[i]={key:record[key] for key in ('ledger','public_scenario','bindings')}
    used=[p for m in spec['members'] for p in m['projects']]
    if len(used)!=12 or len(set(used))!=12 or set(used)!=set(ledger_inputs):raise ValueError('Each of twelve verified associates must be assigned exactly once')
    ledger=simulate_pool(spec,ledger_inputs,project_specs)
    missing=[k for k in spec['required_regimes'] if not ledger['regimes'].get(k)]
    if missing:raise ValueError('Required mechanisms did not occur: '+','.join(missing))
    book=openpyxl.load_workbook(original,keep_links=False)
    removed=[name for name in book.sheetnames if not name.startswith(tuple(p+' ' for p in used))]
    for name in removed:book.remove(book[name])
    bindings=emit_pool(book,spec,source_bindings)
    raw=private/'cashpool_unrecalculated.xlsx';book.save(raw);book.close()
    source_expected=json.loads(Path(ancestor['independent_expectations']['path']).read_text())
    expected={address:value for address,value in source_expected.items() if address.split('!',1)[0] not in removed}
    flows={'net_income','capital_contribution','owner_dividend','external_income','cfo','cfi','cff'}
    for address,b in bindings['cells'].items():
        section=b['section'];m=b.get('month',1)-1
        if section=='member':value=ledger['monthly'][m][b['entity']][b['key']]
        elif section=='treasury':value=ledger['treasury'][m]['treasury'][b['key']]
        elif section=='event':value=ledger['treasury'][m]['events'][b['index']][b['key']]
        elif section=='group':value=ledger['group'][m][b['key']]
        elif section=='date':value=ledger_inputs['T01']['monthly'][m]['date']
        elif section=='annual':
            year=b['year'];key=b['key'];rows=ledger['group'][(year-1)*12:year*12]
            value=sum((r[key] for r in rows),Decimal(0)) if key in flows else rows[0 if key=='cash_open' else -1][key]
        else:raise ValueError('Unknown binding')
        expected[address]={'expected_independent':str(value),'kind':b['kind']}
    for joined,reference in bindings['parameter_cells'].items():
        i,key=joined.split(':');value=spec['treasury'][key] if i=='Treasury' else next(m for m in spec['members'] if m['id']==i).get(key,0)
        if key=='contract':continue
        address=reference.replace("'Pool Scenario'!",'Pool Scenario!').replace('$','')
        expected[address]={'expected_independent':str(value),'kind':'ratio' if any(v in key for v in ('rate','ownership')) else 'money'}
    rawbook=openpyxl.load_workbook(raw);formulas={s.title+'!'+c.coordinate:c.value for s in rawbook for c in s._cells.values() if c.data_type=='f'};sheets=rawbook.sheetnames[:];rawbook.close()
    if set(formulas)-set(expected):raise ValueError('Unbound formulas: '+str(sorted(set(formulas)-set(expected))[:10]))
    write(out/'public_scenario.json',{'scenario_id':spec['scenario_id'],'public_contract_version':spec['public_contract_version'],'parameters':spec,'public_rules':bindings['public_rules'],'reporting_scope':'Four tax-transparent holding partnerships plus Treasury; underlying projects are equity-method associates, not consolidated operating subsidiaries.','source_ancestor_sha256':ancestor['source_ancestor_sha256']})
    for name,value in (('ledger.json',ledger),('bindings.json',bindings),('independent_expectations.json',expected),('formula_snapshot.json',formulas)):
        write(private/name,value)
    # All financial source families and all new pool formula families are masked.
    from sheets_factory.workbook.derived_gold.task_templates import propose_project_task,_formula_rectangles
    reconstruction=json.loads(Path(ancestor['reconstruction_templates']['path']).read_text());masks=[]
    for entity in reconstruction['entities']:masks.extend(entity['financial_modeling_plan']['mask_ranges'])
    rawbook=openpyxl.load_workbook(raw)
    for sheet in rawbook:
        if sheet.title.endswith(' Holding') or sheet.title in ('Treasury','Group Statements','Group Summary'):
            cells={(c.row,c.column) for c in sheet._cells.values() if c.data_type=='f' and c.row!=1}
            masks.extend(_formula_rectangles(sheet.title,cells))
    rawbook.close()
    plan={'title':'Restore the integrated project investment and cross-entity cashpool model','business_context':'Four holding partnerships finance non-controlling project investments through heterogeneous treasury contracts.','public_instruction':'Complete the missing project and investment-partnership financial calculations. Reconstruct the underlying project forecasts, the four holding accounts, the shared treasury settlement and bank facility, and the consolidated statements. Use Portfolio Index for the reporting boundary and cashpool contracts, Pool Scenario and Pool Commitments for provided terms, and each project\'s own Read Me and Scenario for its operating budget. Preserve provided inputs, dates and unrelated formulas. Read /app/input.xlsx and save /app/output.xlsx.','public_rules':['Apply the distinct contracts and accounting perimeter documented in Portfolio Index.'],'scenario_inputs':[],'edits':[],'mask_ranges':masks,'target_sheets':list(dict.fromkeys(r['sheet'] for r in masks)),'reference_evidence':[{'sheet':'Portfolio Index','cell':'A'+str(n+3),'policy':rule} for n,rule in enumerate(bindings['public_rules'])],'protected_inputs':["'Pool Scenario'!A1:C200","'Pool Commitments'!A1:F50"],'native_issues':[],'involved_sheets':sheets}
    write(private/'financial_modeling_plan.json',plan)
    manifest={'schema_version':1,'status':'prepared_pending_real_LO','created_at':datetime.now(timezone.utc).isoformat(),'qualified':False,'task_count':0,'selected':[],'download_url':'derived-seed-pool:cross-entity-cashpool','archive_sha256':None,'unique_workbooks_inspected':0,'ancestor_unique_count':1,'source_ancestor_sha256':ancestor['source_ancestor_sha256'],'source_ancestor':ancestor['source_ancestor'],'operating_source':ref(ancestor_path),'operating_workbook':ref(original),'project_source_proofs':project_source_proofs,'removed_prior_scope_sheets':removed,'raw_workbook':ref(raw),'public_scenario':ref(out/'public_scenario.json'),'recipe':recipe,'sheet_count':len(sheets),'formula_count':len(formulas),'new_pool_formula_count':len(bindings['cells']),'all_formula_cells_have_independent_expectations':True,'independent_ledger_checks':ledger['checks'],'observed_regimes':ledger['regimes'],'api_calls':0,'llm_tokens':0,'elapsed_seconds':round(time.monotonic()-start,6)}
    for name in ('ledger','bindings','independent_expectations','formula_snapshot','financial_modeling_plan'):manifest[name]=ref(private/(name+'.json'))
    if any(sha(v['path'])!=v['sha256'] for v in recipe.values()):raise ValueError('Cashpool recipe changed during build')
    write(out/'manifest.json',manifest);return manifest


def verify(root,out):
    out=Path(out).resolve();m=json.loads((out/'manifest.json').read_text())
    if m['status']!='prepared_pending_real_LO':raise ValueError('Only an unattempted immutable source may be verified')
    for proof in [m[k] for k in ('raw_workbook','public_scenario','ledger','bindings','independent_expectations','formula_snapshot','financial_modeling_plan')]+list(m['recipe'].values()):
        if sha(proof['path'])!=proof['sha256']:raise ValueError('Immutable proof changed')
    # Reproduce the independent cashpool journal from immutable project journals.
    spec=json.loads(Path(m['recipe']['config']['path']).read_text());inputs={};ps={}
    for i,refs in m['project_source_proofs'].items():
        for value in refs.values():
            if sha(value['path'])!=value['sha256']:raise ValueError('Project input changed')
        v=json.loads(Path(refs['ledger']['path']).read_text())
        for r in v['monthly']:r['net_income']=Decimal(r['net_income']);r['dividend']=Decimal(r['dividend'])
        v['valuation']['equity_exit']=Decimal(v['valuation']['equity_exit']);inputs[i]=v;ps[i]=json.loads(Path(refs['public_scenario']['path']).read_text())
    replay=simulate_pool(spec,inputs,ps)
    if json.loads(json.dumps(replay,default=str))!=json.loads(Path(m['ledger']['path']).read_text()):raise ValueError('Independent journal replay differs')
    engine=LibreOfficeEngine(root);start=time.monotonic();m.update(status='verification_running',runtime=engine.metadata());write(out/'manifest.json',m)
    try:
        first=out/'private/first_recalculation.xlsx';final=out/'cashpool_model.xlsx';engine.recalculate(Path(m['raw_workbook']['path']),first);engine.recalculate(first,final)
        stable=compare_workbooks(first,first,final);cached=openpyxl.load_workbook(final,data_only=True);formulas=openpyxl.load_workbook(final)
        api=module(Path(root)/'scripts/build_portfolio_source.py','_cashpool_matches');expected=json.loads(Path(m['independent_expectations']['path']).read_text());checks=[]
        for address,want in expected.items():
            sheet,cell=address.rsplit('!',1);got=cached[sheet][cell].value;checks.append({'address':address,**want,'observed':str(got),'passed':api._matches(got,want['expected_independent'],want['kind'])})
        actual={s.title+'!'+c.coordinate for s in formulas for c in s._cells.values() if c.data_type=='f'};snapshot=json.loads(Path(m['formula_snapshot']['path']).read_text());uncovered=sorted(actual-set(expected));errors=[{'address':s.title+'!'+c.coordinate,'value':c.value} for s in cached for c in s._cells.values() if c.data_type=='e'];failed=[v for v in checks if not v['passed']]
        passed=not failed and not errors and not uncovered and actual==set(snapshot) and stable['reward']==1
        audit={'passed':passed,'checked_cells':len(checks),'formula_count':len(actual),'all_formula_cells_independently_covered':not uncovered,'uncovered':uncovered,'errors':errors,'mismatches':failed,'cell_checks':checks,'independent_ledger_checks':replay['checks'],'two_recalculations_typed_stable':stable['reward']==1}
        write(out/'private/financial_audit.json',audit);write(out/'private/stability.json',stable);cached.close();formulas.close();m.update(status='financially_verified_planning_seed' if passed else 'rejected_financial_source',financial_audit_passed=passed,financial_audit=ref(out/'private/financial_audit.json'),stability=ref(out/'private/stability.json'),local_path=str(final),derived_workbook_sha256=sha(final),verification_elapsed_seconds=round(time.monotonic()-start,6),unique_workbooks_inspected=1)
        if passed:
            evidence={'classification':'cross_entity_cashpool','financial_modeling_eligible':True,'debugging_eligible':True,'finance_eligible':True,'scenario_required':False,'financial_seed_verified':True,'task_business_correctness_certified':False,'source_business_issues':[],'audit_proofs':{k:m[k] for k in ('financial_audit','stability','ledger','public_scenario')},'actual_regimes':m['observed_regimes'],'public_contract_version':spec['public_contract_version']}
            m['selected']=[{'sha256':sha(final),'source_sha256':sha(final),'local_path':str(final),'source_kind':'derived_hypothetical_cashpool','source_url':m['source_ancestor']['source_url'],'source_ancestor_sha256':m['source_ancestor_sha256'],'source_lineage':{'source_ancestor':m['source_ancestor'],'derived_operating_source':m['operating_source']},'scenario_id':spec['scenario_id'],'case_id':'CASHPOOL4','sheet_count':m['sheet_count'],'nonempty_sheet_count':m['sheet_count'],'formula_count':m['formula_count'],'modes':['financial_modeling','debugging'],'finance_eligible':True,'financial_modeling_eligible':True,'debugging_eligible':True,'scenario_required':False,'qualified':False,'task_count':0,'finance_evidence':evidence,'verification_backend':'independent_Decimal_journal_and_real_LibreOffice'}]
        write(out/'manifest.json',m);return m
    except Exception as e:
        m.update(status='verification_failed',error={'type':type(e).__name__,'message':str(e)});write(out/'manifest.json',m);raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=Path('config/derived_cashpool_v1.json'));p.add_argument('--output',type=Path);p.add_argument('--verify-existing',type=Path);p.add_argument('--recalculate',action='store_true');a=p.parse_args()
    if a.verify_existing:m=verify(ROOT,a.verify_existing)
    else:
        out=a.output or ROOT/'outputs/research'/('cashpool_source_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));m=prepare(ROOT,a.config,out)
        if a.recalculate:m=verify(ROOT,out)
    print(json.dumps({k:m.get(k) for k in ('status','local_path','formula_count','new_pool_formula_count','financial_audit_passed','observed_regimes','qualified','task_count')}));return 0 if m['status'] in ('prepared_pending_real_LO','financially_verified_planning_seed') else 1
if __name__=='__main__':raise SystemExit(main())
