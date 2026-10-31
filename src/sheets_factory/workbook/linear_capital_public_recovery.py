"""Public native-table reconstruction for the linear portfolio family.

Only provided workbook tables, public notes and the current brief determine the
financial inputs. Decimal B, CP-SAT and the Excel compiler are shared frozen
implementations; this is not a third independent ledger or global proof.
"""
from __future__ import annotations

import hashlib
import ast
import inspect
import json
from pathlib import Path
import re
import shutil
import tempfile
from copy import deepcopy
import subprocess
import time
import uuid

import openpyxl

from .linear_capital_portfolio import excel, ledger, model_b, spec

SETTING = 'linear_capital_portfolio'
BACKEND = 'linear_public_native_tables_shared_decimal_cp_sat_excel'
REPLAY_SECONDS = 7200
IMAGE = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
PROJECT_COLUMNS = ('id','name','region','sector','asset_cost_pence','t0_ltv_bp',
    'operating_start_year','depreciation_years','base_annual_revenue_pence',
    'base_annual_opex_pence','revenue_growth_factor_bp','opex_growth_factor_bp',
    'bank_rate_bp','debt_policy','debt_maturity_year','tax_rate_bp','discount_rate_bp',
    'terminal_sale_proceeds_pence','lp_commitment_pence')
SCENARIO_COLUMNS = ('revenue_factors_bp','opex_factors_bp','sale_factors_bp','interest_spread_bp')
INPUT_SHEETS = ('ContractNotes','Projects','Scenarios','ResourceUse','Limits','Sites','Prerequisites')
PUBLIC_TABLE_BOUNDS = {'ContractNotes':(64,2),'Projects':(268,22),'Scenarios':(16,24),
    'ResourceUse':(242,362),'Limits':(764,3),'Sites':(43,7),'Prerequisites':(83,5),'Portfolio':(256,512)}
PUBLIC_FUNCTIONS = ('require','_provided','_header','_rows','_put','_parse_book',
    'parse_public_workbook','_physical','write_reconstructed_model','solve_public_model','recover_public')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _provided(sheet, row, column):
    # Read-only Worksheet.cell repeatedly restarts its XML iterator. Cache each
    # bounded provided table once so the production parser stays linear.
    if not hasattr(sheet,'_linear_public_cells'):
        height,width=PUBLIC_TABLE_BOUNDS[sheet.title]
        require((sheet.max_row or 0)<=height and (sheet.max_column or 0)<=width,
            'A provided business table exceeds its bounded native layout')
        sheet._linear_public_cells={(c.row,c.column):(c.value,c.data_type)
            for cells in sheet.iter_rows(max_row=height,max_col=width) for c in cells if c.value is not None}
    value,kind=sheet._linear_public_cells.get((row,column),(None,'n'))
    require(kind != 'f' and type(value) is not bool,
        'A provided public primitive cannot be a formula or Boolean')
    require(value is None or type(value) in (str,int), 'A public primitive must be text or an exact integer')
    return value


def _header(sheet, expected):
    require([_provided(sheet,1,c) for c in range(1,len(expected)+1)] == list(expected),
        'A required public business-table header differs: '+sheet.title)


def _rows(sheet, start, maximum):
    for row in range(start,start+maximum+1):
        if _provided(sheet,row,1) is None:
            return
        require(row < start+maximum, 'A public table exceeds its complete bounded scope')
        yield row


def _put(root, path, value):
    for part in path[:-1]:
        root=root.setdefault(part,{})
        require(type(root) is dict, 'Conflicting public capacity paths')
    require(path[-1] not in root, 'A public primitive is duplicated')
    root[path[-1]]=value


