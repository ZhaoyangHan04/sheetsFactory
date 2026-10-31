"""Small/mocked admission boundaries; no production source verification or LO."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pytest

from sheets_factory.pipelines import sparse_capital_admission as a


def write(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')
    return a.reference(path)


def replace_cache(path, updates):
    with zipfile.ZipFile(path) as z:
        files = {name: z.read(name) for name in z.namelist()}
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    root = ET.fromstring(files['xl/worksheets/sheet1.xml'])
    for cell in root.findall('.//s:c', ns):
        if cell.get('r') in updates:
            v = cell.find('s:v', ns)
            if v is None: v = ET.SubElement(cell, '{'+ns['s']+'}v')
            v.text = str(updates[cell.get('r')])
    files['xl/worksheets/sheet1.xml'] = ET.tostring(root)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items(): z.writestr(name, content)


@pytest.fixture
def small_cache(tmp_path):
    book = openpyxl.Workbook(); f = book.active; f.title = 'F'
    f['A1'] = 7; f['A2'] = 'state'; f['A3'] = 'support'; f['A4'] = 'decision'; f['A5'] = date(2024,3,31)
    f['B2'] = '=A1+1'; f['B3'] = '=B2+1'; f['B4'] = '=1'
    rules = book.create_sheet('Rules')
    for i, rule in enumerate(a.excel.PUBLIC_RULES, 1): rules.cell(i,1,rule)
    contract = book.create_sheet('Contract'); contract['A2'] = 'JSON'; contract['B2'] = json.dumps({'rate':7})
    literals = []
    for sheet in book:
        for row in sheet:
            for cell in row:
                if cell.value is not None and cell.data_type != 'f':
                    value = cell.value
                    literals.append({'sheet':sheet.title,'cell':cell.coordinate,'kind':'date' if isinstance(value,date) else type(value).__name__,
                                     'value':value.isoformat() if isinstance(value,date) else value})
    path = tmp_path/'cache.xlsx'; book.save(path); book.close(); replace_cache(path, {'B2':8,'B3':9,'B4':1})
    bindings = {'sheet_names':['F','Rules','Contract'],
        'financial_bindings':[{'sheet':'F','cell':'B2','formula':'=A1+1'}],
        'arithmetic_bindings':[{'sheet':'F','cell':'B3','formula':'=B2+1'}],
        'decision_bindings':[{'sheet':'F','cell':'B4','project_id':'P01'}],
        'literal_bindings':literals,'input_bindings':[{'sheet':'F','cell':'A1','path':['rate']}],
        'public_spec_chunks':[{'sheet':'Contract','cell':'B2'}],
        'public_rule_cells':[{'sheet':'Rules','cell':f'A{i+1}'} for i in range(len(a.excel.PUBLIC_RULES))],
        'public_rules':list(a.excel.PUBLIC_RULES)}
    expected={a._address('F', cell):value for cell,value in [('B2',8),('B3',9),('B4',1)]}
    counts={'formula_count':3,'financial_formula_count':1,'provided_arithmetic_formula_count':1,'decision_formula_count':1}
    report={**counts,'checked_cells':3,'passed':True,'workbook_structure_verified':True,
        'all_formula_cells_independently_covered':True,'all_scenarios_feasible':True,'all_journals_balance':True,
        'optimality_or_uniqueness_certified':False,'mismatches':[],'control_mismatches':[],
        'cell_checks':[{'address':key,'expected_independent':value,'observed':value,'matched':True,'formula_matches':True} for key,value in expected.items()]}
    return path, {'rate':7}, {'P01':1}, bindings, expected, report, counts


def audit(case):
    return a._audit_cache_pass(*case)


def test_actual_small_formula_cache_and_typed_public_literal_reading(small_cache):
    observed = audit(small_cache)
    assert observed['F','B2'] == ('number',8) and observed['F','A5'] == ('date','2024-03-31')
    assert len(observed) == len(small_cache[3]['literal_bindings'])+3


@pytest.mark.parametrize('change', ['wrong_cache','wrong_formula','extra_literal','bad_expected','bad_observed',
    'duplicate_check','missing_check','bool_expected','false_pass','wrong_public','wrong_rule','missing_literal','wrong_count'])
def test_actual_cache_binding_is_not_just_report_flags(small_cache, change):
    path,public,plan,bindings,expected,report,counts=small_cache
    if change=='wrong_cache': replace_cache(path,{'B2':999})
    if change in ('wrong_formula','extra_literal','wrong_rule'):
        book=openpyxl.load_workbook(path)
        if change=='wrong_formula':book['F']['B2']='=666'
        if change=='extra_literal':book['F']['C10']=99
        if change=='wrong_rule':book['Rules']['A1']='Changed business rule'
        book.save(path);book.close();replace_cache(path,{'B2':8,'B3':9,'B4':1})
    if change=='bad_expected':report['cell_checks'][0]['expected_independent']=999
    if change=='bad_observed':report['cell_checks'][0]['observed']=999
    if change=='duplicate_check':report['cell_checks'][1]=deepcopy(report['cell_checks'][0])
    if change=='missing_check':report['cell_checks'].pop()
    if change=='bool_expected':report['cell_checks'][-1]['expected_independent']=True
    if change=='false_pass':report['passed']=False
    if change=='wrong_public':public['rate']=8
    if change=='missing_literal':bindings['literal_bindings'].pop()
    if change=='wrong_count':report['formula_count']=2
    with pytest.raises((ValueError,KeyError)):audit(small_cache)


def test_same_workbook_bytes_at_another_path_are_accepted(small_cache,tmp_path):
    other=tmp_path/'copied_goal.xlsx';shutil.copyfile(small_cache[0],other)
    assert a._same(a.reference(other),a.reference(small_cache[0]))
    assert audit((other,*small_cache[1:]))==audit(small_cache)


@pytest.mark.parametrize('n,expected',[(40,97323),(48,113171),(56,129019)])
def test_dynamic_full_formula_scope_never_truncates_to_old_dimension(n,expected):
    counts=a._counts(n)
    assert counts['formula_count']==expected==1981*n+18083
    assert counts['formula_count']==sum(counts[key] for key in ('financial_formula_count','provided_arithmetic_formula_count','decision_formula_count'))


def test_live_session_is_opaque_cannot_be_supplied_as_a_dictionary(tmp_path):
    with pytest.raises(ValueError):a._state({'references':{},'proofs':set()})
    session=a.AdmissionSession()
    with pytest.raises(AttributeError):session._checked={}
    path=tmp_path/'artifact';path.write_text('original');ref=a.reference(path)
    a._check(ref,session);path.write_text('changed')
    with pytest.raises(ValueError,match='changed'):a._check(ref,session)


@pytest.fixture
def resource_case(tmp_path):
    session=a.AdmissionSession();profile_ref=a._ref(a.DEFAULT_PROFILE,session)
    profile=a.resource_engine.load_runtime_profile(profile_ref['path'])
    raw=tmp_path/'raw';raw.write_bytes(b'raw');previous=a.reference(raw)
    calls=[];receipts=[]
    for index in range(1,4):
        out=tmp_path/f'pass{index}';out.write_bytes(f'pass{index}'.encode());output=a.reference(out)
        calls.append({'index':index,'input':previous,'output':output,'elapsed_seconds':8.0,'completed':True})
        req=profile['docker_resources']['source']
        receipt={'kind':'resource_bound_libreoffice_call','version':1,'status':'completed','role':'source',
            'profile':profile_ref,'profile_canonical_sha256':a.spec.canonical_sha(profile),'image_id':profile['image']['id'],
            'source':previous,'output':output,'destination':output['path'],'implementation':a._ref(a.resource_engine.__file__,session),
            'requested_resources':req,'actual_resources_verified':True,
            'actual_resources':{'cpus_nanoseconds':req['cpus']*10**9,'memory_bytes':req['memory_bytes'],'pids_limit':req['pids_limit']},
            'container_id':format(index,'064x'),'workbook_file_timeout_seconds':600,'verifier_total_timeout_seconds':2400,
            'solver_tool_budget':profile['solver_tool_budget'],
            'create_command':['docker','create','--memory',str(req['memory_bytes']),'--cpus',str(req['cpus']),'--pids-limit',str(req['pids_limit']),
                              '--network','none',profile['image']['id'],'/tmp/source.xlsx','/tmp/result.xlsx'],
            'started_at':'2026-10-31T01:00:00+00:00','finished_at':'2026-10-31T01:00:08+00:00'}
        receipts.append(write(tmp_path/f'resource{index}.json',receipt));previous=output
    prototype={'actual_LO_calls':calls,'workbook':calls[0]['output'],'runtime':{'actual_resource_receipts':receipts,
        'image_id':profile['image']['id'],'runtime_profile':profile,'runtime_profile_binding':profile_ref,
        'backend':'libreoffice_uno_docker','role':'source','network':'none','macro_execution':'never','external_updates':'never',
        'actual_calculation_calls_recorded':3}}
    return prototype,profile_ref,profile,session


def test_three_explicit_real_resource_receipt_shapes_and_exact_chains(resource_case):
    assert len(a._resource_calls(*resource_case))==3


@pytest.mark.parametrize('change',['two_passes','wrong_chain','resource_cpu','resource_ram','resource_image','resource_destination',
    'role','profile','network','false_completed','bad_timeout','command_ram'])
def test_resource_metadata_disagreements_fail_closed(resource_case,tmp_path,change):
    prototype,profile_ref,profile,session=resource_case
    if change=='two_passes':prototype['actual_LO_calls'].pop()
    elif change=='wrong_chain':prototype['actual_LO_calls'][2]['input']=prototype['actual_LO_calls'][0]['input']
    elif change=='false_completed':prototype['actual_LO_calls'][0]['completed']=False
    else:
        old=prototype['runtime']['actual_resource_receipts'][0];d=json.loads(Path(old['path']).read_text())
        if change=='resource_cpu':d['actual_resources']['cpus_nanoseconds']=10**9
        if change=='resource_ram':d['actual_resources']['memory_bytes']=2*1024**3
        if change=='resource_image':d['image_id']='sha256:'+'0'*64
        if change=='resource_destination':d['destination']='wrong'
        if change=='role':d['role']='agent'
        if change=='profile':d['profile_canonical_sha256']='0'*64
        if change=='network':d['create_command'][d['create_command'].index('--network')+1]='bridge'
        if change=='bad_timeout':d['workbook_file_timeout_seconds']=180
        if change=='command_ram':d['create_command'][d['create_command'].index('--memory')+1]='2147483648'
        prototype['runtime']['actual_resource_receipts'][0]=write(tmp_path/f'{change}.json',d)
    with pytest.raises((ValueError,KeyError)):a._resource_calls(prototype,profile_ref,profile,session)


@pytest.fixture
def reference_case(tmp_path,monkeypatch):
    public={'projects':[{'id':f'P{i:02}'} for i in range(1,41)]};canonical=a.spec.canonical_sha(public)
    path=tmp_path/'artifact';path.write_bytes(b'evidence');ref=a.reference(path)
    def rank(mask,value):return {'mask_hex':'0x'+format(mask,'016x'),'objective_pence':str(value),'scenario_npvs_pence':{sid:str(value) for sid in a.spec.SCENARIO_IDS}}
    best,runner=rank(3,3000),rank(1,2000)
    projection={'public_spec_sha256':canonical,'project_count':40,'masks':ref,'claimed_outcomes':ref,
        'counts':{'leaves':'4','regions':'42','bound':'0','infeasible':'38'},'best':best,'runnerup':runner,'partition':ref}
    opposite={'checks_partition_backend':'A','row_count':'4','outcomes':ref}
    summary={'kind':'sparse_capital_A_intermediate_search','status':'completed_intermediate','partition_coverage_complete':True,
        'stop_reason':'','project_count':40,'covered_plan_count':str(1<<40),'combinatorial_plan_count':str(1<<40),
        'best':best,'runnerup':runner,'emitted_regions':'42','bound_regions':'0','infeasible_regions':'38'}
    completion={'native_exit_code':0,'native_summary':summary,'partition':ref}
    completion_ref=write(tmp_path/'completion.json',completion);summary_ref=write(tmp_path/'summary.json',summary)
    started={'public_spec_sha256':canonical,'opposite_financial_core':'B','complete_native_execution':completion_ref,'native_summary':summary_ref}
    decimals={}
    for name,r in [('best',best),('runnerup',runner)]:
        plan={p['id']:int(bool(int(r['mask_hex'],16)&(1<<i))) for i,p in enumerate(public['projects'])}
        decimals[name]={'plan':plan,'feasible':True,'objective_pence':int(r['objective_pence']),
            'scenarios':{sid:{'feasible':True,'npv_pence':int(r['objective_pence']),'all_journals_balance':True} for sid in a.spec.SCENARIO_IDS}}
    proof={'kind':'complete_sparse_capital_semantic_reference_proof','version':1,'passed':True,'complete':True,
        'two_complete_independent_searches_claimed':False,'public_spec_sha256':canonical,'project_count':40,
        'complete_plan_count':str(1<<40),'native_projection':ref,'opposite_B_all_leaf_execution':ref,'best':best,'runnerup':runner,
        'actual_partition_regions':'42','actual_financial_leaves':'4','gap_pence':'1000','actual_A_native_completion':completion_ref,
        'started':write(tmp_path/'started.json',started),'independent_Decimal':{name:write(tmp_path/(name+'.json'),value) for name,value in decimals.items()}}
    calls=[]
    monkeypatch.setattr(a.streamed_native,'validate_execution',lambda value:(calls.append(('native',value)) or deepcopy(projection)))
    def opposite_validator(value,**kwargs):calls.append(('opposite',kwargs));return deepcopy(opposite)
    monkeypatch.setattr(a.check_masks,'validate_execution',opposite_validator)
    monkeypatch.setattr(a,'_search_resources',lambda *args:None)
    monkeypatch.setattr(a.spec,'plan_from_mask_hex',lambda _,mask:deepcopy(decimals['best' if mask==best['mask_hex'] else 'runnerup']['plan']))
    monkeypatch.setattr(a.ledger,'simulate',lambda _,plan:deepcopy(decimals['best' if plan==decimals['best']['plan'] else 'runnerup']))
    return public,proof,projection,opposite,calls


def test_full_reference_requires_both_actual_validators_and_same_all_leaf_stream(reference_case):
    public,proof,projection,opposite,calls=reference_case
    a._reference_proof(public,proof,{},a.AdmissionSession())
    assert calls[0][0]=='native' and calls[1]==('opposite',{'expected_core':'B','expected_public_sha':a.spec.canonical_sha(public),'expected_masks':projection['masks']})


@pytest.mark.parametrize('change',['partial','wrong_scope','leaf_count','outcome_sha','outcome_bytes','rank','gap','tie','duplicate_rank','decimal_mismatch'])
def test_outer_flags_cannot_override_cross_validator_or_exact_rank_mismatch(reference_case,change,tmp_path):
    public,proof,projection,opposite,_=reference_case
    if change=='partial':proof['complete']=False
    if change=='wrong_scope':projection['public_spec_sha256']='0'*64
    if change=='leaf_count':opposite['row_count']='3'
    if change=='outcome_sha':opposite['outcomes']={**opposite['outcomes'],'sha256':'0'*64}
    if change=='outcome_bytes':opposite['outcomes']={**opposite['outcomes'],'bytes':1}
    if change=='rank':projection['best']=deepcopy(proof['runnerup'])
    if change=='gap':proof['gap_pence']='999'
    if change=='tie':proof['runnerup']['objective_pence']='3000'
    if change=='duplicate_rank':proof['runnerup']['mask_hex']=proof['best']['mask_hex']
    if change=='decimal_mismatch':
        v=json.loads(Path(proof['independent_Decimal']['best']['path']).read_text());v['objective_pence']=7
        proof['independent_Decimal']['best']=write(tmp_path/'wrong_decimal.json',v)
    with pytest.raises((ValueError,KeyError)):a._reference_proof(public,proof,{},a.AdmissionSession())


def test_failed_inner_verifier_propagates_despite_outer_complete_flags(reference_case,monkeypatch):
    public,proof,*_=reference_case
    def failed(*args,**kwargs):raise ValueError('incomplete actual opposite checker')
    monkeypatch.setattr(a.check_masks,'validate_execution',failed)
    with pytest.raises(ValueError,match='incomplete actual opposite'):a._reference_proof(public,proof,{},a.AdmissionSession())


@pytest.fixture
def coupled_outer(tmp_path,monkeypatch):
    # Explicit component mocks isolate coupling/session behavior. No fixture
    # represents an actual source, native proof, Docker call or qualification.
    public={'projects':[{'id':f'P{i:02}'} for i in range(1,41)]}
    public_ref=write(tmp_path/'public.json',public)
    goal=tmp_path/'goal.xlsx';goal.write_bytes(b'unit-test placeholder, not a workbook')
    goal_ref=a.reference(goal);copy=tmp_path/'copied_goal.xlsx';shutil.copyfile(goal,copy)
    small=write(tmp_path/'private_evidence.json',{'mock':True})
    profile_ref=a.reference(a.DEFAULT_PROFILE)
    source={'public_specification':public_ref,'workbook':a.reference(copy),'runtime_profile':profile_ref,
        'bindings':small,'financial_audits':[],'stability':small,'runtime':{'role':'source'}}
    source_ref=write(tmp_path/'source.json',source)
    source_copy=tmp_path/'source_copy.json';shutil.copyfile(source_ref['path'],source_copy)
    best={'mask_hex':'0x0000000000000001','objective_pence':'2','scenario_npvs_pence':{sid:'2' for sid in a.spec.SCENARIO_IDS}}
    runner={**deepcopy(best),'mask_hex':'0x0000000000000000','objective_pence':'1'}
    proof={'profile_id':'40-J01','financial_workbook_prototype':source_ref,'financial_workbook':goal_ref,
        'best':best,'runnerup':runner,'gap_pence':'1','native_projection':small,
        'opposite_B_all_leaf_execution':small,'independent_Decimal':{'best':small,'runnerup':small}}
    proof_ref=write(tmp_path/'proof.json',proof)
    monkeypatch.setattr(a.spec,'load_spec',lambda value:deepcopy(value))
    calls=[]
    def reference(public,proof,profile,session):
        calls.append('reference')
        return {'counts':{'regions':'42'}},{'row_count':'4'},{'best':{'plan':{'P01':1}}}
    def financial(*args):calls.append('financial');return a._counts(40)
    monkeypatch.setattr(a,'_reference_proof',reference)
    monkeypatch.setattr(a,'_financial_source',financial)
    return public_ref,proof_ref,a.reference(source_copy),source,calls


def test_outer_source_copy_path_coupling_and_no_task_qualification(coupled_outer):
    public,proof,source,prototype,calls=coupled_outer
    admitted=a.admit_source(public,proof,source)
    assert calls==['reference','financial']
    assert admitted['source']==prototype['workbook'] and admitted['physical_formula_count']==97323
    assert admitted['one_complete_prefix_and_opposite_all_leaf_reference_verified'] is True
    assert admitted['actual_three_pass_financial_source_verified'] is True
    assert all(admitted[key] is False for key in ('two_complete_independent_searches_claimed','task_quality_certified',
        'independent_public_recovery_certified','Harbor_certified','difficulty_certified','qualified'))
    assert admitted['task_count']==0


def test_live_session_only_reuses_exact_previously_verified_admission(coupled_outer,monkeypatch):
    public,proof,source,_,calls=coupled_outer
    session=a.AdmissionSession();admitted=a.admit_source(public,proof,source,session=session)
    def prohibited(*args,**kwargs):raise ValueError('full read-only admission required')
    monkeypatch.setattr(a,'admit_source',prohibited)
    assert a.verify_admitted_source(admitted,session=session)==admitted
    altered=deepcopy(admitted);altered['qualified']=True
    with pytest.raises(ValueError,match='admission required'):a.verify_admitted_source(altered,session=session)
    with pytest.raises(ValueError,match='admission required'):a.verify_admitted_source(admitted,session=a.AdmissionSession())
    assert calls==['reference','financial']


def test_caller_json_cache_or_wrong_public_artifact_never_skips_full_coupling(coupled_outer,tmp_path):
    public,proof,source,_,calls=coupled_outer
    with pytest.raises(ValueError,match='internal live'):a.admit_source(public,proof,source,session={'verified_artifacts':{}})
    changed=write(tmp_path/'wrong_public.json',{'projects':[]})
    with pytest.raises(ValueError,match='cross-binding differs'):a.admit_source(changed,proof,source)
    assert calls==[]


def test_boolean_schema_version_is_not_an_integer_admission_version(coupled_outer):
    public,proof,source,_,_=coupled_outer
    session=a.AdmissionSession();admitted=a.admit_source(public,proof,source,session=session)
    admitted['version']=True
    with pytest.raises(ValueError,match='complete sparse source'):a.verify_admitted_source(admitted,session=session)
