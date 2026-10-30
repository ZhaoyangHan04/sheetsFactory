"""Build and actually verify an isolated hypothetical regulatory policy seed."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
from .source import prepare_spec
from .ledger import simulate
from .excel import create_workbook
from .validate import audit_workbook
from ..engine import LibreOfficeEngine


def ref(path):
    path=Path(path).resolve();return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}

def write(path,value):Path(path).write_text(json.dumps(value,indent=2,default=str)+'\n')


def build(config_path,output,project_root):
    config_path,output,project_root=Path(config_path),Path(output),Path(project_root)
    output.mkdir(parents=True,exist_ok=False);private=output/'private';private.mkdir()
    started=time.monotonic();config=json.loads(config_path.read_text())
    spec=prepare_spec(config['source_path'],config);ledger=simulate(spec)
    write(output/'public_scenario.json',spec);write(private/'ledger.json',ledger)
    if not all(value is True for value in ledger['checks'].values()):raise ValueError('Independent financial checks failed')
    contract=Path(__file__).with_name('POLICY.md')
    public=contract.read_text().split('## Final financial outputs and oracle')[0]
    raw=private/'unrecalculated.xlsx';emission=create_workbook(config['source_path'],spec,raw,public)
    write(private/'emission.json',emission)
    engine=LibreOfficeEngine(project_root,'sheetsfactory-lo:24.2-openpyxl315-v1',180)
    runtime=engine.metadata()
    if runtime['image_id']!='sha256:50d67001fbf6c74bcdb8dca4b29863585561abcffce8ccc3bf4ef3cdf5203b2c':raise ValueError('Unexpected regulatory runtime image')
    goal=engine.recalculate(raw,output/'regulatory_model.xlsx');audit=audit_workbook(goal,spec,ledger)
    write(private/'financial_audit.json',audit)
    if not audit['passed']:raise ValueError('Actual LO financial audit failed: '+str(audit['mismatches'][:3]))
    stable=engine.check_stable(goal,private/'stability');write(private/'stability.json',stable)
    if not stable['stable']:raise ValueError('Actual LO source is not stable')
    manifest={'schema_version':1,'status':'independently_verified_hypothetical_reopener_seed',
        'qualified':False,'task_count':0,'created_at':datetime.now(timezone.utc).isoformat(),
        'local_path':str(goal.resolve()),'derived_workbook_sha256':ref(goal)['sha256'],
        'source_ancestor':ref(config['source_path']),'source_url':config['official_url'],
        'public_scenario':ref(output/'public_scenario.json'),'ledger':ref(private/'ledger.json'),
        'financial_audit':ref(private/'financial_audit.json'),'stability':ref(private/'stability.json'),
        'runtime':runtime,'config':ref(config_path),'public_contract':ref(contract),
        'new_formula_count':emission['new_formula_count'],'observed_regimes':ledger['observed_regimes'],
        'metadata_adapter':emission['metadata_adapter'],'api_calls':0,'elapsed_seconds':round(time.monotonic()-started,3),
        'calculation_implementations':{str(path.relative_to(project_root)):ref(path) for path in Path(__file__).parent.glob('*.py')}}
    evidence={'classification':'hypothetical_incremental_regulatory_capital_reopener',
        'financial_seed_verified':True,'financial_modeling_eligible':True,'debugging_eligible':False,
        'source_business_issues':[],'scope':audit['scope'],
        'audit_proofs':{key:manifest[key] for key in ('public_scenario','ledger','financial_audit','stability')},
        'actual_regimes':ledger['observed_regimes'],'qualification':'Source scoped verification only; no constructed task or difficulty qualification.'}
    manifest['selected']=[{'sha256':manifest['derived_workbook_sha256'],'source_sha256':manifest['derived_workbook_sha256'],
        'local_path':str(goal.resolve()),'source_kind':'derived_hypothetical_regulatory_reopener',
        'source_url':config['official_url'],'modes':['financial_modeling'],'financial_modeling_eligible':True,
        'finance_eligible':True,'finance_evidence':evidence,'qualified':False,'task_count':0}]
    write(output/'seed_manifest.json',manifest)
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build(args.config,args.output,Path.cwd());print(json.dumps({'seed_manifest':str(args.output/'seed_manifest.json'),'new_formula_count':result['new_formula_count'],'elapsed_seconds':result['elapsed_seconds']}))