def _parse_book(book):
    require(all(name in book.sheetnames for name in INPUT_SHEETS), 'Required public input tables are missing')
    notes=book['ContractNotes']
    require(_provided(notes,1,1)=='Ring-fenced portfolio: public financial contract'
        and [_provided(notes,i+3,1) for i in range(len(excel.PUBLIC_RULES))]==list(excel.PUBLIC_RULES),
        'The complete public financial policies are required')
    projects=book['Projects']
    fields=[str(_provided(projects,1,col)).lower().replace(' ','_') for col in range(1,len(PROJECT_COLUMNS)+1)]
    require(len(set(fields))==len(fields) and set(fields)==set(PROJECT_COLUMNS),
        'The complete labelled project primitive columns are required')
    candidates=[{field:_provided(projects,row,col) for col,field in enumerate(fields,1)}
        for row in _rows(projects,2,240)]
    ids=[p['id'] for p in candidates]
    require(ids and ids==list(spec.PROJECT_IDS[:len(ids)]), 'The complete ordered public project IDs differ')
    n=len(ids)
    require(_provided(projects,n+4,1)=='First fiscal calendar year', 'The public fiscal-year origin is missing')
    fiscal=_provided(projects,n+4,2)
    years=[]
    for col in range(2,23):
        value=_provided(projects,n+6,col)
        if value is None: break
        years.append(value)
    require(years==list(range(1,len(years)+1)) and 1<=len(years)<=20,
        'The complete public fiscal calendar differs')
    scenarios=book['Scenarios']
    _header(scenarios,['Scenario','Name','Assumption / basis points',*['FY'+str(y) for y in years]])
    scenario_map={}
    for row in _rows(scenarios,2,12):
        sid,name,field=(_provided(scenarios,row,col) for col in (1,2,3))
        require(type(field) is str and field.lower().replace(' ','_') in SCENARIO_COLUMNS,
            'An unknown public scenario policy was supplied')
        field=field.lower().replace(' ','_')
        item=scenario_map.setdefault(sid,{'id':sid,'name':name})
        require(item['name']==name and field not in item, 'A public scenario row is duplicated or inconsistent')
        item[field]={str(y):_provided(scenarios,row,i+4) for i,y in enumerate(years)}
    sids=list(scenario_map)
    require(sids and sids==list(spec.SCENARIO_IDS[:len(sids)]), 'The complete public scenario IDs differ')
    usage=book['ResourceUse'];require(_provided(usage,1,1)=='Project','Public resource labels are missing')
    resource_columns=[]
    for col in range(2,362):
        label=_provided(usage,1,col)
        if label is None: break
        match=re.fullmatch(r'(U[0-9]{2}) (S[0-9]{2}) FY([1-9][0-9]*) / units',str(label))
        require(match is not None,'A public resource/calendar header is invalid')
        resource_columns.append((match[1],match[2],int(match[3]),col))
    resources=list(dict.fromkeys(r for r,_,_,_ in resource_columns))
    require(resources and resources==list(spec.RESOURCE_IDS[:len(resources)])
        and [(r,s,y) for r,s,y,_ in resource_columns]==[(r,s,y) for r in resources for s in sids for y in years],
        'The complete Cartesian public resource scope differs')
    for index,p in enumerate(candidates,2):
        require(_provided(usage,index,1)==p['id'],'A public resource row names a different project')
        p['resource_usage_units']={r:{sid:{} for sid in sids} for r in resources}
        for resource,sid,year,col in resource_columns:
            p['resource_usage_units'][resource][sid][str(year)]=_provided(usage,index,col)
    limits=book['Limits'];_header(limits,['Provided capacity','Limit / pence or stated units'])
    shared={}
    families={'initial_sponsor_equity_pence','annual_new_lp_pence','annual_debt_close_pence',
        'resource_capacity_units','region_exposure_pence','sector_exposure_pence'}
    for row in _rows(limits,2,761):
        label=_provided(limits,row,1);require(type(label) is str,'A capacity label must be public text')
        parts=label.split(' / ');parts[0]=parts[0].replace(' ','_')
        require(parts[0] in families,'An unknown public capacity was supplied')
        _put(shared,parts,_provided(limits,row,2))
    require(set(shared)==families,'The complete public capacity families are required')
    regions=list(shared['region_exposure_pence']);sectors=list(shared['sector_exposure_pence'])
    groups=[];sites=book['Sites'];_header(sites,['Alternative group','Business purpose'])
    for row in _rows(sites,2,40):
        members=[]
        for col in range(3,7):
            value=_provided(sites,row,col)
            if value is None:break
            members.append(value)
        groups.append({'id':_provided(sites,row,1),'description':_provided(sites,row,2),'project_ids':members})
    edges=[];prereqs=book['Prerequisites'];_header(prereqs,['Relationship','Dependent','Enabler','Business purpose'])
    for row in _rows(prereqs,2,80):
        edges.append({key:_provided(prereqs,row,col) for col,key in enumerate(('id','dependent','prerequisite','business_reason'),1)})
    raw={'kind':'hypothetical_ringfenced_linear_capital_portfolio','version':1,
        'dimension_mode':'production' if n==240 else 'toy','fiscal_year_start':fiscal,
        'years':years,'project_ids':ids,'scenario_ids':sids,'resource_ids':resources,
        'region_ids':regions,'sector_ids':sectors,'projects':candidates,'scenarios':list(scenario_map.values()),
        'shared_limits':shared,'exclusivity_groups':groups,'prerequisites':edges,
        'provenance':{'hypothetical':True,'description':'Reconstructed solely from provided public native business tables',
            'ancestor_sha256':[]}}
    public=spec.load_spec(raw)
    require(book.sheetnames==[*INPUT_SHEETS,*ids,'Portfolio','GroupSummary','Constraints'],
        'The original public worksheet identities/order must be preserved')
    portfolio=book['Portfolio']
    require(_provided(portfolio,5,1)=='Project' and _provided(portfolio,5,2)=='Choose0 or1 / common plan'
        and [_provided(portfolio,i+6,1) for i in range(n)]==ids,
        'The public common-decision identities differ')
    return public


def parse_public_workbook(path, *, instruction_path=None):
    if instruction_path is not None:
        text=Path(instruction_path).read_text(encoding='utf-8')
        require(bool(text.strip()) and len(text.encode())<=128*1024, 'A bounded current public brief is required')
    book=openpyxl.load_workbook(path,read_only=True,data_only=False,keep_links=False)
    try:return _parse_book(book)
    finally:book.close()


def _physical(book):
    return {(sheet.title,cell.coordinate):cell.value for sheet in book for row in sheet for cell in row if cell.value is not None}


def write_reconstructed_model(source, destination, public, plan):
    """Shared compiler; source formulas/financial values are never an oracle."""
    public=spec.load_spec(public);plan=spec.validate_plan(public,plan)
    destination=Path(destination);require(not destination.exists(),'Preserve previous public replay outputs')
    with tempfile.TemporaryDirectory(prefix='linear-public-compile-') as temporary:
        native=Path(temporary)/'native.xlsx'
        bindings=excel.emit_workbook(native,public,plan=plan,max_formulas=2_000_000)
        expected=openpyxl.load_workbook(native,data_only=False,keep_links=False)
        actual=openpyxl.load_workbook(source,data_only=False,keep_links=False)
        try:
            require(actual.sheetnames==expected.sheetnames,'The public workbook layout differs')
            expected_values=_physical(expected);before=_physical(actual)
            targets={(r['sheet'],r['cell']) for key in ('financial_bindings','arithmetic_bindings','decision_bindings') for r in bindings[key]}
            provided=set(expected_values)-targets
            require(set(before)<=set(expected_values),'Unexpected public data outside the native business model')
            require(all(type(before.get(key)) is type(expected_values[key]) and before.get(key)==expected_values[key]
                for key in provided),'A provided public primitive or label changed')
            for sheet,cell in targets:
                actual[sheet][cell]=expected[sheet][cell].value
            after=_physical(actual)
            require(set(after)==set(expected_values) and all(after[key]==before[key] for key in provided),
                'Public reconstruction changed provided inputs or physical scope')
            actual.save(destination)
            return {'physical_formulas':bindings['formula_count'],'financial_targets':len(bindings['financial_bindings']),
                'common_choices':len(bindings['decision_bindings']),'provided_cells_preserved':len(provided),
                'shared_Excel_compiler':True,'independent_formula_implementation':False}
        finally:actual.close();expected.close()


def solve_public_model(model, *, time_limit_seconds, threads, log_path, model_path):
    """Shared B solver with only its prospective worker ceiling changed.

    Financial code, the exact integer matrix, gap-zero policy and terminal status
    checks remain the frozen B implementation. This is a generation-side solver.
    """
    tree=ast.parse(inspect.getsource(model_b.solve_cp_sat))
    expected=ast.dump(ast.parse('1<=threads<=2',mode='eval').body)
    replacements=0
    for node in ast.walk(tree):
        if isinstance(node,ast.Compare) and ast.dump(node)==expected:
            node.comparators[-1]=ast.Constant(16);replacements+=1
        if isinstance(node,ast.Constant) and node.value=='The reference uses at most the declared two CPU workers':
            node.value='The public recovery uses at most its declared sixteen CPU workers'
    require(replacements==1,'The frozen B solver worker guard changed')
    namespace=dict(vars(model_b))
    exec(compile(ast.fix_missing_locations(tree),'<public-worker-bound-B>','exec'),namespace)
    return namespace['solve_cp_sat'](model,time_limit_seconds=time_limit_seconds,threads=threads,
        log_path=log_path,model_path=model_path)


def recover_public(source, destination, report_path, *, instruction_path, time_limit_seconds=3600, threads=16):
    """Explicit public optimization; never called by prepare or module import."""
    require(type(time_limit_seconds) is int and 1<=time_limit_seconds<=6900
        and type(threads) is int and 1<=threads<=16,'Bounded offline optimizer time/workers are required')
    public=parse_public_workbook(source,instruction_path=instruction_path)
    matrix=model_b.build_model(public)
    folder=Path(destination).parent
    solved=solve_public_model(matrix,time_limit_seconds=time_limit_seconds,threads=threads,
        log_path=folder/'solver.log',model_path=folder/'native_model.pbtxt')
    with (folder/'native_solver.json').open('x',encoding='utf-8') as handle:
        json.dump(solved,handle,indent=2,allow_nan=False)
    require(solved.get('status')=='OPTIMAL' and solved.get('checked_optimal') is True
        and solved.get('exact_plan_check',{}).get('passed') is True,
        'Public optimizer did not establish an exact checked optimum')
    plan=spec.validate_plan(public,solved['plan'])
    exact=model_b.check_plan(matrix,plan)
    require(exact['passed'] and exact['objective_pence']==solved['objective_pence'],
        'The public selected plan does not satisfy all exact integer rows/objective')
    forward=ledger.simulate(public,plan)
    require(forward['feasible'] is True and forward['all_standalone_feasible'] is True
        and forward['objective_pence']==solved['objective_pence'], 'The public financial forward differs from its optimizer')
    scope=write_reconstructed_model(source,destination,public,plan)
    report={'kind':'public_native_linear_capital_reconstruction','version':1,'passed':True,
        'public_financial_specification_sha256':spec.canonical_sha256(public),'project_count':len(public['project_ids']),
        'scenario_count':len(public['scenario_ids']),'year_count':len(public['years']),
        'constraint_count':len(matrix['rows']),'checked_optimal':True,'objective_pence':forward['objective_pence'],
        'all_standalone_feasible':True,'scope':scope,'shared_Decimal_B':True,'shared_CP_SAT':True,
        'shared_Excel_compiler':True,'third_independent_ledger':False,'second_independent_global_proof':False,
        'private_answer_access':False,'financial_outputs_are_formulas_not_cached_literal_answers':True,
        'offline_solver':{'threads':threads,'time_limit_seconds':time_limit_seconds},
        'offline_recovery_is_model_attempt':False}
    with Path(report_path).open('x',encoding='utf-8') as handle:json.dump(report,handle,indent=2,allow_nan=False)
    return report


def public_program_source():
    imports='from pathlib import Path\nimport ast,inspect,json,re,tempfile\nimport openpyxl\nfrom portfolio import spec,ledger,model_b,excel\n'
    constants='\n'.join(name+' = '+repr(globals()[name]) for name in ('PROJECT_COLUMNS','SCENARIO_COLUMNS','INPUT_SHEETS','PUBLIC_TABLE_BOUNDS'))
    return imports+constants+'\n\n'+'\n\n'.join(inspect.getsource(globals()[name]) for name in PUBLIC_FUNCTIONS)


def reference(path):
    from ..pipelines.linear_capital_quality import reference as checked_reference
    return checked_reference(path)


def _write(path,value):
    with Path(path).open('x',encoding='utf-8') as handle:
        json.dump(value,handle,indent=2,allow_nan=False);handle.write('\n')
    return reference(path)


def inventory(directory):
    from .linear_capital_portfolio.optimization_runtime import _walk_files
    return {name:reference(path) for name,path in _walk_files(Path(directory)).items()}


def public_implementation_recipe():
    from .linear_capital_portfolio import optimization_runtime
    return {name:reference(module.__file__) for name,module in
        [('transport',__import__(__name__,fromlist=[''])),('spec',spec),('ledger',ledger),
         ('model_b',model_b),('excel',excel),('vendor_copy_support',optimization_runtime)]}


_RUNTIME_SESSIONS = {}


def prepare_public_runtime(output, *, vendor_site_packages=None):
    """Explicit generic code/vendor copy only: no solver, finance or services."""
    from .linear_capital_portfolio import optimization_runtime as runtime
    output=Path(output).absolute()
    require(output==output.resolve() and not output.exists(),'Use a fresh real runtime preparation directory')
    output.mkdir(parents=True);directory=output/'runtime';directory.mkdir()
    try:
        recipe=public_implementation_recipe();package=directory/'portfolio';package.mkdir()
        (package/'__init__.py').write_bytes(b'')
        for name,module in [('spec',spec),('ledger',ledger),('model_b',model_b),('excel',excel)]:
            shutil.copyfile(module.__file__,package/(name+'.py'))
        (directory/'public_program.py').write_text(public_program_source(),encoding='utf-8')
        sources=runtime._copy_vendor(runtime.VENDOR_SITE_PACKAGES if vendor_site_packages is None else vendor_site_packages,
            directory/'vendor')
        require(recipe==public_implementation_recipe(),'Public runtime code changed during preparation')
        return _write(output/'preparation.json',{'kind':'prepared_public_linear_capital_recovery_runtime','version':1,
            'directory':str(directory),'inventory':inventory(directory),'public_recipe':recipe,
            'vendor_sources':sources,'solver_versions':runtime.DISTRIBUTIONS,'image_id':IMAGE,
            'model_calls':0,'LO_calls':0,'solver_calls':0,'financial_forwards':0,'qualified':False})
    except BaseException as error:
        _write(output/'failure.json',{'type':type(error).__name__,'error':str(error),'solver_calls':0,'model_calls':0,'LO_calls':0})
        raise


def validate_public_runtime(value):
    from ..pipelines.linear_capital_quality import References
    from .linear_capital_portfolio import optimization_runtime as runtime
    record=value if isinstance(value,dict) else reference(value)
    key=(record['path'],record['sha256'],record['bytes'])
    if key in _RUNTIME_SESSIONS:
        result,refs=_RUNTIME_SESSIONS[key];refs.guard()
        require(result['public_recipe']==public_implementation_recipe(),'The public runtime implementation changed')
        return deepcopy(result)
    refs=References();result=refs.read(record)
    require(result.get('kind')=='prepared_public_linear_capital_recovery_runtime'
        and type(result.get('version')) is int and result['version']==1
        and result.get('public_recipe')==public_implementation_recipe()
        and result.get('solver_versions')==runtime.DISTRIBUTIONS and result.get('image_id')==IMAGE
        and result.get('qualified') is False
        and all(type(result.get(k)) is int and result[k]==0 for k in ('model_calls','LO_calls','solver_calls','financial_forwards')),
        'A complete frozen zero-execution public runtime is required')
    directory=Path(result['directory']);require(directory==directory.resolve(),'A real runtime directory is required')
    actual=inventory(directory);require(actual==result['inventory'],'The complete public runtime inventory changed')
    core={'portfolio/__init__.py','portfolio/spec.py','portfolio/ledger.py','portfolio/model_b.py','portfolio/excel.py','public_program.py'}
    require(set(actual)==core|{'vendor/'+name for name in result['vendor_sources']},
        'The runtime contains undeclared files or private source artifacts')
    require((directory/'public_program.py').read_text()==public_program_source()
        and (directory/'portfolio/__init__.py').read_bytes()==b'', 'The standalone public program differs')
    for name in ('spec','ledger','model_b','excel'):
        require({k:actual['portfolio/'+name+'.py'][k] for k in ('sha256','bytes')}
            == {k:result['public_recipe'][name][k] for k in ('sha256','bytes')},'The shared public financial/compiler code differs')
    source_root=runtime.VENDOR_SITE_PACKAGES.absolute()
    require({name.split('/')[0] for name in result['vendor_sources']}==runtime.VENDOR_ROOTS,
        'The complete approved solver environment is required')
    for name,original in result['vendor_sources'].items():
        require(not Path(name).is_absolute() and all(p not in ('','.','..') for p in name.split('/'))
            and original['path']==str(source_root/name),'A vendor source escaped the approved solver environment')
        refs.check(original)
        require({k:actual['vendor/'+name][k] for k in ('sha256','bytes')}
            == {k:original[k] for k in ('sha256','bytes')},'A public solver package copy differs')
    from email.parser import Parser
    for distribution,version in runtime.DISTRIBUTIONS.items():
        metadata=directory/'vendor'/(distribution+'-'+version+'.dist-info')/'METADATA'
        require(metadata.is_file(),'A declared solver distribution lacks metadata')
        fields=Parser().parsestr(metadata.read_text())
        require(fields.get('Version')==version and fields.get('Name','').lower().replace('-','_')==distribution,
            'The installed solver distribution identity/version changed')
    refs.walk(result);_RUNTIME_SESSIONS[key]=(deepcopy(result),refs)
    return deepcopy(result)


_RUNNER = '''import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib,json,re
root=Path('/app')
sys.path.insert(0,str(root/'vendor'))
nonce=(root/'public_nonce.txt').read_text()
if not re.fullmatch('[0-9a-f]{32}\\n',nonce):raise ValueError('Missing fresh public nonce')
expected=json.loads((root/'public_inventory.json').read_text())
actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
if actual != set(expected)|{'public_inventory.json'}:raise ValueError('Unexpected initial public files')
for name,wanted in expected.items():
 p=root/name
 if p.is_symlink() or p.stat().st_size!=wanted['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=wanted['sha256']:
  raise ValueError('Public input or generic runtime changed')
configuration=json.loads((root/'offline_recovery.json').read_text())
from public_program import recover_public
report=recover_public(root/'input.xlsx',root/'recovered.xlsx',root/'public_recovery_report.json',
 instruction_path=root/'instruction.md',time_limit_seconds=configuration['solver_seconds'],threads=configuration['solver_threads'])
print(json.dumps(report),flush=True)
'''
GENERATED_FILES = ('recovered.xlsx','public_recovery_report.json','native_solver.json','native_model.pbtxt',
    'native_model.pbtxt.parameters.pbtxt','solver.log')


def prepare_public_bundle(source, instruction, runtime_preparation, destination, *, nonce, offline_configuration=None):
    require(type(nonce) is str and re.fullmatch('[0-9a-f]{32}',nonce), 'A fresh public nonce is required')
    runtime=validate_public_runtime(runtime_preparation)
    destination=Path(destination).absolute();require(destination==destination.resolve() and not destination.exists(),
        'Preserve every prior public replay directory')
    destination.mkdir(parents=True)
    for name,record in runtime['inventory'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts,'A runtime file escaped its bundle')
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(record['path'],target)
    shutil.copyfile(source,destination/'input.xlsx')
    require(type(instruction) is str and instruction.strip() and len(instruction.encode())<=128*1024,'A bounded current public brief is required')
    (destination/'instruction.md').write_text(instruction,encoding='utf-8')
    (destination/'public_nonce.txt').write_text(nonce+'\n')
    configuration=validate_offline_configuration(default_offline_configuration() if offline_configuration is None else offline_configuration)
    _write(destination/'offline_recovery.json',configuration)
    (destination/'run.py').write_text(_RUNNER)
    initial=inventory(destination)
    _write(destination/'public_inventory.json',{name:{k:record[k] for k in ('sha256','bytes')} for name,record in initial.items()})
    complete=inventory(destination)
    require(set(complete)==set(runtime['inventory'])|{'input.xlsx','instruction.md','public_nonce.txt','offline_recovery.json','run.py','public_inventory.json'},
        'The public replay bundle contains extra files')
    return complete


_INSPECT = ('{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"NanoCpus":{{.HostConfig.NanoCpus}},"Memory":{{.HostConfig.Memory}},'
    '"PidsLimit":{{.HostConfig.PidsLimit}},"NetworkMode":{{json .HostConfig.NetworkMode}},'
    '"Privileged":{{json .HostConfig.Privileged}},"CapDrop":{{json .HostConfig.CapDrop}},'
    '"CapAdd":{{json .HostConfig.CapAdd}},"SecurityOpt":{{json .HostConfig.SecurityOpt}},'
    '"Mounts":{{json .Mounts}},"State":{{json .State}},"Cmd":{{json .Config.Cmd}},'
    '"Entrypoint":{{json .Config.Entrypoint}},"WorkingDir":{{json .Config.WorkingDir}},'
    '"User":{{json .Config.User}},"MaxConcurrency":"{{range .Config.Env}}'
    '{{if eq (index (split . "=") 0) "MAX_CONCURRENCY"}}{{.}}{{end}}{{end}}"}')


def _read(record):
    from ..pipelines.linear_capital_quality import References
    return References().read(record)


def default_offline_configuration():
    return {'version':1,'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256,
        'max_concurrency':2,'solver_threads':16,'solver_seconds':3600,
        'replay_timeout_seconds':REPLAY_SECONDS,'image_id':IMAGE}


def validate_offline_configuration(value):
    require(type(value) is dict and set(value)==set(default_offline_configuration()),
        'Declare every offline public recovery resource and limit')
    require(all(type(value[key]) is int for key in value if key!='image_id')
        and value['version']==1 and 2<=value['cpus']<=16 and value['memory_bytes']==32*1024**3
        and value['pids_limit']==256 and value['max_concurrency']==2
        and 1<=value['solver_threads']<=value['cpus'] and 1<=value['solver_seconds']<=6900
        and value['replay_timeout_seconds']==REPLAY_SECONDS and value['image_id']==IMAGE,
        'Offline recovery resources/limits must be explicit, bounded and image-pinned')
    return deepcopy(value)


def _settings(ctx):
    from .resource_engine import load_runtime_profile
    setting=ctx.config[SETTING];recovery=ctx.config.get('recovery',{})
    require(type(setting.get('version')) is int and setting['version']==1 and setting.get('enabled') is True
        and setting.get('recovery')==reference(__file__), 'The explicit current linear recovery opt-in is required')
    require(recovery.get('compiler_backend')==BACKEND and type(recovery.get('replay_timeout_seconds')) is int
        and recovery['replay_timeout_seconds']==REPLAY_SECONDS, 'The public replay backend or operational guard changed')
    profile_ref=setting['runtime_profile'];require(reference(profile_ref['path'])==profile_ref,'The runtime profile changed')
    profile=load_runtime_profile(profile_ref['path'])
    require(profile['id']=='entity_group_large_v2' and profile['image']['id']==IMAGE
        and profile['docker_resources']['agent']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256},
        'The actual public replay requires pinned 2CPU/32GiB/PID256 resources')
    validate_offline_configuration(recovery['offline_public_recovery'])
    runtime_ref=recovery['public_runtime_preparation'];runtime=validate_public_runtime(runtime_ref)
    return profile,profile_ref,runtime_ref,runtime


def _source_binding(ctx):
    from ..task_adapters.linear_capital_portfolio import context_proof
    proof=context_proof(ctx);_,profile,_,_=_settings(ctx)
    require(proof['runtime_profile']==profile
        and ctx.data.get('finance_evidence',{}).get('financial_seed_verified') is True,
        'The replay must use the admitted financial source and profile')
    for name in ('input','goal'):
        require({k:reference(ctx.data[name])[k] for k in ('sha256','bytes')}
            == {k:proof[name][k] for k in ('sha256','bytes')}, 'The current public input or goal changed')
    return {key:proof[key] for key in ('source_manifest','workbook','runtime_profile',
        'view_manifest','view_plan','actual_validation_terminal','input','goal','full_D')}


def _command(ctx,directory,nonce):
    _settings(ctx);resources=validate_offline_configuration(ctx.config['recovery']['offline_public_recovery'])
    return ['docker','create','--name','sheetsfactory-linear-public-'+nonce,
        '--user','0','--network','none','--cap-drop','ALL','--cap-add','DAC_OVERRIDE',
        '--security-opt','no-new-privileges','--cpus',str(resources['cpus']),
        '--memory',str(resources['memory_bytes']),'--pids-limit',str(resources['pids_limit']),
        '--env','MAX_CONCURRENCY=2','--env','PYTHONDONTWRITEBYTECODE=1',
        '--volume',str(Path(directory).resolve())+':/app:rw','--workdir','/app',
        '--entrypoint','/usr/bin/python3',IMAGE,'-B','/app/run.py']


def _host_valid(actual,owned,directory,resources):
    resources=validate_offline_configuration(resources);mounts=actual.get('Mounts',[])
    return (type(owned) is str and re.fullmatch('[0-9a-f]{64}',owned) is not None
        and actual.get('Id')==owned and actual.get('Image')==IMAGE
        and type(actual.get('NanoCpus')) is int and actual['NanoCpus']==resources['cpus']*10**9
        and type(actual.get('Memory')) is int and actual['Memory']==resources['memory_bytes']
        and type(actual.get('PidsLimit')) is int and actual['PidsLimit']==resources['pids_limit']
        and actual.get('NetworkMode')=='none' and actual.get('Privileged') is False
        and actual.get('CapDrop')==['ALL'] and actual.get('CapAdd')==['CAP_DAC_OVERRIDE']
        and actual.get('SecurityOpt')==['no-new-privileges'] and actual.get('User')=='0'
        and actual.get('MaxConcurrency')=='MAX_CONCURRENCY=2'
        and actual.get('Entrypoint')==['/usr/bin/python3'] and actual.get('Cmd')==['-B','/app/run.py']
        and actual.get('WorkingDir')=='/app' and len(mounts)==1
        and mounts[0].get('Type')=='bind' and mounts[0].get('RW') is True
        and mounts[0].get('Source')==str(Path(directory).resolve()) and mounts[0].get('Destination')=='/app')


def _normal_container_state(actual, *, before):
    state=actual.get('State',{})
    return (type(state) is dict and state.get('Status')==('created' if before else 'exited')
        and state.get('Running') is False and state.get('OOMKilled') is False
        and type(state.get('ExitCode')) is int and state['ExitCode']==0)


def _execute_replay(ctx,directory,attempt,result):
    from ..core.audit import utcnow
    profile,profile_ref,_,_=_settings(ctx);replay=result['replay'];owned=None
    offline=validate_offline_configuration(ctx.config['recovery']['offline_public_recovery'])
    command=_command(ctx,directory,replay['nonce'])
    replay.update(command=command,runtime_profile=profile_ref,started_at=utcnow(),completed=False,
        operational_timeout_seconds=REPLAY_SECONDS,offline_recovery_resources=offline,
        model_runtime_profile=profile_ref,model_resources_claimed_verified=False,
        operational_replay_budget_is_model_tool_budget=False)
    _write(attempt/'replay_started.json',deepcopy(replay))
    try:
        created=subprocess.run(command,capture_output=True,text=True,timeout=30)
        _write(attempt/'create_result.json',{'returncode':created.returncode,'stdout':created.stdout,'stderr':created.stderr})
        require(created.returncode==0 and re.fullmatch('[0-9a-f]{64}',created.stdout.strip()),
            'Creation did not return a proven owned full container ID')
        owned=created.stdout.strip();replay['container_id']=owned
        def inspect_owned(name):
            observed=subprocess.run(['docker','inspect',owned,'--format',_INSPECT],capture_output=True,text=True,timeout=30)
            require(observed.returncode==0,'The owned replay cannot be inspected')
            actual=json.loads(observed.stdout);replay[name]=_write(attempt/(name+'.json'),actual)
            require(_host_valid(actual,owned,directory,offline),'Actual replay resources, MAX2 or public-only mount differ')
            return actual
        require(_normal_container_state(inspect_owned('host_before'),before=True),'Public container was not newly created')
        with (attempt/'replay.stdout').open('xb') as stdout,(attempt/'replay.stderr').open('xb') as stderr:
            done=subprocess.run(['docker','start','--attach',owned],stdout=stdout,stderr=stderr,timeout=REPLAY_SECONDS)
        replay['returncode']=done.returncode;actual=inspect_owned('host_after')
        require(done.returncode==0 and _normal_container_state(actual,before=False),'Public replay did not exit normally')
        final=inventory(directory)
        require(set(final)==set(replay['initial_files'])|set(GENERATED_FILES)
            and all(final[name]==record for name,record in replay['initial_files'].items()),
            'Public input, brief, code or nonce changed, or extra files appeared')
        replay.update(final_files=final,completed=True,actual_resources_verified=True,public_information_unchanged=True)
    finally:
        if owned is not None:
            try:
                done=subprocess.run(['docker','rm','--force',owned],capture_output=True,text=True,timeout=30)
                replay['cleanup']={'owned_full_id':owned,'returncode':done.returncode}
            except Exception as error:
                replay['cleanup']={'owned_full_id':owned,'returncode':None,'error_type':type(error).__name__}
        else:replay['cleanup_skipped_no_owned_container']=True
        replay['finished_at']=utcnow();replay['terminal']=_write(attempt/'replay_terminal.json',deepcopy(replay))
    require(replay.get('cleanup')=={'owned_full_id':owned,'returncode':0},'Owned public replay cleanup failed')


def _artifacts(ctx,result):
    directory=Path(result['replay']['directory']);attempt=Path(result['attempt_record_path']).parent
    return {**{'public/'+name:directory/name for name in result['replay']['final_files']},
        'host_before':attempt/'host_before.json','host_after':attempt/'host_after.json',
        'replay_terminal':attempt/'replay_terminal.json','replay_stdout':attempt/'replay.stdout',
        'replay_stderr':attempt/'replay.stderr','input_stability':attempt/'stability.json',
        'calculated_pass1':attempt/'calculated_pass1.xlsx','calculated_pass2':attempt/'recovered.xlsx',
        'recovered':ctx.revision_dir/'private/recovered.xlsx'}


def _binding(ctx,result):
    from ..nodes.quality import reference_revision_binding
    return {'version':1,'revision':reference_revision_binding(ctx),'source':_source_binding(ctx),
        'implementation':reference(__file__),'public_recipe':public_implementation_recipe(),
        'public_runtime_preparation':_settings(ctx)[2],
        'artifacts':{name:reference(path) for name,path in _artifacts(ctx,result).items()},
        'recalculations':result['recalculations']}


def _execution_valid(ctx,result):
    profile,profile_ref,runtime_ref,runtime=_settings(ctx);_source_binding(ctx)
    offline=validate_offline_configuration(ctx.config['recovery']['offline_public_recovery'])
    replay=result['replay'];directory=Path(replay['directory']);attempt=Path(result['attempt_record_path']).parent
    require(re.fullmatch('[0-9a-f]{32}',replay['nonce']) is not None
        and directory==ctx.revision_dir/('linear-recovery-replay-'+replay['nonce']), 'The public replay nonce/directory is stale')
    require(replay.get('completed') is True and replay.get('actual_resources_verified') is True
        and replay.get('public_information_unchanged') is True and type(replay.get('returncode')) is int
        and replay['returncode']==0 and replay['runtime_profile']==profile_ref
        and replay['command']==_command(ctx,directory,replay['nonce'])
        and replay.get('offline_recovery_resources')==offline
        and replay.get('model_runtime_profile')==profile_ref and replay.get('model_resources_claimed_verified') is False
        and replay.get('cleanup')=={'owned_full_id':replay['container_id'],'returncode':0},
        'A complete owned actual public replay is required')
    terminal=_read(replay['terminal'])
    require(terminal=={k:v for k,v in replay.items() if k!='terminal'},'The immutable replay terminal changed')
    initial=replay['initial_files'];final=inventory(directory)
    require(set(initial)==set(runtime['inventory'])|{'input.xlsx','instruction.md','public_nonce.txt','offline_recovery.json','run.py','public_inventory.json'}
        and set(final)==set(initial)|set(GENERATED_FILES) and final==replay['final_files']
        and all(final[name]==record for name,record in initial.items()),'The complete public-only file inventory changed')
    for name,record in runtime['inventory'].items():
        require({k:final[name][k] for k in ('sha256','bytes')}=={k:record[k] for k in ('sha256','bytes')},
            'The executed generic runtime differs from its preparation')
    require({k:final['input.xlsx'][k] for k in ('sha256','bytes')}=={k:reference(ctx.data['input'])[k] for k in ('sha256','bytes')}
        and (directory/'instruction.md').read_text()==ctx.data['instruction']
        and (directory/'public_nonce.txt').read_text()==replay['nonce']+'\n'
        and (directory/'run.py').read_text()==_RUNNER
        and json.loads((directory/'offline_recovery.json').read_text())==offline,
        'The held-out public input/brief/program/offline configuration changed')
    before,after=(_read(replay[name]) for name in ('host_before','host_after'))
    require(_host_valid(before,replay['container_id'],directory,offline)
        and _host_valid(after,replay['container_id'],directory,offline)
        and _normal_container_state(before,before=True) and _normal_container_state(after,before=False),
        'The actual before/after resources or normal process states differ')
    report=json.loads((directory/'public_recovery_report.json').read_text())
    parsed=parse_public_workbook(directory/'input.xlsx',instruction_path=directory/'instruction.md')
    require(report.get('kind')=='public_native_linear_capital_reconstruction' and report.get('passed') is True
        and report.get('public_financial_specification_sha256')==spec.canonical_sha256(parsed)
        and (report.get('project_count'),report.get('scenario_count'),report.get('year_count'))
            ==(len(parsed['project_ids']),len(parsed['scenario_ids']),len(parsed['years']))
        and report.get('checked_optimal') is True and report.get('all_standalone_feasible') is True
        and report.get('offline_solver')=={'threads':offline['solver_threads'],'time_limit_seconds':offline['solver_seconds']}
        and report.get('offline_recovery_is_model_attempt') is False
        and report.get('shared_Decimal_B') is True and report.get('shared_Excel_compiler') is True
        and report.get('third_independent_ledger') is False and report.get('second_independent_global_proof') is False,
        'The complete public reconstruction report is missing or overclaims independence')
    solved=json.loads((directory/'native_solver.json').read_text())
    require(solved.get('status')=='OPTIMAL' and solved.get('checked_optimal') is True
        and solved.get('exact_plan_check',{}).get('passed') is True
        and solved.get('objective_pence')==report['objective_pence']
        and solved.get('threads')==offline['solver_threads'] and solved.get('time_limit_seconds')==offline['solver_seconds'], 'The actual public solver did not prove a checked optimum')
    source=directory/'recovered.xlsx';calls=result['recalculations']
    require(len(calls)==2,'Two actual source-bound recalculations are required')
    session=ctx.data['_linear_admission'].source
    for index,(call,destination) in enumerate(zip(calls,(attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx')),1):
        require(call['index']==index and call['completed'] is True and call['input']==reference(source)
            and call['output']==reference(destination),'The recovered calculation chain changed')
        evidence=session.helper.validate_actual_call(call,call['actual_resource_evidence']['terminal'],
            {'runtime_profile':profile_ref,'runtime_profile_value':profile})
        require(evidence==call['actual_resource_evidence'],'Actual recovered MAX2/resources/file evidence changed')
        source=destination
    from .heterogeneous_contracts.validate import compare_typed_caches
    stable=json.loads((attempt/'stability.json').read_text())
    require(stable==compare_typed_caches(attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx')
        and stable.get('passed') is True and stable.get('entire_value_union_checked') is True
        and stable.get('typed_value_mismatches')==0 and stable.get('money_quantization_applied') is False,
        'The entire recovered typed union is unstable')
    return True


_WITNESSES = {}


def valid_linear_capital_recovery_witness(ctx,candidate):
    from ..pipelines.linear_capital_quality import References
    from ..evaluation.streaming_delta import compare_workbooks
    try:
        if type(candidate) is not dict or candidate.get('verified') is not True:return False
        require(candidate.get('task_revision_hash')==ctx.data.get('revision_hash')
            and candidate.get('usage_calls')==[] and candidate.get('usage_attribution')=='not_applicable_programmatic',
            'The recovery revision or model attribution differs')
        record=Path(candidate['attempt_record_path']);checksum=record.with_name('attempt.sha256')
        require(record.parent.parent==ctx.revision_dir/'private/recovery_attempts'
            and re.fullmatch('attempt_[0-9]{6}',record.parent.name) is not None
            and record==record.resolve() and checksum==checksum.resolve(),'The immutable attempt escaped its current revision')
        actual=reference(record);key=(str(record),actual['sha256'])
        if key in _WITNESSES:
            snapshot,refs,binding=_WITNESSES[key]
            require(candidate==snapshot,'The cached recovery candidate changed');refs.guard()
            require(binding==_binding(ctx,candidate),'The cached witness no longer binds the current revision')
            return True
        require(candidate.get('attempt_record_sha256')==actual['sha256'] and checksum.read_text().strip()==actual['sha256']
            and json.loads(record.read_text())=={k:v for k,v in candidate.items() if k!='attempt_record_sha256'},
            'The complete immutable recovery attempt/checksum changed')
        require(_execution_valid(ctx,candidate) and candidate.get('witness_binding')==_binding(ctx,candidate),
            'Current public replay execution/artifact evidence is incomplete')
        paths=_artifacts(ctx,candidate)
        require(reference(paths['calculated_pass2'])['sha256']==reference(paths['recovered'])['sha256'],
            'The canonical recovered copy differs')
        comparison=compare_workbooks(ctx.data['input'],ctx.data['goal'],paths['recovered'])
        require(comparison.get('reward')==1 and comparison==candidate.get('comparison'),
            'The actual complete recovered value set differs from the private verified goal')
        refs=References();refs.check(actual);refs.check(reference(checksum));refs.walk(candidate['witness_binding'])
        _WITNESSES[key]=(deepcopy(candidate),refs,deepcopy(candidate['witness_binding']))
        return True
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration):return False


from ..nodes.quality import RecoveryNode


class LinearCapitalRecoveryNode(RecoveryNode):
    node_id='independent_recovery'

    def execute(self,ctx):
        from ..core.audit import utcnow
        from ..core.node import CooperativeCancelled
        from ..nodes import quality as normal
        from ..evaluation.streaming_delta import compare_workbooks
        from .heterogeneous_contracts.validate import compare_typed_caches
        if ctx.config.get(SETTING) is None:return super().execute(ctx)
        require(normal.validate_reference_policy_selection(ctx.config)=='independent_public_recovery',
            'This explicit family requires actual public reconstruction')
        profile,profile_ref,runtime_ref,_=_settings(ctx);_source_binding(ctx)
        saved=ctx.revision_dir/'private/independent_recovery.json'
        if saved.is_file():
            candidate=json.loads(saved.read_text())
            if valid_linear_capital_recovery_witness(ctx,candidate):return {'recovery':candidate}
        history=ctx.revision_dir/'private/recovery_attempts';history.mkdir(parents=True,exist_ok=True)
        index=0
        while True:
            attempt=history/f'attempt_{index:06d}'
            try:attempt.mkdir(mode=0o700);break
            except FileExistsError:index+=1
        result={'public_information_only':True,'verified':False,'attempt_id':attempt.name,
            'attempt_record_path':str(attempt/'attempt.json'),'started_at':utcnow(),
            'task_revision_hash':ctx.data.get('revision_hash'),'compiler_backend':BACKEND}
        try:
            work=normal.prepare_workspace(ctx,'linear_recovery_public');result['workspace']=str(work)
            result['compiler']={'is_llm_attempt':False,'shared_Decimal_B':True,'shared_CP_SAT':True,
                'shared_Excel_compiler':True,'third_independent_ledger':False,'second_independent_global_proof':False,
                'public_recipe':public_implementation_recipe(),'assumptions_added':[],'unresolved_questions':[]}
            nonce=uuid.uuid4().hex;replay=ctx.revision_dir/('linear-recovery-replay-'+nonce)
            initial=prepare_public_bundle(ctx.data['input'],ctx.data['instruction'],runtime_ref,replay,nonce=nonce,
                offline_configuration=ctx.config['recovery']['offline_public_recovery'])
            result['replay']={'directory':str(replay),'nonce':nonce,'initial_files':initial,
                'returncode':None,'fresh_network_disabled_container':True}
            _execute_replay(ctx,replay,attempt,result)
            # The public process has exited and its owned container is cleaned
            # before the host is allowed to compare against the private goal.
            source=replay/'recovered.xlsx';calls=[]
            for index,destination in enumerate((attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'),1):
                before=len(ctx.engine.metadata().get('actual_resource_receipts',[]));clock=time.monotonic()
                call={'index':index,'input':reference(source),'started_at':utcnow(),'completed':False}
                _write(attempt/f'LO{index}_started.json',deepcopy(call))
                try:
                    actual=Path(ctx.engine.recalculate(source,destination))
                    require(actual.resolve()==destination.resolve(),'The recovery engine returned another output')
                    call.update(output=reference(destination),completed=True,elapsed_seconds=time.monotonic()-clock)
                    receipts=ctx.engine.metadata()['actual_resource_receipts'];require(len(receipts)==before+1,'An unrecorded calculation occurred')
                    helper=ctx.data['_linear_admission'].source.helper
                    call['actual_resource_evidence']=helper.validate_actual_call(call,receipts[-1],
                        {'runtime_profile':profile_ref,'runtime_profile_value':profile})
                finally:
                    call['finished_at']=utcnow();_write(attempt/f'LO{index}_terminal.json',deepcopy(call))
                    calls.append(call);result['recalculations']=calls
                source=destination
            _write(attempt/'stability.json',compare_typed_caches(attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'))
            require(_execution_valid(ctx,result),'Public replay resource/solver/stability evidence is incomplete')
            result['comparison']=compare_workbooks(ctx.data['input'],ctx.data['goal'],attempt/'recovered.xlsx')
            if result['comparison'].get('reward')==1:
                shutil.copyfile(attempt/'recovered.xlsx',ctx.revision_dir/'private/recovered.xlsx')
                result['witness_binding']=_binding(ctx,result);result['verified']=True
        except CooperativeCancelled:
            result.update(status='cancelled',error='Explicit cooperative stop; public recovery remains unverified');raise
        except Exception as error:
            result.update(error_type=type(error).__name__,error=str(error))
        finally:
            result.update(usage_calls=[],usage_attribution='not_applicable_programmatic',finished_at=utcnow())
            result.setdefault('status','verified' if result['verified'] else 'unverified')
            raw=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
            with (attempt/'attempt.json').open('xb') as handle:handle.write(raw)
            with (attempt/'attempt.sha256').open('x') as handle:handle.write(hashlib.sha256(raw).hexdigest()+'\n')
            (attempt/'attempt.json').chmod(0o444);(attempt/'attempt.sha256').chmod(0o444)
            result['attempt_record_sha256']=hashlib.sha256(raw).hexdigest();ctx.save('independent_recovery.json',result)
        return {'recovery':result}
